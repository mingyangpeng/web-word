# S3 Review · 集成回归审查（AppTest 全角色矩阵 + 降级 + 空表 + 全量回归）

> 审查对象：三新页（cluster/template/semantic）在 `src/app.py` 的集成面 ——
> `_PAGE_ACCESS` 角色可见性、main() 分派登录门、各页 DB_AVAILABLE=False 降级、
> 空表（cs_* / 业务表为空）行为；测试载体 `tests/test_integration_apptest.py`
> （真实登录表单 + 独立空测试库 web_word_users_test）。
> 审查方法：逐页读码核对（app.py 分派/入口/过滤 × 三模块渲染函数 × 数据层
> 降级分支）+ AppTest 实测 + 全量 pytest。与 S1（功能+安全）、S2（数据正确性）
> 不重复：S3 只看「集成与回归」，不再复算数学、不再审输入校验实现。
>
> **结论：清单五项全部核验通过；三新页 × 五角色矩阵、断库降级、空库降级的
> 用例在 8623798 已就位（S3 起点即覆盖，逐条确认通过）；发现并补齐 1 处
> 用例缺口（既有页 category/graph/domain 从未在空库下渲染过）+ 1 处静态锁
> （_PAGE_ACCESS 键/角色防拼写漂移）。修复后全量 `python3 -m pytest tests/ -q`
> = **610 passed** 全绿（608 基线 + 本次新增 2 用例）。**

## 0. 测试基线核对

- 审查起点实测：`MYSQL_HOST=127.0.0.1 python3 -m pytest tests/ -q` = **608 passed**
  （与 S1/S2 收官一致，未漂移）；其中 `tests/test_integration_apptest.py` 单模块
  24 passed（含 TestS3NewPagesMatrix 五会话矩阵与 TestDbUnavailableDegrade 三新页
  断库降级 —— 均随 8623798 入库，S3 逐条复跑确认）。
- MySQL 以 `MYSQL_HOST=127.0.0.1` 连接（默认主机名 `mysql` 不可解析，S1/S2 同款惯例）。

## 1. 清单逐项核验

### 1.1 AppTest 全角色矩阵（三新页 × 5 角色）—— 通过（已在库，逐条复跑）

`TestS3NewPagesMatrix`（tests/test_integration_apptest.py:397 起）逐格实测：

| 页面 \ 角色 | 未登录 | viewer | annotator | reviewer | admin |
|---|---|---|---|---|---|
| cluster 🧬 | 拦截+隐藏 | 可见可渲染 | 可见可渲染 | 可见可渲染 | 可见可渲染 |
| template 🧩 | 拦截+隐藏 | 可见可渲染 | 可见可渲染 | 可见可渲染 | 可见可渲染 |
| semantic 🧠 | 拦截+隐藏 | 可见可渲染 | 可见可渲染 | 可见可渲染 | 可见可渲染 |

- 未登录（`test_unlogged_new_pages_blocked_and_hidden`）：三页 session 直入均被
  「请先登录」warning 拦下，页面本体标题/使用说明 expander 不渲染（无内容泄漏），
  侧边栏 radio 无三页入口。
- 四个登录角色（`_login_and_assert_new_pages` 真实表单登录后逐页）：三页 radio
  可见 + 使用说明 + 页面本体 + 空库降级哨兵在场、无 error 通道；admin 另断
  radio == 全部 12 键且保持 PAGE_KEYS 原序；viewer 另回锚「受保护三页仍不可见」
  （防新页改表时误放开旧页）。
- 无越权判定：三新页设计即「需登录、全角色可见」（app.py:201-203），唯一隐藏面
  是未登录 —— 两条到达路径（radio 点击 / 残留会话直入）均被 require_login 门
  拦下；越权面无豁口。
- semantic 另有带查询用例（`test_semantic_page_query_flow_empty_db`）：规则层解析
  chips（离线可用）+ 最近邻空库 info 降级。

### 1.2 _PAGE_ACCESS 语义与页面注册一致 —— 通过（补 1 处静态锁）

逐一核对（PAGE_KEYS 12 键 × main() 分派 × _PAGE_ACCESS，src/app.py:197-218/2843-2875）：

| 页面 | _PAGE_ACCESS | 侧边栏可见 | 分派登录门 | 页内 role gate |
|---|---|---|---|---|
| search/graph/corpus/domain/category | 无键（基础页） | 全员含未登录 | 无 | 无（只读） |
| annotate | 无键（基础页） | 全员含未登录 | require_login | 标注页内部（viewer 拦 / admin 快速通道） |
| submission | admin/reviewer/annotator | 登录且角色相符 | require_login | 入口内（viewer 直入被「无权限」拦） |
| users_admin | admin | 仅 admin | require_login | 入口内（「仅管理员可用」） |
| reliability | admin/reviewer | 仅此两角色 | require_login | 入口内（「reviewer / admin」） |
| cluster/template/semantic | 四个登录角色 | 登录即见 | require_login | 无需（全角色授权） |

- 键集恰为 6 个非基础页，无遗漏、无陈旧键；main() 的 11 个 elif + else(search)
  恰好覆盖 12 键，与 `test_page_keys_match_app_pages`（PAGE_KEYS == APP_PAGES == 12）
  互证。角色映射无拼写漂移、无空元组。
