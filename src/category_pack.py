"""范畴包（Category Pack）机制：跨词类通用框架的配置加载与自检（Agent D）。

职责（唯一事实源 docs/spec/多人标注系统设计规范.md §3-§4 / docs/spec/跨词类通用框架.md §1-§2）：

  * ``CATEGORIES()``               扫描 configs/ 下的范畴包目录（含 pack.yaml 的非下划线目录）
  * ``load_pack(category)``        加载六件套 →
                                   ``{admission, features, schemas, corpus_map, prompts, pack}``
                                   加载即自检，失败抛 ``CategoryPackError``（问题清单）
  * ``run_selfcheck(category)``    纯 Python 校验（**不引 jsonschema**），返回 ``(ok, problems)``

范畴包六件套（configs/<category>/，新词类从 configs/_template/ 复制，框架文档 §1/§5）::

    pack.yaml / admission.yaml / features.yaml / schemas.yaml / corpus_map.yaml
    prompts/screening.txt

自检六条（规范 §4；与 pack.yaml 的 ``selfcheck`` 清单一一对应）：

  ① 六文件齐全且 yaml.safe_load 可解析（screening.txt 为纯文本，要求可读且非空）；
  ② admission_classes 非空且 code 互斥（无重复）；
  ③ features ≥5 项 in_clustering=true；每个特征的 value_type ∈ {binary, nominal, ordinal}；
     每个 in_clustering 特征有非空 code 且唯一；
  ④ schemas 非空且 annotation.mode 已定义；每个 evidence_slot ∈ corpus_map.slots 的 code 集合；
  ⑤ prompts/screening.txt 存在且含规范列出的全部占位符（9 个）；
  ⑥ features 的 group 与 admission 无关，但必须在 features.yaml 的 groups 定义里。

引擎与配置的边界（框架文档 §4 纪律）：本模块只认识「范畴包」，不出现任何具体词类的
名词；换词类 = 换 configs/<category>/ 目录，引擎代码零修改。

安全规则：yaml 只用 ``safe_load``（§6-6 PyYAML 已随 streamlit 可用）。
"""

from __future__ import annotations

import os
from typing import Any, Optional

__all__ = [
    "CategoryPackError",
    "CATEGORIES",
    "load_pack",
    "run_selfcheck",
    "PACK_FILES",
    "SCREENING_RELPATH",
    "REQUIRED_PLACEHOLDERS",
    "VALUE_TYPES",
    "MIN_CLUSTERING_FEATURES",
]

# 仓库根目录（src/category_pack.py 的上一级）。测试可用 monkeypatch 替换以指向临时 configs。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 六件套：五个 YAML + 一个提示词（框架文档 §1/§2）
PACK_FILES = ("pack.yaml", "admission.yaml", "features.yaml", "schemas.yaml", "corpus_map.yaml")
SCREENING_RELPATH = os.path.join("prompts", "screening.txt")

# prompts/screening.txt 必须包含的占位符（规范 §4 / 框架文档 §2⑤）
REQUIRED_PLACEHOLDERS = (
    "category_name",
    "operational_definition",
    "admission_classes",
    "verbal_heuristic",
    "boundary_rules",
    "schema_names",
    "sense_id",
    "definition",
    "examples",
)

# 特征取值类型枚举（决定 Gower 距离分支，框架文档 §2②）
VALUE_TYPES = ("binary", "nominal", "ordinal")

# in_clustering=true 的最少特征数（框架文档 §2⑥ 自检清单）
MIN_CLUSTERING_FEATURES = 5


class CategoryPackError(Exception):
    """范畴包缺失 / 不可解析 / 自检未通过。

    ``str(exc)`` 为换行拼接的问题清单（每行以 "- " 起头，便于在 UI/日志里逐条展示）。
    """


# ============================================
# 路径与扫描
# ============================================

def _configs_root() -> str:
    return os.path.join(_REPO_ROOT, "configs")


def _category_dir(category: str) -> str:
    return os.path.join(_configs_root(), str(category))


def CATEGORIES() -> tuple:
    """扫描 configs/ 下的范畴包目录名（可启动 = 目录含 pack.yaml）。

    跳过 ``_``/``.`` 开头的内部目录（``_template``、``_schema`` 等）。
    返回排序后的 tuple（引擎与 reliability 页面按此枚举可选范畴）。
    """
    root = _configs_root()
    if not os.path.isdir(root):
        return ()
    found: list[str] = []
    for name in sorted(os.listdir(root)):
        if name.startswith(("_", ".")):
            continue
        if os.path.isfile(os.path.join(root, name, "pack.yaml")):
            found.append(name)
    return tuple(found)


# ============================================
# 读取（yaml 只用 safe_load）
# ============================================

def _read_yaml(path: str) -> tuple[Optional[Any], Optional[str]]:
    """读单个 YAML 文件。返回 ``(data, error)``；error 非 None 表示缺失/解析失败。"""
    if not os.path.isfile(path):
        return None, "缺失"
    try:
        import yaml

        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception as exc:  # noqa: BLE001 — 解析失败要带原因进问题清单
        return None, f"解析失败: {exc}"
    return data, None


