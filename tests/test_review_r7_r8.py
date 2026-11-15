"""R7 权限矩阵穿越 ＋ R8 状态机完整性扫描 —— review 收敛测试（批次 53）。

聚焦批次 41-51 新功能面（词表核定页 / collab_db / 双语切换）＋既有核心流抽查。
全部测试**零真库依赖**（monkeypatch / 源码哨兵 / 纯函数），任何环境可跑。
所有权说明：src/dict_admin_pages.py 与 src/app.py 本轮**只读**——涉及二者的
问题以「现状哨兵」测试钉住当前形态，修复时随移交项一起翻转断言。

R7 判定摘要（详见各测试 docstring）：
  * 词表核定页：页面级两级角色闸在 render_dict_admin_page 入口（会话判定
    ＋实时查库兜底）**有闸**；tab 内三处写操作（增/删/重建）**无 API 级
    二次闸**（同页成员/媒体/出版 tab 均有 guards.require_dict_admin 调用点
    闸）——防御纵深缺，P2 移交（只读文件），现状哨兵钉住；
  * 双语切换：set_lang 未登录可切（会话态，设计如此）；登录态持久化走
    user_context_db.upsert_profile——**签名不收 user_id**（会话派生唯一
    来源），「伪造 user_id 越权写他人 profiles」在数据层**无构造面**；
  * collab_db.create_assignment：数据层参数校验＋FK 兜底在位；角色面
    （任务×角色矩阵/负荷上限/回避制）在页面层三重校验＋调用点
    guards.require_dict_admin——数据层薄 INSERT 为文档化设计决定（对照
    reassign_assignment 的数据层 actor 闸：两族语义按 guards 模块口径
    「系统作业面/交互面」分治），记录不修；
  * restore --database：宿主运维操作无角色概念（设计如此）；库名白名单、
    --force 警告、非交互拒绝覆盖非空库、BUSINESS_DB 判定守卫在位——
    「--force 指向非 BUSINESS_DB 的他人业务库」残余面在单机运维场景
    可接受（记录）。

R8 判定摘要：
  * assignments：全仓唯一 UPDATE 写点是 reassign_assignment（状态闸
    REASSIGNABLE_ASSIGNMENT_STATUSES=('open',)＋原子 WHERE 复验）——
    open→in_progress→submitted→closed 前向流转**无写点**（annotation_flow
    常量注释如实声明），「closed 后再认领」因无认领入口而不可能经代码发生；
  * 词表核定：文件直写无状态机——本轮收「写一半」面（write_corpus_vocab_file
    临时文件＋os.replace 原子换名＋失败清 tmp）；「读-改-写丢更新」（两编者
    并发增删、后写覆盖先写）在页面层 _vocab_write_words（只读文件）——P3
    移交（文件级乐观锁建议：mtime/版本比对或锁文件）；
  * i18n：get_lang 两级白名单防御（会话脏值/库脏值均不采信）既有测试已锁
    （test_i18n.py）；本轮补 ZH_EN 字典字面量重复键哨兵（ast 扫描）；
  * style_check_runs：append-only（全模块无 UPDATE/DELETE），消费端
    collab_metrics.style_check_status 取最近 1 次（口径：体例以现行
    style.yaml 为准）、pass_rate_trend 全史如实——历史 fail run 留在趋势里
    语义正确。
"""

import ast
import importlib.util
import inspect
import os
from pathlib import Path

import pytest

from src import user_context_db
from src.annotation_flow import (
    ASSIGNMENT_STATUSES,
    REASSIGNABLE_ASSIGNMENT_STATUSES,
    reassign_assignment,
)
from src.collab_db import create_assignment
from src.guards import require_dict_admin, require_role
from src.style_check import (
    _REPO_ROOT,
    check_defining_vocab,
    write_corpus_vocab_file,
)
from src.users_db import effective_six_roles

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"

