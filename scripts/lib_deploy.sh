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
DB_PORT=3306
ROOT_PW_FILE="$PWD/data/.mysql_root_pw"

# ---------- 0.1 加载 .env（部署配置：MySQL 账号 / AI key 与模型）----------
# 项目不装 python-dotenv；入口脚本在这里 source 一次，Streamlit 子进程随
# nohup 继承。已在 shell 里 export 过的变量优先（set -a 只对未定义生效场景
# 由调用方保证：重复 source 覆盖也无碍，值相同）。
load_env() {
  if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
    echo "[env] 已加载 .env（ZHIPUAI_API_KEY: $([ -n "${ZHIPUAI_API_KEY:-}" ] && echo 已配置 || echo 未配置)）"
  else
    echo "[env] ⚠ 未找到 .env（AI 释义降级为离线兜底）。可执行: cp .env.example .env"
  fi
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
db_up()   { "$MYSQL_BIN/mysqladmin" --protocol=tcp -h 127.0.0.1 -P "$DB_PORT" ping >/dev/null 2>&1; }
app_up()  { lsof -iTCP:"$APP_PORT" -sTCP:LISTEN >/dev/null 2>&1; }

stop_all() {
  [ -f "$DATADIR/mysqld.pid" ] && kill "$(cat "$DATADIR/mysqld.pid")" 2>/dev/null || true
  pkill -f "streamlit run src/app.py" 2>/dev/null || true
  echo "已停止（MySQL 退出稍等数秒）"
}

status_all() {
  db_up && echo "MySQL : 运行中 (127.0.0.1:$DB_PORT)" || echo "MySQL : 未运行"
  app_up && echo "App   : 运行中 (http://localhost:$APP_PORT)" || echo "App   : 未运行"
}

# ---------- root 密码自动探测 ----------
# 探测顺序：缓存 → MYSQL_ROOT_PASSWORD → 免密 → 常见密码清单。
# 结果缓存到 data/.mysql_root_pw（chmod 600，gitignore）。
try_root() {
  local pw="$1"
  if [ -z "$pw" ]; then
    "$MYSQL_BIN/mysql" --protocol=tcp -h 127.0.0.1 -u root \
        -e "SELECT 1" >/dev/null 2>&1
  else
    "$MYSQL_BIN/mysql" --protocol=tcp -h 127.0.0.1 -u root -p"$pw" \
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
    "$MYSQL_BIN/mysql" --protocol=tcp -h 127.0.0.1 -u root < "$1" 2>/dev/null
  else
    "$MYSQL_BIN/mysql" --protocol=tcp -h 127.0.0.1 -u root -p"$root_pw" < "$1" 2>/dev/null
  fi
}

wait_db() {  # 最多等 60s
  for _ in $(seq 1 60); do
    db_up && return 0
    sleep 1
  done
  echo "✗ MySQL 60s 未就绪，看日志: $LOGDIR/mysqld.err"; return 1
}

# ---------- MySQL 启动（含空 datadir 初始化）----------
start_mysqld() {
  if db_up; then
    echo "[mysql] 已在运行"
    return 0
  fi
  mkdir -p "$DATADIR"
  # mysqld 8.0 对空 datadir 不做自动初始化（直接启动会 Failed to find valid
  # data directory 退出）—— 空目录先显式 --initialize-insecure：
  # 生成系统库，root@localhost 空密码（由 root 探测/建库授权接住）
  if [ -z "$(ls -A "$DATADIR" 2>/dev/null)" ]; then
    echo "[mysql] 首次运行：初始化数据目录（--initialize-insecure）..."
    "$MYSQL_BIN/mysqld" \
      --datadir="$DATADIR" \
      --initialize-insecure \
      --log-error="$LOGDIR/mysqld.init.err" \
      >> "$LOGDIR/mysqld.stdout" 2>&1
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
  if "$MYSQL_BIN/mysql" --protocol=tcp -h 127.0.0.1 -u web_word_user -pwebword123 \
       -e "SELECT 1" web_word_db >/dev/null 2>&1; then
    echo "[grant] 数据库账号可用"
    return 0
  fi
  echo "[grant] 首次配置：探测 root 密码并建库授权..."
  if ! probe_root_pw; then
    echo "      ⚠ root 密码探测失败（免密/常见密码都不对）。两种解法："
    echo "        a) 在 .env 里加一行 MYSQL_ROOT_PASSWORD=<密码> 后重跑 develop.sh"
    echo "        b) 手动执行: $MYSQL_BIN/mysql -u root -p < scripts/grant_local_mysql.sql"
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
reassemble_dictionary_db() {
  if [ -f data/dictionary.db ] || ! ls data/dictionary.db.part* >/dev/null 2>&1; then
    return 0
  fi
  echo "[dict] 重组 dictionary.db（197MB 分卷合并，一次性）..."
  cat data/dictionary.db.part* > data/dictionary.db
  if command -v shasum >/dev/null 2>&1; then
    echo "$(cat data/dictionary.db.sha256)" | shasum -a 256 -c - >/dev/null 2>&1 \
      || { echo "      ⚠ sha256 校验失败，重组文件不可信，已删除重试"; rm -f data/dictionary.db; return 1; }
  fi
  echo "      重组完成并校验通过（$(du -h data/dictionary.db | cut -f1)）"
  return 0
}

# ---------- 七步灌库（幂等：--if-empty，已有数据则跳过）----------
run_all_loaders() {
  local n_fail=0
  if MYSQL_HOST=127.0.0.1 python3 scripts/load_word_library.py --if-empty \
       > "$LOGDIR/load_word_library.log" 2>&1; then
    echo "[data 1/7] 词库 + OALD10 义项 + 词间关系 ✓"
  else
    echo "[data 1/7] ⚠ 词库灌入失败（看 $LOGDIR/load_word_library.log）"; n_fail=$((n_fail+1))
  fi

  if MYSQL_HOST=127.0.0.1 python3 scripts/load_corpus_dataset.py --if-empty \
       >> "$LOGDIR/load_corpus.log" 2>&1; then
    echo "[data 2/7] enTenTen21 语料数据集 ✓"
  else
    echo "[data 2/7] ⚠ 语料灌入失败（看 $LOGDIR/load_corpus.log）"; n_fail=$((n_fail+1))
  fi

  if MYSQL_HOST=127.0.0.1 python3 scripts/load_category_study.py --if-empty \
       >> "$LOGDIR/load_category_study.log" 2>&1; then
    echo "[data 3/7] 跑范畴深挖（甄别/编码/聚类/对齐）✓"
  else
    echo "[data 3/7] ⚠ 范畴深挖灌入失败（看 $LOGDIR/load_category_study.log）"; n_fail=$((n_fail+1))
  fi

  if MYSQL_HOST=127.0.0.1 python3 scripts/load_domain_family.py --if-empty \
       >> "$LOGDIR/load_domain_family.log" 2>&1; then
    echo "[data 4/7] 域系初判（352 保留义位）✓"
  else
    echo "[data 4/7] ⚠ 域系初判灌入失败（看 $LOGDIR/load_domain_family.log）"; n_fail=$((n_fail+1))
  fi

  if MYSQL_HOST=127.0.0.1 python3 scripts/update_domain_family_data.py \
       >> "$LOGDIR/load_domain_family.log" 2>&1; then
    echo "[data 5/7] 域系增强（例句全量 + 频次/图式得分）✓"
  else
    echo "[data 5/7] ⚠ 域系增强失败（看 $LOGDIR/load_domain_family.log）"; n_fail=$((n_fail+1))
  fi

  if MYSQL_HOST=127.0.0.1 python3 scripts/load_llm_screening.py --if-empty \
       >> "$LOGDIR/load_llm_screening.log" 2>&1; then
    echo "[data 6/7] LLM 初筛草稿（352 义位）✓"
  else
    echo "[data 6/7] ⚠ LLM 初筛草稿灌入失败（看 $LOGDIR/load_llm_screening.log）"; n_fail=$((n_fail+1))
  fi

  # 《现汉7》：首次需要先解析 mdx 生成 JSON（约 2.5s）
  if [ ! -f data/zh_dict_senses.json ] && [ -d data/ModernChineseDict/mdx ]; then
    echo "[data 7/7] 结构化《现汉7》mdx（首次运行）..."
    python3 scripts/parse_modern_chinese_dict.py \
        >> "$LOGDIR/parse_zh_dict.log" 2>&1 \
      || echo "      ⚠ mdx 解析失败（看 $LOGDIR/parse_zh_dict.log）"
  fi
  if MYSQL_HOST=127.0.0.1 python3 scripts/load_zh_dict.py --if-empty \
       >> "$LOGDIR/load_zh_dict.log" 2>&1; then
    echo "[data 7/7] 《现汉7》词典（70103 词条）✓"
  else
    echo "[data 7/7] ⚠ 《现汉7》灌入失败（看 $LOGDIR/load_zh_dict.log）"; n_fail=$((n_fail+1))
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
  MYSQL_HOST=127.0.0.1 nohup python3 -m streamlit run src/app.py \
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
