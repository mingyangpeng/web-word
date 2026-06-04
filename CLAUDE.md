# CLAUDE.md

此文件为 Claude Code (claude.ai/code) 提供工作指导。

## 项目状态

这是一个单词知识图谱 Web 应用项目，目标是构建一个基于 Streamlit + Sigma.js + GLM-4.7-Flash 的大模型驱动单词学习系统。

## 技术栈

### 1. 前端 & 交互展示
**Streamlit**

- 纯 Python 动态 Web 界面框架
- 支持：对话交互、用户输入、数据表格展示、图谱可视化集成
- 特点：无需前端 JavaScript，由 Python 直接生成动态 UI

### 2. 可视化图谱引擎
**Sigma.js（来自 GitNexus）**

- 单词知识图谱可视化核心
- 支持：力导向布局、拖拽交互、缩放导航、节点高亮
- 前端渲染，无性能压力，支持千万级节点扩展

### 3. 后端服务
**Python 3.10+**

- 业务逻辑处理与数据管理
- 数据库读写操作
- GLM-4.7-Flash 大模型 API 调用
- 单词关系图谱数据生成与维护

### 4. 大模型服务（固定）
**GLM-4.7-Flash**

- 来源：智谱 AI 官方 API
- 功能：
  - 单词语义分析与解释
  - 单词关系生成（近义词、反义词、例句关联）
  - 智能问答与对话交互
  - 学习路径推荐

### 5. 数据库
**MySQL 8.0**

- 本地部署方案
- 数据存储：
  - 单词基础信息
  - 单词关系网络
  - 对话记录
  - 用户学习轨迹

### 6. 单词知识图谱数据
**英语移动动词分类体系**

- 数据来源：docs/英语移动动词五大范畴分类总表.docx
- 单词总数：93 个核心移动动词
- 分类体系：三大范畴（路径聚焦、方式聚焦、关联聚焦）+ 五大次类

**三大范畴分类**：
1. **路径聚焦类** (22个)
   - 终点类：arrive, reach, return, come, go, enter, exit, ascend, rise, climb, fall, descend, plunge, tumble, advance, recede
   - 来源类：leave, abandon, desert, depart, escape, flee

2. **方式聚焦类** (57个)
   - 滚动滑行类：roll, slide, bounce, drift, float, glide, swing
   - 陆地行进类：walk, stride, run, trot, gallop, jog, sprint, march, tramp, stomp, step, hop, skip, jump, leap, vault, spring, hurdle, scramble, scurry, dodge, zigzag
   - 飞行游动类：fly, soar, sail, hover, glide, swim, dive, float, drift
   - 匍匐爬行类：crawl, creep, scramble, clamber, slither, snake
   - 长途行进类：travel, journey, trek, hike, backpack, trudge, march, migrate, commute
   - 运载工具类：drive, ride, sail, ski, skate, board, surf, skateboard, cycle, motor

3. **关联聚焦类** (14个)
   - 目的类：chase, pursue, follow, shadow, tail, track, trail
   - 参与者类：accompany, conduct, escort, guide, lead, shepherd, wait

**知识图谱关系文件**：
- `data/movement_verbs.json` - 单词数据（中文释义、分类、语法形式）
- `data/word_graph_relations.json` - 知识图谱关系（近义词、反义词、相关词、同音词、词族）

**数据生成流程**：
1. 从英语移动动词文档中提取 93 个核心动词
2. 按语言学分类体系组织单词数据
3. 使用 LLM 分析单词间的关系
4. 构建知识图谱数据结构
5. 保存到单独文件便于可视化

### 6. 公网访问（免费）
**Cloudflare Zero Trust Tunnel**

- 免费内网穿透解决方案
- 自动 HTTPS 证书、全球 CDN 加速
- 无需公网 IP、无需端口映射、安全加密传输

## 系统整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Cloudflare Tunnel                        │
│                    (公网访问层)                               │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    Streamlit 应用层                          │
│                  (用户界面 + 交互控制)                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                   Sigma.js 图谱可视化层                       │
│              (力导向布局 + 节点交互 + 数据渲染)                │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    Python 后端服务层                         │
│                (业务逻辑 + 数据库 + 大模型)                   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                   MySQL 8.0 数据库层                         │
│                (单词数据 + 关系网络 + 用户记录)               │
└─────────────────────────────────────────────────────────────┘
```

## 代理设置

代码库已配置以下代理设置，所有 Bash 命令将自动使用：
- HTTP 代理: `http://127.0.0.1:7897`
- HTTPS 代理: `https://127.0.0.1:7897`
- SOCKS5 代理: `socks5://127.0.0.1:7897`

