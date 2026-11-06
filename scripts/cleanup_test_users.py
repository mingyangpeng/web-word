#!/usr/bin/env python3
"""清理测试残留用户及其协作数据（R5 验收遗留项 1）。

前序 review 轮与 e2e 验收（tests/test_e2e_workflow.py，前缀 ``e2e_r5_``）在
真实库 web_word_db 里留下的测试账号（``agentE_e2e_*`` 等历史轮次遗留为
active=0 的僵尸号）会一直占着 users 表；本脚本按用户名 LIKE 前缀定位这些
残留用户，并连同其 assignments / annotation_submissions / adjudications
关联行（以及该用户触发的 reliability_runs 行，若已有 created_by 归属列）
一并删除。

安全约束（先查后删）：
  * **--dry-run 默认开**：只查询并打印将被删除的用户与关联行清单，不动数据；
  * 只有显式加 ``--apply`` 才真删；删除按外键依赖序（adjudications →
    annotation_submissions → assignments → users）；
  * 匹配规则是**用户名前缀白名单**（LIKE 转义下划线，``_`` 在 LIKE 里是
    单字符通配符，不转义会误伤无关用户），且只删匹配行 —— 生产账号（admin、
    正式标注员）一律不碰；
  * 删除前后各打印一次计数自校验。

用法（仓库根目录）：
    python3 scripts/cleanup_test_users.py            # 预览（dry-run）
    python3 scripts/cleanup_test_users.py --apply    # 真删
    python3 scripts/cleanup_test_users.py --prefix my_e2e_ --apply  # 临时追加前缀
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 与 tests/conftest.py 同约定：任何 import src.* 之前 setdefault（环境变量优先
# 于 config.yaml）。Docker 里 compose 已设 MYSQL_HOST=mysql 不受影响；本地裸跑
# 时 config.yaml 的 host 是服务名 "mysql"，不兜底会连不上。
os.environ.setdefault("MYSQL_HOST", "127.0.0.1")

from src.mysql_db import get_db_cursor  # noqa: E402

# 测试用户名前缀白名单（LIKE 模式；下划线一律转义为 \\_，防单字符通配误伤）。
#  * e2e_r5_   —— tests/test_e2e_workflow.py 专用前缀（异常中断会残留）
#  * agentE_e2e_ —— 前序 review 轮（Agent E）遗留的 e2e 账号（R5 遗留 1：
#                  实测 9 个 active=0 僵尸号）
TEST_USERNAME_LIKES = [
    "e2e\\_r5\\_%",
    "agentE\\_e2e\\_%",
]


def _escape_like(prefix: str) -> str:
    """把裸前缀转成安全的 LIKE 模式：转义 \\ 与 _ 与 %，尾部补 %。"""
    return (
        prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    )


def find_test_users(extra_prefixes) -> list:
    """按前缀白名单查残留用户（先查后删的第一步）。"""
    likes = list(TEST_USERNAME_LIKES) + [_escape_like(p) for p in extra_prefixes]
    users = []
    with get_db_cursor() as cursor:
        for like in likes:
            cursor.execute(
                "SELECT id, username, role, active, created_at FROM users "
                "WHERE username LIKE %s ORDER BY id",
                (like,),
            )
            rows = cursor.fetchall()
            # 多个模式可能重叠，按 id 去重
            seen = {u["id"] for u in users}
            users.extend(r for r in rows if r["id"] not in seen)
    return users


def _count_related(cursor, user_ids) -> dict:
    """统计待删用户在各协作表的关联行数（dry-run 展示用）。"""
    placeholders = ", ".join(["%s"] * len(user_ids))
    counts = {}
    queries = {
        "assignments": (
            f"SELECT COUNT(*) AS n FROM assignments WHERE assignee_id IN ({placeholders}) "
            f"OR assigned_by IN ({placeholders})"
        ),
        "annotation_submissions": (
            f"SELECT COUNT(*) AS n FROM annotation_submissions WHERE coder_id IN ({placeholders})"
        ),
        "adjudications": (
            f"SELECT COUNT(*) AS n FROM adjudications WHERE adjudicator_id IN ({placeholders})"
        ),
    }
    for table, sql in queries.items():
        params = user_ids if table != "assignments" else user_ids + user_ids
        cursor.execute(sql, tuple(params))
        counts[table] = int(cursor.fetchone()["n"] or 0)
    # reliability_runs.created_by 归属列（R5 遗留 2）可能尚未迁移出来：
    # 列存在才统计，不存在视为 0（不报错）
    cursor.execute(
        "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'reliability_runs' "
        "AND COLUMN_NAME = 'created_by'"
    )
    if int(cursor.fetchone()["n"] or 0) > 0:
        cursor.execute(
            f"SELECT COUNT(*) AS n FROM reliability_runs WHERE created_by IN ({placeholders})",
            tuple(user_ids),
        )
        counts["reliability_runs"] = int(cursor.fetchone()["n"] or 0)
    else:
        counts["reliability_runs"] = 0
    return counts


def delete_test_users(user_ids) -> dict:
    """按外键依赖序删除关联行与用户，返回各表删除行数。

    顺序：adjudications（引用 submissions 的 id）→ annotation_submissions →
    assignments → users → reliability_runs（归属列，可能为 0/无列）。
    全程一个事务（autocommit=False），失败整体回滚 —— 不留删一半的中间态。
    """
    placeholders = ", ".join(["%s"] * len(user_ids))
    removed = {}
    with get_db_cursor(autocommit=False) as cursor:
        # 1) adjudications：本人仲裁的 + 仲裁了本人提交的（submission_ids 是
        #    JSON 文本无法 JOIN，按 adjudicator_id 删本人仲裁记录；他人仲裁
        #    本人提交的记录保留 —— 定稿口径是团队事实，不随本人账号删除）
        cursor.execute(
            f"DELETE FROM adjudications WHERE adjudicator_id IN ({placeholders})",
            tuple(user_ids),
        )
        removed["adjudications"] = cursor.rowcount
        # 2) submissions（本人提交）
        cursor.execute(
            f"DELETE FROM annotation_submissions WHERE coder_id IN ({placeholders})",
            tuple(user_ids),
        )
        removed["annotation_submissions"] = cursor.rowcount
        # 3) assignments（分配给本人的 + 本人分配给他人的）
        cursor.execute(
            f"DELETE FROM assignments WHERE assignee_id IN ({placeholders}) "
            f"OR assigned_by IN ({placeholders})",
            tuple(user_ids + user_ids),
        )
        removed["assignments"] = cursor.rowcount
        # 4) reliability_runs（本人触发的信度计算；created_by 列不存在则跳过）
        cursor.execute(
            "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'reliability_runs' "
            "AND COLUMN_NAME = 'created_by'"
        )
        if int(cursor.fetchone()["n"] or 0) > 0:
            cursor.execute(
                f"DELETE FROM reliability_runs WHERE created_by IN ({placeholders})",
                tuple(user_ids),
            )
            removed["reliability_runs"] = cursor.rowcount
        else:
            removed["reliability_runs"] = 0
        # 5) 用户本体（最后删，前面各表已无引用）
        cursor.execute(
            f"DELETE FROM users WHERE id IN ({placeholders})",
            tuple(user_ids),
        )
        removed["users"] = cursor.rowcount
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="清理测试残留用户及其 assignments/submissions 关联行"
                    "（默认 dry-run，--apply 才真删）",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="真正执行删除；缺省只预览（dry-run）",
    )
    parser.add_argument(
        "--prefix", action="append", default=[],
        help="临时追加的用户名前缀（可多次传入；下划线等按字面处理）",
    )
    args = parser.parse_args()

    users = find_test_users(args.prefix)
    if not users:
        print("✅ 未发现测试残留用户（前缀白名单："
              f"{TEST_USERNAME_LIKES + args.prefix or '（无）'}），无需清理。")
        return 0

    user_ids = [int(u["id"]) for u in users]
    print(f"{'⚠️ 将删除' if args.apply else '🔍 发现'} {len(users)} 个测试残留用户：")
    for u in users:
        print(f"  - id={u['id']:<4} username={u['username']!r:<20} role={u['role']:<9} "
              f"active={u['active']} created_at={u.get('created_at')}")

    with get_db_cursor() as cursor:
        related = _count_related(cursor, user_ids)
    total = sum(related.values())
    print("关联行（将随用户一并删除）：")
    for table, n in related.items():
        print(f"  - {table:<24} {n} 行")
    print(f"合计 {len(users)} 个用户 + {total} 行关联数据。")

    if not args.apply:
        print("\n[dry-run] 未改动任何数据。确认无误后加 --apply 真删："
              "python3 scripts/cleanup_test_users.py --apply")
        return 0

    removed = delete_test_users(user_ids)
    print("\n已删除：")
    for table, n in removed.items():
        print(f"  - {table:<24} {n} 行")

    # 删除后自校验：前缀用户必须归零
    leftover = find_test_users(args.prefix)
    if leftover:
        print(f"❌ 清理不彻底：仍残留 {len(leftover)} 个匹配用户", file=sys.stderr)
        return 1
    print("✅ 清理完成，自校验通过（前缀用户已归零）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
