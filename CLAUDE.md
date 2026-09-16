# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个基于 Streamlit 的**英文移动动词中文释义**项目：通过运动事件类型学（Talmy, 1985）
为动词提供带五元语义分解（方式 / 路径 / 方向 / 体相 / 范围）的优化释义，并收集用户评分反馈。

- **核心价值**：把传统词典释义转化为结构化语义分解释义，便于对比与检索
- **当前状态**：界面、MySQL 8.0 数据层、智谱 AI 实时生成、反馈与统计均已接入；缺 API key 或
  数据库时自动降级为离线释义
- **技术栈**：Streamlit + Python 3.11 + Pandas + **MySQL 8.0** + 智谱 AI（`zhipuai` SDK）+ Docker Compose

## 常用命令

```bash
# 运行 Streamlit 应用（详见 README.md 的两条快速开始路径）
streamlit run src/app.py

# 本地连本机 MySQL（覆盖 config.yaml 里的 Docker 主机名）
MYSQL_HOST=127.0.0.1 streamlit run src/app.py

# 测试（pytest.ini 默认带覆盖率）
pytest
python -m pytest -q -p no:cacheprovider --no-cov   # 快速跑，不带覆盖率

# 静态检查
flake8 src/    # 配置见 .flake8
mypy src/      # 配置见 mypy.ini

# 灌词库（离线，无网络依赖）
python scripts/load_word_library.py

# GSD 项目统计（需要 node）
scripts/get-stats.sh
```

## 架构设计

分层、模块职责、数据流与遗留模块的完整说明见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。
配置与环境变量的完整清单见 [`CONFIG.md`](CONFIG.md) 与 [`config/README.md`](config/README.md)。

### 分层

```
用户（浏览器）
    ↓
界面层：Streamlit — src/app.py
    ├── 固定置顶搜索栏
    ├── 结果四卡片：原型与位移事件分析 / 范畴锚定 / 核心释义与多维辨异 / 图式示例
    ├── 示例库（三分类标签页）
    ├── 评分与文字反馈
    └── 侧边栏统计、热门动词、CSV 导出
    ↓
释义适配层：get_display_definition()（同在 src/app.py）
    优先级：数据库命中 → 实时大模型 → 内置示例 → 兜底骨架
    ↓
后端层
    ├── src/mysql_db.py   MySQL 8.0 数据访问（连接池、建表、CRUD、统计）
    └── src/llm_api.py    智谱 AI 封装（提示词、调用、JSON 解析、MySQL 缓存、兜底）
    ↓
横切：src/security.py（输入校验 / HTML 转义）、src/design_system.py（视觉常量与样式）
```

### 核心组件

**五元语义分解**（`semantic_table` 五个键）：

- `manner`【方式】- 运动采用的姿势 / 手段
- `path`【路径】- 运动经过的空间轨迹
- `direction`【方向】- 运动朝向的终点 / 目标
- `aspect`【体相】- 运动时身体的姿态 / 状态
- `scope`【范围】- 运动的范围 / 程度

**降级策略**（改代码时务必保持）：

- 无 `ZHIPUAI_API_KEY` → `get_zhipuai_client()` 返回 `None`，跳过实时生成，页面照常渲染
- MySQL 不可用 → `DB_AVAILABLE = False`，统计 / 导出 / 反馈走空数据分支，页面照常渲染
- 任何一级失败都不得抛到界面层

### 目录结构

```
web-word/
├── src/
│   ├── app.py              # Streamlit 主应用（界面 + 释义适配层）
│   ├── mysql_db.py         # MySQL 8.0 数据访问层
│   ├── llm_api.py          # 智谱 AI 封装
│   ├── design_system.py    # 设计系统
│   ├── security.py         # 输入校验与密钥掩码
│   ├── api.py              # 遗留：第二套 LLM 封装，主流程未用
│   ├── database.py         # 遗留：SQLite 模块，主流程未用
│   └── .streamlit/config.toml
├── config/
│   ├── config.yaml         # 应用实际读取的配置（已跟踪）
│   ├── config.example.yaml # 模板
│   └── README.md
├── scripts/                # entrypoint / wait_for_mysql / init_db.sql / 灌库与迁移脚本
├── tests/                  # pytest 测试
├── data/                   # 运行期数据（gitignored）
├── docs/                   # 设计系统文档
├── screenshots_final/      # 界面截图
└── .planning/              # GSD 规划与归档
```

## 代码位置参考（`src/app.py`，共约 1263 行）

| 内容 | 位置 |
|------|------|
| 固定搜索栏 CSS 与 `st.container(key="search_bar")` | 第 98-115 行 / 第 1079 行 |
| `THEORY_DESCRIPTION`（理论说明） | 第 152 行 |
| 热门动词前端筛选 `filter_hot_verbs()` | 第 193 行 |
| `render_semantic_table()`（五元表格渲染） | 第 211 行 |
| `render_example_library()`（示例库三标签页） | 第 412 行 |
| `get_display_definition()`（释义适配层，核心） | 第 548 行 |
| `MOCK_DEFINITIONS`（内置示例） | 第 708 行 |
| `SEMANTIC_COLORS` / `CATEGORY_*` / `EXAMPLE_VERBS` | 第 943-975 行 |
| `render_sidebar()`（统计 / 热门 / 导出） | 第 978 行 |
| `render_main_area()`（卡片与反馈表单） | 第 1069 行 |

> 行号会随编辑漂移，用 `grep -n` 复核，不要直接相信上表。

## 配置要点

**优先级：环境变量 > `config/config.yaml` > 代码内置默认值。**

- 同一份被跟踪的 `config.yaml` 要同时服务 Docker（MySQL 主机名 `mysql`）与本地（`127.0.0.1`），
  所以环境变量必须能覆盖 YAML —— 改 `src/mysql_db.py` 的配置读取时不要颠倒这个顺序。
- 应用真正读取的 key 变量名是 **`ZHIPUAI_API_KEY`**（`src/llm_api.py`）。旧名 `ZHIPU_API_KEY`
  只被遗留的 `src/api.py` / `src/security.py` 读取。
- `.env` **不会**被自动加载（仓库无 python-dotenv），需 `set -a; source .env; set +a`。

## GSD 工作流

- `.planning/STATE.md` — 项目状态跟踪
- `.planning/phases/` — 当前里程碑的阶段规划
- `.planning/milestones/` — 已归档里程碑
- `.planning/codebase/` — 代码库映射（架构 / 技术栈 / 规范 / 集成 / 结构 / 测试）
- `scripts/get-stats.sh` — 查看进度（需要 node）

> `.planning/milestone.lock` 是本机运行态（含 session id 与 PID），已加入 `.gitignore`，不要提交。
