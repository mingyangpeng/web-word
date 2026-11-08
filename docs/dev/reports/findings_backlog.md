# Findings 修复台账（17 轮 review，滚动更新）

> **状态总述（2026-11-09 大核销，FX-16）**：批次 13 系统性修复已入账——
> FX-13（R5-4~7 N+1 修复＋R5-1/2/3/8/9/10、R4-2~7 在码核验，新增 tests/test_fx13_fixes.py）、
> FX-14（RV-9 全 19 项启动链＋RV8-3/4＋R7-26）、FX-15（R7-11/12/14/27＋GUIDE 对齐母本＋「词簇/重心得分」定名全库 0 残留核验）、
> FX-16（本台账核销＋README/ARCHITECTURE/DEPLOYMENT/CHANGELOG 成片刷新＋母本/spec 矛盾修复）。
> 陈账核销：R2 全包、R1-1～R1-10（FX2，批次 12）、R3-1～R3-9（FX，批次 12 前置，1520 绿）、
> RV-1 全包 13 项（FX-A，b421018）、RV-3 全包 8 项（RV3-1 由 FX8 f1e2c81，其余 FX-B b421018）、RV-5 全包 15 项（FX8 f1e2c81＋FX-C b421018）。
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

**① 阶段 1 应落地未落**：内置工具仅注册 3/10；两步激活缺 available 位与
category_tool_settings/settings_audit 接线；pack 自检无；改派无入口；
assignments 缺 round/training 列；协同度量缺 5 指标；G2 缺修订重标闭环与矩阵导出。

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
