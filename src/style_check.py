"""AI 体例质检引擎（FX-25）—— 规范 ②组「AI 体例质检挂钩」的执行与记录面。

背景：规范 §5 质检通道＋§8 一致性四防线之三（AI 体例质检）—— style.yaml
（词典层体例硬准绳）此前只有「在场＋style_version」在场检（dict_admin_pages
G6 体例终检），没有可重复执行的机械质检与执行记录，协同度量五指标（FX-19）
的「体例质检通过率」因此无数据源灰注。本模块把质检引擎与记录面建起来：
``run_style_check`` 逐项机械检查 → 结果落 ``style_check_runs`` →
``collab_metrics.style_check_status`` 取数出真值（出版导出/驾驶舱的 UI 入口
归下一批，本模块只做引擎＋记录＋指标接线）。

检查项清单（code / rule / 判定 / 数据源）—— 全部**机械可验证**，从
configs/style.yaml 实际键出发（style_version / defining_vocab /
substitution_test / sense_ordering / microstructure / multimedia），不发明
语言学语义：「待编者核定」等占位值按其字面含义如实判 fail/warn，不猜数值：

  ==================  ===========================  ==============================  =========================
  code                rule（检查什么）              判定                            数据源
  ==================  ===========================  ==============================  =========================
  CFG_COMPLETE        配置完备性：六件套必备键齐备  缺键 → fail（逐键列名）；        style.yaml（候选路径见
                      （style_version＋五规则键）   全齐 → pass                      ``_style_yaml_candidates``）
  DEFINING_VOCAB      定义词表非空且无重复词条      空 → fail；重复 → fail；         style.yaml defining_vocab
                      （词表规模 <10 → warn）       词表本体未配置 → fail            （words 键或 vocab_file）
  SENSE_ORDERING      声明的排序规则键合法          primary 不含合法枚举词 → fail；  style.yaml sense_ordering
                      （枚举：原型梯度/频次）        未声明/非映射 → fail             ＋规范 §6 两类排序规则
  MICROSTRUCTURE_     microstructure 声明键与       映射键缺 spine 段 → fail；       style.yaml microstructure
  SPINE               sense_spine 七段面一致性      spine 不可比对 → warn「自        ＋ sense_spine._spine_sections
                      （只对照声明键集合是否被       动化比对未覆盖」                 （只读调用，sid=0 走
                      spine 实现面覆盖）                                             无 DB 的固定七段分支）
  MULTIMEDIA_         multimedia 位规则与媒体       图注必配而有空图注 → fail；      style.yaml multimedia
  BINDINGS            绑定抽查（图注 caption、      许可闸而空许可 → fail；          ＋ media_bindings×media_assets
                      许可 license_gate）           无绑定/查询不可用 → warn         （只读 JOIN 抽查）
  ==================  ===========================  ==============================  =========================

模块纪律（同 collab_metrics / ai_ledger / media_db 口径）：
  1. 通过率口径（collab_metrics 引用同文案，单一事实源在本 docstring）::
        pass_rate = passed / (passed + failed)
     warn 单列（计入 total，不入分子也不入分母 —— 警告是「自动化比对未
     覆盖/暂无数据可检」类观察项，不是体例违例）；passed+failed=0 →
     pass_rate=None（「还没有可比项」≠ 0%，ai_ledger 同口径）。
  2. 结果落 style_check_runs 一行：passed/failed/warned/total 四计数列＋
     detail_json（逐项数组 ``[{code, rule, status, detail}]``）。status ∈
     {pass, fail, warn}；ok 表达的是**执行是否成功**（有 run 记录即
     ok=True），质检是否通过看逐项 status 与通过率。
  3. 权限闸（guards 既有模式）：显式 ``actor`` 过
     ``guards.require_role(actor, allowed={"dict_admin"})``（非词典管理员
     抛 PermissionError，调用方转 st.error）；``actor=None`` = 系统作业
     （脚本/定时任务）照 RV2-3 留痕列第 1 类口径放行、run_by 落 NULL ——
     引擎是库函数非 HTTP 面，交互面调用必须显式传 actor（页面层
     ``guards.require_dict_admin()`` 取得后传入），系统作业由调用点自证。
  4. 降级（R4 归因口径，不崩不编数）：style.yaml 缺失/不可解析、数据库
     不可用 → 返回 ok=False ＋ reason 文案（run_id=None、计数 0、items
     空），不写半行记录。
  5. SQL 一律参数化（查询文本全是常量，无一处值拼接）；对 media 两表
     只读（自建 SELECT，不改其表结构与数据）。
  6. yaml/sense_spine 运行时 import（category_pack 同款）：体例质检可
     独立触达，不拖累 collab_metrics 等轻依赖消费方的导入链。
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.db_utils import as_int as _as_int
from src.guards import require_role
from src.mysql_db import STYLE_CHECK_RUNS_TABLE_SQL, get_db_cursor

logger = logging.getLogger(__name__)

# ============================================
# 常量（口径单一事实源）
# ============================================

# 体例六件套必备键（configs/style.yaml 实际顶层键；style_version 是 G6 体例
# 终检的在场硬检字段，其余五键是五条体例规则的声明区）。
REQUIRED_STYLE_KEYS: Tuple[str, ...] = (
    "style_version", "defining_vocab", "substitution_test",
    "sense_ordering", "microstructure", "multimedia",
)

# 定义词表规模 warn 阈值（<10 warn「词表偏小」；学习词典通行量级 2000–3000，
# 试点阶段先以 10 为机械下限 —— 只做规模观察，不判语言学充分性）。
MIN_VOCAB_SIZE = 10

# sense_ordering 合法排序规则枚举（规范 §6「义项排列：原型梯度为主/频次校验」
# 两类 —— style.yaml 头注同源；机械匹配声明文本中的枚举词，不做语义裁判）。
SENSE_ORDERING_ENUM: Tuple[str, ...] = ("原型梯度", "频次")

# microstructure 声明键 → spine 七段面标题关键词的机械映射（只纳入 spine 实现
# 面真正承载的键；bracket_note/usage_note 等编纂成文层构件由工序 13–14 渲染面
# 承载，不在 spine 七段内 → 不入映射，检查时如实列「未纳入比对」）。
MICROSTRUCTURE_SPINE_MAP: Dict[str, Tuple[str, ...]] = {
    "custom_attributes": ("定制属性",),   # spine ⑦ 定制属性（custom_values）
}
SPINE_SECTION_COUNT = 7                 # 七段脊柱（sense_spine._spine_sections）

# 多模态抽查只读 SQL（media_bindings×media_assets；caption 空串=应用层显式
# 「无内容」，license 空串=无许可 —— D⑥ 许可纪律的机械违例信号）。
_MEDIA_SPOT_CHECK_SQL = (
    "SELECT COUNT(*) AS total_binds, "
    "COALESCE(SUM(b.purpose = 'example_media' AND TRIM(COALESCE(b.caption, '')) = ''), 0) "
    "  AS empty_caption, "
    "COALESCE(SUM(TRIM(COALESCE(a.license, '')) = ''), 0) AS empty_license "
    "FROM media_bindings b JOIN media_assets a ON a.id = b.asset_id"
)

# 仓库根与 configs 根（Path 版；测试 monkeypatch _CONFIGS_ROOT 指向临时 configs）
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIGS_ROOT = _REPO_ROOT / "configs"


def _style_yaml_candidates(category: str) -> List[Path]:
    """范畴体例文件候选路径（category 级优先，回退词典层与历史在场路径）。

    configs/<category>/style.yaml 是范畴级体例（本引擎的主数据源）；仓库当前
    只有词典层 configs/style.yaml（G6 体例终检同款候选路径 dict_admin_pages
    _STYLE_YAML_CANDIDATES），故 category 级缺席时回退词典层文件 —— 范畴级
    文件研制后自然接管，引擎零改动。
    """
    safe = str(category).strip()
    candidates: List[Path] = []
    if safe:
        candidates.append(_CONFIGS_ROOT / safe / "style.yaml")
    candidates.extend([
        _CONFIGS_ROOT / "style.yaml",
        _REPO_ROOT / "config" / "style.yaml",
        _REPO_ROOT / "data" / "style.yaml",
        _REPO_ROOT / "style.yaml",
    ])
    return candidates


def load_style_config(
    category: str,
) -> Tuple[Optional[Dict[str, Any]], str, Optional[str]]:
    """读范畴体例配置。返回 ``(style, path, error)``；error 非 None 表示
    缺失/解析失败/顶层非映射（R4 归因文案直接可用）。

    yaml 只用 safe_load（§6-6）；候选路径见 ``_style_yaml_candidates``。
    """
    candidates = _style_yaml_candidates(category)
    existing = [str(p) for p in candidates if p.is_file()]
    if not existing:
        return None, "", (
            "style.yaml 不在场（候选路径均未检出："
            + "、".join(str(p) for p in candidates)
            + "）—— 体例文件未研制，无从质检"
        )
    path = candidates[0] if candidates[0].is_file() else Path(existing[0])
    try:
        import yaml  # category_pack 同款运行时 import

        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception as exc:  # noqa: BLE001 —— 解析失败要带原因归因
        return None, str(path), f"style.yaml 解析失败（{path}）: {exc}"
    if not isinstance(data, dict):
        return None, str(path), (
            f"style.yaml 顶层必须是映射（dict），实际为 {type(data).__name__}（{path}）"
        )
    return data, str(path), None


# ============================================
# 纯函数检查项（前四项；每项返回 {code, rule, status, detail}）
# ============================================
def _item(code: str, rule: str, status: str, detail: str) -> Dict[str, str]:
    """单条检查结果（status ∈ pass/fail/warn；字段名即 style_check_runs
    detail_json 数组元素契约）。"""
    return {"code": code, "rule": rule, "status": status, "detail": detail}


def check_config_complete(style: Dict[str, Any]) -> Dict[str, str]:
    """① CFG_COMPLETE 配置完备性：六件套必备键齐备（缺 → fail 逐键列名）。"""
    rule = "体例六件套必备键齐备（style_version＋五规则键，缺一即 fail）"
    missing = [k for k in REQUIRED_STYLE_KEYS if k not in style]
    if missing:
        present = [k for k in REQUIRED_STYLE_KEYS if k in style]
        return _item(
            "CFG_COMPLETE", rule, "fail",
            f"缺必备键：{'、'.join(missing)}"
            f"（在场 {len(present)}/{len(REQUIRED_STYLE_KEYS)} 键："
            f"{'、'.join(present) if present else '无'}）",
        )
    return _item(
        "CFG_COMPLETE", rule, "pass",
        f"六件套键齐备：{'、'.join(REQUIRED_STYLE_KEYS)}",
    )


def _extract_vocab_words(
    defining_vocab: Any, search_dirs: List[Path]
) -> Tuple[List[str], str]:
    """从 defining_vocab 声明提取词表本体（机械：只认 words 列表与
    vocab_file 文件两条来源）。返回 ``(words, source_note)``；提取不到返回
    空列表＋原因（「待编者核定」占位按其字面含义如实上报，不编词表）。

    vocab_file 相对路径依次在 ``search_dirs``（style.yaml 所在目录 → 其
    上级 configs 目录 → 仓库根）解析，首个落盘者胜。
    """
    if isinstance(defining_vocab, list):        # 词表直接以列表声明
        words = [str(w).strip() for w in defining_vocab if str(w).strip()]
        return words, "defining_vocab 内联词表"
    if not isinstance(defining_vocab, dict):
        return [], f"defining_vocab 类型非映射/列表（{type(defining_vocab).__name__}）"
    words_decl = defining_vocab.get("words")
    if isinstance(words_decl, list):
        words = [str(w).strip() for w in words_decl if str(w).strip()]
        return words, "defining_vocab.words 内联词表"
    vocab_file = defining_vocab.get("vocab_file")
    if isinstance(vocab_file, str) and vocab_file.strip():
        name = vocab_file.strip()
        vf = Path(name)
        if vf.is_absolute():
            if vf.is_file():
                return _read_vocab_file(vf, name)
        else:
            for base in search_dirs:
                candidate = base / vf
                if candidate.is_file():
                    return _read_vocab_file(candidate, name)
        return [], (
            f"vocab_file 未落盘（vocab_file={name!r} —— 「待编者核定」"
            "类占位按未配置处理）"
        )
    return [], "词表本体未声明（无 words 列表、无 vocab_file）"


def _read_vocab_file(path: Path, declared: str) -> Tuple[List[str], str]:
    """读词表文件（每行一词；空行与 # 注释行跳过）。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], f"vocab_file 读取失败（{declared}）: {exc}"
    words = [
        line.strip() for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]
    return words, f"vocab_file 词表文件（{declared}）"


