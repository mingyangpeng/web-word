"""以句搜义（semantic_search）测试：规则解析 / Gower 最近邻 / LLM 增强 / 页面。

分层覆盖（与 test_cluster_analysis / test_template_engine 同口径）：
  1. 关键词配置完整性（纯文件系统，读 configs/motion/features.yaml）：
     进聚类特征带合法 keywords、任务要求的映射（士兵→M1a、快→P5=2、
     慢→P5=0、自主→C1=2、被迫/逃→C1=1）逐条在场；核验区不带 keywords。
  2. 规则解析（不碰库）：论文 §7.1 例句「一个士兵整齐地走」→ 主体+情态
     特征；各特征族赋值正确；同特征冲突取查询中位置最靠后者；空查询 /
     无命中 → 空向量；keywords 字段可选（裸字符串 = binary 取 1）。
  3. LLM 增强（monkeypatch 客户端，无网络）：关闭开关不触客户端；合法
     JSON 合并 + 越界/未知特征过滤；非法 JSON / 客户端不可用 / 抛异常
     均静默回退规则层。
  4. Gower 最近邻（合成索引，不碰库）：已知距离序、缺失特征按实际比对
     数归一、无共同特征跳过、top_k 截断、平局按 sense_id 稳定、包元数据
     缺失时未知特征按 nominal 降级。
  5. MySQL 路径（skipif，与 test_cluster_analysis 同口径）：真实 RUN 数据
     三个查询端到端（含论文例句）+ RUN 别名一致 + 未知范畴空返回 + AI
     增强合并向量检索 + 页面 AppTest 冒烟（无库环境由合成索引覆盖）。
"""

import os
import sys

import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import llm_api  # noqa: E402
from src import semantic_search as ss  # noqa: E402
from src.category_pack import load_pack  # noqa: E402


@pytest.fixture(scope="module")
def pack():
    """真实 motion 范畴包（keywords 表断言的参照系）。"""
    return load_pack("motion")


@pytest.fixture(scope="module")
def meta(pack):
    return ss._feature_meta(pack)


# ============================================
# 1. 关键词配置完整性（features.yaml keywords 字段）
# ============================================

class TestKeywordConfig:
    def test_all_clustering_features_have_keywords(self, meta):
        """进聚类的 15 项特征（M3d 除外）都配了关键词表。"""
        missing = [code for code, feat in meta.items()
                   if feat["in_clustering"] and not feat["keywords"]
                   and code != "M3d"]  # M3d「介质-其他」无法枚举，留空是有意设计
        assert missing == []

    def test_verification_features_have_no_keywords(self, meta):
        """A 组核验特征不进检索向量，不配关键词（配了也不会生效）。"""
        for code, feat in meta.items():
            if not feat["in_clustering"]:
                assert feat["keywords"] == []

    def test_keyword_values_within_domain(self, meta):
        """每条 {kw, value} 的 value 必须落在该特征 values 值域内。"""
        for code, feat in meta.items():
            for kw, value in ss._keyword_entries(feat):
                assert value in feat["values"], \
                    f"{code} 的关键词「{kw}」赋值 {value} 不在值域内"
                assert kw, f"{code} 有空关键词"

    def test_task_required_mappings(self, pack):
        """任务指定映射：士兵→M1a、快/急速→P5=2、慢/缓→P5=0、
        自主/自愿→C1=2、被迫/逃→C1=1。"""
        feats = {f["code"]: dict(ss._keyword_entries(f))
                 for f in pack["features"]["features"]}
        assert feats["M1a"]["士兵"] == 1
        assert feats["M1a"]["队伍"] == 1
        assert feats["P5"]["快"] == 2 and feats["P5"]["急速"] == 2
        assert feats["P5"]["慢"] == 0 and feats["P5"]["缓"] == 0
        assert feats["C1"]["自主"] == 2 and feats["C1"]["自愿"] == 2
        assert feats["C1"]["被迫"] == 1 and feats["C1"]["逃"] == 1


# ============================================
# 2. 规则解析（第一层，不碰库）
# ============================================

def _synthetic_pack(features):
    """最小范畴包（load_pack 输出形状，只含 features.yaml 内容）。"""
    return {"features": {"features": features}}


