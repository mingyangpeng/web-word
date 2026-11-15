#!/usr/bin/env bash
#
# status.sh —— 项目状态一览（只读，不改任何东西）。
#
# 输出：容器状态（compose ps）＋ web 健康端点 ＋ MySQL 容器健康 ＋
# 数据卷占用。861 端口/8502 直跑实例不在职责内（README 口径）。
#
# 用法：bash scripts/ops/status.sh

set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/_common.sh"

cd "$OPS_ROOT"

say_info "容器状态"
docker compose ps

say_info "web 健康端点（8501）"
body="$(curl -s -m 3 http://localhost:8501/_stcore/health 2>/dev/null || true)"
if [ "$body" = "ok" ]; then
    say_ok "http://localhost:8501 —— ok"
else
    say_warn "8501 无响应（body=${body:-空}）—— 未启动或正在预热（启动后预热约需数十秒）"
fi

say_info "MySQL 容器健康"
if docker compose ps mysql 2>/dev/null | grep -q healthy; then
    say_ok "mysql 容器 healthy"
else
    say_warn "mysql 容器非 healthy（或未启动）"
fi

say_info "数据卷占用"
docker system df 2>/dev/null | head -5 || say_warn "docker system df 不可用"

# 部署快照龄期（批次 51：manifest 无消费者的缺口——陈旧化可见性）
say_info "部署快照（data/deploy-snapshot/）"
snap="$OPS_ROOT/data/deploy-snapshot/web_word_db.sql.gz"
if [ -f "$snap" ]; then
    gen="$(grep -E '^generated=' "$OPS_ROOT/data/deploy-snapshot/manifest.txt" 2>/dev/null | cut -d= -f2-)"
    days=$(( ( $(date +%s) - $(stat -f %m "$snap" 2>/dev/null || stat -c %Y "$snap" 2>/dev/null || echo 0) ) / 86400 ))
    if [ "$days" -ge 14 ]; then
        say_warn "部署快照已 ${days} 天未更新（generated=${gen:-?}）——业务数据变化后请 ./start snapshot 刷新"
    else
        say_ok "部署快照龄期 ${days} 天（generated=${gen:-?}）"
    fi
else
    say_info "无部署快照（新机部署走 entrypoint 种子链）——./start snapshot 可固化当前库"
fi

# 批次 36 数据库归一后的拓扑自检（防再犯：谁占 3306/谁的库里有多少表）
# 口径：3306=容器 MySQL 业务库（61 表）；3307=宿主 mysqld 仅 pytest 用。
say_info "数据库拓扑自检（批次 36 归一口径）"
p3306="$(lsof -nP -iTCP:3306 -sTCP:LISTEN 2>/dev/null | tail -1 | awk '{print $1}')"
if [ -z "$p3306" ]; then
    say_warn "3306 无监听（mysql 容器未起）—— ./start 会自动拉起"
elif echo "$p3306" | grep -qi "dock"; then
    say_ok "3306 = 容器 MySQL（业务库，正确）"
else
    say_err "3306 被 '$p3306' 占用（应为容器！）—— 宿主 mysqld 抢了业务端口，先停它再 docker compose up -d mysql"
fi
# docker exec 引号层级（R9 终审对齐 restore/backup/snapshot 同口径）：宿主单
# 引号包裹整条 sh -c（$ 不被宿主展开），容器内 sh 展开 MYSQL_ROOT_PASSWORD；
# 口令经 MYSQL_PWD 环境变量传入而非 -p 命令行形态——容器内 ps 不可见、
# 口令含特殊字符也不经 shell 二次解析。
n3306="$(docker exec web-word-mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=\"web_word_db\""' 2>/dev/null || echo "?")"
if [ "$n3306" = "61" ]; then
    say_ok "容器 web_word_db = 61 表（归一后完整库）"
else
    say_warn "容器 web_word_db = ${n3306} 表（预期 61——若显著偏少请对账 data/backups/db/ 的归一前备份）"
fi
p3307="$(lsof -nP -iTCP:3307 -sTCP:LISTEN 2>/dev/null | tail -1 | awk '{print $1}')"
if [ -n "$p3307" ]; then
    say_ok "3307 = ${p3307}（宿主 mysqld，仅 pytest 用——测试库双轨口径）"
else
    say_info "3307 无监听（宿主 mysqld 未起——跑 pytest 前需拉起，命令见 tests/conftest.py docstring）"
fi
