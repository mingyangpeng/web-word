# 更新日志

## 2026-11-13 · 批次 32：图式范畴化插件——工作流「图式→图式谱系」缺失环节平台化

- 理论落地（给师兄讨论 docx「共享图式提取、图式范畴化」段）：对各子簇提炼的事件图式本身做二级归纳——梳理图式亲缘关系与家族相似性，建立更高层级的事件类型谱系
- 引擎 `src/schema_family.py`：三级归属向量（核心=2/槽位=1/缺省=0）→ Gower nominal（类型差异不取程度差，避免循环论证）→ UPGMA（average linkage，max_distance=0.5 切割）→ 图式家族＋medoid 代表图式；方法论自洽（义位聚类同一套机器用在图式对象上）
- 工具 `schema_family_tool`：第 12 个内置 ToolSpec（stage=schema_family，P 构件工序 8 下游，两步激活照全仓口径）
- 页面语义分析「🌐 图式谱系」tab（第 10 tab）：家族表＋族卡片（代表图式核心要素）；结果按范畴×语言 session 隔离（点「计算」重算），不落库
- 修复 build_schema_families 代表图式错位缺陷（族内位置误索引按族序排列的 medoids——回归断言钉死每族恰一 is_prototype 且与 prototype 一致）
- 测试 `tests/test_schema_family.py` 24 条（向量/Gower 已知值/UPGMA 切割/medoid 平局/端到端/工具委托/RegistryError 必填拒绝/tab 打桩渲染＋<2 图式降级）；test_tools_registry 工具集钉 12、fx18 EXPECTED_TOOL_IDS 同步
- 全量 **3037 passed / 0 failed**（批次 31 基线 3013 → +24）

## 2026-11-13 · fx56–58：RV23–25 监工轮修复收口

- RV24-2：无草稿覆盖更新清残留快照（ai_draft_snapshot=NULL 双形态语句，旧库 1054 回落）——AI-人一致率不再出假分歧
- RV24-5：mysql_db 头部 ALTER-only 清单去失真（补 ai_draft_snapshot 归属、cs_clusters.merged_into 笔误改 cs_senses）
- RV25-2：撰写台暂存陈旧重放双保险（保存成功即暂存失效；基线前进的旧暂存只读收纳不回填）
- RV24-8：save_revision 1062 并发保存冲突专项文案（不再泛化「数据库写入失败」）
- RV19-6 同型补：collab_metrics 快照聚合取数上限 200（双 MEDIUMTEXT 大文本列）
- RV23-P2：AI 模型供应商设置归 A 协作智能层（停 A 一并停 model_settings）；RV23-P3：dict_admin 补 users_admin 入口（功能模块恢复路径可达）；RV25-7：锁定模块读侧恒按启用判定（直库写 0 也不锁死导航）
- RV25-3：勾选段 value-comparison 写回改为「勾选变更才写」（陈旧 session 不再自动覆写 DB）
- FX-57：质检最新运行明细单独 include_detail=True 取数（FX-26 逐项明细不再死路）；RV24-1 灰注归因改真
- 全量回归随批次 32 收口（3037 passed / 0 failed）

## 2026-11-13 · 批次 31：侧边栏净化——三横幅压行＋改密折叠＋搜索页长文折叠

- 用户反馈「左边的登录了咋一直有修改密码提示，还有就是一堆文字干啥的」（64d74f7）
- 默认口令守卫/签发口令横幅：大卡压一行 caption（细节收进 expander，语义保留）
- 修改密码 expander 默认折叠（入口可见不消失——用户「侧边栏太堆」反馈）
- 搜索页：理论长文折叠进 expander，搜索框前置（搜索页「一堆文字」反馈）
- 测试适配：test_integration_apptest／test_security_hardening 断言同步
- 全量 **3013 passed / 0 failed**（+124：fx39 沙箱归位后真库用例激活＋前置批次增量）

## 2026-11-12 · 批次 30：五构件插件化——D·C·P·A·U 模块勾选启停

- 插件注册表 `src/module_plugins.py`：五模块 MODULE_SPECS（D 义位权威库/C 配置定义层/P 编纂工序链/A 协作智能层/U 编者界面层）＋`module_plugins` 表持久化勾选（enabled_by 留痕）；默认全启用（无行/库降级 fail-open——升级不自伤）
- 「📦 功能模块（五构件插件）」勾选段（categories_tools_page 范畴与工具段顶部）：词典管理员勾选启停；C/U 锁定项勾选框置灰（配置层是引擎输入、查阅层是平台底线——服务端写入前二次拒绝）
- 侧边栏过滤＋直访拦截（app.py）：停用模块的页面从侧边栏隐藏；render_module_gate 直访拦截 fail-closed（「🧩 功能模块已被词典管理员停用」提示＋返回搜索释义）；停用为入口级开关不撤数据，重新勾选即恢复
- 测试 `tests/test_fx54_fixes.py` 9 条（表 CRUD/默认启用/锁定项拒绝/fail-open/权限闸/侧边栏隐藏 AppTest）；test_fx18 勾选数断言适配（+5 锁定态渲染）
- 全量 **2937 passed / 0 failed**（批次 28 基线 2928 → +9；2 skipped 口径不变）

## 2026-11-11 · 批次 28：质检趋势可视化＋侧边栏书签快捷段＋CSS v6

- 体例质检趋势 st.line_chart（最近 20 次通过率，分母 0 留空；pass_rate_trend 读面共用查询内核）
- 侧边栏「📌 我的书签」快捷段：最近 3 条（page 锚跳转/sense 锚跳转+动词预选/entry 挂账）＋「全部书签」收尾
- CSS v6：DataFrame 内凹阴影/st.table 白卡/表单 radio 行距/按钮 focus-visible 可达性/侧边栏 232px/指标卡悬停
- 全量 **2928 passed / 0 failed**

## 2026-11-12 · 批次 26：Apple 原生主题定稿＋CSS v4 控件级

- 根因修复：config.toml 加 [theme]（primaryColor #0071E3 等 Apple 色板）——原生控件全转 Apple Blue（此前默认红）
- CSS v4 控件级：accent-color/焦点环/滑杆/表单卡/下载按钮/链接/代码块/节头；侧边栏导航行 !important 定稿
- 全量 **2885 passed / 0 failed**

## 2026-11-12 · 批次 25：侧边栏 macOS 式真导航（radio → 按钮式）

- 七区小节头（灰阶小型字）＋区页整宽按钮；当前页 accent 药丸；on_click page 路由（RV12-1）
- 侧边栏视觉彻底摆脱「【区名】文字前缀＋radio 圆圈」；测试面全面迁移（helpers 口径统一）
- 全量 **2885 passed / 0 failed**

## 2026-11-12 · 批次 24：CSS v4 控件级 Apple 化＋标注暂存＋公网部署三件套

- CSS v4：accent-color 统一选中圈/焦点环/滑杆/表单卡/下载按钮/链接/代码块/节头——控件级全覆盖
- 标注平台表单草稿暂存（draft_states 第二消费面）：暂存/恢复/提交清除，优先级 暂存>上次提交>AI 预填
- 重标逐义位闸核对批量化：单条 IN 替代 N 次往返（双实现对照等价）
- 公网部署三件套：deploy/nginx.conf.example＋Caddyfile.example＋validate.sh＋DEPLOYMENT 公网节
- 全量 **2885 passed / 0 failed**