def check_defining_vocab(
    style: Dict[str, Any], search_dirs: Optional[List[Path]] = None
) -> Dict[str, str]:
    """② DEFINING_VOCAB 定义词表：非空且无重复词条（空/重复 → fail；
    词表规模 <10 → warn「词表偏小」）。重复判定按词条文本 strip＋casefold
    （英文定义词表大小写不敏感计重），机械无例外。"""
    rule = ("定义词表非空、无重复词条（空/重复 → fail；"
            f"词表规模 <{MIN_VOCAB_SIZE} → warn 词表偏小）")
    if "defining_vocab" not in style:
        return _item("DEFINING_VOCAB", rule, "fail", "defining_vocab 键未声明")
    dirs = search_dirs if search_dirs is not None else [_REPO_ROOT]
    words, source_note = _extract_vocab_words(style["defining_vocab"], dirs)
    if not words:
        return _item(
            "DEFINING_VOCAB", rule, "fail",
            f"定义词表为空（{source_note}）—— 词表本体待编者核定后随 "
            "style.yaml 入 git",
        )
    seen: set = set()
    dup_keys: set = set()
    dup_tokens: List[str] = []
    for word in words:
        key = word.casefold()
        if key in seen and key not in dup_keys:
            dup_keys.add(key)
            dup_tokens.append(word)
        seen.add(key)
    if dup_tokens:
        shown = "、".join(dup_tokens[:10]) + ("…" if len(dup_tokens) > 10 else "")
        return _item(
            "DEFINING_VOCAB", rule, "fail",
            f"词表重复词条：{shown}（共 {len(dup_tokens)} 个重复词；"
            f"词表来源 {source_note}，总词条 {len(words)}）",
        )
    unique = len(seen)
    if unique < MIN_VOCAB_SIZE:
        return _item(
            "DEFINING_VOCAB", rule, "warn",
            f"词表偏小：仅 {unique} 词（<{MIN_VOCAB_SIZE}；词表来源 {source_note}）"
            "—— 试点阶段观察项，不判语言学充分性",
        )
    return _item(
        "DEFINING_VOCAB", rule, "pass",
        f"词表 {unique} 词、无重复（词表来源 {source_note}）",
    )