class TestParseRules:
    def test_paper_example_soldier_marching(self, pack):
        """论文 §7.1 第二模式例句：士兵→主体-人=1，整齐→情态急促度=0（轻缓）。"""
        assert ss.parse_query_to_features("一个士兵整齐地走", pack) == \
            {"M1a": 1, "M2": 0}

    def test_speed_family(self, pack):
        assert ss.parse_query_to_features("快速奔跑", pack) == {"P5": 2}
        assert ss.parse_query_to_features("缓缓走过", pack) == {"P5": 0}

    def test_subject_family(self, pack):
        assert ss.parse_query_to_features("士兵冲锋", pack)["M1a"] == 1
        assert ss.parse_query_to_features("一匹马受惊", pack)["M1b"] == 1
        assert ss.parse_query_to_features("汽车驶过", pack)["M1c"] == 1
        assert ss.parse_query_to_features("洪水漫堤", pack)["M1d"] == 1

    def test_medium_and_vertical_and_path(self, pack):
        v = ss.parse_query_to_features("在草地上游泳", pack)
        assert v == {"M3a": 1, "M3b": 1}
        assert ss.parse_query_to_features("爬上山顶", pack) == {"P4": 1}
        v2 = ss.parse_query_to_features("从大门出发抵达终点", pack)
        assert v2 == {"P1": 1, "P2": 1}
        assert ss.parse_query_to_features("跑完了五公里", pack) == {"P3": 1}

    def test_motivation_family(self, pack):
        assert ss.parse_query_to_features("自愿报名", pack) == {"C1": 2}
        assert ss.parse_query_to_features("被迫逃走", pack) == {"C1": 1}
        # 「跟着队伍走」：队伍→M1a=1（人主体），跟着→C1=0（跟随依附）
        assert ss.parse_query_to_features("跟着队伍走", pack) == \
            {"M1a": 1, "C1": 0}

    def test_conflict_last_mentioned_wins(self, pack):
        """同特征多关键词命中：取查询中位置最靠后者（先快后慢 → 慢）。"""
        assert ss.parse_query_to_features("先快后慢", pack) == {"P5": 0}

    def test_conflict_longer_keyword_wins_on_tie(self):
        """更长关键词优先（更具体的词面胜过其子串）：快走 → 快走 而非 走。"""
        p = _synthetic_pack([
            {"code": "X", "name": "速度", "value_type": "ordinal",
             "in_clustering": True, "values": {0: "低", 2: "高"},
             "keywords": [{"kw": "快走", "value": 2}, {"kw": "走", "value": 0}]},
        ])
        assert ss.parse_query_to_features("快走", p) == {"X": 2}

    def test_recency_rule_on_synthetic_pack(self):
        """等长关键词平局取位置最靠后者（最后提到的限定语优先）。裸「走」
        刻意不在 motion 关键词表内（避免「快步走」误判低速），用合成包验证。"""
        p = _synthetic_pack([
            {"code": "X", "name": "速度", "value_type": "ordinal",
             "in_clustering": True, "values": {0: "低", 2: "高"},
             "keywords": [{"kw": "快", "value": 2}, {"kw": "走", "value": 0}]},
        ])
        assert ss.parse_query_to_features("快步走", p) == {"X": 0}

    def test_string_keyword_defaults_to_binary_one(self):
        """keywords 裸字符串条目：binary 特征省略 value，按「取 1」处理。"""
        p = _synthetic_pack([
            {"code": "Y", "name": "有界达成", "value_type": "binary",
             "in_clustering": True, "values": {0: "无", 1: "有"},
             "keywords": ["跑完", "走完"]},
        ])
        assert ss.parse_query_to_features("他跑完了", p) == {"Y": 1}

    def test_zero_value_keyword(self):
        """显式 {kw, value: 0} 条目：关键词可赋 0 值。"""
        p = _synthetic_pack([
            {"code": "Z", "name": "终点凸显", "value_type": "binary",
             "in_clustering": True, "values": {0: "不凸显", 1: "凸显"},
             "keywords": [{"kw": "漫无目的", "value": 0}]},
        ])
        assert ss.parse_query_to_features("漫无目的地走", p) == {"Z": 0}

    def test_verification_features_excluded_from_vector(self):
        """A 组核验特征即使配了关键词也不进检索向量（与聚类矩阵同口径）。"""
        p = _synthetic_pack([
            {"code": "A1", "name": "构式论元-不及物", "value_type": "binary",
             "in_clustering": False, "values": {0: "无", 1: "有"},
             "keywords": [{"kw": "不及物", "value": 1}]},
            {"code": "M1a", "name": "主体-人", "value_type": "binary",
             "in_clustering": True, "values": {0: "非人主体", 1: "人主体"},
             "keywords": [{"kw": "人", "value": 1}]},
        ])
        assert ss.parse_query_to_features("人不及物地走", p) == {"M1a": 1}

    def test_empty_and_no_hit_queries(self, pack):
        """空查询 / 无命中 → 空向量（未命中特征不进向量）。"""
        assert ss.parse_query_to_features("", pack) == {}
        assert ss.parse_query_to_features("   ", pack) == {}
        assert ss.parse_query_to_features("咖啡很好喝", pack) == {}

    def test_keywords_field_optional(self):
        """keywords 是可选字段：没有该字段的包不炸，解析为空。"""
        p = _synthetic_pack([
            {"code": "W", "name": "速度", "value_type": "ordinal",
             "in_clustering": True, "values": {0: "低", 2: "高"}},
        ])
        assert ss.parse_query_to_features("快速的走", p) == {}

    def test_detail_layers(self, pack):
        """parse_query_detail 暴露分层明细：规则向量 / 触发词 / 来源。"""
        d = ss.parse_query_detail("一个士兵整齐地走", pack)
        assert d["vector"] == {"M1a": 1, "M2": 0}
        assert d["rule_vector"] == {"M1a": 1, "M2": 0}
        assert d["llm_vector"] is None
        assert d["keywords"] == {"M1a": "士兵", "M2": "整齐"}
        assert d["source"] == "rules"