## 2026-11-11 · 批次 23：AI-人一致率升级为逐特征真值（FX-43）

- annotation_submissions 补 ai_draft_snapshot（ALTER-only 幂等迁移）；提交链捕获 AI 初筛草稿原始值
- collab_metrics.feature_level_agreement_rate：快照 vs payload 逐键比对；指标页回退链（逐特征真值→提案对照→灰注）
- 8501 容器重建（Apple 视觉＋批次 14~23 全量代码上线容器）
- 全量 **2845 passed / 0 failed**

## 2026-11-11 · 批次 22：范畴偏好跨页消费＋书签 sense 锚跳转（FX-41/42）

- ui.default_category 五处范畴下拉消费（semantic/cluster/template/dict_admin 漏斗＋质检）；widget key 不动、首建后手选不劫持
- 书签 sense 锚跳转：标注平台动词 selectbox 加 key＋回调写 page/annotate_verb 两键（verb 自 title 提取）；entry 锚挂账
- 全量 **2805 passed / 0 failed**

## 2026-11-11 · 批次 21-2：视觉定稿——Apple 设计语言（get_global_theme_css v3）

- 全量重写主题层：#F5F5F7 页底＋纯白内容＋发丝线；单一强调色 #0071E3；药丸按钮；分段式 tabs；毛玻璃侧边栏＋选中 accent 药丸；大标题紧字距；v2 学术风（深侧栏/衬线/渐变）废弃
- 语义色板八色锁定不动（WCAG 契约保持）；全对文本对比 ≥4.5:1
- 全量 **2756 passed / 0 failed**（零功能变更）

## 2026-11-11 · 批次 21：界面美化——全局主题层＋侧边栏标签瘦身

- design_system.get_global_theme_css：按钮过渡/primary 渐变/指标卡/tabs 活动下划线/expander/DataFrame/告警条强调线/标题字距/侧边栏分割/滚动条——全装饰性零色板变更（WCAG 对比度矩阵不动）
- get_card_style 阴影双层升级；侧边栏标签瘦身（前缀去区 emoji＋区名含于页名省前缀，RV21-5）
- 全量 **2756 passed / 0 failed**

## 2026-11-11 · 批次 20：偏好消费＋书签列表＋草稿暂存＋驾驶舱打磨（FX-38/39/40）

- **偏好键消费**：get_pref 读面＋语料页 limit 接 ui.rows_per_page（clamp [10,200]）；范畴下拉消费点勘察后如实挂账（app.py 无该控件）
- **📌 我的书签列表**（账号管理页）：page 锚一键前往＋删除＋空态引导；sense/entry 锚跳转挂账
- **撰写台草稿暂存/恢复**：draft_states 激活——暂存按钮＋打开恢复＋提交自动清除；乐观锁/回避制零破坏
- **驾驶舱打磨**：风险行「前往 →」按钮（单目标三项，on_click page 路由）＋进度聚合手写 TTL 缓存（None 不缓存）＋list_recent_runs include_detail 瘦身
- page_guides「 vs 」行话消缺；全量 **2754 passed / 0 failed**

## 2026-11-11 · 批次 20：释义模板页「同簇并排总览＋在线人工修订」（FX-38）

- **同簇并排总览**（对应 261110 葛批注「同词族分开释义、模式不一」的平台落点）：母图式卡片下新增整簇一屏对照表——词典原文（各自成条、模式不一）vs 模板化释义（同一母图式按参数分档）逐行并排，修订过的行带「已修订（vN）」标记；`overview_rows` 纯函数 + `st.dataframe` TextColumn 长文本列（域系页先例同款）
- **在线人工修订**（补齐论文 §6.2「编者可增删槽位、调整框架描述、修改文字释义」的平台实现）：编纂职能 editor/reviewer/dict_admin 在模板页直接改模板文本＋填优化要点，保存即生成新版本；`template_revisions` 表按 (category, language, sense_id, version) UNIQUE 留痕，版本号单语句原子自增（INSERT…SELECT COALESCE(MAX)+1，无先读后写竞态）；历史在面板下方可查；引擎确定性输出始终并存为基线，锁定簇的修订不改变撰写域基线（G3 口径「锁定＝放行撰写，不是禁写」不变）
- 数据层 `src/template_revision_db.py`：数据层 require_role 闸（tool_settings_db 先例）＋页面 require_role_interactive 交互闸双层；读面 fail-open（库离线 → 并排总览修订列占位"—"、面板降级只读、页面不崩）；建表走 flow-tables 先例（模块内 ensure，首用幂等建，不入 mysql_db 全量清单）
- CSV「优化要点」列自动回填：有修订的义位导出时填入其最新 note，列结构 10 列不变（缺省 None 与历史输出逐字节一致）；同簇并排/修订面板/回填全程不新增页面、不动路由
- 测试：`tests/test_template_revision_db.py`（守卫/清洗 10 项不碰库＋集成 6 项，独立库 web_word_template_revision_test，grant 脚本已补三 host 授权）＋ test_template_engine.py 增 TestOverviewRows/TestExportNotes；帮助母本与 page_guides 同步（锚点「母图式」「确定性槽位拼装」保持命中）

## 2026-11-10 · 批次 19：工具接线收官 11/11＋用户上下文域 UI（FX-35/36/37）

- **工具 run() 页面接线 11/11 全通**（②组最后挂账项消）：admission/reliability/clustering/typicality/schema/template/multimedia 八处新接（+semantic_search/corpus_evidence），全部「get_tool→run、registry 未加载回落直调逐字节等价」先例形态，缓存语义零变化
- **用户上下文域 UI**：义项脊柱「📝 我的笔记」＋「📌 书签」toggle；账号管理页「⚙️ 我的偏好」段（user_profiles 读写）；未登录不渲染
- user_context_db 读面补强：get_note/get_profile/get_bookmark 单条直读＋list_* LIMIT 500 行数闸（RV16-4 消缺）
- 侧边栏「↩︎ 续接上次：X」灰注（落地三分支分支 2 可见面补全）
- 等价性测试三件（test_fx35/36/37）；全量 **2668 passed / 0 failed**

本项目使用 [GSD 工作流](.planning/) 按里程碑推进，每个里程碑的详细计划、验证记录与
上下文归档在 `.planning/milestones/` 与 `.planning/phases/`。本文件只记录**面向使用者的
变更**。

> 早期版本（2026-05-30 之前）没有独立版本号，条目按实际完成时间归入 v1.0。


## 2026-11-10 · review waves 1-2：十镜头 review 20 findings 全修（f85e5e6）

第一波（RV-13 权限／RV-14 一致性／RV-15 会话态）＋第二波（RV-16 性能／RV-17 降级／
RV-18 测试质量），合计 20 findings 全修：

- 重标同轮幂等闸（dedup 返回体，防负荷上限污染）、改派原子复验（EXISTS 在册＋前值，
  含 active 复验）、两步激活 UPDATE 原子复验＋1062 转幂等（TOCTOU 消除）
- 落地分支 1 按可裁决角色过滤（viewer/annotator/editor 不再系统性够不到分支 2）；
  广播表单项目作用域化＋横幅在册闸连通探测（断库不误归因「不在册」）＋逐因提示
