"""R9 部署 shell 终审 ＋ 前轮移交清单修复 —— review 收敛测试（批次 53 续）。

两大面（与本轮修复一一对应；全部零真库依赖——静态哨兵扫描 ＋ monkeypatch
隔离面 ＋ AppTest 真渲染，任何环境可跑）：

A. R9 shell 终审（scripts 五脚本 ＋ ops/_common.sh ＋ ops/status.sh）：
  * set -euo pipefail 完整性：restore/backup 原有；snapshot 补 -e、entrypoint
    补 -u/-o pipefail（两脚本容错分支均为显式 || echo / if !，与 -e 交互
    安全）；_common.sh 是被 source 的公共库——不自带 set（继承调用方
    flags），哨兵防误加裸 set -e 坑 sourced 场景；
  * 临时文件卫生：snapshot 的 mktemp 产物 trap EXIT 兜底清理（唯一豁免：
    gzip -t 失败 KEEP_RAW=1 显式保留原始 SQL 供排查）；backup 的 .part 半截
    产物 trap EXIT 清理（set -e 下 mysqldump 中途失败立即退出，无 trap 会
    在 backups 目录永久残留不匹配 *.sql.gz 的垃圾）；
  * docker exec 引号层级：宿主单引号包整条 sh -c（$ 不被宿主展开、容器内
    sh 展开 MYSQL_ROOT_PASSWORD），三处（restore/snapshot/status）同口径；
    status.sh 的 mysql 调用对齐 MYSQL_PWD 环境变量口径——原
    -p"$MYSQL_ROOT_PASSWORD" 命令行口令容器内 ps 可见、特殊字符经 shell
    二次解析（restore/snapshot/backup 早已是 MYSQL_PWD 口径）；
  * 退出码契约：restore 头注承诺 0/1/2——锚点计数结果非数字（连接闪断/
    异常客户端）原会掉进 test 语法错（bash 退出码 2）伪装成「参数错误」，
    补数字形态预检按导入失败判（1）；say_err 全部配对 exit 1/2；
  * 全角相邻变量：六文件无 $VAR（ 未加花括号形态（${1}（ 已归一——全角
    相邻坑本项目三次踩的回归哨兵）；
  * 幂等性：entrypoint 灌库链 run_loader 统一追加 --if-empty（已知 ✓ 本轮
    核实钉住），直调三面（update_domain_family / load_llm_screening /
    parse_modern_chinese_dict）各自容错或幂等。

B. 移交清单修复（前两轮 review，全部 dict_admin_pages 词表核定页）：
  * P2 二次闸：vocab_add_btn/vocab_del_btn/vocab_rebuild_btn 调用点首行
    guards.require_dict_admin()（try/except PermissionError 口径，同页媒体/
    出版/成员 tab 写路径同口径）；R7 现状哨兵
    test_vocab_tab_write_ops_lack_api_gate_pinned_gap 已翻转断言闸在位；
  * P2 增词上限：text_area 解析后 >200 warning 停写（防误粘贴整段文本把
    受控词表撑爆），≤200 走原解析-去重-写回逻辑；
  * P3 note→detail：质检状态区读 _item 契约键 detail（src/style_check._item
    单一契约 code/rule/status/detail，无 'note' 键——旧读法恒取空串，状态
    字样后详情永远缺失）；scripts/build_defining_vocab.py 同型读法 R7/R8
    轮已修，本轮补运行时断言证明 detail 真到输出；
  * P3 词表并发乐观锁：_vocab_write_words(expect_mtime=基线) 写盘前经
    _vocab_file_mtime() 重取 mtime 比对——不一致抛 ValueError 拒写（两编者
    并发增删、后写覆盖先写的「读-改-写丢更新」面收口）；页面调用点捕获后
    ui_kit.flash ＋ st.rerun（RV12-2 口径）；缺省哨兵不启用比对（旧两参
    直调形态兼容）；R8 哨兵 test_page_layer_lost_update_is_p3_handoff 已翻转；
  * P3 1MB 闸：_vocab_read_words 先 stat 预检再整读（对齐
    src/style_check._read_vocab_file 的 RV19-4 加固形态——旧实现 read_text
    之后才查长度，巨文件先被整读进内存才被拒），stat 后变大的竞态由读后
    len 复查兜底；超限抛 ValueError——页面停渲染写操作面，防「空表＋新词」
    整表覆写丢数据。
"""

