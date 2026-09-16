-- MySQL 初始化脚本 —— Docker 容器首次启动时自动执行
-- （挂载到 /docker-entrypoint-initdb.d/）
--
-- ## 为什么这里不再建表
--
-- 这个脚本以前复制了一份完整的 CREATE TABLE 清单，结果是**两份会漂移的事实来源**：
-- 2026-09 重构表结构时（新增 word_clusters / word_relations、definitions 加
-- cluster_id、删除死表 statistics），这里的副本没同步。而它以 root 身份**先于**应用
-- 执行，一旦建出旧结构的表，应用启动时的 `CREATE TABLE IF NOT EXISTS` 就会
-- **静默跳过**，库就永久停在旧结构上。
--
-- 现在只做 entrypoint 做不到的事：建库与授权。建表统一交给应用侧的
-- `src/mysql_db.py: init_database()` —— 它是唯一的结构权威，同时负责把旧库迁移到
-- 当前 SCHEMA_VERSION（见 _migrate_schema）。

-- 确保库存在且字符集正确（应用也会建，这里让首次连接更顺）
CREATE DATABASE IF NOT EXISTS web_word_db
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 兜底建用户：MYSQL_USER / MYSQL_PASSWORD 环境变量通常已让官方镜像创建了
-- web_word_user@'%'，但 MySQL 8 的 GRANT 不再隐式建用户 —— 用户不存在时整行
-- GRANT 会以 ERROR 1410 失败（"You are not allowed to create a user with GRANT"），
-- 且 initdb 阶段遇错即中断，后面的语句一条都不会执行，权限就没配上。
CREATE USER IF NOT EXISTS 'web_word_user'@'%' IDENTIFIED BY 'webword123';

-- 补上它对业务库的权限（'%' 覆盖容器网络内的连接来源）
--
-- 库名写成 `web\_word\_db` 而不是 web_word_db：GRANT 里的 `_` 是**单字符通配符**
-- （与 LIKE 同规则）。不转义的话授予的是「web_任意字符_word_任意字符_db」这个模式，
-- 同机上的 webXwordYdb 之类无关库会被一并授权。已实测确认过差异：
-- 未转义时该用户能 SELECT 别的库，转义后被拒（1142）。
GRANT ALL PRIVILEGES ON `web\_word\_db`.* TO 'web_word_user'@'%';
FLUSH PRIVILEGES;
