# 单词知识图谱 Web 应用 - 项目结构梳理

## 📁 项目目录结构

```
web-word/
├── .claude/                      # Claude Code 配置
│   ├── workflows/               # 工作流脚本
│   └── settings.json            # Claude Code 设置
├── data/                        # 数据目录
│   ├── __pycache__/            # Python 缓存
│   ├── word_database.py        # 数据库操作封装
│   └── movement_verbs.json     # 移动动词数据（93个单词）
├── pages/                       # 页面目录
│   ├── __pycache__/            # Python 缓存
│   ├── home.py                 # 首页（单词查询）
│   ├── learn.py                # 学习页面（Sigma.js图谱）
│   ├── chat.py                 # 对话页面
│   ├── settings.py             # 设置页面
│   ├── words.py                # 单词库页面
│   └── word_detail.py          # 单词详情页面（新创建）
├── scripts/                     # 脚本目录
│   ├── extract_verbs.py        # 单词提取脚本
│   └── generate_graph_relations.py  # 关系生成脚本
├── services/                    # 服务目录
│   └── llm_service.py          # LLM 服务封装
├── styles/                      # 样式目录
│   └── global.css              # 全局样式
├── docs/                        # 文档目录
│   ├── 英语移动动词五大范畴分类总表.docx  # 原始数据文档
│   └── tech-stack-research.md  # 技术栈调研
├── CLAUDE.md                    # 项目文档
├── app.py                       # Streamlit 主应用入口
├── DB_STORAGE.md                # 数据库存储说明
├── requirements.txt             # Python 依赖（如果存在）
├── .gitignore                   # Git 忽略文件
├── .env                         # 环境变量（应该创建）
└── README.md                    # 项目说明（如果存在）
```

## 📊 核心功能模块

### 1. 应用入口 (app.py)
- **职责**: 整体应用框架、页面路由、导航菜单
- **关键功能**:
  - Streamlit 页面配置
  - 侧边栏导航菜单
  - 页面路由分发
  - 全局 CSS 样式
- **技术栈**: Streamlit, HTML/CSS

### 2. 页面模块 (pages/)

#### 2.1 home.py - 首页（单词查询）
- **职责**: 单词搜索、LLM 分析、关系展示
- **关键功能**:
  - 单词输入和搜索
  - LLM 语义分析
  - 单词详情展示
  - 历史记录
  - 查看知识图谱按钮
- **数据流**: 数据库查询 → LLM 分析 → Session state → UI 展示

#### 2.2 learn.py - 学习页面
- **职责**: 知识图谱可视化
- **关键功能**:
  - Sigma.js 图谱展示
  - 节点筛选和过滤
  - 视图控制（显示标签、连线等）
  - 节点统计
- **技术栈**: Sigma.js, Streamlit components

#### 2.3 chat.py - 对话页面
- **职责**: AI 对话学习
- **关键功能**:
  - 对话历史记录
  - 模式选择（标准、讲解、练习、备考）
  - 快捷问题
  - LLM 对话
- **技术栈**: Streamlit chat API, LLM

#### 2.4 word_detail.py - 单词详情（新增）
- **职责**: 单词详细信息 + 动态知识图谱
- **关键功能**:
  - 单词详情展示
  - 根据范畴动态加载相关单词
  - Sigma.js 知识图谱可视化
  - 关系展示（近义词、反义词）
- **技术栈**: Sigma.js, JSON 数据加载

#### 2.5 words.py - 单词库
- **职责**: 单词管理
- **关键功能**:
  - 单词列表展示
  - 筛选和搜索
  - 单词删除
  - CSV 导出
- **技术栈**: Streamlit, Pandas

#### 2.6 settings.py - 设置页面
- **职责**: 系统配置
- **关键功能**:
  - 数据库状态统计
  - 单词导入（文件上传）
  - 数据库管理（清空）
  - 系统信息
- **技术栈**: Streamlit, 文件上传

### 3. 数据层 (data/)
- **职责**: 数据库操作
- **关键功能**:
  - 单词 CRUD 操作
  - 关系管理
  - 查询优化
  - 数据导入/导出
- **数据库表**:
  - words: 单词表
  - word_relations: 单词关系表
  - user_learning: 用户学习记录
  - chat_history: 对话记录
  - learning_stats: 学习统计
  - system_config: 系统配置

### 4. 服务层 (services/)
- **职责**: 业务逻辑服务
- **llm_service.py**: LLM API 调用封装
  - 单词分析
  - 关系生成
  - 对话接口
  - 错误处理