- 用户上下文 5 表补 FK CASCADE；待我审校 COUNT 专查替代 200 行宽取数；
  迁移 1060 白名单／长度闸归因／坏 JSON 告警等
- 测试质量：grant 脚本补 r1_probe/fx30_test 等测试库、续接点端到端真测试
  （适配器白名单＋登出源钉）；全量 **2569 passed / 0 failed**

## 2026-11-10 · 批次 17：阶段 2② 组收官——登录落地三分支／项目广播／用户上下文域／工具页面接线（1d94ccf）

- **登录落地三分支**（FX-29，规范 §9 L242）：有待办→协作收件箱；有续接点→上次位置
  （flash「已回到上次工作位置：X」）；首次→搜索释义。续接点登出落 `user_state`、
  登录经适配器读取，端到端打通
- **项目广播**（FX-30）：`project_broadcasts` 表＋发布入口（词典管理·项目成员 tab
  「📢 项目广播」，标题 ≤200／正文 ≤10000，校验逐因提示）＋收件箱置顶横幅展示
- **用户上下文域 5 表**（FX-31）：user_profiles／user_state／user_bookmarks／
  user_notes／draft_states（自带 DDL 惰性 ensure，own-rows-only，fail-closed）
- **工具页面接线**：corpus_evidence_tool 页面接线（逐字节等价）；semantic_search_tool
  扩 params_schema 收 index（以句搜义页经工具接线）
- 全量 **2447 passed / 0 failed**（批次 16 基线 2289＋158）

## 2026-11-10 · 批次 16：质检 UI 入口／查询归因／G3 锁定撰写侧消费／docstring 清欠（e458e8a）

- **🧪 体例质检 UI 入口**（FX-26）：主编驾驶舱段——运行按钮＋逐项三色徽章表＋
  最近 5 次历史＋通过率口径注（form_submit_button 提交、flash 纪律、R4 归因灰注）
- **查询归因**（FX-27）：usage_logs.user_id ALTER-only 幂等迁移（NULL＝未登录／
  系统作业）＋log_usage 向后兼容签名＋搜索写路径登录态归因
- **G3 locked 撰写侧消费**（FX-28）：get_cluster_lock_state 锁态读面（fail-open）＋
  撰写台「🔒 词簇已定稿锁定」徽章＋模板页「定稿基线」标识——锁定＝放行撰写非禁写
- R6-11 docstring 全仓清欠（fx5 契约全绿）；ALTER-only 清单补记 usage_logs.user_id
- 全量 **2289 passed / 0 failed**

## 2026-11-10 · 批次 15：阶段 2 第一批——七区菜单分组／驾驶舱风险与裁决汇总／体例质检引擎（2e2d795）

- **七区菜单分组**（FX-23）：侧边栏 17 页按使用说明书七区分组（单 radio＋分区前缀
  标签方案：路由契约 PAGE_KEYS 不变、权限门零改动、无 rerun 环路；未登录态照实 6 键）
- **驾驶舱「⚠️ 风险清单＋📥 待我裁决汇总」**（FX-24）：风险五项（存疑义位／信度未达标／
  分立积压／审校超时 7 天口径／快照滞留）只读逐项兜底＋AI 提案 pending 按草稿/质检/
  探针分列＋待我审校计数卡
- **体例质检引擎**（FX-25）：src/style_check.py 五检查项（配置完备性/定义词表/排序规则/
  spine 覆盖/媒体绑定）＋style_check_runs 表＋协同度量体例质检通过率接真三态
  （motion 实跑 3 过/1 未过：DEFINING_VOCAB fail＝词表待编者核定的如实结论）
- 全量回归 **2289 passed / 0 failed**（批次 15/16 合并复跑口径，较批次 14 基线 2152＋137）

## 2026-11-09 · 批次 14：规范对账①组「阶段 1 应落地未落」七项全落地——工具激活链／协同度量五指标／任务域（da062a5）

- **工具激活链**（FX-18）：tool_settings_db（category_tool_settings＋settings_audit
  两表）两步激活 available→enabled 持久化＋审计全留痕；registry 挂 DB loader 缝；
  categories_tools_page 两区开关；内置工具 3/10→11 全注册＋pack_selfcheck 引用自检
- **协同度量五指标**（FX-19）：collab_metrics——AI-人一致率／标注节省量（估算徽章）／
  打回率有源即算；替换测试与体例质检无数据源灰注占位不编数字（宁缺毋假）
- **任务域**（FX-20）：改派入口（五道闸，open 态分派）＋assignments round/training
  两列 ALTER-only 幂等迁移＋分派表单轮次/试标徽章＋G2 修订→重标闭环
  （create_reannotation_tasks：历史标注人各建 round+1 任务）＋分立台账读面；
  顺带修 registry.reset_registry_state 缺 global 的真 bug
- 收尾：mysql_db ALTER-only 清单补记＋grant 脚本补 fx18/19/20 测试库；
  全量 **2152 passed / 0 failed**（批次 13 基线 1997＋新测试 155）


## 2026-11-08 · 批次 13 系统性修复：性能 N+1／启动链加固／中文学术文案定名

三路并行（FX-13 性能 / FX-14 启动链 / FX-15 文档定名）＋台账大核销与成片文档刷新（FX-16）。
findings 台账（`docs/dev/reports/findings_backlog.md`）同步核销陈账并新增
「规范×实现对账（FX-15 核对，批次 13）」一节。

- **性能 N+1（FX-13）**：装配/义项脊柱/版本历史/模板逐义项四处 N+1 收敛为批量查询
  （查询数 3→1 / 4→1 / 9→3，实测证据钉进新增的 `tests/test_fx13_fixes.py`）；核验
  init_database 会话级单例守卫、get_full_word_graph/get_hot_verbs 缓存、侧边栏按需
  导出、_list_sense_options 去 LIMIT、信度复合索引与降级六口径（R4-2~7）全部在码
- **启动链（FX-14，RV-9 全 19 项）**：start.sh 零数据上线拦截、外部 MySQL 实例防误写
  （`ALLOW_EXTERNAL_MYSQL`）、stop 有界等待、reassemble 失败显式报错、
  `repair.sh --force-reload`、连接参数归一 `DB_*`、web 容器 healthcheck（python urllib
  探 `_stcore/health`）、MySQL `--skip-log-bin`（binlog 关闭，datadir 不再日增约 1G）、
  P3 十三项同型自查修复（env_doctor 自带 .env 加载、.env.local 叠加等）；顺带修
  entrypoint.sh 全角括号变量 bug。`./start doctor` 现 21/23——2 红为真缺口如实上报
  （zh_dict 部分灌入、.env 未配 AI key——AI 走「模型供应商」页的 DB 路由）
- **文案定名与文档成片刷新（FX-15＋FX-16）**：page_guides 十七页/996 条口径、侧边栏
  CSV 登录灰置闸＋原因 caption、reliability 导出原因 caption、范畴页簇列全字符串
  （ArrowInvalid 修复）、GUIDE 对母本 collab 7 处＋dict_admin 5 处、「词簇/重心得分」
  定名全库 0 残留；README/ARCHITECTURE/DEPLOYMENT/CHANGELOG 数字与功能声明以
  当前实现为准核对刷新；母本 6.10 与 4.6 矛盾统一、spec §8/§9 资源登记归属对齐母本

