# 开发报告：以句搜义 MVP（一句话找意思：自然语言 → 特征向量 → 库内 Gower 最近邻）

> 页面更名记录：本页原名「AI 语义检索」，因与首页「搜索释义」名字相近易混
> （两者方向相反：搜索释义输入词形查释义，本页输入句子描述反查义位），
> 更名「以句搜义」。模块名 `semantic_search.py` 与内部函数名不变，
> 下文历史段落中的「AI 语义检索」均指本页。

> 对应 `docs/p1/白话版对照清单.md` 第三档 F1（论文 §7.1 第二模式：
> 输入「一个士兵整齐地走」→ 自动找到 march 类义位）。
>
> 交付：`src/semantic_search.py`（新）、`tests/test_semantic_search.py`（新）、
> `configs/motion/features.yaml` **只增补**可选字段 `keywords`（15 项进聚类特征
> 的关键词表，既有字段一律未动，`run_selfcheck('motion')` 与 `speech` 包自检通过）。
> 未改动任何受约束文件（app.py / page_guides.py / template_engine.py /
> cluster_analysis.py / users_db.py / annotation_flow.py / reliability.py /
> security.py）；`src/llm_api.py` 只读 import（AI 增强层调用其多提供商客户端，
> 未改动）；`requirements.txt` 的 scipy 是聚类分析任务预先加入的，本任务未触碰。
>
> **MVP 不依赖 LLM 也能跑：规则层离线确定性可用，LLM 仅增强（默认关）。**

## 1. 交付面一览

| 需求（任务口径） | 实现 | 入口 |
|---|---|---|
| 查询句 → 特征向量（两层策略） | 第一层规则匹配（features.yaml `keywords` 关键词表，子串匹配）；第二层 LLM 增强（可选开关，失败静默回退第一层） | `parse_query_to_features(query, pack, use_llm=False) -> dict` |
| 解析明细（页面展示用） | 规则向量 / LLM 向量 / 命中触发词 / 来源标记 | `parse_query_detail(query, pack, use_llm=False) -> dict` |
| 库内 Gower 最近邻 | 取该范畴 × 语言全部义位的 in_clustering 特征向量（cs_sense_features），Gower 距离升序 | `search_similar_senses(feature_vector, category, language, top_k=10) -> list[dict]` |
| Streamlit 页 | 搜索框（placeholder=论文例句）→ 命中特征 chips（带触发词标注）→ 最近邻表（距离升序）→ 逐条展开词典释义 → 「AI 增强」开关（默认关）→ 空查询/无命中/无库优雅降级 | `render_semantic_search_page()`（集成步骤挂进 app.py，本模块不改 app.py） |

## 2. 架构与数据流

```
configs/motion/features.yaml ──(load_pack)──► 特征元数据 {code: label/value_type/values/keywords}
                                                    │
查询句 ──► 第一层 规则匹配 _rule_match（关键词表，离线确定性）
              │   同特征多关键词命中：更长词面优先（「快走」胜过其子串「走」），
              │   平局取位置最靠后者（最后提到的限定语优先）；未命中特征不进向量
              ▼
        （可选）第二层 LLM 增强 _llm_parse_features
              │   提示词内嵌特征清单+值域 → llm_api.get_llm_client 多提供商
              │   → 回复提取 JSON → 值域校验（越界值/未知特征/核验区丢弃）
              │   → 合并进规则向量；任何失败静默回退，绝不抛错
              ▼
        查询向量（稀疏）{M1a: 1, M2: 0, ...}
              ▼
search_similar_senses ──► cs_senses JOIN cs_lexemes JOIN categories（范畴/语言过滤）
              │           cs_sense_features（in_clustering=1 的 P/M/C 15 列）
              ▼
        Gower 距离（复用 src/cluster_analysis.gower_distance，同一口径）
        只比对「查询向量中出现 且 义位也编码」的特征；缺失跳过、按实际比对数归一
        无任何共同特征的义位跳过（Gower 对空比对记 0，直接采纳会把未编码义位排到最前）
              ▼
        [{sense_id, verb, sense_no, sense_label, distance, matched_features,
          definition, source_dict, status, language}] 距离升序（平局按 sense_id）
```

分层原则与 test_cluster_analysis / test_template_engine 相同：**纯函数核心
（合成数据全测）+ DB 编排**（失败降级返回 `[]` / `None` 并记日志，不崩）。

### 2.1 范畴名解析

`category` 参数接受范畴包名（`motion`）或研究代号（`RUN`）：先按 categories.code
直取，包名经 `cluster_analysis.PACK_TO_STUDY_CODE`（motion → RUN）映射后直取
（测试断言两别名结果逐条一致）。

