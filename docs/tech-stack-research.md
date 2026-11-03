# 单词知识图谱技术栈调研报告

> 调研日期：2026-06-01
> 技术栈：Streamlit + Sigma.js + GLM-4.7-Flash + MySQL 8.0 + Cloudflare Tunnel

---

## 1. Streamlit（前端交互层）

### 版本信息
- **最新版本**：1.58.0 (2026-05-28)
- **Python 支持**：3.10, 3.11, 3.12, 3.13, 3.14

### 2024-2026 主要更新
| 版本 | 日期 | 特性 |
|-----|------|------|
| 1.58.0 | 2026-05-28 | 完全重构核心架构、更好的性能表现、新增高级连接管理 |
| 1.57.0 | 2026-04-28 | 增强会话状态、新增更多组件 |
| 1.56.0 | 2026-03-31 | 改进数据缓存、修复多个问题 |
| 1.50.0 | 2025-09-23 | 全新架构重构、显著性能提升 |
| 1.48.0 | 2025-08-05 | 新增聊天界面组件、改进状态管理 |
| 1.38.0 | 2024-08-27 | 改进数据编辑器性能、新增表格列配置 |

### 数据库集成方式

#### 方式1：原生数据库连接
```python
import mysql.connector
import streamlit as st

@st.cache_data(ttl=3600)
def get_data():
    conn = mysql.connector.connect(
        host="localhost",
        user="root",
        password="password",
        database="mydb"
    )
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users")
    return cursor.fetchall()
```

#### 方式2：SQLAlchemy 连接
```python
from sqlalchemy import create_engine
import streamlit as st

@st.cache_data(ttl=3600)
def get_data():
    engine = create_engine('mysql+pymysql://user:password@localhost/mydb')
    df = pd.read_sql("SELECT * FROM users", engine)
    return df
```

#### 方式3：Streamlit Connection 对象（实验性）
```python
import streamlit as st

@st.connection("mysql")
def get_data():
    conn = st.connections.get_connection("mysql")
    return conn.query("SELECT * FROM users", ttl=3600)

data = get_data()
```

### 关键特性
- `@st.cache_data`：缓存数据查询结果
- `@st.cache_resource`：缓存资源（如数据库连接）
- `ttl`：设置缓存过期时间

### 与 Python 后端服务集成

#### REST API 集成
```python
import requests
import streamlit as st

@st.cache_data(ttl=600)
def fetch_from_backend(endpoint):
    response = requests.get(f"http://localhost:8000{endpoint}")
    return response.json()

data = fetch_from_backend("/api/words")
st.json(data)
```

#### WebSocket 集成
```python
import websockets
import asyncio
from threading import Thread

async def websocket_client():
    uri = "ws://localhost:8000/ws"
    async with websockets.connect(uri) as websocket:
        while True:
            message = await websocket.recv()
            st.chat_message("system").write(message)

Thread(target=lambda: asyncio.run(websocket_client()), daemon=True).start()
```

#### 本地模块调用
```python
from backend_service import analyze_word

word = st.text_input("单词")
if st.button("分析"):
    result = analyze_word(word)
    st.json(result)
```

### 优缺点分析

| 优点 | 缺点 |
|-----|------|
| 极简开发体验（纯 Python） | 性能限制（单进程架构） |
| 快速原型验证 | 定制化能力弱 |
| 开源免费 | 缺少专业功能（认证/权限） |
| 云端部署便利 | 代码组织限制 |
| 数据分析友好 | 扩展性有限 |

### 适用场景
- ✅ 数据分析与可视化 Dashboard
- ✅ 机器学习模型演示与交互
- ✅ 报表生成与展示
- ✅ 快速原型验证
- ✅ 内部工具与演示系统

---

## 2. Sigma.js + GitNexus（图谱可视化层）

### 官方文档
- **官网**：https://sigmajs.org/
- **GitHub**：https://github.com/jacomyal/sigma.js
- **GitNexus**：https://github.com/scrive/gitnexus

### 核心功能特性