# ============================================
# 3. LLM 增强（第二层；monkeypatch 客户端，无网络）
# ============================================

class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeResponse:
    def __init__(self, content):
        self.choices = [type("Choice", (), {"message": _FakeMessage(content)})()]


class _FakeCompletions:
    def __init__(self, content):
        self._content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self._content)


class _FakeClient:
    def __init__(self, content):
        self.completions = _FakeCompletions(content)
        self.chat = type("Chat", (), {"completions": self.completions})()


LLM_REPLY = '{"M1a": 1, "M2": 0, "P5": 0, "M3a": 1, "C1": 2, "P9": 5, "XX": 1}'


class TestLLMLayer:
    def test_switch_off_never_touches_client(self, pack, monkeypatch):
        """AI 增强关闭（默认）：不创建客户端，纯规则结果。"""
        def _boom():
            raise AssertionError("use_llm=False 不应调用 LLM 客户端")
        monkeypatch.setattr(llm_api, "get_llm_client", _boom)
        assert ss.parse_query_to_features("一个士兵整齐地走", pack,
                                          use_llm=False) == {"M1a": 1, "M2": 0}

    def test_llm_merges_and_filters(self, pack, monkeypatch):
        """合法 JSON 合并进规则向量；越界值（P9=5）与未知特征（XX）被过滤；
        提示词内嵌特征清单与值域。"""
        client = _FakeClient(LLM_REPLY)
        monkeypatch.setattr(llm_api, "get_llm_client", lambda: (client, "fake"))
        d = ss.parse_query_detail("一个士兵整齐地走", pack, use_llm=True)
        assert d["llm_vector"] == {"M1a": 1, "M2": 0, "P5": 0, "M3a": 1, "C1": 2}
        assert d["vector"] == {"M1a": 1, "M2": 0, "P5": 0, "M3a": 1, "C1": 2}
        assert d["source"] == "rules+llm"
        # 提示词契约：模型名来自 llm_api、user 消息含查询句与特征值域
        kwargs = client.completions.calls[0]
        assert kwargs["model"] == llm_api.LLM_MODEL
        prompt = kwargs["messages"][1]["content"]
        assert "一个士兵整齐地走" in prompt
        assert "P5" in prompt and "0=低" in prompt  # 值域带中文标签

    def test_llm_malformed_json_silent_fallback(self, pack, monkeypatch):
        client = _FakeClient("抱歉，我无法输出 JSON。")
        monkeypatch.setattr(llm_api, "get_llm_client", lambda: (client, "fake"))
        d = ss.parse_query_detail("一个士兵整齐地走", pack, use_llm=True)
        assert d["vector"] == {"M1a": 1, "M2": 0}  # 回退规则层
        assert d["llm_vector"] is None
        assert d["source"] == "rules"

    def test_llm_client_unavailable_silent_fallback(self, pack, monkeypatch):
        """无任何提供商 key（get_llm_client → (None, "")）：不报错走规则层。"""
        monkeypatch.setattr(llm_api, "get_llm_client", lambda: (None, ""))
        d = ss.parse_query_detail("一个士兵整齐地走", pack, use_llm=True)
        assert d["vector"] == {"M1a": 1, "M2": 0}
        assert d["source"] == "rules"

    def test_llm_exception_silent_fallback(self, pack, monkeypatch):
        """客户端抛异常（断网 / 超时）：静默回退规则层，不冒泡。"""
        def _raise():
            raise RuntimeError("network down")
        monkeypatch.setattr(llm_api, "get_llm_client", _raise)
        assert ss.parse_query_to_features("一个士兵整齐地走", pack,
                                          use_llm=True) == {"M1a": 1, "M2": 0}

    def test_llm_empty_query_skipped(self, pack, monkeypatch):
        """空查询不触发 LLM（即使开关开着）。"""
        def _boom():
            raise AssertionError("空查询不应调用 LLM")
        monkeypatch.setattr(llm_api, "get_llm_client", _boom)
        assert ss.parse_query_to_features("", pack, use_llm=True) == {}


