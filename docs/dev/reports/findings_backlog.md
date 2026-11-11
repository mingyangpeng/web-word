# Findings 修复台账（17 轮 review，滚动更新）

> **状态总述（2026-11-09 大核销，FX-16）**：批次 13 系统性修复已入账——
> FX-13（R5-4~7 N+1 修复＋R5-1/2/3/8/9/10、R4-2~7 在码核验，新增 tests/test_fx13_fixes.py）、
> FX-14（RV-9 全 19 项启动链＋RV8-3/4＋R7-26）、FX-15（R7-11/12/14/27＋GUIDE 对齐母本＋「词簇/重心得分」定名全库 0 残留核验）、
> FX-16（本台账核销＋README/ARCHITECTURE/DEPLOYMENT/CHANGELOG 成片刷新＋母本/spec 矛盾修复）。
> 陈账核销：R2 全包、R1-1～R1-10（FX2，批次 12）、R3-1～R3-9（FX，批次 12 前置，1520 绿）、
> RV-1 全包 13 项（FX-A，b421018）、RV-3 全包 8 项（RV3-1 由 FX8 f1e2c81，其余 FX-B b421018）、RV-5 全包 15 项（FX8 f1e2c81＋FX-C b421018）。
> 批次 14（2026-11-09，FX-18/19/20）已入账：规范×实现对账①组「阶段 1 应落地未落」七项全落地——FX-18 工具激活链（两步激活 DB 位/内置工具 11 注册/pack 自检）、FX-19 协同度量五指标、FX-20 改派＋assignments round/training 列＋G2 重标闭环，详见文末「批次 14」节。
> 未修项一律保留 [ ] 并在条目内注明状态；R5-11~14、R8-5~8/10 详情缺失于台账重构（见 R5/R8 各节）。
> 本台账记录待修队列；每笔修复后勾销并标 agent/提交号。

## 待修（按优先级）

### 性能（R5）
- [x] R5-1 P1 init_database 每 rerun 全量 DDL——app.py 会话级单例守卫 `_init_db_done`（FX3 de69eec 修，FX-13 核验在码）
- [x] R5-2 P1 get_full_word_graph 无缓存全量 5 表——mysql_db.py cache_data 缓存（FX3 de69eec 修，FX-13 核验在码）
- [x] R5-3 P1 侧边栏每轮 SELECT * FROM feedbacks——改按需导出（FX3 de69eec 修，FX-13 核验在码）
- [x] R5-4~7 P2 N+1 族（装配/脊柱/版本历史/模板逐义项）——查询数 3→1 / 4→1 / 9→3，实测证据＋新测试 tests/test_fx13_fixes.py（FX-13）
- [x] R5-8 P2 _list_sense_options LIMIT 1000 静默截断——去 LIMIT 全量返回（FX9 e993a98 修，FX-13 核验在码）
- [x] R5-9 P3 get_hot_verbs 无缓存——mysql_db.py cache（FX-13 核验在码）
- [x] R5-10 P3 信度查询无复合索引——reliability.py 复合索引（FX-13 核验在码）
- [ ] R5-11~14 P3 详情缺失（台账原文丢失、全库 grep 无痕迹）——阶段 2 重盘再定

### 输入边界（R2，全 P3）——全修 ✅
- [x] R2-1 建壳 chief 下拉双重转义（FX4 已修，6a0186e）
- [x] R2-2 上传魔数一致性准入（FX4 已修；audio/video 嗅探兜底口径留批次 13）
- [x] R2-3 date 真实性/文本超长专用报错（FX4 已修）
- [x] R2-4 去重口径 docstring 对齐（FX4 已修）
- [x] R2-5 collab LIKE 对齐 _escape_like＋ESCAPE（FX4 已修）
- [x] R2-6 例证正文 20000 上限＋页面注明（FX4 已修）

### 降级（R4）
- [x] R4-1 P2 查询失败与未灌数据分流——三口径落码（None=查询失败→「数据不可用」灰注，勿重跑灌库；app.py:2131 归因注释；FX9 e993a98 深探针补齐，FX-13 核验在码）
- [x] R4-2~7 P3 离线统计 "—"/驾驶舱披露/登出提示语/语义分析归因/MOCK 来源徽章/plotly 降级——六处归因全部在码（FX-13 核验；R4-6 见 app.py:722）

### 代码质量（R6，全 P3）
- [x] R6-2 工具层五文件 docstring 阶段口径齐＋_session_roles 0 残留（FX-15 核验完成）
- [x] R6-4 收敛 ✅ FX-17：5/6 处本地副本改 `from src.db_utils import … as _原名`（签名零变化）；mysql_db._column_exists **声明豁免**（三参形态被 test_schema 迁移契约桩钉死，db_utils 两参版被 test_fxb 反钉，docstring 注明关系）；cluster_analysis._as_int_id 同名不同义按台账不动
- [ ] R6-5 审定状态链下沉＋配色统一；R6-6 状态枚举域前缀（export_center EXPORT_STATUS_* 已由 FX10 批修，余项待）；R6-7 ANCHOR_TYPES 改名
- [ ] R6-8 TASK_TYPE_LABELS 收进 annotation_flow；R6-9 role_grant_user 前缀；R6-10 四处补 logger
- [ ] R6-11 17 个补 docstring——P3 风格项机械补注，**降为阶段 2**（FX10 批已顺手补 pipeline_status 六个 _format_*、template_engine、export_center 数处）
- [ ] R6-12 媒体状态机下沉 media_db
- [ ] R6-1 拆文件建议（不实施——结构性建议，维持现状，阶段 2 再议）

