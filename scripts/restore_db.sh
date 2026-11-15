#!/usr/bin/env bash
#
# restore_db.sh —— 灾备恢复（backup_db.sh 的另一半环：备份 → 恢复闭环；
# 架构规范 §6 备份三件套 / §15 数据出入口纪律——恢复仅限灾备场景，由平台
# 管理员执行）。
#
# ⚠️⚠️⚠️ 恢复前必读 ⚠️⚠️⚠️
#   恢复会把目标库整库覆盖（dump 自带 DROP TABLE + CREATE TABLE，恢复本身
#   不可撤销）。动手前先执行 `./start backup` 留一份当前状态的备份——万一
#   恢复失败或误恢复，才有回滚锚点。
#
# 做什么（一次运行 = 一次恢复）：
#   1. 参数校验：备份文件存在、.gz 后缀、gzip -t 完整性预检（防半截文件）；
#   2. 目标库选择：默认 .env.local（优先）→ .env 的 MYSQL_DATABASE
#      （web_word_db），可 --database 指定沙箱库（恢复演练用，不碰业务库）；
#   3. 连接口径：容器内导入——docker exec -i web-word-mysql 经
#      sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot'，root 口令取容器
#      环境变量且经 MYSQL_PWD 传入（不上命令行——ps 不可见、无 insecure 告警），
#      不经宿主命令行——容器内导入不依赖宿主 mysql 客户端（与
#      backup_db.sh 宿主 mysqldump 口径互补：那边靠 127.0.0.1 容器映射）；
#   4. 安全闸：目标库非空且未加 --force 时——交互终端要求键入 yes 确认
#      覆盖；非交互终端（cron/管道）直接拒绝，防无人值守静默覆盖；覆盖的
#      若是业务库且 web 应用容器在跑，提示选维护窗口（恢复期应用会撞瞬时
#      表缺失）；
#   5. 建库：CREATE DATABASE IF NOT EXISTS（utf8mb4 / utf8mb4_unicode_ci，
#      与 compose 服务端字符集口径一致）→ gunzip 管道导入；
#   6. 61 表锚点校验：information_schema 计数，≠61 告警（0 表判失败；
#      计数查询本身失败也判失败，退出码 1）；
#   7. 打印恢复摘要。
#
# 用法：
#   ./start restore <备份文件.sql.gz>                  # 恢复业务库（带安全闸）
#   ./start restore <备份文件.sql.gz> --force          # 跳过交互确认（自动化）
#   ./start restore <备份文件.sql.gz> --database <库>  # 恢复进沙箱库（演练）
#   bash scripts/restore_db.sh <备份文件.sql.gz>       # 等价直调（不经 ./start）
#   bash scripts/restore_db.sh -h                     # 本帮助
#
# 退出码：0 成功；1 目标态不安全/文件或容器异常/导入失败；2 参数错误。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 复用 ops 公共库的 say_ok/say_warn/say_err/say_info（符号/颜色/非 TTY 口径与 ./start 一致）
. "$REPO_ROOT/scripts/ops/_common.sh"

ENV_FILE="$REPO_ROOT/.env"
ENV_LOCAL="$REPO_ROOT/.env.local"

EXPECTED_TABLES=61   # 业务库归一锚点（与 ./start 第⑦步同口径）

usage() {
  # 打印文件头注释块（第 2 行起连续 # 行）——头部增删行无需同步行号
  awk 'NR==1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"
  exit 0
}

