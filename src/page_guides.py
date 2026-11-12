"""页面使用说明 —— 十七页一一对应的使用指南（单一事实来源）。

设计：PAGE_GUIDES 是「页面代号 → 使用说明」的唯一映射，侧边栏的页面
radio 也从这里取键与标签 —— 页面 ↔ 说明的对应关系由数据结构保证，
再加 tests/test_page_guides.py 用 AppTest 逐页验证说明真实渲染出来，
双重锁死「一一对应」。

各页使用说明在页面渲染函数开头调用 render_page_usage_guide(页面代号)；
新增页面时：在 PAGE_GUIDES 加一项 + 在页面函数加一行调用，测试会自动
覆盖新页。
"""

from typing import Any, Dict, List

import streamlit as st

# 每页一段：label（侧边栏标签）/ purpose（一句话定位）/ steps（操作步骤）/ notes（口径与提示）
PAGE_GUIDES: Dict[str, Dict[str, Any]] = {
    "search": {
    "label": "🔍 搜索释义",
    "purpose": "输入一个移动动词，得到基于 Talmy 运动事件类型学的五要素分解释义：六张可折叠卡片把传统笼统释义显式拆成【方式】【路径】【方向】【体相】【范围】，并配套词簇关系图、语料证据与例句库。",
    "principle": [
        "理论依据是 Talmy（1985）运动事件类型学：运动事件分「波浪型（Wave-like，强调方式）」与「矢量型（Vector-like，强调路径+方向）」两类。传统词典释义以路径+方向为核心，而真实使用更强调运动方式与身体姿态，本页因此把方式要素从释义里显式分解出来，实现更准确的运动语义刻画。",
        "五要素语义分解：【方式】（运动采用的姿势/手段）、【路径】（运动经过的空间轨迹）、【方向】（运动朝向的终点/目标）、【体相】（运动时身体的姿态/状态）、【范围】（运动的范围/程度）。这一五元模型（manner/path/direction/aspect/scope）由 src/llm_api.py 的 PROMPT_TEMPLATE 钉死，语义分解表（render_semantic_table）逐行带类型颜色与 emoji 渲染，DB 或 LLM 返回的文本进 HTML 前都会转义。",
        "释义分级策略（_resolve_display_definition 的 D-02 优先级）：MySQL 已审校释义 → 实时大模型生成 → MOCK_DEFINITIONS 内置示例 → 离线兜底（get_fallback_definition，五要素全部标「待生成」）。实时生成的结果会回写 MySQL（mysql_db_persist，traditional+optimized 合并为 JSON 存进 chinese_ndef），下次查询直接命中数据库。",
        "缓存有两级：llm_api.get_definition 先查数据库缓存，created_at 在 CACHE_TTL_HOURS（默认 24 小时，环境变量可调）内即命中；应用层另有会话级 _display_def_cache，防止一次页面重跑中多张卡片各触发一次模型调用。",
        "词间关系的机制：同一 Levin 次类的动词两两互为近义（簇内完全图）。结果页内嵌当前词所在词簇的 vis-network 力导向图（render_word_relation_section），中心词高亮，默认只画「中心词↔成员」连线，避免完全图的连线视觉纠缠。",
        "原型义位自动选择（word_source.select_prototype_index）：词典义位顺序默认可信（实测 17 个可取释义的词中 14 个首条即原型义），只有当首条完全不含位移语义、且存在另一义位同时满足「含位移语义 + 与原型主导义简述加权字符重合」时才覆盖——典型错例是 charge 首条为「要价，收费」，正确原型义是「猛冲向前」。"
    ],
    "data_source": [
        "MySQL definitions / word_senses / oald_senses 表：词目层字段与义位明细，由 scripts/load_word_library.py 灌库；源头是 docs/research/tables/Levin移动动词候选词筛选表.xlsx（171 词、三主范畴十二次类）与 data/dictionary.db（OALD 已审校中文释义，全库缺失时降级读子集快照 data/dictionary_senses_subset.json）。",
        "释义优先级链（src/word_source.py 的 SOURCE_RANK 1-5）：dictionary.db 的 Ch-Def → 既有词库 data/motion_verbs_extracted.json → xlsx「原型主导义简述」（levin-brief）→ data/oxford_cache.json 英文释义（中文待补）→ pending；「义位标注」卡片以彩色徽章如实显示实际命中了哪一级。",
        "实时 AI 释义：src/llm_api.py 按优先级取 ZHIPUAI_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY 配置的提供商（三家均走 OpenAI 兼容 chat.completions，默认模型 glm-4，可用 LLM_PROVIDER 强制指定），PROMPT_TEMPLATE 要求返回traditional / optimized / 五要素 semantic_table / 例句 / 近义词的 JSON。",
        "语料证据卡片：MySQL 语料表，来自 Sketch Engine enTenTen21（475 亿词）的 Word Sketch 导出（data/corpus/），scripts/load_corpus_dataset.py 幂等灌库，提供词频、四类意象图式重心得分与逐槽位搭配明细。",
        "统计与反馈表：usage_logs 记录每次用户主动提交的查询（get_hot_verbs 按它生成热门词），feedbacks 存评分与文字反馈（侧边栏平均评分、总反馈数与 CSV 导出的数据源）。"
    ],
    "steps": [
        "在侧边栏页面单选里切到「🔍 搜索释义」；页面顶部有「📖 使用说明」折叠面板可展开对照。",
        "在顶部固定搜索栏输入动词（如「跑进来」「冲进来」「滑进来」，限 1–50 字符）后回车提交；没想好查什么，可用侧边栏「🔥 热门查询动词」（按真实查询次数排序的前 5 词，支持关键字筛选）或页面底部「📚 示例库」三个标签页（方式聚焦类/路径聚焦类/体相聚焦类）一键点词查询。",
        "结果区「结果展示」从上到下共六张卡片，每张卡片头部是真正可点击的折叠按钮（▼/▶）：🧬 原型与位移事件分析（五要素语义分解表）→ 🎯 范畴锚定（所属范畴「运动方式复合事件」与语义特征标签）→ 🏷️ 义位标注 → 📚 核心释义与多维辨异 → 🖼️ 图式示例 → 🌐 语料库证据 (enTenTen21)。",
        "细读「🏷️ 义位标注」卡片：词目主导义、Levin 来源子类、原型层级（Y=核心 / EXT=拓展 / N=剔除）、意象图式（源点脱离/终点抵达/方式伴随/互动位移四选一）、英汉对齐等级、汉语句法特征、译义转化策略、判定依据，以及「释义来源」徽章；下方义位明细表按 sense_index 列出该词全部义位（分析单元是义位而非词目）。",
        "对照「📚 核心释义与多维辨异」卡片里的两块：灰底的「传统释义」与绿底的「优化释义 (语义分解)」，体会五要素分解前后的差异。",
        "看「🖼️ 图式示例」卡片：真实例句 + 该词同语义范畴的近义动词标签（最多 6 个，来自 word_relations 词簇），可点示例库或在搜索框输入词名逐一对比差异。",
        "展开「🕸️ 词与词关系」区块：查看当前词所在词簇的力导向图（中心词高亮、悬停显名），点顶栏「显示簇内两两连线」展开簇内完全图；「查看簇内全部 N 个动词」展开后点任一词直接切换查询；点「🗺️ 打开全库知识图谱」跳转图谱页。",
        "在底部「💬 反馈与评分」区拖动评分滑块（1–5 星）、填写文字建议后点「📤 提交反馈」——两项都填才能提交，成功后写入 MySQL feedbacks 表并显示反馈历史卡片；需要离线核对时用侧边栏「📥 数据导出」的「导出反馈数据 (CSV)」。"
    ],
    "notes": [
        "释义来源口径：卡片内容可能来自 MySQL 已审校释义、实时 LLM 或离线兜底，「义位标注」卡片的来源徽章会如实标注（词典原文（OALD，可回溯）/既有词库（二手转写，非词典原文）/研究者标注的原型义/仅英文释义/暂无释义），needs_review 的行还会附黄色「候选值需人工复核」提示——候选值不要当定稿用。",
        "词典原文覆盖率必须诚实看待：dictionary.db 里 pos='v' 的 lemma 只有 333 个，与 171 词词表交集很小（约 97% 的词拿不到词典原文），来源分级标注正是为了让人一眼分清词典原文与二手拼装。",
        "未配置任何 LLM key 且数据库无该词时，五要素全部显示「待生成」（离线兜底形态），这不是解析失败；配置 ZHIPUAI_API_KEY（或 OPENAI/DEEPSEEK）后首次查询会实时生成、有数秒级模型调用耗时，结果回写库后后续查询走缓存。",
        "缓存时效：LLM 释义按 CACHE_TTL_HOURS（默认 24 小时）判定新鲜度，会话内另有按词缓存；重新灌库更新数据后，新会话自然刷新。",
        "查询统计口径：只有用户主动提交查询（搜索框回车/点热门词/点示例词）才记 usage_logs，卡片渲染不计数；侧边栏「总查询次数」来自 usage_logs、今日增量取当日区间，「已收录词目」来自 definitions 表，两者是不同口径，不要混读。",
        "反馈必须评分与文字都填才能提交；数据库离线时提交只在本会话内显示成功、不持久化，只有真正写库成功才会标记「已提交」。"
    ]
},
    "graph": {
    "label": "🕸️ 知识图谱",
    "purpose": "全库 171 个动词 / 1935 条近义关系 / 12 个词簇的交互式力导向图，词与词关系的唯一总览入口：可搜索定位、可点选看词条详情、可按词簇过滤。",
    "principle": [
        "数据模型：词簇来自 docs/research/tables/Levin移动动词候选词筛选表.xlsx 的三主范畴十二次类——方式聚焦型（136 词）/ 路径聚焦型（22 词）/ 互动聚焦型（13 词）为主范畴，来源类、终点类、陆地行进类、奔跑行进类、腾空跳跃类、匍匐爬行类、滚动滑行类、长途行进类、飞行游动类、运载工具类、目的类、参与者类为十二次类；同一主范畴+次类的动词构成一个词簇，MySQL word_clusters 表共 12 行。",
        "簇内完全图：词间关系不是逐对人工标注，而是由 scripts/load_word_library.py 的 build_synonym_pairs 从次类推导「簇内两两互为近义」并物化进 word_relations 表（171 词共 1935 条边）。因此每个节点的连线数（度数）恒等于所在簇大小 − 1，每簇边数 = size×(size−1)/2；节点大小按度数缩放，节点越大即所在词簇越大。",
        "力导向布局：前端用 vis-network 的 forceAtlas2Based 求解器（引力/斥力、弹簧长度 120、阻尼 0.4、避免重叠 0.8），初始稳定化 200 次迭代后自动关闭物理引擎——节点静止下来，用户拖动的位置才留得住。",
        "静态化 + 数据指纹缓存：get_full_word_graph 的数据经 src/graph_export.py 渲染成静态 HTML 文件 src/static/word_graph_<指纹>.html，指纹 = SHA256(模板版本号 + 排序后的节点 id 集合 + 边集合 + 节点全量载荷)。数据与模板都没变时 URL 不变，st.iframe 引用静态文件不会随 Streamlit 重跑而重载——拖好的布局、缩放视野、选中的节点全部保留；重新灌库后指纹变化生成新文件，旧文件自动清理。",
        "零网络依赖：vis-network 从本地 vendored 的 src/static/vis-network.min.js 加载（/app/static/ 路径），不用 CDN，断网或内网环境照常渲染。",
        "图内附加机制：右上工具栏提供「节点粒子」粒子层（节点即粒子，相互引力斥力带阻尼）与「⛶ 全屏」；收藏与备注存在浏览器 localStorage（键 wordgraph.annotations.v1），无痕或沙箱模式下降级为内存存储、仅当前会话有效。"
    ],
    "data_source": [
        "MySQL src/mysql_db.py 的 get_full_word_graph()：definitions LEFT JOIN word_clusters 取全部词节点（携带释义/音标/五要素/标注等全量载荷），word_relations 取全部关系边，word_clusters 取簇清单；当前实测 definitions=171、word_relations=1935、word_clusters=12（页顶三个指标卡的数字即此 stats）。",
        "word_relations 的 1935 条边由 scripts/load_word_library.py 灌库时按次类物化（簇内完全图边），运行时不做任何实时推导。",
        "节点载荷还打包了 word_senses（义位明细）与 oald_senses（OALD10 义项，覆盖 132/136 词）——点击节点查看词条详情/浮层卡片时展示。",
        "渲染器 src/graph_export.py 的 build_graph_html / ensure_graph_html：模板版本号 TEMPLATE_VERSION 参与指纹，改模板即换 URL；静态产物写入 src/static/word_graph_<hash>.html，页面用 st.iframe 嵌本地文件而非内联 HTML 字符串。",
        "页面下方「按词簇浏览」按钮的数据来自 get_full_word_graph 返回的 clusters 清单（与 list_clusters 同源），边数按 size×(size−1)/2 计算并显示在按钮文案里。"
    ],
    "steps": [
        "在侧边栏页面单选里切到「🕸️ 知识图谱」；数据库不可用时页面会提示离线模式仅提供释义。",
        "先看顶部三个指标卡掌握规模：动词节点、近义关系、词簇（当前为 171 / 1935 / 12）。",
        "在主区域 820px 高的力导向图上操作：滚轮缩放、拖拽平移、直接拖动节点调整布局；节点越大说明它所在的词簇越大。",
        "右侧栏顶部搜索框输入动词（子串匹配，最多列出 30 条候选），点选结果即定位并聚焦该节点。",
        "点击节点：右侧「节点信息」面板显示词条详情（音标、中文释义、五元语义分解、义位与 OALD 义项、近义邻居列表），同时浮出可拖动的词条卡片，卡片上可点 ★ 收藏、写备注；点邻居列表或卡片里的词名直接切换到该词。",
        "用图例区的词簇清单（可勾选过滤）按簇勾选/取消过滤节点与边：「全选」一键恢复全部，「高亮邻居」开关控制选中节点时是否压暗无关部分；图例下方的统计行实时显示节点、关系、词簇各自的已勾选数与总数。",
        "按需用右上工具栏：「节点粒子」开关粒子层动效，「⛶ 全屏」进入浏览器全屏看大图。",
        "在图下方「按词簇浏览」区（每行 4 个按钮，文案形如「次类名（N 词 / M 边）」）点任一簇，即以该簇第一个词为查询词跳回搜索页，并展开该词所在簇的完全图。",
        "重新灌库更新词库后，数据指纹变化会自动加载新图（布局从头收敛一次）；数据没变时重复打开页面布局与视野保持原样。"
    ],
    "notes": [
        "布局保留的前提是数据与模板都不变：产物文件名含数据指纹，重新灌库会生成新文件，旧布局、收藏过滤等图内状态不会迁移到新图。",
        "完全图口径要读对：连线数 = 所在簇大小 − 1，边表示「同一次类内的近义关系」（按次类规则推导物化，不是逐对人工验证的同义词）；每簇边数 = N×(N−1)/2。",
        "收藏与备注只存浏览器 localStorage（键 wordgraph.annotations.v1），无痕/沙箱环境下退化为内存、关掉页面即丢——图谱是静态 iframe，没有回写服务端的通道，不会进数据库。",
        "规模数字随词表版本变化：历史版本曾是 155 词 / 2143 边、136 词 / 1780 边，现行 v2 词表（171 词捞回路径/互动两类）为 171 词 / 1935 边 / 12 簇；以页面顶部指标卡的实时读数为准。",
        "产物落盘依赖 src/static/ 目录可写，写入失败时页面会提示「图谱文件生成失败」；模板版本号改动会强制产生新指纹，前端改动能立即生效、不会出现「改了看不见」。",
        "图例过滤只影响 iframe 内可见的节点与边，页顶三个指标卡始终是全库口径；过滤后的实时规模看图例下方的统计行。"
    ]
},
    "corpus": {
    "label": "📊 语料数据集",
    "purpose": "浏览 171 个移动动词在 Sketch Engine enTenTen21 语料库中的真实使用证据：词频概览、四类意象图式重心得分与逐槽位搭配明细，并为搭配词的语义归类（人工清洗）提供页内回写入口。",
    "principle": [
        "Word Sketch 机制：Sketch Engine 按词目自动汇总「语法关系（槽位）× 搭配词」矩阵，每个槽位给出按搭配强度排序、最多前 50 个搭配词型；logDice 是对数化搭配强度指标，越高说明该搭配越专属于此动词。注意这是词目层数据，Word Sketch 不做词义消歧。",
        "槽位 → 图式映射：四类意象图式各绑定一组证据槽位——方式伴随图式看 modifiers/adjectives after/同类方式动词并列/subjects 等槽，源点脱离图式看 away/off/out 小品词及其宾语与 from/out of 类介词短语，终点抵达图式看宾语与 into/in/at 类介词短语，互动位移图式看宾语/代词主宾语；同一槽位可服务多个图式，映射回答的是「去哪找证据」。",
        "重心得分公式：每图式重心得分 S = Mean_logDice × log2(N+1)，N 为该图式证据槽位的去重搭配词型数，覆盖率 = 覆盖槽位数/定义槽位数；取 S 最大者为候选凸显图式（candidate_schema），四图式名次记为候选排名（cand_rank）。",
        "AI 初筛口径：该得分为未做语义归类的原始版——抽象名词、名词化用法未被剔除，多义动词（如 run 的计算机义）的搭配会稀释图式信号，因此结果仅作候选参考；最终图式标签须按《义项判定标准修改稿》标准 2 在义位层人工判定。",
        "人机分工：语料回答「哪个要素在该动词的使用档案里信号最强」，词典释义回答「该要素是否为动词自编码」，两个信号叠加才产生图式标签；搭配明细的「语义类别/处理」两列正是语义归类清洗的落库接口（归类用语义标准，独立于 logDice）。"
    ],
    "data_source": [
        "语料库：Sketch Engine · English Web 2021（enTenTen21，约 475 亿词英文网页语料），Word Sketch 导出，检索日期 2026-09-30。",
        "原始数据：data/corpus/wsketch_full/<动词>.json（171 词，槽位×搭配明细与词频）与 data/corpus/schema_evidence/<动词>.json（四图式证据、覆盖率与重心得分）；若存在旧版 output/05_原始数据 与 output/06_图式提取结果 则优先使用。",
        "灌库脚本：scripts/load_corpus_dataset.py 全量替换（先删后插、事务）写入 MySQL 四表：corpus_word_stats（词频概览）、corpus_collocations（搭配明细）、word_schema_scores（重心得分）、corpus_schema_evidence（每图式 Top10 证据词）。",
        "页面读取与回写：get_corpus_overview / get_corpus_word_stats / get_corpus_schema_scores / get_corpus_schema_evidence / get_corpus_collocations 提供展示；人工标注经 update_collocation_annotations 按 id 回写 corpus_collocations 的 semantic_category、keep_flag 两列。"
    ],
    "steps": [
        "进入页面先看状态与规模：数据库不可用或语料数据未灌入时，页面会提示运行 `MYSQL_HOST=127.0.0.1 python3 scripts/load_corpus_dataset.py`；顶部四个指标依次为「动词」总数（171）、「搭配词型总数」、「重心得分行」（动词数 × 4）、语料库（enTenTen21）。",
        "读「总表（按频次降序）」：在「筛选动词」框输入关键字（对动词列做不区分大小写的包含匹配）过滤；列依次为 动词 / 词性 / 总频次 / 每百万频次 / 槽位数 / 搭配词型 / 候选凸显图式(AI初筛) / 最高重心得分；表下图注提醒候选图式仅为 AI 初筛，最终以义位标注为准。",
        "「逐词详情」下钻：在「选择动词」下拉选词（默认 walk），先读四个指标——总频次、每百万频次、槽位数（语法关系数）、搭配词型数。",
        "看「四类意象图式重心（AI初筛）」：柱状图按重心得分 S 对比四个图式，表格给出每图式的 覆盖槽位 / 定义槽位 / 覆盖率 / 搭配词数 N / Mean_logDice / 重心得分 S / 候选排名（按 S 降序）；该词暂无数据时会提示。",
        "核对「图式证据搭配（每图式 Top5）」：每个图式列出得分最高的 5 个证据搭配词、其 logDice 与所在槽位，用来追溯重心得分的数据来源（库里存 Top10，页面展示前 5）。",
        "进「搭配明细（按槽位，可编辑）」：先在「选择槽位」下拉选槽位（默认 'objects of \"%w\"'，槽位列表按名称排序），表格按槽位内排名（即 logDice 序）展示该槽位搭配词及其 logDice、搭配频次等。",
        "人工语义归类：「语义类别(人工)」列填归类（如 空间终点/抽象结果/方式副词），「处理(人工)」列下拉选 保留/剔除（可清空）；其余列为只读。点「💾 保存本槽位语义归类」，系统按行 id 对齐、只回写真正修改过的行，成功后提示保存条数（没有修改则提示无需保存）。",
        "保存后看本槽位底部的口径图注：当前槽位总行数与「保留」行数即 PS 计算的 N，Mean_logDice 按「保留」行的 logDice 均值计——这就是清洗后正式重算的口径。"
    ],
    "notes": [
        "AI 初筛 ≠ 最终标签：页面「候选凸显图式」与四图式重心得分未做语义归类（N 未清洗），多义词搭配互相稀释；最终图式标签以「标注平台」的义位层人工标注为准。",
        "人工标注回写方式：页内编辑「语义类别(人工)/处理(人工)」→ 只保存改动行 → UPDATE corpus_collocations.semantic_category / keep_flag；语义归类须用独立于 logDice 的语义标准（如 station/summit 等可物理到达的空间实体保留，conclusion/milestone 等抽象与隐喻投射名词剔除），剔除记录保留以备核查。",
        "两个口径并存：四图式重心得分为清洗前的 AI 初筛；PS = Mean_logDice × log2(N+1) 的正式计算只统计「保留」行——引用数值时注意区分。",
        "重灌会丢失人工标注：load_corpus_dataset.py 为全量替换（DELETE 后仅重插语料字段），corpus_collocations 已填的 semantic_category/keep_flag 不随语料包恢复，重灌前请先导出备份。",
        "槽位层级与字段：prepositional phrases 的介词子槽（objects of \"%w\" out 等）已展平为独立搭配条目；每槽位最多前 50 个搭配词型，页面单槽位最多展示 100 行；typical_combo / combo_freq 两列当前导出为空。",
        "本页定位是词目层语料证据浏览 + 两列人工回写；义位层的准入与图式标注在「标注平台」完成，本页不承担义位级判定。"
    ]
},
    "domain": {
    "label": "🧭 域系初判",
    "purpose": "浏览 352 个保留义位按词目层初判归入三域十二系的分布总览与逐条明细，并同屏对照词典释义、双语例句与语料证据，是义位层人工标注前的域—系分类底稿。",
    "principle": [
        "三域十二系体系：352 个保留义位按词目归入方式位移域（264 义位 / 8 系：陆地行进、滚动滑行、奔跑行进、运载工具、腾空跳跃、长途行进、匍匐爬行、飞行游动）、路径位移域（62 义位 / 2 系：终点类、来源类）、互动位移域（26 义位 / 2 系：目的类、参与者类）；总览表按 方式→路径→互动 的固定次序排列。",
        "词目层初判与义位层标注：本页为词目层初判预览（v0.2）——义位图式暂取词目初判（lemma_schema 列），语料得分也是词目层聚合；义位层须按 SenseID 在「标注平台」逐条人工标注（准入 Y/EXT/N → 图式四选一 → 英汉对齐等），最终域—系体系以义位层标注后重聚类为准（届时升级 v1.0 正式体系表）。",
        "筛选规则标签：数据链为 物理位移义位表 358 候选 → R1 剔除 6 条抽象义位 → v0.2 保留 352；表内 R0 = 常规物理位移，R2 = 明确保留的隐喻性空间位移，R3 = 边界案例（保留待双重核验）；R2/R3 行的规则理由列携带判定理由全文，R1 只作用于筛选、保留行不带该标签。",
        "SenseID 结构：主键为 (word, sense_num) 组合键，由 SenseID「动词-Sn」拆分而来，据此定位到词目的具体义项；sense_id 是 STORED 生成列（CONCAT(word, '-S', sense_num)，如 walk-S1），由数据库自动维护、兼容旧引用、不手工写入。",
        "语料证据关联：freq 与 schema_scores 两列把 enTenTen21 词目频次与四图式重心得分挂到每条义位上作标注参考；指数是证据不是结论，最终标签须能被释义 + 例句回溯，边界案例进争议清单人工仲裁。"
    ],
    "data_source": [
        "主表来源：docs/research/tables/域系初判表v0.2.xlsx（01 域系总览 / 02 逐义位明细 / 03 口径说明三张工作表），由 scripts/load_domain_family.py 全量替换灌入 domain_family_senses（--if-empty 可仅空表灌入）。",
        "释义与例句来源：docs/research/tables/词表义项清单.xlsx 两页——「中英对照义位」页提供 dictionary.db 已审校中文释义与双语例句（覆盖 17 词 246 义位，例句按换行拆分后逐条 zip 对齐），「义项明细」页提供 OALD10 全部例句。",
        "例句子表：domain_family_examples（主键 word + sense_num + ex_num，外键级联删除），英文例句与中文翻译按 ex_num 同号同行对齐，source 标注 dictionary.db / OALD10；scripts/update_domain_family_data.py 补入 OALD 全量例句（352 义位约 1050 条，dictionary.db 双语在前、OALD10 补充在后、英文文本去重）并刷新主表首条例句冗余列。",
        "语料证据关联：scripts/update_domain_family_data.py 读取 wsketch_full / schema_evidence JSON，回写主表 freq（BIGINT，词目频次）与 schema_scores（JSON，四图式重心得分 prominence_score 保留两位）；初判表共覆盖 162 词（早期灌数为 127 词、另 35 个路径/互动词后补齐，现为全量）——171 词词表其余 9 词（人工补充义位词与后续捞回词）不在 v0.2 初判表内，故本页无其语料证据行；语料包 data/corpus/ 仍存全部 171 词的检索 JSON。"
    ],
    "steps": [
        "进入页面先读顶部四个指标：保留义位总数（352）、认知域数（3）、语义系数（12）、口径（词目层初判 v0.2）；其下的口径警告图注（义位图式暂取词目初判，非义位层标注结果）务必先看。",
        "看「三域十二系总览」：表格列出每个语义系的 义位数 与 词数（去重词目数），按 方式位移域→路径位移域→互动位移域 排序、域内按义位数降序；条形图直观比较各系义位数体量。",
        "「逐义位明细」三级筛选：第一级「认知域」下拉（全部 / 方式位移域 / 路径位移域 / 互动位移域）；第二级「语义系」下拉随域联动——选定域后只列该域的系，选「全部」时列出全部 12 系；第三级「词目筛选」输入动词关键字（不区分大小写的包含匹配）；表上方图注显示当前筛选条数。",
        "读明细表：列序为 词目 + 义项序号（组合键在前）→ SenseID → 英文释义 → 中文释义 → 词目层初判图式 → 域 → 系 → 义位层标注（待人工）→ 语料频次 → 四图式重心得分 → 规则 → 规则理由 → 数据来源 → 最后修改。",
        "「义位详情」下钻：在「选择义位（word + 义项序号）」下拉（选项来自当前筛选结果，形如 walk · S1）选一条；上方三个指标给出初判域 / 初判系 / 筛选规则标签，正文给出 SenseID（word 与序号）、数据来源与最后修改时间。",
        "看语料证据区：该词目有数据时显示 enTenTen21 词目频次、四图式重心得分（JSON 解析后按得分降序排列）以及候选凸显图式图注（AI 初筛，仅作参考）；无数据时提示「该词目暂无语料证据（初判表未覆盖该词，或语料包缺该词的检索 JSON）」。",
        "读释义与例句区：英文释义逐条展示，中文释义有则显示（dictionary.db 已审校，覆盖 17 词）；例句逐条列出——英文句下一行以「↳」缩进显示对应中文翻译，末尾图注注明例句来源（dictionary.db 带审校翻译 / OALD10 翻译待补）。",
        "关注规则信息：R2/R3 行会在详情区以信息框展示完整「筛选规则理由」；页尾提示该义位的最终图式标签请在「标注平台」人工复核确定，本页初判归属仅作对照参考。"
    ],
    "notes": [
        "本页只读：页面不提供任何编辑入口；义位层标注（准入/图式/英汉对齐）在「标注平台」完成，主表的 sense_annotation 列只是初判表预留列，当前为待人工状态。",
        "词目层局限：图式初判与语料得分都是词目层聚合，多义动词的搭配互相稀释（如 run 的计算机义），不能把本页初判归属直接作为论文最终体系引用。",
        "例句对齐口径：dictionary.db 双语例句在前（带翻译）、OALD10 补充在后（无翻译），英文文本去重；中文释义与双语例句目前覆盖 17 词 246 义位，其余义位仅英文。",
        "freq / schema_scores 为 NULL 表示该词目的 Sketch Engine 检索结果尚未回写（语料包缺该词 JSON 时灌库脚本跳过），不是频次为零，解读时勿与 0 混淆。",
        "重灌口径：load_domain_family.py 全量替换（同一事务先删 domain_family_examples 与 domain_family_senses 再插入）；update_domain_family_data.py 幂等可重跑（先清该义位旧例句再全量写入，频次/得分直接 UPDATE）。",
        "规则标签只有 R0/R2/R3 三种落表；R1 是 v0.1→v0.2 的剔除规则（剔 6 条抽象义位，如 run/race/rush 的抽象义），被剔义位不在本页数据中。"
    ]
},
    "annotate": {
        "label": "🏷️ 标注平台",
        "purpose": "义位级五维标注的操作台：准入标签 → 意象图式 → 英汉对齐 → "
                   "汉语句法特征 / 译义转化策略，逐词逐义项推进。",
        "principle": [
            "判定单元是**义位**而非词目（判定标准文档明确），逐义项独立标注；"
            "词目层的 definitions 行只是主导原型义的摘要。",
            "五条标准链式推进：标准1 准入标签（Y=核心物理位移义、EXT=隐喻拓展义、"
            "N=非位移剔除，判定该义位"
            "是否进入研究范围）→ 标准2 意象图式（源点脱离 / 终点抵达 / 方式伴随 / "
            "互动位移四选一）→ 标准4 英汉对齐（完全 / 部分 / 零 三选一，「错位」"
            "属簇层对齐判定，不在义位层标注）→ "
            "汉语句法特征与译义转化策略。",
            "判定依据 = OALD10 释义 + 例句；页面同屏提供语料证据（AI 初筛候选图式 + "
            "重心得分）辅助判断，但 AI 结果只是候选参考，最终以人工确认为准。",
            "needs_review 与 human_reviewed 语义分开：前者是「复核后仍存疑、需进"
            "仲裁清单」，后者记录「该义位已经人工标注保存过」—— 避免把全部义位"
            "都算成存疑。",
            "🤖 徽章的「LLM 初筛草稿」来自 data/corpus/llm_screening/（智谱模型"
            "对 136 词逐义位的预标注）：准入标签、图式候选、对齐候选、理由与存疑点，"
            "人工可直接在其基础上修改保存。",
        ],
        "data_source": [
            "OALD10 义项：docs/research/tables/output-oald10en-for-senselist-1020.xlsx → "
            "scripts/load_word_library.py → oald_senses 表（996 条 = 992 OALD10 + "
            "4 人工补充，含语法码/例句/习语标记）。",
            "LLM 初筛草稿：data/corpus/llm_screening/*.json → scripts/load_llm_screening.py "
            "→ domain_family_senses 表的 llm_tag/llm_schema/llm_align/llm_reason/llm_doubt 列。",
            "语料证据：corpus_schema_evidence / word_schema_scores 表（enTenTen21 Word Sketch）。",
            "判定标准文档：docs/research/protocols/义项判定标准修改稿.docx（标准链的完整口径）。",
            "标注写回：word_senses / oald_senses 的标注列（幂等，可重复修改）。",
        ],
        "steps": [
            "选择动词 → 该词全部 OALD 义项按序展开（含语法码、例句、习语标记）；",
            "每条义项依次填：准入（Y/EXT/N）→ 意象图式四选一 → "
            "英汉对齐三选一 → 句法特征与译义策略；",
            "带 🤖 徽章的「LLM 初筛草稿」是机器预标注（候选参考，须人工确认）——"
            "直接在其基础上修改保存；",
            "顶部进度条显示该词标注完成度；全部动词的进度看侧边栏「已收录词目」与导出区。",
        ],
        "notes": [
            "保存直接写回 MySQL（word_senses / oald_senses 的标注列），幂等可重复修改；",
            "存疑的边界案例在理由字段打标，进仲裁清单复核；",
            "标注结果可整表导出 CSV（页面底部下载按钮），便于离线核对。",
        ],
    },
    "submission": {
        "label": "📥 标注提交",
        "purpose": "多人标注的提交流视图：选动词 → 选义位 → 在 LLM 初筛草稿基础上"
                   "独立提交准入/图式/对齐/汉语句法/译义策略判定，写入 "
                   "annotation_submissions；同一义位重复提交=覆盖更新。",
        "principle": [
            "独立性（用户决策④）：annotator 只能经「我的提交记录」看到自己的提交，"
            "页面不提供任何他人数据入口；他人提交与分歧清单在仲裁面板"
            "（仅 reviewer/admin 角色可见）。",
            "AI 草稿可见性（用户决策③ / 验收 V7）：全员看同样的 LLM 初筛草稿"
            "（llm_tag/llm_schema/llm_align/llm_reason/llm_doubt）后独立标注，"
            "因此下游信度口径为 AI-assisted IAA。",
            "提交即覆盖（验收 V2）：同一 (sense_id, task_type, coder_id) 唯一，"
            "重复提交整行覆盖且 status 重置为 submitted —— 旧仲裁结论不自动沿用，"
            "需重新进审核/仲裁。",
            "提交内容应用层先校验再入库：admission 必须 ∈ {Y, EXT, N}、needs_review "
            "必须为 bool，非法值不进数据库；留空的可选字段不入提交内容"
            "（缺失 ≠ 空串，避免污染分歧比对）。",
            "表结构由 ensure_flow_tables 首次访问时幂等创建"
            "（annotation_submissions / adjudications / assignments），无需手跑迁移。",
        ],
        "data_source": [
            "义位与状态：oald_senses（get_oald_senses，联 domain_family_senses 的 "
            "llm_* 草稿列）+ get_annotation_progress 的动词进度。",
            "提交读写：src/annotation_flow.py 的 submit_annotation / "
            "get_my_submissions（独立性入口，只看自己）。",
            "判定标准：configs/motion 范畴包 admission.yaml（Y/EXT/N 三分与边界"
            "仲裁条款，页内只读展示）；设计规范 docs/spec/多人标注系统设计规范.md §2/§5。",
        ],
        "steps": [
            "选择动词 → 选择义位（SenseID，选项含当前权威层状态与 LLM 草稿摘要）；",
            "对照「🤖 LLM 初筛草稿」、英文释义与例句（判定标准见范畴包只读面板）"
            "填写表单：准入（Y/EXT/N）→ 意象图式四选一 → 英汉对齐三选一 → "
            "汉语句法特征/译义策略，边界案例勾选「存疑」；",
            "点「提交本义位标注」写入 annotation_submissions（同义位再次提交"
            "=覆盖更新，覆盖后需重新审核）；",
            "在「我的提交记录」核对自己历次提交（submitted/adjudicated 两态）；"
            "分歧清单与定稿在下方仲裁面板（reviewer/admin 角色）。",
        ],
        "notes": [
            "annotator 不可见他人提交（独立性，规范 §0/§1）；需要看分歧清单"
            "请使用 reviewer/admin 账号登录。",
            "准入三值口径与权威层对应：Y=核心物理位移义、EXT=隐喻拓展义、N=非位移"
            "剔除；提交后进入"
            "审核流，最终以仲裁金标为准。",
            "数据库离线时本页不可用（表由 ensure_flow_tables 首次访问创建，"
            "需要 MySQL 可用）。",
        ],
    },
    "users_admin": {
        "label": "👥 账号管理",
        "purpose": "管理员专用：账号创建、角色分配（admin/reviewer/annotator/viewer）"
                   "与停用/启用，多人标注流的权限入口。",
        "principle": [
            "角色语义按设计规范 §1：admin 一切、reviewer 看全部提交并仲裁、"
            "annotator 独立提交互不可见、viewer 只读；改角色/停用的业务规则"
            "（ROLES 枚举校验、rowcount 语义）都在数据层，页面只转译成败。",
            "自保护：当前登录 admin 不能停用自己、不能撤销自己的 admin 角色 ——"
            "否则最后一个管理员把自己锁在门外后，系统再无入口。",
            "密码安全：pbkdf2_sha256 + 每用户随机盐（150000 迭代），哈希不出数据层"
            "（列表不含 password_hash）；新建用户初始密码只在表单内存中出现，"
            "提交后立即从会话清除。",
        ],
        "data_source": [
            "src/users_db.py：create_user / list_users / set_role / set_active；"
            "users 表由 ensure_user_tables 幂等创建（表为空时自动创建内置 admin，"
            "首次登录后必须改密）。",
        ],
        "steps": [
            "顶部指标卡看总用户/启用中/管理员数；只读表格核对账号清单；",
            "「修改角色」选择用户与新角色保存（停用账号 verify_login 返回失败，"
            "不能登录）；",
            "「停用 / 启用」切换登录资格（记录保留，历史提交的外键引用不受影响）；",
            "「新建用户」填用户名/初始密码/显示名/角色创建账号，并通知本人"
            "首次登录后修改密码。",
        ],
        "notes": [
            "仅 admin 可见可用；其他角色从侧边栏看不到本页，强行进入会提示无权限。",
            "内置默认 admin 的初始密码是公开 bootstrap 凭据，首次登录后必须立即修改。",
            "停用 ≠ 删除：提交记录外键引用用户 id，物理删除会断链，因此只提供停用。",
        ],
    },
    "reliability": {
        "label": "📐 信度报告",
        "purpose": "AI-assisted IAA 信度视图：对同一 (范畴, 任务) 的全部已提交标注"
                   "计算 Krippendorff's α（overall + 按指标/特征），高亮低信度项"
                   "并导出分歧清单 CSV。",
        "principle": [
            "口径标注（用户决策③）：所有编码人看同样的 AI 草稿后独立标注，"
            "α 命名为 AI-assisted IAA（全员可见 AI 草稿口径）。",
            "计算双路径：krippendorff 库为主路径，纯 Python 巧合矩阵实现兜底"
            "（库缺失或异常自动启用，RELIABILITY_FORCE_PURE 可强制）；"
            "nominal/ordinal 按 value_type 映射，缺失值容忍（缺若干义位不报错）。",
            "达标线 α ≥ 0.7；低于阈值的指标与分歧条目直接对接仲裁面板"
            "（reviewer/admin 定稿金标后，提交置为 adjudicated 并退出信度口径）。",
        ],
        "data_source": [
            "annotation_submissions（仅 status='submitted'）→ src/reliability.py 的 "
            "run_reliability → 结果写 reliability_runs 留痕；admission 任务对 "
            "admission/schema/alignment 各算 nominal α。",
            "分歧条目导出 CSV（utf-8-sig）；仲裁操作在「📥 标注提交」页的仲裁面板。",
        ],
        "steps": [
            "选范畴（motion）与任务类型（admission / feature_coding / alignment）；",
            "读 overall α 大数字与达标判定；按指标/特征条形图定位低信度项；",
            "展开分歧条目表核对编码人取值冲突；需要仲裁时到「📥 标注提交」页定稿；",
            "点导出按钮下载含分歧清单的 CSV，离线留存。",
        ],
        "notes": [
            "仅 reviewer/admin 可见；annotator/viewer 的侧边栏不出现本页入口。",
            "α 显示为 — 表示不可计算（可用编码人/重叠单元不足），不是 0。",
            "已仲裁（adjudicated）的提交不参与计算；覆盖提交会重置回 submitted "
            "并重新进入口径。",
        ],
    },
    "cluster": {
        "label": "📊 语义分析",
        "purpose": "「跑」范畴语义分析的一页全收工作台（批次 8 合并原「🏃‍♀️ 范畴深挖」"
                   "与「📈 谱系与典型性」）：谱系树与交互切割、典型性、分立复核、义位"
                   "图谱四视图呈现聚类谱系（dendrogram 谱系树 ＋ medoid 中心点三级"
                   "典型性 ＋ G3 闸门），双语聚类对比、编码热图、跨语言对齐、图式对齐、"
                   "总览甄别五视图对应英汉对比研究流水线；「🌐 图式谱系」（批次 32）"
                   "对各簇图式做二级归纳，建立更高层级的事件类型谱系（图式范畴化）。",
        "principle": [
            "研究流水线四阶段，页面后五视图对应：义位甄别（保留/边缘/剔除三态）"
            "→ P/M/C+A 特征编码 → 英汉各自独立聚类 → 双层对齐（簇层人工判定 + "
            "图式层程序推导）。",
            "特征编码 18 列：P1-P5（路径：源点/终点/有界达成/轴向/速度）、M1a-d"
            "（主体：人/动物/车辆/无生）、M2（情态急促度）、M3a-d（介质）、C1"
            "（动因：2 自主 / 1 受迫 / 0 依附）共 15 列进聚类矩阵；A1-A3 仅核验。",
            "聚类算法 Gower 距离 + average 层次聚类（k=5 探索性切分），共表型相关"
            "系数（cophenetic）衡量保真度（英 0.825 / 汉 0.795）；簇对齐判定四类："
            "完全 / 部分 / 零 / 错位（开题报告口径）。谱系树由预计算的 Gower 相异度"
            "方阵经 squareform + average linkage（UPGMA，非加权组平均法）生成，"
            "带 k=5 探索性切分参考线；特征按范畴包 features.yaml 的 value_type "
            "走不同距离分支。",
            "典型性判定：中心点（medoid）＝簇内到其他成员平均 Gower 距离最小的义位；"
            "成员按到中心点的距离三分位自动划为 prototype / typical / periphery，"
            "替代人工判读；谱系树标签页另提供交互式切割（fcluster maxclust 重切，"
            "可保存为新运行版本，与预计算版共存互不覆盖）。",
            "图式层对齐由编码推导（derive_image_schema）：追逐标注 → 互动位移；"
            "P1=1 → 源点脱离；P2/P3=1 → 终点抵达；其余 → 方式伴随 —— 与全词库"
            "四图式体系一致。图式中心 = 两侧成员 15 维均值（/2 归一），阈值 "
            "d<0.05 完全对齐 / d<0.15 部分对齐 / 一侧为空 = 零对齐。",
            "当前数据为程序预编码版本（cluster_runs.version=预编码），正式流程需"
            "双标注独立编码后做 IAA 一致性检验再重跑；schema 按版本共存，可对比。",
            "图式范畴化（批次 32）：对各子簇提炼的事件图式本身再归纳——图式特征"
            "向量＝各语义槽三级归属（核心=2／槽位=1／缺省=0），Gower nominal＋"
            "UPGMA（max_distance=0.5 切割）聚成图式家族，族内平均距离最小者为"
            "代表图式——把义位聚类的同一套机器用在图式对象上（方法论自洽）。"
        ],
        "data_source": [
            "甄别与编码：data/d1/ 跑范畴英汉义位甄别表.xlsx + 编码与独立聚类表.xlsx"
            "（英语 23 词目 32 义位 / 汉语 19 词条 25 义位条目）。",
            "灌库链：scripts/load_category_study.py → categories / cs_lexemes / "
            "cs_senses / cs_sense_features / cs_cluster_runs / cs_clusters / "
            "cs_cluster_members / cs_cluster_alignment 共 8 表；谱系四个标签页读 "
            "cs_clusters / cs_cluster_members / cs_sense_features（跑范畴试点："
            "英语 32 义位、汉语 19 词条），特征元数据来自 configs/motion/features.yaml。",
            "词典证据：《现汉7》mdx（data/ModernChineseDict）→ zh_dict_* 3 表"
            "（70,113 词条 / 94,876 义项），「图式对齐」视图显示词典层规模，"
            "「总览甄别」视图的词典原文对照逐义项关联甄别判定。",
            "AI 聚类参考：数据表内标注「程序预编码」，正式 IAA 编码后以新 run 入库。",
        ],
        "steps": [
            "侧边栏切到「📊 语义分析」，先看谱系侧顶部选范畴与语言（en/zh）；",
            "「🌳 谱系树与交互切割」标签页：查看层次聚类结构与 k=5 切分参考线，拖动"
            "「切割簇数 k」滑块（2–10）实时重切子簇，勾选确认后可「保存为新运行版本」；",
            "「🏆 典型性」标签页逐簇展开：medoid 徽章 + 成员距离条形图 + 三级典型性标签；",
            "「🧬 分立复核」标签页（工序 8 · 闸门 G3）：簇证据视图核对成员/medoid/词频/"
            "cs_senses 现状，登录者发起 merge/split/keep 建议，词典管理员/审校裁决"
            "落地并锁定簇（locked 簇才允许流入释义撰写）；",
            "「🕸️ 义位图谱」标签页：经典多维标度分析（MDS）前两轴散点（簇着色、"
            "medoid 星标「原型居中」），可选显示簇内两两 Gower 距离边表；",
            "「🫱🫲 双语对比」标签页：英 5 簇与汉 5 簇左右配对（按 Gower 距离对齐），"
            "核心发现置顶（方式奔跑图式完全对齐 d=0.045）；点成员展开义位明细；",
            "「🔥 编码热图」标签页：义位 × 18 特征着色网格（P 路径 / M 主体方式 / C 动因"
            "进聚类，A 仅核验），英/汉切换，汉语侧可按保留/边缘/剔除筛选；",
            "「🔀 跨语言对齐」标签页：簇二部图（连线按距离着色）+ 完全对齐簇对的雷达叠加；",
            "「⚖️ 图式对齐」标签页：双层对齐机制说明 + 四类图式（方式伴随/源点脱离/"
            "终点抵达/互动位移）中英对照热图与成员清单 + 双语特征均值对比条形图 + "
            "《现汉7》词典证据链规模卡；",
            "「🌐 图式谱系」标签页（批次 32）：先完成聚类与图式提取（≥2 个子簇"
            "图式），点「⚙️ 计算图式家族谱系」生成家族表与族卡片——代表图式标注"
            "核心要素；结果按范畴×语言会话缓存，点按钮重算；",
            "「📋 总览甄别」标签页：英汉双清单、判定漏斗，以及《现汉7》词典原文对照"
            "（逐义项释义/例句/语域/比喻标记，与甄别判定徽章并排）。",
        ],
        "notes": [
            "数据链：data/d1/ 两个 xlsx → scripts/load_category_study.py → "
            "categories/cs_* 8 表；当前为程序预编码版本，正式流程需双标注 IAA 后重跑；",
            "图式由 P/M/C 编码推导（追逐→互动位移、P1→源点脱离、P2/P3→终点抵达、"
            "其余→方式伴随），与全词库四图式体系一致。",
            "k=5 为探索性切分，正式切分以义位层标注后重聚类为准；典型性阈值为三分位"
            "默认值，可在后续版本配置化。",
        ]
    },
    "template": {
        "label": "🧩 释义模板",
        "purpose": "从每个聚类簇自动提炼母图式（共享要素与可变槽位），并为簇内任一义位实例化四维结构化释义模板，与词典原文逐条对照；同簇并排总览一屏纵览整族统一模式，编者可在线人工修订（按版本留痕），支持批量导出。",
        "principle": [
            "母图式提炼：簇内特征均值 ≥0.5 的二元特征为共享要素（schema_core），"
            "其余为可变槽位；序数/名义特征方差为 0 时记共享取值；"
            "A 组核验特征不进图式、只进句法维度。",
            "模板四维结构：图式维度（簇图式名+定义）/ 语义参数维度（可变槽位+本义位"
            "取值）/ 句法维度（A 组构式论元）/ 对齐预留维度。生成规则为确定性槽位拼装，"
            "不调用 LLM，编者可在此基础上润色成成品释义。"
        ],
        "data_source": [
            "cs_* 聚类表族 + configs/motion/schemas.yaml（图式定义）+ "
            "configs/motion/features.yaml（特征中文标签与值域）+ "
            "oald_senses（原文释义对照）。",
            "人工修订存 template_revisions 表（版本留痕，FX-38）；"
            "修订不可用（库离线）时并排总览与修订面板自动降级为只读引擎基线。"
        ],
        "steps": [
            "选范畴与语言 → 浏览母图式卡片（左栏共享要素、右栏可变槽位）；",
            "看「同簇并排总览」表：整簇义位的词典原文与模板化释义对照一屏对照，"
            "修订过的行带「已修订（vN）」标记；",
            "选簇内义位 → 查看实例化模板四维卡片与词典原文并排对照；",
            "编纂职能（editor/reviewer/dict_admin）在「人工修订」面板直接改模板"
            "文本、填优化要点，保存即生成新版本（历史在面板下方可查）；",
            "用页底按钮把当前簇全部模板导出为 CSV（修订过的义位自动回填"
            "「优化要点」列）或结构化 JSON。"
        ],
        "notes": [
            "模板定位是编者的结构化语义底座，不是面向学习者的成品释义（同论文 §6.4 口径）；导出 CSV 已做公式注入防护。",
            "人工修订是叠加在确定性引擎输出之上的人工层：引擎基线始终并存可对照，"
            "修订按版本留痕、不覆盖历史；锁定簇的修订不改变撰写域已采用的基线"
            "（G3 口径：锁定＝放行撰写，不是禁写）。"
        ]
    },
    "semantic": {
        "label": "🧠 以句搜义",
        "purpose": "用自然语言描述一个运动场景（如「一个士兵整齐地走」），平台把查询"
                   "解析为语义特征向量，按 Gower 距离返回库内最近的义位——"
                   "词形检索之外的语义描述检索入口。",
        "principle": [
            "两层解析：第一层关键词规则匹配（features.yaml 的 keywords 表，"
            "离线确定性）；第二层 LLM 增强解析（默认关，开启且配置了 API key 才生效，"
            "失败静默回退规则层）。",
            "最近邻：只比对查询向量与义位向量共同出现的特征，按实际比对数归一；"
            "距离升序，无共同特征的义位跳过。"
        ],
        "data_source": [
            "cs_sense_features（义位特征向量）+ configs/motion/features.yaml"
            "（关键词与值域）；LLM 增强走 src/llm_api 的多提供商客户端。"
        ],
        "steps": [
            "在搜索框输入自然语言场景描述（如「一个士兵整齐地走」「一匹马在草地上慢慢跑」）；",
            "查看解析出的特征 chips（命中哪些维度），确认解析符合预期；",
            "读最近邻结果表（距离升序），点行展开 OALD 释义核对；需要语义解析更准再打开「AI 增强」开关。"
        ],
        "notes": [
            "规则层完全离线可用；LLM 层输出仅作解析参考，最终范畴归属仍由编者判断（同论文 §7.1 口径）。试点语料之外（如 march 不在 RUN 试点库）会如实提示覆盖范围。"
        ]
    },
    "help": {
        "label": "❓ 帮助中心",
        "purpose": "平台帮助文档的界面入口：按七区菜单逐功能提供「功能说明 / 使用介绍 / "
                   "原理说明 / 注意事项」四段式帮助，支持章节导航与关键词搜索；"
                   "母本是 docs/help/平台功能使用说明.md，本页即其界面渲染。全员可见（含未登录）。",
        "principle": [
            "母本机制：docs/help/平台功能使用说明.md 是全部功能帮助的唯一事实源，"
            "页面建成后对应章节原样迁入应用内「📖 使用说明」面板（page_guides），两处永不漂移。",
            "状态标记约定：【已实现】【阶段1】【阶段2】分层标注——规划中功能的说明即验收标准，"
            "没有说明的功能不算完成。"
        ],
        "data_source": [
            "docs/help/平台功能使用说明.md（随仓库分发，离线可读）；文档缺失时本页降级提示，不抛错。"
        ],
        "steps": [
            "在「章节导航」下拉选择分区（查阅展示/语义建模/…/系统管理）或选「📖 全文阅读」；",
            "在搜索框输入关键词（如「信度」「导入」「盲标」）过滤命中的章节；",
            "注意每条功能的【已实现】/【阶段1】/【阶段2】状态标记，规划中功能的说明即验收标准。"
        ],
        "notes": [
            "本页全员可见（含未登录）——帮助不该有门槛；帮助文档与功能同步交付的纪律见 docs/README.md §五。"
        ]
    },
}