def check_sense_ordering(style: Dict[str, Any]) -> Dict[str, str]:
    """③ SENSE_ORDERING 排序规则键合法：primary 声明须命中合法枚举
    （原型梯度/频次 —— 规范 §6 两类；枚举外值 → fail）。机械词面匹配，
    不裁判语言学派序优劣。"""
    rule = (
        "sense_ordering.primary 声明的排序规则键合法"
        f"（枚举：{'/'.join(SENSE_ORDERING_ENUM)}；枚举外值 → fail）"
    )
    if "sense_ordering" not in style:
        return _item(
            "SENSE_ORDERING", rule, "fail",
            "sense_ordering 键未声明（义项排列规则无从核验）",
        )
    so = style["sense_ordering"]
    if not isinstance(so, dict):
        return _item(
            "SENSE_ORDERING", rule, "fail",
            f"sense_ordering 须为映射，实际为 {type(so).__name__}",
        )
    primary = so.get("primary")
    if not isinstance(primary, str) or not primary.strip():
        return _item(
            "SENSE_ORDERING", rule, "fail",
            f"primary 未声明或非字符串（实际 {primary!r}）",
        )
    hit = [token for token in SENSE_ORDERING_ENUM if token in primary]
    if not hit:
        return _item(
            "SENSE_ORDERING", rule, "fail",
            f"排序规则键在枚举外：primary={primary!r}"
            f"（合法枚举：{'/'.join(SENSE_ORDERING_ENUM)}）",
        )
    extra = ""
    secondary = so.get("secondary_check")
    if isinstance(secondary, str) and secondary.strip():
        extra = f"；secondary_check={secondary.strip()}"
    return _item(
        "SENSE_ORDERING", rule, "pass",
        f"primary={primary.strip()}（命中枚举 {'/'.join(hit)}）{extra}",
    )


