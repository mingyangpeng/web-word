# 阶段 1「立柱」验收报告（架构 v5.1 落地）

> 生成：2026-11-07。口径：全量 `pytest -q --no-cov` **1332 passed / 0 failed**（安静窗口）。
> 基线 610 → **1332**（+722 用例）。多 agent 并行开发：17 个交付 agent（A–N、P–V、Z1），
> 8 个施工批次，契约文件 `docs/spec/阶段1施工规范.md`（§1–§11）。

## 一、交付面（对照架构规范 §3 十五道工序）

| 工序 | 平台能力 | 状态 |
|------|----------|------|
| 1 词典设计 | style.yaml 体例（配置层就绪，工单流批次 8） | 🟡 |
| 3 收词定表 | Levin 词表入库＋导入向导（批次台账＋回滚＋业务写入 definitions UPSERT） | ✅ |
| 4 义位准入 | 准入任务＋AI 草稿＋主动排序 | ✅ |
| 5 特征标注 | 盲标工作台（AI-assisted IAA）＋training 试标轮位 | ✅ |
| 6 信度检验 | α 报告＋特征矩阵导出＋分歧清单 | ✅ |
| 7 聚类归类 | Gower+UPGMA＋**交互式切割（F2 兑现）**＋版本化运行 | ✅ |
| 8 分立复核 | 建议→裁决→cs_senses 落地（merged/split＋merged_into） | ✅ |
| 9 图式模板 | 母图式提炼＋四维模板＋批量导出（确定性引擎） | ✅ |
| 10 释义撰写 | **撰写工作台**（三表状态机＋乐观锁＋回避制硬校验＋G3 locked 消费） | ✅ |
| 11 例证配置 | 三来源＋审定流转＋媒体绑定入口 | ✅ |
| 12 对译定稿 | 三态收口＋辨析栏草稿 | ✅ |
| 13 审校定稿 | 意见线＋审校台（裁决权=受派审校人） | ✅ |
| 15 出版导出 | 导出中心（内容域快照＋§15 闸门）；G6 许可/体例终检页批次 8 | 🟡 |

## 二、横向能力

- **权限**：六角色（user_roles 多角色）＋三级最小权限链＋提权硬闸门（含四旁路封堵）
  ＋个人自助改密＋guards 中央闸门接三敏感写路径；
- **AI 协作**：ai_proposals 台账（draft/audit/probe）＋协作收件箱（待裁决按不确定度
  排序）＋协同度量（采纳率）＋侧边栏待办徽章；
- **一体脊柱**：义项脊柱七段（词条浏览器展开即达全链，按角色脱敏）；
- **基础设施**：wordforms 词形还原检索、媒体资产域（上传通道＋许可必填）、
  导入批次审计＋跨会话回滚、备份纪律、测试库分库（11 个专库授权）。

## 三、界面账

侧边栏 **17 页**：基础六页（search/graph/corpus/domain/annotate/category→已并入）…
终态 14 键：search · graph · corpus · domain · annotate · cluster(语义分析九 tab) ·
submission · users_admin(账号管理) · reliability · template · semantic(以句搜义) ·
dict_admin(七 tab) · ai_hub · writing · lexical · help。
（PAGE_KEYS 14 键＝去 category 并 writing/lexical 后；帮助中心不计入权限表。）

## 四、质量账

- 单元/集成/AppTest 三层；11 个独立测试库授权（`grant_local_mysql.sql` 固化）；
- e2e：`tests/test_stage1_e2e.py` 七步协作真库走查——**零链路断点**；
- 文档：架构规范 v5.1、功能使用说明 24+ 功能四段式（母本机制与 page_guides 同源）、
  施工规范 §1–§11、CHANGELOG、本报告。

## 五、遗留（批次 8 / 阶段 2，均有占位锚点）

1. G6 出版页（许可/体例终检清单接 export_center）＋style.yaml 工单流；
2. 词典管理员终裁接口（reviewed→approved→final 展开）＋审校改派（assignments 域）；
3. oald_senses 追加写入（学术决策待定）；revert_log 已持久化，跨会话回滚已通；
4. 数据层 API 级闸门全量收口（现三敏感路径＋users_admin 四路径已接）；
5. 义位级图谱增强、簇级定稿锁定消费（阶段 2 装配侧）、侧边栏分区折叠美化。