### 5. 脚本目录 (scripts/)
- **extract_verbs.py**: 从文档提取动词数据
- **generate_graph_relations.py**: 使用 LLM 生成关系数据

## 🗃️ 数据库架构

### 主要数据表

1. **words 表** - 单词基础信息
   ```sql
   id, word, pronunciation, part_of_speech,
   definition, english_definition, example_sentence,
   example_translation, frequency, difficulty_level
   ```

2. **word_relations 表** - 单词关系网络
   ```sql
   id, word_id, related_word_id, relation_type,
   relation_strength, created_at
   ```

3. **其他辅助表**: user_learning, chat_history, learning_stats, system_config

### 数据分类体系

- **路径聚焦类**: arrive, reach, return, come, go... (22个)
- **方式聚焦类**: roll, walk, run, fly, swim... (57个)
- **关联聚焦类**: chase, pursue, follow... (14个)
- **关系类型**: 近义词、反义词、相关词、同音词、词族

## 🔧 技术栈

### 前端
- **Streamlit**: Web 界面框架
- **Sigma.js**: 知识图谱可视化
- **HTML/CSS**: 自定义样式

### 后端
- **Python 3.12**: 主要语言
- **Streamlit**: 框架
- **GLM-4.7-Flash**: LLM API
- **MySQL 8.0**: 数据库

### 开发工具
- **Claude Code**: AI 辅助开发
- **Git**: 版本控制

## 📡 API 集成

### GLM-4.7-Flash API
- **接口**: https://open.bigmodel.cn/api/paas/v4/chat/completions
- **功能**: 单词分析、关系生成、对话
- **认证**: API Key

### 数据库连接
- **类型**: MySQL 8.0
- **连接方式**: mysql.connector
- **连接池**: 未实现（建议添加）

## 🚀 数据流

```
用户输入单词
    ↓
数据库查询 (home.py)
    ↓
LLM 分析 (llm_service.py)
    ↓
Session State 更新
    ↓
UI 展示
    ↓
查看详情/知识图谱
```

## 📝 配置要求

### 环境变量
```bash
# .env 文件
GLM_API_KEY=your_api_key_here
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=word_knowledge_db
```

### 依赖安装
```bash
pip install streamlit mysql-connector-python requests
```

## 🔍 代码审查发现的问题（23个）

### 高危（3个）
1. 硬编码 API 密钥（services/llm_service.py:23）
2. 硬编码数据库凭证（data/word_database.py:20-21）
3. Session state 键冲突（pages/home.py:103）

### 严重（12个）
4. try-except 缺少 finally（pages/learn.py:81-82）
5. try-except 缺少 finally（pages/settings.py:91-162）
6. 可变默认参数问题（pages/chat.py:89, 150）
7. JSON 解析错误处理不完善（services/llm_service.py:143-164）
8. 数据库连接未使用连接池（data/word_database.py:51-520）
9. 文件 I/O 未使用上下文管理器（pages/word_detail.py:32-33）
10. 异常捕获范围过大（pages/home.py:62-92）
11. Session state 不一致（pages/home.py:103, 112）
12. 数据库连接未使用连接池
13. 异常捕获范围过大
14. 魔术数字
15. 重复代码

### 中等问题（8个）
16. 循环中的数据库查询效率低
17. 空值检查不完整
18. 资源清理不完整
19. 默认值硬编码
20. 错误信息不友好

### 轻微问题（6个）
21. 注释过时
22. 变量命名不规范
23. 代码重复

## 🎯 优先修复建议

1. **立即修复**:
   - 移除硬编码的 API 密钥和数据库凭证
   - 修复 session_state 键冲突
   - 添加 finally 块确保资源释放

2. **尽快修复**:
   - 优化异常处理
   - 添加数据库连接池
   - 完善错误提示

3. **逐步优化**:
   - 消除重复代码
   - 提取魔法数字为常量
   - 优化性能瓶颈

## 📚 参考文档

- [Streamlit 官方文档](https://docs.streamlit.io)
- [Sigma.js 文档](https://projects.sigmajs.com)
- [Talmy 运动事件理论](https://en.wikipedia.org/wiki/Talmy%27s_linguistic_typology)
- [Levin 动词分类](https://en.wikipedia.org/wiki/Levin%27s_categories_of_verbs)

## 📞 联系方式

- 项目位置: /home/pmy/megatron_2025/pmy/web-word
- Python 环境: /home/pmy/dev/miniconda3/envs/p312/bin/python
- 数据库: MySQL 8.0（本地）
