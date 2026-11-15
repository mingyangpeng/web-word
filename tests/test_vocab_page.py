"""📝 词表核定页（dict_admin 区 tab 5）AppTest 交互专项 —— R2 词表核定页深测。

前两轮 review 只做过框架层/纯函数层（tests/test_vocab_admin.py 锁
_vocab_read/_vocab_write 往返），本轮逐页＋页面级交互深测，全部走
AppTest 真渲染（fx23 式 admin 登录 mock：session_state["user"] 注入六角色
会话，_is_dict_admin 纯函数放行，不触库角色兜底）：

  1. 渲染冒烟：登录态渲染不崩（not at.exception）＋ tab 在场 ＋ 质检状态区
     pass 态 success ＋ 词表 dataframe 在场（'词条' 列，行数=词表实际词条数）；
  2. 增词交互：text_area 填词 → 点「➕ 写入新增词」→ **真文件写回断言**
     （_VOCAB_PATH monkeypatch 到 tmp_path）＋ rerun 后词条数 +N ＋ flash
     提示（ui_kit.flash 队列经 pop_and_render_flash 弹出）；
  3. 删词交互：text_input 填已有词 → 点「➖ 移除该词」→ 写回断言词条数 -1
     （含 casefold 大小写变体命中）；删不存在词/空输入 → warning 不崩、
     文件不变；
  4. 重复词：加已存在词 → warning「无有效新增（…跳过）」不崩、文件不变；
  5. 🔄 重建按钮：fetch_corpus_definitions / count_corpus_words /
     build_corpus_vocab / write_corpus_vocab_file 四函数 monkeypatch
     （src.style_check 模块级——页面点击分支内 from-import 即取运行时属性）
     → 点击 → success（已重建 N 词，flash 态）＋ 语料空 → warning 且
     write 不被调用。

AppTest 时序注意（两轮实证踩坑，写入 docstring 供后续用例规避）：
  * **控件引用必须每轮重新抓取**——at.run() 每轮整树替换，旧树元素对象
    的 set_value/click 虽然大多仍能落到共享 widget state，但 button 连续
    二次 click 会因 _value 残留 True 而第二次不触发（trigger 消费语义），
    本文件一律「每轮断言前现取现用」；
  * at.run() 的树是**一次 run 内全部消息的并集**（含 st.rerun 前后被中止
    轮的元素），故 rerun 前旧元素也可能出现在断言集——写回结果一律以
    文件/词数为准（本文件主线），页面元素断言只做「在场性」。

本文件不动 src/app.py；src/dict_admin_pages.py 只在 R2 发现 bug 时修
（本轮实证修两处，见 _render_vocab_tab 段注释：质检 style.yaml 定位解耦
_VOCAB_PATH 落位、重建成功反馈改 ui_kit.flash——st.success+st.rerun
连用提示被 rerun 整体丢弃，违反本模块 RV12-2 纪律）。
"""

import sys
from pathlib import Path

import pytest

# 时序契约（tests/conftest.py 头注）：conftest 已先于本文件设定 env 并
# import tests.helpers 固定 src.* 加载时序；这里再 import 命中 sys.modules 缓存。
from tests import helpers  # noqa: F401
from tests.helpers import _goto, _new_at

import src.dict_admin_pages as dap  # noqa: E402
import src.style_check as style_check  # noqa: E402  (重建四函数 monkeypatch 面)

# fx23 口径的 admin 登录 mock（纯会话计算不触库；roles 与 legacy role 并集，
# _is_dict_admin 六角色纯函数放行 → 词表 tab 随词典管理区全 tab 渲染）
_ADMIN_SESSION = {
    "id": 1,
    "username": "admin",
    "display_name": "管理员",
    "role": "admin",
    "roles": ["dict_admin", "sys_admin"],
}

# 词表种子（fixture 预写 tmp 词表文件；质检 DEFINING_VOCAB pass 态不受其
# 影响——质检读 style.yaml 声明的 vocab_file（仓库权威词表），与本页增删
# 写回的 tmp 文件解耦，见 _render_vocab_tab 质检段注释）
_SEED_WORDS = ["alpha", "beta", "to"]


# ============================================
# fixture 与抓取 helper
# ============================================

@pytest.fixture
def vocab_file(tmp_path, monkeypatch):
    """把 _VOCAB_PATH 指到 tmp_path 预置种子词表，返回路径（真写回断言面）。"""
    vf = tmp_path / "defining_vocab.txt"
    vf.write_text(
        "# 定义词表（测试种子）\n"
        f"# 词条 {len(_SEED_WORDS)}\n"
        + "\n".join(_SEED_WORDS) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dap, "_VOCAB_PATH", vf)
    return vf


