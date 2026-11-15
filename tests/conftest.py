"""pytest 全局配置。

本地裸跑 `pytest`（无 Docker）时的连接约定：config.yaml 的 host 是
Docker 服务名 "mysql"，这里在**任何测试模块 import src.* 之前**设置
环境变量（环境变量优先级高于 config.yaml），让页面/集成测试直接连
本机 MySQL。已在 Docker 环境或显式设置了 MYSQL_HOST/MYSQL_PORT 时
不覆盖。

批次 36 数据库归一后的双轨口径：业务库统一容器 MySQL（127.0.0.1:3306，
8501/8502 都连它）；测试库走宿主机 mysqld **3307**（datadir 与历史测试
环境完全一致——容器环境下跨文件连跑出现大面失败集漂移，测试基建回退
到已验证的宿主实例；业务数据不受影响）。宿主 mysqld 启动：
    nohup /opt/homebrew/bin/mysqld --defaults-file=/opt/homebrew/etc/my.cnf \\
        --port=3307 --bind-address=127.0.0.1 >/tmp/mysqld_dev.log 2>&1 &
"""
import os

os.environ.setdefault("MYSQL_HOST", "127.0.0.1")
# 测试专用端口（宿主 mysqld 3307；容器业务库占 3306）。CI 里 services:
# mysql:8 容器映射的是 3306，显式设置了 MYSQL_PORT 时不覆盖。
os.environ.setdefault("MYSQL_PORT", "3307")
# 测试账号口令（批次 41 史清理后 config.yaml 的密码位为占位——测试进程 env
# 优先级高于 config.yaml，这里 setdefault 保证本地 pytest 连接；与
# grant_local_mysql.sql 的授权口径同值。CI 显式设置时不受影响。）
os.environ.setdefault("MYSQL_PASSWORD", "webword123")

# 时序契约收口：共享 helper（tests/helpers.py，review P3 收敛落点）含 src.*
# import（page_guides、mysql_db 探针），必须在上面 env 设定**之后**加载。
# pytest 先于一切测试模块导入本文件，这里显式 import 一次即可固定顺序；
# 各测试文件 `from tests.helpers import ...` 命中 sys.modules 缓存，不会重复执行。
from tests import helpers  # noqa: E402,F401  (导入即固定 helper 的 src 加载时序)