## 2026-11-08 · 批次 11/12 期评审修复（补记，概述）

批次 11/12 期间并行推进的四块工作，此前未入账，补记如下（概述，不逐条）：

- **多供应商 LLM**（3581db2 / 42fadd0）：`llm_providers_db` 数据层＋引擎改造
  （DB 优先路由＋Anthropic 兼容客户端）＋「🤖 模型供应商」管理页面
  （Base URL / API 格式 / API Key / 模型列表，两步激活）
- **部署打包（RV-11，FX-11）**：打包脚本排除 root 密码缓存文件；Dockerfile 非 root
  （uid 1000）＋基础镜像三处 FROM digest 固定（sha256:07d48240…）；compose env_file
  挂 `.env`＋`.env.local`（Compose v2.24+）；种子改由镜像内幂等补种；备份目录
  bind mount；备份脚本依次读 .env.local→.env
- **FX-A/B/C 三路合并**（b421018；FX8 前置 f1e2c81）：RV-1 CSS/WCAG 13 项（对比度/
  暗色主题/字号层级/移动端溢出）、RV-3 签名×行为一致性 8 项、RV-5 中文学术文案
  定名 15 项（「词簇」「重心得分」等术语统一）
- **RV-10/11/12 三镜头 33 findings 全修**（5c0c95f）：测试闸门＋CI 真 MySQL 服务、
  部署链安全（打包泄露/凭据/属主）、会话态（`src/ui_kit.py` flash 队列替代
  success+rerun 23 处、widget 键回调化防 StreamlitAPIException）

## 2026-11-08 · 批次 13：FX10——R6 质量收敛残留＋R7 文档一致性残留

- R6-4 残留收敛：export_center._column_exists 直引 db_utils；export_center/
  pipeline_status 的 `_table_exists`（只传表名、自开游标口径）改为
  db_utils.table_exists 的薄包装——information_schema 探测逻辑全仓库
  只剩 src/db_utils.py 一份，调用点与测试 monkeypatch 零改动
- R6-6 残留：export_center 快照状态常量域前缀 EXPORT_STATUS_*
  （ready/published/revoked，值不改；INSERT 不再内联裸字面量）
- R6-11 残留：pipeline_status 六个 _format_*、template_engine
  _strip_prefix/_get_category、export_center _table_exists 补 docstring
- R7 文档残留：CHANGELOG 词典管理区 tab 数勘正为八（批次 8 出版导出并入后
  的实际数）；功能使用说明 7.4 扩展项标【阶段 1 后续】＋结果卡片六卡口径；
  README 过时数字修正（171 词/1935 边/12 次类簇）；ARCHITECTURE 五处硬错补修

## 2026-11-08 · 批次 12：R1 权限走查十项安全修复

- 数据层六写函数 actor 化（账号接管/越权授权/冒名终裁/草稿劫持复现全部 PASS）
- 四处 legacy 角色门改六角色口径（授予式用户放行）；登出全清白名单；收件箱裁决门；
  版本历史脱敏；停用管理闸；五调用点中央闸门（+59 用例，1579 绿）

## 2026-11-07 · 批次 11：G6 小尾巴收口

- 资源登记数据面（registry_db）；备份自动化（backup_db.sh 真跑验证）；
  configs/style.yaml 体例五节研制；G6 三卡灰注全部转硬检（+44 用例，1490 绿）

## 2026-11-07 · 批次 9-10：装配视图＋跨词类复用验证 5/5 ✅

- 词条装配视图（搜索页七段成品渲染）；speech 配置包复用验证五步全过；
  R-1 模板拼装表外置范畴包（4653 例差分对拍 motion 逐字不变；引擎词类名词清零）

## 2026-11-06 · v2 词表恢复 171 词

- Levin v2 词表（171 词/996 义位）为现行口径；136 词为历史 v1 口径（对照用）

## 2026-09 — 词表收窄到 136 个自移移动动词；接入 OALD10 逐义项数据；导出义项清单 xlsx

**词表范围：171 → 136，只收「方式聚焦型」**

`docs/Levin移动动词候选词筛选表.xlsx` 里 171 个通过筛选的词分三类：方式聚焦型（136）、
路径聚焦型（22）、互动聚焦型（13）。**自移移动动词只对应方式聚焦型** —— 把
`come` / `go` / `arrive` / `enter` / `chase` / `follow` 这类词留在词表里，图上的「近义」
会把「自己怎么移动」和「朝哪移动 / 与谁互动」混成一堆。所以
`load_levin_table()` 默认 `scope="manner"`，只取那 136 词；想看全部 171 词用
`scope="all"`（测试与对照用）。非法 scope 直接报错，不静默返回全部。

这个 136 与用户给的词表**逐个核对完全相等**，也与
`docs/output-oald10en-for-senselist-1020.xlsx` 的提取范围一致。

实测：`definitions=136, word_clusters=8, word_relations=1780`（陆地行进类 45 词 = 990 条边，
完全图理论值与视图推导一致）。

**新增 OALD10 逐义项数据（665 条 / 132 词）**

`docs/output-oald10en-for-senselist-1020.xlsx` 是 OALD 第 10 版的逐义项导出：216602 行，
每行是一个「词条 + 词性 + 义项包」的 Python 字面量。新增 `src/oald_senses.py` 负责提取与清洗：

| 原始形态 | 处理 | 去向 |
|----------|------|------|
| `[intransitive]to move using your legs` | 剥掉方括号前缀 | `grammar` 列 |
| 例句串换行分隔 | 按行切分去空行 | `examples` JSON |
| 行首 `<+ adv./prep.> He ran home` | 剥掉前缀，**并向同组后续例句传播** | `example_patterns` JSON |
| 例句里的 `(= pay by credit card)` | **保留** | 词典原文的夹注，不是编码 |
| `group_tag: 'IDIOMS'` | 提升为 `sense_group` + `is_idiom=1` | 保留但标记 |

原则是**剥下来单独存、不删**：`[transitive]` 决定义项能不能带宾语，是判断英汉对齐时必须看的
证据。习语义项（173 条）也保留、只标记并在卡片上压暗 —— 是否排除是研究判断，程序替研究者
决定等于隐藏了数据。

同形异义与拼写变体都处理了，否则会静默少词：`row` → `row1`（划船）/ `row2`（争吵）、
`tear` → `tear1` / `tear2`（靠表里的 `link_to` 列定位）、`whiz` 在表里拼作 `whizz`。
合并后每条义项保留 `headword` 列，仍能回溯「哪个义项是划船」。

**表结构升到 v6：两个义项来源分两张表**

`word_senses`（`dictionary.db`，中英对照义位，64 条 / 4 词）与新建的 `oald_senses`
（OALD10，665 条 / 132 词）分开。中间那版曾把两者合并、按 `source` 列区分，实测下来
合表代价更高：切分体系不同无法一一对应，`sense_index` 混排后不再表达「同词目下第几条」，
且 `grammar` / `sense_group` / `is_idiom` 会让一半的行恒为 NULL。分表后取某词全部义项要查
两次，这个代价集中在 `get_all_senses()` 一个函数里。

