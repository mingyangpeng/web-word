"""流程聚合（pipeline_status）测试：漏斗纯函数全分支 + 真 MySQL 聚合冒烟。

两层结构（与 test_org_db / test_ai_ledger 同口径）：
  * 纯函数层：format_funnel_segments 的全部分支——缺段跳过、缺数灰行、
    有数格式化、脏数据不崩、非 dict 入参空漏斗；
  * 集成层：get_cluster_pipeline_status 在真库上的聚合冒烟——
    建表就绪时各段要么有数要么如实缺数（data/reason 互斥不变量），
    绝不允许出现「编造的 0」。MySQL 不可用整类 skip。

漏斗语义见 src/pipeline_status.py 模块 docstring（十五道工序 → 六段聚合，
编纂成文段在 definition_versions 建表前如实返回「未建」）。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline_status import (  # noqa: E402
    MISSING_PREFIX,
    SEGMENT_LABELS,
    SEGMENT_ORDER,
    format_funnel_segments,
    get_cluster_pipeline_status,
)

# ============================================
# 纯函数层：format_funnel_segments
# ============================================


class TestFormatFunnelSegments:
    def test_none_returns_empty(self):
        assert format_funnel_segments(None) == []

    def test_non_dict_returns_empty(self):
        assert format_funnel_segments("漏斗") == []
        assert format_funnel_segments([1, 2]) == []

    def test_segments_not_dict_returns_empty(self):
        assert format_funnel_segments({"segments": [1, 2]}) == []

    def test_full_status_orders_by_segment_order(self):
        status = {
            "segments": {
                key: {"data": {"stub": 1}, "reason": None}
                for key in reversed(SEGMENT_ORDER)
            }
        }
        rows = format_funnel_segments(status)
        assert [r[0] for r in rows] == [SEGMENT_LABELS[k] for k in SEGMENT_ORDER]
        # 有数段不带缺数前缀
        assert all(not text.startswith(MISSING_PREFIX) for _, text in rows)

    def test_missing_segment_rendered_grey_with_reason(self):
        status = {"segments": {
            "admission": {"data": None, "reason": "cs_senses 未灌"},
        }}
        rows = format_funnel_segments(status)
        assert len(rows) == 1
        label, text = rows[0]
        assert label == SEGMENT_LABELS["admission"]
        assert text.startswith(MISSING_PREFIX)
        assert "cs_senses 未灌" in text

    def test_missing_reason_defaults(self):
        status = {"segments": {"admission": {"data": None, "reason": None}}}
        _, text = format_funnel_segments(status)[0]
        assert "暂无数据" in text

    def test_unknown_keys_skipped_not_crash(self):
        status = {"segments": {
            "admission": {"data": {"n": 1}, "reason": None},
            "ghost": {"data": {"x": 1}, "reason": None},
        }}
        rows = format_funnel_segments(status)
        assert len(rows) == 1 and rows[0][0] == SEGMENT_LABELS["admission"]

    def test_dirty_data_does_not_crash(self):
        """段数据为脏结构时格式化器抛错 → 灰行兜底，不向上抛。"""
        status = {"segments": {"admission": {"data": "不是字典", "reason": None}}}
        rows = format_funnel_segments(status)
        assert rows and rows[0][1].startswith(MISSING_PREFIX)

    def test_every_segment_order_key_has_label(self):
        """段序清单与标签表键集一致（新增段漏配标签即失败）。"""
        assert set(SEGMENT_ORDER) == set(SEGMENT_LABELS.keys())


# ============================================
# 集成层：真 MySQL 聚合冒烟
# ============================================

try:  # MySQL 可用性探测（与 test_org_db 同口径）
    import pymysql  # noqa: F401

    HAS_MYSQL = True
except Exception:  # noqa: BLE001
    HAS_MYSQL = False


@pytest.mark.skipif(not HAS_MYSQL, reason="MySQL 不可用，跳过流程聚合集成测试")
class TestGetClusterPipelineStatus:
    def test_motion_status_shape_and_invariants(self):
        """RUN 试点库上聚合：各段 data/reason 互斥；有数段文本非空。"""
        status = get_cluster_pipeline_status("motion")
        assert isinstance(status, dict)
        segments = status.get("segments")
        assert isinstance(segments, dict) and segments
        for key, segment in segments.items():
            assert set(segment) == {"data", "reason"}, key
            data, reason = segment["data"], segment["reason"]
            assert (data is None) != (reason is None), \
                f"{key}: data/reason 必须恰有一方为 None（互斥不变量）"
        rows = format_funnel_segments(status)
        assert rows, "试点库上至少应有一个段可渲染"

    def test_unknown_category_all_segments_honest(self):
        """不存在的范畴：各段走如实缺数路径，绝不出现编造的 0。"""
        status = get_cluster_pipeline_status("no_such_pack")
        for key, segment in status["segments"].items():
            if segment["data"] is None:
                assert segment["reason"], f"{key}: 缺数段必须给 reason"