def _load_raw(category: str, problems: list[str]) -> dict:
    """读六件套原始内容；文件级问题（缺失/解析失败/类型不对）记入 problems。

    返回 dict：五个 YAML 文件名 → dict|None，外加 ``"screening"`` → str|None。
    """
    cdir = _category_dir(category)
    raw: dict[str, Any] = {}
    # ① 六文件齐全且可解析
    for fname in PACK_FILES:
        path = os.path.join(cdir, fname)
        data, err = _read_yaml(path)
        if err is not None:
            problems.append(f"{fname}: {err}（路径 {path}）")
            raw[fname] = None
        elif not isinstance(data, dict):
            problems.append(f"{fname}: 顶层必须是映射（dict），实际为 {type(data).__name__}")
            raw[fname] = None
        else:
            raw[fname] = data

    screen_path = os.path.join(cdir, SCREENING_RELPATH)
    if os.path.isfile(screen_path):
        try:
            with open(screen_path, "r", encoding="utf-8") as fh:
                raw["screening"] = fh.read()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"prompts/screening.txt: 读取失败: {exc}")
            raw["screening"] = None
    else:
        problems.append(f"prompts/screening.txt: 缺失（路径 {screen_path}）")
        raw["screening"] = None
    return raw


# ============================================
# 自检（纯 Python，不引 jsonschema）
# ============================================

def run_selfcheck(category: str) -> tuple[bool, list[str]]:
    """对范畴包执行全部自检。返回 ``(ok, problems)``；ok=False 时 problems 非空。"""
    problems: list[str] = []
    raw = _load_raw(str(category), problems)
    _check_deep(str(category), raw, problems)
    return (not problems, problems)


def load_pack(category: str) -> dict:
    """加载范畴包六件套。加载即自检，任一失败抛 ``CategoryPackError(问题清单)``。

    返回 ``{admission, features, schemas, corpus_map, prompts, pack}``；
    ``prompts`` 为 ``{"screening": <screening.txt 全文>}``。
    """
    problems: list[str] = []
    raw = _load_raw(str(category), problems)
    _check_deep(str(category), raw, problems)
    if problems:
        raise CategoryPackError(
            f"范畴包 selfcheck 未通过（category={category}），共 {len(problems)} 项问题：\n- "
            + "\n- ".join(problems)
        )
    return {
        "pack": raw["pack.yaml"],
        "admission": raw["admission.yaml"],
        "features": raw["features.yaml"],
        "schemas": raw["schemas.yaml"],
        "corpus_map": raw["corpus_map.yaml"],
        "prompts": {"screening": raw["screening"]},
    }


def _check_deep(category: str, raw: dict, problems: list[str]) -> None:
    """逐文件深度校验（文件级问题已由 _load_raw 记录，此处只查加载成功者）。"""
    _check_pack_meta(category, raw.get("pack.yaml"), problems)
    _check_admission(raw.get("admission.yaml"), problems)
    _check_features(raw.get("features.yaml"), problems)
    _check_schemas(raw.get("schemas.yaml"), raw.get("corpus_map.yaml"), problems)
    _check_screening(raw.get("screening"), problems)


def _check_pack_meta(category: str, pack: Any, problems: list[str]) -> None:
    if pack is None:  # 文件级问题已记录
        return
    got = pack.get("category")
    if got != category:
        problems.append(f"pack.yaml: category={got!r} 与目录名 {category!r} 不一致")
    if not pack.get("version"):
        problems.append("pack.yaml: 缺少 version 字段")


def _check_admission(admission: Any, problems: list[str]) -> None:
    """② admission_classes 非空且 code 互斥。"""
    if admission is None:
        return
    if not str(admission.get("operational_definition") or "").strip():
        problems.append("admission.yaml: 缺少 operational_definition（操作性定义）")
    classes = admission.get("admission_classes")
    if not isinstance(classes, list) or not classes:
        problems.append("admission.yaml: admission_classes 必须是非空列表")
        return
    codes: list[str] = []
    for i, cls in enumerate(classes):
        if not isinstance(cls, dict):
            problems.append(f"admission.yaml: admission_classes[{i}] 必须是映射")
            continue
        code = cls.get("code")
        if not isinstance(code, str) or not code.strip():
            problems.append(f"admission.yaml: admission_classes[{i}] 缺少非空 code")
            continue
        codes.append(code.strip())
    dupes = sorted({c for c in codes if codes.count(c) > 1})
    if dupes:
        problems.append(
            f"admission.yaml: admission_classes 的 code 必须互斥，发现重复: {', '.join(dupes)}"
        )