迁移删掉 v5 那 6 个过渡列；**迁移本身不删任何业务数据** —— 过渡期若有 OALD 行残留在
`word_senses` 里，只记进 summary 提示「该重跑灌库了」，由灌库脚本的 `clear_all_word_data()`
处理。

**一个静默失效的 bug：665 条义项的释义全部丢失**

提取器输出的键名是 `definition`，而写库函数读的是 `en_ndef`。结果是行数、外键、日志全都
正常，只有打开卡片才发现每条义项都是空的 —— 这类 bug 靠「看日志有没有报错」永远发现不了。
修法是让清洗产物直接叫 `en_ndef`（与落地表同一个词汇表），并在灌库脚本的收尾校验里加一条
**「释义为空的行数」检查**：非零就打印 `❌` 并说明不要当作灌库成功。测试也钉住了键名。

**导出义项清单 xlsx 供人工核查**

`scripts/export_senses_xlsx.py` 生成 `docs/词表义项清单.xlsx`，四张表：

| 工作表 | 一行是什么 | 用来核查什么 |
|--------|-----------|--------------|
| `词表概览` | 一个词 | 覆盖是否完整、音标缺口、词目释义（灌库值）与来源 |
| `义项明细` | 一个义项 | **主表**：665 条，清洗对不对、语法码有没有剥干净、习语要不要剔除 |
| `中英对照义位` | 一个 dictionary.db 义位 | 中文释义是否可用作词目释义 |
| `问题清单` | 一个待确认点 | 417 条，脚本自己发现的可疑点，不用人去猜哪里有坑 |

导出里的标注与释义**走灌库时同一个函数**，不另算一遍 —— 另算就多一套会漂移的逻辑，
而这一页正是用来核对它的。

**覆盖率的诚实说明**：665 条 OALD 义项里习语 173 条、带例句 559 条、带语法码 437 条；
有 4 个词在整张表里查不到动词义项（`dodder` / `scutter` / `kayak` / `oar`，逐个复核过：
或只有名词词条，或词条名都不存在），它们以「0 义项」出现在导出清单与问题清单里，
而不是被悄悄跳过。词目中文释义的词典原文率降到 **2.9%（4/136）** —— 词表收窄后与
`dictionary.db`（仅 333 个动词词条）的重合自然减少，这是覆盖率的真实下降，不为了让
数字好看而放宽取词范围。

## 2026-09 — 图谱节点/关系详情：右侧信息面板、两张可拖动浮层卡片

点节点或点边，现在能看到的不再只是一行「词簇 + 近义边数」。

**右侧面板 + 独立浮层卡片，两处同源**

选中节点后右侧信息面板给出音标 / 词性 / 词簇 / 释义 / 意象图式等概览，并有
「查看详情」入口弹出**独立的浮层小卡片**：可拖动、可关闭、可单独摆在一处慢慢看，
内容与面板保持同步。卡片含词条名、音标、词性、释义、意象与标注、五元语义分解、
义位明细（逐个义位的中英文释义 / 句式 / 例句 / 近义反义）、关联节点、来源与复核、
备注与收藏。

「同步」不是靠两段代码小心对齐，而是**结构上只有一份**：面板与卡片都调用同一个
`nodeDetailHTML(n, compact)`，面板走 `compact=true` 分支。两套 HTML 靠人工对齐迟早
漂移，而漂移的症状是「面板和卡片说的不一样」—— 最难被发现的那类 bug。

**点「边」看关系卡片**

点连线（而不是点节点）弹出关系卡片：关系名称、源词条、目标词条、关系类型、关系方向、
关系说明、权重 / 强度、例句、来源、备注与收藏。卡片里的词条名可点，直接跳到该词的
词条卡片。

这里踩到一个**实际发生过**的坑：vis 在点到节点时会把「该节点关联的所有边」一并塞进
`p.edges`（实测点一个度数 44 的节点会带回 44 条边）。所以 click 处理**必须先判节点、
再判边** —— 顺序反了就会「点节点却随机弹出某条关联边的关系卡片」，而且因为「确实弹出
了卡片」看起来不像坏掉。已在测试里钉住这个顺序。

**不编造相似度分数**

关系卡片有「权重 / 强度」一节，但没有 `0~1` 的相似度。次类内是**完全图**，每条边结构
等价，「共同邻居数」恒等于（次类词数 − 2），任何相似度都只是把簇大小重新标度一遍。
所以只给可验证的结构指标，并在卡片里**写明为什么没有权重**。

**数据缺口一律显式说明，不留空白**

卡片如实标注了四个覆盖缺口，而不是让人以为是自己没找到：

| 字段 | 覆盖 | 卡片上的说法 |
|------|------|--------------|
| 音标 | 23 / 171 | 「未收录」 |
| 义位明细 | 17 / 171 | 「该词尚未拆分义位」 |
| 词目级例句 | 43 / 171 | 「两端词条都没有例句」 |
| `aspect` / `scope` | 0 / 171 | 「库中 171 词全部为空，暂无数据」 |

音标**不猜**：它是发音事实，用规则拼一个出来比留空更糟，因为读者无从分辨哪条是抄的。

**表结构升到 v4（`definitions.phonetic`）**

音标来自 `data/dictionary.db` 的 `<pronunciation>/<AmE|BrE>/<IPA>`，是词目层的固有属性，
所以和别的标注字段一起放在 `definitions`，由灌库脚本写入；LLM 实时生成时不传该键，
因而不会把灌库写入的音标抹成 NULL（与 `cluster_id` 用 `COALESCE` 同一个道理）。
迁移仍然**只加列**。

**收藏与备注存在浏览器本地**

图谱页是 iframe 里的静态 HTML，没有回写服务端的通道，所以收藏与备注存在
`localStorage`，卡片上如实写着「保存在本机浏览器」。存储被禁用时（无痕 / 沙箱）
退回内存 store，功能当前会话内照常可用，而不是静默失败。

同源下另有一个细节：同一个词重复渲染时**不重建卡片**，否则正在输入的备注会被
`innerHTML` 覆盖掉。换词时才重建，并按词各自保存。

实测（Chrome，Playwright）：面板与卡片共有的 10 个字段取值完全一致；两张卡片都能拖动
（位移 > 40px）与关闭；真实鼠标点击边的曲线中点打开的是**被点的那条边**；点节点不会
误开关系卡片。

## 2026-09 — 按《义项判定标准》重建词表，释义以 dictionary.db 为准，产出一份词表文档

依据 `docs/` 下两份新文档（`义项判定标准.docx`、`Levin移动动词候选词筛选表.xlsx`）重构词表。

**词表换成 Levin 筛选结果，分类换成文档规定的体系**

词目从旧词库的 155 词改为筛选表的 **171 词**；分类从自定义的 25 个 sub_cat 改为文档的
**三主范畴 / 十二次类**。这套变更必须**整体重建**簇与关系（新旧两套次类混在一张图上
只会得到自相矛盾的结果），所以灌库脚本现在会先 `clear_all_word_data()`，
但**保留 feedbacks 与 usage_logs** —— 那是用户产生的数据，不是派生数据。

实测：`definitions=171, word_clusters=12, word_relations=1935, word_senses=246`，
视图推导的边数与物化表一致。

**表结构升到 v3（义位独立成表）**

