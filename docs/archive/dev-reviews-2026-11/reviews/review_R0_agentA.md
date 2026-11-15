# R0 Review · Agent A：用户与权限模块改动清单

> 依据唯一事实源 `docs/spec/多人标注系统设计规范.md` 实现（§2 users DDL、§3 模块契约、§6 安全规则、验收 V1/V6）。
> 状态：完成。`tests/test_users_db.py` 22 通过（含 15 项真实 MySQL 8.0 集成）；全量 `pytest -q` 235 通过、无回归。

## 1. 新增文件

### `src/users_db.py` —— 用户与权限数据层

- `USERS_TABLE_SQL`：规范 §2 users 表 DDL **原样**（InnoDB / utf8mb4 / ENUM 角色 / UNIQUE username）。
- 规范 §3 契约函数，签名与规范一致（未改动）：
  - `ensure_user_tables() -> None`：幂等建表；**users 表为空时自动创建内置默认管理员 admin/admin123**（display_name=内置管理员，role=admin），docstring 与日志注明**首次登录后必须改密**；日志不落口令明文。DB 不可用时只记日志不抛（与 `mysql_db.init_database` 容错口径一致）。
  - `hash_password(plain) -> str`：`pbkdf2_sha256$150000$salt_hex$hash_hex`；每用户随机盐 `secrets.token_hex(16)`，150000 迭代（≥规范下限 120000）。
  - `verify_password(plain, stored) -> bool`：解析存储串，`hmac.compare_digest` 常数时间比较；存储串脏数据（缺字段/算法不符/非十六进制）一律 False 不抛异常。
  - `verify_login(username, password) -> dict | None`：active=1 才返回 `{id, username, display_name, role}`（不含 password_hash）；「无此用户/密码错/已停用」统一返回 None，防账号枚举。
  - `create_user(username, password, display_name, role) -> int | None`：角色应用层先校验（`ROLES` 枚举，非法值不进库）；用户名重复（UNIQUE）返回 None。
  - `list_users() -> list[dict]`：只返回 id/username/display_name/role/active/created_at，**不返回 password_hash**（哈希不出数据层）。
  - `set_role(user_id, role) -> bool` / `set_active(user_id, active) -> bool`：参数化 UPDATE；非法角色 False；目标值与现值相同（MySQL 不计变更行）返回 False，docstring 已注明语义。
- 全部 SQL 参数化，无字符串拼接；风格沿用 `src/mysql_db.py`（`get_db_cursor` + try/except pymysql.Error + logger）。

### `src/users_admin_page.py` —— 用户管理页（Streamlit，仅 admin）

- 入口 `render_users_admin_page()`：**role gate 在函数入口**（§6-4，读 `st.session_state["user"]`），未登录 warning、非 admin error 拦截。
- 功能：统计卡（总用户/启用中/管理员）＋ 用户列表 HTML 表 ＋ 改角色表单 ＋ 停用/启用表单 ＋ 新建用户表单（`st.form`，提交后 `st.rerun()` 刷新）。
- 样式沿用 `src/app.py` 的模式：`design_system` 的 `HEADER_H1/H2/H3`、`get_card_style`、`get_table_header_style/row_style`；徽章沿用 `category_study_page._badge` 视觉。
- 安全（§6-3）：所有用户名/显示名/时间等进 `unsafe_allow_html` 前一律过 `_html_escape`；密码框不回显、提交后从 `st.session_state` 清除；**自保护：admin 不能停用自己、不能撤销自己的 admin 角色**（防最后一个管理员锁死系统）。
- 未接入 `app.py`（集成由后续步骤统一做，规范 §5）。

### `tests/test_users_db.py` —— 22 项测试

- 纯函数层（无 DB，CI 必跑）：hash/verify 往返、错密码拒绝、格式断言（4 段/迭代≥120000/盐 32 hex/hash 64 hex）、同明文异盐、中文 emoji 口令、8 种脏存储串+篡改位拒绝、None 存储。
- 集成层（`@pytest.mark.skipif(not HAS_MYSQL, ...)`，与 `test_migration_integration.py` 同约定：连不上/无建库权限即 skip）：
  - 内置 admin bootstrap、ensure 幂等、ensure 不动已有用户；
  - create+login 往返、错密码/不存在用户/重复用户名拒绝、非法角色（create_user 与 set_role 双入口）被拒且不入库；
  - set_role 生效、set_active 停用禁登/启用恢复、对不存在用户返回 False；
  - 安全不变量：库中 `password_hash` 为 pbkdf2 格式且明文不在其中、`list_users` 无 password_hash 字段、空用户名/空密码拒绝。
  - 集成跑在独立测试库 `web_word_users_test`（monkeypatch `db.MYSQL_DATABASE`，连接池按 db 名隔离），每测重建、结束 DROP，不污染业务库。

## 2. 未改动

- `src/app.py`、`src/mysql_db.py`、`requirements.txt`（无新增依赖）—— 按约束保持原样。

## 3. 验证记录

| 项 | 结果 |
|---|---|
| `python3 -m pytest tests/test_users_db.py -q` | 22 passed（MySQL 8.0.46 本地实跑，15 项集成非 skip） |
| `python3 -m pytest -q`（全量回归，验收 V6） | **235 passed，0 failed** |
| `flake8 src/users_db.py src/users_admin_page.py tests/test_users_db.py` | 0 违规（repo `.flake8`，max-line 100） |
| 规范 §3 签名核对 | 8 个函数签名逐一与规范一致 |

- 环境备注：本机 homebrew mysql@8.0 未运行，为实跑集成测试临时启动 `mysqld`（`--defaults-file=/opt/homebrew/etc/my.cnf`，datadir=repo `data/mysql`），按 `test_migration_integration.py` 文档给 `web_word_user` 授了 `web_word_users_test` / `web_word_migration_test` 两库权限（后者同时解锁了既有迁移集成测试），验证后已 `mysqladmin shutdown` 还原（GRANT 保留，属该测试文档明文要求的操作）。无 MySQL 时集成测试自动 skip，CI 仍全绿。

## 4. 遗留与交接

- 登录框/侧边栏徽章/角色分派进 `app.py`（规范 §5）由集成步骤完成；本模块提供 `verify_login` 返回值即 `st.session_state["user"]` 的结构。
- 「修改密码」入口按规范 §5 属登录/个人设置页职责，users_db 未含 change_password 函数（规范 §3 未定义，不擅自加）。
- 集成时调用 `ensure_user_tables()`（建议在 app 启动/登录框渲染前），users 表为空即得内置 admin。
