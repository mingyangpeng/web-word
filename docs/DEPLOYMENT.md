# 部署清单（LexiSchema · 上架前必查）

> 本文档按部署前 → 部署中 → 部署后三段列出检查项，每项标注责任角色（平台管理员/词典管理员）。
> 完成 ✅ 后方可持续运行；未 ✅ 项需在部署说明中如实标注风险。

## 一、部署前（平台管理员）

### 1.1 凭据安全 🔴

| # | 检查项 | 操作 |
|---|--------|------|
| 1 | API Key 轮换 | 在智谱/网关后台**作废旧 key**→生成新 key→写入 `.env` 或「🤖 模型供应商」页面 |
| 2 | MySQL 口令轮换 | `ALTER USER 'web_word_user'@'%' IDENTIFIED BY '<新口令>'`→同步 `.env` |
| 3 | `.env` 历史清理 | git 历史仍含旧凭据（172+ 提交）；如需彻底清除需 `git filter-repo` 重写历史＋force push——**评估是否值得**（团队私有仓库可接受不清理，但须轮换凭据使旧值失效） |
| 4 | `.env.local` | 生产部署的真实凭据写 `.env.local`（已 gitignore），`.env` 只留占位模板 |

### 1.2 Streamlit 配置

| # | 检查项 | 现状 |
|---|--------|------|
| 5 | `showErrorDetails = false` | ✅ 已改（批次 12） |
| 6 | `enableStaticServing` | true（图谱 HTML 需要）——**注意**：`/app/static/*` 无鉴权（RV4-7），公网部署口径见 §六 |
| 7 | `server.headless` | true（无浏览器弹窗）✅ |

### 1.3 Docker / 网络安全

| # | 检查项 | 现状 |
|---|--------|------|
| 8 | MySQL 端口绑定 | ✅ 已改为 `127.0.0.1:3306:3306`（不再暴露 0.0.0.0） |
| 9 | HTTPS | **待部署层配置**——Streamlit 本身无 TLS，需 Nginx/Caddy 反代＋Let's Encrypt；现成样例见 §六（deploy/ 三件套） |
| 10 | CORS / XSRF | Streamlit 默认启用 ✅ |
| 11 | Docker 网络 | compose 内部网络隔离 MySQL（已改 127.0.0.1 后外部不可达） |

### 1.4 备份与恢复

| # | 检查项 | 操作 |
|---|--------|------|
| 12 | 备份自动化 | `crontab -e` 添加 `15 2 * * * cd /path/to/web-word && bash scripts/backup_db.sh --keep 14 >> data/logs/backup_db.log 2>&1` |
| 13 | 备份验证 | 每月抽一份 `*.sql.gz` 在沙箱实例恢复演练 |
| 14 | G6 备份新鲜卡 | 部署后确认词典管理→出版导出→备份新鲜卡显示 ✅ |

### 1.5 测试库初始化（本地开发/CI 用，生产部署可跳过）

pytest 的真库集成模块（迁移集成/e2e 工作流/各批次 fixes 集成段）需要 `web_word_user`
对各自的测试库有建库删库权限。`scripts/grant_local_mysql.sql` 一次性幂等完成：

- **1 个应用库**：`web_word_db`；
- **23 个测试库**：迁移集成（`web_word_migration_test`）＋按模块分库的集成测试库
  （users/flow/ai_ledger/media/wordforms/org/dict_admin/collab/writing/lexical/
  stage1_e2e/review_regression/llm_providers）＋批次 14~17 及 review waves 逐批补入的
  fx18/fx19/fx20/fx25/fx27(r1_probe)/fx30/fx31/fx32/fx33 测试库——合计授权 **24 库**
  （脚本内注释逐库标注归属模块）。

```bash
mysql -u root -p < scripts/grant_local_mysql.sql   # 幂等；库名一律 `\_` 转义（防 GRANT 通配符误授权）
MYSQL_HOST=127.0.0.1 pytest                        # 真库集成段即真跑
```

> **无授权自动 skip 口径**：未执行授权（或连不上 MySQL）时，真库集成用例**自动 skip
> 而非 fail**——这是环境能力问题，不是代码缺陷；单元层用例不受影响照常跑。
> CI（.github/workflows/ci-cd.yml）已加 MySQL 8 service 并在 job 内执行授权脚本，
> 真库用例在 CI 上真跑。测试库互不共用（按模块分库，防并行 pytest 互删）。

## 二、部署中

