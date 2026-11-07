#!/usr/bin/env bash
#
# backup_db.sh —— 运维性灾备备份（架构规范 §6 备份三件套 / §10 部署与运维 /
# §15 数据出入口纪律：运维性备份归平台管理员，目的限于灾备；备份文件按敏感
# 数据受控存放，不得用于对外交付 —— 对外交付必须走词典管理员的出版导出，
# 即词典管理区「出版导出」tab 的 G6 闸门内容域快照）。
#
# 做什么（一次运行 = 一批）：
#   1. mysqldump 全库（连接参数读仓库根 .env；--single-transaction 一致性
#      快照，InnoDB 不锁表）→ gzip → data/backups/db/YYYYMMDD-HHMM.sql.gz；
#   2. data/media 媒体资产目录 → tar.gz 同批归档 →
#      data/backups/media/YYYYMMDD-HHMM-media.tar.gz（media 缺位则跳过并注明）；
#   3. 保留策略：每类目录只留最新 KEEP 份（默认 14），超出删最旧；
#   4. 末尾打印最新备份路径（G6「备份新鲜」卡扫 data/backups/ 的
#      *.sql.gz / *.tar.gz 判在场与新鲜度）。
#
# 用法：
#   bash scripts/backup_db.sh             # 保留默认 KEEP=14
#   bash scripts/backup_db.sh --keep 1    # 只留最新 1 批（验收/省盘用法）
#   bash scripts/backup_db.sh --keep=7    # 等号写法等价
#
# 定时调度（crontab 一行示例；launchd 用户把同命令写进 plist 的
# ProgramArguments 即可）：
#   15 2 * * * cd /Users/jhon/pmy/web-word && bash scripts/backup_db.sh --keep 14 >> data/logs/backup_db.log 2>&1
#
# 依赖：mysqldump / gzip / tar 在 PATH 中（本机 Homebrew MySQL 8 自带）。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

usage() {
  sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
}

# ---------- 参数解析：--keep N / --keep=N / -h ----------
KEEP=14
while [ $# -gt 0 ]; do
  case "$1" in
    --keep)
      [ $# -ge 2 ] || { echo "错误：--keep 需要一个正整数参数" >&2; exit 2; }
      KEEP="$2"; shift 2 ;;
    --keep=*)
      KEEP="${1#*=}"; shift ;;
    -h|--help)
      usage ;;
    *)
      echo "错误：未知参数 $1（用法：backup_db.sh [--keep N]）" >&2; exit 2 ;;
  esac
done

case "$KEEP" in
  ''|*[!0-9]*)
    echo "错误：--keep 必须是非负整数，得到：$KEEP" >&2; exit 2 ;;
esac
[ "$KEEP" -ge 1 ] || { echo "错误：--keep 至少为 1" >&2; exit 2; }

# ---------- 读 .env 连接参数（KEY=VALUE 逐行提取，不 source） ----------
if [ ! -f "$ENV_FILE" ]; then
  echo "错误：找不到 ${ENV_FILE}（mysqldump 连接参数从这里读取）" >&2
  exit 1
fi

env_value() {
  # 取 KEY=VALUE 的 VALUE：去行内注释、首尾空白与成对引号；无值输出空串
  local line
  line="$(grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true)"
  line="${line%%#*}"
  line="$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
    -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/")"
  printf '%s' "$line"
}

MYSQL_HOST_VAL="$(env_value MYSQL_HOST)"
MYSQL_PORT_VAL="$(env_value MYSQL_PORT)"
MYSQL_DATABASE_VAL="$(env_value MYSQL_DATABASE)"
MYSQL_USER_VAL="$(env_value MYSQL_USER)"
MYSQL_PASSWORD_VAL="$(env_value MYSQL_PASSWORD)"

MYSQL_HOST_VAL="${MYSQL_HOST_VAL:-127.0.0.1}"
MYSQL_PORT_VAL="${MYSQL_PORT_VAL:-3306}"
if [ -z "$MYSQL_DATABASE_VAL" ] || [ -z "$MYSQL_USER_VAL" ]; then
  echo "错误：.env 缺 MYSQL_DATABASE 或 MYSQL_USER，无法备份" >&2
  exit 1