### 文档一致性（R7）
- [x] R7-1/2/3/4/5/7/10 帮助母本 P2/P3 已修（本批）
- [x] R7-8/9/13 collab_pages/dict_admin_pages 内 GUIDE 与文案——GUIDE 对母本 collab 7 处＋dict_admin 5 处（FX-15）
- [x] R7-11/12 page_guides 两处数字——十七页口径/996 条口径（FX-15）
- [x] R7-14 app.py 侧边栏 CSV 登录灰置闸＋原因 caption＋reliability 导出原因 caption（FX-15）
- [x] R7-15/16/18/19/20/21 规范标注未落地项——并入下方「规范×实现对账（FX-15 核对，批次 13）」节逐项在账；两处文档矛盾（母本 6.10、spec §8/§9 资源登记归属）由 FX-16 改真
- [x] R7-22/23/24 README/ARCHITECTURE 成片刷新——以实现为准核对全部数字与功能声明（十七页/六角色/1966 测试/多供应商 LLM/部署双路径/非 root 容器/镜像 digest 固定/容器 healthcheck/--skip-log-bin）（FX-16）
- [x] R7-25 CHANGELOG 置顶批次 13 系统性修复条目＋补批次 11/12 期缺失条目（多供应商 LLM/部署打包/FX-A/B/C/RV-10/11/12）（FX-16）
- [x] R7-26 env_doctor 计数对齐（12 种子/22 表/53 断言）（FX-14）
- [x] R7-27 簇列统一字符串——category_study_page `_cluster_no_cell` 全 str，ArrowInvalid 修复（FX-15）

### R8（原节详情缺失于台账重构，重构后补记）
- [x] R8-1 密码入口三处合一（唯一入口=🔑修改密码面板）＋R8-4 卡片标题去分隔符（2d139cd）；R8-9 覆盖范围提示（18ff66a）
- [ ] R8-5~8、R8-10 详情缺失（台账重构丢失原文；R8-9 已于 18ff66a 补文档提示）——阶段 2 打磨时重盘

## RV-3 签名×行为一致性（8 findings：P2×1 P3×7）— 全修 ✅

- [x] RV3-1 P2 bind_example_media 幂等重绑返 False——回写删 `== 1` 判定＋补重绑测试（FX8，f1e2c81）
- [x] RV3-2 P3 create_assignment assigned_by=0 必败哨兵——改必填＋显式拒绝文案（FX-B，b421018）
- [x] RV3-3 P3 「操作人」参数统一 actor_id（FX-B，b421018）
- [x] RV3-4 P3 media_db mime/_sha256_of_file 注解改 Optional[str]（FX-B，b421018）
- [x] RV3-5 P3 org_db bool 放行——_as_int 统一（FX-B，b421018）
- [x] RV3-6 P3 update_draft/update_example 无变化语义 docstring 互注（FX-B，b421018）
- [x] RV3-7 P3 pipeline_status _format_* 补 docstring＋注解精度（FX-B，b421018）
- [x] RV3-8 P3 advance_binding/example_status 参数校验次序对齐（FX-B，b421018）

## RV-5 中文学术文案（15 findings：P2×5 P3×10）— 全修 ✅

- [x] RV5-1 P2 准入三分统一（Y=核心/EXT=拓展/N=剔除，首现全称）（FX8，f1e2c81）
- [x] RV5-2 P2 搜索页「五要素」＋标点全角化（FX8，f1e2c81）
- [x] RV5-3 P2 标注指南对齐口径文案（FX8，f1e2c81）
- [x] RV5-4 P2 口令→密码 统一（FX8，f1e2c81）
- [x] RV5-5 P2 词义簇/语义簇/词簇 三写法定名「词簇」（FX8＋FX-C；FX-15 复核全库 0 残留）
- [x] RV5-6~15 P3 义项/义位/词条/词目定则＋审稿死术语清理＋滑块＋图注＋UPGMA/MDS/medoid 首现中文全称＋「重心得分」定名＋审定/审核/审校/仲裁/裁决五概念速查表＋词类歧义＋裸表名空态指引＋127/35 差额说明＋平局提示对齐＋母本「编撰」错字＋角色门文案补全＋四卡→六卡同步（FX-C，b421018）

## 规范×实现对账（FX-15 核对，批次 13）

> FX-15 以 spec（平台架构设计规范 v5.1）逐条核对实现，三类差异原样入账：

**① 阶段 1 应落地未落**——七项已全部落地（批次 14，2026-11-09，逐项勾销如下）：
- [x] ①1 两步激活缺 available 位与 category_tool_settings/settings_audit 接线——新建 src/tool_settings_db.py（两表入 CREATE_TABLES_SQL；available_set/unset=平台管理员、enabled_set/unset=词典管理员且 available 先行；审计行 who/when/action/old→new 全留痕）；registry 挂 _DB_ENABLED_LOADER 缝（DB 位优先回落进程位）＋reset_registry_state 复位钩子；新建范畴与工具页两区开关即写即审计（FX-18）
- [x] ①2 内置工具仅注册 3/10——十类工具＋multimedia 共 11 个 ToolSpec 全注册：三标注工具（admission/feature_coding/alignment）以 task_type 委托 submit_annotation，其余八类薄包装委托既有数据层函数；页面接线归阶段 2，docstring 阶段口径沿用 R6-2 纪律（FX-18）
- [x] ①3 pack 自检无——新建 src/tools/pack_check.py pack_selfcheck(category)：pack 引用 ⊆ 注册表＋启用态校验接 DB loader；无引用范畴返回「无工具引用，通过」（FX-18）
- [x] ①4 改派无入口——annotation_flow.reassign_assignment 五道闸（actor 权限/状态 ∈ 可改派集（规范 draft/rejected 提法以码为准映射 open 态）/非现承包人/同项目在册＋账号在用/乐观并发 UPDATE WHERE status 复验）＋日志留痕；任务分配 tab 加改派操作（FX-20）
- [x] ①5 assignments 缺 round/training 列——ALTER-only 幂等迁移（information_schema 探测缺列才加）：round INT NULL/training TINYINT(1) NULL（NULL 口径按 RV2-3）；分派表单轮次/试标轮可选输入＋看板 R2/试标徽章；重标任务 round+1 落列（**mysql_db.py ALTER-only 清单由 FX-21 并行补记**）（FX-20）
- [x] ①6 协同度量缺 5 指标——新建 src/collab_metrics.py 接入协同度量页五卡：AI-人一致率（adopted÷已裁决草稿提案，modified 保守不入分子）/标注节省量（(采纳＋修改采纳)×3.0 分钟/条，工程估算徽章）/打回率（review_tasks verdict 只读：(打回＋否决)÷已出结论轮）有源即算；替换测试与体例质检通过率无数据源→灰注占位不编数字（FX-19）
- [x] ①7 G2 缺修订重标闭环与矩阵导出——annotation_flow.create_reannotation_tasks（逐义位校验裁决状态（CAST 显式 COLLATE utf8mb4_unicode_ci 修 1267 混排）＋历史标注人各建 round+1 任务＋scope_verbs=受影响义位动词）＋任务分配 tab「发起重标」入口＋list_divided_senses 台账读面；特征矩阵导出核实已在码（入口在信度报告页，原述「缺导出」就此更正）（FX-20）

