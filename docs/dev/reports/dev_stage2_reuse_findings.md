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
| 5 | 模板实例化 | ⚠️ 机制就绪＋**R-1 断点** | 无数据；灌数后仍是 motion 词面产物 |

**结论：配置层复用成立（selfcheck/加载/页面点亮全绿）；第 5 步存在引擎侧词类硬编码，是复用收口最后一个断点。**

## 复用断点清单（批次 10 待收口）

- **R-1（唯一阻断）** `template_engine` 槽位拼装表硬编码 motion 特征码（M1a–M1d/P5/M2/M3a–M3d/P1–P4＋「自源点出发」词面）——speech 特征不在表内，实测渲染「主体不限，移动」；**违框架 §4「引擎出现词类名词即违规」**。收口：拼装表外置进范畴包（schemas.yaml 或新 template.yaml）。
- **R-2** `app.py` 标注页准入 expander 硬编码 `load_pack("motion")`——speech 义位永远显示移动动词口径。收口：按当前义位所属范畴取包。
- **R-3** `PACK_TO_STUDY_CODE={"motion":"RUN"}` 且灌数链只装 d1——speech 无研究登记名与灌数支持（框架 §5 第三步缺引擎口）。
- **R-4** `prompts/screening.txt` 被 selfcheck 校验但无引擎消费（生产初筛走 llm_screening JSON）——「占位符自检通过≠提示词被使用」，论文措辞需避开或补消费链。
- **R-5** 义位锚分裂：writing_db 三段式（`speech:12:345`）vs lexical_db 裸 `str(sense_id)`——e2e 已证三段式可穿透两层，批次 10 统一。

## 附带修复

- writing_db/lexical_db 的 `STATUS_PUBLISHED` 同名异物（"published" vs "发布"）别名收口；
- Z1 e2e 弹池键 f-string 与 `mysql_db._pool_key()` 四元组不符——stage2 fixture 已按四元组收口（Z1 原文件留待批次 10 对齐）。