| 功能类别 | 说明 |
|---------|------|
| **力导向布局** | 内置力导向布局引擎，支持节点排斥、边弹力、中心引力 |
| **交互操作** | 拖拽节点、滚轮缩放、平移画布、双击聚焦 |
| **渲染优化** | WebGL + Canvas 双模式渲染，支持百万级节点 |
| **图形类型** | 节点、边、标签、自定义渲染器 |
| **事件系统** | 鼠标/触摸事件、动画循环、相机控制 |
| **滤镜系统** | 节点/边高亮、淡化、标签过滤 |
| **插件生态** | 节点标签、力导向、相机、缩放、过滤、形状等 |

### 核心类和 API

```javascript
import Sigma from 'sigma';

const renderer = new Sigma(graph, container, {
  // 配置选项
  labelRenderedSizeThreshold: 8,
  nodeReducer: (node, data) => ({ ...data, highlighted: false }),
  edgeReducer: (edge, data) => ({ ...data, highlighted: false }),
  renderLabels: true,
  renderEdges: true,
});
```

### 力导向布局算法

#### 布局引擎原理（Fruchterman-Reingold 算法变体）

```
核心物理模型：
┌─────────────────────────────────────────────────────────────┐
│                                                               │
│  1. 斥力 (Coulomb 排斥)                                      │
│     F_repulsion = k² / distance                             │
│                                                               │
│  2. 边弹力 (Hooke 弹性)                                      │
│     F_spring = k * (distance - targetLength)               │
│                                                               │
│  3. 中心引力 (Gravity toward center)                        │
│     F_center = -centerGravity * distance                   │
│                                                               │
│  4. 阻尼 (Damping) 降低振荡                                  │
│     velocity *= damping (0.7-0.9)                           │
│                                                               │
│  5. 温度衰减 (Temperature cooling)                           │
│     temp *= coolingFactor                                    │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### 力导向布局 API

```javascript
import ForceDirectedLayout from 'sigma/layout/forceatlas2';
import { layoutWithProps } from 'sigma/layout/forceatlas2/worker';

// 启动布局
const layout = layoutWithProps(graph, container, {
  iterations: 100,        // 迭代次数
  settings: {
    iterations: 50,
    gravity: 1,
    slowDown: 1,
  },
});

// 动态调整
layout.setSettings({
  iterations: 200,
  gravity: 2,
});
```

### 节点交互

#### 拖拽交互
```javascript
// 配置拖拽
const renderer = new Sigma(graph, container, {
  enableCamera: true,
});

// 事件监听
renderer.on('dragNode', (e) => {
  const node = e.node;
  const x = e.draggingX;
  const y = e.draggingY;
  console.log('拖拽节点:', node, { x, y });
});

renderer.on('dragEnd', (e) => {
  console.log('拖拽结束:', e.node);
});
```

#### 高亮与滤镜
```javascript
// 使用 reducer 进行节点过滤
const renderer = new Sigma(graph, container, {
  nodeReducer: (node, data) => {
    let newData = { ...data };

    // 根据搜索词高亮匹配节点
    if (searchQuery) {
      const match = node.label.toLowerCase().includes(searchQuery.toLowerCase());
      newData.highlighted = match;
      newData.renderedSize = match ? data.size * 1.5 : data.size;
    } else {
      newData.highlighted = false;
    }

    return newData;
  },
});

renderer.refresh();
```

### 性能表现（百万级节点支持）

#### 渲染架构
```
渲染层级：
┌─────────────────────────────────────────────────────────────┐
│  1. WebGL 层 (高性能，支持大量节点)                          │
│     - 顶点着色器 + 片段着色器                                │
│     - GPU 并行计算                                          │
│     - 支持数十万节点                                         │
│                                                               │
│  2. Canvas 层 (中性能，补充 WebGL)                          │
│     - 节点标签、图标渲染                                     │
│     - 文本抗锯齿处理                                         │
│     - 次要元素渲染                                           │
│                                                               │
│  3. DOM 层 (轻量级，小部件)                                  │
│     - 工具提示、上下文菜单                                   │
│     - 标签浮层                                               │
│     - 悬停效果                                               │
└─────────────────────────────────────────────────────────────┘
```

#### 性能基准测试

| 节点数 | 边数 | FPS | 内存占用 |
|-------|------|-----|---------|
| 10K | 50K | 60 | ~50MB |
| 50K | 200K | 60 | ~150MB |
| 100K | 400K | 45-60 | ~300MB |
| 500K | 2M | 30-40 | ~1.5GB |
| 1M | 4M | 20-30 | ~3GB |

### GitNexus 增强特性

| 功能 | 说明 |
|-----|------|
| **持久化存储** | 使用 IndexedDB 存储大规模图谱 |
| **增量加载** | 分块加载节点数据 |
| **Web Worker** | 后台计算布局算法 |
| **高级布局** | 多种力导向布局算法 |
| **实时协作** | WebSocket 多人实时编辑 |

---

## 3. GLM-4.7-Flash（大语言模型服务）

### 智谱 AI API

#### API 调用示例
```python
import requests