fi

# 密码走环境变量而非命令行（ps 不可见、无「command line insecure」告警）
export MYSQL_PWD="$MYSQL_PASSWORD_VAL"

command -v mysqldump >/dev/null 2>&1 || {
  echo "错误：mysqldump 不在 PATH 中（本机请先 brew install mysql-client 或 mysql）" >&2
  exit 1
}

# ---------- 落盘目录 ----------
STAMP="$(date +%Y%m%d-%H%M)"
BACKUP_ROOT="$REPO_ROOT/data/backups"
DB_DIR="$BACKUP_ROOT/db"
MEDIA_DIR="$BACKUP_ROOT/media"
mkdir -p "$DB_DIR" "$MEDIA_DIR"

DB_OUT="$DB_DIR/$STAMP.sql.gz"
DB_TMP="$DB_OUT.part"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始数据库备份：host=$MYSQL_HOST_VAL port=$MYSQL_PORT_VAL db=$MYSQL_DATABASE_VAL"

# ---------- 1) mysqldump 全库 → gzip（先写 .part，成功才改名，防半截文件） ----------
# --single-transaction：InnoDB 一致性快照不锁表（架构规范 §6 备份三件套口径）；
# --no-tablespaces：应用账号通常无全局 PROCESS 权限，跳过表空间信息不损内容
mysqldump \
  --host="$MYSQL_HOST_VAL" --port="$MYSQL_PORT_VAL" \
  --user="$MYSQL_USER_VAL" \
  --single-transaction --quick --routines --triggers --no-tablespaces \
  "$MYSQL_DATABASE_VAL" | gzip > "$DB_TMP"

# 校验产物非空才落正式名
if [ ! -s "$DB_TMP" ]; then
  rm -f "$DB_TMP"
  echo "错误：mysqldump 产物为空（检查连接参数与库权限）" >&2
  exit 1
fi
mv "$DB_TMP" "$DB_OUT"
echo "数据库备份完成：${DB_OUT}（$(du -h "${DB_OUT}" | cut -f1)）"

# ---------- 2) data/media 同批归档（缺位如实跳过，不算失败） ----------
MEDIA_OUT="$MEDIA_DIR/$STAMP-media.tar.gz"
if [ -d "$REPO_ROOT/data/media" ]; then
  tar -czf "$MEDIA_OUT" -C "$REPO_ROOT/data" media
  echo "媒体资产归档完成：${MEDIA_OUT}（$(du -h "${MEDIA_OUT}" | cut -f1)）"
else
  echo "跳过媒体归档：$REPO_ROOT/data/media 不存在（尚无媒体落盘资产）"
fi

# ---------- 3) 保留策略：每类只留最新 KEEP 份，超出删最旧 ----------
prune_dir() {
  local dir="$1" pattern="$2" keep="$3"
  [ -d "$dir" ] || return 0
  local files=() f i count
  while IFS= read -r f; do
    [ -n "$f" ] && files+=("$f")
  done < <(ls -t "$dir"/$pattern 2>/dev/null || true)
  count=${#files[@]}
  if [ "$count" -gt "$keep" ]; then
    for ((i = keep; i < count; i++)); do
      echo "保留策略（KEEP=${keep}）：清理过期备份 ${files[$i]}"
      rm -f -- "${files[$i]}"
    done
  fi
}
prune_dir "$DB_DIR" '*.sql.gz' "$KEEP"
prune_dir "$MEDIA_DIR" '*.tar.gz' "$KEEP"

# ---------- 4) 末尾打印最新备份路径（G6 备份新鲜卡取数口径） ----------
LATEST_DB="$(ls -t "$DB_DIR"/*.sql.gz 2>/dev/null | head -n 1 || true)"
LATEST_MEDIA="$(ls -t "$MEDIA_DIR"/*.tar.gz 2>/dev/null | head -n 1 || true)"
echo "最新数据库备份：${LATEST_DB:-（无）}"
echo "最新媒体归档：${LATEST_MEDIA:-（无）}"