def _check_features(features_doc: Any, problems: list[str]) -> None:
    """③ features ≥5 项进聚类、value_type 枚举、in_clustering code 唯一；
    ⑥ 每个特征的 group 必须在 groups 定义里（与 admission 无关）。"""
    if features_doc is None:
        return

    group_ids: set[str] = set()
    groups = features_doc.get("groups")
    if isinstance(groups, list) and groups:
        for g in groups:
            if isinstance(g, dict) and isinstance(g.get("id"), str) and g["id"].strip():
                group_ids.add(g["id"].strip())
    else:
        problems.append("features.yaml: groups 必须是非空列表（每项含 id）")

    features = features_doc.get("features")
    if not isinstance(features, list) or not features:
        problems.append("features.yaml: features 必须是非空列表")
        return

    clustering_codes: list[str] = []
    n_clustering = 0
    for i, feat in enumerate(features):
        if not isinstance(feat, dict):
            problems.append(f"features.yaml: features[{i}] 必须是映射")
            continue
        label = str(feat.get("code") or f"features[{i}]")
        value_type = feat.get("value_type")
        if value_type not in VALUE_TYPES:
            problems.append(
                f"features.yaml: 特征 {label} 的 value_type={value_type!r} "
                f"不在 {list(VALUE_TYPES)} 内"
            )
        group = feat.get("group")
        if group_ids:
            if not isinstance(group, str) or group.strip() not in group_ids:
                problems.append(
                    f"features.yaml: 特征 {label} 的 group={group!r} 未在 groups 定义里"
                    f"（已定义: {', '.join(sorted(group_ids))}）"
                )
        elif not group:
            problems.append(f"features.yaml: 特征 {label} 缺少 group")
        if feat.get("in_clustering"):
            n_clustering += 1
            code = feat.get("code")
            if not isinstance(code, str) or not code.strip():
                problems.append(f"features.yaml: 第 {i} 项 in_clustering 特征缺少非空 code")
            else:
                clustering_codes.append(code.strip())

    if n_clustering < MIN_CLUSTERING_FEATURES:
        problems.append(
            f"features.yaml: in_clustering=true 的特征仅 {n_clustering} 项，"
            f"至少需要 {MIN_CLUSTERING_FEATURES} 项"
        )
    dupes = sorted({c for c in clustering_codes if clustering_codes.count(c) > 1})
    if dupes:
        problems.append(
            f"features.yaml: in_clustering 特征的 code 必须唯一，发现重复: {', '.join(dupes)}"
        )


def _check_schemas(schemas_doc: Any, corpus_map: Any, problems: list[str]) -> None:
    """④ schemas 非空、annotation.mode 已定义、evidence_slot ⊆ corpus_map.slots 的 code 集合。"""
    # 先收集 corpus_map.slots 的 code 集合（槽位引用完整性的参照系）
    slot_codes: set[str] = set()
    if corpus_map is None:
        problems.append("corpus_map.yaml: 文件缺失或不可解析，无法核验 evidence_slot 引用")
    else:
        slots = corpus_map.get("slots")
        if isinstance(slots, list) and slots:
            for i, slot in enumerate(slots):
                if (
                    isinstance(slot, dict)
                    and isinstance(slot.get("code"), str)
                    and slot["code"].strip()
                ):
                    slot_codes.add(slot["code"].strip())
                else:
                    problems.append(f"corpus_map.yaml: slots[{i}] 缺少非空 code")
        else:
            problems.append("corpus_map.yaml: slots 必须是非空列表（每项含 code）")

    if schemas_doc is None:
        return
    schemas = schemas_doc.get("schemas")
    if not isinstance(schemas, list) or not schemas:
        problems.append("schemas.yaml: schemas 必须是非空列表")
        return
    annotation = schemas_doc.get("annotation")
    mode = annotation.get("mode") if isinstance(annotation, dict) else None
    if not (isinstance(mode, str) and mode.strip()):
        problems.append("schemas.yaml: annotation.mode 未定义（如 forced_choice）")

    for i, schema in enumerate(schemas):
        if not isinstance(schema, dict):
            problems.append(f"schemas.yaml: schemas[{i}] 必须是映射")
            continue
        label = str(schema.get("code") or f"schemas[{i}]")
        if not (isinstance(schema.get("code"), str) and schema["code"].strip()):
            problems.append(f"schemas.yaml: 第 {i} 个图式缺少非空 code")
        slots_ref = schema.get("evidence_slots")
        if not isinstance(slots_ref, list) or not slots_ref:
            problems.append(f"schemas.yaml: 图式 {label} 缺少非空 evidence_slots 列表")
            continue
        for slot in slots_ref:
            code = slot.strip() if isinstance(slot, str) else ""
            if not code:
                problems.append(f"schemas.yaml: 图式 {label} 的 evidence_slots 含空槽位")
            elif code not in slot_codes:
                problems.append(
                    f"schemas.yaml: 图式 {label} 引用的证据槽位 '{code}' "
                    "未在 corpus_map.slots 中定义"
                )


def _check_screening(text: Any, problems: list[str]) -> None:
    """⑤ prompts/screening.txt 存在且含全部占位符（缺失/读取失败已在 _load_raw 记录）。"""
    if text is None:
        return
    if not text.strip():
        problems.append("prompts/screening.txt: 文件为空")
        return
    for name in REQUIRED_PLACEHOLDERS:
        token = "{" + name + "}"
        if token not in text:
            problems.append(f"prompts/screening.txt: 缺少占位符 {token}")