def check_microstructure_spine(style: Dict[str, Any]) -> Dict[str, str]:
    """④ MICROSTRUCTURE_SPINE：microstructure 声明键集合是否被
    sense_spine 七段实现面覆盖（spine 读取函数**只读调用**——sid=0 走无 DB
    的固定七段分支；不可比对 → warn「自动化比对未覆盖」）。未纳入映射的
    声明键（编纂成文层构件）如实列名，不计违例。"""
    rule = (
        "microstructure 声明键与 sense_spine 七段面一致性"
        "（映射键须被 spine 实现面覆盖；不可比对 → warn）"
    )
    if "microstructure" not in style:
        return _item(
            "MICROSTRUCTURE_SPINE", rule, "fail",
            "microstructure 键未声明（词条内部构件规则无从核验）",
        )
    ms = style["microstructure"]
    if not isinstance(ms, dict):
        return _item(
            "MICROSTRUCTURE_SPINE", rule, "fail",
            f"microstructure 须为映射，实际为 {type(ms).__name__}",
        )
    declared = [k for k in ms.keys() if isinstance(k, str) and k.strip()]
    mapped = [k for k in declared if k in MICROSTRUCTURE_SPINE_MAP]
    unmapped = [k for k in declared if k not in MICROSTRUCTURE_SPINE_MAP]
    try:
        from src import sense_spine  # 运行时 import（本模块纪律 6）

        sections = sense_spine._spine_sections(0)   # sid=0 → 固定七段，无 DB
        titles = [s.title for s in sections]
    except Exception as exc:  # noqa: BLE001 —— 不可比对按 warn，不崩
        logger.warning(f"style_check: spine 七段面读取失败: {exc}")
        return _item(
            "MICROSTRUCTURE_SPINE", rule, "warn",
            f"自动化比对未覆盖：spine 七段面读取失败（{exc}）；"
            f"声明键 {len(declared)} 个未比对",
        )
    if len(titles) != SPINE_SECTION_COUNT:
        return _item(
            "MICROSTRUCTURE_SPINE", rule, "warn",
            f"自动化比对未覆盖：spine 实现面段数异常（{len(titles)} ≠ "
            f"{SPINE_SECTION_COUNT}），映射比对暂缓",
        )
    uncovered = []
    for key in mapped:
        markers = MICROSTRUCTURE_SPINE_MAP[key]
        if not any(marker in title for marker in markers for title in titles):
            uncovered.append(f"{key}（缺 spine 段：{'/'.join(markers)}）")
    if uncovered:
        return _item(
            "MICROSTRUCTURE_SPINE", rule, "fail",
            "声明键未被 spine 实现面覆盖：" + "、".join(uncovered),
        )
    detail = (
        f"spine 七段面在场（{len(titles)} 段）；映射键覆盖通过："
        f"{'、'.join(mapped) if mapped else '（无映射键声明）'}"
    )
    if unmapped:
        detail += (
            f"；未纳入 spine 自动比对（编纂成文层构件）：{'、'.join(unmapped)}"
        )
    return _item("MICROSTRUCTURE_SPINE", rule, "pass", detail)


