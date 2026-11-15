"""tests 共享 helper —— review P3 收敛落点（唯一权威实现）。

此前下列 helper 在各测试文件里各复制一份、随批次各自演化出语义漂移：
  _new_at ×9（default_timeout 出现 120/180 两派）、_pget ×6、_form_login ×5、
  _goto ×3（fx29/review_r18 直扫 sidebar.button 不滤 PAGE_KEYS，fx23 先滤）、
  _nav_buttons ×2、_radio_keys ×2、_nav_click ×1、requires_db skipif 判据 ×3
  （探针手法各异：get_db_cursor 真查 / pymysql 裸连 / 包装层 get_db_cursor）。
本模块统一口径后供各文件显式 import（pytest 惯例：conftest 里的普通函数
不会自动注入测试模块，故各文件 `from tests.helpers import ...`）。

统一裁决（收敛时的语义基线，均有依据）：
  * _new_at：default_timeout 统一 180（fx51/fx35 原为 120 —— 超时只是等待
    上限，取长不改任何断言语义；180 与 fx23/integration/fx29/r18/r1 共识）；
  * _goto / _nav_click：统一 fx23 口径 —— 先以 page_label(PAGE_KEYS) 标签集
    滤出导航按钮，再点 label == page_label(key) 的那颗。fx29/review_r18 原实现
    直扫 at.sidebar.button 不滤 PAGE_KEYS，对页键参数两者严格等价（page_label
    值均带 emoji 前缀，「登录/退出」等非导航按钮标签不可能与页名重合，
    见 src/page_guides.PAGE_GUIDES），其调用点全部传页键，无「故意允许任意
    label 按钮」的依赖，故不强留本地实现；
  * requires_db：统一「src.mysql_db.get_db_cursor 真连配置库 SELECT 1」探针
    （原 fx3_perf 只探 TCP 连接不选库 —— 统一为库面可用性：库不可用时宁可
    skip 也不裸跑假失败）。

时序契约（tests/conftest.py 头注）：本模块的 `src.*` import 必须发生在
conftest 的 env 设定之后 —— 由 conftest 在 env 块之后 `from tests import
helpers` 保证（pytest 先于一切测试模块导入 conftest）；各测试文件再 import
本模块时命中 sys.modules 缓存，src 依赖不会以错误时序重复执行。
"""

import os

import pytest

from src.page_guides import PAGE_KEYS, page_label

# app.py 绝对路径（各文件原 APP 常量同值：仓库根/src/app.py）
APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "src", "app.py")


def _new_at(default_timeout: int = 180):
    """新开 AppTest 会话加载 src/app.py（超时共识 180s，见模块 docstring）。"""
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(APP, default_timeout=default_timeout)


def _pget(at, key, default=None):
    """AppTest 会话读取（SafeSessionState 不支持 .get()，异常路径回退默认值）。"""
    try:
        return at.session_state[key]
    except Exception:  # noqa: BLE001
        return default


def _form_login(at, username: str, password: str):
    """侧边栏登录表单真实提交（填账号密码 → 点「登录」提交按钮 → rerun）。

    与 test_integration_apptest / fx29 / review_r18 既有手法逐行一致（真实
    登录流：verify_login_full → 会话四键+roles 就位），不走 session 注入捷径。
    """
    inputs = {t.key: t for t in at.sidebar.text_input}
    inputs["login_username"].set_value(username)
    inputs["login_password"].set_value(password)
    submit = [b for b in at.sidebar.button
              if b.form_id and "登录" in str(b.label)]
    assert submit, "登录提交按钮未找到"
    submit[0].click()
    at.run()
    return at


def _nav_buttons(at) -> list:
    """侧边栏导航按钮（批次 22 按钮式侧边栏；label=page_label，按渲染序即七区序）。

    导航按钮在 st.sidebar.container(key="ls_nav") 内渲染，与登录/退出/热门动词
    等非导航按钮以 PAGE_KEYS 的 page_label 标签集区分。
    """
    return [b for b in at.sidebar.button
            if str(b.label) in {page_label(k) for k in PAGE_KEYS}]


def _radio_keys(at) -> list:
    """侧边栏可见页键（导航按钮按七区序还原；函数名保留 radio 时代调用面）。"""
    label2key = {page_label(k): k for k in PAGE_KEYS}
    return [label2key[str(b.label)] for b in _nav_buttons(at)
            if str(b.label) in label2key]


def _goto(at, key: str):
    """点导航按钮切页（on_click 回调写 session_state["page"] 后 rerun）。

    fx23 口径：只在导航按钮集合里找（label ∈ page_label(PAGE_KEYS)），
    找不到即 AssertionError —— 绝不点页名集之外的任意按钮。
    """
    for b in _nav_buttons(at):
        if str(b.label) == page_label(key):
            b.click()
            at.run()
            return
    raise AssertionError(f"导航按钮不存在: {key}")


# test_integration_apptest 历史命名，语义与 _goto 完全一致 —— 别名保留调用面
_nav_click = _goto


def _db_available() -> bool:
    """MySQL 库面可用性探针：真连配置库跑 SELECT 1（只读、无写操作）。"""
    try:
        from src.mysql_db import get_db_cursor
        with get_db_cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


# 数据库用例统一 skipif 门（import 时评估一次；MySQL 不可用/配置库缺失 → skip）。
# review_r18 / review_regression 的 requires_db 走 HAS_MYSQL 常量＋个性化 reason
# （提示各自的专用测试库名），语义等价，按原样保留不强收。
requires_db = pytest.mark.skipif(
    not _db_available(), reason="MySQL 不可用，跳过数据库真连用例")
