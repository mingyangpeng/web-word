-- 本地开发用：一次性完成 MySQL 授权（幂等，可重复执行）
--
-- 用法（需要 root 权限）：
--     mysql -u root -p < scripts/grant_local_mysql.sql
--     或本机 root 免密时：mysql -u root < scripts/grant_local_mysql.sql
--
-- ## 授权对象分三类
--
-- 1. web_word_db —— 应用真正用的库。
-- 2. web_word_migration_test —— tests/test_migration_integration.py 用的临时库。
--    那个测试必须在真 MySQL 上跑（它验证的正是「迁移后业务数据还在不在」），
--    而它需要自己 CREATE / DROP 这个库。MySQL 的规则是：只要在某个具体库上被授予
--    ALL，就在该库名上拥有 CREATE/DROP 权限，不需要全局权限 —— 所以这一条授权
--    就够了，不必给 web_word_user 任何全局权限。
-- 3. tests/ 各模块集成测试的独立测试库（2b/4b 两节：users/flow/ai_ledger/media/
--    wordforms，grep -rn "web_word_.*_test" tests/ 的实测清单）—— 同样只需库名级
--    ALL，fixture 自己 DROP/CREATE。
--
-- ## 库名里的下划线必须转义 —— 这是本文件最要紧的一条
--
-- GRANT 语句里的 `_` 是**单字符通配符**，和 `LIKE` 一样。写成
--     GRANT ALL PRIVILEGES ON web_word_db.* ...
-- 授予的其实是「web_任意单字符_word_任意单字符_db」这个模式，
-- 于是 `webXwordYdb` 也会被一起授权 —— 一个同机上的无关数据库可能因此被读到。
--
-- 已实测确认：未转义时 web_word_user 能 SELECT `webXwordYdb.secret`；
-- 写成 `web\_word\_db` 后同一个用户被拒绝（1142 SELECT command denied）。
--
-- 所以本文件里**每一处库名都写成 `\_`**。加不加反引号不影响通配符语义，
-- 反引号只是引用标识符，不改变 GRANT 的模式匹配行为。

-- ---------- 1. 应用库 ----------
CREATE DATABASE IF NOT EXISTS web_word_db
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------- 2. 迁移集成测试用的临时库 ----------
CREATE DATABASE IF NOT EXISTS web_word_migration_test
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------- 2b. 集成测试库（tests/ 实测清单，幂等） ----------
-- grep -rn "web_word_.*_test" tests/ 的实测清单；各模块集成测试的 fixture 自己
-- DROP/CREATE 测试库，这里的 CREATE IF NOT EXISTS 只是让空库先存在（与上面
-- migration 测试库同口径）。实测归属：
--   web_word_users_test      test_users_db / test_org_db / test_dict_admin_db /
--                            test_collab_pages / test_integration_apptest /
--                            test_security_hardening / test_pipeline_status 共用
--   web_word_flow_test       test_annotation_flow
--   web_word_ai_ledger_test  test_ai_ledger
--   web_word_media_test      test_media_db
--   web_word_wordforms_test  test_wordforms_db
CREATE DATABASE IF NOT EXISTS web_word_users_test
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS web_word_flow_test
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS web_word_ai_ledger_test
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS web_word_media_test
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS web_word_wordforms_test
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ---------- 3. 建用户（幂等）----------
-- MySQL 8 的 GRANT 不再隐式建用户，用户不存在时整行 GRANT 会以
-- ERROR 1410 ("You are not allowed to create a user with GRANT") 失败，
-- 且脚本遇错即中断，后面的授权一条都不会执行。
--
-- 为什么要三个 host：
--   * 'localhost'  —— 走 Unix socket 的连接
--   * '127.0.0.1'  —— 走 TCP 的连接
--   * '%'          —— 容器 / 其它主机（Docker Compose 里 web 容器连 mysql 服务走这个）
-- MySQL 把 host 视为用户身份的一部分，三者是三个不同的账号。
-- 另外 MySQL 默认会把 127.0.0.1 反解成 localhost，所以 @'localhost' 的授权
-- 对 TCP 连接同样生效 —— 这正是漏授权 / 多授权都容易踩坑的地方，
-- 也是上面那条「下划线必须转义」更需要注意的原因。
CREATE USER IF NOT EXISTS 'web_word_user'@'localhost' IDENTIFIED BY 'webword123';
CREATE USER IF NOT EXISTS 'web_word_user'@'127.0.0.1' IDENTIFIED BY 'webword123';
CREATE USER IF NOT EXISTS 'web_word_user'@'%'         IDENTIFIED BY 'webword123';

-- ---------- 4. 授权（库名一律 `\_` 转义）----------
GRANT ALL PRIVILEGES ON `web\_word\_db`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_db`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_db`.* TO 'web_word_user'@'%';

GRANT ALL PRIVILEGES ON `web\_word\_migration\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_migration\_test`.* TO 'web_word_user'@'127.0.0.1';

-- ---------- 4b. 集成测试库授权（库名一律 `\_` 转义；三 host 与应用库同口径，
-- 容器里跑 pytest 时走 '%'） ----------
GRANT ALL PRIVILEGES ON `web\_word\_users\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_users\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_users\_test`.* TO 'web_word_user'@'%';

GRANT ALL PRIVILEGES ON `web\_word\_flow\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_flow\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_flow\_test`.* TO 'web_word_user'@'%';

GRANT ALL PRIVILEGES ON `web\_word\_ai\_ledger\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_ai\_ledger\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_ai\_ledger\_test`.* TO 'web_word_user'@'%';