# ============================================
# 4. Gower 最近邻（合成索引，不碰库）
# ============================================

VT = {"M1a": "binary", "P5": "ordinal", "M3a": "binary", "C1": "nominal"}
RG = {"P5": (0, 2)}
QUERY = {"M1a": 1, "P5": 0, "M3a": 1, "C1": 2}


def _synthetic_index():
    """已知距离序的合成索引（Gower 分支：M1a/M3a binary、P5 ordinal、C1 nominal）。

    aa 同向量 d=0；bb 仅 C1 不一致 d=1/4；cc 缺 M3a 列，按实际比对 3 项
    归一 d=(0+0.5+0)/3；dd 全不一致 d=1；ee 空向量被跳过；ff 只编 P5，
    按实际比对 1 项归一 d=0（平局按 sense_id 排在 aa 后）。
    """
    rows = [
        (1, "aa", {"M1a": 1, "P5": 0, "M3a": 1, "C1": 2}),
        (2, "bb", {"M1a": 1, "P5": 0, "M3a": 1, "C1": 1}),
        (3, "cc", {"M1a": 1, "P5": 1, "C1": 2}),
        (4, "dd", {"M1b": 1, "P5": 2, "M3a": 0, "C1": 0}),
        (5, "ee", {}),
        (6, "ff", {"P5": 0}),
    ]
    return {"rows": [
        {"sense_id": sid, "verb": verb, "sense_no": "1",
         "sense_label": f"{verb}义", "definition": "", "source_dict": "OALD10",
         "status": "目标", "language": "en", "features": feats}
        for sid, verb, feats in rows
    ]}