def _open_vocab_page():
    """AppTest 开词典管理区并 _goto 到词表 tab 所在页（fx23 式导航先例）。

    页内九 tab 全量渲染（st.tabs 服务端不分流），词表控件直接按 key 抓取。
    """
    at = _new_at()
    at.session_state["user"] = _ADMIN_SESSION
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    _goto(at, "dict_admin")
    assert not at.exception, [str(e.value) for e in at.exception]
    return at


def _by_key(elements, key):
    """按 widget key 现取现用（每轮新树重抓，见模块 docstring 时序注意）。"""
    hits = [el for el in elements if str(el.key) == key]
    assert hits, f"widget 不在场: {key}"
    return hits[0]


def _vocab_body(vf) -> list:
    """读 tmp 词表正文词条（去注释去空行——与 _vocab_read_words 同口径）。"""
    return [ln.strip() for ln in vf.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def _word_count_metric(at) -> int:
    """「当前词条数」指标卡现值（词表 tab 的词条数显示面）。"""
    hits = [m for m in at.metric if str(m.label) == "当前词条数"]
    assert hits, "「当前词条数」指标卡不在场"
    return int(hits[0].value)


def _vocab_dataframe(at):
    """词表 dataframe（'词条' 列）；整页唯一 dataframe 即它（实证）。"""
    hits = [d for d in at.dataframe
            if hasattr(d.value, "columns") and "词条" in list(d.value.columns)]
    assert hits, "词表 dataframe（'词条' 列）不在场"
    return hits[0]


# ============================================
# 1. 渲染冒烟（登录态 mock ＋ 质检状态区 ＋ dataframe 在场）
# ============================================

def test_vocab_tab_renders_with_dict_admin_mock(vocab_file):
    """登录态渲染不崩；词表 tab 在场；质检 DEFINING_VOCAB pass 态 success。"""
    at = _open_vocab_page()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert "📝 词表核定" in [str(t.label) for t in at.tabs], "词表 tab 不在场"
    # 质检状态区：style.yaml（仓库权威体例文件）+ 权威词表 → pass 态 success
    qc = [str(s.value) for s in at.success
          if "质检 DEFINING_VOCAB" in str(s.value)]
    assert qc and qc[0].startswith("质检 DEFINING_VOCAB：pass"), \
        f"质检状态区应 pass 态 success: {qc}"


def test_vocab_dataframe_and_metric_present(vocab_file):
    """词表 dataframe 在场（'词条' 列、行数=种子词数）＋ 指标卡同值。"""
    at = _open_vocab_page()
    assert not at.exception, [str(e.value) for e in at.exception]
    df = _vocab_dataframe(at).value
    assert list(df.columns) == ["词条"]
    assert len(df) == len(_SEED_WORDS), \
        f"dataframe 行数应=种子词数: {len(df)} != {len(_SEED_WORDS)}"
    assert _word_count_metric(at) == len(_SEED_WORDS)


def test_vocab_add_delete_widgets_present(vocab_file):
    """交互控件四件套在场：增词 text_area/按钮、删词 text_input/按钮。"""
    at = _open_vocab_page()
    assert not at.exception, [str(e.value) for e in at.exception]
    _by_key(at.text_area, "vocab_add")
    _by_key(at.button, "vocab_add_btn")
    _by_key(at.text_input, "vocab_del")
    _by_key(at.button, "vocab_del_btn")


# ============================================
# 2. 增词交互（真文件写回 ＋ 词条数 +N ＋ flash）
# ============================================

def test_vocab_add_two_words_writeback(vocab_file):
    """text_area 填两个新词（逗号分隔）→ 点按钮 → 写回 +2 ＋ flash 提示。"""
    at = _open_vocab_page()
    _by_key(at.text_area, "vocab_add").set_value("gamma, delta")
    _by_key(at.button, "vocab_add_btn").click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    # 真文件写回断言（monkeypatch 面上的 tmp 文件）
    body = _vocab_body(vocab_file)
    assert sorted(body) == sorted(_SEED_WORDS + ["gamma", "delta"]), body
    # rerun 后词条数 +2（指标卡与 dataframe 双面）
    assert _word_count_metric(at) == len(_SEED_WORDS) + 2
    assert len(_vocab_dataframe(at).value) == len(_SEED_WORDS) + 2
    # flash 提示（ui_kit 队列经 app.main 每轮 pop_and_render_flash 弹出）
    flash = [str(s.value) for s in at.success if "已增补" in str(s.value)]
    assert flash and "已增补 2 词" in flash[0], f"增词 flash 不在场: {flash}"


def test_vocab_add_multiline_filters_illegal_and_casefold_dedup(vocab_file):
    """换行/逗号混排＋大小写归一去重＋非法词过滤：'Delta, delta, go!' 只增 delta。"""
    at = _open_vocab_page()
    _by_key(at.text_area, "vocab_add").set_value("Delta, delta, go!")
    _by_key(at.button, "vocab_add_btn").click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    body = _vocab_body(vocab_file)
    # casefold 去重（Delta/delta 归一）＋ 非法词 'go!'（含非 [a-z']）被滤
    assert sorted(body) == sorted(_SEED_WORDS + ["delta"]), body
    flash = [str(s.value) for s in at.success if "已增补" in str(s.value)]
    assert flash and "已增补 1 词" in flash[0] and "跳过重复/非法 2" in flash[0]


# ============================================
# 3. 删词交互（写回 -1 ＋ casefold 命中 ＋ 不存在词/空输入 warning）
# ============================================

def test_vocab_delete_word_writeback(vocab_file):
    """text_input 填已有词 → 点按钮 → 写回 -1 ＋ flash 提示。"""
    at = _open_vocab_page()
    _by_key(at.text_input, "vocab_del").set_value("beta")
    _by_key(at.button, "vocab_del_btn").click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    body = _vocab_body(vocab_file)
    assert sorted(body) == sorted(w for w in _SEED_WORDS if w != "beta"), body
    assert _word_count_metric(at) == len(_SEED_WORDS) - 1
    flash = [str(s.value) for s in at.success if "已移除" in str(s.value)]
    assert flash and "已移除「beta」" in flash[0], f"删词 flash 不在场: {flash}"


def test_vocab_delete_casefold_variant_hit(vocab_file):
    """删词大小写不敏感：输入 'TO' 移除 'to'（casefold 同口径计重）。"""
    at = _open_vocab_page()
    _by_key(at.text_input, "vocab_del").set_value("TO")
    _by_key(at.button, "vocab_del_btn").click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    body = _vocab_body(vocab_file)
    assert "to" not in [w.casefold() for w in body], body
    flash = [str(s.value) for s in at.success if "已移除" in str(s.value)]
    assert flash and "已移除「to」" in flash[0]


def test_vocab_delete_missing_word_warns_without_crash(vocab_file):
    """删不存在词 → warning「不在词表中」不崩；文件与词数不变。"""
    at = _open_vocab_page()
    _by_key(at.text_input, "vocab_del").set_value("nosuchword")
    _by_key(at.button, "vocab_del_btn").click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    warns = [str(w.value) for w in at.warning if "不在词表中" in str(w.value)]
    assert warns, f"删不存在词应 warning: {[str(w.value) for w in at.warning]}"
    assert _vocab_body(vocab_file) == _SEED_WORDS, "删不存在词不得改文件"
    assert _word_count_metric(at) == len(_SEED_WORDS)


def test_vocab_delete_empty_input_warns_without_crash(vocab_file):
    """空输入点删词按钮 → warning（「或输入为空」分支）不崩、文件不变。"""
    at = _open_vocab_page()
    _by_key(at.text_input, "vocab_del").set_value("")
    _by_key(at.button, "vocab_del_btn").click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    warns = [str(w.value) for w in at.warning if "不在词表中" in str(w.value)]
    assert warns and "或输入为空" in warns[0]
    assert _vocab_body(vocab_file) == _SEED_WORDS


# ============================================
# 4. 重复词（加已存在词 → warning「跳过」不崩）
# ============================================

def test_vocab_add_existing_word_only_warns(vocab_file):
    """加已存在词（无新增）→ warning「无有效新增（…跳过）」不崩、文件不变。"""
    at = _open_vocab_page()
    _by_key(at.text_area, "vocab_add").set_value("alpha")
    _by_key(at.button, "vocab_add_btn").click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    warns = [str(w.value) for w in at.warning if "无有效新增" in str(w.value)]
    assert warns and "1 个重复/非法被跳过" in warns[0], \
        f"重复词应 warning 跳过: {warns}"
    assert _vocab_body(vocab_file) == _SEED_WORDS, "重复词不得写文件"
    assert _word_count_metric(at) == len(_SEED_WORDS)


# ============================================
# 5. 🔄 重建按钮（style_check 四函数 monkeypatch → success ＋ rerun；
#    语料空 → warning 且 write 不被调用）
# ============================================

class _FakeRebuild:
    """重建四函数桩：fetch→固定语料；count/build→真函数（纯统计无副作用）；
    write→落盘到注入路径并记录调用（页面 write_corpus_vocab_file 的落盘
    目标是 style_check 模块内硬编码 configs/defining_vocab.txt——不桩会写真
    仓库文件，故必须桩）。"""

    def __init__(self, texts, write_to):
        self.texts = texts
        self.write_to = write_to
        self.write_calls = []

    def fetch(self):
        return list(self.texts)

    def write(self, pairs):
        self.write_calls.append(pairs)
        self.write_to.write_text(
            "# rebuilt\n" + "\n".join(w for w, _ in pairs) + "\n",
            encoding="utf-8")
        return self.write_to


def test_vocab_rebuild_button_success_and_rerun(vocab_file, tmp_path,
                                                monkeypatch):
    """语料非空：四函数桩 → 点「🔄 重建词表初版」→ success flash ＋ 语料
    落盘断言（rerun 后页面仍不崩）。"""
    rebuilt = tmp_path / "rebuilt.txt"
    fake = _FakeRebuild(["the cat the", "the dog the"], rebuilt)
    monkeypatch.setattr(style_check, "fetch_corpus_definitions", fake.fetch)
    # count/build 用真函数（纯统计确定性）——先捕获原引用再包 passthrough
    # 桩（monkeypatch 后模块属性即桩，桩体内再取模块属性会自我递归）
    real_count = style_check.count_corpus_words
    real_build = style_check.build_corpus_vocab
    monkeypatch.setattr(style_check, "count_corpus_words",
                        lambda texts: real_count(texts))
    monkeypatch.setattr(style_check, "build_corpus_vocab",
                        lambda counter, min_freq=2: real_build(counter, min_freq))
    monkeypatch.setattr(style_check, "write_corpus_vocab_file", fake.write)

    at = _open_vocab_page()
    _by_key(at.button, "vocab_rebuild_btn").click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    # 落盘断言（桩 write 被调用且产物在注入路径）
    assert fake.write_calls, "重建写函数未被调用"
    assert rebuilt.exists() and "the" in rebuilt.read_text(encoding="utf-8")
    # success 反馈（RV12-2 修复后走 ui_kit.flash，rerun 后仍可见）
    flash = [str(s.value) for s in at.success if "已重建" in str(s.value)]
    assert flash and "已重建 1 词" in flash[0], f"重建 flash 不在场: {flash}"


def test_vocab_rebuild_empty_corpus_warns_and_skips_write(vocab_file,
                                                          tmp_path,
                                                          monkeypatch):
    """语料空：fetch 桩返回 [] → 点击 → warning「释义语料为空」不崩；
    write 不被调用（重建跳过）、词表文件不变。"""
    rebuilt = tmp_path / "rebuilt.txt"
    fake = _FakeRebuild([], rebuilt)
    monkeypatch.setattr(style_check, "fetch_corpus_definitions", fake.fetch)
    monkeypatch.setattr(style_check, "write_corpus_vocab_file", fake.write)

    at = _open_vocab_page()
    _by_key(at.button, "vocab_rebuild_btn").click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    warns = [str(w.value) for w in at.warning if "释义语料为空" in str(w.value)]
    assert warns, f"语料空应 warning: {[str(w.value) for w in at.warning]}"
    assert fake.write_calls == [], "语料空不得触发写回"
    assert not rebuilt.exists()
    assert _vocab_body(vocab_file) == _SEED_WORDS, "重建跳过不得动词表"


# ============================================
# 6. 纪律哨兵：重建成功反馈走 ui_kit.flash（RV12-2，本轮修复防回潮）
# ============================================

def test_vocab_rebuild_feedback_uses_flash_not_st_success():
    """RV12-2 纪律：重建成功反馈 ui_kit.flash ＋ st.rerun，不回潮 st.success
    （st.success 紧跟 st.rerun 提示被下一轮整体丢弃——R2 专项实证 bug）。
    注：质检状态区的 st.success（「质检 DEFINING_VOCAB：pass」）是**状态
    展示**而非动作反馈、且不在 rerun 路径上，不属本纪律管辖，故本哨兵只
    钉重建反馈的形态（'已重建' 文案必须经 ui_kit.flash）。"""
    import inspect

    src = inspect.getsource(dap._render_vocab_tab)
    assert 'ui_kit.flash(f"已重建' in src, \
        "重建成功反馈必须走 ui_kit.flash（rerun 不丢）"
    assert 'st.success(f"已重建' not in src, \
        "重建成功反馈不得用 st.success（rerun 即丢）"


def test_vocab_style_yaml_locator_decoupled_from_vocab_path(tmp_path,
                                                            monkeypatch):
    """质检 style.yaml 定位独立于 _VOCAB_PATH 落位：词表 txt monkeypatch 到
    tmp 后，_vocab_style_yaml_path 仍定位到仓库权威 style.yaml（本轮修复——
    旧实现取 _VOCAB_PATH.parent/style.yaml，词表重定位即误报「暂不可读」）。"""
    relocated = tmp_path / "elsewhere" / "defining_vocab.txt"
    relocated.parent.mkdir(exist_ok=True)
    relocated.write_text("alpha\n", encoding="utf-8")
    monkeypatch.setattr(dap, "_VOCAB_PATH", relocated)
    found = dap._vocab_style_yaml_path()
    assert found is not None and found.is_file()
    assert found.name == "style.yaml" and "configs" in str(found)
