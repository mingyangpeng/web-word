# scripts/ops —— 项目运维脚本（全 Docker 部署口径）

启动项目的各种脚本集中地：环境安装、启动、停止、状态、日志、滚动更新。
**所有启动动作只走 docker compose**（mysql＋web 两容器，代码烧镜像、数据在卷），
不做本机裸跑兜底。

## 脚本一览

| 脚本 | 用途 | 典型场景 |
|---|---|---|
| `install.sh` | 环境安装/自检：Docker daemon（挂了自动拉起）＋ compose v2 ＋ .env（缺则从 .env.example 复制）＋ AI key 存在性 ＋ 端口预检 ＋ 构建镜像 | 新机器首次部署 / 升级代码后重建 |
| `start.sh` | 启动：compose up -d ＋ 轮询健康端点（≤120s） | 日常启动（幂等，重复运行无害） |
| `stop.sh` | 停止：compose stop（容器保留、**数据卷不动**） | 日常停止 |
| `down.sh` | 移除容器：compose down（**不带 -v**，数据卷永不删） | 改了 compose 配置/端口后重建 |
| `status.sh` | 只读状态：容器表＋健康端点＋MySQL 健康＋卷占用 | 巡检 |
| `logs.sh` | 日志：`logs.sh [web\|mysql\|all] [--tail N]` | 排障 |
| `update.sh` | 滚动更新：git pull --ff-only → 重建镜像 → 只替换 web 容器 | 代码升级部署 |

## 快速开始（新机器）

```bash
./start                       # 唯一入口：自检＋缺啥补啥＋启动 → http://localhost:8501
```

## 口径与红线

1. **永不删数据卷**：MySQL 数据、`web-word-app-data` 媒体卷、bind 挂载的
   `data/backups/` 只增不删；所有脚本不带 `-v`。
2. **代码与数据分离**：源码构建进镜像（升级 = `update.sh` 重建）；数据全在
   named volume 与 `data/` bind —— 升级不自伤。
3. **daemon 自愈**：Docker Desktop（macOS）自动 `open -a Docker`、Linux 自动
   `systemctl start docker`，等待就绪后继续；无 docker CLI 则给安装指引退出。
4. **.env 是硬依赖**：compose `env_file` required（v2.24+ 语法）——缺失时
   `install.sh` 从 `.env.example` 复制并提示必填项后**继续构建但先别启动**。
5. **灾备备份**走既有 `scripts/backup_db.sh`（mysqldump＋media 归档，保留 14 份）；
   本目录不做备份，避免双轨。
6. **8502 直跑实例**（开发热载用，`python -m streamlit run src/app.py
   --server.port 8502`）不在本目录职责内；要停它 `pkill -f "streamlit run src/app.py --server.port 8502"`。

## 与既有资产的关系

- `scripts/env_doctor.py` —— 本机裸跑形态的环境体检（./start doctor 历史口径），
  全 Docker 部署用 `install.sh` 替代；doctor 保留用于开发机诊断。
- `scripts/entrypoint.sh` —— 容器入口（种子幂等补种），compose build 时打进镜像。
- `scripts/lib_deploy.sh` / `package_deploy.sh` —— 打包交付/部署函数库，与本目录互补。
- `deploy/nginx.conf.example` 等 —— 公网反代三件套，见 docs/DEPLOYMENT.md。