- **新增静态锁**（本次修复②）：`test_page_access_table_consistent_with_registration`
  钉死「键 == 六个非基础页、角色 ⊆ 规范 §1 四角色、元组非空」—— 行为矩阵用例
  钉得住「在场角色可见」，钉不住「陈旧键/拼错角色」这类静默失效，此锁补位。

### 1.3 DB_AVAILABLE=False 降级 —— 通过

`TestDbUnavailableDegrade.db_down`（monkeypatch MYSQL_PORT → 必然拒绝连接的端口）：

| 页面 | 断库行为 | 断言 |
|---|---|---|
| cluster | `get_categories`/查 runs 降级空 → info「暂无聚类运行数据」 | 不抛异常、无 error；用例先清 `ca._load_page_data` 缓存真跑断库路径 |
| template | `category_study_ready()` 异常→False → info「范畴深挖数据尚未灌入」 | 不抛异常、无 error |
| semantic | 空查询引导 info；带查询**规则层照常解析**（离线可用）+ 索引装载降级 info「暂无义位数据」 | 不抛异常、无 error；查询框照常渲染 |

- 同类既有用例（登录框/标注/提交流/用户管理/信度页断库降级）一并复跑通过；
  登录门不依赖库状态（断库下未登录进受保护页仍被「请先登录」拦截）。

### 1.4 空表不崩溃 —— 通过（补 1 处既有页缺口）

- 三新页：空测试库（cs_* 表不存在/为空、categories 无表）下逐页渲染的哨兵断言
  已由 TestS3NewPagesMatrix 固化（同 §1.1），不抛异常、走 info 引导。
- **缺口（本次修复①）**：既有页 category/graph/domain 从未在空库下渲染过
  （test_pages/test_page_guides 均连真实业务库；apptest 空库只渲染过
  search/corpus/annotate 与受保护页）。新增
  `TestS3EmptyDbExistingPages::test_existing_pages_empty_db_graceful`：
  category（categories 表缺失 → `category_study_ready` 捕获 → info「范畴深挖数据
  尚未灌入」）、graph（word_relations 空 → info「暂无词间关系数据」）、
  domain（domain_family_senses 空 → info「域系初判数据尚未灌入」）三页
  空库直入：不抛异常、无 error 通道。至此 12 页全部有空库不崩溃覆盖。
- 读码核对佐证：三页数据层函数全部 try/except 降级（category_study.py:437-473、
  mysql_db.py:2646-2654、app.py:1699-1710），空分支均为 info/warning 引导，无裸抛路径。

### 1.5 回归确认 —— 通过

`MYSQL_HOST=127.0.0.1 python3 -m pytest tests/ -q` = **610 passed**（84s；
608 基线 + 修复①②新增 2 用例），零 fail 零 error。三新页真实数据页冒烟由
`test_page_guides.py::test_every_page_renders_its_guide`（12 页逐页真实库渲染）与
`test_cluster_analysis/test_semantic_search` 的 `test_smoke_with_real_data` 覆盖，
本次未改动任何源码、无需另行验证。

## 2. 修复清单（外科手术式，仅测试，无源码改动）

| # | 文件 | 问题 | 改法 |
|---|---|---|---|
| ① | `tests/test_integration_apptest.py`（新增 TestS3EmptyDbExistingPages 类） | 用例缺口：既有页 category/graph/domain 在全仓测试中从未于空库渲染，清单 4 的「既有页不抛异常」无执行证据 | 新增 1 用例：空测试库直入三页，断言 info 降级哨兵在场、无异常、无 error 通道（search/corpus/annotate 空库渲染已有用例，不重复） |
| ② | `tests/test_page_guides.py`（新增 test_page_access_table_consistent_with_registration） | 静默回归面：_PAGE_ACCESS 的陈旧键/拼错角色不会被任何行为用例抓住（矩阵用例只断言在场角色可见） | 新增 1 静态锁：导入 src.app（main() 有 `__main__` 守卫，test_phase4/5 同款）断言键恰为六个非基础页、角色 ⊆ {admin, reviewer, annotator, viewer}、元组非空 |

无源码修改：三新页矩阵/断库降级用例与 `_PAGE_ACCESS` 接线在 8623798 已正确
就位，S3 核验为零缺陷，故仅补测试。未 git commit（按约定留监工处理）。

## 3. 数据真值核对（红线项）与留档

- 本次零源码改动，171/996/0.825/0.795/k=5/d=0.045 等真值锚点无触碰风险；
  新增 2 用例只断言 UI 降级哨兵文案与注册结构，不含任何真值。
- α：新增代码零提及 α 具体值 ✅。
- 留档观察（未修，非 S3 清单项）：`src/app.py:1708` graph 页空库引导文案
  「155 词词库及其 2143 条词间关系」与同函数 docstring「136 词 / 1780 边」均系
  历史口径；实测库内 word_relations = 1935（与论文锚点一致），有数据时页面
  metric 读 `get_full_graph` 运行时统计、不受该文案影响。建议后续文档性修订
  统一为运行时口径或 171 词 / 1935 关系，避免误导（改文案属 S1 范畴，本次
  按外科手术纪律不动）。

## 4. 复现

```bash
MYSQL_HOST=127.0.0.1 python3 -m pytest tests/ -q                  # 610 passed
MYSQL_HOST=127.0.0.1 python3 -m pytest tests/test_integration_apptest.py -q   # 25 passed
MYSQL_HOST=127.0.0.1 python3 -m pytest tests/test_page_guides.py -q           # 17 passed
```