文档明确「分析单元是义位（sense），而非词目 lemma」，所以新增 `word_senses` 表，
一词目下逐义位记录中英文释义、搭配框架、例句、近义反义词与逐义位的标注字段。
`definitions` 增加义位层面的标注列（意象图式 / 原型层级 / 英汉对齐等级 /
汉语句法特征 / 译义转化策略 / 释义来源 / 来源可信度 / 待复核标志）。

迁移**只做结构**：加列加表，不删任何业务数据。迁移每次应用启动都会跑，让它删数据太危险；
词簇与关系的重建是灌库脚本的职责。新增测试专门断言迁移里不含任何 DELETE。

**释义以 dictionary.db 为首选来源，并如实标注来源**

`src/word_source.py` 是新的词表数据源解析层，把四个来源合成统一结构，释义按可信度降级：

| Rank | 来源 | 词数 |
|------|------|------|
| 1 | dictionary.db（OALD，可回溯原文） | 17 |
| 2 | 既有词库（二手转写） | 130 |
| 3 | 研究者标注的原型义（短语） | 24 |
| 4/5 | 仅英文 / 无 | 0 |

**词典原文率只有 13.5%**，这个数字在页面上、文档里、审计输出中都显式标出 ——
`dictionary.db` 里 `pos='v'` 的词目仅 333 个，与 Levin 词表交集 23 个。不写清楚的话，
读者会以为每条释义都是词典原文。

**原型义位选择：默认保留首条，只在有硬证据时覆盖**

词典的义位顺序携带信息，首位通常就是原型义（17 个词里 16 个如此）。但 `charge`
的首条是「要价，收费」，而它的 Levin 原型主导义是「猛冲向前」—— 直接取首条会把一个
移动动词的释义写成完全无关的意思。

选择器的第一版按「与原型主导义简述的字符重合」排序，结果**弄坏了本来正确的词**：
`come` 的简述是「朝说话人位置趋近」，字面在「来到；到达」里一个都不出现，
而冷僻义位「〔某物〕垂到〔某位置〕」因为带「位置」二字拿到最高分。
用一个会挑冷僻义位的启发式覆盖基本正确的默认值，是净损失。

最终策略：默认保留首条，只有当首条**完全不含位移语义**（既无中文位移语素也无英文
位移动词）、且存在另一个既含位移语义又与简述有实际重合的义位时才覆盖。
实测恰好修正 `charge` 一词，并由测试钉住「只覆盖 charge」这个结果。

**新增词表文档**

`scripts/generate_word_doc.py` → `docs/英语自移移动动词词表.docx`（171 词 / 12 次类 /
1935 边 / 45 条剔除记录）。含编者说明、分类统计、分组词表、义位明细、剔除理由附录。
由脚本生成是为了让每个数字都能追溯到来源，重新灌库后重跑即同步。

**顺带修掉一个真实缺陷：卡片 CSS 当文本泄漏到页面上**

结果区原本用 `st.markdown(get_card_style(), unsafe_allow_html=True)` 给卡片上样式，
实际效果是把 CSS **当文本渲染**出来 —— 页面上可见 5 段
「background-color: #f7fafc; padding: 24px; border-radius: 12px; ...」，
而配对的 `</div>` 也没包住任何东西（Streamlit 把每次 st.markdown 渲染成独立兄弟节点，
HTML 无法跨调用闭合）。这个缺陷从 2026-05 的 phase-02 就存在。

改为带 key 的 `st.container(key=f"card_body_{card_key}")` + CSS 选择器，
与搜索栏 `.st-key-search_bar` 是同一个模式。加了回归测试，并验证过它
在旧写法下确实会失败。

测试 97 → **152**（有 MySQL）/ 140（无 MySQL，12 skipped）。


## 2026-09 — 图谱粒子动效与全屏

- **粒子动效**：每个节点向外冒彩色粒子（带拖尾轨道），**上限 200 个**同时活跃。
  画在独立 canvas 覆盖层上（不拦截鼠标事件），只读 vis-network 的坐标，因此不影响
  拖拽/缩放/点击，且每帧只重绘覆盖层而不必重画 2143 条边。左上角可一键开关。
- **粒子按簇轮转分配**：有选中节点时其所在簇优先（用户要求）；其余按簇大小轮转。
  不能按度数排序取前 N —— 实测那样 200 个粒子会被 56 词的「常态行走」簇独占，
  25 个簇里只有 1 个发光。
- **全屏**：左上角 ⛶ 按钮，对整个 body 请求全屏（侧边栏一起放大），再点退出。
  组件 iframe 的 `allow` 已含 `fullscreen`，实测可进入 1920×1080 并正确重算画布。
- 产物指纹现在**并入模板版本号**（`TEMPLATE_VERSION`）。原先只由数据决定，
  于是「改了模板但数据没变」时 URL 不变，页面继续跑旧渲染逻辑，改了看不见 ——
  本轮踩过这个坑，现在改模板即产生新 URL 并自动清理旧文件。


## 2026-09 — 节点即粒子：引力斥力与阻尼、解除数量上限、搜索自动解锁词簇

- **单词节点本身就是粒子**（原先是「节点旁边另挂一圈小点」）。节点之间同时受锚定力
  （弱弹簧回布局原位）、斥力（与距离平方成反比）与近义边上的引力，一阶阻尼
  `v ← (v + a) × DAMPING`。整体速度按用户要求降到原布局的 0.1×。
- **取消 200 个粒子的数量上限**。每个可见节点都有一颗粒子，粒子数恒等于可见节点数
  （默认 171）。不设上限时「选中簇优先吃配额」的预算分配失去意义，那套两阶段分配
  代码（`PARTICLE_MAX` / `FOCUS_SHARE` / `focusClusterIds` / `particlesPerNode`）
  整体删除，不留开关 —— 没有调用方的死代码只会误导后来的人。
- **修复「一团光晕，啥也看不清」**：粒子半径没有乘 `network.getScale()`。vis 把节点
  画成 `size × scale` 屏幕像素，粒子层却按 canvas 单位画，于是在缩小的默认视野里
  粒子半径是节点的 **3.4 倍**；171 个半透明光晕在 `lighter` 叠加下互相加亮，
  17.1% 的已绘制像素饱和成近纯白。修复后：半径乘缩放并夹在 `[2.5px, 26px]`、
  光晕从节点半径的 3.2 倍降到 1.9 倍、缩放小到 `r < 4px` 时只画实心点（LOD）。
  实测覆盖画布 51%→8%，近纯白 17.1%→0.86%。
- **搜索自动解锁词簇**（用户要求）：搜到的词即使其所在词簇当前没勾选，也会被自动
  勾选上，避免「搜到了这个词，图上却看不到它」。解锁在 `network.focus` 之前执行。
- **物理参数实测标定**：关键指标是「被限速的节点数」—— 初版 167/171 个节点顶在
  `MAX_SPEED` 上，运动由限速而非受力决定，观感是「整张图匀速平移」。经在浏览器中
  逐组测量，采用 `DAMPING=0.94` / `ACCEL_MAX=0.014` / `REPULSE_K=3`，被限速节点
  降到 **0/171**，`MAX_SPEED` 退回纯安全兜底。

## 2026-09 — 交互式知识图谱页（graphify 风格）