def run_config_check_items(
    style: Dict[str, Any], search_dirs: Optional[List[Path]] = None
) -> List[Dict[str, str]]:
    """前四项纯函数检查（配置完备性/定义词表/排序规则/microstructure×spine）。

    独立成函数供测试与将来局部复检；第五项（媒体绑定抽查）依赖 DB，由
    ``run_style_check`` 单独调用。``search_dirs`` 是 vocab_file 的解析目录
    链（默认 [仓库根]；run_style_check 传 style.yaml 所在目录链）。
    """
    return [
        check_config_complete(style),
        check_defining_vocab(style, search_dirs),
        check_sense_ordering(style),
        check_microstructure_spine(style),
    ]


# ============================================
# 第五项：multimedia × media_bindings 抽查（只读 DB）
# ============================================
def check_multimedia_bindings(style: Dict[str, Any]) -> Dict[str, str]:
    """⑤ MULTIMEDIA_BINDINGS：multimedia 位规则与 media_bindings 现有绑定
    的抽查（图注必配 example_media 而图注空 → fail；许可闸声明而资产许可
    空 → fail；无绑定数据 → warn「暂无媒体绑定可检」；查询不可用 → warn）。

    只读 JOIN 抽查（media 两表全量计数，绑定表量级小；不改其数据）。
    """
    rule = (
        "multimedia 位规则抽查：example_media 图注必配（caption 空违例）、"
        "license_gate 许可闸（license 空违例）；无绑定数据 → warn"
    )
    if "multimedia" not in style:
        return _item(
            "MULTIMEDIA_BINDINGS", rule, "fail",
            "multimedia 键未声明（多模态位规则无从核验）",
        )
    mm = style["multimedia"]
    if not isinstance(mm, dict):
        return _item(
            "MULTIMEDIA_BINDINGS", rule, "fail",
            f"multimedia 须为映射，实际为 {type(mm).__name__}",
        )
    example_media = mm.get("example_media")
    caption_required = (
        isinstance(example_media, dict) and example_media.get("caption_required") is True
    )
    license_gate = "license_gate" in mm and mm.get("license_gate") not in (None, False)
    try:
        with get_db_cursor() as cursor:
            cursor.execute(_MEDIA_SPOT_CHECK_SQL)
            row = cursor.fetchone() or {}
    except Exception as exc:  # noqa: BLE001 —— 表未建/查询失败按 warn 降级
        logger.warning(f"style_check: 媒体绑定抽查查询失败: {exc}")
        return _item(
            "MULTIMEDIA_BINDINGS", rule, "warn",
            f"暂无媒体绑定可检（media 两表未建或查询失败：{exc}）；"
            f"规则声明 caption_required={caption_required}、"
            f"license_gate={license_gate}",
        )
    total_binds = _as_int(row.get("total_binds")) or 0
    if total_binds <= 0:
        return _item(
            "MULTIMEDIA_BINDINGS", rule, "warn",
            "暂无媒体绑定可检（media_bindings 无记录）——媒体登记后抽查自动"
            f"生效；规则声明 caption_required={caption_required}、"
            f"license_gate={license_gate}",
        )
    empty_caption = _as_int(row.get("empty_caption")) or 0
    empty_license = _as_int(row.get("empty_license")) or 0
    violations: List[str] = []
    if caption_required and empty_caption > 0:
        violations.append(
            f"图注必配违例：example_media 绑定 {empty_caption} 条图注为空"
        )
    if license_gate and empty_license > 0:
        violations.append(
            f"许可闸违例：{empty_license} 个绑定资产 license 为空"
            "（无许可不入库 —— D⑥）"
        )
    if violations:
        return _item(
            "MULTIMEDIA_BINDINGS", rule, "fail",
            f"抽查绑定 {total_binds} 条：" + "；".join(violations),
        )
    return _item(
        "MULTIMEDIA_BINDINGS", rule, "pass",
        f"抽查绑定 {total_binds} 条：图注/许可规则无违例"
        f"（caption_required={caption_required}、license_gate={license_gate}，"
        f"空图注 {empty_caption}、空许可 {empty_license}）",
    )


