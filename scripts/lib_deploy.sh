#!/usr/bin/env bash
# lib_deploy.sh —— develop.sh / start.sh / repair.sh 共享的变量与函数库。
# 本文件不直接执行：由三个入口脚本 source。
# 变量与函数的单一事实来源在这里，避免三个入口各自漂移。

# ---------- 路径与端口 ----------
export WEB_WORD_ROOT="$PWD"
MYSQL_BIN=/opt/homebrew/opt/mysql@8.0/bin
DATADIR="$PWD/data/mysql"
LOGDIR="$PWD/data/logs";  mkdir -p "$LOGDIR"
APP_PORT=8501
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=web_word_db
DB_USER=web_word_user
DB_PASS=webword123
ROOT_PW_FILE="$PWD/data/.mysql_root_pw"

# ---------- 0.1 加载 .env（部署配置：MySQL 账号 / AI key 与模型）----------
# 项目不装 python-dotenv；入口脚本在这里加载一次，Streamlit 子进程随
# nohup 继承。语义（RV8-3）：已在 shell 里 export 过的变量优先 —— 文件值
# 只补缺，不覆盖调用方显式给出的值（下面用子 shell dump + printenv 判定实现）。
# 加载顺序 .env → .env.local，后者覆盖前者对未导出变量的补缺。
load_env() {
  if [ -f .env ]; then
    # 在子 shell 里 source 两个文件并 dump 全部导出变量（export -p 的输出
    # 可被 eval 安全回放，值已按 shell 规则转义），再只把当前 shell 尚未
    # 导出的变量回填进来 —— 实现「已 export 优先」而不污染当前环境。
    local _dump line key
    _dump="$(mktemp)"
    (
      set -a
      # shellcheck disable=SC1091
      source .env
      # .env.local（gitignored）：生产部署的真实凭据覆盖 .env 占位值
      if [ -f .env.local ]; then
        # shellcheck disable=SC1091
        source .env.local
      fi
      export -p
    ) > "$_dump" 2>/dev/null
    while IFS= read -r line; do
      case "$line" in
        declare\ -x\ [A-Za-z_]*=*) line="${line#declare -x }" ;;
        *) continue ;;
      esac
      key="${line%%=*}"
      case "$key" in
        ''|*[!A-Za-z0-9_]*) continue ;;   # 键名合法性防御，跳过怪变量
      esac
      if printenv "$key" >/dev/null 2>&1; then
        continue                          # 已 export：调用方值优先，不覆盖
      fi
      eval "export $line"
    done < "$_dump"
    rm -f "$_dump"
    echo "[env] 已加载 .env（ZHIPUAI_API_KEY: $([ -n "${ZHIPUAI_API_KEY:-}" ] && echo 已配置 || echo 未配置)）"
  else
    echo "[env] ⚠ 未找到 .env（AI 释义降级为离线兜底）。可执行: cp .env.example .env"
    # 无 .env 时给本地裸跑兜底：config.yaml 的 host 是 Docker 服务名 mysql，
    # 不导出本地默认的话，"离线降级可启动"的承诺会变成连 'mysql' 失败的误导报错。
    # AI key 仍为空 → 应用按文档降级；MySQL 用 .env.example 同款本地默认值。
    export MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
    export MYSQL_PORT="${MYSQL_PORT:-3306}"
    export MYSQL_DATABASE="${MYSQL_DATABASE:-web_word_db}"
    export MYSQL_USER="${MYSQL_USER:-web_word_user}"
    export MYSQL_PASSWORD="${MYSQL_PASSWORD:-webword123}"
  fi
  # ---------- 连接参数归一（RV9-11）----------
  # 脚本侧（db_up/授权/灌库/探活）一律用 DB_*，不再散落硬编码 127.0.0.1:3306
  # +webword123 —— 用户改 .env 后脚本管的才是同一套实例。缺省回退现值
  # （与 .env.example 默认一致）。
  DB_HOST="${MYSQL_HOST:-127.0.0.1}"
  DB_PORT="${MYSQL_PORT:-3306}"
  DB_NAME="${MYSQL_DATABASE:-web_word_db}"
  DB_USER="${MYSQL_USER:-web_word_user}"
  DB_PASS="${MYSQL_PASSWORD:-webword123}"
  export DB_HOST DB_PORT DB_NAME DB_USER DB_PASS
}