**② 规范超前属阶段 2**：用户上下文 5 表 / 广播 / 登录三分支 / 七区分组 /
AI 体例质检 / G3 撰写侧消费 / usage_logs.user_id / 驾驶舱风险清单。

**③ 文档矛盾**（FX-16 已改真）：
- spec §8/§9 资源登记＝平台管理员·系统管理区 vs 母本 §7.5 词典管理员·出版导出
  tab——**实现跟随母本**，spec 两处已对齐并加「（2026-11-08 对齐实现口径）」；
- 母本 6.10「出版导出【阶段2】」vs 4.6【已实现】自相矛盾——统一按 4.6【已实现】口径。

## RV-2 Schema 迁移完整性（4 findings：P2×1 P3×3）

- [x] RV2-1 ✅ FX-17：双层闸（删前探测 annotation_submissions/adjudications 行数→RuntimeError+force 指引；撞 1451 重抛「事务已回滚未删行」）；沙箱实测假成功消除
- [x] RV2-2 ✅ FX-17：定名「users FK 删除纪律」单一出处 users_db.py（自有表 CASCADE＋留痕 SET NULL／业务引用 NO ACTION＋入口前置探测），org_db.py 互指；不做破坏性 ALTER
- [x] RV2-3 ✅ FX-17：定名「留痕列 NULL 口径」写为 mysql_db.py CREATE_TABLES_SQL 头注释（INT NULL=系统作业/VARCHAR NULL=动作尚未发生/NOT NULL ''=显式无内容），不改数据
- [x] RV2-4 ✅ FX-17：CREATE 头部 ALTER-only 清单 18 项＋新测试与 CREATE 文本互钉

## RV-1 CSS/布局/可访问性（13 findings：P2×7 P3×6）— 全修 ✅（FX-A，b421018）

- [x] RV1-1 P2 IAA 徽章白字对黄底对比度——深档替换
- [x] RV1-2 P2 13 个底色白字对比度不达 AA——深档替换＋_badge 收敛 design_system
- [x] RV1-3 P2 暗色主题浅底容器文字不可读——补深色文字/主题分支
- [x] RV1-4 P2 字号层级 120 处失效（font 简写值当 font-size 插值）——常量拆独立值
- [x] RV1-5 P2 design_system 对比度校验器公式错误——实现标准 sRGB luminance
- [x] RV1-6 P2 状态/警示文本彩字对比度——深档替换
- [x] RV1-7 P2 卡片正文彩字/徽章群对比度——正文彩字≥4.5 深档
- [x] RV1-8 P3 320px 移动端 flex 固定宽溢出——flex-wrap/百分比
- [x] RV1-9 P3 内联 CSS 无 overflow-wrap——td 加 anywhere
- [x] RV1-10 P3 get_section_spacing 间距从未生效——独立渲染/直写 margin
- [x] RV1-11 P3 暗色主题写死浅色面——半透明或主题分支
- [x] RV1-12 P3 折叠按钮白字 on 渐变对比度——渐变加深
- [x] RV1-13 P3 画像进度条填充对比度——填充改深档蓝

## RV-4 安全深化（8 findings：P1×1 P2×2 P3×5）

- [x] RV4-1 P1 ~~.env 真实 API key 入库~~ ✅ **用户已确认旧 key 早已在智谱后台作废**（2026-11-08）；.env 旧值已清空
- [ ] RV4-2 P2 _sha256_file 只捕 OSError 不捕 ValueError（NUL byte 崩页出 traceback）——扩为 (OSError, ValueError)
- [x] RV4-3 ✅ FX-17：_media_path_gate realpath 前缀校验＋拒 symlink；默认清单 data/media＋data/ModernChineseDict（既有加载链真实来源），MEDIA_BASE_DIRS 可覆盖；三负向测试（../逃逸/绝对路径外/symlink）
- [ ] RV4-4 P3 showErrorDetails=true 生产改 false（配合日志）
- [x] RV4-5 ✅ FX-17：两 docstring 明示「TOCTOU 窗口（亚 rerun 级）＋后果有界」并指向页面实时复核 current_roles=list_roles()
- [x] RV4-6 ✅ FX-17：app.py:131 唯一命中改 logger.error 留细节＋页面通用文案；AST 测试钉死不再回潮
- [ ] RV4-7 P3 static 目录图谱 HTML 绕登录门——数据敏感度低，**留公网部署时处理**（DEPLOYMENT.md §1.2/§五已如实标注风险）
- [x] RV4-8 ✅ requests>=2.32.4 已提（前批）＋FX-17：CI 加 pip-audit step（continue-on-error 温和档只出报告）

## RV-8 环境变量完整性（6 findings：P1×1 P2×2 P3×3）

- [x] RV8-1 P1 ~~.env.local 断链~~ ✅ 三段全通（4262adf bash load_env ＋ FX-11 compose env_file `.env`/`.env.local` required:false ＋ backup_db.sh 依次读 .env.local→.env）
- [x] RV8-2 ✅ FX-17：逐键 grep src/ 实读后补 12 行（含台账键名更正 LLM_DB_PROVIDER_TTL_SECONDS、LLM_CONNECT_TIMEOUT 实际在 llm_providers_db.py）；新测试反证键名真实在码
- [x] RV8-3 P2 lib_deploy.sh load_env 真「已 export 优先」（FX-14）
- [x] RV8-4 P3 start_streamlit 去 MYSQL_HOST=127.0.0.1 硬编码，连接参数归一 DB_*（FX-14）
- [x] RV8-5 P3 README 环境变量指引行按实际键名改真（ZHIPUAI_MODEL/LLM_MODEL 语义、去 ZHIPU_API_KEY「.env.example 另有旧名」误导）（FX-16）
- [x] RV8-6 ✅ FX-17：.env.example 补三行（+08:00/utf8mb4/utf8mb4_unicode_ci，与 mysql_db 缺省一致）；README 侧环境变量行 FX-16 已按实改真

