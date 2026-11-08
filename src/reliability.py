"""Krippendorff's α 信度引擎（多人标注系统 · Agent C）。

职责（唯一事实源 docs/spec/多人标注系统设计规范.md §3 / §7-V4）：

  * ``compute_alpha(units, value_type)``      对 {unit: {coder: value}} 算 α
  * ``run_reliability(category, task_type, features_meta)``  从 annotation_submissions
    汇总全部 status='submitted' 的提交 → 按任务比对字段/逐特征算 α → 写 reliability_runs
  * ``render_reliability_page()``             reviewer/admin 的信度报告页（Streamlit）

口径说明（用户决策③）：所有编码人看**同样的 AI 草稿**后独立标注，因此本页的 α
命名为 **AI-assisted IAA（全员可见 AI 草稿口径）**，页面输出必须带此标注。

两条计算路径（验收 V4 + 任务要求）：
  1. ``krippendorff`` 库（requirements.txt 已加；主路径）——
     ``krippendorff.alpha(reliability_data=矩阵, level_of_measurement='nominal'|'ordinal')``，
     矩阵形状 (M 编码人, N 单元)，缺失值用 np.nan；
  2. 纯 Python 回退实现 ``_alpha_pure``（库缺失或计算异常时自动启用，
     也可用环境变量 RELIABILITY_FORCE_PURE=1 强制）——实现 Krippendorff (2011)
     的巧合矩阵公式，nominal / ordinal 两分支，缺失值跳过，与库逐位同源。

单元 = 义位（sense_id）；编码人 = coder_id；缺失 = 某 coder 对某 unit 无提交/无该字段。
"""

from __future__ import annotations

import csv
import html
import io
import json
import logging
import math
import os
from typing import Any, Optional

import numpy as np

# 主路径：krippendorff 库；缺失时自动落到纯 Python 回退（两条路径都在本文件内）
try:
    import krippendorff

    KRIPPENDORFF_AVAILABLE = True
except ImportError:  # pragma: no cover - 环境差异分支
    krippendorff = None
    KRIPPENDORFF_AVAILABLE = False

from src.annotation_flow import parse_payload  # payload JSON 列解析的唯一实现（R4 消重）
from src.mysql_db import get_db_cursor
from src.security import sanitize_csv_cell  # CSV 公式注入防护（R1-P2a）的唯一实现
from src.users_db import effective_six_roles  # R1-2：信度页角色门六角色口径

logger = logging.getLogger(__name__)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ============================================
# 常量
# ============================================
# admission 任务比对字段（规范 §3：对 admission/schema/alignment 各算 nominal α）。
# alignment 作为独立 task_type 出现时（DDL 枚举里有），比对字段只有 alignment 本身。
_TASK_FIELDS: dict[str, tuple[str, ...]] = {
    "admission": ("admission", "schema", "alignment"),
    "feature_coding": (),  # 逐特征动态确定（payload["features"] 的键）
    "alignment": ("alignment",),
}

# 信度达标线（白话版对照清单：α ≥ 0.7 才算过关）
LOW_ALPHA_THRESHOLD = 0.7

# 页面口径标注（用户决策③，规范 §1/§7-V7 同源）
IAA_CAPTION = "AI-assisted IAA（全员可见 AI 草稿口径）"

# 规范 §2 DDL 原样 + created_by 归属列（R5 遗留 2：reliability_runs 无归属列，
# 无法按用户定位是谁跑的信度；e2e/清理脚本只能按 id 水位线）。NULL 允许
# 数据层调用（脚本/测试）不带归属。已有旧表由 _ensure_reliability_table 的
# 幂等迁移补列。
RELIABILITY_RUNS_DDL = """CREATE TABLE IF NOT EXISTS reliability_runs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  category VARCHAR(40) NOT NULL DEFAULT 'motion',
  task_type ENUM('admission','feature_coding','alignment') NOT NULL,
  n_coders INT NOT NULL, n_units INT NOT NULL,
  overall_alpha DECIMAL(5,3) NULL,
  per_feature JSON NULL,                        -- {"P1":0.82,...}
                                                --  （admission 任务为 {"admission":x,"schema":y,...}）
  disagreements JSON NULL,                      -- 分歧条目摘要
  created_by INT NULL,                          -- 触发本次计算的 users.id（归属列）
  computed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


# ============================================
# 计算路径选择
# ============================================
def _force_pure() -> bool:
    """环境变量强制走纯 Python 回退（测试/排查用）。"""
    return os.getenv("RELIABILITY_FORCE_PURE", "").strip().lower() in ("1", "true", "yes")


def _normalize_level(value_type: Optional[str]) -> str:
    """value_type → krippendorff 的 level_of_measurement。

    features.yaml 的 value_type 有 binary/ordinal/nominal 三种（框架文档 §2）：
    binary 是 nominal 的特例（0/1 两类），按 nominal 算。未知值按规范默认 nominal。
    """
    vt = str(value_type or "").strip().lower()
    if vt.startswith("ord"):
        return "ordinal"
    return "nominal"  # nominal / binary / 空 / 未知 → nominal


# ============================================
# units → 可靠性数据矩阵
# ============================================
def _is_usable_label(value: Any) -> bool:
    """取值类型门槛：标量（str/int/float/bool）才算标注值。

    dict/list 等结构化脏值与 NaN 按**缺失**跳过（缺失 = 该 coder 无有效取值），
    不让单条脏数据炸掉整个引擎，也不让它变成一个假的第三类别。

    字符串 "nan"/"NaN" 等（float() 可解析出 NaN 的串）同样按缺失：float('nan')
    是 krippendorff 库路径的缺失哨兵（np.nan），这类字符串数值化后与真缺失无法
    区分（R2 review 发现的 bug：库路径当缺失、纯 Python 回退当类别，两路径结果
    分叉），按缺失跳过与 float NaN 的口径一致。
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, float):
        return not math.isnan(value)
    if isinstance(value, str):
        try:
            return not math.isnan(float(value))
        except ValueError:
            return True
    return isinstance(value, (int, float))