# ============================================
# 落库（建表 / 写 run / 读 run）
# ============================================
def ensure_style_check_table() -> None:
    """幂等建 style_check_runs（DDL 单一事实源
    mysql_db.STYLE_CHECK_RUNS_TABLE_SQL，与 init_database 全量建表同源）。

    失败向上抛（调用方 run_style_check 捕获转 ok=False ＋ R4 归因 reason）。
    """
    with get_db_cursor() as cursor:
        cursor.execute(STYLE_CHECK_RUNS_TABLE_SQL)


def pass_rate_from_counts(passed: Any, failed: Any) -> Optional[float]:
    """体例质检通过率纯函数（口径单一事实源，collab_metrics 委托本实现）：
    passed/(passed+failed)，4 位小数；分母 0 → None（「还没有可比项」≠ 0%）；
    warn 不入分子也不入分母（单列）。脏计数按 0（宽松规整，不抛异常）。"""
    p = _count(passed)
    f = _count(failed)
    denominator = p + f
    if denominator <= 0:
        return None
    return round(p / denominator, 4)


def _count(value: Any) -> int:
    """宽松计数规整：bool/None/非数值/负数一律按 0（计数不会为负；
    collab_metrics._count 同口径）。"""
    if value is None or isinstance(value, bool):
        return 0
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _declined(reason: str) -> Dict[str, Any]:
    """ok=False 统一形态（run_id=None、计数 0、items 空 —— R4 归因口径）。"""
    return {
        "ok": False, "run_id": None, "category": None,
        "passed": 0, "failed": 0, "warned": 0, "total": 0,
        "pass_rate": None, "items": [], "reason": reason,
    }