| # | 步骤 | 命令/操作 |
|---|------|-----------|
| 1 | 克隆代码 | `git clone git@github.com:mingyangpeng/web-word.git && cd web-word && git checkout gsd/phase-01-verb-tool` |
| 2 | 配置凭据 | 复制生产凭据到 `.env.local`（API key、MySQL 口令）——**不写 `.env`** |
| 3 | Docker 启动 | `docker compose up -d` |
| 4 | 探活 | `curl http://localhost:8501/_stcore/health` → 返回 `ok` |
| 5 | 数据灌入 | 容器首启自动八步灌库（幂等）；如需增量走导入向导 |
| 6 | 供应商配置 | 登录 admin → 词典管理 → 🤖 模型供应商 → 添加网关/直连供应商 |
| 7 | 备份任务 | 宿主机 crontab 添加（见 §1.4 第 12 条） |

> **首启与升级注意事项（RV11）**
>
> - **首次 `up` 前**先 `mkdir -p data/backups`：该目录 bind 挂进容器（G6 备份
>   新鲜卡的取数路径）。Linux 宿主机上若由 Docker 代建，会归 root 属主，
>   宿主机 cron 备份会写不进。
> - **`.env.local` 依赖 Compose v2.24+**（2024-02，Docker Desktop 4.27+ 内置）：
>   compose 的 `env_file` 以 `required: false` 挂载 `.env.local`，旧版 compose
>   不认该语法，请先升级。
> - **升级存量部署**：镜像已改为非 root（uid 1000）运行；历史 `web-word-app-data`
>   卷若属主是 root，先执行一次
>   `docker run --rm -v web-word-app-data:/d alpine chown -R 1000:1000 /d`
>   再 `up -d`。种子文件改由 entrypoint 从镜像内 `/app/seed/data` 补入
>   （缺才拷、已有不覆盖）——升级镜像不会重置数据；确需刷新某份种子，
>   删卷内对应文件后重启即可。
> - **容器自愈与 binlog（RV-9）**：web 与 mysql 服务均带 healthcheck（web 用
>   python urllib 探 `_stcore/health`，mysql 用 `mysqladmin ping`），僵死容器可被
>   compose 识别重启；MySQL 以 `--skip-log-bin` 启动——binlog 关闭，datadir 不再
>   日增约 1G（历史卷里已生成的 binlog 可在升级窗口手动 PURGE 后回收空间）。

## 三、部署后

| # | 检查项 | 方法 |
|---|--------|------|
| 1 | 全页可用 | 侧边栏 17 页逐页点击（或用 tests/test_review_regression.py AppTest 矩阵） |
| 2 | AI 功能 | 搜索 run → 六卡片出全 → 以句搜义输入一句话 → 最近邻出结果 |
| 3 | 撰写→审校→终裁→出版 | 走一遍编纂链（需 ≥2 账号：编纂员＋审校） |
| 4 | 权限隔离 | viewer 账号登录确认不可见管理区 |
| 5 | 备份验证 | 词典管理→出版导出→备份新鲜卡 ✅ |
| 6 | 日志审计 | 服务端日志无 PermissionError/traceback 外泄 |
| 7 | 环境体检 | `./start doctor` 七类 23 项——本开发机基线 21/23（2 红为真缺口如实上报：zh_dict 部分灌入＋.env 未配 AI key，AI 走「模型供应商」页 DB 路由）；新部署应核对至全过或如实记录 |

## 四、架构速览（部署视角）

```
互联网 ──▶ Nginx/Caddy（TLS 终止:443）
              │
              ▼
         Streamlit:8501（编纂端 + 查阅端）
              │
              ├──▶ MySQL:3306（仅 127.0.0.1，Docker 内部网络）
              ├──▶ data/media（媒体资产，卷挂载）
              ├──▶ data/backups（备份，卷挂载）
              └──▶ https://api.kakouai.com（LLM 网关，出站 HTTPS）
```

## 五、已知风险（如实标注）

