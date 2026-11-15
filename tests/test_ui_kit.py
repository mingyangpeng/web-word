"""ui_kit flash 队列单测：pop_and_render_flash 三路兜底分支（review 补欠）。

背景（review finding）：src/ui_kit.py 的 pop_and_render_flash 有三路
「队列损坏/脏元素」兜底 —— ①队列非 list 按空队列返回；②元素非 dict 跳过；
③空 message 跳过 —— 加上 level 未知取值回落 st.success 的保守兜底，
此前零覆盖（既有测试只锁 flash 写队列面与 AppTest 正常弹出面，坏态从不
构造）。本文件照 tests/test_fx26_fixes.py 的 st 打桩口径（_StubSt 记录器
＋monkeypatch），用 monkeypatch 直写实际队列载体（st.session_state 的
_FLASH_QUEUE_KEY = "_ui_kit_flash_queue" 键）构造坏态，钉住「提示机制
永不带崩页面」契约：

  * ①空队列（队列键不出场）→ 不渲染不落键；
  * ②正常 flash → 渲染后队列即清空，二轮不重复（消费即弃）；
  * ③队列非 list（脏字符串/数值/None）→ 自愈不崩、键被弹出；
  * ④元素非 dict 混入 → 脏项跳过，合法项照常渲染；
  * ⑤空 message（空串/None/键缺席）→ 跳过不渲染；
  * ⑥level 未知/空值 → 按 success 渲染（docstring「宁可展示也不静默
    丢弃」口径：未知取值走 st.success 兜底，空值归一 success）。

打桩口径注记：_LEVEL_RENDERERS 在模块 import 时即绑死真 streamlit 渲染
函数 —— 只换 ui_kit.st 不够（.get(level, st.success) 的兜底默认值才是从
模块 st 现取），fixture 里连 _LEVEL_RENDERERS 一并换桩。桩 st 自带 dict
形 session_state：ui_kit 对它的全部用法是 .get / []= / .pop(key, default)
三面，dict 语义完全等价 —— 全程不触真 streamlit bare 会话，天然无跨用例
残留。
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest  # noqa: E402

from src import ui_kit  # noqa: E402

# ============================================
# st 假体（fx26 _StubSt 最小同面：输出族记录器 ＋ dict 形 session_state）
# ============================================


class _StubSt:
    """ui_kit 所需的 st 最小假体。

    渲染调用按 (kind, text) 记进 messages 供逐条断言；session_state 用
    真 dict（ui_kit 只用 get / []= / .pop(key, default) 三面）。
    """

    def __init__(self):
        self.session_state = {}
        self.messages = []       # (kind, text)

    def _record(self, kind, *args, **kwargs):
        self.messages.append((kind, args[0] if args else ""))

    def success(self, *args, **kwargs):
        self._record("success", *args, **kwargs)

    def error(self, *args, **kwargs):
        self._record("error", *args, **kwargs)

    def warning(self, *args, **kwargs):
        self._record("warning", *args, **kwargs)

    def info(self, *args, **kwargs):
        self._record("info", *args, **kwargs)


@pytest.fixture
def stub_st(monkeypatch):
    """桩 st 注入 ui_kit ＋ _LEVEL_RENDERERS 一并换桩。

    只 monkeypatch ui_kit.st 覆盖不到 _LEVEL_RENDERERS 的 import 时绑定，
    须连渲染表一起换 —— 否则正常分支会打到真 streamlit 渲染函数。
    """
    stub = _StubSt()
    monkeypatch.setattr(ui_kit, "st", stub)
    monkeypatch.setattr(ui_kit, "_LEVEL_RENDERERS", {
        "success": stub.success,
        "error": stub.error,
        "warning": stub.warning,
        "info": stub.info,
    })
    return stub


# ============================================
# ①② 正常面：空队列 / 正常 flash 消费即清空
# ============================================

def test_empty_queue_renders_nothing(stub_st):
    """①空队列（队列键不出场）→ 不渲染、不落键（返回即弃）。"""
    ui_kit.pop_and_render_flash()
    assert stub_st.messages == []
    assert ui_kit._FLASH_QUEUE_KEY not in stub_st.session_state


def test_normal_flash_renders_then_queue_cleared(stub_st):
    """②正常 flash → 按入队序渲染（level 对号入座），渲染后队列清空；
    二轮渲染不再弹出（消费即弃、不跨轮重复 —— RV12-2 rerun 口径的核心）。"""
    ui_kit.flash("收录成功")
    ui_kit.flash("保存失败", level="error")
    queue = stub_st.session_state[ui_kit._FLASH_QUEUE_KEY]
    assert [item["message"] for item in queue] == ["收录成功", "保存失败"]

    ui_kit.pop_and_render_flash()
    assert stub_st.messages == [("success", "收录成功"), ("error", "保存失败")]
    assert ui_kit._FLASH_QUEUE_KEY not in stub_st.session_state

    stub_st.messages.clear()
    ui_kit.pop_and_render_flash()          # 二轮渲染：队列已消费，零渲染
    assert stub_st.messages == []


# ============================================
# ③④⑤ 三路兜底：队列非 list / 元素非 dict / 空 message
# ============================================

@pytest.mark.parametrize("bad_queue", ["脏字符串队列", 42, None],
                         ids=["str", "int", "none"])
def test_non_list_queue_self_heals(stub_st, bad_queue):
    """③队列非 list（历史脏态/串改会话）→ 按空队列自愈：不渲染不崩，
    且队列键已被 pop 弹出（下轮 flash 从空队列重建，坏态不留根）。"""
    stub_st.session_state[ui_kit._FLASH_QUEUE_KEY] = bad_queue
    ui_kit.pop_and_render_flash()
    assert stub_st.messages == []
    assert ui_kit._FLASH_QUEUE_KEY not in stub_st.session_state


def test_non_dict_element_skipped(stub_st):
    """④元素非 dict（字符串/数值/None/列表混入）→ 脏项跳过，合法项照常
    渲染 —— 不会因单个脏元素带崩整条提示链。"""
    stub_st.session_state[ui_kit._FLASH_QUEUE_KEY] = [
        "裸字符串", 42, None, ["list 形态的脏项"],
        {"level": "warning", "message": "合法提示"},
    ]
    ui_kit.pop_and_render_flash()
    assert stub_st.messages == [("warning", "合法提示")]


@pytest.mark.parametrize(
    "bad_item",
    [{"level": "success", "message": ""},   # message 空串
     {"level": "error", "message": None},   # message None
     {"level": "info"}],                    # message 键缺席
    ids=["empty-str", "none", "missing-key"])
def test_empty_message_skipped(stub_st, bad_item):
    """⑤空 message（空串/None/键缺席）→ 跳过不渲染，合法项不受牵连。"""
    good = {"level": "error", "message": "真正的提示"}
    stub_st.session_state[ui_kit._FLASH_QUEUE_KEY] = [bad_item, good]
    ui_kit.pop_and_render_flash()
    assert stub_st.messages == [("error", "真正的提示")]


# ============================================
# ⑥ level 兜底：未知取值 / 空值 → success 渲染
# ============================================

def test_unknown_or_empty_level_falls_back_to_success(stub_st):
    """⑥level 未知取值 → .get 兜底走模块 st.success（本桩口径下即桩
    success）渲染；level 空值/None → or 归一 success 同表渲染 —— 两条
    路径都守住「提示宁可展示也不静默丢弃」的保守口径。"""
    stub_st.session_state[ui_kit._FLASH_QUEUE_KEY] = [
        {"level": "mystery", "message": "未知等级提示"},   # 表外键 → st.success 兜底
        {"level": "", "message": "空等级提示"},            # or 归一 success → 表内命中
        {"message": "无等级提示"},                         # 键缺席 → or 归一 success
    ]
    ui_kit.pop_and_render_flash()
    assert stub_st.messages == [("success", "未知等级提示"),
                                ("success", "空等级提示"),
                                ("success", "无等级提示")]