## 3. 规则层口径（确定性）

### 3.1 keywords 字段（features.yaml 增补）

每个进聚类特征的可选字段 `keywords`，条目两种写法：

* `{kw: 关键词, value: 编码值}` —— ordinal/nominal 显式赋值（如 P5 的
  `{kw: 快, value: 2}`）；
* 裸字符串 —— binary 特征省略 value，按「取 1」处理（解析器同时兼容两种）。

任务指定的映射逐条在场（测试 `TestKeywordConfig.test_task_required_mappings`）：
士兵/队伍 → M1a=1；快/急速 → P5=2；慢/缓 → P5=0；自主/自愿 → C1=2；被迫/逃 → C1=1。
完整表（motion 包，M3d「介质-其他」无法枚举、A 组核验区不进检索向量，均留空）：

| 特征 | keywords（value） |
|---|---|
| P1 源点凸显 | 逃离/离开/出发/脱离/撤离 (1) |
| P2 终点凸显 | 抵达/到达/赶到/冲向/终点 (1) |
| P3 有界达成 | 跑完/走完/穿过/跨过/渡过 (1) |
| P4 轴向垂直 | 爬上/爬下/上升/下降/降落/升起 (1) |
| P5 速度 | 快/急速/飞速/迅速/疾/狂 (2)；中速 (1)；慢/缓/徐/散步/慢走/缓步 (0) |
| M1a 主体-人 | 士兵/队伍/人/人群/孩子/男人/女人/运动员/犯人 (1) |
| M1b 主体-动物 | 马/动物/狗/猫/狼/鹿/牛/羊/狮/虎/鸟 (1) |
| M1c 主体-车辆工具 | 车/船/飞机/火箭/列车 (1) |
| M1d 主体-无生液体 | 水/液体/岩浆/熔岩/洪水/血 (1) |
| M2 情态急促度 | 急促/匆忙/慌忙/仓促/慌张/猛冲 (2)；整齐/从容/悠闲/平稳/轻缓/稳步 (0) |
| M3a 介质-陆地 | 陆地/地面/地上/路上/跑道/街上/草地/山路/地板 (1) |
| M3b 介质-水 | 水中/水里/水面/游泳/涉水/渡河/潜水 (1) |
| M3c 介质-空气 | 空中/天上/天空/飞翔/翱翔/滑翔 (1) |
| C1 动因 | 自主/自愿/主动/自发 (2)；被迫/逃/驱赶/强制/不得不 (1)；跟随/跟着/追随/押送 (0) |

设计要点：裸「走」刻意不进 P5 关键词表（「快步走」这类短语不能误判低速）；
「整齐」映射到 M2=0（轻缓）——行进步态有序、不急促，是最接近的情态编码。

### 3.2 冲突消解

同一特征多个关键词命中：**更长关键词优先**（更具体的词面胜过其子串，
如「快走」胜过「走」——子串天然出现在更靠后位置，只看位置会判反）；
等长平局取查询中位置最靠后者（「先快后慢」→ 慢）。规则确定性，测试覆盖。

## 4. LLM 增强层（默认关，失败静默回退）

* `use_llm=False`（默认）不创建客户端、不发任何请求（测试断言客户端工厂
  被替换成炸弹也不触发）。
* `use_llm=True`：`src/llm_api.get_llm_client()` 多提供商客户端
  （智谱 / OpenAI / DeepSeek，按 key 优先级），提示词内嵌全部进聚类特征的
  清单与值域（如 `P5 速度（ordinal）: 0=低、1=中、2=高`）；temperature=0.0
  （结构化解析要确定性，不沿用释义生成的 0.7）。