## Python 环境配置

### Python 解释器路径

所有 Python 调用必须使用项目指定的 Conda 环境：

**Python 解释器路径**：
```
/home/pmy/dev/miniconda3/envs/p312/bin/python
```

**Python 版本**：
```
Python 3.12.13
```

### Shebang 配置

项目中的所有 Python 文件已配置正确的 shebang：
- `#!/home/pmy/dev/miniconda3/envs/p312/bin/python`

### 使用方式

**执行 Python 文件**：
```bash
/home/pmy/dev/miniconda3/envs/p312/bin/python your_script.py
```

**安装依赖**：
```bash
/home/pmy/dev/miniconda3/envs/p312/bin/pip install -r requirements.txt
```

**激活虚拟环境（开发时）**：
```bash
source /home/pmy/dev/miniconda3/bin/activate p312
```

### 运行测试

项目使用 pytest 9.x 作为测试框架，测试代码位于 `tests/` 目录。

**⚠️ 重要：必须禁用插件自动加载**

本机 pytest entry points 被 ROS Jazzy 的 `launch_testing_ros` 插件污染（注册了未定义 hook `pytest_launch_collect_makemodule`，会导致 `check_pending()` 校验失败）。**所有 pytest 命令必须前置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 环境变量**，并通过 `-p` 显式启用所需插件。

**运行全部测试**（67 项，含数据库集成测试）：
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  /home/pmy/dev/miniconda3/envs/p312/bin/python -m pytest tests/ -v
```

**仅运行单元测试**（无需 MySQL，40 项）：
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  /home/pmy/dev/miniconda3/envs/p312/bin/python -m pytest \
    tests/test_constants.py \
    tests/test_logging_config.py \
    tests/test_db_config.py \
    tests/test_llm_service.py -v
```

**仅运行数据库集成测试**（需可用的 MySQL，27 项）：
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  /home/pmy/dev/miniconda3/envs/p312/bin/python -m pytest tests/test_word_database.py -v
```

**单个测试方法**：
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  /home/pmy/dev/miniconda3/envs/p312/bin/python -m pytest \
    tests/test_word_database.py::TestWordCRUD::test_add_and_get_word -v
```

**测试模块说明**：
| 模块 | 测试数 | 依赖 | 说明 |
|------|--------|------|------|
| `test_constants.py` | 9 | 无 | 验证常量完整性（关系类型、颜色映射、数值范围） |
| `test_logging_config.py` | 5 | 无 | logger 缓存、级别控制、stdout 输出 |
| `test_db_config.py` | 4 | 无 | 环境变量解析、SQL 异常回滚 |
| `test_llm_service.py` | 22 | 无（mock） | LLM 配置、chat 响应、JSON 提取、单例 |
| `test_word_database.py` | 27 | MySQL | CRUD、批量查询、N+1 修复、UPSERT |

**数据库测试隔离机制**：
- `tests/conftest.py` 中的 `isolated_db` fixture 复用现有 `word_knowledge_db`（`jhon` 用户仅有该库权限，无法 CREATE DATABASE）
- 每个测试用例开始前 `SET FOREIGN_KEY_CHECKS=0` + TRUNCATE 所有业务表，结束后再次清空
- `conftest.py` 启动时自动加载项目根目录的 `.env` 文件（不覆盖已存在的环境变量）

**pytest 配置文件**：`pytest.ini`
```ini
[pytest]
testpaths = tests
addopts = -v --tb=short --strict-markers
           -p no:cacheprovider
           -p no:launch_testing
           -p no:launch_testing_ros
```