# 批次 2 区级页面：页面模块 GUIDE 原样并入（母本机制——模块 GUIDE 即唯一事实源，
# 集成不复制文本，防两处漂移）；help 置于末尾（区级页面在其前）。
from src.dict_admin_pages import GUIDE as _DICT_ADMIN_GUIDE  # noqa: E402
from src.collab_pages import GUIDE as _AI_HUB_GUIDE  # noqa: E402
from src.writing_pages import GUIDE as _WRITING_GUIDE  # noqa: E402
from src.lexical_pages import GUIDE as _LEXICAL_GUIDE  # noqa: E402
from src.model_settings_pages import GUIDE as _MODEL_SETTINGS_GUIDE  # noqa: E402
PAGE_GUIDES["dict_admin"] = _DICT_ADMIN_GUIDE
PAGE_GUIDES["ai_hub"] = _AI_HUB_GUIDE
PAGE_GUIDES["writing"] = _WRITING_GUIDE
PAGE_GUIDES["lexical"] = _LEXICAL_GUIDE
PAGE_GUIDES["model_settings"] = _MODEL_SETTINGS_GUIDE
PAGE_GUIDES["help"] = PAGE_GUIDES.pop("help")

# 页面键清单（侧边栏 radio 与使用说明共用，保证一一对应）
PAGE_KEYS: List[str] = list(PAGE_GUIDES.keys())


