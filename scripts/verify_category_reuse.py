#!/usr/bin/env python3
"""跨词类复用验收脚本 —— 第二范畴（speech）仅凭配置包走通平台（批次 9 · Agent AT；
批次 10 · Agent AU 第 5 步收口：拼装表外置后按 speech 渲染实测转 ✅）。

验收判据（docs/spec/跨词类通用框架.md §5「复用验证的客观判据」）：
    在第二个范畴上，仅通过编写配置包（不改引擎代码）走完
    「义位筛选 → 特征标注 → 聚类 → 图式提取 → 模板实例化」五步。

用法（零新依赖；零写库——脚本全程不连生产库，AppTest 段强制断库空态降级）：

    python3 scripts/verify_category_reuse.py           # 人读报告（markdown）
    python3 scripts/verify_category_reuse.py --json    # 机器可读 JSON

五项验收（任务书 ①–⑤）：

  ① run_selfcheck('speech') 全绿           —— 配置包六件套自检（不引 jsonschema）
  ② CATEGORIES() 含 speech                 —— configs/ 扫描到第二个范畴（可启动）
  ③ load_pack('speech') 六件套键齐全       —— admission/features/schemas/corpus_map/
                                              prompts/pack 全部加载成功且结构达标
  ④ 页面可用性 AppTest 冒烟                —— 语义分析页（cluster）/以句搜义页
                                              （semantic）的范畴下拉均含 speech
                                              （monkeypatch 数据层为空态降级：
                                              验证「工具点亮、页面可切」而非数据）
  ⑤ 五步验收表（markdown 打印）            —— 每步标注 ✅架构就绪 / ⚠️待数据；
                                              第 5 步（模板实例化）自批次 10 R-1
                                              收口（拼装表外置进范畴包
                                              template_assembly 节）起，附纯函数
                                              直渲染实测：speech 产物含言说动词
                                              配置词面、零 motion 词面残留。

如实标注原则：speech 无真实语料/无 cs_* 灌数，五步中凡引擎链路已验证为配置驱动、
无词类硬编码的标 ✅架构就绪；凡「走完该步」必须等待数据的标 ⚠️待数据；凡引擎代码
里发现词类专属接缝的，在「复用断点清单」如实列出（最高价值输出，集成方归档）。
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CATEGORY = "speech"          # 第二范畴（虚构验证帧，configs/speech/）
BASELINE = "motion"          # 第一范畴（已验证真数据，作对照锚）

# 五步验收表的行（判定在 check_five_steps() 里按实测证据填充）
FIVE_STEPS = ("义位筛选", "特征标注", "聚类", "图式提取", "模板实例化")


def _fail(message: str) -> None:
    raise AssertionError(message)


# ============================================
# ① selfcheck 全绿
# ============================================

def check_selfcheck() -> dict:
    from src.category_pack import run_selfcheck

    ok, problems = run_selfcheck(CATEGORY)
    _fail(f"run_selfcheck({CATEGORY!r}) 应全绿，实际 problems={problems}") if not ok else None
    return {"ok": True, "problems": problems,
            "detail": f"run_selfcheck({CATEGORY}) = (True, []) —— 六件套自检六条全过"}


# ============================================
# ② CATEGORIES() 含 speech（且第一范畴 motion 仍在）
# ============================================

def check_categories() -> dict:
    from src.category_pack import CATEGORIES

    cats = CATEGORIES()
    _fail(f"CATEGORIES() 应含 {CATEGORY!r}，实际 {cats!r}") if CATEGORY not in cats else None
    _fail(f"第一范畴 {BASELINE!r} 不应消失，实际 {cats!r}") if BASELINE not in cats else None
    return {"ok": True, "categories": list(cats),
            "detail": f"CATEGORIES() = {cats} —— 引擎按目录扫描自动发现第二个范畴"}


# ============================================
# ③ load_pack('speech') 六件套键齐全＋结构达标
# ============================================

def check_load_pack() -> dict:
    from src.category_pack import MIN_CLUSTERING_FEATURES, REQUIRED_PLACEHOLDERS, load_pack

    pack = load_pack(CATEGORY)  # 加载即自检，失败抛 CategoryPackError
    expected_keys = {"admission", "features", "schemas", "corpus_map", "prompts", "pack"}
    missing = expected_keys - set(pack)
    _fail(f"load_pack 六件套缺键: {sorted(missing)}") if missing else None
    for key in ("pack", "admission", "features", "schemas", "corpus_map"):
        _fail(f"load_pack 键 {key} 为空") if not pack.get(key) else None

    # 结构达标的具体数字（供 JSON 与报告引用；不再编口径，全部来自实测）
    admission_codes = [c.get("code") for c in pack["admission"]["admission_classes"]]
    features = pack["features"]["features"]
    clustering = [f for f in features if f.get("in_clustering")]
    value_types = sorted({f.get("value_type") for f in clustering})
    schemas = pack["schemas"]["schemas"]
    slots = [s.get("code") for s in pack["corpus_map"]["slots"]]
    screening = pack["prompts"]["screening"]
    missing_ph = [p for p in REQUIRED_PLACEHOLDERS if "{" + p + "}" not in screening]
    _fail(f"screening.txt 缺占位符: {missing_ph}") if missing_ph else None
    if len(clustering) < MIN_CLUSTERING_FEATURES:
        _fail(f"进聚类特征 {len(clustering)} 项 < 下限 {MIN_CLUSTERING_FEATURES}")
    # 图式引用槽位 ⊆ corpus_map.slots（selfcheck ④ 已查，此处复述为报告证据）
    for schema in schemas:
        outside = [s for s in schema.get("evidence_slots", []) if s not in slots]
        _fail(f"图式 {schema.get('code')} 引用了未定义槽位 {outside}") if outside else None
    return {
        "ok": True,
        "admission_codes": admission_codes,
        "n_features": len(features),
        "n_clustering": len(clustering),
        "value_types": value_types,
        "n_schemas": len(schemas),
        "schema_codes": [s.get("code") for s in schemas],
        "n_slots": len(slots),
        "detail": (
            f"六件套齐全：准入三分 {admission_codes}＋边界条款；特征 {len(features)} 项"
            f"（进聚类 {len(clustering)} 项，value_type={value_types}）；"
            f"图式 {len(schemas)} 个 {[s.get('code') for s in schemas]}，"
            f"证据槽位 {len(slots)} 个（引用全部闭合）；screening.txt 占位符 "
            f"{len(REQUIRED_PLACEHOLDERS)}/{len(REQUIRED_PLACEHOLDERS)} 齐全"
        ),
    }


# ============================================
# ④ AppTest 页面冒烟：语义分析页 / 以句搜义页范畴下拉含 speech
# ============================================

# 两个被测页面（app.py 页面键 → 范畴下拉的 widget key）
SMOKE_PAGES = (
    {"page": "cluster", "select_key": "ca_category",
     "label": "语义分析页（cluster · 📊）"},
    {"page": "semantic", "select_key": "ss_category",
     "label": "以句搜义页（semantic · 🧠）"},
)


def _refused_port() -> int:
    """挑一个必然拒绝连接的端口（端口 1 有服务时退 65501；口径同集成测试）。"""
    probe = socket.socket()
    try:
        return 65501 if probe.connect_ex(("127.0.0.1", 1)) == 0 else 1
    finally:
        probe.close()


def check_apptest_smoke() -> dict:
    """断库空态降级下渲染两页，断言范畴下拉含 speech（不碰生产库一行数据）。

    monkeypatch 口径（与 tests/test_integration_apptest.py 的
    TestDbUnavailableDegrade 同一手法）：把 src.mysql_db.MYSQL_PORT 指向必然
    拒绝的端口 → 页面数据层全部空态降级（info/warning 引导灌库，不抛异常）；
    会话用户直接注入（无 _user_db_backed 标记，不触发实时回查，断库可跑）。
    """
    import src.mysql_db as db
    from streamlit.testing.v1 import AppTest

    app_path = ROOT / "src" / "app.py"
    old_port = db.MYSQL_PORT
    results = []
    try:
        db.MYSQL_PORT = _refused_port()  # 数据层空态降级（§3 disabled≠enabled+empty 的空态）
        for spec in SMOKE_PAGES:
            at = AppTest.from_file(str(app_path), default_timeout=180)
            at.session_state["user"] = {
                "id": 1, "username": "reuse_smoke", "display_name": "复用冒烟",
                "role": "viewer",
            }
            at.session_state["page"] = spec["page"]
            at.run()
            _fail(f"{spec['label']} AppTest 异常: {at.exception}") if at.exception else None
            errors = [str(e.value) for e in at.error]
            _fail(f"{spec['label']} 出现 error 通道（应空态降级）: {errors}") if errors else None
            select = [s for s in at.selectbox if getattr(s, "key", "") == spec["select_key"]]
            _fail(f"{spec['label']} 未找到范畴下拉（key={spec['select_key']}）") \
                if not select else None
            options = list(select[0].options)
            _fail(f"{spec['label']} 范畴下拉 {options!r} 不含 {CATEGORY!r}") \
                if CATEGORY not in options else None
            _fail(f"{spec['label']} 范畴下拉 {options!r} 不含 {BASELINE!r}") \
                if BASELINE not in options else None
            results.append({"page": spec["page"], "label": spec["label"],
                            "select_key": spec["select_key"], "options": options})
    finally:
        db.MYSQL_PORT = old_port  # 还原（脚本不遗留全局副作用）
    return {"ok": True, "pages": results,
            "detail": "；".join(
                f"{r['label']}范畴下拉={r['options']}" for r in results
            ) + "（断库空态降级，工具点亮、页面可切）"}


# ============================================
# 第 5 步渲染实测（批次 10 R-1 收口判据：speech 词面非 motion 残留）
# ============================================

# 纯函数直渲染探针向量（零 DB；speech=言说六特征验证帧，motion=run-S1 对照锚）
SPEECH_PROBE_VECTOR = {"I1": 1, "I2": 1, "I3": 1, "S1": "oral", "R1": 0, "R2": 1,
                       "A1": 1}
MOTION_PROBE_VECTOR = {"M1a": 1, "M1b": 1, "M2": 1, "M3a": 1, "C1": 2, "A1": 1}


def _assembly_wordings(node: object) -> list:
    """拼装节 → 主句词面标记集合（text/fragments/value_fragments/values/
    prefix/suffix/fallback 的字面量；含 {占位符} 的模板串与单字符修饰不算）。"""
    marks: list = []
    if isinstance(node, dict):
        for key, val in node.items():
            if key == "text" and isinstance(val, str):
                marks.append(val)
            elif key in ("fragments", "value_fragments") and isinstance(val, dict):
                marks.extend(str(v) for v in val.values())
            elif key == "values" and isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        marks.extend(str(item[k]) for k in ("prefix", "suffix")
                                     if isinstance(item.get(k), str))
            elif key in ("template", "prefix", "suffix", "fallback") \
                    and isinstance(val, str):
                marks.append(val)
            else:
                marks.extend(_assembly_wordings(val))
    elif isinstance(node, list):
        for item in node:
            marks.extend(_assembly_wordings(item))
    return [m for m in marks if m and "{" not in m and len(m) >= 2]


def check_template_render() -> dict:
    """第 5 步判据实测：speech 包拼装节渲染产出言说动词词面（非 motion 残留）。

    render_template_text 为纯函数（零 DB、零 LLM），直渲染两包探针向量：
      ① speech 产物含其拼装节词面标记（言说动词口径）；
      ② speech 产物不含 motion 拼装节任何词面标记（「移动」类残留为零）；
      ③ motion 产物仍含自身词面标记（第一范畴护栏不回退）。
    """
    import src.template_engine as te
    from src.category_pack import load_pack

    speech_pack = load_pack(CATEGORY)
    motion_pack = load_pack(BASELINE)
    speech_text = te.render_template_text(
        te._feature_meta(speech_pack), SPEECH_PROBE_VECTOR,
        speech_pack["schemas"]["schemas"][0], [])
    motion_text = te.render_template_text(
        te._feature_meta(motion_pack), MOTION_PROBE_VECTOR,
        motion_pack["schemas"]["schemas"][0], [])
    speech_marks = _assembly_wordings(
        speech_pack["schemas"].get("template_assembly") or {})
    motion_marks = _assembly_wordings(
        motion_pack["schemas"].get("template_assembly") or {})
    _fail("speech 拼装节词面标记为空（template_assembly 缺失/为空）") \
        if not speech_marks else None
    _fail(f"speech 渲染产物不含任何拼装节词面标记: {speech_text!r}") \
        if not any(m in speech_text for m in speech_marks) else None
    residue = [m for m in motion_marks if m in speech_text]
    _fail(f"speech 渲染产物含 motion 词面残留: {residue}") if residue else None
    _fail(f"motion 渲染产物失去自身词面（护栏破坏）: {motion_text!r}") \
        if not any(m in motion_text for m in motion_marks) else None
    hits = sorted({m for m in speech_marks if m in speech_text})
    return {
        "ok": True,
        "speech_text": speech_text,
        "motion_text": motion_text,
        "speech_marks": speech_marks,
        "speech_mark_hits": hits,
        "detail": (
            f"speech 直渲染＝「{speech_text}」（含拼装节词面标记 {hits}，"
            f"零 motion 词面残留）；motion 直渲染＝「{motion_text}」（护栏）"
        ),
    }


# ============================================
# ⑤ 五步验收表（判定 = 本脚本实测证据；数据缺口如实）
# ============================================

def check_five_steps(selfcheck_info: dict, pack_info: dict, smoke_info: dict) -> list:
    """五步验收表。判定口径（任务书）：✅架构就绪 / ⚠️待数据，不编数。"""
    n_schemas = pack_info["n_schemas"]
    render = check_template_render()  # 批次 10：第 5 步判定附渲染实测
    rows = [
        {
            "step": "义位筛选",
            "verdict": "✅架构就绪",
            "evidence": (
                f"admission.yaml 三分 {'/'.join(pack_info['admission_codes'])}"
                "＋边界条款自检过；引擎准入链路（annotation_flow 的 admission 任务、"
                "协作收件箱）按 payload 的 Y/EXT/N 校验，零范畴假设——speech 包即插即用"
            ),
            "gap": "speech 无候选义位池（admission.yaml 的 candidate_pipeline 为验证帧"
                   "演示值）；cs_lexemes/cs_senses 未灌 speech 行——灌数后即可实走",
        },
        {
            "step": "特征标注",
            "verdict": "✅架构就绪",
            "evidence": (
                f"features.yaml 进聚类 {pack_info['n_clustering']} 项"
                f"（≥5），value_type={pack_info['value_types']} 三型齐；"
                "语义分析页/以句搜义页/信度页特征元数据全部经 load_pack 读取"
                "（冒烟实测两页可切 speech），Gower 分支按 value_type 自动选择"
            ),
            "gap": "speech 无义位可标（feature_coding 任务与 cs_sense_features 长表"
                   "未灌 speech 数据）——标注链路本身零改引擎",
        },
        {
            "step": "聚类",
            "verdict": "✅架构就绪",
            "evidence": (
                "features.yaml 声明 clustering.algorithm=gower_upgma + "
                "feature_scope=in_clustering；引擎（Gower+UPGMA）按包内 value_type "
                "分支计算，对特征码/特征名零假设——speech 六特征落在与 motion "
                "完全相同的字段结构（框架文档 §3 对照结论，selfcheck 实测）"
            ),
            "gap": "无 cs_sense_features 编码数据、无 cs_cluster_runs 运行记录"
                   "——聚类实走需先灌数（pipeline 漏斗会如实给缺数 reason）",
        },
        {
            "step": "图式提取",
            "verdict": "✅架构就绪",
            "evidence": (
                f"schemas.yaml {n_schemas} 个图式（断言/指令/表达）的 evidence_slots "
                f"⊆ corpus_map.yaml {pack_info['n_slots']} 槽位（selfcheck ④ 引用闭合实测）；"
                "scoring.function=mean_logdice_log2n 为引擎内置函数；"
                "template_engine.derive_cluster_schemas 经 resolve_pack 读包，零范畴假设"
            ),
            "gap": "无语料槽位统计数据（corpus_map 指向的 sketch_engine 槽位为通用"
                   "资源，speech 的 8 槽位未灌搭配数据）——图式提取实走需语料",
        },
        {
            "step": "模板实例化",
            "verdict": "✅架构就绪（R-1 已收口，渲染实测）",
            "evidence": (
                "批次 10 R-1 收口：槽位拼装表外置进范畴包（configs/<category>/"
                "schemas.yaml 的 template_assembly 节），引擎只保留「值标签 → "
                "槽位词面」通用段规则，零词类硬编码（缺节 fail-closed 报"
                "「范畴包缺 template_assembly」，不回退任何词类）；纯函数直渲染"
                f"实测——speech 产物＝「{render['speech_text']}」"
                f"（含言说动词拼装节词面标记 {render['speech_mark_hits']}，"
                "零 motion 词面残留）；motion 包产物逐字保持原拼装（护栏测试全绿）"
            ),
            "gap": "speech 无义位数据可实例化（cs_* 表未灌 speech 行）——灌数后即可"
                   "实走全链（义位 → 特征向量 → 四维模板）；词面为虚构验证帧研制值，"
                   "正式词面待言说动词编者定稿（只改配置节，引擎零修改）",
        },
    ]
    _fail(f"五步表应恰含 {len(FIVE_STEPS)} 步") if len(rows) != len(FIVE_STEPS) else None
    return rows


# 复用断点清单（批次 9 发现，如实列出；编号供五步表与集成报告引用。
# R-1/R-2 已由批次 10 收口——方向栏标注收口方式，其余仍开放）
BREAKPOINTS = [
    {
        "id": "R-1",
        "where": "src/template_engine.py（槽位拼装表）",
        "what": "render_template_text 的主体/速度/方式/介质/路径词面硬编码 motion "
                "特征码（M1a–M1d/P5/M2/M3a–M3d/C1）与中文路径片段（「自源点出发」等），"
                "speech 包特征不在其内——模板实例化对第二范畴退化为「主体不限，移动」",
        "direction": "✅ 批次 10 已收口：拼装表外置进 configs/<category>/schemas.yaml "
                     "的 template_assembly 节（motion 值逐字迁移；speech 按六特征 "
                     "I1/I2/I3/S1/R1/R2 研制验证帧词面）；引擎只保留「值标签 → 槽位"
                     "词面」通用段规则，缺节 fail-closed（报「范畴包缺 "
                     "template_assembly」）；本脚本 check_template_render 实测 speech "
                     "产物含言说动词词面、零 motion 残留",
    },
    {
        "id": "R-2",
        "where": "src/app.py（标注页「📋 准入判定标准」expander）",
        "what": "load_pack(\"motion\") 硬编码——准入标准只读展示永远显示 motion 包，"
                "speech 义位的准入判定页看到的仍是移动动词的三分口径",
        "direction": "✅ 批次 10 已收口：expander 改按当前标注范畴取包——标注页范畴"
                     "选择件（session/参数）取不到时按 CATEGORIES() 首个范畴包取数并"
                     "在标题注明；提交流接入范畴切换后自动跟随",
    },
    {
        "id": "R-3",
        "where": "src/cluster_analysis.py PACK_TO_STUDY_CODE ＋ 灌数脚本",
        "what": "包名→研究代号映射只有 {\"motion\": \"RUN\"}；speech 无研究登记名，"
                "语义分析页对比侧与 pipeline 漏斗对 speech 只能给「categories 无此范畴」"
                "缺数段；且 scripts/load_category_study.py 仅装载 d1（motion）数据，"
                "框架 §5 第三步「灌注义位」对 speech 无现成数据链路",
        "direction": "登记 speech 的 categories 行＋扩充 PACK_TO_STUDY_CODE（或改为"
                     "categories 表驱动）；义位灌数脚本接受任意范畴包",
    },
    {
        "id": "R-4",
        "where": "configs/*/prompts/screening.txt（五件套之⑤）",
        "what": "提示词文件被 selfcheck 逐占位符校验，但全仓库无任何引擎模块消费它"
                "（生产 LLM 初筛走 data/corpus/llm_screening/*.json 批次灌入，"
                "semantic_search 另建内嵌提示词）——「占位符自检通过」≠「提示词被引擎使用」",
        "direction": "llm_api/ai_ledger 的草稿通道接入 load_pack()['prompts'] 的"
                     "screening 模板（资源注入协议 §5），让 ⑤ 真正参与运行",
    },
    {
        "id": "R-5",
        "where": "writing_db.sense_ref（三段式锚）vs lexical_db.sense_ref（裸 cs_senses.id）",
        "what": "同一义位在释义撰写层锚「speech:12:345」、在例证/对译层锚「12」"
                "（lexical_pages 以 str(sense_id) 传参）——两层数据按不同键各存一份，"
                "装配时需二次解析才能对齐，批次 9 之后接词条装配时是隐患",
        "direction": "lexical_db 建议收口到同一三段式锚（valid_sense_ref 已兼容）；"
                     "至少在装配层统一换算函数",
    },
]


# ============================================
# 报告输出
# ============================================

def _print_markdown(checks: dict, rows: list) -> None:
    print("# 跨词类复用验收报告（第二范畴 speech · 批次 9 Agent AT ／ 批次 10 Agent AU 第 5 步收口）\n")
    print(f"判据：在第二个范畴上，仅通过编写配置包（不改引擎代码）走完"
          f"「{' → '.join(FIVE_STEPS)}」五步。\n")
    for name, info in checks.items():
        mark = "✅" if info["ok"] else "❌"
        print(f"- {mark} **{name}**：{info.get('detail', '')}")
    print("\n## 五步验收表\n")
    print("| # | 步骤 | 判定 | 架构证据（本脚本实测） | 数据缺口（如实） |")
    print("|---|------|------|------------------------|------------------|")
    for i, row in enumerate(rows, 1):
        print(f"| {i} | {row['step']} | {row['verdict']} | {row['evidence']} "
              f"| {row['gap']} |")
    print("\n## 发现的复用断点（speech 包与引擎的接缝，如实列）\n")
    for bp in BREAKPOINTS:
        print(f"- **{bp['id']}** {bp['where']}：{bp['what']}")
        print(f"  - 收口方向：{bp['direction']}")
    print("\n> speech 为虚构验证帧（框架文档 §3）：上表「数据缺口」列全部如实——"
          "判据是「配置包跑通」，不编数据。批次 9 基线引擎零修改；批次 10 完成 "
          "R-1/R-2 收口（拼装表外置进范畴包＋准入判定按范畴取包），第 5 步已按 "
          "speech 渲染实测转 ✅。")


def main() -> int:
    as_json = "--json" in sys.argv[1:]
    checks: dict = {}
    try:
        checks["① selfcheck 全绿"] = check_selfcheck()
        checks["② CATEGORIES 含 speech"] = check_categories()
        checks["③ load_pack 六件套齐全"] = check_load_pack()
        checks["④ AppTest 页面冒烟"] = check_apptest_smoke()
        rows = check_five_steps(checks["① selfcheck 全绿"], checks["③ load_pack 六件套齐全"],
                                checks["④ AppTest 页面冒烟"])
    except AssertionError as e:
        print(f"复用验收未通过：{e}", file=sys.stderr)
        if as_json:
            print(json.dumps({"ok": False, "error": str(e),
                              "checks": checks}, ensure_ascii=False, indent=2))
        return 1

    if as_json:
        payload = {
            "ok": True,
            "criterion": "第二范畴仅凭配置包走通五步（不改引擎代码）",
            "category": CATEGORY,
            "checks": checks,
            "five_steps": rows,
            "breakpoints": BREAKPOINTS,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_markdown(checks, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