# ---------- Python 依赖自检 + 自动安装 ----------
# 新机器最常见的故障：依赖没装全（requirements.txt 曾漏 plotly/openpyxl，
# 导致知识图谱与灌库直接崩）。缺了自动补装，装不上才给安装命令。
check_deps() {
  local missing=()
  for mod in streamlit pandas plotly pymysql yaml openpyxl; do
    python3 -c "import $mod" >/dev/null 2>&1 || missing+=("$mod")
  done
  if [ ${#missing[@]} -gt 0 ]; then
    echo "[deps] 缺少 Python 依赖: ${missing[*]}，自动安装（requirements.txt）..."
    if pip3 install -q -r requirements.txt >> "$LOGDIR/pip_install.log" 2>&1; then
      echo "[deps] 依赖安装完成（详见 $LOGDIR/pip_install.log）"
      return 0
    fi
    echo "[deps] ⚠ 自动安装失败，请手动执行: pip3 install -r requirements.txt"
    return 1
  fi
  echo "[deps] Python 依赖自检通过"
  return 0
}

# ---------- MySQL 二进制：自动安装 + 定位 ----------
ensure_mysql_binary() {
  if [ ! -x "$MYSQL_BIN/mysql" ] && [ ! -x "$(command -v mysql 2>/dev/null)" ]; then
    echo "[mysql] 未找到 MySQL，尝试通过 Homebrew 安装 mysql@8.0（一次性，较大）..."
    if command -v brew >/dev/null 2>&1; then
      brew install mysql@8.0 >> "$LOGDIR/brew_mysql.log" 2>&1 \
        && echo "      安装完成" \
        || { echo "      ⚠ brew install 失败（看 $LOGDIR/brew_mysql.log），请手动: brew install mysql@8.0"; return 1; }
    else
      echo "      ⚠ 未找到 Homebrew。请安装 MySQL 8.0 后重跑："
      echo "        macOS:  brew install mysql@8.0（先装 Homebrew）"
      echo "        Linux:  sudo apt install mysql-server（或 docker compose up -d）"
      return 1
    fi
  fi
  # 定位：优先项目约定的 Homebrew 路径，回退 PATH
  if [ ! -x "$MYSQL_BIN/mysql" ]; then
    MYSQL_BIN="$(command -v mysql | xargs dirname | xargs dirname | xargs dirname 2>/dev/null || true)"
  fi
  if [ ! -x "$MYSQL_BIN/mysql" ]; then
    echo "✗ MySQL 不可用（自动安装也失败）。按上方提示安装后重跑"
    return 1
  fi
  return 0
}

# ---------- 服务探活 / 停止 / 状态 ----------
db_up()   { "$MYSQL_BIN/mysqladmin" --protocol=tcp -h "$DB_HOST" -P "$DB_PORT" ping >/dev/null 2>&1; }
app_up()  { lsof -iTCP:"$APP_PORT" -sTCP:LISTEN >/dev/null 2>&1; }

# 应用真健康：/_stcore/health 应答 200。端口被 LISTEN ≠ 本应用在服务
# （RV9-13：status_all 只看端口会把占着 8501 的其他进程报成「运行中」）。
app_healthy() {
  APP_PORT="$APP_PORT" python3 - <<'PY' >/dev/null 2>&1
import os, sys, urllib.request
try:
    r = urllib.request.urlopen(
        f"http://127.0.0.1:{os.environ['APP_PORT']}/_stcore/health", timeout=3)
    sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
}

# ---------- 实例归属防护（RV9-2）----------
# db_up 只能证明「端口有 mysqld 应答」，不能证明那是本项目 data/mysql 拉起的
# 实例 —— 本机原生 mysqld / 其他项目的 MySQL 占着端口时，建库授权与灌库会写进
# 别人的实例。判定口径：本项目实例必带 --datadir=$DATADIR（我们自己拼的启动
# 命令行），按 pid 文件 + 进程 cmdline 匹配；端口被占但不是本项目实例时默认
# 拒绝，ALLOW_EXTERNAL_MYSQL=1 显式放行（故意灌入远程/自管实例的高级用法）。
is_own_mysqld() {
  local pid
  if [ -f "$DATADIR/mysqld.pid" ]; then
    pid="$(cat "$DATADIR/mysqld.pid" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
  fi
  pgrep -f "mysqld.*--datadir=$DATADIR" >/dev/null 2>&1
}

require_own_instance() {
  # 端口没人应答：不存在误写对象，放行（start_mysqld 会拉起自己的实例）
  db_up || return 0
  is_own_mysqld && return 0
  if [ "${ALLOW_EXTERNAL_MYSQL:-0}" = "1" ]; then
    echo "[mysql] ⚠ ALLOW_EXTERNAL_MYSQL=1 —— $DB_HOST:$DB_PORT 是外部实例，"
    echo "        授权/灌库将写入该实例（数据不落在 data/mysql，备份脚本口径同）"
    return 0
  fi
  echo "✗ $DB_HOST:$DB_PORT 上有 MySQL 在应答，但不是本项目 data/mysql 的实例 ——"
  echo "  为避免在外部实例上建库写数据，已拒绝继续。三种处理："
  echo "    a) 停掉该实例后重跑（本项目会拉起自己的 data/mysql）"
  echo "    b) 确要灌入该实例: ALLOW_EXTERNAL_MYSQL=1 ./develop.sh（显式确认）"
  echo "    c) 换端口/主机: 在 .env 设 MYSQL_PORT / MYSQL_HOST 后重跑"
  return 1
}

stop_mysqld() {
  # RV9-3：kill 不等退出 → 紧接着的 start 会把垂死实例当就绪（端口还在应答）。
  # 有界等待退出（TERM 后 mysqld 还要做 redo/缓冲池清理），超时 SIGKILL；
  # pid 文件缺失/失效但本项目 mysqld 还在时按 cmdline 兜底（RV9-4）。
  local pid
  if [ -f "$DATADIR/mysqld.pid" ]; then
    pid="$(cat "$DATADIR/mysqld.pid" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  fi
  # 只匹配带本项目 datadir 的 mysqld —— 不会误伤外部实例
  pkill -f "mysqld.*--datadir=$DATADIR" 2>/dev/null || true
  for _ in $(seq 1 15); do
    pgrep -f "mysqld.*--datadir=$DATADIR" >/dev/null 2>&1 || break
    sleep 1
  done
  if pgrep -f "mysqld.*--datadir=$DATADIR" >/dev/null 2>&1; then
    echo "  ⚠ mysqld TERM 15s 未退出 → SIGKILL"
    pkill -9 -f "mysqld.*--datadir=$DATADIR" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$DATADIR/mysqld.pid"
}

stop_streamlit() {
  pkill -f "streamlit run src/app.py" 2>/dev/null || true
  for _ in $(seq 1 10); do
    pgrep -f "streamlit run src/app.py" >/dev/null 2>&1 || break
    sleep 1
  done
  if pgrep -f "streamlit run src/app.py" >/dev/null 2>&1; then
    pkill -9 -f "streamlit run src/app.py" 2>/dev/null || true
    sleep 1
  fi
}

stop_all() {
  stop_mysqld
  stop_streamlit
  echo "已停止（进程已退出，端口已释放；stop 后立刻 start 也不会撞上垂死实例）"
}

status_all() {
  db_up && echo "MySQL : 运行中 ($DB_HOST:$DB_PORT)" || echo "MySQL : 未运行"
  if app_healthy; then
    echo "App   : 运行中（健康检查通过）(http://localhost:$APP_PORT)"
  elif app_up; then
    echo "App   : ⚠ $APP_PORT 端口被占用，但 /_stcore/health 无应答（可能是其他进程或应用僵死）"
  else
    echo "App   : 未运行"
  fi
}

# ---------- root 密码自动探测 ----------
# 探测顺序：缓存 → MYSQL_ROOT_PASSWORD → 免密 → 常见密码清单。
# 结果缓存到 data/.mysql_root_pw（chmod 600，gitignore）。
try_root() {
  local pw="$1"
  if [ -z "$pw" ]; then
    "$MYSQL_BIN/mysql" --protocol=tcp -h "$DB_HOST" -P "$DB_PORT" -u root \
        -e "SELECT 1" >/dev/null 2>&1
  else
    "$MYSQL_BIN/mysql" --protocol=tcp -h "$DB_HOST" -P "$DB_PORT" -u root -p"$pw" \
        -e "SELECT 1" >/dev/null 2>&1
  fi
}

probe_root_pw() {
  if [ -s "$ROOT_PW_FILE" ] && try_root "$(cat "$ROOT_PW_FILE")"; then
    root_pw="$(cat "$ROOT_PW_FILE")"
    return 0
  fi
  if [ -n "${MYSQL_ROOT_PASSWORD:-}" ] && try_root "$MYSQL_ROOT_PASSWORD"; then
    root_pw="$MYSQL_ROOT_PASSWORD"
    printf '%s' "$root_pw" > "$ROOT_PW_FILE"; chmod 600 "$ROOT_PW_FILE"
    return 0
  fi
  if try_root ""; then
    root_pw=""
    printf '%s' "$root_pw" > "$ROOT_PW_FILE"; chmod 600 "$ROOT_PW_FILE"
    return 0
  fi
  for pw in rootpass123 p root password admin mysql 123456; do
    if try_root "$pw"; then
      root_pw="$pw"
      printf '%s' "$root_pw" > "$ROOT_PW_FILE"; chmod 600 "$ROOT_PW_FILE"
      return 0
    fi
  done
  return 1
}

run_root_sql() {  # run_root_sql <sql 文件>
  if [ -z "$root_pw" ]; then
    "$MYSQL_BIN/mysql" --protocol=tcp -h "$DB_HOST" -P "$DB_PORT" -u root < "$1" 2>/dev/null
  else
    "$MYSQL_BIN/mysql" --protocol=tcp -h "$DB_HOST" -P "$DB_PORT" -u root -p"$root_pw" < "$1" 2>/dev/null
  fi
}

# 真探活：能连接且能执行 SELECT 1（RV9-3：端口通 ≠ 可用 —— 垂死实例、
# 只初始化未就绪的实例同样应答 ping/端口）。凭据阶梯与应用/授权口径一致：
# 应用账号 → root（缓存 → MYSQL_ROOT_PASSWORD → 空密码 → 常见密码清单）。
db_ready() {
  local pw
  if "$MYSQL_BIN/mysql" --protocol=tcp -h "$DB_HOST" -P "$DB_PORT" \
       -u "$DB_USER" -p"$DB_PASS" -e "SELECT 1" >/dev/null 2>&1; then
    return 0
  fi
  for pw in "$(cat "$ROOT_PW_FILE" 2>/dev/null || true)" \
            "${MYSQL_ROOT_PASSWORD:-}" "" \
            rootpass123 p root password admin mysql 123456; do
    if try_root "$pw"; then
      return 0
    fi
  done
  return 1
}

wait_db() {  # 最多等 60s
  for _ in $(seq 1 60); do
    db_ready && return 0
    sleep 1
  done
  echo "✗ MySQL 60s 未就绪（以能 SELECT 1 为准），看日志: $LOGDIR/mysqld.err"
  echo "  若 root 密码已改且应用账号未授权: 在 .env 设 MYSQL_ROOT_PASSWORD 后重跑，"
  echo "  或 ./repair.sh --fix"
  return 1
}

# ---------- MySQL 启动（含空 datadir 初始化）----------
start_mysqld() {
  if db_up; then
    if is_own_mysqld; then
      echo "[mysql] 已在运行（data/mysql 实例）"
      return 0
    fi
    # 探活通过但不是本项目的实例 —— 两种情况：
    # a) 本项目幽灵实例：数据目录被删/清空后（误操作或重装），残留的 mysqld
    #    仍握着已 unlink 的文件应答端口 —— 在它上面灌库必然数据丢失，InnoDB
    #    落盘时直接断言崩溃。cmdline 匹配得到，清掉再正常拉起。
    # b) 外部实例（本机原生 mysqld / 其他项目的 MySQL）：cmdline 匹配不到，
    #    默认拒绝（RV9-2），ALLOW_EXTERNAL_MYSQL=1 显式放行。
    if pgrep -f "mysqld.*--datadir=$DATADIR" >/dev/null 2>&1; then
      echo "[mysql] ⚠ 本项目残留实例在应答但数据目录 $DATADIR 已不是它的 —— 清理..."
      pkill -f "mysqld.*--datadir=$DATADIR" 2>/dev/null || true
      # mysqld 收到 TERM 后还要做 redo/缓冲池清理，大库可能要几秒 ——
      # 单次 sleep 会漏判慢关闭；有界轮询，进程一退出立刻往下走（RV9-3：
      # 以进程退出为准，不再拿「端口还通」判断垂死实例）。
      for _ in $(seq 1 15); do
        pgrep -f "mysqld.*--datadir=$DATADIR" >/dev/null 2>&1 || break
        sleep 1
      done
      if pgrep -f "mysqld.*--datadir=$DATADIR" >/dev/null 2>&1; then
        echo "  ⚠ TERM 15s 未退出 → SIGKILL"
        pkill -9 -f "mysqld.*--datadir=$DATADIR" 2>/dev/null || true
        sleep 1
      fi
      rm -f "$DATADIR/mysqld.pid"
      echo "      已清理，重新初始化..."
    else
      require_own_instance
      return $?
    fi
  fi
  mkdir -p "$DATADIR"
  # mysqld 8.0 对空 datadir 不做自动初始化（直接启动会 Failed to find valid
  # data directory 退出）—— 空目录先显式 --initialize-insecure：
  # 生成系统库，root@localhost 空密码（由 root 探测/建库授权接住）
  if [ -z "$(ls -A "$DATADIR" 2>/dev/null)" ]; then
    echo "[mysql] 首次运行：初始化数据目录（--initialize-insecure）..."
    if ! "$MYSQL_BIN/mysqld" \
          --datadir="$DATADIR" \
          --initialize-insecure \
          --log-error="$LOGDIR/mysqld.init.err" \
          >> "$LOGDIR/mysqld.stdout" 2>&1; then
      # RV9-10：初始化失败不再静默往下走（过去会白等 60s 端口超时，且
      # 指错日志 —— 真正的报错在 mysqld.init.err 而不是 mysqld.err）
      echo "✗ 数据目录初始化失败 —— 真实报错在 $LOGDIR/mysqld.init.err："
      tail -n 5 "$LOGDIR/mysqld.init.err" 2>/dev/null || true
      echo "  处理后重跑 ./develop.sh（或 ./repair.sh --fix）"
      return 1
    fi
    echo "      初始化完成（root 空密码，稍后自动建库授权）"
  fi
  echo "[mysql] 启动（数据目录 data/mysql）..."
  "$MYSQL_BIN/mysqld" \
    --datadir="$DATADIR" \
    --port="$DB_PORT" --bind-address=127.0.0.1 \
    --mysqlx=OFF \
    --log-error="$LOGDIR/mysqld.err" \
    --pid-file="$DATADIR/mysqld.pid" \
    >> "$LOGDIR/mysqld.stdout" 2>&1 &
  wait_db || return 1
  echo "      MySQL 就绪"
}

# ---------- 建库授权（幂等；root 密码自动探测）----------
grant_if_needed() {
  # RV9-2：外部实例防护 —— 端口被外部 MySQL 占着时，授权会写进别人的实例
  require_own_instance || return 1
  if "$MYSQL_BIN/mysql" --protocol=tcp -h "$DB_HOST" -P "$DB_PORT" \
       -u "$DB_USER" -p"$DB_PASS" -e "SELECT 1" "$DB_NAME" >/dev/null 2>&1; then
    echo "[grant] 数据库账号可用"
    return 0
  fi
  echo "[grant] 首次配置：探测 root 密码并建库授权..."
  if ! probe_root_pw; then
    echo "      ⚠ root 密码探测失败（免密/常见密码都不对）。两种解法："
    echo "        a) 在 .env 里加一行 MYSQL_ROOT_PASSWORD=<密码> 后重跑 develop.sh"
    echo "        b) 手动执行: $MYSQL_BIN/mysql -u root -p -h $DB_HOST < scripts/grant_local_mysql.sql"
    return 1
  fi
  if run_root_sql scripts/grant_local_mysql.sql; then
    echo "      授权完成（root 密码已自动探测并缓存到 data/.mysql_root_pw）"
    return 0
  fi
  echo "      ⚠ 授权 SQL 执行失败（root 可连但授权报错），请手动检查："
  echo "        $MYSQL_BIN/mysql -u root -p < scripts/grant_local_mysql.sql"
  return 1
}

# ---------- dictionary.db 分卷重组 ----------
# 197MB 全库词典以 90MB 分卷入库（GitHub 单文件 100MB 上限），
# 首次自动拼接还原并校验 sha256（幂等：完整文件已存在则跳过）。
# RV9-6：失败一律 return 1 带重下指引 —— 调用方不许 || true 吞掉，否则
# 损坏/半截的词典库静默上线，部署完成横幅还照打 ✅。
reassemble_dictionary_db() {
  if [ -f data/dictionary.db ] || ! ls data/dictionary.db.part* >/dev/null 2>&1; then
    return 0
  fi
  echo "[dict] 重组 dictionary.db（197MB 分卷合并，一次性）..."
  if ! cat data/dictionary.db.part* > data/dictionary.db; then
    echo "      ✗ 分卷合并失败（磁盘满或分卷缺失），已删除半截文件"
    rm -f data/dictionary.db
    return 1
  fi
  if command -v shasum >/dev/null 2>&1; then
    if echo "$(cat data/dictionary.db.sha256)" | shasum -a 256 -c - >/dev/null 2>&1; then
      echo "      重组完成并校验通过（$(du -h data/dictionary.db | cut -f1)）"
    else
      echo "      ✗ sha256 校验失败，重组文件不可信，已删除。修复："
      echo "        git checkout HEAD -- 'data/dictionary.db.part*' && ./develop.sh"
      rm -f data/dictionary.db
      return 1
    fi
  else
    # shasum 不在（罕见）：不假装校验过 —— 如实注明，由使用方决定是否继续
    echo "      ⚠ shasum 不可用，跳过 sha256 校验（文件完整性未验证）"
  fi
  return 0
}

# ---------- 行数探测（RV9-1/RV9-9 共用）----------
# 返回 <表> 当前行数；连不上/缺表按 0 处理（由调用方决定语义）
table_rows() {  # table_rows <表名>
  local n
  n="$("$MYSQL_BIN/mysql" --protocol=tcp -h "$DB_HOST" -P "$DB_PORT" \
        -u "$DB_USER" -p"$DB_PASS" -N -e "SELECT COUNT(*) FROM \`$1\`" \
        "$DB_NAME" 2>/dev/null || true)"
  [ -n "$n" ] && echo "$n" || echo 0
}

# 数据已灌探测（RV9-1）：初始化后中断 = 系统表在而基线表全空，零数据上线。
# 以 definitions / word_relations 双基线行数为准（对齐 env_doctor DB_BASELINE）。
check_data_loaded() {
  local n_def n_rel
  n_def="$(table_rows definitions)"
  n_rel="$(table_rows word_relations)"
  if [ "$n_def" -eq 0 ] && [ "$n_rel" -eq 0 ]; then
    echo "⚠ 数据库尚未灌入（definitions 与 word_relations 均 0 行）—— 拒绝零数据上线。"
    echo "    灌库:  ./develop.sh          # 全量灌入（幂等，中断可重跑）"
    echo "    体检:  ./start doctor        # 看哪张表缺数据"
    echo "    修复:  ./repair.sh --fix     # 自动修复低基线表"
    return 1
  fi
  return 0
}

# ---------- 八步灌库（幂等：--if-empty，已有数据则跳过）----------
# RV9-9：--if-empty 只灌全空表 —— 部分灌入（中断残留）的表会被静默跳过且缺口
# 永远补不上。灌库前先对关键基线表预检：全空正常灌 / 达标跳过 / 部分灌入如实
# 报告并给 --force-reload 指引。--force-reload = 不带 --if-empty 重跑各 loader
# （各 loader 无 --if-empty 时走自身文档化的「强制重灌」路径：先清后灌）。
run_all_loaders() {
  # RV9-2：repair.sh 的 db_up→灌库路径不经 start_mysqld 的归属防护，这里兜住
  require_own_instance || return 1
  local n_fail=0 flag_empty="--if-empty" table n baseline
  [ "${1:-}" = "--force-reload" ] && flag_empty=""

  # 部分灌入预检（RV9-9）：表 → 期望最小行数（与 scripts/env_doctor.py DB_BASELINE 对齐）
  if [ -z "$flag_empty" ]; then
    echo "[data] --force-reload：各 loader 不带 --if-empty 全量重灌（先清后灌，耗时较长）"
  else
    for table in definitions corpus_word_stats cs_sense_features domain_family_senses zh_dict_entries; do
      case "$table" in
        definitions) baseline=171 ;;
        corpus_word_stats) baseline=171 ;;
        cs_sense_features) baseline=918 ;;
        domain_family_senses) baseline=352 ;;
        zh_dict_entries) baseline=70103 ;;
      esac
      n="$(table_rows "$table")"
      if [ "$n" -gt 0 ] && [ "$n" -lt "$baseline" ]; then
        # 注：变量紧贴全角标点必须加花括号 —— bash 会把全角字符字节并入
        # 变量名（set -u 下直接报 unbound，无 -u 时静默展开为空）
        echo "[data] ⚠ ${table} 部分灌入（${n} < 基线 ${baseline}）—— --if-empty 会跳过，缺口不会被补。"
        echo "       如需强制重灌: ./repair.sh --fix --force-reload（各 loader 先清后灌）"
      fi
    done
  fi

  if MYSQL_HOST="$DB_HOST" MYSQL_PORT="$DB_PORT" \
       python3 scripts/load_word_library.py $flag_empty \
       > "$LOGDIR/load_word_library.log" 2>&1; then
    echo "[data 1/8] 词库 + OALD10 义项 + 词间关系 ✓"
  else
    echo "[data 1/8] ⚠ 词库灌入失败（看 $LOGDIR/load_word_library.log）"; n_fail=$((n_fail+1))
  fi

  # 人工补充义位 4 条（scutter/kayak/oar/dodder，OALD10 未收录）：研究词表
  # 996 = 992 OALD + 4 补充，缺了它们标注平台会漏行。脚本自身幂等。
  if MYSQL_HOST="$DB_HOST" MYSQL_PORT="$DB_PORT" \
       python3 scripts/load_supplemented_senses.py \
       >> "$LOGDIR/load_supplemented.log" 2>&1; then
    echo "[data 2/8] 人工补充义位（4 条）✓"
  else
    echo "[data 2/8] ⚠ 人工补充义位灌入失败（看 $LOGDIR/load_supplemented.log）"; n_fail=$((n_fail+1))
  fi

  if MYSQL_HOST="$DB_HOST" MYSQL_PORT="$DB_PORT" \
       python3 scripts/load_corpus_dataset.py $flag_empty \
       >> "$LOGDIR/load_corpus.log" 2>&1; then
    echo "[data 3/8] enTenTen21 语料数据集 ✓"
  else
    echo "[data 3/8] ⚠ 语料灌入失败（看 $LOGDIR/load_corpus.log）"; n_fail=$((n_fail+1))
  fi

  if MYSQL_HOST="$DB_HOST" MYSQL_PORT="$DB_PORT" \
       python3 scripts/load_category_study.py $flag_empty \
       >> "$LOGDIR/load_category_study.log" 2>&1; then
    echo "[data 4/8] 跑范畴深挖（甄别/编码/聚类/对齐）✓"
  else
    echo "[data 4/8] ⚠ 范畴深挖灌入失败（看 $LOGDIR/load_category_study.log）"; n_fail=$((n_fail+1))
  fi

  if MYSQL_HOST="$DB_HOST" MYSQL_PORT="$DB_PORT" \
       python3 scripts/load_domain_family.py $flag_empty \
       >> "$LOGDIR/load_domain_family.log" 2>&1; then
    echo "[data 5/8] 域系初判（352 保留义位）✓"
  else
    echo "[data 5/8] ⚠ 域系初判灌入失败（看 $LOGDIR/load_domain_family.log）"; n_fail=$((n_fail+1))
  fi

  if MYSQL_HOST="$DB_HOST" MYSQL_PORT="$DB_PORT" \
       python3 scripts/update_domain_family_data.py \
       >> "$LOGDIR/load_domain_family.log" 2>&1; then
    echo "[data 6/8] 域系增强（例句全量 + 频次/图式得分）✓"
  else
    echo "[data 6/8] ⚠ 域系增强失败（看 $LOGDIR/load_domain_family.log）"; n_fail=$((n_fail+1))
  fi

  if MYSQL_HOST="$DB_HOST" MYSQL_PORT="$DB_PORT" \
       python3 scripts/load_llm_screening.py $flag_empty \
       >> "$LOGDIR/load_llm_screening.log" 2>&1; then
    echo "[data 7/8] LLM 初筛草稿（352 义位）✓"
  else
    echo "[data 7/8] ⚠ LLM 初筛草稿灌入失败（看 $LOGDIR/load_llm_screening.log）"; n_fail=$((n_fail+1))
  fi

  # 《现汉7》：首次需要先解析 mdx 生成 JSON（约 2.5s）
  if [ ! -f data/zh_dict_senses.json ] && [ -d data/ModernChineseDict/mdx ]; then
    echo "[data 8/8] 结构化《现汉7》mdx（首次运行）..."
    python3 scripts/parse_modern_chinese_dict.py \
        >> "$LOGDIR/parse_zh_dict.log" 2>&1 \
      || echo "      ⚠ mdx 解析失败（看 $LOGDIR/parse_zh_dict.log）"
  fi
  if MYSQL_HOST="$DB_HOST" MYSQL_PORT="$DB_PORT" \
       python3 scripts/load_zh_dict.py $flag_empty \
       >> "$LOGDIR/load_zh_dict.log" 2>&1; then
    echo "[data 8/8] 《现汉7》词典（70103 词条）✓"
  else
    echo "[data 8/8] ⚠ 《现汉7》灌入失败（看 $LOGDIR/load_zh_dict.log）"; n_fail=$((n_fail+1))
  fi
  return $n_fail  # 0=全部成功（bash 惯例）
}

# ---------- Streamlit ----------
start_streamlit() {
  if app_up; then
    echo "[app] 应用已在运行 → http://localhost:$APP_PORT"
    return 0
  fi
  echo "[app] 启动 Streamlit ..."
  # RV8-4：不再硬编码 MYSQL_HOST=127.0.0.1（会静默覆盖 .env 的远程库配置）
  # —— load_env 已归一 DB_*，仅未设置时才缺省 127.0.0.1。
  MYSQL_HOST="$DB_HOST" MYSQL_PORT="$DB_PORT" \
    nohup python3 -m streamlit run src/app.py \
    --server.port "$APP_PORT" --server.headless true \
    > "$LOGDIR/streamlit.log" 2>&1 &
  for _ in $(seq 1 30); do
    app_up && break; sleep 1
  done
  if app_up; then
    echo "[app] 应用就绪 → http://localhost:$APP_PORT"
    open "http://localhost:$APP_PORT" 2>/dev/null || true
    return 0
  fi
  echo "✗ 应用 30s 未就绪，看 $LOGDIR/streamlit.log"
  return 1
}