def run_style_check(category: str, actor: Any = None) -> Dict[str, Any]:
    """对范畴执行一次体例质检并落 style_check_runs 一行。

    Args:
        category: 范畴名（configs/<category>/ 目录名；含路径分隔符/点前缀
            等非法名直接 ok=False 拒绝 —— category 要进文件路径与 SQL 值）。
        actor: 显式用户 dict（页面层经 guards.require_dict_admin 传入）；
            非 dict_admin 抛 PermissionError（guards 既有模式）。None =
            系统作业（脚本/定时任务）—— 照 RV2-3 留痕列第 1 类口径放行、
            run_by 落 NULL，调用点须自证其职。

    Returns:
        dict: ``{ok, run_id, category, passed, failed, warned, total,
        pass_rate, items, reason?}``。
        * ok=True：执行成功（已落一行），items 为逐项结果
          （``[{code, rule, status, detail}]``，status ∈ pass/fail/warn）；
          质检是否通过看逐项 status 与 pass_rate，ok 只表达执行面；
        * ok=False：style.yaml 缺失/不可解析 或 数据库不可用 —— reason 为
          R4 归因文案，run_id=None、不落任何记录；
        * pass_rate = passed/(passed+failed)（warn 不入分母；分母 0 → None）。
    """
    cat = str(category).strip() if category is not None else ""
    if (not cat or cat.startswith(".") or "/" in cat or "\\" in cat
            or cat in (".", "..")):
        return _declined(
            f"范畴名非法：{category!r}（应为 configs/ 下目录名，"
            "不含路径分隔符与点前缀）"
        )
    # 权限闸（guards 既有模式）：None=系统作业照 RV 口径；显式 actor 过闸
    if actor is None:
        run_by: Optional[int] = None
    else:
        user = require_role(
            actor, allowed={"dict_admin"}, action="体例质检执行"
        )   # 非 dict_admin 抛 PermissionError
        run_by = _as_int(user.get("id"))
    # 数据库先行（建不了表/连不上 → ok=False，不写半行）
    try:
        ensure_style_check_table()
    except Exception as exc:  # noqa: BLE001 —— pymysql.Error 等统一归因
        logger.error(f"style_check: style_check_runs 建表失败: {exc}")
        return _declined(
            f"数据库不可用（style_check_runs 建表失败：{exc}）—— 本次质检"
            "未执行、未落库"
        )
    # 体例配置（缺失/解析失败 → ok=False）
    style, path, error = load_style_config(cat)
    if error is not None or style is None:
        return _declined(error or f"style.yaml 不可读（{path}）")
    # 逐项检查：前四项纯函数 ＋ 第五项 DB 抽查
    # vocab_file 解析目录链：style.yaml 所在目录 → 其上级（configs/）→ 仓库根
    style_dir = Path(path).parent
    search_dirs = [style_dir, style_dir.parent, _REPO_ROOT]
    items: List[Dict[str, str]] = run_config_check_items(style, search_dirs)
    items.append(check_multimedia_bindings(style))
    passed = sum(1 for it in items if it["status"] == "pass")
    failed = sum(1 for it in items if it["status"] == "fail")
    warned = sum(1 for it in items if it["status"] == "warn")
    total = len(items)
    # 落库（detail_json=逐项数组；INSERT 失败也归因 ok=False，不崩）
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO style_check_runs "
                "(category, run_by, passed, failed, warned, total, detail_json) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (cat, run_by, passed, failed, warned, total,
                 json.dumps(items, ensure_ascii=False)),
            )
            run_id = int(cursor.lastrowid)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"style_check: 质检结果落库失败: {exc}")
        return _declined(f"数据库不可用（质检结果落库失败：{exc}）")
    return {
        "ok": True, "run_id": run_id, "category": cat,
        "passed": passed, "failed": failed, "warned": warned,
        "total": total, "pass_rate": pass_rate_from_counts(passed, failed),
        "items": items,
    }