# 纯 sys_admin 会话（六角色快照，无 dict_admin、非 legacy admin）
_PURE_SYS_ADMIN = {"id": 3, "username": "sysop", "roles": ["sys_admin"]}
# legacy admin（过渡期两位一体：role='admin' → dict_admin+sys_admin）
_LEGACY_ADMIN = {"id": 1, "username": "admin", "role": "admin"}


# ============================================
# R7-1 词表核定页权限闸结构（dict_admin_pages 只读——现状哨兵）
# ============================================

class TestR7VocabPageGate:
    def test_page_entry_has_two_level_role_gate(self):
        """tab 入口有页面级闸：render_dict_admin_page 在调用 _render_vocab_tab
        之前先过会话判定（_is_dict_admin）＋实时查库兜底
        （_db_confirms_dict_admin），不过即 return——tab 内容一概不执行。"""
        import src.dict_admin_pages as dap

        src_page = inspect.getsource(dap.render_dict_admin_page)
        assert "_is_dict_admin(me)" in src_page
        assert "_db_confirms_dict_admin(me)" in src_page
        # 闸先于 tab 调用（同一函数内序关系）
        assert src_page.index("_is_dict_admin(me)") < src_page.index(
            "_render_vocab_tab(me)")
        # _render_vocab_tab 全仓唯一调用点就在本函数内（def 行除外）
        module_src = (SRC / "dict_admin_pages.py").read_text(encoding="utf-8")
        call_sites = [ln for ln in module_src.splitlines()
                      if "_render_vocab_tab(" in ln
                      and not ln.strip().startswith("def ")]
        assert len(call_sites) == 1, f"词表 tab 出现了新调用点: {call_sites}"
        assert "_render_vocab_tab(me)" in inspect.getsource(dap.render_dict_admin_page)

    def test_vocab_tab_write_ops_lack_api_gate_pinned_gap(self):
        """P2 移交现状哨兵：tab 内三处写操作（增词/删词/重建）无 API 级二次
        闸（guards.require_dict_admin）——防御纵深缺一层。页面级闸在场时
        不可达利用，但与同页成员/媒体/出版 tab（写路径调用点均再过
        require_dict_admin，纵深防御 §6-4 同页写路径同口径）不一致。
        **移交修复时翻转本断言**（写路径应改为先 guards.require_dict_admin()
        再落盘，并补低权会话直调拒绝的交互面测试）。"""
        import src.dict_admin_pages as dap

        src_tab = inspect.getsource(dap._render_vocab_tab)
        assert "require_dict_admin" not in src_tab, (
            "词表 tab 已补 API 级二次闸——请同步更新本哨兵与本文件 R7-1 判定："
            "改为断言三处写操作（vocab_add_btn/vocab_del_btn/vocab_rebuild_btn）"
            "的调用点都过 guards.require_dict_admin()")
        # 写操作确实在场（哨兵别钉在空函数上）
        for key in ("vocab_add_btn", "vocab_del_btn", "vocab_rebuild_btn"):
            assert key in src_tab, f"写按钮 {key} 不在场（页面结构变了，复核哨兵）"

    def test_sys_admin_compat_semantics(self):
        """sys_admin 兼判口径：legacy role='admin' 经 effective_six_roles
        两位一体（dict_admin+sys_admin 都有——过渡期兼容）；纯六角色
        sys_admin **不**兼判 dict_admin（词典数据写与账号管理分权）。三层
        （页面 _is_dict_admin / guards.require_dict_admin / 侧边栏
        _PAGE_ACCESS_SIX）同一判定实现，口径一致。"""
        assert effective_six_roles(_LEGACY_ADMIN) >= {"dict_admin", "sys_admin"}
        assert effective_six_roles(_PURE_SYS_ADMIN) == {"sys_admin"}
        # guards 同口径：legacy admin 过闸；纯 sys_admin 被拒
        assert require_dict_admin(_LEGACY_ADMIN) == _LEGACY_ADMIN
        with pytest.raises(PermissionError):
            require_dict_admin(_PURE_SYS_ADMIN)
        # 但纯 sys_admin 在 sys_admin 动作面（如账号管理）过闸
        assert require_role(_PURE_SYS_ADMIN, allowed={"sys_admin"},
                            action="账号管理") == _PURE_SYS_ADMIN

    def test_sidebar_dict_admin_zone_entry_is_dict_admin_only(self):
        """app.py 侧边栏入口口径（只读哨兵）：「📖 词典管理」页允许集恰为
        ('dict_admin',)——纯 sys_admin 连侧边栏入口都不可见，与页面闸一致
        （窄口设计：词典管理区不向 sys_admin 兼判开放）。"""
        from src.app import _PAGE_ACCESS_SIX

        assert _PAGE_ACCESS_SIX["dict_admin"] == ("dict_admin",)