## RV-9 启动脚本与健康检查（19 findings：P2×6 P3×13）— 全修 ✅（FX-14）

- [x] RV9-1 P2 start.sh 零数据上线拦截（初始化后中断不再静默上线）＋env_doctor hint 对齐
- [x] RV9-2 P2 外部 MySQL 实例防误写——ALLOW_EXTERNAL_MYSQL 显式开关
- [x] RV9-3 P2 stop→start 竞态——stop 有界等待退出
- [x] RV9-6 P2 reassemble 失败显式报错（去 `|| true` 吞错）
- [x] RV9-9 P2 repair --fix 增 --force-reload（部分灌入的表可修）
- [x] RV9-11 P2 硬编码 127.0.0.1:3306+webword123——连接参数归一 DB_*（.env 生效）
- [x] RV9-12 P2 web 容器 healthcheck——compose python urllib 探 `_stcore/health`
- [x] RV9-14 P2 MySQL binlog 未关——compose `--skip-log-bin`（datadir 不再日增 ~1G）
- [x] RV9-4~5,7,8,10,13,15~19 P3 13 项按同型自查替代修复：stop 拆分/develop 失败指引/wait_for_mysql SELECT 1/磁盘阈值 3GB/初始化失败显式退出/status 三态/env_doctor 自带 _load_dotenv/.env.local 叠加/AI hint 补齐/8501 健康检查/分卷 hint 可执行等；顺带修 entrypoint.sh 全角括号变量 bug
- 口径注：doctor 现 **21/23**——2 红为真缺口如实上报（zh_dict 部分灌入＋.env AI key 空，AI 走 DB 供应商路由），非脚本误报

# 第 17 轮（2026-11-08 · 三新镜头：测试质量/依赖配置/会话态）

> 33 findings（P1×5 P2×10 P3×18），三路修复 agent（FX-10 测试侧/CI 侧、FX-11 部署链侧、FX-12 会话态侧）并行交付，
> 全量回归 **1948 passed / 0 failed**（现收集口径 1966 项，FX-13 批新增 tests/test_fx13_fixes.py）。无误报；reviewer 全部 finding 复现。

## RV-10 测试套件质量（11 findings：P1×4 P2×3 P3×4）— 全修 ✅

- [x] P1 无库环境下 12 红点清零：test_users_db fixture connect 入 try＋TestR1ActorGate 类级 skipif；test_pages 模块探针（4 数据依赖用例 skip，11 纯渲染保留）；test_export_center import 探针→真连接探针（死端口实测 196 passed/59 skipped/0 error）
- [x] P2-1 CI 加 `services: mysql:8`＋test env（root 覆盖 fixture 自建库）＋cryptography 依赖——CI 494 skip（25.4%）从根上解
- [x] P2-2 help_center 唯一零行为覆盖模块——tests/test_rv12_fixes.py 补 AppTest（章节导航对齐母本/全文/关键词过滤）
- [x] P2-3 plotly 降级用例零断言——_PlotlyProbeSt 三断言（不抛/warning 含降级/plotly_chart 调用数 0）
- [x] P1-4/P3-1 两处 `or True` 恒真断言删除（test_schema:519 图谱库文件存活守卫复原、test_semantic_search:494）
- [x] P3-4 僵尸用例复活：monkeypatch llm_providers_db=None 真跑 4 条 fail-closed
- [x] P3-2/P3-3 源码文本断言 44 处/e2e 顺序耦合：留档不改（负向耦合断言属合理契约；重构噪音监控）
- [x] ~~观察项~~（FX-12 报出）category_study_page.py「簇」列混 `"—"` 与 int 的 ArrowInvalid——已由 **FX-15 R7-27** 修复（`_cluster_no_cell` 全 str）

## RV-11 依赖/配置/打包（15 findings：P1×1 P2×5 P3×9）— 全修 ✅

- [x] P1 🔴 package_deploy.rsync 追加排除 `data/.mysql_root_pw`（root 密码缓存文件不再随 tar.gz 外发；真打包验证 NOT_IN_TARBALL_OK）＋.dockerignore 同款
- [x] P2 compose env_file 挂 `.env`＋`.env.local`（required:false，Compose v2.24+ 注明）；`./data/backups` bind mount 落位（G6 备份新鲜卡可见宿主 cron 产物）；backup_db.sh 依次读 .env.local→.env；Dockerfile 非 root（useradd -u 1000 app＋chown＋USER app，真 build 容器 whoami=app）；种子 COPY→/app/seed/data＋entrypoint 缺才拷幂等补种（升级镜像种子不再被 named volume 钉死）
- [x] P3 九项：showWelcomeEmail 无效键删／numpy>=1.24 补声明＋streamlit>=1.41（RV12-6）／docx 注释订正／README+TESTING.md 覆盖率口径改实（pytest-cov 转可选手动 `--cov`）／mypy 补 openpyxl 段／screenshots/ git rm --cached（7 文件索引移除，规则生效）／QUICK_START 口令矛盾修／.dockerignore 五目录＋.gsd／基础镜像三处 FROM digest 固定（sha256:07d48240…，台账注日期）
- 风险台账：存量 root 属主卷需一次性 chown 1000:1000（DEPLOYMENT.md 已给）；Linux 首启 mkdir -p data/backups（compose 注释已给）

## RV-12 Streamlit 会话态/rerun（7 findings：P2×2 P3×5）— 全修 ✅