# ---------- 参数解析：<file> ＋ --force / --database / --container ----------
DUMP_FILE=""
TARGET_DB=""
CONTAINER="web-word-mysql"
FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --force)       FORCE=1; shift ;;
    --database)    [ $# -ge 2 ] || { echo "错误：--database 需要一个库名参数" >&2; exit 2; }
                   TARGET_DB="$2"; shift 2 ;;
    --database=*)  TARGET_DB="${1#*=}"; shift ;;
    --container)   [ $# -ge 2 ] || { echo "错误：--container 需要一个容器名参数" >&2; exit 2; }
                   CONTAINER="$2"; shift 2 ;;
    --container=*) CONTAINER="${1#*=}"; shift ;;
    -h|--help)     usage ;;
    --*)           echo "错误：未知参数 ${1}（可用：--force / --database <库> / --container <容器名>）" >&2; exit 2 ;;
    *)
      # 第一个非选项参数即备份文件；只接受一个
      [ -z "$DUMP_FILE" ] || { echo "错误：只接受一个备份文件，多给了 $1" >&2; exit 2; }
      DUMP_FILE="$1"; shift ;;
  esac
done
[ -n "$DUMP_FILE" ] || { echo "错误：缺少备份文件参数（用法：./start restore <备份文件.sql.gz>，详见 -h）" >&2; exit 2; }

# 选项注入闸（R4 扫描加固）：相对路径以 - 开头（如 -f.gz、--help.gz）会被
# 下游 gzip -t / gunzip -c / du / shasum 当成自己的选项解析而非文件名——
# 统一补 ./ 前缀归一成路径（绝对路径与普通相对路径不受影响）。含空格/特殊
# 字符的路径在全部消费点均已双引号包裹，无需改写。
case "$DUMP_FILE" in
  -*) DUMP_FILE="./$DUMP_FILE" ;;
esac

# ---------- 目标库默认值：.env.local（优先）→ .env 的 MYSQL_DATABASE ----------
env_value() {
  # 取 KEY=VALUE 的 VALUE：依次查 .env.local → .env（与 backup_db.sh 同口径）；
  # 去行内注释、首尾空白与成对引号；两处都没有则输出空串
  local f line
  for f in "$ENV_LOCAL" "$ENV_FILE"; do
    [ -f "$f" ] || continue
    line="$(grep -E "^$1=" "$f" | tail -n 1 | cut -d= -f2- || true)"
    line="${line%%#*}"
    line="$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
      -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/")"
    if [ -n "$line" ]; then
      printf '%s' "$line"
      return 0
    fi
  done
  printf ''
}
[ -n "$TARGET_DB" ] || TARGET_DB="$(env_value MYSQL_DATABASE)"
[ -n "$TARGET_DB" ] || TARGET_DB="web_word_db"

# 业务库判定：目标库 == 默认业务库（.env(.local) 的 MYSQL_DATABASE，兜底
# web_word_db）即视为业务库——不管用户是默认走到的还是 --database 显式指的。
# 供维护窗口提示用（沙箱演练库不打扰）。
BUSINESS_DB="$(env_value MYSQL_DATABASE)"
[ -n "$BUSINESS_DB" ] || BUSINESS_DB="web_word_db"
IS_BUSINESS_DB=0
if [ "$TARGET_DB" = "$BUSINESS_DB" ]; then
  IS_BUSINESS_DB=1
fi

# 库名/容器名白名单（进 SQL 语句，防注入防怪字符）：字母数字下划线 / 容器名再放宽 .-
case "$TARGET_DB" in
  ''|*[!A-Za-z0-9_]*) say_err "目标库名不合法：${TARGET_DB}（只允许字母数字下划线）"; exit 2 ;;
esac
case "$CONTAINER" in
  ''|*[!A-Za-z0-9_.-]*) say_err "容器名不合法：$CONTAINER"; exit 2 ;;
esac

# ---------- 1) 参数校验：文件存在 ＋ .gz ＋ gzip 完整性 ----------
say_info "① 校验备份文件：$DUMP_FILE"
if [ ! -f "$DUMP_FILE" ] || [ ! -r "$DUMP_FILE" ]; then
  say_err "备份文件不存在或不可读：${DUMP_FILE}（备份产物目录：data/backups/db/）"
  exit 1
