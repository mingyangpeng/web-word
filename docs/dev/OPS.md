# OPS.md —— 运维速查备忘（给未来忘了上下文的维护者，人 ＋ AI agent 都看这份）

> 2026-11-15 批次 36–38 归一定版。忘了任何背景：先读本文，再跑 `./start status`。

## 一、一句话现状

- **代码**：git 唯一真相；8501 容器 bind mount 宿主代码目录（动态映射）＝ 8502 直跑 ＝ 工作树，天然同源
- **业务库**：容器 MySQL（`web-word-mysql`）`web_word_db` **61 表**是唯一业务库（词典全量 zh_dict_* ＋ users ＋ 全部业务表）
- **测试库**：宿主 mysqld **3307**（仅 pytest；30 个 `web_word_*_test` 动态建删；业务数据与它无关）
- **启动**：根目录唯一入口 `./start`（八步幂等流：daemon→env→端口→镜像→容器→健康→锚点→就绪）

## 二、端口与凭据

| 项 | 值 | 说明 |
|---|---|---|
| 8501 | 容器 web | 对外主入口（compose 映射 0.0.0.0——公网部署需改 127.0.0.1） |
| 8502 | 宿主直跑 streamlit | 开发热载（连同一个容器业务库） |
| 3306 | 容器 MySQL | 业务库；宿主 `my.cnf` 已固化 port=3307，宿主 mysqld 物理上抢不了 |
| 3307 | 宿主 mysqld | pytest 专用；不启动时跑 pytest 前需拉起（命令见 tests/conftest.py docstring） |
| MySQL 账号 | `web_word_user` / `<your-mysql-password>` | .env 与容器 MYSQL_USER 同源 |
| 归一前备份 | `data/backups/db/manual-20261115-1237-pre-unify.sql.gz` | 数据库归一回滚锚点 |

## 三、命令速查

```bash
./start                  # 万能启动（缺啥补啥）
./start status           # 巡检（含数据库拓扑自检——3306 占用者/61 表锚点/3307 状态）
./start stop | down | logs | update | backup | doctor
pytest                   # 连宿主 3307（conftest 固定；CI 显式 3306 不受影响）
docker compose restart web   # 改码后让 8501 生效（bind mount 动态映射，无需重建镜像）
```

## 四、坑位清单（历史上真的踩过）

1. **宿主 mysqld 抢 3306** → 8502 假离线。已双保险：my.cnf 固化 3307＋start 第③步自动处置。再犯时 `lsof -nP -iTCP:3306 -sTCP:LISTEN` 看占用者。
2. **brew 默认 datadir 旧废库**（/opt/homebrew/var/mysql）→ 连上就是错数据。已归档改名 `web_word_db.ARCHIVED-pre-batch36`。若 mysqld 启动参数不带 --datadir，my.cnf 已写死 `datadir = data/mysql`。
3. **应用假离线（healthcheck 骗人）**：healthcheck 只探活不探库——瞬时断连后 fail-open 标记钉死，容器显示 healthy 但页面报离线。处置：`docker compose restart web`（8502 则刷新页面/重启进程）。
4. **pytest 容器环境漂移**：pytest 直连容器 3306 时跨文件连跑失败集漂移（141 failed vs 单跑全绿）——所以测试走 3307 双轨。别轻易改 conftest 回 3306。
5. **st.sidebar.\* 容器陷阱**：`st.sidebar.form/button` 显式绑定 sidebar 根容器，会脱离 `with st.sidebar.expander/container(...)` 上下文（批次 34/35 两次踩坑）——侧栏内嵌套一律用 `st.form`/`st.button`。
6. **`.tmp-shots/`、`.tmp/` 中间产物**：截图/探针残留，不入库可随时删。

## 五、挂账（接手者优先看）

- **stash@{0}**：侧边栏 `st.sidebar.button → st.button` 根因修复（区头/按钮真正落进 `ls_nav` 容器）——配套 AppTest 跨文件适配未完成（5 失败），修好再 pop 落地
- **`src/section_dock.py`**：另一会话并行开发中的页内 Dock 导航（app.py 已接线，未提交）——**不要动别人的活**
- CHANGELOG/findings_backlog 缺批次 34/35 条目（批次 36/37 已补）
- 待用户裁决：词表核定（configs/style.yaml DEFINING_VOCAB，质检唯一 fail）／第二标注人（双盲 IAA）／Robert 引文／AI 供应商配置

## 六、文档地图

- 部署全流程：`docs/DEPLOYMENT.md`（§三·五 数据库拓扑定版节）
- 测试口径：`docs/dev/TESTING.md`；架构：`docs/dev/ARCHITECTURE.md`
- 台账：`docs/dev/CHANGELOG.md`（批次序列）＋ `docs/dev/reports/findings_backlog.md`（滚动修复）
- 使用手册：`docs/使用说明书.md`；帮助母本：`docs/help/平台功能使用说明.md`