- [x] P2 RV12-1 collab_pages:934 正文直写 widget 键 `page`（点击「去分立复核」必抛 StreamlitAPIException）→ on_click 回调改法；FX-10 加 grep 哨兵防回潮；AppTest 真点流验证旧崩点
- [x] P2 RV12-2 23 处 `st.success+st.rerun` 成功提示被 rerun 整体作废（写成功零反馈，users_admin 角色授予/媒体出版流转最易重复提交）→ 新建 **src/ui_kit.py**（flash/pop_and_render_flash 队列），app.py main() 每轮消费；三页模块 23/23 逐处替换、文案逐字保留、collab_pages 薄封装签名不变；grep 证 success+rerun 组合 0 残留
- [x] P3 RV12-3 template_export 载荷作用域三元组校验（切簇/语言/范畴不再误显上一簇模板）
- [x] P3 RV12-4 _LOGOUT_KEEP_KEYS 补 `_init_db_done`/`_db_available`（登出不再旁路 R5-1 DDL 守卫）；test_r1_fixes 哨兵同步五键
- [x] P3 RV12-5 图谱 prune 放宽回收 `.tmp` 中间文件（word/cluster 双族）
- [x] P3 RV12-6 streamlit>=1.41（options 收缩回落行为；requirements 侧 FX-11 落）
- [x] P3 RV12-7 main() docstring「十六页」→「十七页（16 显式分支 + search 兜底）」
- 口径定版：PAGE_KEYS=17（test_page_guides 锁死）；使用说明书「17 页」正确，验收报告「14 键」为批次 9 前旧口径（留档不改）

## 批次 14（2026-11-09 · 规范对账①组落地：工具激活链/五指标/任务域）

> 三路并行交付，「规范×实现对账」①组「阶段 1 应落地未落」七项全落地：
> FX-18 工具激活链（tests/test_fx18_fixes.py **61 passed**，含两步激活往返/审计/越权拒/页面 AppTest）、
> FX-19 协同度量（tests/test_fx19_fixes.py 新增 25＋test_collab_pages.py 43＝**68 passed**）、
> FX-20 任务域（tests/test_fx20_fixes.py **69 passed**，含真库端到端）。
> 三件新测试文件合计 155 passed；全量回归（现收集口径 2152 项）待收口统一跑，届时更新顶部总述数字。

**FX-18 工具激活链**：
- 两步激活 available 位持久化：新建 src/tool_settings_db.py——category_tool_settings＋settings_audit 两表入 CREATE_TABLES_SQL；available_set/unset=平台管理员、enabled_set/unset=词典管理员且 available 先行约束；审计行 who/when/action/old→new 全留痕
- src/tools/registry.py 挂 _DB_ENABLED_LOADER 缝：DB 位优先、回落进程位；reset_registry_state 复位钩子
- 新建 src/categories_tools_page.py（范畴与工具页）：available/enabled 两区开关即写即审计
- 内置工具注册补全 3/10→11：十类工具＋multimedia 共 11 个 ToolSpec 全注册——三标注工具（admission/feature_coding/alignment）以 task_type 委托 submit_annotation，reliability/clustering/typicality/schema/template/semantic_search/corpus_evidence/multimedia 八类薄包装委托既有数据层函数；页面接线归阶段 2，docstring 阶段口径沿用 R6-2 纪律
- pack 自检：新建 src/tools/pack_check.py pack_selfcheck(category)——pack 引用 ⊆ 注册表＋启用态校验接 DB loader；无引用范畴返回「无工具引用，通过」（测试含 tmp_path 沙箱 pack 与 loader 联动）

**FX-19 协同度量**：
- 新建 src/collab_metrics.py，协同度量页 _render_five_metrics 五卡接入（口径 tooltip＋数据源 caption＋DB 离线整卡降级）
- 有源三指标即算：AI-人一致率（台账三值裁决口径：adopted÷已裁决草稿提案，modified 保守不入分子）；标注节省量（(采纳＋修改采纳)×3.0 分钟/条，工程估算徽章）；打回率（writing_db.review_tasks verdict 只读：(打回＋否决)÷已出结论轮）
- 无数据源两指标（替换测试通过率/体例质检通过率）→灰注占位不编数字，宁缺毋假

**FX-20 任务域**：
- 改派入口：annotation_flow.reassign_assignment 五道闸（actor 权限/状态 ∈ 可改派集（规范 draft/rejected 提法以码为准映射 open 态）/非现承包人/同项目在册＋账号在用/乐观并发 UPDATE WHERE status 复验）＋日志留痕；任务分配 tab 改派操作（src/dict_admin_pages.py）
- assignments round/training 列：ALTER-only 幂等迁移（information_schema 探测→缺列才加；round INT NULL/training TINYINT(1) NULL，NULL 口径按 RV2-3 规范：未设轮次=NULL）；分派表单轮次/试标轮可选输入＋看板 R2/试标徽章；重标任务 round+1 落列——**mysql_db.py ALTER-only 清单与 grant 脚本由 FX-21 并行补记**
- G2 修订→重标闭环：annotation_flow.create_reannotation_tasks（category/sense_ids/旧轮→逐义位校验裁决状态（_CS_STATUS_SQL 映射，CAST 显式 COLLATE utf8mb4_unicode_ci 修 1267 混排）、历史标注人各建 round+1 任务、scope_verbs=受影响义位动词、None actor=系统作业）；任务分配 tab「发起重标」入口；list_divided_senses 台账读面（含 merged_into 列幂等补列哨兵）
- 特征矩阵导出核实：信度报告页已有 ✅（①组原述「缺导出」就此更正——已在码，入口在信度报告页）

**顺带修复两处**：
- 🔴 src/tools/registry.py reset_registry_state 的 `_DB_ENABLED_LOADER = None` 原为函数局部赋值（缺 global），loader 解绑从未生效——FX-20 收尾时发现并修复
- annotation_flow._query 补 docstring（fx5 契约）；test_fx20 修 3 处断言口径（迁移计数按 ALTER 计/整数串 id 合法清洗/杂类型 actor 用字符串构造）


## 批次 15/16（2026-11-09~10 · 阶段 2 自主迭代第一批）

> 五路 agent 并行交付，规范对账②组过半落地。全量回归 **2289 passed / 0 failed**（批次 14 基线 2152 → +137 用例）。

**批次 15（2e2d795）**：
- [x] ②七区菜单分组——app.py 侧边栏 17 页按使用说明书七区分组（单 radio＋分区前缀标签方案：路由契约 PAGE_KEYS 不变、权限门零改动、无 rerun 环路；未登录态照实 6 键）（FX-23）
- [x] ②驾驶舱「风险清单＋待我裁决汇总」——风险五项（存疑义位/信度未达标/分立积压/审校超时 7 天口径/快照滞留）只读灰注降级＋AI 提案 pending 分列＋待我审校四卡（FX-24）
- [x] ②AI 体例质检挂钩——新建 src/style_check.py 五检查项引擎（配置完备性/定义词表/排序规则/spine 覆盖/媒体绑定）＋style_check_runs 表＋collab_metrics 体例质检通过率接真三态（motion 真跑 3pass/1fail/1warn：DEFINING_VOCAB fail=词表待编者核定的如实结论）（FX-25）