def _units_to_matrix(
    units: dict, value_type: Optional[str]
) -> tuple[Optional[list[list[Optional[float]]]], list, list]:
    """把 {unit_id: {coder_id: value}} 转成 (编码人 × 单元) 矩阵。

    返回 (matrix, coder_ids, unit_ids)：matrix[i][j] 是第 i 个编码人对第 j 个
    单元的取值（float），缺失为 None（库路径再转 np.nan）。不可计算时返回
    (None, [], [])。

    数值化规则：
      * 全部值都能 float → 用原值（ordinal 必须如此，保序）；
      * 否则（nominal 字符串标签，或 ordinal 的非数值标签）→ 按排序后的去重
        标签映射成 0..V-1 的码。nominal 对任意双射编码不变；ordinal 的非数值
        标签按字典序（features.yaml 的 ordinal 特征均为数值编码，实际不会走到）。
    """
    if not isinstance(units, dict) or not units:
        return None, [], []

    unit_ids = list(units.keys())
    try:
        unit_ids.sort()
    except TypeError:
        unit_ids.sort(key=str)

    coder_ids: list = []
    seen: set = set()
    for inner in units.values():
        if not isinstance(inner, dict):
            continue  # 内层非 dict（脏结构）按无数据单元处理，不炸引擎（R4）
        for coder in inner:
            if coder not in seen:
                seen.add(coder)
                coder_ids.append(coder)
    try:
        coder_ids.sort()
    except TypeError:
        coder_ids.sort(key=str)
    if not coder_ids:
        return None, [], []

    raw = [
        v
        for inner in units.values()
        if isinstance(inner, dict)
        for v in inner.values()
        if _is_usable_label(v)
    ]
    if not raw:
        return None, [], []

    # 数值化决策与 level 无关：numeric → 原 float（ordinal 保序；nominal 对编码不变式）；
    # 非 numeric → sorted 去重标签的码（ordinal 依赖标签字典序，见函数 docstring）。
    # OverflowError：超大 int（float() 装不下）归入非 numeric 标签码分支，不炸引擎。
    numeric = True
    try:
        for v in raw:
            float(v)
    except (TypeError, ValueError, OverflowError):
        numeric = False

    if numeric:
        to_float = float
    else:
        distinct = sorted({str(v) for v in raw})
        codes = {label: float(i) for i, label in enumerate(distinct)}
        to_float = lambda v: codes[str(v)]  # noqa: E731

    matrix: list[list[Optional[float]]] = [
        [None] * len(unit_ids) for _ in coder_ids
    ]
    for j, unit_id in enumerate(unit_ids):
        inner = units[unit_id]
        if not isinstance(inner, dict):
            continue  # 内层非 dict：整个单元按缺失处理（与上面 raw/coder 收集同口径）
        for i, coder_id in enumerate(coder_ids):
            value = inner.get(coder_id)
            if not _is_usable_label(value):
                continue
            try:
                matrix[i][j] = to_float(value)
            except (TypeError, ValueError, OverflowError):
                # 单个无法数值化的脏值当缺失处理，不让整个引擎崩掉
                matrix[i][j] = None
    return matrix, coder_ids, unit_ids


