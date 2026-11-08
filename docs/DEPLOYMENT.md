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
| 6 | `enableStaticServing` | true（图谱 HTML 需要）——**注意**：`/app/static/*` 无鉴权（RV4-7），如含敏感数据须改路由 |
| 7 | `server.headless` | true（无浏览器弹窗）✅ |

### 1.3 Docker / 网络安全

| # | 检查项 | 现状 |
|---|--------|------|
| 8 | MySQL 端口绑定 | ✅ 已改为 `127.0.0.1:3306:3306`（不再暴露 0.0.0.0） |
| 9 | HTTPS | **待部署层配置**——Streamlit 本身无 TLS，需 Nginx/Caddy 反代＋Let's Encrypt |
| 10 | CORS / XSRF | Streamlit 默认启用 ✅ |
| 11 | Docker 网络 | compose 内部网络隔离 MySQL（已改 127.0.0.1 后外部不可达） |

### 1.4 备份与恢复

| # | 检查项 | 操作 |
|---|--------|------|
| 12 | 备份自动化 | `crontab -e` 添加 `15 2 * * * cd /path/to/web-word && bash scripts/backup_db.sh --keep 14 >> data/logs/backup_db.log 2>&1` |
| 13 | 备份验证 | 每月抽一份 `*.sql.gz` 在沙箱实例恢复演练 |
| 14 | G6 备份新鲜卡 | 部署后确认词典管理→出版导出→备份新鲜卡显示 ✅ |

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

## 三、部署后

| # | 检查项 | 方法 |
|---|--------|------|
| 1 | 全页可用 | 侧边栏 16 页逐页点击（或用 test_review_regression.py 40 用例 AppTest 矩阵） |
| 2 | AI 功能 | 搜索 run → 四卡片出全 → 以句搜义输入一句话 → 最近邻出结果 |
| 3 | 撰写→审校→终裁→出版 | 走一遍编纂链（需 ≥2 账号：编纂员＋审校） |
| 4 | 权限隔离 | viewer 账号登录确认不可见管理区 |
| 5 | 备份验证 | 词典管理→出版导出→备份新鲜卡 ✅ |
| 6 | 日志审计 | 服务端日志无 PermissionError/traceback 外泄 |

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
| `/app/static/*` 无鉴权 | P3 | 图谱数据敏感度低；如需收紧改路由 |
| `.env` 历史含旧凭据 | P1 | 轮换后旧值失效即消解；filter-repo 可选 |
| requests >=2.31 下限 | P3 | requirements 已提至 >=2.32.4；CI 加 pip-audit（待实施） |