**批次 16（本节）**：
- [x] 体例质检 UI 入口——驾驶舱「🧪 体例质检」段：运行按钮＋逐项三色徽章表＋最近 5 次历史＋通过率口径注（form_submit_button 提交、ui_kit.flash 纪律、R4 归因灰注）（FX-26）
- [x] ②usage_logs.user_id——查询日志归因：ALTER-only 幂等迁移（NULL=未登录/系统作业，RV2-3 第 1 类）＋log_usage 向后兼容签名＋app 搜索写路径登录态归因（FX-27）
- [x] ②G3 locked 撰写侧消费——writing_db.get_cluster_lock_state 锁态读面（fail-open）＋撰写台「🔒 词簇已定稿锁定」徽章＋模板页「定稿基线」标识（规范口径：锁定=放行撰写，非禁写；cs_clusters 无 locked_at/locked_by 列如实不编造）（FX-28）
- [x] R6-11 docstring 清欠——fx5 契约全绿：全仓补注（category_pack/llm_api/reliability/word_source/dict_admin_pages 新增 5 函数）＋缝合 app.py field/_status、mysql_db 两个 register（FX-26＋合并缝合）
- [x] ALTER-only 清单补记 usage_logs.user_id（FX-27 报备→合并缝合）

**②组余量（阶段 2 继续）**：登录落地三分支、项目广播、用户上下文 5 表、工具 run() 页面接线。

## 批次 17（1d94ccf · 阶段2②组收官）

> 三路交付＋缝合：FX-29 登录落地三分支（规范 §9 L242 原文：有待办→收件箱/续接点→上次位置/首次→搜索释义，set_resume_page_loader 缝）＋corpus_evidence_tool 接线；FX-30 项目广播域（project_broadcasts＋发布入口＋收件箱横幅）；FX-31 用户上下文域 5 表（自带 DDL 惰性 ensure、own-rows-only 会话派生 CRUD）。缝合：semantic_search_tool 扩 params_schema 收 index（页面缓存透传）＋以句搜义页经工具接线＋续接点端到端（登出落 user_state＋适配器白名单）。全量 2447 passed。

## 批次 18（2026-11-10 · 十镜头 review：25 findings 全修＋文档收口＋回归固化）

> 镜头 13~22 共十镜审批次 14~17 新功能面，四波跑完边审边修。终版全量 **2576 passed / 0 failed**（批次 17 基线 2447 → +129）。

- [x] RV-13 权限（6 P3）——改派原子复验（EXISTS 在册+active）/重标 active 复核/留痕一致性闸/docstring 降格/guards.require_role_interactive＋口径表/_is_dict_admin 收口（FX-32/33）
- [x] RV-14 一致性（3 P2+6 P3）——重标同轮幂等闸（dedup）/user_context 5 表 FK CASCADE/两步激活原子复验+1062 幂等/迁移 1060 白名单×3/长度闸+逐因/改派前值复验/双口径归一/坏 JSON 告警/空行幂等（FX-32/33）
- [x] RV-15 会话态（1 P2+3 P3）——落地分支 1 按可裁决角色过滤（分支 2 复活）/广播表单项目作用域化/「继续」flash/新查询无缓存留档（FX-33）
- [x] RV-16 性能（5 P3）——count_pending_reviews COUNT 专查替代 200 行宽取数；其余留档（驾驶舱聚合/detail_json 多拉/users 双读/list_ 无 LIMIT 潜伏/工具层无共享缓存）
- [x] RV-17 降级（1 P2+3 P3）——广播在册闸连通探测（断库不再误归因不在册）/横幅逐因/登出 warning/α 标签插值
- [x] RV-18 测试质量（7 P3）——grant 补 r1_probe+fx30_test/续接点胶水真测试（适配器白名单+登出源钉）/fx31 死变量/fx27 桩初始化；桩分叉/钉板扩散留档监控
- [x] RV-19 安全（6 P3 加固）——重标批量 ≤500 上限+日志截断/质检异常归一（detail 不落 DB 原文）/reason 相对路径化/vocab_file 绝对路径拒读+1MB 闸/upsert_draft 50000 闸/limit 上界；注入/越权/泄露面 ✅ 无 P1/P2
- [x] RV-20 文档（18 findings）——FX-34 文档收口：说明书 §四七区十七行重写＋落地三分支行为/母本补 6.11 质检 6.12 广播 6.6 改派重标＋三处枚举改真/CHANGELOG 补 14~17+waves 五条/README 三数字＋模块树/spec 三处对齐注＋附录 A 26 张/DEPLOYMENT §1.5 测试库初始化＋TESTING 分层口径；范畴与工具页接线（users_admin 页内段，RV20-1 P2 消）
- [x] RV-21 UX（2 P2+5 P3）——质检范畴下拉移出表单（切换即刷新）/收件箱广播历史 expander（公示兜底面信息丢失消）/重标 500 提示/广播改派空态引导；flash 就近/风险行跳转按钮留档
- [x] RV-22 回归固化——tests/test_review_r18.py 六链端到端（两步激活链/质检→指标链/广播→收件箱链/改派→重标链/落地三分支 AppTest e2e/跨设备续接）＋grant r18 授权

**遗留观察项**（P3 留档）：驾驶舱聚合无缓存（量级小）/list_* 无 LIMIT 潜伏/工具层无共享缓存/源码钉板扩散监控/风险行跳转按钮（on_click 先例已在码）。「落定项无文档」清单全部消（FX-34）。

## 批次 19（2026-11-10 · 工具接线收官＋用户上下文 UI＋RV16-4 消缺）

> 三路交付（FX-35/37 agent＋FX-36 合并手工）：**工具 run() 页面接线 11/11 全通**（②组最后挂账项消）。
> 全量 **2668 passed / 0 failed**（批次 18 基线 2576 → +92）。

