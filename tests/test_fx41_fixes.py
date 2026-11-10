"""批次 20 挂账项消费测试（FX-41）：范畴下拉跨页消费 ui.default_category。

FX-37 造偏好读写 UI、FX-38 接 app.py 语料页行数（ui.rows_per_page）；
本批把 ui.default_category 接到四处范畴下拉（五处 selectbox 实例，
批次 20 挂账项收口）：

  * src/semantic_search.py   ss_category（以句搜义页）
  * src/cluster_analysis.py  ca_category（语义分析页谱系侧）
  * src/template_engine.py   cat_code（释义模板引擎页，原无 index 参数，
                              本批补 index，format_func 口径保持）
  * src/dict_admin_pages.py  dict_admin_cockpit_category（驾驶舱进度漏斗）
                              ＋ dict_admin_style_check_category（体例质检）

接线纪律（本文件逐处验收）：

  * 三态：偏好命中选项集 → selectbox 首建 index 指向偏好范畴；偏好不在
    选项集（脏值）→ 回退原默认（ss/ca 回 motion，其余回首项），不崩；
    未登录（真身 get_pref fail-closed：AppTest 会话无 user，uid 解析
    早退不触库）→ 原默认不变；
  * ImportError（sys.modules 置 None 模拟并行读面未落）→ 原默认，不崩；
  * widget key 不变（按 key 定位即锁 key；te 页无 key 照旧按位定位）；
    index 只作用于首次实例化 —— 首建后用户手选经 rerun 不被偏好劫持
    （Streamlit session_state 接管，逐处演示一次）。

打桩口径：get_pref 桩设在 src.user_context_db 源模块（消费点为函数内
from-import，每次渲染重取模块属性即命中桩），桩记录入参键锁接线键；
页面自身依赖照既有冒烟先例打桩（ca._load_page_data / category_study
就绪面与范畴行 / te.derive_cluster_schemas / dict_admin _current_user
角色门），其余降级路径走真身。偏好命中态用 speech 区分 motion 原默认
（configs/ 实际两包 motion/speech，motion 为各处原默认）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import category_study  # noqa: E402  （te 页就绪面/范畴行桩位）
from src import cluster_analysis as ca  # noqa: E402  （ca 页取数桩位）
from src import dict_admin_pages as dp  # noqa: E402  （体例质检角色门桩位）
from src import template_engine as te  # noqa: E402  （te 页聚类取数桩位）
from src import template_revision_db  # noqa: E402  （te 页建表面桩位）
from src import user_context_db  # noqa: E402  （get_pref 桩位）

PREF_KEY = "ui.default_category"


# ============================================
# 桩体
# ============================================

def _stub_pref(monkeypatch, value):
    """get_pref 桩：恒返 value，并记录入参键（锁「读的是 ui.default_category」）。"""
    calls = []

    def fake_get_pref(key, default=None):
        calls.append(key)
        return value

    monkeypatch.setattr(user_context_db, "get_pref", fake_get_pref)
    return calls


def _block_ucdb(monkeypatch):
    """sys.modules 置 None → 函数内 from-import 抛 ImportError（并行读面未落）。"""
    monkeypatch.setitem(sys.modules, "src.user_context_db", None)


# te 页范畴行（get_categories 桩；行键与真身同构，format_func 只用 code/name_cn）
_TE_CATEGORIES = [
    {"id": 1, "code": "motion", "name_cn": "动作", "name_en": "motion",
     "status": "active", "notes": None},
    {"id": 2, "code": "speech", "name_cn": "言语", "name_en": "speech",
     "status": "active", "notes": None},
]


# ============================================
# 页面脚本（AppTest.from_string：页面函数依赖模块级全局，同既有冒烟先例）
# ============================================

SS_SCRIPT = (
    "from src import semantic_search as ss\n"
    "ss.render_semantic_search_page()\n"
)
CA_SCRIPT = (
    "from src import cluster_analysis as ca\n"
    "ca.render_semantic_analysis_page()\n"
)
TE_SCRIPT = (
    "from src import template_engine as te\n"
    "te.render_template_page()\n"
)
COCKPIT_SCRIPT = (
    "from src import dict_admin_pages as dp\n"
    "dp._render_cockpit_tab()\n"
)
STYLE_CHECK_SCRIPT = (
    "from src import dict_admin_pages as dp\n"
    "dp._render_style_check_section()\n"
)


def _stub_ca_page(monkeypatch) -> None:
    """ca 页谱系侧取数桩（真身触库；既有页面冒烟同款，其余降级走真身）。"""
    monkeypatch.setattr(
        ca, "_load_page_data",
        lambda _scope, _cat, _lang: {"ranking": [], "dendro": {},
                                     "scipy_missing": False})


def _stub_te_page(monkeypatch) -> None:
    """te 页：就绪面 True ＋ 两范畴行 ＋ 聚类运行空（页面恰在下拉后收口）
    ＋ 修订建表面 no-op —— 范畴下拉成为页内唯一 selectbox（按位定位）。"""
    monkeypatch.setattr(category_study, "category_study_ready",
                        lambda code=None: True)
    monkeypatch.setattr(category_study, "get_categories",
                        lambda: _TE_CATEGORIES)
    monkeypatch.setattr(template_revision_db,
                        "ensure_template_revision_tables", lambda: None)
    monkeypatch.setattr(te, "derive_cluster_schemas", lambda _cat, _lang: [])


def _stub_style_check_gate(monkeypatch) -> None:
    """体例质检段角色门：词典管理员登录桩（dp._current_user 页面门 ——
    ucdb 会话仍是 AppTest 无登录态，未登录态 get_pref 测试不受影响）。"""
    monkeypatch.setattr(
        dp, "_current_user",
        lambda: {"id": 1, "username": "fx41", "role": "admin"})


# ============================================
# 1. ss_category（以句搜义页）
# ============================================

class TestSsCategoryPref:
    """ss_category：偏好命中 index 指向偏好范畴 / 不在选项集回退 motion /
    未登录回退 / ImportError 回退 / 首建后手选不被劫持。"""

    key = "ss_category"

    def _run(self, monkeypatch, pref):
        calls = _stub_pref(monkeypatch, pref)
        at = AppTest.from_string(SS_SCRIPT, default_timeout=30)
        at.run()
        return at, calls

    def test_pref_hit_selects_saved_category(self, monkeypatch):
        at, calls = self._run(monkeypatch, "speech")
        assert not at.exception
        assert calls == [PREF_KEY]  # 接线键锁：读的就是 ui.default_category
        assert at.selectbox(key=self.key).value == "speech"
        assert at.selectbox(key=self.key).index == 1

    def test_pref_not_in_options_falls_back_to_motion(self, monkeypatch):
        at, _ = self._run(monkeypatch, "nosuchcat")
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"

    def test_no_pref_not_logged_in_falls_back_to_motion(self, monkeypatch):
        """未登录（AppTest 会话无 user）：真身 get_pref fail-closed 返 None
        → 原 motion 默认（uid 解析早退，不触库）。"""
        at = AppTest.from_string(SS_SCRIPT, default_timeout=30)
        at.run()
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"

    def test_import_error_falls_back_to_motion(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "src.user_context_db", None)
        at = AppTest.from_string(SS_SCRIPT, default_timeout=30)
        at.run()
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"

    def test_user_choice_survives_rerun(self, monkeypatch):
        """index 只作用于首次实例化：首建指向偏好后，用户手选经 rerun
        不被偏好劫持（session_state 接管）。"""
        at, _ = self._run(monkeypatch, "speech")
        at.selectbox(key=self.key).set_value("motion")  # 用户手选
        at.run()
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"


# ============================================
# 2. ca_category（语义分析页谱系侧）
# ============================================

class TestCaCategoryPref:
    """ca_category：同 ss 四态＋手选保持（回退默认同为 motion）。"""

    key = "ca_category"

    def _run(self, monkeypatch, pref):
        calls = _stub_pref(monkeypatch, pref)
        _stub_ca_page(monkeypatch)
        at = AppTest.from_string(CA_SCRIPT, default_timeout=60)
        at.run()
        return at, calls

    def test_pref_hit_selects_saved_category(self, monkeypatch):
        at, calls = self._run(monkeypatch, "speech")
        assert not at.exception
        assert calls == [PREF_KEY]
        assert at.selectbox(key=self.key).value == "speech"
        assert at.selectbox(key=self.key).index == 1

    def test_pref_not_in_options_falls_back_to_motion(self, monkeypatch):
        at, _ = self._run(monkeypatch, "nosuchcat")
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"

    def test_no_pref_not_logged_in_falls_back_to_motion(self, monkeypatch):
        _stub_ca_page(monkeypatch)
        at = AppTest.from_string(CA_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"

    def test_import_error_falls_back_to_motion(self, monkeypatch):
        _stub_ca_page(monkeypatch)
        monkeypatch.setitem(sys.modules, "src.user_context_db", None)
        at = AppTest.from_string(CA_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"

    def test_user_choice_survives_rerun(self, monkeypatch):
        at, _ = self._run(monkeypatch, "speech")
        at.selectbox(key=self.key).set_value("motion")
        at.run()
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"


# ============================================
# 3. cat_code（释义模板引擎页）
# ============================================

class TestTemplateCatCodePref:
    """cat_code（原无 index 参数，本批补 index；回退默认＝首项 motion）：
    四态＋手选保持；format_func 口径保持（桩范畴行 name_cn 供标签拼装）。"""

    def _run(self, monkeypatch, pref):
        calls = _stub_pref(monkeypatch, pref)
        _stub_te_page(monkeypatch)
        at = AppTest.from_string(TE_SCRIPT, default_timeout=60)
        at.run()
        return at, calls

    def _cat(self, at: AppTest):
        return at.selectbox[0]  # 桩口径下页内唯一 selectbox（本下拉无 key 照旧）

    def test_pref_hit_selects_saved_category(self, monkeypatch):
        at, calls = self._run(monkeypatch, "speech")
        assert not at.exception
        assert calls == [PREF_KEY]
        assert self._cat(at).value == "speech"
        assert self._cat(at).index == 1

    def test_pref_not_in_options_falls_back_to_first(self, monkeypatch):
        at, _ = self._run(monkeypatch, "nosuchcat")
        assert not at.exception
        assert self._cat(at).value == "motion"

    def test_no_pref_not_logged_in_falls_back_to_first(self, monkeypatch):
        _stub_te_page(monkeypatch)
        at = AppTest.from_string(TE_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        assert self._cat(at).value == "motion"

    def test_import_error_falls_back_to_first(self, monkeypatch):
        _stub_te_page(monkeypatch)
        monkeypatch.setitem(sys.modules, "src.user_context_db", None)
        at = AppTest.from_string(TE_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        assert self._cat(at).value == "motion"

    def test_user_choice_survives_rerun(self, monkeypatch):
        at, _ = self._run(monkeypatch, "speech")
        self._cat(at).set_value("motion")
        at.run()
        assert not at.exception
        assert self._cat(at).value == "motion"


# ============================================
# 4. dict_admin_cockpit_category（驾驶舱进度漏斗）
# ============================================

class TestCockpitCategoryPref:
    """漏斗范畴下拉（同源 _funnel_category_options）：四态＋手选保持。"""

    key = "dict_admin_cockpit_category"

    def _run(self, monkeypatch, pref):
        calls = _stub_pref(monkeypatch, pref)
        at = AppTest.from_string(COCKPIT_SCRIPT, default_timeout=60)
        at.run()
        return at, calls

    def test_pref_hit_selects_saved_category(self, monkeypatch):
        at, calls = self._run(monkeypatch, "speech")
        assert not at.exception
        assert calls == [PREF_KEY]
        assert at.selectbox(key=self.key).value == "speech"
        assert at.selectbox(key=self.key).index == 1

    def test_pref_not_in_options_falls_back_to_first(self, monkeypatch):
        at, _ = self._run(monkeypatch, "nosuchcat")
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"

    def test_no_pref_not_logged_in_falls_back_to_first(self, monkeypatch):
        at = AppTest.from_string(COCKPIT_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"

    def test_import_error_falls_back_to_first(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "src.user_context_db", None)
        at = AppTest.from_string(COCKPIT_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"

    def test_user_choice_survives_rerun(self, monkeypatch):
        at, _ = self._run(monkeypatch, "speech")
        at.selectbox(key=self.key).set_value("motion")
        at.run()
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"


# ============================================
# 5. dict_admin_style_check_category（体例质检段）
# ============================================

class TestStyleCheckCategoryPref:
    """质检范畴下拉（_funnel_category_options 同源）：四态＋手选保持；
    角色门走登录桩（页面门），ucdb 会话仍无登录 → 未登录态真身 get_pref
    fail-closed 路径不受桩影响。"""

    key = "dict_admin_style_check_category"

    def _run(self, monkeypatch, pref):
        calls = _stub_pref(monkeypatch, pref)
        _stub_style_check_gate(monkeypatch)
        at = AppTest.from_string(STYLE_CHECK_SCRIPT, default_timeout=60)
        at.run()
        return at, calls

    def test_pref_hit_selects_saved_category(self, monkeypatch):
        at, calls = self._run(monkeypatch, "speech")
        assert not at.exception
        assert calls == [PREF_KEY]
        assert at.selectbox(key=self.key).value == "speech"
        assert at.selectbox(key=self.key).index == 1

    def test_pref_not_in_options_falls_back_to_first(self, monkeypatch):
        at, _ = self._run(monkeypatch, "nosuchcat")
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"

    def test_no_pref_not_logged_in_falls_back_to_first(self, monkeypatch):
        _stub_style_check_gate(monkeypatch)
        at = AppTest.from_string(STYLE_CHECK_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"

    def test_import_error_falls_back_to_first(self, monkeypatch):
        _stub_style_check_gate(monkeypatch)
        monkeypatch.setitem(sys.modules, "src.user_context_db", None)
        at = AppTest.from_string(STYLE_CHECK_SCRIPT, default_timeout=60)
        at.run()
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"

    def test_user_choice_survives_rerun(self, monkeypatch):
        at, _ = self._run(monkeypatch, "speech")
        at.selectbox(key=self.key).set_value("motion")
        at.run()
        assert not at.exception
        assert at.selectbox(key=self.key).value == "motion"