import importlib.util
import inspect
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# 时序契约（tests/conftest.py 头注）：conftest 已先于本文件设定 env 并
# import tests.helpers 固定 src.* 加载时序；这里再 import 命中 sys.modules 缓存。
from tests import helpers  # noqa: F401
from tests.helpers import _goto, _new_at

import src.dict_admin_pages as dap  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"

# R9 终审覆盖面：五脚本 ＋ ops 公共库 ＋ ops/status（相对 scripts/ 的路径）
SHELL_FILES = [
    "restore_db.sh", "snapshot_db.sh", "backup_db.sh", "entrypoint.sh",
    "ops/_common.sh", "ops/status.sh",
]

# fx23 口径的 admin 登录 mock（纯会话计算不触库；guards.require_dict_admin
# 从会话读 user 后 effective_six_roles 放行——API 级二次闸在 AppTest 里可达）
_ADMIN_SESSION = {
    "id": 1, "username": "admin", "display_name": "管理员",
    "role": "admin", "roles": ["dict_admin", "sys_admin"],
}
# 词表种子（fixture 预写 tmp 词表文件）
_SEED_WORDS = ["move", "come"]


def _shell_text(rel: str) -> str:
    return (SCRIPTS / rel).read_text(encoding="utf-8")


# ============================================
# A1. set -euo pipefail 完整性
# ============================================

class TestR9ShellSetFlags:
    def test_bash_n_syntax_ok(self):
        """bash -n 六文件全绿（终审基线：语法先行）。"""
        for rel in SHELL_FILES:
            proc = subprocess.run(["bash", "-n", str(SCRIPTS / rel)],
                                  capture_output=True, text=True)
            assert proc.returncode == 0, f"{rel} 语法错: {proc.stderr}"

    def test_five_scripts_and_status_have_set_euo_pipefail(self):
        """五脚本（restore/snapshot/backup/entrypoint）＋ ops/status 全部
        set -euo pipefail（R9 补齐：snapshot 缺 -e、entrypoint 缺 -u 与
        -o pipefail）。"""
        for rel in ("restore_db.sh", "snapshot_db.sh", "backup_db.sh",
                    "entrypoint.sh", "ops/status.sh"):
            assert "set -euo pipefail" in _shell_text(rel), \
                f"{rel} 缺 set -euo pipefail"

    def test_common_sh_is_set_free_library(self):
        """_common.sh 是被 source 的公共库——**不自带 set**（flags 由调用方
        脚本决定：全消费方 start/stop/down/logs/update/install/status 均
        自带 set -euo pipefail）。哨兵防误加裸 set -e 坑 sourced 场景。"""
        assert not re.search(r"^set ", _shell_text("ops/_common.sh"), re.M)


# ============================================
# A2. 临时文件卫生（trap EXIT）
# ============================================

class TestR9ShellTempHygiene:
    def test_snapshot_mktemp_trap_with_diagnosis_exception(self):
        """snapshot 的 mktemp 产物经 trap EXIT 兜底清理（任何退出路径不留
        /tmp 残留）；唯一豁免是 gzip -t 失败分支 KEEP_RAW=1 显式保留原始
        SQL 供排查（文案与豁免标记成对在场）。"""
        text = _shell_text("snapshot_db.sh")
        assert 'RAW_SQL="$(mktemp' in text, "mktemp 临时产物不在场"
        assert "trap '[ \"$KEEP_RAW\" -eq 1 ] || rm -f \"$RAW_SQL\"' EXIT" in text, \
            "缺 trap EXIT 清理（KEEP_RAW 豁免口径）"
        assert "KEEP_RAW=1" in text and "供排查" in text, \
            "gzip -t 失败的显式保留标记/文案缺失（豁免与 trap 口径对不上）"

    def test_backup_part_file_trap_cleanup(self):
        """backup 的 .part 半截产物经 trap EXIT 清理：set -euo pipefail 下
        mysqldump 中途失败立即退出，无 trap 会在 backups 目录残留半截 .part
        （不匹配 *.sql.gz 保留策略 glob、永不被清理）。"""
        text = _shell_text("backup_db.sh")
        assert 'DB_TMP="$DB_OUT.part"' in text
        assert "trap 'rm -f \"$DB_TMP\"' EXIT" in text

    def test_restore_has_no_mktemp_temp_products(self):
        """restore 无临时产物（gunzip -c | mysql 容器内流式导入，不落中间
        文件）——临时文件卫生面天然为空，哨兵防未来引入 mktemp 忘配 trap。"""
        assert "mktemp" not in _shell_text("restore_db.sh")


