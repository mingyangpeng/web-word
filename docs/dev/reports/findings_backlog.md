# Findings 修复台账（10 轮 review，滚动更新）

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

- [ ] RV4-1 P1 🔴 .env 真实 API key/MySQL 口令入库并推 GitHub——**轮换凭据＋.env 改占位**（今天）
- [ ] RV4-2 P2 _sha256_file 只捕 OSError 不捕 ValueError（NUL byte 崩页出 traceback）——扩为 (OSError, ValueError)
- [ ] RV4-3 P2 媒体路径登记无 base 目录限定——resolve 后前缀校验限 data/media＋拒 symlink
- [ ] RV4-4 P3 showErrorDetails=true 生产改 false（配合日志）
- [ ] RV4-5 P3 grant/revoke TOCTOU 亚 rerun 窗口——实时回库或文档明示
- [ ] RV4-6 P3 st.warning 插值 {e} 可能含 DB 信息——受控分支极窄（P3）
- [ ] RV4-7 P3 static 目录图谱 HTML 绕登录门——数据敏感度低，公网部署时处理
- [ ] RV4-8 P3 requirements 无锁文件＋requests>=2.31 下限——CI 加 pip-audit＋requests>=2.32.4

## RV-8 环境变量完整性（6 findings：P1×1 P2×2 P3×3）

- [ ] RV8-1 P1 🔴 DEPLOYMENT.md 指示写 .env.local 但全仓库无代码读取 .env.local——load_env 只 source .env；compose env_file 也只挂 .env。按清单操作=空操作。修：load_env 追加 .env.local 或改文档
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
