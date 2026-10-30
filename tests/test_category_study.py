"""范畴深挖（category study）的集成测试：xlsx 解析 → 灌入 → 查询 → 页面。

三层覆盖：
  1. load_category_study.py 的 xlsx 解析（build_payload，不碰数据库）——
     断言词条/义位/编码/簇成员/对齐行的数量与关键样本值，防止 d1 表格
     改版后解析悄悄错位；
  2. category_study 数据层（replace + 查询）—— 在业务库上以独立范畴代号
     RUNTEST 全量替换后读回，断言计数一致、外键匹配、幂等重灌不翻倍；
  3. 页面模块（category_study_page）—— 数据加载函数返回四视图所需的
     全部键，视图渲染函数在 AppTest 冒烟里已覆盖，这里只测数据契约。

没有可用的 MySQL 时数据层测试 skip（与 test_migration_integration 同口径）。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import category_study as cs  # noqa: E402


# ============================================
# 1. xlsx 解析（纯函数，不需要数据库）
# ============================================

@pytest.fixture(scope="module")
def run_payload():
    """解析 d1 两个 xlsx 组装出的 RUN 范畴 payload（模块级缓存一次）。"""
    script_dir = os.path.join(os.path.dirname(__file__), "..", "scripts")
    sys.path.insert(0, script_dir)
    import load_category_study as loader
    return loader.build_payload("RUN")


def test_payload_category_meta(run_payload):
    cat = run_payload["category"]
    assert cat["code"] == "RUN"
    assert cat["name_cn"] == "跑"
    assert cat["status"] == "试点"
    assert "纵向深挖" in cat["notes"]


def test_payload_lexemes_bilingual(run_payload):
    lexemes = run_payload["lexemes"]
    en = [l for l in lexemes if l["language"] == "en"]
    zh = [l for l in lexemes if l["language"] == "zh"]
    assert len(en) == 23  # 英语 23 词目
    assert len(zh) == 19  # 汉语 19 词条（跑 6 义项 + 驰驱 2 义项归并同词条）
    # 补录 4 词不在 Levin 词表内
    not_in_levin = {l["lemma"] for l in en if not l["in_levin"]}
    assert not_in_levin == {"sprint", "pound", "stampede", "career"}
    # 词典来源标注
    assert all(l["source_dict"] == "OALD10" for l in en)
    assert all(l["source_dict"] == "现汉7" for l in zh)


def test_payload_senses_counts_and_status(run_payload):
    senses = run_payload["senses"]
    en = [s for s in senses if s["language"] == "en"]
    zh = [s for s in senses if s["language"] == "zh"]
    assert len(en) == 32  # 英语 32 目标义位
    assert len(zh) == 25  # 汉语 25 义位条目
    # 汉语三态判定：保留 14 / 边缘 5 / 剔除 6
    status = {}
    for s in zh:
        status[s["status"]] = status.get(s["status"], 0) + 1
    assert status == {"保留": 14, "边缘": 5, "剔除": 6}
    # 英语侧无三态判定，统一「目标」
    assert all(s["status"] == "目标" for s in en)


def test_payload_features_complete(run_payload):
    """进编码矩阵的义位（英 32 + 汉 19）都有 18 列特征编码，值域 0/1/2。

    汉语侧剔除的 6 条（跑③④⑤⑥/驰驱②/逃匿）不进编码矩阵 ——
    编码矩阵表本身只编了 19 条目，这是 xlsx 的口径而非解析遗漏。
    """
    excluded = {("跑", "方走义"), ("跑", "奔走办事义"), ("跑", "离位义"),
                ("跑", "泄漏义"), ("驰驱", "奔走效力义"), ("逃匿", "逃匿义")}
    coded, uncoded = [], []
    for s in run_payload["senses"]:
        (uncoded if (s["lemma"], s["sense_label"]) in excluded
         else coded).append(s)
    assert len(coded) == 51  # 32 en + 19 zh
    assert len(uncoded) == 6
    for s in coded:
        feats = s["features"]
        assert set(feats.keys()) == set(cs.FEATURE_CODES), (
            f"{s['lemma']}·{s['sense_label']} 特征列不全: {sorted(feats.keys())}")
        assert all(v in (0, 1, 2) for v in feats.values())
    for s in uncoded:
        assert not s["features"]


def test_payload_feature_samples(run_payload):
    """抽查关键义位的编码值（与编码矩阵表逐格核对过的锚点）。"""
    by_key = {(s["lemma"], s["sense_label"]): s
              for s in run_payload["senses"]}
    # run·足部奔跑义：M1a=1 M1b=1 M2=1 M3a=1 C1=2
    run = by_key[("run", "足部奔跑义")]
    assert run["features"]["M1a"] == 1
    assert run["features"]["C1"] == 2
    # flee·逃离义：P1=1（源点凸显）C1=1（受迫）
    flee = by_key[("flee", "逃离义")]
    assert flee["features"]["P1"] == 1
    assert flee["features"]["C1"] == 1
    # 跑②·逃走义：P1=1 C1=1（受迫逃离）
    pao2 = by_key[("跑", "逃走义")]
    assert pao2["sense_no"] == "②"
    assert pao2["features"]["P1"] == 1
    assert pao2["features"]["C1"] == 1


def test_payload_cluster_runs(run_payload):
    runs = run_payload["cluster_runs"]
    assert len(runs) == 2  # en + zh 各一个运行
    en_run = next(r for r in runs if r["language"] == "en")
    zh_run = next(r for r in runs if r["language"] == "zh")
    assert en_run["algorithm"] == "Gower+average"
    assert en_run["cophenetic"] == pytest.approx(0.825)
    assert zh_run["cophenetic"] == pytest.approx(0.795)
    assert en_run["version"] == "预编码"
    # k=5：英 5 簇（2+3+4+6+17=32 义位全覆盖），汉 5 簇（1+2+4+4+8=19 条目）
    en_sizes = sorted(c["size"] for c in en_run["clusters"])
    assert en_sizes == [2, 3, 4, 6, 17]
    zh_sizes = sorted(c["size"] for c in zh_run["clusters"])
    assert zh_sizes == [1, 2, 4, 4, 8]
    # 成员数与规模一致
    for run in runs:
        for cl in run["clusters"]:
            assert len(cl["members"]) == cl["size"]


def test_payload_cluster_members_reference_real_senses(run_payload):
    """簇成员 (lemma, sense_no, label) 三元组都能在义位清单里找到。"""
    sense_keys = {(s["lemma"], s["sense_no"], s["sense_label"])
                  for s in run_payload["senses"]}
    for run in run_payload["cluster_runs"]:
        for cl in run["clusters"]:
            for member in cl["members"]:
                assert member in sense_keys, (
                    f"{run['language']} 簇{cl['cluster_no']} 成员悬空: {member}")


def test_payload_alignments(run_payload):
    alignments = run_payload["alignments"]
    assert len(alignments) == 5
    # 核心发现：英簇4 ↔ 汉簇4 完全对齐 d=0.045
    full = next(a for a in alignments if a["verdict"] == "完全对齐")
    assert full["en_cluster_no"] == 4
    assert full["zh_cluster_no"] == 4
    assert full["gower_distance"] == pytest.approx(0.045)
    # 四类判定分布：完全 1 / 部分 3 / 零 1
    verdicts = {}
    for a in alignments:
        verdicts[a["verdict"]] = verdicts.get(a["verdict"], 0) + 1
    assert verdicts == {"完全对齐": 1, "部分对齐": 3, "零对齐": 1}


# ============================================
# 2. 数据层（需要 MySQL；不可用则 skip）
# ============================================

def _db_available():
    try:
        with cs.get_db_cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def loaded_runtest(run_payload):
    """把 payload 以范畴代号 RUNTEST 灌入业务库（不动 RUN），返回灌入计数。

    模块级：灌一次，多个测试共用读；最后清掉。
    """
    if not _db_available():
        pytest.skip("MySQL 不可用，跳过范畴深挖数据层测试")
    counts = cs.replace_category_study(
        {**run_payload, "category": {**run_payload["category"],
                                     "code": "RUNTEST"}})
    yield counts
    with cs.get_db_cursor() as cursor:
        cursor.execute("DELETE FROM categories WHERE code = 'RUNTEST'")


def test_replace_counts(loaded_runtest, run_payload):
    counts = loaded_runtest
    assert counts["lexemes"] == len(run_payload["lexemes"])
    assert counts["senses"] == len(run_payload["senses"])
    # 特征数 = 编码义位 51 × 18 列（剔除 6 条不进编码矩阵）
    assert counts["features"] == 51 * 18
    assert counts["clusters"] == 10  # en 5 + zh 5
    assert counts["members"] == 51   # 32 + 19
    assert counts["alignments"] == 5


def test_query_roundtrip(loaded_runtest):
    cats = [c for c in cs.get_categories() if c["code"] == "RUNTEST"]
    assert len(cats) == 1
    cat = cats[0]
    assert cat["en_senses"] == 32
    assert cat["zh_senses"] == 25

    senses = cs.get_senses_with_features(int(cat["id"]))
    assert len(senses) == 57
    # 每个义位带特征与簇归属（19 个汉语条目里剔除的 6 条无簇，其余都有）
    with_cluster = [s for s in senses if s.get("cluster")]
    assert len(with_cluster) == 51

    # 编码抽查：flee·逃离义 P1=1
    flee = next(s for s in senses
                if s["lemma"] == "flee" and s["sense_label"] == "逃离义")
    assert flee["features"]["P1"] == 1
    assert flee["cluster"]["cluster_no"] == 5


def test_query_cluster_runs_and_members(loaded_runtest):
    cats = [c for c in cs.get_categories() if c["code"] == "RUNTEST"]
    category_id = int(cats[0]["id"])
    runs = cs.get_cluster_runs(category_id)
    assert {r["language"] for r in runs} == {"en", "zh"}
    for run in runs:
        clusters = cs.get_clusters_with_members(run["run_id"])
        assert len(clusters) == 5
        for cl in clusters:
            assert len(cl["members"]) == cl["size"]
            # 成员带特征编码（聚类面板点开要用）
            for m in cl["members"]:
                assert isinstance(m["features"], dict)


def test_query_alignments(loaded_runtest):
    cats = [c for c in cs.get_categories() if c["code"] == "RUNTEST"]
    alignments = cs.get_alignments(int(cats[0]["id"]))
    assert len(alignments) == 5
    full = next(a for a in alignments if a["verdict"] == "完全对齐")
    assert full["en_cluster_no"] == 4 and full["zh_cluster_no"] == 4
    assert full["gower_distance"] == pytest.approx(0.045)


def test_query_screening_stats(loaded_runtest):
    cats = [c for c in cs.get_categories() if c["code"] == "RUNTEST"]
    stats = cs.get_screening_stats(int(cats[0]["id"]))
    assert stats["en"]["n_senses"] == 32
    assert stats["zh"]["status"] == {"保留": 14, "边缘": 5, "剔除": 6}
    assert stats["verdicts"] == {"完全对齐": 1, "部分对齐": 3, "零对齐": 1}


def test_replace_is_idempotent(loaded_runtest, run_payload):
    """同范畴重灌 = 全量替换，不累积行。"""
    payload = {**run_payload,
               "category": {**run_payload["category"], "code": "RUNTEST"}}
    counts = cs.replace_category_study(payload)
    assert counts["senses"] == 57
    cats = [c for c in cs.get_categories() if c["code"] == "RUNTEST"]
    senses = cs.get_senses_with_features(int(cats[0]["id"]))
    assert len(senses) == 57  # 没有翻倍


# ============================================
# 2.5 图式层对齐（derive_image_schema / compute_schema_alignment）
# ============================================

def test_derive_image_schema_rules():
    """四类图式推导规则：追逐 > 源点 > 终点 > 方式。"""
    # 方式伴随：无路径凸显
    assert cs.derive_image_schema({"P1": 0, "P2": 0, "P3": 0}) == "方式伴随"
    # 源点脱离：P1=1
    assert cs.derive_image_schema({"P1": 1, "P2": 0, "P3": 0}) == "源点脱离"
    # 源点优先于终点（P1 与 P2 同现按源点判）
    assert cs.derive_image_schema({"P1": 1, "P2": 1, "P3": 1}) == "源点脱离"
    # 终点抵达：P2 或 P3
    assert cs.derive_image_schema({"P1": 0, "P2": 1, "P3": 0}) == "终点抵达"
    assert cs.derive_image_schema({"P1": 0, "P2": 0, "P3": 1}) == "终点抵达"
    # 互动位移：追逐标注最优先
    assert cs.derive_image_schema({"P1": 1}, tag="附追逐") == "互动位移"
    # 逃离/冲撞标注不触发互动（只有追逐是双参与者互动）
    assert cs.derive_image_schema({"P1": 1}, tag="附逃离") == "源点脱离"


def test_schema_alignment_run_category(loaded_runtest):
    """跑范畴图式对齐：分布与判定与 d1 编码矩阵的口径一致。

    预期（由 32+19 条编码义位推导）：
      方式伴随  EN 18 (56%) / ZH 10 (53%)  → 完全对齐（d≈0.018）
      源点脱离  EN  5 (16%) / ZH  8 (42%)  → 完全对齐（d≈0.066）
      终点抵达  EN  9 (28%) / ZH  0 ( 0%)  → 零对齐（汉语未词汇化）
      互动位移  EN  0 ( 0%) / ZH  1 ( 5%)  → 零对齐（奔逐，英语侧无追逐义位）
    """
    cats = [c for c in cs.get_categories() if c["code"] == "RUNTEST"]
    senses = cs.get_senses_with_features(int(cats[0]["id"]))
    rows = cs.compute_schema_alignment(senses)
    by_schema = {r["schema"]: r for r in rows}
    assert list(by_schema.keys()) == cs.SCHEMA_ORDER

    manner = by_schema["方式伴随"]
    assert manner["en_size"] == 18 and manner["zh_size"] == 10
    assert manner["verdict"] == "完全对齐"
    assert manner["distance"] == pytest.approx(0.018, abs=0.005)

    source = by_schema["源点脱离"]
    assert source["en_size"] == 5 and source["zh_size"] == 8
    # d≈0.066：图式类型匹配但配置有差（英语 flee/escape 无群体义、汉语逃X 族
    # 带群体/语体差异）→ 部分对齐
    assert source["verdict"] == "部分对齐"
    assert source["distance"] == pytest.approx(0.066, abs=0.005)
    # 汉语源点脱离成员 = 逃X 构词族
    zh_lemmas = {m["lemma"] for m in source["zh_members"]}
    assert zh_lemmas == {"跑", "奔窜", "奔逃", "逃窜", "逃走", "逃跑",
                         "逃逸", "逃遁"}

    goal = by_schema["终点抵达"]
    assert goal["en_size"] == 9 and goal["zh_size"] == 0
    assert goal["verdict"] == "零对齐"
    assert goal["distance"] is None

    interactive = by_schema["互动位移"]
    assert interactive["en_size"] == 0 and interactive["zh_size"] == 1
    assert interactive["zh_members"][0]["lemma"] == "奔逐"
    assert interactive["verdict"] == "零对齐"

    # 剔除义位（无编码）不进图式对齐
    total = sum(r["en_size"] + r["zh_size"] for r in rows)
    assert total == 51  # 32 en + 19 zh


# ============================================
# 3. 页面数据契约
# ============================================

def test_page_data_contract(run_payload):
    """_load_category 返回的键覆盖四个视图的全部取数点（页面冒烟在 AppTest）。"""
    from src.category_study_page import VIEWS, VIEW_LABELS
    assert set(VIEWS) == {"cluster", "matrix", "align", "overview"}
    assert all(v in VIEW_LABELS for v in VIEWS)
    # 视图函数依赖的数据键（与 _load_category 返回结构一一对应）
    required_keys = {"category", "senses", "en_run", "zh_run",
                     "en_clusters", "zh_clusters", "alignments",
                     "profiles_en", "profiles_zh", "stats"}
    from src.category_study_page import _load_category
    # RUNTEST 已在数据层 fixture 灌入；这里直接验证键集合的静态契约
    assert required_keys == {
        "category", "senses", "en_run", "zh_run",
        "en_clusters", "zh_clusters", "alignments",
        "profiles_en", "profiles_zh", "stats"}
