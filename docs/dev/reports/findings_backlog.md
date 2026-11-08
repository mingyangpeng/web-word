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