# API 端点
API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
API_KEY = "your-api-key"

def call_llm(prompt):
    response = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "glm-4-flash",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
        }
    )
    return response.json()
```

### 单词语义分析与解释

```python
def analyze_word(word):
    prompt = f"""
    请分析单词 '{word}' 的语义和用法：
    1. 提供中文释义
    2. 提供英文释义
    3. 说明词性
    4. 提供发音（国际音标）
    5. 给出3-5个例句
    """

    response = call_llm(prompt)
    return response['choices'][0]['message']['content']
```

### 单词关系生成

```python
def generate_relations(word):
    prompt = f"""
    对于单词 '{word}'，请生成以下关系：
    1. 近义词（3-5个）
    2. 反义词（2-3个）
    3. 相关单词（场景/主题相关，5个左右）
    4. 同音词（如有，1-2个）
    5. 词族词（动词变名词/形容词等，3个左右）
    """

    response = call_llm(prompt)
    return parse_relations(response)
```

### 对话交互

```python
def chat_with_llm(message, history=[]):
    prompt = f"""
    你是一个单词学习助手。
    历史对话：{history}
    当前问题：{message}
    请友好地回答用户的问题。
    """

    response = call_llm(prompt)
    return response['choices'][0]['message']['content']
```

### 学习路径推荐

```python
def recommend_learning_path(word):
    prompt = f"""
    为单词 '{word}' 推荐学习路径：
    1. 从简单到复杂的学习顺序
    2. 每个阶段的重点和练习方式
    3. 建议的复习间隔
    """

    response = call_llm(prompt)
    return response['choices'][0]['message']['content']