- [x] ②工具 run() 接线余 9 个 ✅ 全通——admission（app.py:3432 准入提交）/reliability（页面渲染 :891）/clustering+typicality（cluster_analysis :1929/:1917 同模块自委托）/schema（template_engine :700/:933＋entry_assembly :422）/template（:1244）/multimedia（entry_assembly :497＋lexical_pages :627）；八处全部「get_tool→run、registry 未加载回落直调逐字节等价」先例形态；缓存语义零变化
- [x] 用户上下文域 UI 落地——义项脊柱「📝 我的笔记」（upsert/delete＋updated_at 显示）＋「📌 书签」toggle（'sense' 锚）；账号管理页「⚙️ 我的偏好」段（user_profiles 键值读写，预置 ui.* 两键）；未登录不渲染（fail-closed UI 表达）（FX-37）
- [x] user_context_db 读面补强——get_note/get_profile/get_bookmark 单条直读＋list_* LIMIT 500 行数闸（RV16-4 消缺，参数化占位符）
- [x] RV15-3 侧边栏「↩︎ 续接上次：X」灰注（落地分支 2 命中旗标，radio 上方；登出全清回收）（FX-35）
- [x] 等价性测试：test_fx35（admission 落库行为/三分支）、test_fx36（八处源级钉板＋schema/multimedia 透传行为＋registry 空回落）、test_fx37（笔记/书签/偏好/未登录）

**②组全部关闭**。剩余阶段 2 大件：查阅端只读静态镜像、localStorage 合并、第二标注人/speech（等数据）。

## 批次 20（2026-11-11 · 用户上下文消费落地＋驾驶舱打磨批）

> 三路交付（FX-38/39 agent＋FX-40 合并手工）。全量 **2754 passed / 0 failed**（批次 19 基线 2668 → +86）。

- [x] 偏好键消费（FX-38）——user_context_db.get_pref 读面（fail-closed）＋app.py 消费点：语料页搭配明细 limit 接 ui.rows_per_page（clamp [10,200]）；勘察结论「app.py 无范畴下拉消费点」如实挂账（semantic/cluster/template 页归后续）
- [x] 📌 我的书签列表段（FX-39）——账号管理页：五列表格＋page 锚 on_click 跳转（RV12-1 回调纪律）＋删除＋空态引导；sense/entry 锚跳转如实挂账
- [x] 撰写台草稿暂存/恢复（FX-39）——draft_states 域激活：「💾 暂存草稿」+恢复默认值+提交自动清除；乐观锁/作者校验/回避制零破坏（测试实证）；form_key=writing_draft_{cs_sense_id}
- [x] RV21-3 风险行跳转按钮——单目标三项「前往 →」（on_click 写 page，复合路径两行文字指路）；行渲染改容器布局
- [x] RV16-1 驾驶舱聚合缓存——手写 TTL 60s（**None 不缓存**，R4 归因即时可见；测试清缓存 fixture 配套）
- [x] RV16-1 list_recent_runs 瘦身——include_detail=False 消费（历史小表不再拉 MEDIUMTEXT）
- [x] page_guides「 vs 」行话消缺（copy_quality 契约）
- [ ] 留档：ui.default_category 范畴下拉消费点（semantic/cluster/template 页——app.py 无该控件，勘察如实）；sense/entry 锚跳转（依赖页面上下文）；localStorage 合并

## 批次 21（2026-11-11 · 界面美化：全局主题层＋标签瘦身）

> 全量 **2756 passed / 0 failed**（批次 20 基线 2754 → +2）。

- [x] **全局主题 CSS**（design_system.get_global_theme_css，app.py 模块级注入）——按钮圆角/过渡/悬停抬升＋primary 渐变（两端色白字均 ≥7:1 不降 WCAG）／指标卡卡片化／tabs 活动下划线主题色／expander 与 DataFrame 圆角／告警条左侧主题色强调线／标题字距＋h1 下划线／侧边栏右缘分割／滚动条细圆角——**零色板变更**（语义色板逐值锁定不动，对比度矩阵不受影响）
- [x] get_card_style 阴影升级——单层→双层（1px 贴合＋4px 环境光）＋transition（RV1-3 钉板子串全保留）
- [x] RV21-5 标签瘦身——前缀括号内去区 emoji（页名自带 emoji 相邻重复消）＋区名含于页名时省前缀（语义分析/AI 协作/词典管理三处单行化）；fx23 契约测试同步适配（分块位置断言锁定分组归属）
- 浏览器实测：未登录 6 键单行紧凑、h1 下划线、侧栏右缘分割线在码；登录后各面指标卡/质检段吃全局主题

## 批次 21-2（2026-11-11 · 视觉 2.0 定稿：Apple 设计语言）

> 用户反馈 v2 学术风「太丑」→ 重写为 **Apple 设计语言**（get_global_theme_css v3 全量替换）。全量 **2756 passed / 0 failed**（零功能变更）。

- [x] **设计语言定稿（Apple HIG 网页风格）**：页面底 #F5F5F7＋内容纯白／单一强调色 Apple Blue #0071E3（白字 4.7:1 ✓）／药丸按钮（980px 圆角，apple.com 同款）／分段式 tabs（灰槽白段选中）／毛玻璃侧边栏（backdrop-blur 20px）＋选中项 accent 填充药丸白字／大标题无衬线粗体 -0.02em／发丝线分隔／极简滚动条
- [x] v2 学术风废弃（深色侧栏/衬线 h1/渐变下划线/靛蓝 accent 全部撤）；语义色板八色锁定不动（test_rv1 契约保持）；对比度全对 ≥4.5:1（#1D1D1F/#6E6E73/#0071E3 白字组合）
- [x] 细节：搜索栏全药丸化／tabs 红色下划线残余移除／指标卡白卡大数字紧字距
- 浏览器实测三轮：未登录/登录/驾驶舱——分段时间线、药丸按钮、白卡层级在码

## 批次 22（2026-11-11 · 范畴偏好跨页消费＋书签锚跳转）

> 两路交付（FX-41/42）。全量 **2805 passed / 0 failed**（批次 21-2 基线 2756 → +49）。