# ============================================
# A3. docker exec 引号层级 ＋ 口令口径
# ============================================

class TestR9DockerExecQuoteLayers:
    def test_mysql_pwd_env_convention_everywhere(self):
        """容器内 mysql/mysqldump 口令统一 MYSQL_PWD 环境变量口径（容器内
        ps 不可见、特殊字符不经 shell 二次解析）——status.sh 原
        -p"$MYSQL_ROOT_PASSWORD" 命令行形态已归一。"""
        for rel in ("restore_db.sh", "snapshot_db.sh", "ops/status.sh"):
            text = _shell_text(rel)
            assert '-p"$MYSQL_ROOT_PASSWORD"' not in text, \
                f"{rel} 仍有命令行口令形态（ps 可见）"
            assert 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD"' in text, \
                f"{rel} 缺 MYSQL_PWD 环境变量口径"

    def test_sh_c_wrapped_in_single_quotes(self):
        """sh -c 整条命令一律宿主单引号包裹（$ 不被宿主展开，容器内 sh 负责展开
        MYSQL_ROOT_PASSWORD / 内层 "$@"；双引号包裹会让宿主提前展开容器变量——
        本项目多次踩的引号层级坑）。"""
        for rel in ("restore_db.sh", "snapshot_db.sh", "ops/status.sh"):
            text = _shell_text(rel)
            assert 'sh -c "' not in text, f"{rel} 出现 sh -c 双引号包裹（宿主会展开 $）"
            assert "sh -c '" in text


# ============================================
# A4. restore 退出码契约（0/1/2）＋ 锚点计数健壮性
# ============================================

class TestR9RestoreExitContract:
    _text = _shell_text("restore_db.sh")

    def test_exit_codes_confined_to_contract(self):
        """头注承诺 0 成功 / 1 不安全或失败 / 2 参数错误——全脚本 exit 码
        不越界，且 1/2 都在用。"""
        codes = {int(m) for m in re.findall(r"\bexit (\d+)", self._text)}
        assert codes <= {0, 1, 2}, f"restore 出现契约外退出码: {codes}"
        assert {1, 2} <= codes

    def test_say_err_always_paired_with_exit(self):
        """say_err 与退出码成对（错误消息一致性）：每处 say_err **调用行**的
        同语句或随后两行内必有 exit 1/exit 2——不留「报错却 0 退出」或依赖
        set -e 隐式退出码的歧义路径（注释行提及 say_err 的不计）。"""
        lines = self._text.splitlines()
        for i, ln in enumerate(lines):
            if "say_err" in ln and not ln.lstrip().startswith("#"):
                window = "\n".join(lines[i:i + 3])
                assert re.search(r"exit [12]", window), \
                    f"restore 第 {i + 1} 行 say_err 未配对退出码: {ln.strip()}"

    def test_anchor_count_numeric_preflight(self):
        """锚点计数结果数字形态预检（R9 修复）：非数字/空串不进 -eq 算术
        比较——那会伪装成 test 语法错（bash 退出码 2）违反 0/1/2 契约；
        按导入失败判（1）并给人工核对指引。"""
        assert re.search(
            r"case \"\$n_tables\" in\s*\n\s*''\|\*\[!0-9\]\*\)",
            self._text,
        ), "锚点计数数字形态预检缺失"
        assert "锚点计数结果异常" in self._text


# ============================================
# A5. 全角相邻变量 ＋ _common.sh 卫生
# ============================================

