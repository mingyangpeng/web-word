-- 本地开发用：一次性完成 MySQL 授权（幂等，可重复执行）
--
-- 用法（需要 root 权限）：
--     mysql -u root -p < scripts/grant_local_mysql.sql
--     或本机 root 免密时：mysql -u root < scripts/grant_local_mysql.sql
--
-- ## 授权对象分两类
--
-- 1. web_word_db —— 应用真正用的库。
-- 2. web_word_migration_test —— tests/test_migration_integration.py 用的临时库。
--    那个测试必须在真 MySQL 上跑（它验证的正是「迁移后业务数据还在不在」），
--    而它需要自己 CREATE / DROP 这个库。MySQL 的规则是：只要在某个具体库上被授予
--    ALL，就在该库名上拥有 CREATE/DROP 权限，不需要全局权限 —— 所以这一条授权
--    就够了，不必给 web_word_user 任何全局权限。
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

FLUSH PRIVILEGES;

-- ---------- 5. 自检输出 ----------
SELECT '授权完成' AS status;
SELECT Host, Db AS granted_pattern FROM mysql.db WHERE User = 'web_word_user';
