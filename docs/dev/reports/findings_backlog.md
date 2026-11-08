# Findings 修复台账（17 轮 review，滚动更新）

> 已修：R3-1～R3-9（FX，批次 12 前置，1520 绿）。进行中：FX2（R1-1～R1-10）。
> 本台账记录待修队列；每笔修复后勾销并标提交号。

## 待修（按优先级）

### 性能（R5）
- [ ] R5-1 P1 init_database 每 rerun 全量 DDL——app.py 加单例守卫（等 FX2 释放 app.py）
- [ ] R5-2 P1 get_full_word_graph 无缓存全量 5 表——加 cache_data(ttl=300)
- [ ] R5-3 P1 侧边栏每轮 SELECT * FROM feedbacks——改按需/缓存
- [ ] R5-4~7 P2 N+1 族（装配/脊柱/版本历史/模板逐义项）——灌数前修
- [ ] R5-8 P2 _list_sense_options LIMIT 1000 静默截断（正确性）
- [ ] R5-9~14 P3

### 输入边界（R2，全 P3）
- [x] R2-1 建壳 chief 下拉双重转义（FX4 已修，6a0186e）
- [x] R2-2 上传魔数一致性准入（FX4 已修；audio/video 嗅探兜底口径留批次 13）
- [x] R2-3 date 真实性/文本超长专用报错（FX4 已修）
- [x] R2-4 去重口径 docstring 对齐（FX4 已修）
- [x] R2-5 collab LIKE 对齐 _escape_like＋ESCAPE（FX4 已修）
- [x] R2-6 例证正文 20000 上限＋页面注明（FX4 已修）

### 降级（R4）
- [ ] R4-1 P2 查询失败与未灌数据分流（fail-closed 返 None+reason，页面「数据不可用：<原因>」；灌库指引限 ready() 通过分支）——重点：防「重跑先删后插灌库」误导
- [ ] R4-2~7 P3 离线统计 "—"/驾驶舱披露/登出提示语/语义分析归因/MOCK 来源徽章/plotly 降级

### 代码质量（R6，全 P3）
- [ ] R6-2 工具层接线或 docstring 明示阶段口径；删 _session_roles
- [ ] R6-4 _as_int/_current_user/_column_exists/_table_exists 收敛；同名不同义四件改名
- [ ] R6-5 审定状态链下沉＋配色统一；R6-6 状态枚举域前缀；R6-7 ANCHOR_TYPES 改名
- [ ] R6-8 TASK_TYPE_LABELS 收进 annotation_flow；R6-9 role_grant_user 前缀；R6-10 四处补 logger
- [ ] R6-11 17 个补 docstring；R6-12 媒体状态机下沉 media_db；R6-1 拆文件建议（不实施）

### 文档一致性（R7）
- [x] R7-1/2/3/4/5/7/10 帮助母本 P2/P3 已修（本批）
- [ ] R7-8/9/13 collab_pages/dict_admin_pages 内 GUIDE 与文案（FX2 后串行）
- [ ] R7-11/12 page_guides 两处数字（FX2 后串行）
- [ ] R7-14 剩余：app.py 侧边栏 CSV 闸门（FX2 后）＋reliability 导出闸门
- [ ] R7-15/16/18/19/20/21 规范标注未落地项（随批次 12/13 工单）
- [ ] R7-22/23/24 README/ARCHITECTURE 成片刷新（修复收敛后统一做）
- [ ] R7-25 CHANGELOG 置顶＋补批次 11/12 条目；R7-26 env_doctor 计数；R7-27 簇列统一字符串

## RV-3 签名×行为一致性（8 findings：P2×1 P3×7）

- [ ] RV3-1 P2 bind_example_media 幂等重绑返 False（docstring 承诺 True）——回写删 `== 1` 判定＋补重绑测试
- [ ] RV3-2 P3 create_assignment assigned_by=0 必败哨兵——改必填或 None＋显式拒绝文案
- [ ] RV3-3 P3 「操作人」参数 15 名 10+ 型——统一 actor_id: int（批次 13 与 R1-1 剩余合并）
- [ ] RV3-4 P3 media_db mime: str = None 注解谎报 → Optional[str]；_sha256_of_file → Optional[str]
- [ ] RV3-5 P3 org_db isinstance(chief_id, int) 放行 bool——改 _as_int 统一
- [ ] RV3-6 P3 update_draft 无变化=True vs update_example 无变化=False——docstring 互注或统一
- [ ] RV3-7 P3 pipeline_status 六个 _format_* 无 docstring＋三个注解精度
- [ ] RV3-8 P3 advance_binding/example_status 参数校验次序不一致（仅一致性）

## RV-5 中文学术文案（15 findings：P2×5 P3×10）

