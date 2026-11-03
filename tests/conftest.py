"""pytest 全局配置。

本地裸跑 `pytest`（无 Docker）时的连接约定：config.yaml 的 host 是
Docker 服务名 "mysql"，这里在**任何测试模块 import src.* 之前**设置
环境变量（环境变量优先级高于 config.yaml），让页面/集成测试直接连
本机 MySQL。已在 Docker 环境或显式设置了 MYSQL_HOST 时不覆盖。
"""
import os

os.environ.setdefault("MYSQL_HOST", "127.0.0.1")