# ============================================
# 纯 Python 回退实现（Krippendorff 2011 巧合矩阵公式）
# ============================================
def _alpha_pure(matrix: list[list[Optional[float]]], level: str) -> Optional[float]:
    """与 krippendorff 库同公式的纯 Python 实现（nominal/ordinal 两分支）。

    α = 1 − D_o / D_e，其中（对可配对单元，即 ≥2 个编码人的单元）：
      o_ck —— 巧合矩阵：每个单元内每对取值按 1/(n_u−1) 计入；
      n_v  —— 取值频次（巧合矩阵的列和）；
      D_o  = (1/n) Σ_{c≠k} o_ck δ_ck；D_e = (1/(n(n−1))) Σ_{c≠k} n_c n_k δ_ck；
      δ    —— nominal: 0/1；ordinal: (Σ_{g=i..k} n_g − (n_i+n_k)/2)²（与库的
              _ordinal_metric 逐项一致）。
    单元内只有 1 个取值（n_u=1）时不产生巧合，直接跳过（缺失容忍的核心）。
    """
    n_rows = len(matrix)
    n_cols = len(matrix[0]) if n_rows else 0
    distinct = sorted(
        {
            matrix[i][j]
            for i in range(n_rows)
            for j in range(n_cols)
            if matrix[i][j] is not None
        }
    )
    if not distinct:
        return None
    if len(distinct) == 1:
        return 1.0

    index = {v: i for i, v in enumerate(distinct)}
    n_values = len(distinct)
    o = [[0.0] * n_values for _ in range(n_values)]

    for j in range(n_cols):
        counts: dict[float, int] = {}
        for i in range(n_rows):
            v = matrix[i][j]
            if v is None:
                continue
            counts[v] = counts.get(v, 0) + 1
        n_u = sum(counts.values())
        if n_u < 2:
            continue  # 非可配对单元：缺失容忍，跳过
        denom = n_u - 1
        for a, count_a in counts.items():
            row = o[index[a]]
            for b, count_b in counts.items():
                row[index[b]] += count_a * (count_b - (1 if a == b else 0)) / denom

    n_v = [sum(o[c][k] for c in range(n_values)) for k in range(n_values)]
    n = sum(n_v)
    if n < 2:
        return None

    if level == "ordinal":
        d = [[0.0] * n_values for _ in range(n_values)]
        for i in range(n_values):
            for k in range(i + 1, n_values):
                segment = sum(n_v[i : k + 1]) - (n_v[i] + n_v[k]) / 2.0
                d[i][k] = d[k][i] = segment * segment
    else:  # nominal
        d = [
            [0.0 if i == k else 1.0 for k in range(n_values)]
            for i in range(n_values)
        ]

    observed = sum(
        o[i][k] * d[i][k] for i in range(n_values) for k in range(n_values)
    )
    expected = sum(
        n_v[i] * n_v[k] * d[i][k]
        for i in range(n_values)
        for k in range(n_values)
        if i != k
    )
    if expected <= 0:
        # 全部距离为 0（理论上进不来，防御）：视为完全一致
        return 1.0 if observed <= 0 else None
    return 1.0 - observed / (expected / (n - 1.0))


# ============================================
# 对外主函数 1：compute_alpha
# ============================================
def compute_alpha(units: dict, value_type: str) -> float | None:
    """计算 Krippendorff's α。

    Args:
        units: ``{unit_id: {coder_id: value}}``；缺失 = 某 coder 对该 unit 无取值
            （内层 dict 缺键，或值为 None）。
        value_type: ``'nominal' | 'ordinal'``（binary 归入 nominal；未知默认 nominal）。

    Returns:
        α（float）；数据不足以计算时返回 None —— 总观测值 < 2、没有任何单元被
        ≥2 个编码人标过（含单人标注）、矩阵为空。

    两条路径：优先 krippendorff 库（reliability_data 矩阵，缺失 np.nan）；库缺失
    或计算异常时自动落纯 Python 回退（同公式）。完全一致（只有一个去重值且存在
    可配对单元）返回 1.0。
    """
    level = _normalize_level(value_type)
    matrix, _coder_ids, unit_ids = _units_to_matrix(units, value_type)
    if matrix is None:
        return None

    n_units = len(unit_ids)
    per_unit_counts = [
        sum(1 for row in matrix if row[j] is not None) for j in range(n_units)
    ]
    total_observed = sum(per_unit_counts)
    # 不可计算：总观测 < 2，或没有任何单元被 ≥2 人标过（验收⑤单人数据）
    if total_observed < 2 or max(per_unit_counts, default=0) < 2:
        return None

    observed_values = {
        row[j]
        for j in range(n_units)
        if per_unit_counts[j] >= 2
        for row in matrix
        if row[j] is not None
    }
    if not observed_values:
        return None  # 冗余防御：无可配对数据（前面 max 检查已挡）
    if len(observed_values) == 1:
        # 可配对数据完全一致（验收①）。注意按**可配对单元**判断：只出现在单人
        # 单元里的取值不参与巧合，否则库会在 (e*d)=0 时给出 nan。
        return 1.0

    if KRIPPENDORFF_AVAILABLE and not _force_pure():
        try:
            data = np.asarray(matrix, dtype=np.float64)  # None → np.nan
            value = krippendorff.alpha(
                reliability_data=data, level_of_measurement=level
            )
        except Exception as exc:  # 库对退化输入会 raise，落回退而不是让页面崩
            logger.warning("krippendorff 库计算失败，改用纯 Python 回退: %s", exc)
        else:
            if value is None or (isinstance(value, float) and math.isnan(value)):
                return None
            return float(value)

    return _alpha_pure(matrix, level)


# ============================================
# 数据访问（直连 MySQL，参照 mysql_db.get_db_cursor 模式，SQL 全参数化）
# ============================================
# payload 解析复用 annotation_flow.parse_payload（R4 消重：原此处有一份逐字
# 复制的 _parse_payload，两处实现必然同步漂移，现以 annotation_flow 为唯一实现，
# 于文件头部 from src.annotation_flow import parse_payload 导入）。


