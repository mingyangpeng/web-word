#!/usr/bin/env bash
#
# snapshot_db.sh —— 把当前容器业务库固化成「部署快照」（新机带数据部署）。
#
# 用法：./start snapshot   （或 bash scripts/snapshot_db.sh）
#
# 做什么：
#   1. dump 容器业务库 web_word_db（--single-transaction 一致性快照）
#      → data/deploy-snapshot/web_word_db.sql.gz（固定路径，**入库**）；
#   2. **脱敏**：排除 llm_providers 表（供应商 api_key 明文——新机在
#      「🤖 模型供应商」页重配，不进 git）；
#   3. 校验：gzip 完整性＋61 表锚点计数写入快照旁的 manifest（表数/时间/
#      源实例），恢复端据此告警；
#   4. 提醒：新机部署 = clone（含本快照）→ cp .env.example .env 填三键
#      → ./start（检测快照＋空库自动恢复，见 start 第⑦步前段）。
#
# 与 backup 的分工：backup 是运维灾备（data/backups，不入库、保留 14 份、
# 可恢复任意时点）；snapshot 是部署资产（固定路径、入库、随仓库分发、
# 恢复目标=新机空库）。二者互不替代。

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/scripts/ops/_common.sh"
cd "$ROOT"

ensure_docker_daemon
require_compose

OUT_DIR="$ROOT/data/deploy-snapshot"
OUT_FILE="$OUT_DIR/web_word_db.sql.gz"
mkdir -p "$OUT_DIR"

say_info "① dump 业务库（排除 llm_providers——api_key 不进 git）"
RAW_SQL="$(mktemp /tmp/web_word_snapshot.XXXXXX.sql)"
# 口令走 MYSQL_PWD 环境变量（ps 不可见）；stderr 保留输出（dump 失败原因可见）
if ! docker exec web-word-mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --routines --triggers --ignore-table=web_word_db.llm_providers web_word_db' > "$RAW_SQL"; then
    say_err "mysqldump 失败——容器内 stderr 已在上方输出；检查 mysql 容器状态（./start status）"
    rm -f "$RAW_SQL"; exit 1
fi

say_info "② 脱敏双保险：清除 dump 里 llm_providers 的残留段（若 ignore 表仍有 INSERT 头）"
sed -i '' '/INSERT INTO `llm_providers`/d' "$RAW_SQL" 2>/dev/null || sed -i '/INSERT INTO `llm_providers`/d' "$RAW_SQL"

say_info "③ gzip＋完整性校验"
gzip -c "$RAW_SQL" > "$OUT_FILE" && rm -f "$RAW_SQL"
gzip -t "$OUT_FILE" || { say_err "gzip 完整性校验失败——保留原始 $RAW_SQL 供排查"; exit 1; }
say_info "④ manifest（表数锚点）"
n_tables="$(docker exec web-word-mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=\"web_word_db\""' 2>/dev/null || echo "?")"
printf 'tables=%s\ngenerated=%s\nsource=container-mysql-3306\nsha256=%s\n' "$n_tables" "$(date '+%Y-%m-%d %H:%M')" "$(shasum -a 256 "$OUT_FILE" | awk '{print $1}')" > "$OUT_DIR/manifest.txt"
say_ok "快照完成：${OUT_FILE}（$(du -h "$OUT_FILE" | cut -f1)），manifest tables=$n_tables"
if [ "$n_tables" != "61" ]; then
    say_warn "表数 $n_tables ≠ 61——源库状态异常，快照仍已生成，恢复端会按 manifest 告警"
fi
say_info "新机部署：git clone（含快照）→ cp .env.example .env 填三键 → ./start（自动检测快照＋空库恢复）"
