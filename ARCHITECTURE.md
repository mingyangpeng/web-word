# 目录结构说明

## 📁 项目结构

```
web-word/
├── data/                    # 数据目录
│   ├── web_word.db         # SQLite 数据库文件（备用）
│   └── *.docx              # 文档文件
│
├── config/                  # 配置目录
│   └── database.env        # MySQL 数据库配置文件
│
├── src/                     # 源代码目录
│   ├── app.py              # Streamlit 主应用
│   ├── mysql_db.py         # MySQL 数据库模块
│   └── database.py         # SQLite 数据库模块
│
├── scripts/                 # 脚本目录
├── docs/                    # 文档目录
└── .planning/               # GSD 规划文件
```

## 🗄️ 数据库配置

### MySQL 配置（主要）
- **配置文件**: `config/database.env`
- **数据库模块**: `src/mysql_db.py`
- **配置项**:
  - `MYSQL_HOST`: 数据库主机地址
  - `MYSQL_PORT`: 数据库端口
  - `MYSQL_DATABASE`: 数据库名称
  - `MYSQL_USER`: 数据库用户名
  - `MYSQL_PASSWORD`: 数据库密码
  - `MYSQL_POOL_SIZE`: 连接池大小
  - `MYSQL_POOL_MAX_OVERFLOW`: 连接池最大溢出数

### SQLite 配置（备用）
- **数据库文件**: `data/web_word.db`
- **数据库模块**: `src/database.py`

## 📋 数据库表结构

MySQL 数据库包含以下表：

1. **definitions** - 动词定义表
   - `verb`: 动词名称
   - `chinese_ndef`: 中文释义
   - `semantic_table`: 语义分解表格（JSON 格式）
   - `example_sentence`: 例句
   - `model_version`: 模型版本
   - `created_at`: 创建时间
   - `updated_at`: 更新时间

2. **synonyms** - 同义词表
   - `original_verb_id`: 原动词 ID（外键）
   - `synonym_verb`: 同义词

3. **feedbacks** - 用户反馈表
   - `verb`: 动词名称
   - `rating`: 评分（1-5）
   - `feedback_text`: 反馈文本
   - `created_at`: 创建时间

4. **usage_logs** - 使用日志表
   - `verb`: 动词名称
   - `query_time`: 查询时间
   - `device_info`: 设备信息

5. **statistics** - 统计数据表
   - `stat_name`: 统计名称
   - `stat_value`: 统计值
   - `last_updated`: 最后更新时间

## 🔧 使用说明

1. **配置数据库连接**
   - 编辑 `config/database.env` 文件
   - 修改数据库连接信息（主机、端口、用户名、密码等）

2. **初始化数据库**
   - 运行应用时会自动创建数据库和表
   - 如果 PyMySQL 未安装，会跳过 MySQL 初始化

3. **备份数据**
   - SQLite 数据库位于 `data/web_word.db`
   - MySQL 数据库需要手动备份

## 📝 注意事项

- `config/` 目录存放所有配置文件，不应包含敏感信息
- `data/` 目录存放数据库文件和临时数据
- 生产环境应使用环境变量或密钥管理服务