GRANT ALL PRIVILEGES ON `web\_word\_media\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_media\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_media\_test`.* TO 'web_word_user'@'%';

GRANT ALL PRIVILEGES ON `web\_word\_wordforms\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_wordforms\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_wordforms\_test`.* TO 'web_word_user'@'%';

FLUSH PRIVILEGES;

-- ---------- 5. 自检输出 ----------
SELECT '授权完成' AS status;
SELECT Host, Db AS granted_pattern FROM mysql.db WHERE User = 'web_word_user';

-- 阶段 1 批次 5：按模块分库（防并行 pytest 互删，见 docs/spec/阶段1施工规范.md §8）
GRANT ALL PRIVILEGES ON `web\_word\_org\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_org\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_dict\_admin\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_dict\_admin\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_collab\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_collab\_test`.* TO 'web_word_user'@'localhost';
FLUSH PRIVILEGES;

-- 阶段 2 批次 7/8：编纂成文域与端到端验收测试库
GRANT ALL PRIVILEGES ON `web\_word\_writing\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_writing\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_lexical\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_lexical\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_stage1\_e2e\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_stage1\_e2e\_test`.* TO 'web_word_user'@'localhost';
FLUSH PRIVILEGES;

-- 批次 12：十轮 review 回归固化测试库
GRANT ALL PRIVILEGES ON `web\_word\_review\_regression\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_review\_regression\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_review\_regression\_test`.* TO 'web_word_user'@'%';
FLUSH PRIVILEGES;

-- 批次 13：多供应商 LLM 测试库
GRANT ALL PRIVILEGES ON `web\_word\_llm\_providers\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_llm\_providers\_test`.* TO 'web_word_user'@'localhost';
FLUSH PRIVILEGES;

-- FX-18：范畴×工具两步激活持久化测试库（tests/test_fx18_fixes.py）
GRANT ALL PRIVILEGES ON `web\_word\_fx18\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_fx18\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_fx18\_test`.* TO 'web_word_user'@'%';
FLUSH PRIVILEGES;

-- FX-19：协同度量五指标测试库（tests/test_fx19_fixes.py）
GRANT ALL PRIVILEGES ON `web\_word\_fx19\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_fx19\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_fx19\_test`.* TO 'web_word_user'@'%';
FLUSH PRIVILEGES;

-- FX-20：改派 / 试标轮两列 / 重标闭环测试库（tests/test_fx20_fixes.py）
GRANT ALL PRIVILEGES ON `web\_word\_fx20\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_fx20\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_fx20\_test`.* TO 'web_word_user'@'%';
FLUSH PRIVILEGES;

-- FX-25：AI 体例质检引擎测试库（tests/test_fx25_fixes.py）
GRANT ALL PRIVILEGES ON `web\_word\_fx25\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_fx25\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_fx25\_test`.* TO 'web_word_user'@'%';
FLUSH PRIVILEGES;

-- FX-31：用户上下文域 5 表测试库（tests/test_fx31_fixes.py）
GRANT ALL PRIVILEGES ON `web\_word\_fx31\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_fx31\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_fx31\_test`.* TO 'web_word_user'@'%';
FLUSH PRIVILEGES;
-- FX-33：两步激活原子复验/用户上下文 CASCADE/广播归因测试库（tests/test_fx33_fixes.py）
GRANT ALL PRIVILEGES ON `web\_word\_fx33\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_fx33\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_fx33\_test`.* TO 'web_word_user'@'%';
FLUSH PRIVILEGES;
-- FX-32：改派原子复验/重标幂等闸测试库（tests/test_fx32_fixes.py）
GRANT ALL PRIVILEGES ON `web\_word\_fx32\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_fx32\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_fx32\_test`.* TO 'web_word_user'@'%';
FLUSH PRIVILEGES;
FLUSH PRIVILEGES;

-- RV18-1：查询归因真库沙箱（tests/test_fx27_fixes.py 实用库）
GRANT ALL PRIVILEGES ON `web\_word\_r1\_probe`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_r1\_probe`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_r1\_probe`.* TO 'web_word_user'@'%';

-- RV18-1：项目广播域测试库（tests/test_fx30_fixes.py）
GRANT ALL PRIVILEGES ON `web\_word\_fx30\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_fx30\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_fx30\_test`.* TO 'web_word_user'@'%';
FLUSH PRIVILEGES;

-- RV-22：批次 14~17 新功能端到端回归固化测试库（tests/test_review_r18.py，
-- 六链跨模块固化：工具两步激活/质检→指标/广播→收件箱/改派→重标/落地三分支/跨设备续接）
GRANT ALL PRIVILEGES ON `web\_word\_review\_r18\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_review\_r18\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_review\_r18\_test`.* TO 'web_word_user'@'%';
FLUSH PRIVILEGES;

-- FX-38：模板人工修订测试库（tests/test_template_revision_db.py）
GRANT ALL PRIVILEGES ON `web\_word\_template\_revision\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_template\_revision\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_template\_revision\_test`.* TO 'web_word_user'@'%';
FLUSH PRIVILEGES;

-- FX-43：AI 草稿快照迁移/逐特征一致率测试库（tests/test_fx43_fixes.py）
GRANT ALL PRIVILEGES ON `web\_word\_fx43\_test`.* TO 'web_word_user'@'127.0.0.1';
GRANT ALL PRIVILEGES ON `web\_word\_fx43\_test`.* TO 'web_word_user'@'localhost';
GRANT ALL PRIVILEGES ON `web\_word\_fx43\_test`.* TO 'web_word_user'@'%';
FLUSH PRIVILEGES;