class TestR9VarQuotingDiscipline:
    def test_no_unbraced_var_adjacent_fullwidth_paren(self):
        """全角相邻坑回归哨兵（本项目三次踩）：六文件无 $VAR（ 未加花括号
        形态——全角括号前必须 ${VAR}（，消除「变量名边界靠猜」的脆弱形态
        （本扫描零豁免：双引号串内也要求花括号）。"""
        for rel in SHELL_FILES:
            bad = re.findall(r"\$[A-Za-z_][A-Za-z0-9_]*（", _shell_text(rel))
            assert not bad, f"{rel} 存在 $VAR（ 未加花括号形态: {bad}"

    def test_common_sh_no_duplicate_exit(self):
        """_common.sh ensure_docker_daemon 的重复 exit 1 死代码已清（R9 终审
        顺手项——两连 exit 永不可达第二发）。"""
        assert not re.search(r"exit 1\s*\n\s*exit 1\b",
                             _shell_text("ops/_common.sh"))

    def test_common_loop_vars_quoted_in_test(self):
        """_common.sh 数值循环变量在 test 中加引号（R9 终审归一；数值恒
        安全但形态与其他脚本对齐）。"""
        text = _shell_text("ops/_common.sh")
        assert '[ "$i" -lt 40 ]' in text
        assert '[ "$i" -lt 120 ]' in text
        assert not re.search(r"\[ \$i ", text)


# ============================================
# A6. entrypoint 灌库链幂等性（已知 ✓ 核实钉住）
# ============================================

class TestR9EntrypointIdempotency:
    _text = _shell_text("entrypoint.sh")

    def test_run_loader_appends_if_empty(self):
        """run_loader 统一追加 --if-empty（幂等闸）：表已有数据直接跳过、
        不执行整体重建，重复执行安全。"""
        assert '"$@" --if-empty || echo' in self._text

    def test_all_loaders_route_through_run_loader(self):
        """七个 load_* 灌库步全部经 run_loader（--if-empty 链覆盖完整）——
        防未来新增灌库步绕开幂等闸（P2 实证过的 wordforms 漏灌同型面）。"""
        for mod in ("load_word_library.py", "load_supplemented_senses.py",
                    "load_corpus_dataset.py", "load_category_study.py",
                    "load_domain_family.py", "load_zh_dict.py",
                    "load_wordforms.py"):
            pos = self._text.find(f"python scripts/{mod}")
            assert pos != -1, f"entrypoint 缺灌库步 {mod}"
            head = self._text[max(0, pos - 200):pos]
            assert "run_loader" in head, f"{mod} 未走 run_loader（绕开 --if-empty 闸）"

    def test_direct_calls_have_own_fault_tolerance(self):
        """三个不经 run_loader 的直调步各自容错/幂等：update_domain_family
        （幂等增强）与 parse_modern_chinese_dict（首次 mdx 条件内）|| echo
        非阻断；load_llm_screening 原生 --if-empty。"""
        assert "load_llm_screening.py --if-empty" in self._text
        assert re.search(r"update_domain_family_data.py \\\s*\|\| echo", self._text)
        assert re.search(r"parse_modern_chinese_dict.py \\\s*\|\| echo", self._text)


# ============================================
# B1. 词表并发乐观锁（P3 修复回归）
# ============================================

@pytest.fixture
def vocab_file(tmp_path, monkeypatch):
    """把 _VOCAB_PATH 指到 tmp_path 预置种子词表（真写回断言面，绝不触仓库
    权威词表 configs/defining_vocab.txt）。"""
    vf = tmp_path / "defining_vocab.txt"
    vf.write_text("# 定义词表（测试种子）\n" + "\n".join(_SEED_WORDS) + "\n",
                  encoding="utf-8")
    monkeypatch.setattr(dap, "_VOCAB_PATH", vf)
    return vf