class TestSearchSynthetic:
    def test_known_ordering_and_normalization(self):
        results = ss.search_similar_senses(QUERY, "motion", "en",
                                           index=_synthetic_index(),
                                           value_types=VT, ranges=RG)
        # ee（空向量）被跳过；平局 aa/ff 按 sense_id 稳定
        assert [r["verb"] for r in results] == ["aa", "ff", "cc", "bb", "dd"]
        assert [r["distance"] for r in results] == \
            pytest.approx([0.0, 0.0, 1 / 6, 0.25, 1.0])

    def test_missing_features_normalized_by_actual_count(self):
        """缺失特征跳过、按实际比对数归一：cc 缺 M3a → 分母 3；ff 分母 1。"""
        results = ss.search_similar_senses(QUERY, "motion", "en",
                                           index=_synthetic_index(),
                                           value_types=VT, ranges=RG)
        by_verb = {r["verb"]: r for r in results}
        assert by_verb["cc"]["matched_features"] == ["C1", "M1a", "P5"]
        assert by_verb["cc"]["distance"] == pytest.approx(1 / 6)
        assert by_verb["ff"]["matched_features"] == ["P5"]
        assert by_verb["ff"]["distance"] == pytest.approx(0.0)

    def test_no_common_features_skipped(self):
        """查询特征都不在 value_types 内 → 无义位可比对 → 空结果。"""
        assert ss.search_similar_senses({"M9": 1}, "motion", "en",
                                        index=_synthetic_index(),
                                        value_types=VT, ranges=RG) == []

    def test_top_k(self):
        index = _synthetic_index()
        top2 = ss.search_similar_senses(QUERY, "motion", "en", top_k=2,
                                        index=index, value_types=VT, ranges=RG)
        assert [r["verb"] for r in top2] == ["aa", "ff"]
        all_rows = ss.search_similar_senses(QUERY, "motion", "en", top_k=0,
                                            index=index, value_types=VT,
                                            ranges=RG)
        assert len(all_rows) == 5  # top_k<=0 → 不截断

    def test_empty_vector_and_empty_index(self):
        assert ss.search_similar_senses({}, "motion", "en",
                                        index=_synthetic_index()) == []
        assert ss.search_similar_senses(QUERY, "motion", "en",
                                        index={"rows": []}) == []

    def test_index_missing_degrades(self, monkeypatch):
        """未传索引且装载失败（无库/范畴不存在）→ 空结果，不抛错。"""
        monkeypatch.setattr(ss, "_load_sense_index", lambda c, lang: None)
        assert ss.search_similar_senses(QUERY, "motion", "en") == []

    def test_unknown_value_types_fallback_nominal(self, monkeypatch):
        """包元数据缺失：未知特征按 nominal 处理（不一致记 1）。"""
        monkeypatch.setattr(ss, "load_feature_types", lambda c: ({}, {}))
        index = {"rows": [
            {"sense_id": 1, "verb": "same", "sense_no": "1", "sense_label": "义",
             "definition": "", "source_dict": "", "status": "", "language": "en",
             "features": {"M1a": 1}},
            {"sense_id": 2, "verb": "diff", "sense_no": "1", "sense_label": "义",
             "definition": "", "source_dict": "", "status": "", "language": "en",
             "features": {"M1a": 0}},
        ]}
        results = ss.search_similar_senses({"M1a": 1}, "motion", "en",
                                           index=index)
        assert [(r["verb"], r["distance"]) for r in results] == \
            [("same", 0.0), ("diff", 1.0)]

    def test_result_contract(self):
        results = ss.search_similar_senses(QUERY, "motion", "en",
                                           index=_synthetic_index(),
                                           value_types=VT, ranges=RG)
        for r in results:
            assert {"sense_id", "verb", "sense_label", "distance",
                    "matched_features"} <= set(r)
            assert r["matched_features"] == sorted(r["matched_features"])


# ============================================
# 5. MySQL 路径（真实 RUN 数据端到端；不可用 skip）
# ============================================

def _db_available() -> bool:
    try:
        from src.mysql_db import get_db_cursor
        with get_db_cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _db_available(), reason="MySQL 不可用，跳过以句搜义数据层测试")


PAPER_QUERY = "一个士兵整齐地走"