fi
case "$DUMP_FILE" in
  *.gz|*.GZ) : ;;
  *) say_err "不是 .gz 备份文件：${DUMP_FILE}（backup_db.sh 产物为 *.sql.gz）"; exit 1 ;;
esac
if ! gzip -t "$DUMP_FILE"; then
  say_err "gzip 完整性校验失败——文件损坏或被截断，换一份备份"
  exit 1
fi
say_ok "文件在位且 gzip 完整（$(du -h "$DUMP_FILE" | cut -f1)）"

# ---------- 2) 容器与 mysql 可达性（容器内导入口径） ----------
say_info "② 检查目标容器：$CONTAINER"
if ! command -v docker >/dev/null 2>&1; then
  say_err "未找到 docker CLI——请先安装/启动 Docker"
  exit 1
fi
if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)" != "true" ]; then
  say_err "容器 $CONTAINER 未在运行——先 ./start 拉起（恢复走容器内 mysql，不依赖宿主客户端）"
  exit 1
fi
say_ok "容器运行中"

# 容器内 mysql：root 口令取容器环境变量 MYSQL_ROOT_PASSWORD，经 MYSQL_PWD
# 传给容器内 mysql（与 backup_db.sh 同理由：不上命令行——ps 不可见、且避开
# 「Using a password on the command line」告警刷屏）
mysql_exec() {
  docker exec -i "$CONTAINER" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$@"' _ "$@"
}

# ---------- 3) 安全闸：恢复会覆盖现有库——非空库默认拒绝/要求确认 ----------
say_info "③ 安全闸检查：目标库 $TARGET_DB 现状"
if ! n_before="$(mysql_exec -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${TARGET_DB}'")"; then
  say_err "查询目标库 $TARGET_DB 现状失败（mysql 连接异常）——中止，未做任何改动"
  exit 1
fi
# 覆盖非空业务库且 web 应用容器在跑：dump 自带 DROP TABLE，恢复期间应用会
# 撞「表不存在」的瞬时错误——提醒选维护窗口。告警不阻断：灾备恢复多为紧急
# 场景，是否先 ./start stop 由管理员按当时情况权衡。
if [ "${n_before:-0}" -gt 0 ] && [ "$IS_BUSINESS_DB" -eq 1 ] && \
   [ "$(docker inspect -f '{{.State.Running}}' web-word-app 2>/dev/null || true)" = "true" ]; then
  say_warn "建议维护窗口（./start stop）——恢复期间应用会出现瞬时表缺失"
fi
if [ "${n_before:-0}" -gt 0 ] && [ "$FORCE" -ne 1 ]; then
  say_warn "目标库 $TARGET_DB 已存在且有 $n_before 张表——恢复将整库覆盖（不可撤销）！"
  if [ -t 0 ]; then
    # 交互终端：键入 yes 才放行（其他任意输入取消）
    read -r -p "   确认覆盖请键入 yes（其他任意输入取消）：" confirm
    if [ "$confirm" != "yes" ]; then
      say_err "已取消——未做任何改动"
      exit 1
    fi
    say_ok "已人工确认覆盖"
  else
    # 非交互终端（cron/管道）：无人值守时静默覆盖太危险，直接拒绝
    say_err "当前非交互终端（stdin 非 TTY）——拒绝覆盖非空库。确属灾备且已确认请加 --force；只想演练请 --database <沙箱库>"
    exit 1
  fi
fi
if [ "$FORCE" -eq 1 ] && [ "${n_before:-0}" -gt 0 ]; then
  say_warn "已按 --force 跳过覆盖确认（目标库现有 $n_before 张表将被覆盖）"
fi

# ---------- 4) 建库（如不存在）＋ 导入 ----------
say_info "④ 建库（如不存在）：${TARGET_DB}（utf8mb4 / utf8mb4_unicode_ci，与 compose 服务端字符集口径一致）"
mysql_exec -e "CREATE DATABASE IF NOT EXISTS \`${TARGET_DB}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"