class TestR9VocabOptimisticLock:
    def test_lock_rejects_when_file_changed_elsewhere(self, vocab_file):
        """乐观锁拒写面：基线 mtime 取后他人并发写回（内容＋mtime 变化）——
        expect_mtime 比对失配抛 ValueError，文件保持他人版本（丢更新面收口）。"""
        baseline = dap._vocab_file_mtime()
        assert baseline is not None
        # 模拟他人并发写回（os.utime 强推 mtime，保证与基线必不相等）
        vocab_file.write_text(
            "# 定义词表（他人并发版）\n" + "\n".join(_SEED_WORDS) + "\nrun\n",
            encoding="utf-8")
        st = os.stat(vocab_file)
        os.utime(vocab_file, (st.st_atime + 5, st.st_mtime + 5))
        with pytest.raises(ValueError, match="并发修改"):
            dap._vocab_write_words(["move", "come"], "编者甲",
                                   expect_mtime=baseline)
        # 拒写 = 文件保持他人版本（先写者不丢更新）
        assert "run" in vocab_file.read_text(encoding="utf-8")

    def test_lock_accepts_when_file_untouched(self, vocab_file):
        """基线新鲜（无人并发写过）→ 正常写回，返回词条数。"""
        baseline = dap._vocab_file_mtime()
        n = dap._vocab_write_words(_SEED_WORDS + ["run"], "编者甲",
                                   expect_mtime=baseline)
        assert n == 3

    def test_legacy_two_arg_call_bypasses_lock(self, vocab_file):
        """缺省哨兵不启用比对：旧两参直调形态（tests/test_vocab_admin.py 的
        存量用法）行为与 R9 前一致——锁是页面调用点显式传基线才生效。"""
        n = dap._vocab_write_words(["move"], "编者甲")
        assert n == 1

    def test_mtime_none_allows_first_boot_create(self, tmp_path, monkeypatch):
        """文件不在场（首次建表）：基线 None，写前重取仍 None → None==None
        不拦——首次建表语义保持。"""
        monkeypatch.setattr(dap, "_VOCAB_PATH", tmp_path / "nope.txt")
        assert dap._vocab_file_mtime() is None
        assert dap._vocab_write_words(["move"], "编者甲",
                                      expect_mtime=None) == 1

    def test_render_tab_wires_lock_baseline_and_two_write_sites(self):
        """页面接线哨兵：_render_vocab_tab 读词表后即刻取基线（恰好一处），
        增/删两处写回均传 expect_mtime=vocab_mtime（重建按钮走
        write_corpus_vocab_file 整表刷新、按钮级确认，不在锁面）。"""
        src_tab = inspect.getsource(dap._render_vocab_tab)
        assert src_tab.count("vocab_mtime = _vocab_file_mtime()") == 1
        assert src_tab.count("expect_mtime=vocab_mtime") == 2


# ============================================
# B2. 词表读取 1MB 闸（P3 修复回归——对齐 _read_vocab_file stat 预检形态）
# ============================================

class TestR9VocabReadSizeGate:
    def test_oversize_rejected(self, vocab_file):
        """>1MB → ValueError（拒绝读取文案），不整读进内存。"""
        vocab_file.write_text("x" * (dap._VOCAB_MAX_BYTES + 1), encoding="utf-8")
        with pytest.raises(ValueError, match="过大"):
            dap._vocab_read_words()

    def test_boundary_exactly_max_reads_ok(self, vocab_file):
        """恰等于上限（1MB）放行——闸是「超过才拒」，与 _read_vocab_file
        的 >1_000_000 判式同口径。"""
        payload = "x" * dap._VOCAB_MAX_BYTES
        vocab_file.write_text(payload, encoding="utf-8")
        assert dap._vocab_read_words() == [payload]

    def test_stat_preflight_precedes_full_read(self):
        """形态哨兵（对齐 _read_vocab_file 的 R6 加固形态）：stat 预检先于
        read_text 整读（防巨文件先整读进内存的内存放大面）；读后 len 复查
        兜底 stat 后变大的竞态（两道闸同口径）。"""
        src_fn = inspect.getsource(dap._vocab_read_words)
        assert src_fn.index("stat().st_size") < src_fn.index("_VOCAB_PATH.read_text")
        assert "_VOCAB_MAX_BYTES" in src_fn
        assert src_fn.count("_VOCAB_MAX_BYTES") >= 2, "缺读后 len 复查的第二道闸"

    def test_os_error_wrapped_as_valueerror(self, tmp_path, monkeypatch):
        """读侧 OSError（路径是目录/权限等）包装为 ValueError——页面调用方
        统一按「读取被拒」降级停写，不崩页。"""
        monkeypatch.setattr(dap, "_VOCAB_PATH", tmp_path)  # 目录：read_text 抛 OSError
        with pytest.raises(ValueError, match="读取失败"):
            dap._vocab_read_words()


# ============================================
# B3. P2 二次闸 ＋ note→detail ＋ 200 上限（页面结构哨兵）
# ============================================

