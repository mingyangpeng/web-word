"""
常量定义测试

确保关键常量值未被意外修改、映射完整。
"""

from config import constants as C


class TestRelationConstants:
    def test_relation_types_complete(self):
        assert set(C.RELATION_TYPES) == {
            "synonym", "antonym", "related", "homophone", "family",
        }

    def test_relation_labels_cover_all_types(self):
        for rt in C.RELATION_TYPES:
            assert rt in C.RELATION_LABELS, f"缺少 {rt} 的标签"

    def test_relation_color_map_cover_all_types(self):
        for rt in C.RELATION_TYPES:
            assert rt in C.RELATION_COLOR_MAP, f"缺少 {rt} 的颜色"


class TestCategoryConstants:
    def test_all_categories_complete(self):
        assert set(C.ALL_CATEGORIES) == {
            "path", "manner", "purpose", "participant",
        }

    def test_category_color_map_cover_all(self):
        for cat in C.ALL_CATEGORIES:
            assert cat in C.CATEGORY_COLOR_MAP


class TestDifficultyConstants:
    def test_difficulty_labels(self):
        assert C.DIFFICULTY_LABELS["easy"].endswith("简单")
        assert C.DIFFICULTY_LABELS["medium"].endswith("中等")
        assert C.DIFFICULTY_LABELS["hard"].endswith("困难")
        assert C.DIFFICULTY_LABELS["advanced"].endswith("高级")

    def test_difficulty_alias_map(self):
        # 别名应解析到标准值
        assert C.DIFFICULTY_ALIAS_MAP["simple"] == "easy"
        assert C.DIFFICULTY_ALIAS_MAP["difficult"] == "hard"
        assert C.DIFFICULTY_ALIAS_MAP["medium"] == "medium"


class TestNumericConstants:
    def test_positive_values(self):
        assert C.DB_POOL_SIZE > 0
        assert C.GLM_API_TIMEOUT_SECONDS > 0
        assert C.MAX_DISPLAY_WORDS > 0
        assert C.NODE_SIZE_LARGE > C.NODE_SIZE_DEFAULT

    def test_sigma_edge_width_range(self):
        assert C.SIGMA_EDGE_WIDTH_MIN < C.SIGMA_DEFAULT_EDGE_WIDTH < C.SIGMA_EDGE_WIDTH_MAX
