# 跨词类复用验证报告（speech 验证帧 · 批次 9）

> 生成：2026-11-07（Agent AT）。判据（思路文档第 16 步）：**仅通过编写配置包
> （引擎零修改）走完五步**。脚本：`scripts/verify_category_reuse.py`（--json 可机器读）。

## 五步验收表

| # | 步骤 | 判定 | 数据缺口 |
|---|------|------|----------|
| 1 | 义位筛选 | ✅ 架构就绪 | 无候选义位池 |
| 2 | 特征标注 | ✅ 架构就绪（6 特征三型齐） | 无义位可标 |
| 3 | 聚类 | ✅ 架构就绪（Gower 按类型分支零假设） | 无编码数据 |
| 4 | 图式提取 | ✅ 架构就绪（evidence_slots 引用闭合实测） | 无语料统计 |
| 5 | 模板实例化 | ✅ **架构就绪（批次 10 R-1 已收口，4653 例差分对拍 motion 逐字不变＋speech 实渲染）** | 无真实义位数据 |

**结论（批次 10 终版）：五步 5/5 ✅——「仅通过编写配置包（引擎零修改）走完五步」的复用判据已验证成立。** R-1 收口证据：模板拼装表外置三包 schemas.yaml `template_assembly` 节；`grep` 引擎词类名词清零；4653 组向量差分对拍 motion 输出逐字符不变；speech 直渲染言说动词词面（「作出陈述/就话题/正式度」），零 motion 残留。R-3/R-4/R-5 保持开放（灌数链/提示词消费/锚统一）。

## 复用断点清单（批次 10 待收口）

- **R-1 ✅ 批次 10 已收口（原唯一阻断）** `template_engine` 槽位拼装表硬编码 motion 特征码（M1a–M1d/P5/M2/M3a–M3d/P1–P4＋「自源点出发」词面）——speech 特征不在表内，实测渲染「主体不限，移动」；**违框架 §4「引擎出现词类名词即违规」**。收口：拼装表外置进范畴包（schemas.yaml 或新 template.yaml）。
- **R-2 ✅ 批次 10 已收口**：准入 expander 改按 CATEGORIES() 首包动态取数，expander 标题注明 configs/{cat}。
- **R-3** `PACK_TO_STUDY_CODE={"motion":"RUN"}` 且灌数链只装 d1——speech 无研究登记名与灌数支持（框架 §5 第三步缺引擎口）。
- **R-4** `prompts/screening.txt` 被 selfcheck 校验但无引擎消费（生产初筛走 llm_screening JSON）——「占位符自检通过≠提示词被使用」，论文措辞需避开或补消费链。
- **R-5** 义位锚分裂：writing_db 三段式（`speech:12:345`）vs lexical_db 裸 `str(sense_id)`——e2e 已证三段式可穿透两层，批次 10 统一。

## 附带修复

- writing_db/lexical_db 的 `STATUS_PUBLISHED` 同名异物（"published" vs "发布"）别名收口；
- Z1 e2e 弹池键 f-string 与 `mysql_db._pool_key()` 四元组不符——stage2 fixture 已按四元组收口（Z1 原文件留待批次 10 对齐）。