def page_label(page_key: str) -> str:
    """侧边栏标签（未登记的键原样返回，防御未知页面）。"""
    guide = PAGE_GUIDES.get(page_key)
    return guide["label"] if guide else page_key


def render_page_usage_guide(page_key: str) -> None:
    """在页面顶部渲染与 page_key 一一对应的使用说明（折叠 expander）。

    说明结构：定位 → 原理 → 数据来源 → 操作步骤 → 注意事项。
    principle / data_source 为详细版新增段（旧结构缺省时跳过该段）。
    键必须在 PAGE_GUIDES 中 —— tests/test_page_guides.py 会逐页验证
    说明真实渲染，新增页面漏配会被测试拦下。
    """
    guide = PAGE_GUIDES.get(page_key)
    if not guide:
        st.caption(f"⚠️ 页面 {page_key} 未配置使用说明（见 src/page_guides.py）。")
        return

    with st.expander(f"📖 使用说明 —— {guide['label']}", expanded=False):
        st.markdown(f"**这一页做什么：** {guide['purpose']}")

        if guide.get("principle"):
            st.markdown("**🧠 原理：**")
            for item in guide["principle"]:
                st.markdown(f"- {item}")

        if guide.get("data_source"):
            st.markdown("**🗂️ 数据来源：**")
            for item in guide["data_source"]:
                st.markdown(f"- {item}")

        st.markdown("**🖱️ 怎么用：**")
        for i, step in enumerate(guide["steps"], start=1):
            st.markdown(f"{i}. {step}")

        st.markdown("**⚠️ 注意事项：**")
        for note in guide["notes"]:
            st.caption(f"💡 {note}")