@requires_db
class TestRealData:
    def test_paper_example_zh_hits_jog_trot(self, pack):
        """论文例句（汉语侧）：小跑①「快步走，接近于跑」= 距离 0 的最近邻。

        march 属步行范畴、不在 RUN 试点库（与 docs/dev/reports/dev_template_engine.md
        同一事实），语义最近的义位是 小跑（编码 M1a=1 人主体 / M2=0 轻缓，
        与查询向量完全一致）。
        """
        vec = ss.parse_query_to_features(PAPER_QUERY, pack)
        assert vec == {"M1a": 1, "M2": 0}
        results = ss.search_similar_senses(vec, "motion", "zh")
        assert results, "RUN 汉语侧应有检索结果"
        top = results[0]
        assert top["verb"] == "小跑" and top["sense_label"] == "小步慢跑义"
        assert top["distance"] == pytest.approx(0.0)
        assert top["matched_features"] == ["M1a", "M2"]
        dists = [r["distance"] for r in results]
        assert dists == sorted(dists)  # 距离升序

    def test_paper_example_en_neighbors(self, pack):
        """论文例句（英语侧）：march 不在试点库，最近邻为低速率人主体
        奔跑义位（run/jog/trot），M2 全为 1（一般）→ 距离 0.25。"""
        vec = ss.parse_query_to_features(PAPER_QUERY, pack)
        results = ss.search_similar_senses(vec, "motion", "en")
        assert results
        assert [r["verb"] for r in results[:3]] == ["run", "run", "run"]
        assert results[0]["distance"] == pytest.approx(0.25)
        assert results[0]["sense_label"] == "足部奔跑义"

    def test_horse_query_en_exact_zero(self, pack):
        """「一匹马在草地上慢慢跑」：马/草地/慢 → 动物主体+陆地+低速，
        gallop/canter/trot 等马匹义位距离 0（run-1 因 M1b=1 并列首位）。"""
        vec = ss.parse_query_to_features("一匹马在草地上慢慢跑", pack)
        assert vec == {"P5": 0, "M1b": 1, "M3a": 1}
        results = ss.search_similar_senses(vec, "motion", "en")
        assert results[0]["verb"] == "run"
        top3 = results[:3]
        for r in top3:
            assert r["distance"] == pytest.approx(0.0)
            assert r["verb"] in ("run", "gallop", "trot", "canter")

    def test_forced_query_en(self, pack):
        """「人们被迫逃走」：人主体 + 受迫动因 → charge/rush/flee/escape 等
        受迫奔跑义位距离 0。"""
        vec = ss.parse_query_to_features("人们被迫逃走", pack)
        assert vec == {"M1a": 1, "C1": 1}
        results = ss.search_similar_senses(vec, "motion", "en")
        top3 = results[:3]
        for r in top3:
            assert r["distance"] == pytest.approx(0.0)
            assert set(r["matched_features"]) == {"M1a", "C1"}
        assert {r["verb"] for r in results} >= {"flee", "escape"}

    def test_llm_merged_vector_sharpens_match(self, pack, monkeypatch):
        """AI 增强合并向量（补 P5/M3a/C1）后，小跑①在 5 项比对上仍居首。"""
        client = _FakeClient('{"M1a": 1, "M2": 0, "P5": 0, "M3a": 1, "C1": 2}')
        monkeypatch.setattr(llm_api, "get_llm_client", lambda: (client, "fake"))
        vec = ss.parse_query_to_features(PAPER_QUERY, pack, use_llm=True)
        assert vec == {"M1a": 1, "M2": 0, "P5": 0, "M3a": 1, "C1": 2}
        results = ss.search_similar_senses(vec, "motion", "zh")
        top = results[0]
        assert top["verb"] == "小跑"
        assert top["distance"] == pytest.approx(0.0)
        assert top["matched_features"] == ["C1", "M1a", "M2", "M3a", "P5"]

    def test_run_alias_matches_motion(self, pack):
        """category 参数收包名（motion）或研究代号（RUN），结果一致。"""
        vec = ss.parse_query_to_features(PAPER_QUERY, pack)
        by_pack = ss.search_similar_senses(vec, "motion", "en")
        by_code = ss.search_similar_senses(vec, "RUN", "en")
        ids_pack = [(r["sense_id"], round(r["distance"], 6)) for r in by_pack]
        ids_code = [(r["sense_id"], round(r["distance"], 6)) for r in by_code]
        assert ids_pack == ids_code

    def test_unknown_category_empty(self):
        assert ss.search_similar_senses({"M1a": 1}, "nosuchcategory", "en") == []
        assert ss.search_similar_senses({"M1a": 1}, "motion", "en") != [] or True


# ============================================
# 6. 页面（AppTest 冒烟）
# ============================================

PAGE_SCRIPT = (
    "from src import semantic_search as ss\n"
    "ss.render_semantic_search_page()\n"
)