* 回复提取 JSON（兼容 ```json 围栏）后逐项校验：未知特征 / 核验区特征 /
  越界取值丢弃；剩余项合并进规则向量（补充规则层覆盖不到的表达）。
* 无 key / 断网 / 超时 / 非法 JSON / 校验后为空 → 一律静默回退规则层结果
  （测试用假客户端覆盖全部分支，无网络依赖）。

## 5. Gower 检索口径

* 距离函数直接复用 `cluster_analysis.gower_distance`（binary/nominal 不一致
  记 1，ordinal 按 |a−b|/值域跨度），value_type 与值域读自范畴包 features.yaml
  （`cluster_analysis.load_feature_types`，包缺失时未知特征按 nominal 降级）。
* **只比对查询向量中出现且义位也编码的特征**，缺失跳过、按实际比对数归一
  （任务口径）；`matched_features` 记录该结果实际参与比对的特征码（升序）。
* 无任何共同特征的义位跳过——cs_sense_features 对无编码义位没有行（D1
  剔除义位不进编码矩阵），若采纳 Gower 的「空比对记 0」约定会把它们错误地
  排到最前。
* 排序：距离升序，平局按 sense_id 稳定；`top_k` 截断（None / ≤0 返回全部）。

## 6. 三个真实查询端到端样例（真实 MySQL RUN 试点库，程序真实输出）

样例 1 是论文 §7.1 的原始例句（英汉两侧都跑）。

**样例 1：「一个士兵整齐地走」（汉语侧，现汉7）**

```
命中特征：M1a=1（人主体）←「士兵」，M2=0（轻缓）←「整齐」
解析方式：规则关键词匹配（离线）  向量 {M1a:1, M2:0}
Top3：
  1. 小跑「—」小步慢跑义  d=0.000  比对 M1a,M2  〔现汉7〕快步走，接近于跑；小步慢跑
  2. 跑① 快速奔跑义       d=0.250  比对 M1a,M2  〔现汉7〕两只脚或四条腿迅速前进（脚可以同时腾空）
  3. 逃遁「—」逃遁义      d=0.250  比对 M1a,M2  〔现汉7〕逃跑；逃避
```

**样例 1（英语侧，OALD10）**：march 不在 RUN 试点甄别表（见 §7 说明），
最近邻为低速率人主体奔跑义位（库内这些义位 M2 全为 1「一般」，与查询的
M2=0 相差半档 → 0.25）：

```
命中特征：M1a=1（人主体）←「士兵」，M2=0（轻缓）←「整齐」
Top3：
  1. run1  足部奔跑义 d=0.250 比对 M1a,M2 〔OALD10〕to move using your legs, going faster than when you walk
  2. run2  跑完里程义 d=0.250 比对 M1a,M2 〔OALD10〕to travel a particular distance by running
  3. run3  跑步运动义 d=0.250 比对 M1a,M2 〔OALD10〕to run as a sport
  （jog1 慢跑义 / trot3 碎步快走义 等以 0.250 并列，按义位 id 稳定排序）
```

**样例 2：「一匹马在草地上慢慢跑」（英语侧）**

```
命中特征：P5=0（低）←「慢」，M1b=1（动物主体）←「马」，M3a=1（陆地介质）←「地上」
Top3（0.000 并列，按义位 id）：
  1. run1    足部奔跑义   d=0.000 比对 M1b,M3a,P5 〔OALD10〕（run 编码 M1a=1+M1b=1 人/动物主体）
  2. gallop1 马飞驰义     d=0.000 比对 M1b,M3a,P5 〔OALD10〕when a horse or similar animal gallops…
  3. gallop2 骑马飞驰义   d=0.000 比对 M1b,M3a,P5 〔OALD10〕to ride a horse very fast…
  （canter1 马小跑义 / trot1 马小跑义 等亦 0.000 并列）
```

**样例 3：「人们被迫逃走」（英语侧）**

```
命中特征：M1a=1（人主体）←「人」，C1=1（受迫）←「被迫」
Top3（0.000 并列，按义位 id）：
  1. charge7 冲锋义 d=0.000 比对 C1,M1a 〔OALD10〕to rush forward and attack…
  2. charge8 冲奔义 d=0.000 比对 C1,M1a 〔OALD10〕to rush in a particular direction
  3. rush1   冲奔义 d=0.000 比对 C1,M1a 〔OALD10〕to move or to do something with great speed
  （flee1 逃离义 / escape1,2 / bolt4 / scurry1 / scuttle1 等受迫人主体义位亦 0.000 并列）