- [ ] RV5-1 P2 准入三分 5 种写法统一（Y=核心/EXT=拓展/N=剔除，首现全称）
- [ ] RV5-2 P2 搜索页「四要素」→「五要素」＋标点全角化
- [ ] RV5-3 P2 标注指南「英汉对齐」三值 vs 四值对齐（「错位」属簇层）——文案对齐
- [ ] RV5-4 P2 users_admin/page_guides 口令→密码 统一
- [ ] RV5-5 P2 词义簇/语义簇/词簇 三写法定名「词簇」
- [ ] RV5-6~15 P3 义项/义位/词条/词目定则＋审稿死术语＋滑杆/滑块＋caption/图注＋UPGMA/MDS/medoid 首现中文全称＋图式得分四写定名「重心得分」＋审定/审核/审校/仲裁/裁决五概念速查表＋词类歧义＋裸表名空态补指引＋127/35 差额说明＋平局提示对齐＋母本「编撰」错字＋角色门文案补全＋四卡→六卡同步

## RV-2 Schema 迁移完整性（4 findings：P2×1 P3×3）

- [ ] RV2-1 P2 clear_all_word_data 标注存在时 FK 1451 静默回滚但上报虚假成功——先探测 flow 表行，有则显式报错/要求 --force
- [ ] RV2-2 P3 users FK 删除纪律两种口径（CASCADE vs NO ACTION）——规范修订或入口前置探测
- [ ] RV2-3 P3 留痕列 NULL 语义三种口径（INT NULL/VARCHAR NULL/VARCHAR NOT NULL ''）——定一条规范
- [ ] RV2-4 P3 CREATE_TABLES_SQL 缺 12+ ALTER-only 列——CREATE 头部注释维护 ALTER-only 清单

## RV-1 CSS/布局/可访问性（13 findings：P2×7 P3×6）

- [ ] RV1-1 P2 IAA 徽章白字对黄底 1.61:1（reliability 主路径比降级分支还差）
- [ ] RV1-2 P2 13 个底色白字对比度不达 AA（系统性——五份 _badge＋色表）——深档替换＋_badge 收敛 design_system
- [ ] RV1-3 P2 暗色主题浅底容器文字 1.00:1 不可读（156 处中至少 10 处命中）——补 color:#1a202c 或主题分支
- [ ] RV1-4 P2 字号层级 120 处全失效（HEADER_*/BODY_* 是 font 简写值却当 font-size 插值，浏览器丢整条）——常量改带属性名或拆独立值
- [ ] RV1-5 P2 design_system 内建对比度校验器公式错误（未线性化，全表误报 FAIL）——实现标准 sRGB luminance
- [ ] RV1-6 P2 状态/警示文本彩字 2.43~4.13:1 不达——深档替换
- [ ] RV1-7 P2 卡片正文彩字/徽章群 2.26~4.13:1 不达——正文彩字≥4.5 深档
- [ ] RV1-8 P3 320px 移动端漏斗/图式对齐 flex 固定宽溢出——flex-wrap/百分比
- [ ] RV1-9 P3 全库内联 CSS 无 overflow-wrap——td 加 anywhere
- [ ] RV1-10 P3 get_section_spacing 返回完整 div 塞进 style 属性（间距从未生效）——独立渲染或直写 margin
- [ ] RV1-11 P3 暗色主题写死浅色面（搜索栏/卡片）——半透明或主题分支
- [ ] RV1-12 P3 折叠按钮白字 on 渐变 3.66:1——渐变加深或字号提
- [ ] RV1-13 P3 画像进度条填充 2.71:1<3:1——填充改 #2b6cb0

## RV-4 安全深化（8 findings：P1×1 P2×2 P3×5）

- [x] RV4-1 P1 ~~.env 真实 API key 入库~~ ✅ **用户已确认旧 key 早已在智谱后台作废**（2026-11-08）；.env 旧值已清空
- [ ] RV4-2 P2 _sha256_file 只捕 OSError 不捕 ValueError（NUL byte 崩页出 traceback）——扩为 (OSError, ValueError)
- [ ] RV4-3 P2 媒体路径登记无 base 目录限定——resolve 后前缀校验限 data/media＋拒 symlink
- [ ] RV4-4 P3 showErrorDetails=true 生产改 false（配合日志）
- [ ] RV4-5 P3 grant/revoke TOCTOU 亚 rerun 窗口——实时回库或文档明示
- [ ] RV4-6 P3 st.warning 插值 {e} 可能含 DB 信息——受控分支极窄（P3）
- [ ] RV4-7 P3 static 目录图谱 HTML 绕登录门——数据敏感度低，公网部署时处理
- [ ] RV4-8 P3 requirements 无锁文件＋requests>=2.31 下限——CI 加 pip-audit＋requests>=2.32.4