class TestR9VocabPageSentinels:
    def test_detail_key_read_not_note(self):
        """P3 note→detail：质检状态区读 _item 契约键 detail（无 'note' 键
        ——读 note 恒取空串，状态字样后详情永远缺失）。"""
        src_tab = inspect.getsource(dap._render_vocab_tab)
        assert 'item.get("detail", "")' in src_tab
        assert 'item.get("note"' not in src_tab

    def test_add_limit_200_present(self):
        """P2 增词上限 200：text_area 解析后 >200 warning 停写（按原始解析
        数计——非法词本就被下游过滤，闸只管量）。"""
        src_tab = inspect.getsource(dap._render_vocab_tab)
        assert "if len(tokens) > 200:" in src_tab
        assert "单次增词 ≤200" in src_tab

    def test_read_gate_stops_write_ui_on_oversize(self):
        """1MB 闸的页面接线：读侧 ValueError → st.error 停渲染（写操作面
        停用）——防「空表＋新词」整表覆写丢数据。"""
        src_tab = inspect.getsource(dap._render_vocab_tab)
        assert "词表读取被拒" in src_tab
        # 停渲染在先（return），写 UI 与三按钮在后
        assert src_tab.index("词表读取被拒") < src_tab.index("vocab_add_btn")


# ============================================
# B4. P2 二次闸交互面 ＋ 200 上限（AppTest 真渲染）
# ============================================

def _by_key(elements, key):
    """按 widget key 现取现用（每轮新树重抓——AppTest 时序契约，见
    test_vocab_page.py 模块 docstring）。"""
    hits = [el for el in elements if str(el.key) == key]
    assert hits, f"widget 不在场: {key}"
    return hits[0]


def _open_vocab_page():
    """AppTest 开词典管理区并 _goto 到词表 tab 所在页（fx23 式导航先例）。"""
    at = _new_at()
    at.session_state["user"] = _ADMIN_SESSION
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    _goto(at, "dict_admin")
    assert not at.exception, [str(e.value) for e in at.exception]
    return at