```

**AI 增强对照**：样例 1 开启 AI 增强且配置 LLM key 时，LLM 会补充
P5/M3a/C1 等规则层覆盖不到的特征（合并向量 {M1a:1, M2:0, P5:0, M3a:1,
C1:2}，来源标记 rules+llm），小跑① 在 5 项比对上仍以距离 0 居首、且
matched_features 升到 5 项（`test_llm_merged_vector_sharpens_match` 用假
客户端断言此行为；本环境未配 key，真实运行即静默回退规则层——降级路径
同样被测试覆盖）。

## 7. march 与试点库的边界（如实说明）

论文例句的目标词 **march 不在 RUN 试点甄别表的 23 个英语词目内**
（march 属步行范畴；与 `docs/dev_template_engine.md` §8 记录的是同一事实）。
本 MVP 的检索机制与词类无关（范畴包配置化，换 configs/<category>/ 即换词类），
示例展示的是机制在现有 RUN 试点库上的真实输出：汉语侧 小跑① 以距离 0 命中
（「快步走，接近于跑」与「士兵整齐地走」在 18 特征体系中的编码完全一致），
英语侧最近邻为 run/jog/trot 族。待步行范畴灌库后，同一查询即按相同机制命中
march 的对应义位——论文措辞建议写「机制已实现并以试点范畴验证，march 例
依赖步行范畴扩库」。

## 8. 页面

`render_semantic_search_page()`（app.py 接线由集成步骤统一做）：
范畴包 / 语言选择器 → 搜索框（placeholder「例如：一个士兵整齐地走」）→
「AI 增强」开关（默认关）→ 空查询显示引导语 → 解析出的特征向量 chips
（编码 + 中文值标签 + 触发词「←士兵」，按特征组着色，全部过 `_html_escape`）
→ 最近邻 `st.dataframe`（距离/词/义项/义位标签/比对特征，距离升序）→
逐条 `st.expander` 展开（词典原文释义 + 状态 + 比对特征 + 义位 id；释义走
st.markdown 默认转义，不做 unsafe HTML）。无查询 / 无命中 / 无库 / 范畴包
失败均优雅降级不抛错；检索索引 `@st.cache_data(ttl=600)` 页面级缓存。
AppTest 无头冒烟：空查询引导语、合成索引下 chips+结果表+展开卡齐全、
无命中降级、真实 RUN 汉语侧 小跑 居首且 10 条展开卡。

## 9. 测试

`tests/test_semantic_search.py` **43 项全绿**（`pytest -q`：基线 511 → 554，
零回归）：

| 层 | 覆盖 |
|---|---|
| 关键词配置完整性（读 features.yaml） | 进聚类特征（M3d 除外）都配 keywords、value 全部落在值域；A 组核验区不配；任务指定映射（士兵/快/慢/自主/被迫/逃）逐条在场 |
| 规则解析（不碰库） | 论文例句 → {M1a:1, M2:0}；速度/主体/介质/垂直/路径/动因各关键词族赋值；冲突消解（更长词面优先、等长取后位）；空查询/无命中 → {}；keywords 字段可选（裸字符串 = binary 取 1、value 0 显式赋值）；核验区特征即使配词也不进向量；detail 分层明细 |
| LLM 增强（假客户端，无网络） | 开关关闭不触客户端；合法 JSON 合并 + 越界值/未知特征过滤 + 提示词契约（模型名、查询句、值域标签）；非法 JSON / 客户端不可用 / 抛异常 / 空查询均静默回退 |
| Gower 最近邻（合成索引，不碰库） | 已知距离序 aa(0) → ff(0,平局 id 稳定) → cc(1/6) → bb(1/4) → dd(1)，空向量 ee 跳过；缺失特征按实际比对数归一（cc 分母 3、ff 分母 1）；无共同特征跳过；top_k 截断与不截断；索引缺失降级；包元数据缺失按 nominal 降级；返回键契约 |
| MySQL 路径（skipif，与 test_cluster_analysis 同口径） | 三个真实查询端到端（§6 的断言固化：小跑① 0.0 / run 族 0.25 / gallop 族 0.0 / charge-rush 族 0.0）；AI 增强合并向量 5 特征居首；RUN 别名与 motion 结果一致；未知范畴空返回 |
| 页面（AppTest） | 空查询引导语 + 开关在场；例句 + 合成索引 → chips（含触发词）+ 结果表 + 展开卡距离升序；无命中优雅降级；真实数据 zh 冒烟（小跑 居首、10 条展开卡） |

flake8（max-line-length=100）对两个新文件零告警；mypy 对新模块仅剩环境级
pandas stubs 缺失一条（与既有 src/cluster_analysis.py 等同类），两个
no-any-return 已顺手修复。

## 10. 边界与后续

* 规则层是词面匹配，不处理否定/歧义（「不快」会命中「快」）；这正是
  LLM 增强层的职责分工——开关打开后由 LLM 按整句语义解析并合并。
* 单字关键词（人/马/水/车/逃）按中文子串匹配，无分词依赖，但存在少量
  误触发面（如「马拉松」命中「马」）——MVP 取召回优先，误触发进入向量
  后只影响距离权重，不产生报错；后续可加最长词面优先的停用表。
* march 例依赖步行范畴扩库（§7）；跨范畴联合检索（一次查多范畴）与
  义位级语义图联动是后续工作。
