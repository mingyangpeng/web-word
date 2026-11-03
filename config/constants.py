"""
项目常量定义

集中管理所有魔术数字、字符串常量、颜色映射等，
避免在代码中硬编码，便于统一维护和调整。
"""

# ========== 应用基础配置 ==========
APP_NAME = "单词知识图谱 Web 应用"
APP_VERSION = "1.1.0"
DEFAULT_PAGE_SIZE = 20
MAX_DISPLAY_WORDS = 9          # 单词详情页卡片最大显示数
MAX_QUICK_QUESTIONS_COLS = 3   # 快捷问题网格列数
MAX_RELATIONS_DISPLAY = 6      # 关系网络每类最大显示数

# ========== 数据库相关 ==========
DB_POOL_SIZE = 5
DB_DEFAULT_LIMIT = 1000        # get_all_words 默认查询上限
DB_SEARCH_LIMIT = 50
DB_FETCH_ALL_BATCH = 500       # 批量获取每批大小
WORD_HISTORY_MAX = 5           # 单词查询历史保留数量

# ========== LLM 服务相关 ==========
GLM_API_TIMEOUT_SECONDS = 30
GLM_DEFAULT_TEMPERATURE = 0.7
GLM_MAX_TOKENS_CHAT = 800
GLM_MAX_TOKENS_ANALYZE = 1000
GLM_MAX_TOKENS_RELATIONS = 1500
GLM_MAX_TOKENS_EXAMPLES = 1000
GLM_DEFAULT_MODEL = "glm-4-flash"

# ========== 关系类型枚举 ==========
RELATION_SYNONYM = "synonym"
RELATION_ANTONYM = "antonym"
RELATION_RELATED = "related"
RELATION_HOMOPHONE = "homophone"
RELATION_FAMILY = "family"

RELATION_TYPES = (
    RELATION_SYNONYM,
    RELATION_ANTONYM,
    RELATION_RELATED,
    RELATION_HOMOPHONE,
    RELATION_FAMILY,
)

# 关系类型对应的中文标签（用于 UI 展示）
RELATION_LABELS = {
    RELATION_SYNONYM: "🟢 近义词",
    RELATION_ANTONYM: "🔴 反义词",
    RELATION_RELATED: "🔵 相关词",
    RELATION_HOMOPHONE: "🟡 同音词",
    RELATION_FAMILY: "🟣 词族词",
}

# ========== 范畴分类 ==========
CATEGORY_PATH = "path"
CATEGORY_MANNER = "manner"
CATEGORY_PURPOSE = "purpose"
CATEGORY_PARTICIPANT = "participant"

ALL_CATEGORIES = (
    CATEGORY_PATH,
    CATEGORY_MANNER,
    CATEGORY_PURPOSE,
    CATEGORY_PARTICIPANT,
)

# ========== 颜色映射 ==========
# 关系类型 -> 颜色（用于图谱节点）
RELATION_COLOR_MAP = {
    RELATION_SYNONYM: "#2ecc71",    # 绿色
    RELATION_ANTONYM: "#e74c3c",    # 红色
    RELATION_RELATED: "#3498db",    # 蓝色
    RELATION_HOMOPHONE: "#f1c40f",  # 黄色
    RELATION_FAMILY: "#9b59b6",     # 紫色
}

# 范畴 -> 颜色
CATEGORY_COLOR_MAP = {
    CATEGORY_PATH: "#2ecc71",
    CATEGORY_MANNER: "#3498db",
    CATEGORY_PURPOSE: "#f39c12",
    CATEGORY_PARTICIPANT: "#9b59b6",
}

DEFAULT_NODE_COLOR = "#95a5a6"     # 灰色（默认）
DEFAULT_EDGE_COLOR = "#bdc3c7"
HIGHLIGHT_COLOR = "#ff6b6b"

# 节点尺寸
NODE_SIZE_DEFAULT = 10
NODE_SIZE_LARGE = 15
NODE_SIZE_FREQUENCY_THRESHOLD = 5  # frequency 大于该值则用大节点

# ========== 难度等级 ==========
DIFFICULTY_EASY = "easy"
DIFFICULTY_MEDIUM = "medium"
DIFFICULTY_HARD = "hard"
DIFFICULTY_ADVANCED = "advanced"

DIFFICULTY_LABELS = {
    DIFFICULTY_EASY: "😊 简单",
    DIFFICULTY_MEDIUM: "😐 中等",
    DIFFICULTY_HARD: "😮 困难",
    DIFFICULTY_ADVANCED: "🤯 高级",
}

# 文件导入时的难度别名映射（别名 -> 标准值）
DIFFICULTY_ALIAS_MAP = {
    "easy": DIFFICULTY_EASY,
    "simple": DIFFICULTY_EASY,
    "medium": DIFFICULTY_MEDIUM,
    "hard": DIFFICULTY_HARD,
    "difficult": DIFFICULTY_HARD,
    "advanced": DIFFICULTY_ADVANCED,
}

# 熟练度阈值（>= 视为已掌握）
MASTERY_THRESHOLD = 3

# ========== Sigma.js 可视化参数 ==========
SIGMA_GRAPH_HEIGHT = 700             # 图谱区域高度（像素）
SIGMA_GRAPH_HEIGHT_DETAIL = 800      # 单词详情页图谱高度
SIGMA_LABEL_SIZE = 14
SIGMA_LABEL_THRESHOLD = 8
SIGMA_DEFAULT_EDGE_WIDTH = 2
SIGMA_EDGE_WIDTH_MIN = 1
SIGMA_EDGE_WIDTH_MAX = 5

# ========== 学习统计 ==========
STATS_LIMIT_DEFAULT = 1000           # 设置页查询上限