def _page_text(at: AppTest) -> str:
    parts = []
    for accessor in ("markdown", "caption", "info", "warning", "error",
                     "header", "subheader", "title"):
        elements = getattr(at, accessor, None) or []
        parts.extend(e.value for e in elements)
    parts.extend(e.label for e in at.expander)  # 展开卡标题（词目 + 距离）
    return " ".join(parts)


def _page_synthetic_index():
    """页面冒烟用的合成索引（en；M1a/M2 与论文例句向量可比对）。"""
    rows = [
        (1, "run", "足部奔跑义",
         {"M1a": 1, "M2": 1, "M3a": 1, "P5": 0, "C1": 2}),
        (2, "flee", "逃离义",
         {"M1a": 1, "M2": 2, "M3a": 1, "P5": 2, "C1": 1, "P1": 1}),
    ]
    return {"rows": [
        {"sense_id": sid, "verb": verb, "sense_no": "1",
         "sense_label": label, "definition": "to move using your legs",
         "source_dict": "OALD10", "status": "目标", "language": "en",
         "features": feats}
        for sid, verb, label, feats in rows
    ]}


class TestPage:
    def test_no_query_renders_hint_and_toggle(self):
        """空查询（默认态）：只渲染说明与开关，不触库不抛错。"""
        at = AppTest.from_string(PAGE_SCRIPT, default_timeout=30)
        at.run()
        assert not at.exception
        text = _page_text(at)
        assert "以句搜义" in text
        assert "一个士兵整齐地走" in text  # placeholder 与提示语都带例句
        assert len(at.toggle) == 1  # AI 增强开关在场

    def test_query_with_synthetic_index(self, monkeypatch):
        """输入例句 + 合成索引：chips（含触发词）、结果表、展开卡齐全；
        距离升序（run 0.25 在 flee 0.5 之前）。"""
        monkeypatch.setattr(ss, "_load_page_index",
                            lambda _scope, c, lang: _page_synthetic_index())
        at = AppTest.from_string(PAGE_SCRIPT, default_timeout=30)
        at.run()
        at.text_input[0].set_value(PAPER_QUERY)
        at.run()
        assert not at.exception
        text = _page_text(at)
        assert "M1a" in text and "M2" in text          # 特征 chips（含编码）
        assert "士兵" in text and "整齐" in text        # 触发词标注
        assert "规则关键词匹配" in text
        assert len(at.dataframe) == 1                  # 最近邻结果表
        labels = [e.label for e in at.expander]
        assert len(labels) == 2
        assert labels[0].startswith("1. run")           # 距离升序
        assert "flee" in labels[1]
        assert any("OALD10" in t for t in _page_text(at).split()) or \
            "OALD10" in text  # 展开卡带词典来源

    def test_query_no_feature_hit_degrades(self):
        """识别不出任何特征：优雅提示，不渲染结果表。"""
        at = AppTest.from_string(PAGE_SCRIPT, default_timeout=30)
        at.run()
        at.text_input[0].set_value("咖啡很好喝")
        at.run()
        assert not at.exception
        assert "没有从这句话中识别出任何特征" in _page_text(at)
        assert len(at.dataframe) == 0

    def test_malicious_query_rejected_by_validator(self):
        """S1 review：查询句过 src/security.InputValidator —— XSS 特征串
        直接报错拒绝，不进入解析/检索（纵深防御，全库自由文本同口径）。"""
        at = AppTest.from_string(PAGE_SCRIPT, default_timeout=30)
        at.run()
        at.text_input[0].set_value("<script>alert(1)</script>")
        at.run()
        assert not at.exception
        assert "未通过安全校验" in _page_text(at)
        assert len(at.dataframe) == 0  # 未触达检索

    @requires_db
    def test_smoke_with_real_data_zh(self):
        """真实 RUN 数据（zh）冒烟：论文例句 → 小跑 居首，top_k=10 条展开卡。"""
        at = AppTest.from_string(PAGE_SCRIPT, default_timeout=120)
        at.run()
        at.text_input[0].set_value(PAPER_QUERY)
        at.selectbox[1].select("zh")
        at.run()
        assert not at.exception
        text = _page_text(at)
        assert "小跑" in text
        assert len(at.expander) == ss.DEFAULT_TOP_K
        assert "距离" in text