def _vocab_body(vf) -> list:
    """读 tmp 词表正文词条（去注释去空行——与 _vocab_read_words 同口径）。"""
    return [ln.strip() for ln in vf.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


class TestR9VocabPageInteraction:
    # 纯字母词批量生成（"aa".."hv"）：增词解析器只收 [a-z']+（数字词会被
    # 合法性过滤吞掉）——批量用例必须用纯字母词才能走真正的写回路径
    @staticmethod
    def _letter_batch(n: int) -> list:
        return [chr(97 + i // 26) + chr(97 + i % 26) for i in range(n)]

    def test_add_over_200_warns_and_writes_nothing(self, vocab_file):
        """>200 词一次性粘贴 → warning「单次增词 ≤200」停写、文件不变、
        词条数不变（闸按原始解析数计——超限词即使全部合法也先撞量闸）。"""
        at = _open_vocab_page()
        _by_key(at.text_area, "vocab_add").set_value(
            ", ".join(self._letter_batch(201)))
        _by_key(at.button, "vocab_add_btn").click()
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]
        warns = [str(w.value) for w in at.warning if "≤200" in str(w.value)]
        assert warns, f"超限应 warning 停写: {[str(w.value) for w in at.warning]}"
        assert "解析到 201" in warns[0]
        assert _vocab_body(vocab_file) == _SEED_WORDS, "超限不得改文件"

    def test_add_200_boundary_writes_ok(self, vocab_file):
        """边界 200 词（≤200，全部合法纯字母词）→ 正常写回（原逻辑），flash
        报「已增补 200 词」——闸不误伤合法批量增词。"""
        batch = self._letter_batch(200)
        at = _open_vocab_page()
        _by_key(at.text_area, "vocab_add").set_value(", ".join(batch))
        _by_key(at.button, "vocab_add_btn").click()
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]
        flash = [str(s.value) for s in at.success if "已增补" in str(s.value)]
        assert flash and "已增补 200 词" in flash[0], \
            f"200 词边界应正常写回: {flash}"
        body = _vocab_body(vocab_file)
        assert len(body) == len(_SEED_WORDS) + 200
        assert set(batch) <= set(body)

    def test_qc_status_area_shows_detail_not_empty(self, vocab_file):
        """P3 note→detail 功能面：质检状态区 pass 态 success 的「pass —— 」
        之后带真实详情（style_check._item 契约 detail 文案「词表 N 词、
        无重复」），不再是旧 note 读法的恒空尾巴。"""
        at = _open_vocab_page()
        assert not at.exception, [str(e.value) for e in at.exception]
        qc = [str(s.value) for s in at.success
              if "质检 DEFINING_VOCAB" in str(s.value)]
        assert qc and qc[0].startswith("质检 DEFINING_VOCAB：pass")
        tail = qc[0].split("pass —— ", 1)[1].strip()
        assert tail, "pass 态详情缺失（note→detail 修复未生效）"
        assert "词、无重复" in tail, f"详情应为 _item 契约 detail 文案: {tail}"


# ============================================
# B5. build_defining_vocab.py detail 键（运行时证明）
# ============================================

class TestR9BuildDefiningVocabDetail:
    def _load_script(self):
        """薄壳脚本按文件位置独立加载（与 test_review_r7_r8 同形态）。"""
        spec = importlib.util.spec_from_file_location(
            "bdv_r9", REPO / "scripts" / "build_defining_vocab.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    # 桩规模：≥10 词（脚本 main 在 len(pairs)<10 时提前返回 1，到不了质检段）
    _STUB_PAIRS = [(f"w{i}", 3) for i in range(12)]

    def test_detail_key_reaches_output(self, tmp_path, monkeypatch, capsys):
        """运行时证明：质检验证段读 'detail' 键——pass 态详情文案真到 stdout
        （旧 'note' 读法下「DEFINING_VOCAB → pass: 」后恒空）。构建函数全桩
        （零库依赖），style.yaml 指向 tmp。"""
        mod = self._load_script()
        monkeypatch.setattr(mod, "fetch_corpus_definitions", lambda: ["the cat the"])
        monkeypatch.setattr(mod, "count_corpus_words",
                            lambda texts: {w: 3 for w, _ in self._STUB_PAIRS})
        monkeypatch.setattr(mod, "build_corpus_vocab",
                            lambda counter, min_freq=2: list(self._STUB_PAIRS))
        monkeypatch.setattr(mod, "write_corpus_vocab_file",
                            lambda pairs: Path("/fake/vocab.txt"))
        monkeypatch.setattr(
            mod, "check_defining_vocab",
            lambda style: {"code": "DEFINING_VOCAB", "rule": "r",
                           "status": "pass",
                           "detail": "词表 809 词、无重复（词表来源 vocab_file 词表文件）"})
        style_file = tmp_path / "style.yaml"
        style_file.write_text("vocab_file: configs/defining_vocab.txt\n",
                              encoding="utf-8")
        monkeypatch.setattr(mod, "STYLE_FILE", style_file)
        monkeypatch.setattr(sys, "argv", ["build_defining_vocab.py"])
        rc = mod.main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "DEFINING_VOCAB → pass: 词表 809 词、无重复" in out, \
            f"detail 文案未到输出（note 读法回潮？）: {out}"

    def test_non_pass_detail_exits_1(self, tmp_path, monkeypatch, capsys):
        """退出码判定不受 detail 修复影响：质检非 pass → 退出码 1（头注
        「退出码判定不受影响」的契约钉住）。"""
        mod = self._load_script()
        monkeypatch.setattr(mod, "fetch_corpus_definitions", lambda: ["the cat the"])
        monkeypatch.setattr(mod, "count_corpus_words",
                            lambda texts: {w: 3 for w, _ in self._STUB_PAIRS})
        monkeypatch.setattr(mod, "build_corpus_vocab",
                            lambda counter, min_freq=2: list(self._STUB_PAIRS))
        monkeypatch.setattr(mod, "write_corpus_vocab_file",
                            lambda pairs: Path("/fake/vocab.txt"))
        monkeypatch.setattr(
            mod, "check_defining_vocab",
            lambda style: {"code": "DEFINING_VOCAB", "rule": "r",
                           "status": "fail", "detail": "词表为空"})
        style_file = tmp_path / "style.yaml"
        style_file.write_text("vocab_file: configs/defining_vocab.txt\n",
                              encoding="utf-8")
        monkeypatch.setattr(mod, "STYLE_FILE", style_file)
        monkeypatch.setattr(sys, "argv", ["build_defining_vocab.py"])
        assert mod.main() == 1
        assert "DEFINING_VOCAB → fail: 词表为空" in capsys.readouterr().out