- [x] ui.default_category 跨页消费——五处范畴下拉接 get_pref（semantic ss_category／cluster ca_category／template cat_code 补 index／dict_admin 漏斗＋质检两处）；widget key 不动、偏好不在选项集回退、首建后手选不劫持（FX-41，25 测试）
- [x] 书签 sense 锚跳转——标注平台动词选择加 key="annotate_verb"＋书签回调写两键（page=annotate＋annotate_verb；verb 从 title「walk-S1 …」提取，Pilot 集外行为如实测试）；entry 锚维持挂账（FX-42，24 测试）
- [x] 顺带：dict_admin_pages 基线 F821 死行清除（FX-41）

## 批次 23（2026-11-11 · AI-人一致率升级为逐特征真值）

> FX-43 单路交付。全量 **2845 passed / 0 failed**（批次 22 基线 2805 → +40）。8501 容器同步重建（Docker daemon 重启＋build＋up，健康验证 ✓）。

- [x] AI 草稿快照落库——annotation_submissions 补 ai_draft_snapshot JSON NULL（ALTER-only 幂等迁移＋1060 白名单，迁移核提炼 _add_columns_if_missing 共用）；submit_annotation 加 ai_draft 可选参（None=旧 SQL 逐字节一致零破坏）；捕获点=标注平台提交处 AI 初筛草稿原始值（llm_tag/llm_schema/llm_align/llm_reason→映射值域，空值不入快照防假分歧）
- [x] 逐特征一致率口径——collab_metrics.feature_level_agreement_rate（快照 vs payload 逐键比对：一致数÷可比键总数，单侧独有键不计，聚合带快照提交）；指标页回退链：快照面有→逐特征真值（caption「逐特征口径（n 提交）」）→无→台账提案对照口径→断库灰注
- [x] 测试 40 条：迁移幂等/1060/submit 两态/三态聚合/回退链 AppTest/真库端到端 0.8 对表
- 备注：存量提交无快照 → 回退口径自然生效；新提交起逐特征真值累积

## 批次 24（2026-11-12 · Apple 界面 v4 控件级＋标注暂存＋重标批量查询）

> 两路交付（CSS v4 手工＋FX-45）。全量 **2885 passed / 0 failed**（批次 23 基线 2845 → +40）。

- [x] **CSS v4 控件级 Apple 化**——accent-color（radio/checkbox 选中圈统一 Apple Blue，替换 Streamlit 默认红）／焦点环（3px accent glow）／滑杆轨道+拇指 accent／表单卡白底 16px 圆角／下载按钮药丸族／链接 accent 色／代码块 SF Mono 浅灰底／expander 标题加重／内容图圆角／侧边栏节头小灰阶
- [x] 标注平台表单草稿暂存（FX-45，draft_states 第二消费面）——「💾 暂存标注」＋打开恢复（优先级：暂存 > 上次提交 > AI 预填 > 空，字段级校验回落）＋提交自动清除；六字段快照（admission/schema/alignment/cn_syntax/strategy/needs_review）
- [x] RV19-1 重标逐义位闸核对批量化——单条 IN 查询（JOIN 键与 _CS_STATUS_SQL 逐字一致）替代 N 次往返；8 组夹具双实现对照逐项一致；500 上限/dedup 闸不动
- [x] FX-46 公网部署三件套（前批被取消任务重做成功）——deploy/nginx.conf.example（TLS/WS 升级/RV4-7 限速+noindex 折中/限速/安全头）＋Caddyfile.example＋validate.sh（nginx -t 真验通过）＋DEPLOYMENT「六、公网部署」节；核实两件：8501 端口=0.0.0.0（公网时应改 127.0.0.1）、st.iframe 经浏览器请求 static（deny all 不可行→折中口径）

## 批次 25（2026-11-12 · 侧边栏 macOS 式真导航：radio → 按钮式）

> 用户「左侧的太丑」→ 推倒 radio 方案，升级为 **macOS 式真侧边栏**：每区灰阶小节头（ls-nav-header 小型字）＋区页整宽按钮（label=page_label，当前页 type="primary" accent 药丸，on_click 写 session_state["page"]——RV12-1 回调纪律）。PAGE_KEYS/权限过滤/落地三分支全部不变。全量 **2885 passed / 0 failed**（+40：fx42/45 遗留＋本批适配）。

- [x] 侧边栏导航重构——st.sidebar.container(key="ls_nav")＋七区小节头＋整宽按钮；CSS .st-key-ls_nav 透明底/hover 浅灰/primary 蓝药丸白字；zone_text 源常量免转义
- [x] 测试面迁移——_radio_keys/_radio_labels/_page_radio 全部换按钮口径（integration helpers＋fx23＋fx29＋review_r18＋回归矩阵 label_to_key 改 page_label＋page_guides 源级钉板换 nav_{key} 键契约＋fx35 灰注段锚换「七区菜单导航」）；fx23 区块断言改小节头三区在场
- [x] page_label import 补齐（review_r18 模块级归位）；fx23 断言去 Button.type（AppTest 元素类型非按钮 kind）

## 批次 26（2026-11-12 · Apple 原生主题定稿＋控件级 v4）

> 用户反馈「还是太丑」→ 两轮深化：**根因修复**（config.toml 无 [theme] 段——Streamlit 一直在用默认红主题色，radio 红点/焦点红全源于此）＋ CSS v4 控件级全覆盖。全量 **2885 passed / 0 failed**（零功能变更）。

- [x] **根因修复**：src/.streamlit/config.toml 加 [theme] 段（primaryColor=#0071E3 Apple Blue／backgroundColor=#FFFFFF／secondaryBackgroundColor=#F5F5F7／textColor=#1D1D1F）——原生控件（radio 选中圈/checkbox/slider/primary 按钮/焦点）全部转 Apple Blue，替换默认红
- [x] **CSS v4 控件级**——ls_nav 导航行 !important 定稿（未选中透明/悬停浅灰/选中 accent 药丸白字）＋accent-color 统一选中圈＋焦点环 3px glow＋滑杆 accent＋表单卡白底 16px＋下载按钮药丸＋链接 accent＋代码块 SF Mono＋expander 加重＋内容图圆角＋侧栏节头小灰阶＋主区顶距收紧
- [x] 侧边栏 macOS 式真导航定稿——七区小节头（ls-nav-header 灰阶小字）＋区页整宽按钮（当前页 accent 药丸）
- [x] 浏览器实测：未登录首屏/语义分析/驾驶舱三面截图验收（分段 tabs/白卡指标/蓝药丸选中）