# ============================================
# R7-2 双语切换：user_id 会话派生（无伪造面）
# ============================================

class TestR7LangSwitchOwnership:
    def test_upsert_profile_signature_takes_no_user_id(self):
        """「伪造 user_id 越权写他人 profiles」在数据层无构造面：写接口签名
        根本不收 user_id —— 归人只经 _resolve_user_id（会话派生，fail-closed），
        调用方没有任何入口指定他人 id。签名收窄即契约（模块 docstring
        「数据层不收 user_id」同源）。"""
        params = list(inspect.signature(user_context_db.upsert_profile).parameters)
        assert params == ["key", "value"], f"upsert_profile 签名漂移: {params}"

    def test_resolve_user_id_fail_closed_without_session(self, monkeypatch):
        """未登录（会话无 user）→ None：无主人不触库（读 None/写 False）。"""
        monkeypatch.setattr(user_context_db, "current_user", lambda: None)
        assert user_context_db._resolve_user_id() is None

    @pytest.mark.parametrize("bad_user", [
        {"id": 0}, {"id": -1}, {"id": "abc"}, {"id": None},
        {"username": "no-id"}, "not-a-dict", 7,
    ])
    def test_resolve_user_id_rejects_dirty_actor(self, monkeypatch, bad_user):
        """脏 actor（缺 id/非法 id/非 dict）一律 None —— 伪造会话拿不到
        合法归人，越权写在源头断（bool 是 int 子类由 as_int 先拦）。"""
        monkeypatch.setattr(user_context_db, "current_user", lambda: bad_user)
        assert user_context_db._resolve_user_id() is None

    def test_get_profile_never_touches_db_without_valid_session(
            self, monkeypatch):
        """未登录读偏好：fail-closed 在触库前返回 None（零 DB 访问——
        断言游标工厂根本不被创建）。"""
        def _boom_cursor():
            raise AssertionError("未登录不得触库")

        monkeypatch.setattr(user_context_db, "current_user", lambda: None)
        monkeypatch.setattr(user_context_db, "get_db_cursor", _boom_cursor)
        assert user_context_db.get_profile("ui.lang") is None
        assert user_context_db.upsert_profile("ui.lang", "en") is False


# ============================================
# R7-3 collab_db.create_assignment 分层防御（记录性契约）
# ============================================