把「词与词关系」从静态 SVG 升级为可交互的力导向图，观感与操作对齐
[graphify](https://github.com/Graphify-Labs/graphify) 产出的 `graph.html`。

- **新增图谱页**（侧边栏顶部切换）：全库 155 词 / 2143 边一张图。支持滚轮缩放、
  拖拽平移、节点搜索、点击查看节点信息与全部近义词、按词簇勾选过滤、高亮邻居、
  实时统计当前可见节点/关系/簇数。
- **新增 `src/graph_export.py`** + `get_full_word_graph()`：图谱数据同时具备
  「单簇」与「全库」两种粒度，前者给结果页的 SVG，后者给图谱页。
- **vis-network 本地化**（`src/static/vis-network.min.js`，688KB，随仓库提交），
  不引 CDN —— 与「灌库脚本离线可用 / 无 key 降级 / 无库降级」一致，内网环境下
  CDN 会渲染成一片空白。为此开启 `server.enableStaticServing`。
- **图谱以静态文件 + iframe 呈现**，文件名带数据指纹。若用
  `components.html(html_string)`，Streamlit 每次重跑都会重写 iframe，力导向布局
  从零收敛、用户拖动的位置与选中节点全丢；静态文件则只在数据变化时重载。
- 图谱页底部提供 25 个「按词簇浏览」按钮，点击直接跳到该簇的第一个词并展示其完全图。


## 2026-09 — 表结构重构与词簇图谱接口

### 破坏性变更（自动迁移，无需手工干预）

- **`synonyms` 表已删除**，取而代之的是 `word_clusters` + `word_relations` + `definitions.cluster_id`。
  旧表的边是「环邻」（每词只连同簇左右各 3 个邻居），新语义是「簇内**完全图**」
  （同簇任意两词都有边）。两者不能共存 —— 混在一起会得到自相矛盾的图。旧边被丢弃，
  跑一次 `python scripts/load_word_library.py` 即重建为 2143 条正确边。
- **`statistics` 表已删除**：v1 设计里的键值统计表，全仓库无任何代码读写，实际是死表。
- `init_database()` 现在会自动执行结构迁移（`_migrate_schema()`），用 `information_schema`
  探测后按需 ALTER / DROP，幂等可重复。`definitions` / `feedbacks` / `usage_logs` 的行**原地保留**。

### 新增

- **`word_clusters` 表**：词义簇，唯一键 `(main_cat, sub_cat)`，共 25 个簇。
- **`word_relations` 表**：词间关系，物化簇内完全图，共 2143 条边。
  `CHECK(verb_a_id < verb_b_id)` 保证无向边只存一份（旧表双向各存一行），
  `uq_word_relations_pair` 保证重复灌库幂等，两个端点均有外键（旧表的 `synonym_verb`
  是裸字符串，无法保证词真的存在）。
- **`schema_migrations` 表**：结构版本记录。
- **视图 `v_cluster_complete_graph`**：由簇成员推导完全图，作为物化表的对照实现，
  灌库脚本每次都会核对两者边数是否相等。
- **页面上的词与词关系图谱**（`src/cluster_graph.py` + `app.py: render_cluster_graph_section`）：
  搜索结果页新增 🕸️ 区块，把「查询词 + 其所属词簇」的完全图画成内联 SVG。
  支持切换「完整簇 / 只显示中心词连线」、显示簇大小与 C(n,2) 边数、
  展开簇内成员列表并点击直接切词。
- **切换词簇**：新增 `get_cluster_graph_by_id()` 与 `list_clusters()`，页面上有
  「切换词簇」下拉框，可直接打开 25 个簇中的任意一个 —— 在此之前只能靠「先搜一个别的词」
  间接进入它所在的簇，无法主动浏览。换词时（搜索框 / 热门词 / 簇内成员按钮）选择器自动
  重置回「跟随当前词」。
- 侧边栏新增 **词义簇** 与 **词间关系** 两个结构指标。
- `tests/test_schema.py`（21 个用例）：DDL 约束契约、迁移幂等性、完全图查询与 SVG 渲染。

### 修正
- **授权语句里的库名现在转义下划线**（`scripts/grant_local_mysql.sql` 新增，
  `scripts/init_db.sql` / README / config/README 同步修正）。GRANT 中的 `_` 是
  **单字符通配符**（与 LIKE 同规则），`GRANT ... ON web_word_db.*` 授予的实际是
  「web_任意字符_word_任意字符_db」这个**模式** —— 同机上名字相像的无关库会被一并授权。
  实测确认：未转义时 `web_word_user` 能 `SELECT` 另一个库的表，改成 `web\_word\_db`
  后被拒（1142）。这类问题不报错、不失败，只会安静多给权限，因此另加静态测试
  （`tests/test_schema.py: TestGrantStatements`）扫描所有 SQL 与文档里的 GRANT 语句。
- **新增 `scripts/grant_local_mysql.sql`**：一体化、幂等的本地授权脚本，覆盖应用库
  与迁移集成测试所需库，并说明为何要同时授权 `@'localhost'` / `@'127.0.0.1'` / `@'%'`。

- **`scripts/init_db.sql` 不再复制建表语句**。它以前有一份完整的 CREATE TABLE 副本，
  且以 root 身份**先于**应用执行 —— 一旦建出旧结构的表，应用启动时的
  `CREATE TABLE IF NOT EXISTS` 会**静默跳过**，库就永久停在旧结构上。现在它只建库与授权，
  建表统一由 `src/mysql_db.py` 负责。同时补了 `CREATE USER IF NOT EXISTS`：
  MySQL 8 的 GRANT 不再隐式建用户，用户不存在时整行 GRANT 会以 ERROR 1410 中断脚本。
- **`insert_definition()` 的 `cluster_id` 用 `COALESCE(VALUES(cluster_id), cluster_id)`**：
  传 None 时保留库中现值。否则 LLM 实时生成释义（它不知道簇划分）会把灌库脚本建立的
  簇归属抹成 NULL。
- **建视图的时机移到迁移之后**：视图引用 `definitions.cluster_id`，而旧库要等迁移才补上该列。
- **词簇图谱的小簇布局**：3 个词时改用左右布局，原先的上下布局会让「两个环上节点之间的边」
  与中心词标签叠在同一竖直线上。
- `get_synonyms()` 改为按 `cluster_id` 取同簇其他成员（不再依赖已删除的 `synonyms` 表）。


## Unreleased（仓库清理与部署可用性）

### 部署可用性

- **修复 Docker 下大模型静默失效**：`docker-compose.yml` 注入的是 `ZHIPU_API_KEY`，而应用
  实际读取的是 `ZHIPUAI_API_KEY`（`src/llm_api.py`），导致容器内 key 恒为空、释义永远走离线
  降级且无任何报错。现已同时透传两个变量，并允许通过环境变量覆盖 `LLM_MODEL`。
- **新增 `config/config.example.yaml`**：提供 `host: localhost` 与占位凭据的模板，配合
  `cp config/config.example.yaml config/config.yaml` 即可在新机器部署。
- **重写 `config/README.md`**：修正了此前文档中错误的口令与表结构，写明配置优先级
  （环境变量 > `config/config.yaml` > 内置默认值）、代码识别的全部 `MYSQL_*` 变量名、
  本地 MySQL 从零搭建步骤，以及 Docker Compose 的注入行为。
- **修正 `.env.example`**：`ENVIRONMENT` / `DEBUG` 实际无任何代码读取，已移入「已废弃/预留」；
  `MYSQL_HOST` 默认值同时说明 Docker（`mysql`）与本地（`127.0.0.1`）两种情形。
- **重写 `README.md`**：两条快速开始路径（Docker Compose / 本地 Python + 本地 MySQL），
  目录结构与当前仓库一致，并说明 `.env` 不会被自动加载（仓库无 python-dotenv）。
- **补全 `requirements.txt`**：新增 `python-docx`、`requests`（仅
  `scripts/ingest_motion_verbs.py` 使用），并把运行时依赖、脚本依赖、测试与开发工具分区。
- **CI**：`.github/workflows/ci-cd.yml` 的 Hugging Face 部署任务因转义错误与占位实现而无法
  工作，暂时注释并标注 TODO；测试任务不变。

### 仓库瘦身

- **不再跟踪 `data/mysql/`**（193 个文件、约 184 MB 的 InnoDB 数据文件、binlog 与证书）。
  `.gitignore` 早已包含 `data/`，但文件在规则加入前就已被提交，导致运行中的 MySQL 每次写入都会
  弄脏工作区。仅从索引移除，磁盘上的 datadir 保持原样。
- **不再跟踪根目录重复的学位论文 docx**（与 `data/docs/` 下的副本逐字节相同）。
- **不再跟踪 `.DS_Store` 与遗留的 `tests/__pycache__/*.pyc`**。
- **忽略本机运行产物**：`graphify-out/`、`.gsd/`、`.planning/milestone.lock`。
- **删除 7 份过期的一次性交付/清理报告**：`CLEANUP_REPORT.md`、`FINAL_DELIVERY_REPORT.md`、
  `FINAL_TEST_REPORT.md`、`PROJECT_DELIVERY_SUMMARY.md`、`INDEX.md`、`DOCS_INDEX.md`、
  `DATABASE_MIGRATION.md`。它们宣称「完成度 95% / 可交付」，而当时的 LLM 仍是模拟数据，且
  其中的口令与表结构均与实际代码不符，容易误导新协作者。

## v1.1（进行中）

### Phase 05 — 实时生成接入（Live Generation）

- 新增端到端释义适配层 `get_display_definition()`，明确取数优先级：
  **数据库命中 → 实时 LLM 生成 → 内置示例 `MOCK_DEFINITIONS` → 兜底骨架**。
- LLM 生成成功的结果会持久化到 MySQL，作为后续查询的缓存（`CACHE_TTL_HOURS`，默认 24 小时）。
- 缺少 `ZHIPUAI_API_KEY` 或调用异常时降级不崩溃：仅在结果区提示「实时生成暂不可用，
  已显示离线释义」。
- 把 `InputValidator` 接入查询入口，非法输入不再进入大模型提示词。
- 新增 `tests/test_phase5.py` 覆盖优先级、持久化契约与降级路径。

### 界面修复

- 修复固定搜索栏：此前用 `st.markdown` 包裹 `st.text_input` 的写法从未生效（Streamlit 会把
  两者渲染成兄弟节点），并修正了 `rgba(#ffffff, 0.98)` 这类非法 CSS 与永不成功的 JS 注入等待。
  回归测试见 `tests/test_search_bar.py`。

## v1.0（2026-08-24，tag `v1.0`）

**4 个阶段、5 个计划、8 个任务**（详见 `.planning/milestones/v1.0-*`）。

### 界面与交互

- 三分类示例库（方式聚焦类 / 路径聚焦类 / 体相聚焦类），点击动词即查询。
- 结果四卡片布局：原型与位移事件分析 / 范畴锚定 / 核心释义与多维辨异 / 图式示例，均可折叠。
- 侧边栏：实验统计、热门查询动词（本地筛选、点击即查）、反馈数据 CSV 导出；支持折叠为窄图标栏。

### 后端接入

- **MySQL 8.0 数据访问层**：连接池、启动自动建表，五张表 —— `definitions`、`synonyms`、
  `feedbacks`、`usage_logs`、`statistics`。
- **智谱 AI（GLM）接入**：`src/llm_api.py` 负责调用、JSON 解析与 MySQL 缓存。
- 统计口径修正：「总查询次数」改为来自 `usage_logs`，「已收录词条」单独展示，不再把词条数
  冒充查询次数。
- 用户反馈（1–5 星 + 文字）写入 `feedbacks` 表。

### 安全

- `src/security.py`：SQL 注入与 XSS 模式校验、输出 HTML 转义、密钥掩码。

### 工程化

- Docker 化部署：`Dockerfile` + `docker-compose.yml`（`mysql:8.0` + Streamlit），入口脚本
  先探活 MySQL 再启动应用，探活超时也以离线模式启动；数据落命名卷。
- 迁移到 macOS M1（arm64）：改用 Compose 内的 MySQL，`python:3.11-slim` 多架构镜像。
- pytest 测试框架与 GitHub Actions CI。

## 2026-11-07 · 阶段 1「立柱」完成（架构 v5.1 落地）

- 数据层六模块：协作底座（多角色/项目成员）、工具注册表（ToolSpec 插件）、词典管理
  （定制属性/导入批次/回滚）、AI 台账（ai_proposals）、媒体资产、词形表（wordforms）
- 页面层：词典管理区（八 tab：驾驶舱/成员/定制属性/导入/浏览器/任务分配/
  媒体库/出版导出）、
  AI 协作区（收件箱/协同度量）、帮助中心；搜索词形还原提示
- 流程能力：交互式谱系切割（F2）、义项分立复核（G3 前置）、义位图谱（MDS）、
  流程漏斗（十五工序聚合）、任务分配三校验、提权硬闸门、个人改密、
  导入业务写入（definitions UPSERT＋revert_log）、导出中心（§15 唯一正式出口）
- 测试：610 → 1097+；文档：架构规范 v5.1、功能使用说明（24 功能）、docs/ 六类 taxonomy

## 2026-11-07 · 批次 9：装配视图＋跨词类复用验证（阶段 2 开篇）

- 词条装配视图：搜索页「📄 词条装配预览」——成品词条七段渲染（头块/义项 coverage/
  发布例证/对译三态/多模态/定制属性/参见），工序 14 消费侧首次可见（+75 测试）
- speech 跨词类复用验证：`scripts/verify_category_reuse.py` 五步判据 4/5 架构就绪；
  断点清单 R-1～R-5 归档（R-1 模板硬编码为唯一阻断）；批次 7/8 链路 e2e 六步（+6）
- G6 出版导出页＋词典管理员终裁接口（+38 测试）；侧边栏 AI 待办徽章（on_click 修复）
- 语义分析页合并（范畴深挖＋谱系典型性九 tab 一页；PAGE_KEYS 15→14）

## 2026-11-07 · 批次 10：R-1 收口——跨词类复用判据 5/5 ✅

- 模板拼装表外置范畴包（motion 逐字迁移＋speech 言说动词词面研制＋_template 骨架）；
  引擎词类名词 grep 清零；4653 组向量差分对拍 motion 输出逐字符不变（+9 测试护栏）
- R-2：准入 expander 按范畴动态取包；复用脚本五步 5/5 ✅（R-3/R-4/R-5 开放）
- 搜索页 v0 magic 字符串文案清出界面（Streamlit 顶层裸字面量渲染特性）