> 注：`pytest.ini` 中的 `-p no:xxx` 仅禁用已加载的插件，但不会阻止 entry point 自动注册。`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 才能彻底阻止 entry point 扫描，因此两者必须同时使用。

**测试依赖**：
```bash
/home/pmy/dev/miniconda3/envs/p312/bin/pip install -r tests/requirements.txt
```

### 文件清单

已更新 shebang 的文件：
- `./config/init_db.py` - 数据库初始化脚本
- `./test_llm_api.py` - GLM API 测试脚本
- `./test_llm_service.py` - LLM 服务测试脚本

**页面文件**：
- `./pages/home.py` - 首页（单词查询）
- `./pages/learn.py` - 学习页面（Sigma.js图谱）
- `./pages/chat.py` - 对话页面
- `./pages/word_detail.py` - 单词详情页面（新增）
- `./pages/words.py` - 单词库页面
- `./pages/settings.py` - 设置页面

**数据文件**：
- `./data/movement_verbs.json` - 93个移动动词数据
- `./data/word_graph_relations.json` - 知识图谱关系数据

**脚本文件**：
- `./scripts/extract_verbs.py` - 单词提取脚本
- `./scripts/generate_graph_relations.py` - 关系生成脚本

### 代码审查结果

**详细报告**: `CODE_REVIEW_REPORT.md`
**项目结构**: `PROJECT_STRUCTURE.md`

**代码质量评分**: 5.8/10 → 8.3/10（一期优化）→ **8.9/10**（二期优化）

**已修复问题（累计）**：
- ✅ **P0 高危（3/3）**：硬编码 API Key fallback、数据库凭证、Session state 键冲突
- ✅ **P1 严重（9/9）**：finally 块、可变默认参数、连接池、异常处理细化
- ✅ **P2 中等（4/4）**：
  - 魔术数字 → `config/constants.py`（53 个常量集中管理）
  - 重复代码 → `pages/chat.py` LLM 调用从 2 处合并为 1 处
  - N+1 查询 → 新增 `get_relations_for_word_ids`、`get_relation_type_stats` 批量方法
  - print → logging（`config/logging_config.py`）
- ✅ **二期新发现并修复的隐藏 Bug**：
  - `pages/home.py:103` `word_info` NameError（点击历史按钮崩溃）
  - `pages/word_detail.py:141,152` `syn in filtered_words` 类型混淆
  - `pages/words.py:85-91` 筛选逻辑永远不生效
  - `pages/words.py:154-165` 分页按钮无功能
  - `data/word_database.py:14-37` `exec(open().read())` 远程代码执行风险
  - MySQL 8.0 `utf8mb4_0900_ai_ci` 下 `'happiness' LIKE '%happy%'` 返回 0 的 UCA 权重 bug

**测试覆盖**：从近 0 起步提升到 **67 项**（40 单元 + 27 集成），运行命令见「运行测试」章节。

## 开发流程

### 1. 项目初始化
- 创建 Python 虚拟环境
- 安装依赖：Streamlit、numpy、pandas、mysql-connector-python
- 配置 GLM-4.7-Flash API 密钥
- 初始化 MySQL 数据库与表结构

### 2. 数据层实现
- 设计数据库表结构（单词表、关系表、对话记录表）
- 实现 CRUD 操作封装
- 数据导入与批量处理

### 3. 后端服务开发
- 单词查询与语义分析接口
- 大模型 API 集成（智谱 AI）
- 关系图谱生成算法

### 4. 前端界面开发
- Streamlit 页面布局设计
- Sigma.js 图谱容器集成
- 对话组件与输入组件
- 数据可视化展示

### 5. Cloudflare Tunnel 配置
- 注册 Cloudflare 账号
- 创建隧道服务
- 公网访问域名配置

## 关键文件结构

```
web-word/
├── app.py                  # Streamlit 主应用入口
├── data/
│   ├── word_database.py    # 数据库操作封装
│   └── word_data.sql       # 数据库初始化脚本
├── config/
│   └── config.py           # 配置管理
├── services/
│   ├── llm_service.py      # 大模型服务封装
│   └── graph_service.py    # 图谱生成服务
└── pages/
    ├── home.py            # 首页（单词查询）
    ├── learn.py           # 学习界面（图谱展示）
    └── chat.py            # 对话界面
```

## 注意事项

- 项目使用纯 Python 开发，避免跨技术栈复杂性
- 图谱可视化依赖 Sigma.js CDN，需保持网络可访问
- 大模型 API 调用需要合理的错误处理和限流控制
- 数据库连接需使用连接池管理资源
- 所有环境变量应通过 `.env` 文件管理，不要硬编码敏感信息