class TestR7CreateAssignmentLayering:
    def test_bad_params_rejected_before_db(self, monkeypatch):
        """数据层参数校验先行（安全规则 2）：非法 id / task_type / category /
        scope_verbs 一律返回 0 且**零 DB 访问**（游标工厂不被创建）。"""
        def _boom_cursor():
            raise AssertionError("参数非法不得触库")

        monkeypatch.setattr("src.collab_db.get_db_cursor", _boom_cursor)
        assert create_assignment(0, "admission") == 0
        assert create_assignment(-1, "admission") == 0
        assert create_assignment("abc", "admission") == 0
        assert create_assignment(2, "bogus_task") == 0
        assert create_assignment(2, None) == 0
        assert create_assignment(2, "admission", category="") == 0
        assert create_assignment(2, "admission", category="x" * 41) == 0
        assert create_assignment(2, "admission", scope_verbs=[]) == 0
        assert create_assignment(2, "admission", scope_verbs="run") == 0
        assert create_assignment(2, "admission", assigned_by=0) == 0

    def test_thin_insert_contract_no_actor_param(self):
        """分层契约哨兵（R7-3 记录不修的口径固化）：create_assignment 是
        「系统作业面」薄 INSERT——签名不收 actor，角色面（任务×角色矩阵/
        负荷上限/回避制）归页面层三重校验＋调用点 guards.require_dict_admin
        （collab_pages._render_assign_tab 实证）。对照：交互面写函数
        reassign_assignment 收 actor 且入口先过 _require_assignment_actor。
        两族语义按 guards 模块「actor 语义口径表」分治——若未来给本函数
        补数据层角色闸，应走 require_role_interactive 语义并同步翻转本断言。"""
        params = inspect.signature(create_assignment).parameters
        assert "actor" not in params
        assert set(params) == {"assignee_id", "task_type", "scope_verbs",
                               "assigned_by", "category"}
        reassign_params = inspect.signature(reassign_assignment).parameters
        assert reassign_params["actor"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_reassign_data_layer_actor_gate(self):
        """对照面（其他写函数的分层防御在位）：reassign_assignment 数据层
        actor 闸——低权 dict 在触库前即抛 PermissionError（闸 1 先于一切
        DB 访问；系统作业 None 放行走既有契约不在此测）。"""
        with pytest.raises(PermissionError):
            reassign_assignment(1, 1, 2, 2,
                                actor={"id": 5, "username": "low",
                                       "role": "viewer"})
        with pytest.raises(PermissionError):
            reassign_assignment(1, 1, 2, 2, actor="garbage")


# ============================================
# R7-4 restore 脚本守卫（宿主运维面——静态哨兵）
# ============================================

class TestR7RestoreScriptGuards:
    _text = (REPO / "scripts" / "restore_db.sh").read_text(encoding="utf-8")

    def test_business_db_and_interactive_gates_present(self):
        """四道守卫在场（文本哨兵）：① BUSINESS_DB 判定（维护窗口提示口径）；
        ② 非交互终端拒绝覆盖非空库（--force 才可越——无人值守静默覆盖防）；
        ③ 库名白名单（进 SQL 前拦怪字符）；④ --force 越闸仍有警告留痕。
        残余面（--force + --database 指向非 BUSINESS_DB 的他人业务库）在
        单机运维场景可接受——记录不修（R7-4 判定）。"""
        assert "IS_BUSINESS_DB=1" in self._text
        assert "拒绝覆盖非空库" in self._text
        assert "只允许字母数字下划线" in self._text
        assert "已按 --force 跳过覆盖确认" in self._text

    def test_option_injection_gate_present(self):
        """批次 52 选项注入闸（- 前缀 ./ 归一）不回潮：DUMP_FILE 归一与
        gzip -t 完整性预检在位。"""
        assert "case \"$DUMP_FILE\" in\n  -*)" in self._text
        assert "gzip -t" in self._text


# ============================================
# R8-1 assignments 状态机（无前向流转写点——现状哨兵）
# ============================================

class TestR8AssignmentStateMachine:
    def test_single_guarded_update_write_point(self):
        """全仓 src/ 唯一「UPDATE assignments」写点是 reassign_assignment，
        且语句带原子状态守卫（WHERE ... AND status = %s）——状态机推进面
        收在单一有闸写点。前向流转（open→in_progress→submitted→closed）
        无写点（annotation_flow 常量注释如实声明）：「closed 后再认领」
        因无认领入口不可能经代码发生。**新增状态流转写点时必须带等价
        状态闸并翻转本哨兵**。"""
        hits = {}
        for py in sorted(SRC.glob("*.py")):
            text = py.read_text(encoding="utf-8")
            n = text.count("UPDATE assignments")
            if n:
                hits[py.name] = n
        assert hits == {"annotation_flow.py": 1}, f"UPDATE assignments 写点漂移: {hits}"
        flow = (SRC / "annotation_flow.py").read_text(encoding="utf-8")
        assert "AND status = %s AND assignee_id = %s" in flow, (
            "reassign 的原子状态守卫（status+assignee 前值复验）缺失")

    def test_collab_db_is_insert_only(self):
        """collab_db 数据层零 UPDATE/DELETE（docstring「唯一写路径=INSERT」
        契约的代码面哨兵）：status 固定初始态 'open'，无状态推进函数。"""
        text = (SRC / "collab_db.py").read_text(encoding="utf-8")
        assert "UPDATE " not in text
        assert "DELETE FROM" not in text
        assert "'open'" in text   # INSERT 固定初始态

    def test_status_enum_and_reassignable_gate_shape(self):
        """状态枚举四态与改派闸形态（既有 test_status_constants_match_ddl_enum
        / fx20 之外的独立复核——本文件自带，防跨文件漂移一屏可见）。"""
        assert ASSIGNMENT_STATUSES == ("open", "in_progress", "submitted", "closed")
        assert REASSIGNABLE_ASSIGNMENT_STATUSES == ("open",)


# ============================================
# R8-2 词表文件直写：原子落盘（本轮修复回归）＋ 丢更新移交记录
# ============================================

class TestR8VocabFileAtomicWrite:
    def test_atomic_write_roundtrip_and_no_tmp_leftover(self, tmp_path,
                                                        monkeypatch):
        """落盘原子化回归：临时文件写全 → os.replace 换名——产物完整、
        .tmp 无残留、返回路径正确（_REPO_ROOT monkeypatch 到 tmp 隔离，
        绝不触仓库权威词表）。"""
        monkeypatch.setattr("src.style_check._REPO_ROOT", tmp_path)
        (tmp_path / "configs").mkdir()   # 生产在 configs/ 在场前提下落盘
        ret = write_corpus_vocab_file([("the", 3), ("cat", 2), ("run", 2)])
        target = tmp_path / "configs" / "defining_vocab.txt"
        assert ret == target and target.is_file()
        body = [ln.strip() for ln in target.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.startswith("#")]
        assert body == ["the", "cat", "run"]   # 一行一词，pairs 原序
        assert "总出现 7 次" in target.read_text(encoding="utf-8")
        assert not list(target.parent.glob("*.tmp")), "落盘后不得残留 .tmp"

    def test_failed_replace_preserves_old_file_and_cleans_tmp(
            self, tmp_path, monkeypatch):
        """换名失败（磁盘满/权限/被打断模拟）：旧词表**原样保留**（读者
        要么旧表要么新表，绝无半截态）＋ .tmp 清理 ＋ 异常照常上传。"""
        monkeypatch.setattr("src.style_check._REPO_ROOT", tmp_path)
        target = tmp_path / "configs" / "defining_vocab.txt"
        target.parent.mkdir(parents=True)
        target.write_text("# old\nmove\n", encoding="utf-8")

        def _boom(src, dst):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(os, "replace", _boom)
        with pytest.raises(OSError):
            write_corpus_vocab_file([("the", 3)])
        assert target.read_text(encoding="utf-8") == "# old\nmove\n", (
            "换名失败不得破坏既有词表")
        assert not list(target.parent.glob("*.tmp")), "失败路径不得残留 .tmp"

    def test_page_layer_lost_update_is_p3_handoff(self):
        """P3 移交记录哨兵：页面层「编者增删写回」(_vocab_write_words) 是
        读-改-写（无版本/mtime 比对、无锁）——两编者并发增删时后写覆盖先写
        （删词场景丢更新最实）。本轮只修写一半面（上方两测试），丢更新
        面移交（只读文件）；修复建议：文件级乐观锁（写前重读＋mtime/
        词条数比对不匹配即拒绝并提示刷新，或 configs 侧锁文件）。
        修复后翻转：断言 _vocab_write_words 具备版本/mtime 防护。"""
        import src.dict_admin_pages as dap

        src_fn = inspect.getsource(dap._vocab_write_words)
        assert "read_text" not in src_fn and "getmtime" not in src_fn, (
            "页面写回已具备重读/版本比对——请更新本 P3 记录与断言")

    def test_script_shell_delegates_write_to_style_check(self, monkeypatch,
                                                         capsys):
        """scripts/build_defining_vocab.py 薄壳化回归：落盘委托
        src/style_check.write_corpus_vocab_file（单一事实源，头注模板不再
        双份）；dry-run 只预览不落盘。"""
        script_path = REPO / "scripts" / "build_defining_vocab.py"
        spec = importlib.util.spec_from_file_location("bdv_under_test",
                                                      script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        calls = []
        monkeypatch.setattr(mod, "write_corpus_vocab_file",
                            lambda pairs: (calls.append(pairs),
                                           Path("/fake/vocab.txt"))[1])
        mod.write_vocab_file([("a", 2), ("b", 1)], dry_run=True)
        assert calls == [], "dry-run 不得触发落盘"
        assert "dry-run" in capsys.readouterr().out
        mod.write_vocab_file([("a", 2)], dry_run=False)
        assert calls == [[("a", 2)]], "落盘必须委托 write_corpus_vocab_file"
        assert "/fake/vocab.txt" in capsys.readouterr().out


# ============================================
# R8-3 i18n 字典卫生（脏值防御既有测试已锁，这里补重复键哨兵）
# ============================================

class TestR8I18nDictHygiene:
    def test_zh_en_literal_has_no_duplicate_keys(self):
        """ZH_EN 字面量无重复键（ast 扫描）：Python dict 字面量重复键静默
        覆盖——同值重复是死代码、异值重复是「想改没改成」的隐患，一律拦。
        （本轮已去重 '用户名'/'密码' 两条同值重复——回归哨兵。）"""
        tree = ast.parse((SRC / "i18n.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                keys = [ast.literal_eval(k) for k in node.keys
                        if isinstance(k, ast.Constant)]
                dupes = {k for k in keys if keys.count(k) > 1}
                assert not dupes, f"ZH_EN 字面量重复键: {sorted(dupes)}"


# ============================================
# R8-4 style_check_runs append-only（消费端口径）
# ============================================

class TestR8StyleCheckRunsAppendOnly:
    def test_no_update_or_delete_on_runs_table(self):
        """style_check_runs 只 INSERT（append-only 哨兵）：引擎与消费方
        （collab_metrics）全模块无 UPDATE/DELETE——质检历史如实留痕，
        词表 pass 后历史 fail run 仍在趋势里（语义正确，记录不修）。"""
        for name in ("style_check.py", "collab_metrics.py"):
            text = (SRC / name).read_text(encoding="utf-8")
            assert "UPDATE style_check_runs" not in text, name
            assert "DELETE FROM style_check_runs" not in text, name

    def test_check_item_contract_keys(self):
        """检查项字典契约：键恰为 {code, rule, status, detail}（_item 单一
        契约）——**没有 'note' 键**。回归背景：build_defining_vocab.py 旧代码
        读 item.get('note') 恒取空串（R7/R8 review 实证修复为 'detail'）；
        dict_admin_pages.py:4074 同型读法属只读文件——P3 移交（词表页质检
        状态区 detail 恒空，状态字样正常、不崩，纯展示缺文）。"""
        style = {"defining_vocab": [f"word{i}" for i in range(12)]}
        item = check_defining_vocab(style)
        assert set(item) == {"code", "rule", "status", "detail"}
        assert "note" not in item
        assert item["status"] == "pass"
        assert item["detail"], "pass 态 detail 不得为空（消费方读它出详情）"

    def test_build_defining_vocab_reads_detail_key(self):
        """脚本修复回归：build_defining_vocab.py 质检验证段读 'detail' 键，
        'note' 键读法不回潮。"""
        text = (REPO / "scripts" / "build_defining_vocab.py").read_text(
            encoding="utf-8")
        assert "get('detail'" in text or 'get("detail"' in text
        assert "get('note'" not in text and 'get("note"' not in text