## RV-8 环境变量完整性（6 findings：P1×1 P2×2 P3×3）

- [x] RV8-1 P1 ~~.env.local 断链~~ ✅ 三段全通（4262adf bash load_env ＋ FX-11 compose env_file `.env`/`.env.local` required:false ＋ backup_db.sh 依次读 .env.local→.env）
- [ ] RV8-2 P2 .env.example 缺 9 个变量（LLM_PROVIDER/OPENAI_*/DEEPSEEK_*/LLM_CONNECT_TIMEOUT/LLM_DB_PROVIDER_TTL/MYSQL_TIME_ZONE/RELIABILITY_FORCE_PURE）
- [ ] RV8-3 P2 lib_deploy.sh load_env 声称「已 export 优先」与 bash 语义相反（set -a; source 无条件覆盖）
- [ ] RV8-4 P3 start_streamlit 硬编码 MYSQL_HOST=127.0.0.1 静默覆盖 .env——远程库用户备份对象与应用写入对象不一致
- [ ] RV8-5 P3 README 指向 .env.example 不存在的 LLM_MODEL/ZHIPU_API_KEY 行
- [ ] RV8-6 P3 config/README 与 .env.example 漏 MYSQL_TIME_ZONE/MYSQL_CHARSET/MYSQL_COLLATION

## RV-9 启动脚本与健康检查（19 findings：P2×6 P3×13）

- [ ] RV9-1 P2 start.sh 不验「数据已灌」——初始化后中断即零数据上线；env_doctor 两处 hint 与实际不符
- [ ] RV9-2 P2 db_up 无法区分本项目 mysqld 与外部 MySQL 实例——可能在外部实例上建库写数据
- [ ] RV9-3 P2 stop→start 竞态——kill 不等退出＋wait_db 把垂死实例当成功
- [ ] RV9-6 P2 reassemble_dictionary_db 失败被 || true 吞掉——损坏下载完成部署无人知
- [ ] RV9-9 P2 repair --fix 只能重灌全空表——部分灌入的表非空→被跳过→修不了
- [ ] RV9-11 P2 lib_deploy.sh 硬编码 127.0.0.1:3306+webword123——用户改 .env 后脚本管的是另一套
- [ ] RV9-12 P2 web 容器无 healthcheck——僵死不退出永不重启；_stcore/health 语义错配潜伏
- [ ] RV9-14 P2 MySQL binlog 未关——7.3G/7.7G datadir 纯属浪费＋每日 1G churn
- [ ] RV9-4~5,7,8,10,13,15~19 P3（进程管理/磁盘/脚本容错/env_doctor 文案等 13 项）

# 第 17 轮（2026-11-08 · 三新镜头：测试质量/依赖配置/会话态）

> 33 findings（P1×5 P2×10 P3×18），三路修复 agent（FX-10 测试侧/CI 侧、FX-11 部署链侧、FX-12 会话态侧）并行交付，
> 全量回归 **1948 passed / 0 failed**。无误报；reviewer 全部 finding 复现。

## RV-10 测试套件质量（11 findings：P1×4 P2×3 P3×4）— 全修 ✅

- [x] P1 无库环境下 12 红点清零：test_users_db fixture connect 入 try＋TestR1ActorGate 类级 skipif；test_pages 模块探针（4 数据依赖用例 skip，11 纯渲染保留）；test_export_center import 探针→真连接探针（死端口实测 196 passed/59 skipped/0 error）
- [x] P2-1 CI 加 `services: mysql:8`＋test env（root 覆盖 fixture 自建库）＋cryptography 依赖——CI 494 skip（25.4%）从根上解
- [x] P2-2 help_center 唯一零行为覆盖模块——tests/test_rv12_fixes.py 补 AppTest（章节导航对齐母本/全文/关键词过滤）
- [x] P2-3 plotly 降级用例零断言——_PlotlyProbeSt 三断言（不抛/warning 含降级/plotly_chart 调用数 0）
- [x] P1-4/P3-1 两处 `or True` 恒真断言删除（test_schema:519 图谱库文件存活守卫复原、test_semantic_search:494）
- [x] P3-4 僵尸用例复活：monkeypatch llm_providers_db=None 真跑 4 条 fail-closed
- [x] P3-2/P3-3 源码文本断言 44 处/e2e 顺序耦合：留档不改（负向耦合断言属合理契约；重构噪音监控）
- [ ] 观察项（FX-12 报出，本轮范围外）：category_study_page.py:316 等 3 处「簇」列混 `"—"` 与 int，真实数据下 dataframe ArrowInvalid（不崩页）；阶段 2 灌数前统一列类型

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