def list_recent_runs(
    category: Optional[str] = None, limit: int = 5
) -> Optional[List[Dict[str, Any]]]:
    """读最近 N 次体例质检 run（id 降序＝新在前；数据库不可用/表未建返回
    None —— R4 归因，调用方据此灰注）。

    Args:
        category: None → 跨范畴取最近 limit 次；给定 → 该范畴最近 limit 次。
        limit: 返回条数上限（默认 5；非正数按 1）。

    Returns:
        list[dict] | None：行含 id/category/run_by/passed/failed/warned/
        total/detail_json/created_at，另附 ``items``（detail_json 解析后的
        逐项数组；解析失败或空为 None，不抛异常）。
    """
    sql = (
        "SELECT id, category, run_by, passed, failed, warned, total, "
        "detail_json, created_at FROM style_check_runs"
    )
    params: List[Any] = []
    if category is not None:
        sql += " WHERE category = %s"
        params.append(str(category))
    sql += " ORDER BY id DESC LIMIT %s"
    try:
        capped = max(1, int(limit))
    except (TypeError, ValueError):
        capped = 1
    params.append(capped)
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall() or []
    except Exception as exc:  # noqa: BLE001 —— 表未建/库断连统一降级
        logger.error(f"style_check: 读取质检 run 记录失败: {exc}")
        return None
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        raw = item.get("detail_json")
        parsed: Any = None
        if isinstance(raw, (str, bytes)) and raw:
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                parsed = None
        item["items"] = parsed if isinstance(parsed, list) else None
        out.append(item)
    return out