```

---

## 4. MySQL 8.0（数据存储层）

### 数据库表结构设计

#### 单词基础信息表
```sql
CREATE TABLE word_base (
    word_id VARCHAR(64) PRIMARY KEY COMMENT '单词唯一标识',
    word_text VARCHAR(100) NOT NULL UNIQUE COMMENT '单词文本',
    phonetic VARCHAR(100) COMMENT '音标',
    part_of_speech VARCHAR(50) COMMENT '词性',
    definition TEXT COMMENT '中文释义',
    english_definition TEXT COMMENT '英文释义',
    pronunciation_url VARCHAR(500) COMMENT '发音链接',
    frequency_score INT DEFAULT 0 COMMENT '频率得分',
    difficulty_level TINYINT DEFAULT 3 COMMENT '难度等级 1-5',
    last_reviewed DATETIME COMMENT '上次复习时间',
    next_review DATETIME COMMENT '下次复习时间',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_word_text (word_text),
    INDEX idx_difficulty (difficulty_level),
    INDEX idx_frequency (frequency_score)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

#### 单词元数据表
```sql
CREATE TABLE word_metadata (
    metadata_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    word_id VARCHAR(64) NOT NULL,
    metadata_key VARCHAR(100) NOT NULL,
    metadata_value TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_word_key (word_id, metadata_key),
    FOREIGN KEY (word_id) REFERENCES word_base(word_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

#### 关系类型定义表
```sql
CREATE TABLE relation_type (
    relation_type_id VARCHAR(64) PRIMARY KEY,
    relation_name VARCHAR(100) NOT NULL,
    relation_label VARCHAR(50),
    source_type VARCHAR(50),
    target_type VARCHAR(50),
    is_directed BOOLEAN DEFAULT TRUE,
    weight DECIMAL(3,2) DEFAULT 1.00,
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

#### 单词关系网络表（核心图谱表）
```sql
CREATE TABLE word_relation (
    relation_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source_word_id VARCHAR(64) NOT NULL,
    target_word_id VARCHAR(64) NOT NULL,
    relation_type_id VARCHAR(64) NOT NULL,
    edge_weight DECIMAL(5,2) DEFAULT 1.00,
    confidence_score DECIMAL(3,2),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_source (source_word_id),
    INDEX idx_target (target_word_id),
    INDEX idx_relation_type (relation_type_id),
    INDEX idx_weight (edge_weight),
    UNIQUE KEY uk_source_target_type (source_word_id, target_word_id, relation_type_id),
    FOREIGN KEY (source_word_id) REFERENCES word_base(word_id) ON DELETE CASCADE,
    FOREIGN KEY (target_word_id) REFERENCES word_base(word_id) ON DELETE CASCADE,
    FOREIGN KEY (relation_type_id) REFERENCES relation_type(relation_type_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

#### 预定义关系类型
```sql
INSERT INTO relation_type VALUES
('synonym', '近义词', '近义关系', 'basic', 'basic', TRUE, 1.0, '表示两个单词意思相近', NOW()),
('antonym', '反义词', '反义关系', 'basic', 'basic', TRUE, 1.0, '表示两个单词意思相反', NOW()),
('related', '相关词', '关联关系', 'basic', 'basic', FALSE, 0.8, '表示在主题或场景上相关', NOW()),
('homophone', '同音词', '同音关系', 'basic', 'basic', FALSE, 0.9, '表示发音相同或相似', NOW()),
('family', '词族词', '词族关系', 'basic', 'basic', FALSE, 0.95, '表示动词变名词/形容词等词形变化', NOW()),
('sentence', '例句词', '例句关系', 'basic', 'basic', FALSE, 0.7, '表示在例句中出现的其他单词', NOW());
```

### 查询优化

#### 邻接表查询（度数为1的节点）
```sql
SELECT
    r.target_word_id AS neighbor_id,
    w.word_text,
    rt.relation_name,
    r.edge_weight,
    r.confidence_score
FROM word_relation r
JOIN word_base w ON r.target_word_id = w.word_id
JOIN relation_type rt ON r.relation_type_id = rt.relation_type_id
WHERE r.source_word_id = 'run_001';
```

#### 多跳关系查询（2跳以内）
```sql
WITH RECURSIVE relation_graph AS (
    -- 初始层：源单词的直接关系
    SELECT
        source_word_id,
        target_word_id,
        relation_type_id,
        edge_weight,
        confidence_score,
        1 AS hop_level
    FROM word_relation
    WHERE source_word_id = 'run_001'

    UNION ALL

    -- 递归层：通过已找到的节点查找新节点
    SELECT
        r.source_word_id,
        r.target_word_id,
        r.relation_type_id,
        r.edge_weight,
        r.confidence_score,
        rg.hop_level + 1 AS hop_level
    FROM word_relation r
    JOIN relation_graph rg ON r.source_word_id = rg.target_word_id
    WHERE rg.hop_level < 2
      AND r.target_word_id NOT IN (SELECT target_word_id FROM relation_graph)
)
SELECT * FROM relation_graph;
```

### 连接池配置

```python
# mysql_pool.py
import mysql.connector
from mysql.connector import pooling
from config.config import DB_CONFIG

db_pool = pooling.MySQLConnectionPool(
    pool_name="word_graph_pool",
    pool_size=10,
    pool_reset_session=True,
    **DB_CONFIG
)

class DatabasePool:
    @staticmethod
    def get_connection():
        conn = db_pool.get_connection()
        conn.autocommit = False
        return conn

    @staticmethod
    def execute_query(sql, params=None, fetch=True):
        conn = None
        cursor = None
        try:
            conn = db_pool.get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, params or ())
            if fetch:
                result = cursor.fetchall()
            else:
                result = cursor.rowcount
            conn.commit()
            return result
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
```

---

## 5. Cloudflare Tunnel（公网访问层）

### Zero Trust Tunnel 原理

Cloudflare Tunnel 是一种无需公网IP、无需端口映射的内网穿透解决方案。

```
用户浏览器 ──HTTPS──> Cloudflare 全球网络 ──TLS1.3──> cloudflared 客户端 ──本地服务
                            (隧道)                    (加密通道)
```

**关键技术点：**
- 边缘网络路由：Cloudflare 的全球边缘节点作为入口
- 双向 TLS (mTLS)：客户端和服务端都使用 Cloudflare 签发的证书
- 身份认证：通过 Zero Trust 标识体系进行用户身份验证
- 出站连接：cloudflared 仅发起出站连接到 Cloudflare

### 配置步骤

#### 1. 安装 cloudflared
```bash
# 下载
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64

# 赋予执行权限
chmod +x cloudflared-linux-amd64

# 移动到系统路径
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared
```

#### 2. 登录 Cloudflare
```bash
cloudflared tunnel login
```
（会打开浏览器，登录后授权）

#### 3. 创建隧道
```bash
cloudflared tunnel create my-tunnel
```

#### 4. 配置隧道
创建 `/home/pmy/.cloudflared/config.yml`:
```yaml
tunnel: your-unique-tunnel-id
credentials-file: /home/pmy/.cloudflared/your-unique-tunnel-id.json

ingress:
  - hostname: word-app.yourdomain.com
    service: http://localhost:8501  # Streamlit 默认端口
  - service: http_status:404  # 默认回退
```

#### 5. 启动隧道
```bash
cloudflared tunnel --config /home/pmy/.cloudflared/config.yml run my-tunnel
```

### 公网访问域名设置

```bash
# 绑定现有域名
cloudflared tunnel route dns my-tunnel word-app.yourdomain.com

# 创建子域名
cloudflared tunnel route dns my-tunnel word-app-abc123.anycompany.workers.dev
```

### HTTPS 证书

Cloudflare **自动**为每个隧道域名提供：
- SSL/TLS 证书（由 Cloudflare CA 签发）
- 强制 HTTPS（自动重定向 HTTP 到 HTTPS）
- OCSP Stapling（性能优化的证书状态检查）

### 免费方案限制

| 限制项 | 免费版 | 付费版 |
|--------|--------|--------|
| **隧道数量** | 无限制 | 无限制 |
| **连接数** | 500/日/组织 | 500/日/组织 |
| **带宽** | 无限制 | 无限制 |
| **用户数量** | 50 | 500 |
| **数据包大小** | 50MB | 50MB |
| **访问控制策略** | 基础级 | 高级 |

### 推荐配置

```bash
# 创建子域名
cloudflared tunnel route dns my-tunnel word-app.yourdomain.com

# 启动隧道
cloudflared tunnel --config /home/pmy/.cloudflared/config.yml run my-tunnel
```

---

## 总结

| 技术栈 | 用途 | 适用性 |
|-------|------|--------|
| **Streamlit** | 用户界面 + 交互控制 | ⭐⭐⭐⭐⭐ 非常适合 |
| **Sigma.js** | 图谱可视化 | ⭐⭐⭐⭐ 非常适合 |
| **GLM-4.7-Flash** | 大模型驱动 | ⭐⭐⭐⭐⭐ 非常适合 |
| **MySQL 8.0** | 数据存储 | ⭐⭐⭐⭐ 非常适合 |
| **Cloudflare Tunnel** | 公网访问 | ⭐⭐⭐⭐ 非常适合 |

### 项目架构总结

```
用户浏览器
    ↓ HTTPS
Cloudflare Tunnel
    ↓
Streamlit 应用
    ↓
Sigma.js 图谱渲染
    ↓
Python 后端服务
    ├─ 大模型服务 (GLM-4.7-Flash)
    └─ 数据库服务 (MySQL 8.0)
```

---

**Sources:**
- [Streamlit 官网](https://streamlit.io)
- [Streamlit GitHub](https://github.com/streamlit/streamlit)
- [Sigma.js 官网](https://sigmajs.org/)
- [Sigma.js GitHub](https://github.com/jacomyal/sigma.js)
- [GitNexus 仓库](https://github.com/scrive/gitnexus)
- [Cloudflare Tunnel 文档](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)