def _fetch_submissions(category: str, task_type: str) -> Optional[list[dict]]:
    """取全部 status='submitted' 的提交；数据库不可用时返回 None（区别于空集）。"""
    sql = (
        "SELECT id, sense_id, coder_id, payload, status "
        "FROM annotation_submissions "
        "WHERE category = %s AND task_type = %s AND status = 'submitted' "
        "ORDER BY sense_id, coder_id"
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, (category, task_type))
            return list(cursor.fetchall())
    except Exception as exc:  # pymysql.Error / 表未建等，页面不能因此崩
        logger.error("读取 annotation_submissions 失败: %s", exc)
        return None


def _ensure_reliability_table() -> bool:
    """幂等建 reliability_runs（规范 §2 DDL 原样）+ 旧表补 created_by 列
    + (category, task_type) 查询索引。

    迁移幂等（R5 遗留 2）：CREATE TABLE IF NOT EXISTS 对已存在的旧表是空操作，
    故再用 INFORMATION_SCHEMA 查列，缺 created_by 则 ALTER TABLE ADD COLUMN ——
    重复调用不炸、不重复加列。失败返回 False（只算不写）。

    R5-10（P3）：页面按 (category, task_type) 过滤 reliability_runs
    （_fetch_submissions 同型的提交读路径在 annotation_submissions；
    runs 表的历史清单读 category+task_type），无索引时全表扫描。
    MySQL 8 无 CREATE INDEX IF NOT EXISTS —— 用 INFORMATION_SCHEMA.STATISTICS
    探测后建，幂等模式同 _migrate_created_by_column。
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute(RELIABILITY_RUNS_DDL)
            _migrate_created_by_column(cursor)
            _migrate_category_index(cursor)
        return True
    except Exception as exc:
        logger.error("建 reliability_runs 表失败: %s", exc)
        return False


def _migrate_created_by_column(cursor) -> None:
    """旧 reliability_runs 表补 created_by 归属列（幂等，R5 遗留 2）。

    INFORMATION_SCHEMA 查列不存在才 ALTER；库/表/列名不拼接用户输入，
    一律字面量（规范 §6-1 参数化口径：无值可参数化的标识符用常量）。
    """
    cursor.execute(
        "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'reliability_runs' "
        "AND COLUMN_NAME = 'created_by'"
    )
    row = cursor.fetchone()
    if row is None:
        return  # 假游标/异常通道拿不到结果：按无需迁移处理，不让建表流程炸掉
    if int(row.get("n") or 0) == 0:
        cursor.execute(
            "ALTER TABLE reliability_runs ADD COLUMN created_by INT NULL"
        )
        logger.info("reliability_runs 已补 created_by 归属列（幂等迁移）")


# runs 历史清单按 (category, task_type) 读取的复合索引名（R5-10）
_RELIABILITY_RUNS_CATEGORY_INDEX = "idx_reliability_runs_category"


def _migrate_category_index(cursor) -> None:
    """reliability_runs 补 (category, task_type) 复合索引（幂等，R5-10）。

    MySQL 8 不支持 CREATE INDEX IF NOT EXISTS —— 先探
    INFORMATION_SCHEMA.STATISTICS（同库同表同索引名任一行存在即视为已建，
    与 _index_exists 的既有迁移口径一致），缺则 CREATE INDEX。库/表/索引名
    不拼接用户输入，一律字面量（规范 §6-1：无值可参数化的标识符用常量）。
    """
    cursor.execute(
        "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'reliability_runs' "
        "AND INDEX_NAME = %s",
        (_RELIABILITY_RUNS_CATEGORY_INDEX,),
    )
    row = cursor.fetchone()
    if row is None:
        return  # 假游标/异常通道拿不到结果：按无需迁移处理，不让建表流程炸掉
    if int(row.get("n") or 0) == 0:
        cursor.execute(
            "CREATE INDEX idx_reliability_runs_category "
            "ON reliability_runs (category, task_type)"
        )
        logger.info("reliability_runs 已补 (category, task_type) 查询索引（幂等迁移）")


def _persist_run(result: dict, created_by: Optional[int] = None) -> None:
    """把一次计算写入 reliability_runs（overall DECIMAL(5,3)，JSON 列 dumps）。

    created_by：触发本次计算的 users.id（R5 遗留 2 归属列）；None 表示
    数据层直调（脚本/测试）不带归属。
    """
    overall = result.get("overall_alpha")
    # 脏值防御：会话里的 id 理论上恒为 int，转不动时按无归属处理而非炸页面
    try:
        created_by_value = None if created_by is None else int(created_by)
    except (TypeError, ValueError):
        created_by_value = None
        logger.warning("created_by 不是可整型化的值，按 NULL 落库: %r", created_by)
    sql = (
        "INSERT INTO reliability_runs "
        "(category, task_type, n_coders, n_units, overall_alpha, per_feature, "
        "disagreements, created_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
    )
    params = (
        result["category"],
        result["task_type"],
        int(result["n_coders"]),
        int(result["n_units"]),
        None if overall is None else round(float(overall), 3),
        json.dumps(result.get("per_feature") or {}, ensure_ascii=False),
        json.dumps(result.get("disagreements") or [], ensure_ascii=False),
        created_by_value,
    )
    try:
        with get_db_cursor() as cursor:
            cursor.execute(sql, params)
            result["run_id"] = getattr(cursor, "lastrowid", None)
    except Exception as exc:
        logger.error("写入 reliability_runs 失败: %s", exc)
        result["db_error"] = f"信度结果写入失败: {exc}"


def _load_features_meta(category: str) -> list[dict]:
    """读 configs/{category}/features.yaml 的特征元数据；文件不存在 → []。"""
    path = os.path.join(_REPO_ROOT, "configs", str(category), "features.yaml")
    if not os.path.isfile(path):
        logger.info("features.yaml 不存在（%s），特征 value_type 一律默认 nominal", path)
        return []
    try:
        import yaml

        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:
        logger.warning("features.yaml 解析失败（%s）: %s", path, exc)
        return []
    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list):
        return []
    return [f for f in features if isinstance(f, dict)]


def _resolve_value_type(features_meta: list[dict], feature_name: str) -> str:
    """按特征名（优先 code，其次 feature/name/id）在 features_meta 里查 value_type。

    查不到（features.yaml 缺失或未登记该特征）→ 默认 nominal（规范 §3）。
    """
    wanted = str(feature_name)
    for meta in features_meta or []:
        if not isinstance(meta, dict):
            continue
        candidates = {
            str(meta.get(key))
            for key in ("code", "feature", "name", "id")
            if meta.get(key) is not None
        }
        if wanted in candidates:
            return _normalize_level(meta.get("value_type"))
    return "nominal"


# ============================================
# 对外主函数 2：run_reliability
# ============================================
def run_reliability(
    category: str,
    task_type: str,
    features_meta: list[dict] | None = None,
    created_by: int | None = None,
) -> dict:
    """对某个 (category, task_type) 的全部 submitted 提交算信度并落库。

    Args:
        category: 范畴名（如 'motion'）。
        task_type: 'admission' | 'feature_coding' | 'alignment'。
        features_meta: 特征元数据列表（configs/motion/features.yaml 的 features 节，
            每项含 code/value_type）；None 时自动读 configs/{category}/features.yaml，
            文件不存在则全部特征按 nominal（规范 §3）。
        created_by: 触发本次计算的 users.id（落 reliability_runs.created_by 归属列，
            R5 遗留 2）；None 表示数据层直调不带归属。

    Returns:
        ``{category, task_type, overall_alpha, per_feature, n_coders, n_units,
        disagreements, ...}``。admission 任务 per_feature 的键是三个比对字段；
        feature_coding 的键是特征名。overall = 各指标 α 的均值（不可算的跳过；
        全不可算为 None）。数据库不可用时结果带 db_error 且不落库。
    """
    if task_type not in _TASK_FIELDS:
        raise ValueError(f"未知 task_type: {task_type!r}")

    if features_meta is None:
        features_meta = _load_features_meta(category)

    result: dict[str, Any] = {
        "category": category,
        "task_type": task_type,
        "overall_alpha": None,
        "per_feature": {},
        "n_coders": 0,
        "n_units": 0,
        "disagreements": [],
        "features_meta": features_meta,
    }

    rows = _fetch_submissions(category, task_type)
    if rows is None:
        result["db_error"] = "annotation_submissions 读取失败（数据库不可用或表未建）"
        return result

    result["n_coders"] = len({r["coder_id"] for r in rows})
    result["n_units"] = len({r["sense_id"] for r in rows})

    # sense_id → coder_id → payload
    payloads: dict[Any, dict[Any, dict]] = {}
    for row in rows:
        payloads.setdefault(row["sense_id"], {})[row["coder_id"]] = parse_payload(
            row.get("payload")
        )

    # 按任务类型确定「指标 → units」
    if task_type == "feature_coding":
        # 口径（R2 review 确认）：指标清单 = 实际提交 payload 里出现过的特征键的并集，
        # **不按 features.yaml 的 in_clustering 过滤** —— in_clustering/feature_scope
        # 是 Gower 聚类的列范围（跨词类通用框架.md features.yaml 的 clustering 节），
        # 设计规范 §3 对信度的要求是「feature_coding 对每特征按其 value_type 算」，
        # 且核验区特征（A1-A3，in_clustering=false）的 IAA 对 reviewer 同样有意义。
        # value_type 仍按 features_meta 解析（未登记 → nominal）。
        metric_names = sorted(
            {
                str(name)
                for by_coder in payloads.values()
                for payload in by_coder.values()
                for name in (payload.get("features") or {})
            }
        )
        units_by_metric: dict[str, dict] = {}
        for name in metric_names:
            units: dict[Any, dict[Any, Any]] = {}
            for sense_id, by_coder in payloads.items():
                for coder_id, payload in by_coder.items():
                    value = (payload.get("features") or {}).get(name)
                    if value is not None:
                        units.setdefault(sense_id, {})[coder_id] = value
            units_by_metric[name] = units
    else:
        units_by_metric = {}
        for field in _TASK_FIELDS[task_type]:
            units = {}
            for sense_id, by_coder in payloads.items():
                for coder_id, payload in by_coder.items():
                    value = payload.get(field)
                    if value is not None:
                        units.setdefault(sense_id, {})[coder_id] = value
            units_by_metric[field] = units

    # 逐指标算 α（value_type：admission 固定 nominal；特征按 features_meta）
    raw_alphas: dict[str, Optional[float]] = {}
    for name, units in units_by_metric.items():
        if task_type == "feature_coding":
            value_type = _resolve_value_type(features_meta, name)
        else:
            value_type = "nominal"
        raw_alphas[name] = compute_alpha(units, value_type)

    result["per_feature"] = {
        name: (None if alpha is None else round(alpha, 6))
        for name, alpha in raw_alphas.items()
    }
    computed = [a for a in raw_alphas.values() if a is not None]
    result["overall_alpha"] = (
        round(sum(computed) / len(computed), 6) if computed else None
    )

    # 分歧条目：同一单元被 ≥2 人标注且取值不同
    disagreements: list[dict] = []
    for name, units in units_by_metric.items():
        for sense_id in sorted(units, key=str):
            values = units[sense_id]
            if len(values) < 2:
                continue
            if len({str(v) for v in values.values()}) > 1:
                disagreements.append(
                    {
                        "sense_id": sense_id,
                        "field": name,
                        "values": {
                            str(coder_id): value
                            for coder_id, value in sorted(
                                values.items(), key=lambda kv: str(kv[0])
                            )
                        },
                    }
                )
    result["disagreements"] = disagreements

    # 落库（有提交才写；空跑不留垃圾行）
    if rows and _ensure_reliability_table():
        _persist_run(result, created_by=created_by)
    return result


# ============================================
# 对外主函数 3：render_reliability_page（Streamlit 视图）
# ============================================
# 样式沿用 app.py 的 HEADER_*/get_card_style 模式；design_system 不可用时内联等价值
try:
    from src.design_system import HEADER_H1, HEADER_H2, HEADER_H3, get_card_style
except ImportError:  # pragma: no cover - 仅在 design_system 缺失的环境生效
    # RV1-4：降级值与 design_system 同步改独立属性声明（旧 font 简写
    # "bold 2.5rem/1.2 system-ui" 放进 style 属性会被浏览器整条丢弃）。
    HEADER_H1 = "font-size: 2.5rem; font-weight: 700; line-height: 1.2;"
    HEADER_H2 = "font-size: 2rem; font-weight: 700; line-height: 1.3;"
    HEADER_H3 = "font-size: 1.5rem; font-weight: 700; line-height: 1.4;"

    def get_card_style() -> str:
        # RV1-3：卡底是常亮浅色面，暗色主题下补深字才可读（与 design_system
        # get_card_style 的 color: #1a202c 同口径）。
        return (
            "background-color: #f7fafc; color: #1a202c; padding: 24px;"
            " border-radius: 12px; border: 1px solid #e2e8f0;"
            " box-shadow: 0 2px 8px rgba(0,0,0,0.05);"
        )


def _list_categories() -> tuple[str, ...]:
    """可选范畴：优先 Agent D 的 category_pack.CATEGORIES，回退扫 configs/ 子目录。"""
    try:
        from src.category_pack import CATEGORIES

        cats = CATEGORIES() if callable(CATEGORIES) else CATEGORIES
        cats = tuple(str(c) for c in cats)
        if cats:
            return cats
    except Exception:
        pass
    configs_dir = os.path.join(_REPO_ROOT, "configs")
    if os.path.isdir(configs_dir):
        found = sorted(
            d
            for d in os.listdir(configs_dir)
            if os.path.isdir(os.path.join(configs_dir, d))
            and not d.startswith(("_", "."))
        )
        if found:
            return tuple(found)
    return ("motion",)


def _build_disagreement_rows(disagreements: list[dict]) -> list[dict]:
    """分歧条目 → 展示用行（长表：每 coder 一行）。"""
    rows = []
    for item in disagreements:
        for coder_id, value in item.get("values", {}).items():
            rows.append(
                {
                    "义位 sense_id": item.get("sense_id"),
                    "字段/特征": str(item.get("field", "")),
                    "coder_id": coder_id,
                    "取值": html.escape(str(value)),
                }
            )
    return rows


def _export_csv(result: dict) -> bytes:
    """导出 CSV（utf-8-sig，Excel 打开中文不乱码）：信度汇总 + 逐特征 + 分歧长表。

    每个单元格过 security.sanitize_csv_cell（R1-P2a）：分歧条目的 value /
    feature 名等可能带用户标注的自由文本，以 = + - @ \\t \\r 开头时前置单引号，
    防 Excel 公式注入（与 app.py 标注导出、template_engine 模板导出同一实现）。
    """
    buf = io.StringIO()
    writer = csv.writer(buf)

    def _write_row(cells) -> None:
        writer.writerow([sanitize_csv_cell(c) for c in cells])

    _write_row(["# 信度报告（AI-assisted IAA：全员可见 AI 草稿口径）"])
    _write_row(["category", result.get("category")])
    _write_row(["task_type", result.get("task_type")])
    _write_row(["n_coders", result.get("n_coders")])
    _write_row(["n_units", result.get("n_units")])
    overall = result.get("overall_alpha")
    _write_row(["overall_alpha", "" if overall is None else f"{overall:.3f}"])
    _write_row([])
    _write_row(["feature/field", "alpha", "达标(>=0.7)"])
    for name, alpha in (result.get("per_feature") or {}).items():
        if alpha is None:
            _write_row([name, "", "不可算"])
        else:
            _write_row([name, f"{alpha:.3f}", "是" if alpha >= LOW_ALPHA_THRESHOLD else "否"])
    _write_row([])
    _write_row(["sense_id", "field", "coder_id", "value"])
    for item in result.get("disagreements") or []:
        for coder_id, value in item.get("values", {}).items():
            _write_row([item.get("sense_id"), item.get("field"), coder_id, value])
    return buf.getvalue().encode("utf-8-sig")


def _per_feature_chart(per_feature: dict) -> None:
    """每特征 α 条形图：plotly（<0.7 红色高亮 + 0.7 达标线），无 plotly 退 st.bar_chart。"""
    names = list(per_feature.keys())
    values = [0.0 if v is None else float(v) for v in per_feature.values()]
    try:
        import plotly.graph_objects as go

        # RV1-6：条色取深档（#c53030 白字 5.47:1 / #2f855a 4.54:1），浅色条
        # 在白底图区不达 WCAG 非文本 3:1（旧 #e53e3e 4.13 / #48bb78 2.43）。
        colors = [
            "#c53030" if (per_feature[n] is None or per_feature[n] < LOW_ALPHA_THRESHOLD)
            else "#2f855a"
            for n in names
        ]
        fig = go.Figure(
            go.Bar(
                x=names,
                y=values,
                marker_color=colors,
                text=[("—" if per_feature[n] is None else f"{per_feature[n]:.3f}") for n in names],
                textposition="outside",
            )
        )
        fig.add_hline(
            y=LOW_ALPHA_THRESHOLD,
            line_dash="dash",
            line_color="#c05621",  # RV1-6：深档警示色（白底 4.57:1；旧 #ed8936 2.55:1）
            annotation_text=f"{LOW_ALPHA_THRESHOLD} 达标线",
        )
        fig.update_layout(
            yaxis_range=[-0.1, 1.1],
            yaxis_title="Krippendorff's α",
            height=380,
            margin=dict(l=10, r=10, t=30, b=10),
        )
        import streamlit as st

        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        import pandas as pd
        import streamlit as st

        st.bar_chart(pd.Series(values, index=names))


def render_reliability_page() -> None:
    """📐 信度报告页（reviewer/admin）：overall 大数字 + 每特征条形 + 低信度高亮 + 分歧表 + CSV 导出。

    权限在函数入口判定（规范 §6-4）；未登录/无角色一律拒绝。
    R1-2 收口（施工规范 §14 批次 12）：判定从 legacy role 列改为**有效六角色集**
    （users_db.effective_six_roles，允许集与 app._PAGE_ACCESS_SIX["reliability"]
    同口径：dict_admin / sys_admin / reviewer）—— 授予式 reviewer（legacy 列
    viewer 但 user_roles 已授予）不再被拦在页外；legacy admin 经映射两位一体
    自然通过；viewer/annotator/editor 单角色照旧拒绝。
    """
    import streamlit as st

    # --- 角色门（入口判定，不信任前端）---
    # 会话用户结构守卫与 app._current_user / users_admin_page._current_user 同口径：
    # 只认 dict（规范 §6-5），脏值（如误写入的非 dict）按未登录拦截，不抛异常。
    user = st.session_state.get("user")
    user = user if isinstance(user, dict) else {}
    if not (effective_six_roles(user or None) & {"dict_admin", "sys_admin", "reviewer"}):
        st.warning("信度报告仅对 reviewer / admin 开放。")
        return

    st.markdown(
        f"<h1 style='{HEADER_H1}'>📐 信度报告</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<span style='{_badge_css()}'>{IAA_CAPTION}</span>",
        unsafe_allow_html=True,
    )
    st.caption(
        "同一 (category, task_type) 的全部 status='submitted' 提交参与计算；"
        "缺失值容忍（某编码人缺若干义位不报错）；α 不可算显示为 —。"
    )

    # --- 选择器 ---
    categories = _list_categories()
    col_cat, col_task, _ = st.columns([2, 2, 3])
    with col_cat:
        category = st.selectbox("范畴", list(categories), index=0)
    with col_task:
        task_type = st.selectbox(
            "任务类型",
            ["admission", "feature_coding", "alignment"],
            format_func={
                "admission": "admission · 准入三字段",
                "feature_coding": "feature_coding · 逐特征",
                "alignment": "alignment · 对齐",
            }.get,
        )

    # R5 遗留 2：归属列 —— 记录本次计算由哪个会话用户触发（reliability_runs.created_by）。
    # role gate 已保证 user 是登录会话；id 脏值由 _persist_run 兜底转 None。
    result = run_reliability(category, task_type, created_by=user.get("id"))

    if result.get("db_error"):
        st.error(f"数据库不可用：{result['db_error']}")
        return
    if result.get("n_coders", 0) == 0:
        st.info("该 (范畴, 任务类型) 下还没有已提交的标注。")
        return

    per_feature: dict = result.get("per_feature") or {}
    overall = result.get("overall_alpha")

    # --- overall 大数字 + 汇总卡 ---
    if overall is None:
        overall_text = "—"
        # RV1-6：状态彩字换深档（白底对比 ≥4.5:1）—— 旧 #a0aec0 2.26:1、
        # #48bb78 2.43:1、#e53e3e 4.13:1 全不达 AA。
        verdict = "<span style='color:#4a5568'>尚不可计算（可用编码人/重叠单元不足）</span>"
    elif overall >= LOW_ALPHA_THRESHOLD:
        overall_text = f"{overall:.3f}"
        verdict = "<span style='color:#2f855a'>达标（α ≥ 0.7）</span>"
    else:
        overall_text = f"{overall:.3f}"
        verdict = "<span style='color:#c53030'>未达标（α &lt; 0.7，需仲裁/重标）</span>"

    st.markdown(
        f"""
        <div style='{get_card_style()}'>
          <div style='font-size:0.9rem;color:#4a5568;margin-bottom:4px;'>
            Overall Krippendorff's α · {html.escape(str(category))} / {task_type}
          </div>
          <div style='font-size:3rem;font-weight:700;line-height:1.1;'>{overall_text}</div>
          <div style='margin-top:6px;'>{verdict}</div>
          <div style='margin-top:6px;color:#4a5568;font-size:0.85rem;'>
            编码人 {result.get('n_coders', 0)} 人 · 义位单元 {result.get('n_units', 0)} 个
             · 指标数 {len(per_feature)}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --- 每特征 α 条形图 ---
    if per_feature:
        st.markdown(
            f"<h3 style='{HEADER_H3}'>按指标/特征的 α</h3>",
            unsafe_allow_html=True,
        )
        _per_feature_chart(per_feature)

        # 低信度特征高亮（< 0.7）
        low = {n: v for n, v in per_feature.items() if v is not None and v < LOW_ALPHA_THRESHOLD}
        uncomputable = [n for n, v in per_feature.items() if v is None]
        if low:
            names = "、".join(
                f"{html.escape(str(n))}（{v:.3f}）" for n, v in sorted(low.items())
            )
            st.warning(f"低信度指标（α < {LOW_ALPHA_THRESHOLD}，建议进仲裁清单）：{names}")
        if uncomputable:
            st.info(
                "以下指标因数据不足（如仅单人标注）暂不可算："
                + "、".join(html.escape(str(n)) for n in uncomputable)
            )
        if not low and not uncomputable:
            st.success("全部指标 α ≥ 0.7，信度达标。")

        # 明细表
        st.dataframe(
            [
                {
                    "指标": name,
                    "α": ("—" if v is None else round(float(v), 3)),
                    "达标": ("—" if v is None else ("是" if v >= LOW_ALPHA_THRESHOLD else "否")),
                }
                for name, v in per_feature.items()
            ],
            use_container_width=True,
            hide_index=True,
        )

    # --- 分歧条目表 + CSV 导出 ---
    disagreements = result.get("disagreements") or []
    st.markdown(
        f"<h3 style='{HEADER_H3}'>分歧条目（{len(disagreements)}）</h3>",
        unsafe_allow_html=True,
    )
    if disagreements:
        rows = _build_disagreement_rows(disagreements)
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.caption("没有检测到分歧（各编码人对所有共同标注单元的取值一致，或重叠样本不足）。")

    csv_bytes = _export_csv(result)
    _export_disabled = not (per_feature or disagreements)
    st.download_button(
        "📥 导出信度报告 CSV（含分歧清单）",
        data=csv_bytes,
        file_name=f"reliability_{category}_{task_type}.csv",
        mime="text/csv",
        disabled=_export_disabled,
    )
    # R7-14：灰置须注明原因（与其他导出口径一致）。权限闸在本页入口
    # （reviewer/dict_admin/sys_admin 之外整页拒渲染），这里只补数据闸的原因。
    if _export_disabled:
        st.caption(
            "导出已灰置：尚无可导出的明细（无逐特征结果，也无分歧条目）——"
            "提交量增长后再导出。"
        )


def _badge_css() -> str:
    """口径标注徽章的内联样式（与 design_system.get_badge_style 等价，避免额外依赖）。

    RV1-1：旧 HIGHLIGHT_COLOR #ecc94b 黄底白字实测 1.61:1 —— 主路径经
    design_system 深档 #975a16（白字 5.54:1）＋按底色自动选深/浅字修复；
    降级分支同步对齐同一深档视觉，两种环境都 ≥4.5:1。
    """
    try:
        from src.design_system import get_badge_style, HIGHLIGHT_COLOR

        return get_badge_style(HIGHLIGHT_COLOR)
    except ImportError:
        return (
            "display:inline-block;background-color:#975a16;color:#ffffff;"
            "padding:4px 16px;border-radius:12px;font-size:0.875rem;font-weight:500;"
        )