say_info "⑤ 导入 dump（gunzip -c | mysql 容器内导入，大库请耐心等待）……"
SECONDS=0
# pipefail 口径：gunzip 或 mysql 任一失败都会让本脚本非零退出（防半截导入被当成功）
gunzip -c "$DUMP_FILE" | mysql_exec "$TARGET_DB"
say_ok "导入完成（耗时 ${SECONDS}s）"

# ---------- 5) 61 表锚点校验 ----------
say_info "⑥ 锚点校验：${TARGET_DB} 表数量（预期 ${EXPECTED_TABLES}）"
# manifest 一致性比对（快照侧 sha256——dump/manifest 非原子生成的错位检出）
SNAP_MANIFEST="${DUMP_FILE%/*}/manifest.txt"
if [ -f "$SNAP_MANIFEST" ]; then
    expect_sha="$(grep -E "^sha256=" "$SNAP_MANIFEST" | cut -d= -f2-)"
    actual_sha="$(shasum -a 256 "$DUMP_FILE" | awk '{print $1}')"
    if [ -n "$expect_sha" ] && [ "$expect_sha" != "$actual_sha" ]; then
        say_warn "快照 sha256 与 manifest 不一致——dump 与 manifest 可能错位（部分恢复风险）；建议重新 ./start snapshot"
    fi
fi
# 计数查询本身也可能失败（连接闪断/容器恰在重启）——不能放任空/非数字的
# n_tables 混进下面的 -eq 算术比较（那会把「校验失败」伪装成 test 语法报错
# 崩溃）。显式 if ! 接管：按头部退出码契约判导入失败（1），给人工核对指引。
if ! n_tables="$(mysql_exec -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${TARGET_DB}'")"; then
  say_err "锚点计数查询失败（mysql 连接异常）——导入已执行但无法确认结果；请人工进容器核对 ${TARGET_DB} 表数量后再决定重跑或回滚（恢复前留的 ./start backup 即回滚锚点）"
  exit 1
fi
# 计数结果健壮性（R9 终审）：连接闪断/异常客户端可能给出空串或非数字——
# 直接进下面 -eq 算术比较会把「校验失败」伪装成 test 语法错（bash 退出码 2，
# 违反头注 0/1/2 契约）。先验数字形态，非数字按导入失败判（退出码 1）。
case "$n_tables" in
  ''|*[!0-9]*) say_err "锚点计数结果异常（非数字：${n_tables}）——导入已执行但无法确认结果；请人工进容器核对 ${TARGET_DB} 表数量后再决定重跑或回滚"; exit 1 ;;
esac
if [ "$n_tables" -eq "$EXPECTED_TABLES" ]; then
  anchor="✓ 命中归一锚点（$n_tables/$EXPECTED_TABLES 表，完整）"
elif [ "$n_tables" -eq 0 ]; then
  say_err "导入后 0 张表——dump 为空或不含建表语句，恢复失败"
  exit 1
else
  # ≠61：告警不阻断（沙箱演练/单库子集恢复属正常；业务库恢复到该数请核对 dump 来源）
  anchor="⚠ ≠$EXPECTED_TABLES 锚点，告警（$n_tables 表——沙箱演练正常；业务库恢复请核对 dump 来源与完整性）"
fi

# ---------- 6) 恢复摘要 ----------
echo
echo "════════════════ 恢复摘要 ════════════════"
echo "  备份文件：$DUMP_FILE"
echo "  目标库　：${TARGET_DB}（容器 ${CONTAINER} 内导入）"
echo "  耗时　　：${SECONDS}s"
echo "  表数量　：$n_tables —— $anchor"
echo "  提醒　　：媒体归档如需恢复，手工 tar -xzf data/backups/media/<批次>-media.tar.gz -C data/"
echo "  提醒　　：恢复结果异常时，用恢复前 ./start backup 留的那份备份再走一遍本脚本回滚"
echo "══════════════════════════════════════════"
