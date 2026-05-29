# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个基于 Streamlit 的**中文动词释义**项目，旨在通过运动事件类型学理论，为中文动词提供带语义分解（方式/路径/方向/体相）的优化释义。

- **核心价值**：将传统词典释义转化为基于语义要素分解的优化释义，帮助用户更准确地理解和学习中文动词
- **当前状态**：前端界面完成（含模拟数据），后端 API 和数据库待接入
- **技术栈**：Streamlit (前端) + Python 3.11 + Pandas + SQLite，计划接入大模型 API

## 常用命令

```bash
# 运行 Streamlit 应用
cd /Users/jhon/pmy/web-word
streamlit run src/app.py

# 查看项目统计（GSD 状态）
scripts/get-stats.sh
# 或直接运行
node scripts/get-stats.js
```

## 架构设计

### 分层架构

```
用户（浏览器）
    ↓
部署层：Hugging Face Spaces（免费托管）
    ↓
前端层：Streamlit
    ├── Sticky 搜索栏（固定定位）
    ├── 语义分解展示（表格形式）
    ├── 用户评分与反馈（1-5分 + 文字）
    └── 数据导出（CSV）
    ↓
后端层：Python
    ├── 提示词工程（语义要素分解：方式/路径/方向/体相）
    ├── 大模型 API 调用（OpenAI SDK → DeepSeek/智谱）
    └── 结果解析
    ↓
数据层：SQLite + Pandas
    ├── 查询日志（动词、释义、模型版本、时间戳）
    ├── 用户评分收集（1-5分 + 文字反馈）
    └── 统计数据导出（CSV）
    ↓ 数据库文件路径：data/web_word.db
    ↓
外部服务：大模型 API（DeepSeek/智谱/OpenAI）
```

### 核心组件

**语义要素分解**（基于 Talmy, 1985 运动事件类型学）：
- 【方式】- 运动采用的姿势/手段（如：跑步、滑行）
- 【路径】- 运动经过的空间轨迹（如：直线进入、环绕）
- 【方向】- 运动朝向的终点/目标（如：朝向内部、向上）
- 【体相】- 运动时身体的姿态/状态（如：前倾、紧绷）

### 目录结构

```
web-word/
├── src/
│   ├── app.py              # Streamlit 主应用
│   ├── database.py         # MySQL 8.0 数据库模块
│   └── .streamlit/
│       └── config.toml     # Streamlit 配置
├── scripts/
│   ├── get-stats.js        # GSD 项目统计脚本
│   └── get-stats.sh        # Bash 包装脚本
├── data/                   # 数据文件（待填充）
├── docs/                   # 文档（待填充）
├── temp/                   # 临时文件
└── .planning/              # GSD 规划文件
    ├── STATE.md            # 项目状态跟踪
    └── phases/             # 阶段规划
```

## 待实现功能

### 必须接入

1. **大模型 API 调用**
   - 输入：动词（如"跑进来"）
   - 输出：传统释义 + 优化释义（带语义分解表格）
   - 当前位置：`app.py` 第 221-251 行的模拟数据部分
   - 模型选择：优先使用 DeepSeek/智谱 API（比 OpenAI 更经济）

2. **SQLite 数据库**（已实现，见 `src/database.py`，数据存储在 `data/web_word.db`）
   - `queries` 表：记录查询日志
   - `feedbacks` 表：记录用户反馈
   - 统计查询：热门动词、平均评分

3. **用户反馈提交**（已实现）
   - 接收：评分 + 文字反馈
   - 存储：MySQL 插入

4. **统计 API**（已实现）
   - 从 MySQL 查询：总查询次数、平均评分、热门动词

### 优化改进

1. **API 密钥管理**：使用环境变量存储大模型 API 密钥
2. **错误处理**：API 调用失败时的降级方案
3. **缓存机制**：避免重复调用相同动词
4. **Markdown 渲染优化**：语义分解表格的样式美化

## 数据流

1. 用户输入动词 → Streamlit 表单
2. 点击生成按钮 → 触发大模型 API 调用
3. 模型返回释义 → 解析并渲染
4. 用户评分反馈 → 提交到数据库
5. 侧边栏统计 → 从数据库实时查询

## GSD 工作流

项目使用 GSD（GSD planning system）进行阶段规划：
- `.planning/STATE.md` - 项目状态跟踪
- `.planning/phases/` - 各阶段规划文件
- 使用 `scripts/get-stats.sh` 查看进度

## 代码位置参考

- **语义分解模板**：`app.py` 第 83-141 行（MOCK_DEFINITIONS 结构）
- **用户反馈 UI**：`app.py` 第 264-318 行
- **侧边栏统计**：`app.py` 第 153-184 行
- **固定搜索栏**：`app.py` 第 20-35 行（CSS）+ 320-403 行（JS）