| 风险 | 等级 | 缓解 |
|------|------|------|
| Streamlit 单进程并发上限 | P2 | 查阅端走只读静态镜像；编纂端低并发可接受 |
| `/app/static/*` 无鉴权 | P3 | 图谱数据敏感度低；公网折中口径（限速＋不索引，deny all 会打断图谱渲染）见 §六与 deploy/README.md |
| `.env` 历史含旧凭据 | P1 | 轮换后旧值失效即消解；filter-repo 可选 |
| requests >=2.31 下限 | P3 | requirements 已提至 >=2.32.4；CI 已加 pip-audit 依赖审计（advisory 提示级，不阻断合并——审计结果按当时漏洞库解析，命中须人工评估） |
| 宿主机 3306 已被原生 MySQL 占用（双栈开发机） | P3 | 本地加 docker-compose.override.yml（gitignored）：services.mysql.ports: !reset []（Compose v2.24+），容器库仅内部网络可达，应用走 service name 不受影响 |

## 六、公网部署（Nginx/Caddy 三件套）

> RV4-7/R4-7（`/app/static/*` 绕登录门）的公网处置方案，落地为 deploy/ 下
> 可执行清单。本节是口径摘要，操作细节与实测记录见 **deploy/README.md**。

### 6.1 三件套

| 文件 | 说明 |
|------|------|
| `deploy/nginx.conf.example` | 完整独立 nginx.conf 样例：443 TLS（证书路径占位）、`/` 反代 127.0.0.1:8501（**WebSocket 升级头齐全**——Streamlit 全部交互走 `/_stcore/stream` 长连接，缺 Upgrade/Connection 头页面直接卡死）、`/app/static/` RV4-7 折中块、`/_stcore/stream` 握手 10r/m、安全头、gzip、`client_max_body_size 50m`（媒体上传） |
| `deploy/Caddyfile.example` | 同语义 Caddy v2 版：自动 HTTPS（免证书路径）、WebSocket 原生支持；vanilla Caddy 无内置限速，差异在文件头如实注明 |
| `deploy/validate.sh` | 静态自检（括号配平/必需指令/占位符提醒），`bash deploy/validate.sh`，无需 nginx 二进制 |

启用步骤（cp → 改占位 → `nginx -t` → `systemctl reload`）与
「nginx -t 需先有证书文件」的实测记录见 deploy/README.md §二。

### 6.2 HTTPS 必要性

Streamlit 本身**无 TLS**（8501 明文 HTTP）：登录表单的用户口令、AI key 配置
等全部经 8501 明文传输。公网部署必须 TLS 终止在反代层（443），8501 不得
直接对公网开放（docker 端口映射口径见 6.4）。

### 6.3 RV4-7 处置口径（`/app/static/` 直链）

**deny all 不可行，落地为「限速＋不索引＋限文件类型」折中。** 已核实：
图谱页 `st.iframe(url)` 嵌的是相对路径 `/app/static/word_graph_<指纹>.html`
（`src/graph_export.py` `ensure_graph_html`/`ensure_cluster_html` 返回值，
`src/app.py` 两处调用），由**浏览器**直接向 `/app/static/` 发 GET（图谱
HTML 内的 `vis-network.min.js` 同样浏览器侧加载）——反代层 deny all 会让
知识图谱/词簇图渲染成空白，图谱 HTML 含内部数据但敏感度低（§五 P3）。

折中实现（两个样例均已含）：static 路由限速 30r/m/IP、`X-Robots-Tag: noindex`
＋不列目录、nginx 侧仅放行 `.html/.js` 其余 404。**残余风险（如实）**：拿到
完整直链的匿名用户仍可取到单个 HTML；缓解因素为文件名含 SHA256 指纹不可
枚举、数据敏感度低 P3、本项目既定定位「编纂端低并发原型」（§五第一行）。
数据敏感度若升级，出路是应用侧路由鉴权（改 Streamlit），非反代层。

### 6.4 Docker 端口映射口径

现仓库 `docker-compose.yml` 的 web 服务是 `"8501:8501"`——**即 0.0.0.0，
宿主所有网卡可达**（MySQL 已是 `127.0.0.1:3306` 合规）。公网部署且反代
同宿主时应改为 `127.0.0.1:8501:8501`，公网流量一律经 443 反代进来；
是否收紧绑定取决于部署拓扑，改部署机上的 compose 文件，样例不代改。
详情（含反代容器化时的 expose 口径）见 deploy/README.md §五。

### 6.5 「login 端点 10r/m」的真实落点

Streamlit **无独立 HTTP 登录端点**：登录表单在应用页面内，提交走
WebSocket `/_stcore/stream`。样例把 10r/m 限速挂在该端点的握手请求上
（每浏览器标签页一次握手，正常用户无感；试口令的重连风暴被压住）。
Caddy 版因 vanilla 无内置限速不落地此项，替代方案见样例文件头注。
