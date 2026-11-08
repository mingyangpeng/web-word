#!/usr/bin/env python3
"""
wait_for_mysql.py — 等待 MySQL 就绪后再启动 Streamlit

在 Docker CMD 中使用:
    python scripts/wait_for_mysql.py && streamlit run src/app.py

或者作为入口脚本:
    python scripts/wait_for_mysql.py && exec "$@"
"""

import os
import sys
import time
import socket

HOST = os.getenv("MYSQL_HOST", "mysql")
PORT = int(os.getenv("MYSQL_PORT", "3306"))
MAX_RETRIES = 30
RETRY_DELAY = 2


def check_mysql(host: str, port: int) -> bool:
    """以能真正执行 SQL 为就绪标准（RV9-7：TCP 可达 ≠ SQL 可用 —— 服务端
    初始化/换实例窗口期端口通但查询失败）。先试 pymysql 真查询，凭据未就绪
    等场景退回纯端口探测（保持「离线降级可启动」的兜底语义）。"""
    try:
        import pymysql
        conn = pymysql.connect(
            host=host, port=port, connect_timeout=3,
            user=os.getenv("MYSQL_USER", "web_word_user"),
            password=os.getenv("MYSQL_PASSWORD", "webword123"),
        )
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        return True
    except Exception:
        try:
            with socket.create_connection((host, port), timeout=3):
                return True
        except (ConnectionRefusedError, OSError, TimeoutError):
            return False


def main():
    print(f"⏳ Waiting for MySQL at {HOST}:{PORT}...")

    for attempt in range(1, MAX_RETRIES + 1):
        if check_mysql(HOST, PORT):
            # 查询可达，额外等 1 秒让 MySQL 完成初始化
            time.sleep(1)
            print(f"✅ MySQL is ready! (attempt {attempt}/{MAX_RETRIES})")
            sys.exit(0)

        print(f"  Attempt {attempt}/{MAX_RETRIES} — MySQL not ready, retrying in {RETRY_DELAY}s...")
        time.sleep(RETRY_DELAY)

    print(f"⚠️  MySQL did not become ready after {MAX_RETRIES} attempts. Starting app in offline mode...")
    sys.exit(0)  # Exit 0 so the app still starts in offline mode


if __name__ == "__main__":
    main()
