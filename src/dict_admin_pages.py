"""词典管理区页面 —— 词典管理员工作台（主编驾驶舱 · 项目成员 · 定制属性 · 媒体库）。

阶段 1 批次 2 Agent F（docs/spec/阶段1施工规范.md §5-F）：词典管理区一个菜单项，
页内 st.tabs 分区；数据全部来自批次 1 数据层（只读调用，不重复实现业务规则）：
  * src/org_db.py          项目壳与成员册（selfcheck 体检数据源）
  * src/ai_ledger.py       AI 协作台账（get_stats 驾驶舱指标）
  * src/dict_admin_db.py   定制属性 EAV（字段定义/弃用/写值）
  * src/users_db.py        花名册与六角色（选人、dict_admin 实时兜底判定）
  * src/media_db.py        媒体资产两表（批次 4 增设 🖼️ 媒体库 tab）
  * src/registry_db.py     资源登记（批次 11 增设：D⑥ resource_registry，
                           G6 许可终检的数据面）

是什么（平台架构设计规范 §8/§9 词典管理区阶段 1 MVP）：
  * 主编驾驶舱：项目自检问题清单（绿=✓ 无阻塞）+ AI 台账关键指标卡 + 项目/成员
    规模统计；进度漏斗数据源（get_cluster_pipeline_status）批次 3 才建，如实标注；
  * 项目成员：项目下拉 + 成员表 + 添加成员（入册/改授）与移出表单 —— chief 不可
    移除、在途任务未改派被拒等 org_db 拒绝一律转成 st.warning 转述，不静默；
  * 定制属性：定义字段（code/展示名/挂锚/值类型/枚举白名单/必填声明）+ 字段列表
    （含弃用按钮，停写不删）+ 为锚写值（一字段一锚一值，重复写即改值）——
    dict_admin_db 校验失败（0/False 返回）转 st.error 展示；
  * 🖼️ 媒体库（批次 4 Agent M；批次 8 Agent W 开通上传落盘通道）：登记资产
    **双轨**——①上传落盘（png/jpeg/jpg/mp3/mp4，单文件 ≤50MB，写 data/media/
    {kind}/YYYYMM/ 后走同一条登记链）②服务器路径登记（license 必填，sha256
    去重「已存在复用」）· 资产列表（按状态筛选）· 绑定资产（四锚 × 用途）·
    绑定列表与审定流转（候选→审定→发布，逐级单步）——**数据资产归词典管理员**
    口径（帮助文档 §4.5/§六：媒体是展示层资产，许可纪律是无许可不入库）。
  * 📤 出版导出（批次 8 Agent G6；工序 15，G6 闸门执行页；批次 11 AV2 灰注
    转硬检）：G6 检查清单三卡（许可终检=resource_registry 逐行 license 审计，
    表随页面自举建、0 行=「空过（未登记资源）」注明，有空行=未过 n/m／体例终检
    =configs/style.yaml 在场＋含 style_version 字段（展示体例版本），缺失=
    「体例文件未研制」灰注／备份新鲜=data/backups/ 最新 *.sql.gz/*.tar.gz
    mtime（scripts/backup_db.sh 落地产物），无=「备份任务未运行」灰注）＋
    🗂️ 资源登记块（登记表单 name/version/coverage/license 必填＋资源清单，
    registry_db 数据面；双人双签审定线批次 12）＋内容域快照（guards 闸门→
    export_center.build_content_snapshot 只读调用）＋快照清单与状态流转
    （ready→published 需三项全过；ready→revoked 撤销单向不可逆）——**占位项
    不拦内部快照（MANIFEST 如实标注），拦 published**（§15 内容性导出唯一
    权利人=词典管理员）。

页面行为依据 docs/help/平台功能使用说明.md §六（词典管理区）；风格对齐
src/users_admin_page.py（role gate 入口判定 + HTML 转义 + 卡片表格）。

权限（纵深防御，规范 §15 导入/内容操作同权）：入口两层判定 ——
  1. 会话纯函数 _is_dict_admin：role == 'admin'（过渡期：内置 admin 兼有
     dict_admin/sys_admin，users_db 迁移口径）或 roles 列表含 'dict_admin'；
  2. 会话不放行时再实时查库 users_db.has_role(id, 'dict_admin') 兜底
     （会话快照滞后于授权的场景，如先登录后被授予角色）。
两层都不过 → st.warning「仅词典管理员」并 return，页面内容不渲染。

widget key 一律 'dict_admin_' 前缀（见各 st.* 调用 key=）；用户生成内容
（项目名/用户名/展示名/字段 code/枚举值/媒体路径与图注等）进 unsafe_allow_html
前一律过 _esc；selectbox/expander 的选项文本由 Streamlit 自带转义，不需（也不能）
先转义。

由集成步骤挂载（render_dict_admin_page() 注册进 app.py 分派 + GUIDE 并入
PAGE_GUIDES['dict_admin']）；本模块不修改 app.py / page_guides.py。

媒体查询与流转（R6-12 起归 media_db 数据层单一实现）：资产列表
  media_db.list_assets、绑定审定流转 media_db.advance_binding_status
  （R3-4a：流转时写入审定留痕 reviewed_by/reviewed_at；乐观并发守卫
  WHERE status=当前态）、下一态查表 media_db.next_binding_status；
  本模块仅余两个只读私有辅助：_find_asset_by_sha256 / _list_media_bindings
批次 8 上传通道（落盘后复用 register_asset 登记链，license/sha256 口径不变）：
  纯函数 _validate_upload（扩展名/MIME 白名单 + ≤50MB + R2-2 内容魔数一致性：
  声明 image 须 PNG/JPEG 魔数，svg/script 伪装 png 落盘前被拦）与
  _upload_target_path（内容寻址落盘路径，tests 直接测）；
  页面 _render_media_upload_form（不抛异常，失败一律 st.error）。
批次 8 出版导出（G6）：纯函数 _g6_license_summary / _g6_style_summary /
  _g6_backup_summary（三卡摘要，DB/文件系统探测以可注入函数为默认实现，
  tests 直接测）＋ _g6_gate_blockers / _g6_gate_open / _g6_license_passed
  （闸门判定）＋ _advance_export_status（快照状态单步流转，export_center
  契约未含的私有辅助，乐观并发守卫；R3-4b：published 流转写入出版留痕
  published_by/published_at）；页面 _render_publication_tab；
  widget key 前缀 'pub_'（本 tab 内）。
批次 11 AV2（G6 小尾巴收口：灰注转硬检）：体例终检升级为「style.yaml 在场
  ＋含 style_version 字段」硬检（纯函数 _g6_style_version，展示体例版本，
  缺失=「体例文件未研制」占位；体例文件 configs/style.yaml 本批次研制）；
  备份新鲜升级为扫 data/backups/ 最新 *.sql.gz / *.tar.gz（纯函数
  _g6_scan_backups，scripts/backup_db.sh 落地产物，无=「备份任务未运行」
  占位，快照≠灾备备份）；许可终检数据面接通（页面自举
  registry_db.ensure_resource_registry_tables，0 行=「空过（未登记资源）」
  注明）；新增 🗂️ 资源登记块（纯函数 _registry_form_error ＋
  _render_registry_form / _render_registry_table，写路径 guards 闸门后调
  registry_db.register_resource，UNIQUE(name, version) 去重）。
"""

import hashlib
import logging
import math
import os
import re
from datetime import date, datetime
from html import escape as _html_escape
from typing import Any, Callable, Dict, List, Optional, Tuple

import streamlit as st

from src import ai_ledger, dict_admin_db, export_center, media_db, org_db
from src import registry_db
from src import pipeline_status, users_db
from src.db_utils import current_user as _current_user  # R6-4：单一实现点
from src.mysql_db import get_db_cursor
from src import guards
from src.design_system import (
    HEADER_H1,
    HEADER_H2,
    HEADER_H3,
    REVIEW_STATUS_COLORS,
    get_card_style,
    get_table_header_style,
    get_table_row_style,
)

logger = logging.getLogger(__name__)

# ============================================
# 页面使用说明（四段式；集成时原样并入 PAGE_GUIDES["dict_admin"]）
# ============================================

GUIDE: Dict[str, Any] = {
    "label": "📖 词典管理",
    "purpose": (
        "词典管理员的工作台（阶段 1 MVP）：主编驾驶舱一页看清项目自检与 AI 台账"
        "指标，项目成员维护三级权限链的第二级（入册/改授/移出），定制属性定义 EAV "
        "字段并为锚写值，媒体库登记/绑定/审定多模态资产（数据资产归词典管理员；"
        "批次 8 开通上传落盘通道，与服务器路径登记双轨并行），出版导出执行 G6 "
        "出版闸门（许可/体例/备份三检＋内容域快照，批次 8 开通）。"
    ),
    "principle": [
        "三级最小权限链（平台架构设计规范 §8）：平台管理员建号（默认 viewer）→ "
        "词典管理员在本页把人入册项目（project_members 项目内职能 "
        "chief/reviewer/editor/annotator/viewer，一人一项目一职，重入=改授）→ "
        "词典管理员再分派具体任务；任何一级缺失下游不生效，平台管理员不得自行提权。",
        "chief 不可移除、每项目 ≥1 名在用 chief 是 project_selfcheck 硬约束——chief "
        "是词典管理员在项目内的化身，摘掉主编项目就无人执行词典管理员职能；成员有在途"
        "任务（assignments open/in_progress）时 remove_member 拒绝，须先改派再移出。",
        "词典管理员是内容性数据的唯一权利人（§15 导入同权）：定制属性字段与值的定义"
        "只归 dict_admin（项目内即 chief）；页面入口做纵深防御角色门（会话判定 + 实时 "
        "has_role 兜底），数据层不再重复判定。",
        "定制属性是 EAV 模型（custom_fields + custom_values）：字段挂 "
        "word/sense/example 三类锚，值类型 text/number/enum/date/bool；enum 字段定义时"
        "必须给白名单；字段只有 active/deprecated 两态——弃用只停写不删行，历史值一直"
        "可展示。",
        "AI 协作台账（ai_proposals）是三通道 AI 提议的留痕线：驾驶舱只读 get_stats "
        "展示总数/待裁决/采纳率/平均不确定度，裁决动作在 AI 协作区收件箱完成，本页不做"
        "裁决、不写台账。",
        "进度漏斗如实缺位：十五道工序的进度数据源（get_cluster_pipeline_status）"
        "批次 3 才建，本版驾驶舱不渲染虚假进度漏斗，只给自检清单 + 台账指标 + 成员规模"
        "三类真数据。",
        "G6 出版闸门（架构规范 §3 闸门表 / §15，批次 8 开通、批次 11 灰注转硬检）："
        "许可检查＋体例终检＋备份新鲜三项全过才允许把 ready 快照标记为 published "
        "—— 占位/未过项不拦「生成内容域快照」（内部快照，MANIFEST 如实标注、"
        "不得对外交付），但拦 published 流转；许可终检=resource_registry 逐行 "
        "license 审计（0 行=空过「未登记资源」注明，有空行=未过 n/m）、体例终检="
        "configs/style.yaml 在场＋含 style_version 字段（缺失=「体例文件未研制」）、"
        "备份新鲜=data/backups/ 最新 *.sql.gz/*.tar.gz 灾备产物（无=「备份任务"
        "未运行」，快照≠灾备备份）——占位如实展示，绝不渲染虚假健康状态。",
        "快照状态单向流转：ready→published（G6 全过才可用，published 终态）／"
        "ready→revoked（撤销=作废退出出版通道，单向不可逆，如需再出版须重新生成"
        "快照，防「撤销又复活」的审计断链）；流转带乐观并发守卫（两人同转只有一人"
        "生效），快照生成与流转都在 guards 中央闸门之后（纵深防御第二层）。",
    ],
    "data_source": [
        "src/org_db.py：dictionary_projects / project_members（list_projects / "
        "get_members / add_member / remove_member / project_selfcheck）——项目壳由"
        "平台管理员创建（create_project），本页只管成员册与体检。",
        "src/ai_ledger.py：ai_proposals（get_stats）——AI 提案总数/待裁决数/采纳率"
        "（adopted ÷ (adopted+rejected+modified)，分母为已裁决数）/平均不确定度"
        "（综合信号，非 LLM 自报置信度）。",
        "src/dict_admin_db.py：custom_fields / custom_values（define_field / "
        "list_fields / deprecate_field / set_value）——校验失败（code 重复、枚举缺"
        "白名单、锚与 applies_to 不符、值类型非法、字段已弃用）以 0/False 返回，页面转 "
        "st.error 展示。",
        "src/users_db.py：users / user_roles（list_users 供添加成员选人；"
        "has_role(id, 'dict_admin') 作角色门实时兜底）。",
        "src/export_center.py（批次 8，只读调用）：build_content_snapshot 内容域"
        "快照机械（逐表 CSV→zip→export_batches 登记线，角色闸在调用点再校验一次）"
        "＋ list_exports 最近快照清单——本页负责其前置的 G6 三检与 ready 状态后的 "
        "published/revoked 流转（私有单步辅助 _advance_export_status）。",
        "src/registry_db.py（批次 11）：resource_registry（D⑥ 资源发布域数据面）"
        "——登记表单 register_resource（name/version/coverage/license 必填，"
        "UNIQUE(name, version) 去重）＋ list_resources 资源清单；G6 许可终检"
        "逐行审计的就是这张表。",
    ],
    "steps": [
        "进入「📖 词典管理」先看主编驾驶舱：顶部指标卡给项目数/成员人次/AI 提案总数/"
        "待裁决/采纳率/平均不确定度；下方逐项目自检清单——绿 ✓ 无阻塞，红条目即需处理"
        "的问题（无 chief、chief 账号全部停用、数据库不可用）。",
        "「👥 项目成员」选项目：成员表（chief 置顶）看职能与授权人；「添加成员」选人 + "
        "选项目内职能后入册，对已入册者重入即改授职能；「移出项目」选成员执行移除——"
        "chief 或有在途任务者被数据层拒绝时页面以黄色警告转述原因。",
        "「🏷️ 定制属性」选项目先「定义字段」：填 code（项目内唯一）与展示名、选挂锚"
        "类型（word/sense/example）与值类型（text/number/enum/date/bool），enum 类型"
        "必须给逗号分隔的白名单，勾选必填为表单侧强制声明。",
        "字段列表确认定义结果（含已弃用字段，灰徽章只读）；「弃用」选中在用字段即停写"
        "不删——存量值保留可展示，字段绝不物理删除。",
        "「为锚写值」选在用字段 + 锚类型（须与字段 applies_to 一致）+ 锚 id（锚行主键）"
        "+ 按值类型录入值后写入；一字段一锚一值，重复写即改值；必填字段空值在表单侧"
        "拦截。",
        "「🖼️ 媒体库」先「登记资产」（双轨）：①上传落盘——选本地 png/jpeg/jpg/"
        "mp3/mp4 文件（单文件 ≤50MB）+ 来源 + 许可，平台写入 data/media/{kind}/"
        "YYYYMM/（文件名取 sha256 前 16 位）后自动登记；②服务器路径登记——填"
        "服务器/仓库文件路径 + 资产形态（image/audio/video）+ 来源 + 许可（license "
        "必填，空许可表单侧拦截——无许可的资产不入库）。两轨都按文件内容算 sha256，"
        "命中已有资产即提示「已存在，复用」（上传命中可直接转入绑定）；再「绑定资产」"
        "到四锚（词目/义位/例证/图式）并给用途与图注；绑定以「候选」态起步，在绑定"
        "列表逐级单步流转（候选→审定→发布），词条装配只取发布态。",
        "「📤 出版导出」先读 G6 三卡：许可终检（resource_registry 逐行 license "
        "审计——0 行=空过「未登记资源」注明，有空 license 行=未过 n/m）、体例终检"
        "（configs/style.yaml 在场＋含 style_version 字段，展示体例版本；缺失="
        "「体例文件未研制」占位）、备份新鲜（data/backups/ 灾备产物在场=已过，"
        "无=「备份任务未运行」占位）——占位/未过仍可「生成内容域快照」（内部快照，"
        "zip 路径/行数/包含表/跳过表如实展示），但「标记 published」按钮禁用并注明"
        "原因；三项全过后选 ready 快照「标记 published」出版交付，或「撤销快照」"
        "（ready→revoked，单向不可逆）。",
        "「📤 出版导出」的「🗂️ 资源登记」块（D⑥ 数据面）：填资源名称/版本/覆盖"
        "说明/许可（四项必填）后「登记资源」——同（名称, 版本）重复登记复用既有行"
        "（UNIQUE 去重），登记留痕 registered_by；下方资源清单实时展示。语料库/"
        "参考词典/媒体包等一切进入平台的外部资源都应先登记（无许可不入库）。",
    ],
    "notes": [
        "权限口径：本区仅词典管理员（dict_admin）可用；过渡期内置 admin 账号视为兼有 "
        "dict_admin（会话 role=='admin' 直接放行，另有 users_db.has_role 实时兜底）。"
        "平台管理员不碰业务数据。",
        "驾驶舱的采纳率为 None 表示还没有任何已裁决提案（不是 0%）；平均不确定度按"
        "范围内全部提案（含已裁决）平均。",
        "「成员人次」= 各项目 member_count 之和（一人多项目重复计），不是去重人数；"
        "移除 chief 前须先把 chief 职能改授他人。",
        "字段定义后无更新接口：改枚举/改名属新语义需求，弃用旧 code 后以新 code 重建；"
        "custom_fields 无物理删除。",
        "所有项目名/用户名/字段名/枚举值等用户生成内容渲染进 HTML 前一律转义；下拉与"
        "折叠面板的选项文本由 Streamlit 自带转义。",
        "任务分配/数据导入/词条浏览器三个标签页已并入本区（批次 2 集成）：数据导入"
        "本期登记批次台账（业务表写入批次 3 接线），任务分配的回避制/负荷上限校验"
        "批次 3 接入。",
        "媒体库（批次 4 增设）的数据资产归词典管理员：登记（media_db.register_asset，"
        "license 必填 + sha256 去重）、绑定（bind_asset 四锚×用途，UNIQUE 幂等）、"
        "审定流转只在本页进行；词条装配（义项脊柱媒体段/多模态区）只取「发布」态"
        "绑定，候选/审定态仅留痕可见。绑定的锚存在性校验归页面与加载脚本"
        "（media_db 不做多态锚校验），状态流转逐级单步、不可跳级。",
        "媒体库上传通道（批次 8 开通）：白名单 png/jpeg/jpg/mp3/mp4、单文件 ≤50MB；"
        "落盘 data/media/{kind}/YYYYMM/{sha256 前 16 位}{后缀}（内容寻址，同内容同"
        "路径，目录自动建）；后缀按内容魔数嗅探（png/jpg/mp3/mp4），嗅探不出按资产"
        "形态用规范后缀兜底；扩展名与 MIME 双白名单且须对应，另做内容魔数一致性"
        "校验（声明 image 须 PNG/JPEG 魔数，svg/script 伪装 png 被拒），防改名伪装。"
        "落盘成功但登记失败时文件保留在落盘路径，可改走服务器路径登记补登；任何"
        "上传失败只 st.error 提示不抛异常。",
        "出版导出（批次 11 灰注转硬检后）的口径：许可终检数据面已接通——"
        "resource_registry 随页面自举建表，逐行 license 审计出硬结论（0 行=空过"
        "注明，不渲染虚假健康状态）；体例终检验 configs/style.yaml 在场＋含 style_version "
        "字段（体例文件批次 11 研制，版本对比/变更工单线批次 12 接入）；备份新鲜"
        "主证据=data/backups/ 灾备产物（scripts/backup_db.sh，平台管理员运维线，"
        "本页只探测不执行），内容域快照只是参考证据（快照≠灾备）——占位项不拦内部"
        "快照（license_checked=0 如实登记），拦 published；新鲜度阈值（如「24 小时"
        "内有备份」）待批次 12 运维工单，不编假阈值。",
        "资源登记（批次 11）的数据面边界：登记=词典管理员（guards 中央闸门后调 "
        "registry_db.register_resource）；「双人双签」（技术录入＋许可审定两条签署"
        "线）为批次 12 工单，本版登记行以 registered_by 留痕，审定态字段未开。",
    ],
}

# ============================================
# 展示常量（徽章配色与枚举中文名；存库一律英文枚举值）
# ============================================

# 项目内职能中文名（org_db.PROJECT_ROLES 的展示映射）
PROJECT_ROLE_LABELS = {
    "chief": "主编（词典管理员）",
    "reviewer": "审校",
    "editor": "编纂",
    "annotator": "标注员",
    "viewer": "只读",
}

PROJECT_ROLE_BADGE_COLORS = {
    "chief": "#2b6cb0",
    "reviewer": "#2f855a",
    "editor": "#4299e1",
    "annotator": "#6b46c1",
    "viewer": "#718096",
}

# 锚类型 / 值类型中文名（dict_admin_db.APPLIES_TO / VALUE_TYPES 的展示映射）
ANCHOR_LABELS = {"word": "词目", "sense": "义位", "example": "例证"}
VALUE_TYPE_LABELS = {
    "text": "文本",
    "number": "数值",
    "enum": "枚举",
    "bool": "布尔",
    "date": "日期",
}

_ACTIVE_GREEN = "#2f855a"
_INACTIVE_GRAY = "#718096"

# 日期输入口径（与 dict_admin_db._normalize_value 的 YYYY-MM-DD 一致）
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 媒体库（批次 4 🖼️ tab）：枚举中文展示映射与列表规模
MEDIA_KIND_LABELS = {
    "image": "图片（image）",
    "audio": "音频（audio）",
    "video": "视频（video）",
}
MEDIA_PURPOSE_LABELS = {
    "pronunciation": "发音（pronunciation）",
    "illustration": "释义配图（illustration）",
    "example_media": "例证媒体（example_media）",
    "schema_diagram": "图式示意图（schema_diagram）",
}
MEDIA_ANCHOR_LABELS = {
    "word": "词目（word）",
    "sense": "义位（sense）",
    "example": "例证（example）",
    "schema": "图式（schema）",
}
MEDIA_LIST_LIMIT = 50

# 上传通道（批次 8 Agent W）：白名单与落盘口径。st.file_uploader 的 type 只是
# 客户端过滤，服务端准入以 _validate_upload（扩展名/MIME 双白名单 + 大小）为准。
MEDIA_UPLOAD_MAX_BYTES = 50 * 1024 * 1024  # 单文件 ≤ 50MB
MEDIA_UPLOAD_TYPES = ["png", "jpg", "jpeg", "mp3", "mp4"]  # uploader type 过滤
# 扩展名 → 允许的 MIME（浏览器口径；扩展名与 MIME 必须对应，防改名伪装）
MEDIA_UPLOAD_EXT_MIMES = {
    "png": ("image/png",),
    "jpg": ("image/jpeg",),
    "jpeg": ("image/jpeg",),
    "mp3": ("audio/mpeg", "audio/mp3"),
    "mp4": ("video/mp4",),
}
# 扩展名 → 资产形态（media_db.KINDS；决定落盘目录段 data/media/{kind}/）
MEDIA_UPLOAD_EXT_KINDS = {
    "png": media_db.KIND_IMAGE,
    "jpg": media_db.KIND_IMAGE,
    "jpeg": media_db.KIND_IMAGE,
    "mp3": media_db.KIND_AUDIO,
    "mp4": media_db.KIND_VIDEO,
}
# 内容魔数嗅探不出时的兜底后缀（按资产形态给规范后缀）
MEDIA_UPLOAD_KIND_EXT = {
    media_db.KIND_IMAGE: ".png",
    media_db.KIND_AUDIO: ".mp3",
    media_db.KIND_VIDEO: ".mp4",
}
# 上传落盘根 = 仓库根（data/ 的父目录；category_pack/reliability 同款推导）
_MEDIA_UPLOAD_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ============================================
# 出版导出（批次 8 G6 闸门执行页）：快照状态展示映射与 G6 检查口径
# ============================================

# export_batches.status 三态（export_center.DDL 枚举）的中文展示映射
EXPORT_STATUS_LABELS = {"ready": "就绪", "published": "已出版", "revoked": "已撤销"}
EXPORT_STATUS_COLORS = {
    "ready": "#2b6cb0", "published": "#22543d", "revoked": "#718096",
}

# G6 检查项三态徽章：passed=已过 / placeholder=占位 / failed=未过。
# 口径（施工规范 §12 G6 行）：占位项**不阻止生成内部快照**，但与未过项一样
# **阻止 status ready→published** —— 三项全过（全部 passed）才放行出版流转。
G6_PASSED = "passed"
G6_PLACEHOLDER = "placeholder"
G6_FAILED = "failed"
G6_STATUS_LABELS = {"passed": "已过", "placeholder": "占位", "failed": "未过"}
G6_STATUS_COLORS = {
    "passed": _ACTIVE_GREEN, "placeholder": _INACTIVE_GRAY, "failed": "#e53e3e",
}

# G6 检查项 key（三卡固定顺序：许可 → 体例 → 备份）
G6_KEY_LICENSE = "license"
G6_KEY_STYLE = "style"
G6_KEY_BACKUP = "backup"

# 体例终检的 style.yaml 候选路径（相对仓库根；批次 11 起为硬检：文件在场＋
# 含 style_version 字段才算过——体例文件 configs/style.yaml 批次 11 研制；
# 版本对比/变更工单线归体例配置页 6.7，批次 12 接入）
_G6_STYLE_CANDIDATE_RELS = (
    "configs/style.yaml", "config/style.yaml", "data/style.yaml", "style.yaml",
)

# style_version 字段解析（体例终检硬检项；允许行尾注释与成对引号）
_G6_STYLE_VERSION_RE = re.compile(
    r"^\s*style_version:\s*(?P<value>.+?)\s*(?:#.*)?$"
)

# 许可终检审计的表名（D⑥ 资源发布域 resource_registry：许可必填、双人双签；
# 批次 11 起数据面接通——页面自举 ensure_resource_registry_tables 建表，
# 许可终检按逐行 license 审计出硬结论，不再以「表未建」灰注常态存在）
_G6_LICENSE_TABLE = "resource_registry"


# ============================================
# 纯函数（无 st./DB 依赖，tests/test_dict_admin_pages.py 直接测）
# ============================================

def _esc(value: Any) -> str:
    """任意值 → HTML 安全文本（str() 后 html.escape 含引号）。

    所有进 unsafe_allow_html 的用户生成内容/库内文本必须先过这里；
    selectbox 等纯文本控件由 Streamlit 自带转义，调用方不要再转。
    """
    return _html_escape(str(value), quote=True)


def _is_dict_admin(user: Any) -> bool:
    """会话用户 dict 是否放行词典管理区（纯函数，fail-closed）。

    过渡期判定（施工规范 §5 通用约定）：
      * role == 'admin' 视为兼有 dict_admin/sys_admin（内置 admin 的
        users_db 幂等迁移口径）；
      * roles 列表（六角色多角色快照）含 'dict_admin' 放行；
      * 非 dict 会话、缺键、roles 为非序列类型一律不放行（fail-closed，
        不做大小写/类型宽容 —— 角色枚举在库里恒为小写字面量）。
    实时兜底（会话滞后场景）由 _db_confirms_dict_admin 另行查库，不在本函数。
    """
    if not isinstance(user, dict):
        return False
    if user.get("role") == "admin":
        return True
    roles = user.get("roles")
    if isinstance(roles, (list, tuple, set)):
        return any(str(r) == "dict_admin" for r in roles)
    return False


def _parse_enum_csv(raw: Any) -> List[str]:
    """「语域, 教材分级，频级」→ ['语域', '教材分级', '频级']（逗号分隔枚举解析）。

    中英文逗号皆可分隔；去首尾空白、丢空段、保序去重；非字符串输入返回 []
    （表单侧把空清单视为「未给白名单」，enum 字段提交前据此拦截）。
    """
    if not isinstance(raw, str):
        return []
    items: List[str] = []
    for part in raw.replace("，", ",").split(","):
        text = part.strip()
        if text and text not in items:
            items.append(text)
    return items


def _format_rate(rate: Any) -> str:
    """比率展示口径：None（无数据）→ '—'，数值 → 百分数一位小数；脏值 '—'。"""
    try:
        if rate is None:
            return "—"
        return f"{float(rate) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _format_uncertainty(value: Any) -> str:
    """平均不确定度展示口径：None（无数据）→ '—'，数值 → 两位小数；脏值 '—'。"""
    try:
        if value is None:
            return "—"
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "—"


def _media_register_error(file_path: Any, kind: Any, source: Any,
                          license_text: Any) -> Optional[str]:
    """媒体登记表单校验（纯函数）：必填缺失返回错误文案，合法返回 None。

    口径（批次 4 契约）：file_path / kind（media_db.KINDS 枚举）/ source /
    license 四项必填；license 去空白后为空即「许可必填」——数据层
    register_asset 有同款硬约束，表单侧先拦给出可读错误。
    """
    if not str(file_path or "").strip():
        return "资产文件路径（file_path）必填：register_asset 需要读取真实文件算 sha256。"
    if kind not in media_db.KINDS:
        return f"资产形态（kind）须为 {' / '.join(media_db.KINDS)} 之一。"
    if not str(source or "").strip():
        return "来源（source）必填（如 ModernChineseDict/images）。"
    if not str(license_text or "").strip():
        return "许可（license）必填：无许可的资产不入库（media_db 硬约束，D⑥ 许可纪律）。"
    return None


def _format_bytes(size: Any) -> str:
    """文件字节数展示口径：None/脏值 '—'；<1024 字节原样；否则 KB/MB。"""
    try:
        size = int(size)
    except (TypeError, ValueError):
        return "—"
    if size < 0:
        return "—"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def _sha256_file(path: Any) -> Optional[str]:
    """流式计算文件 sha256（64KB 分块；登记前去重预检用）。读不动返回 None。"""
    digest = hashlib.sha256()
    try:
        with open(str(path), "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                digest.update(chunk)
    except OSError as e:
        logger.warning(f"计算资产 sha256 失败（path={path!r}）: {e}")
        return None
    return digest.hexdigest()


# ============================================
# 上传通道纯函数（批次 8 Agent W；tests/test_dict_admin_pages.py 直接测）
# ============================================

def _sniff_upload_ext(data: bytes) -> str:
    """按内容魔数嗅探真实后缀（.png/.jpg/.mp3/.mp4）；嗅探不出返回 ''。

    与扩展名/MIME 白名单互为印证：落盘后缀以内容为准，防止「改名伪装」的
    文件在磁盘上顶着假后缀（登记的 mime 仍以浏览器报告为准，已过白名单）。
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"ID3") or (
        len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0
    ):
        return ".mp3"
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return ".mp4"
    return ""


def _validate_upload(name: Any, size: Any, mime: Any,
                     data: Any = None) -> Optional[str]:
    """上传准入校验（纯函数）：扩展名/MIME 白名单、大小与内容魔数一致性。

    口径（批次 8 契约；R2-2 增魔数一致性）：白名单 png/jpeg/jpg/mp3/mp4，
    单文件 ≤ 50MB；扩展名与 MIME 必须各自在白名单内且相互对应（浏览器报告
    的 MIME 与扩展名不符即拒绝，防改名伪装）；size 须为正数。任何脏输入返回
    可读错误文案，不抛异常。

    内容魔数一致性（R2-2，data 非 None 时启用；复用 _sniff_upload_ext 的
    魔数逻辑，与扩展名/MIME 白名单互为印证）：
      * 声明 image（.png/.jpg/.jpeg）但内容不是 PNG/JPEG 魔数 → 拒
        「文件内容与扩展名不符」—— svg/script 等文本伪装 png 在此拦截
        （这类文件落盘后可被浏览器当 HTML 渲染，是 XSS 面）；
      * 声明 audio/video 而内容被明确嗅探为其他形态（如 PNG 数据顶着
        .mp3）→ 同款拒绝；嗅探不出（''）不放行也不拒绝 —— 落盘后缀由
        _upload_target_path 按资产形态兜底，不因魔数库覆盖不全误伤合法文件。
    data=None（既有调用方/旧测试缺省）跳过内容校验，维持旧形态。
    """
    raw_name = str(name or "").strip()
    if not raw_name:
        return "未选择文件：请先选择要上传的媒体文件。"
    lower = raw_name.lower()
    ext = lower.rsplit(".", 1)[1] if "." in lower else ""
    allowed = MEDIA_UPLOAD_EXT_MIMES.get(ext)
    if allowed is None:
        return (f"不支持的文件类型 .{ext or '（无扩展名）'}：仅允许 "
                f"{' / '.join(MEDIA_UPLOAD_TYPES)}。")
    reported = str(mime or "").strip().lower()
    if reported not in allowed:
        return (f"MIME 类型不符：.{ext} 应为 {' / '.join(allowed)}，"
                f"浏览器报告 {reported or '（空）'} —— 拒绝疑似改名伪装的文件。")
    try:
        size_bytes = int(size)
    except (TypeError, ValueError):
        return "文件大小不可读，已拒绝上传。"
    if size_bytes <= 0:
        return "空文件（≤0 字节）不入库：请确认文件内容完整后重试。"
    if size_bytes > MEDIA_UPLOAD_MAX_BYTES:
        return (f"文件超过单文件上限 50MB（实际 {_format_bytes(size_bytes)}）；"
                "请压缩后重试，超大资产改走「服务器路径登记」。")
    if data is None:
        return None
    if not isinstance(data, (bytes, bytearray, memoryview)):
        return "文件内容不可读，已拒绝上传。"
    payload = bytes(data)
    sniffed = _sniff_upload_ext(payload)
    kind = MEDIA_UPLOAD_EXT_KINDS.get(ext)
    if kind == media_db.KIND_IMAGE:
        if sniffed not in (".png", ".jpg"):
            return ("文件内容与扩展名不符：.png/.jpeg 须为 PNG/JPEG 魔数，"
                    f"内容嗅探结果为 {sniffed or '（未知魔数）'} —— 拒绝疑似"
                    "伪装成图片的文件（svg/script 等文本不入媒体库）。")
    elif sniffed and sniffed != MEDIA_UPLOAD_KIND_EXT.get(kind):
        return ("文件内容与扩展名不符：内容嗅探为 " + sniffed + "，与 ."
                + ext + " 声明的资产形态不符 —— 拒绝疑似改名伪装的文件。")
    return None


def _upload_target_path(kind: Any, data: Any, base: Any) -> str:
    """上传落盘目标路径（纯函数，内容寻址）：{base}/data/media/{kind}/YYYYMM/…

    口径（批次 8 契约）：base 为落盘根（生产 = 仓库根），返回该根下的**落盘
    绝对路径**（写入用，mkdir parents exist_ok 由调用方做）；登记入库时由调用
    方另取相对 base 的仓库相对路径（可移植口径，与
    scripts/load_media_xianhan.py 的 _rel_path 一致）。文件名 =
    sha256(data) 前 16 位 + 后缀 —— 同内容同路径，重复上传覆盖同一文件（与
    register_asset 的 sha256 去重口径一致）；后缀按内容魔数嗅探（
    _sniff_upload_ext），嗅探不出按 kind 用规范后缀（png/mp3/mp4）兜底。
    kind 非法 / data 非 bytes 类返回 ''（falsy，调用方按失败处理），不抛异常。
    """
    if kind not in media_db.KINDS:
        logger.error(
            f"_upload_target_path 拒绝非法 kind: {kind!r}（须 ∈ {media_db.KINDS}）"
        )
        return ""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        logger.error(f"_upload_target_path 拒绝非法 data: {type(data).__name__}")
        return ""
    payload = bytes(data)
    digest = hashlib.sha256(payload).hexdigest()
    ext = _sniff_upload_ext(payload) or MEDIA_UPLOAD_KIND_EXT[kind]
    month = datetime.now().strftime("%Y%m")
    return os.path.join(str(base or ""), "data", "media", str(kind), month,
                        f"{digest[:16]}{ext}")


# ============================================
# 角色门与会话（纵深防御，规范 §6-4：入口判定，不信任前端隐藏）
# ============================================

def _db_confirms_dict_admin(user: Dict[str, Any]) -> bool:
    """实时查库兜底：users_db.has_role(id, 'dict_admin')（fail-closed）。

    会话快照可能滞后（先登录后被授予 dict_admin，或旧版会话 dict 无 roles 键），
    会话判定不过时以库为准再核一次。has_role 自身对停用/不存在/库故障返回
    False，这里只兜异常不让角色门崩页面。
    """
    try:
        uid = int(user.get("id") or 0)
    except (TypeError, ValueError):
        return False
    if uid <= 0:
        return False
    try:
        return users_db.has_role(uid, "dict_admin")
    except Exception as e:  # pragma: no cover - 数据层已自兜底，防御性兜一层
        logger.warning(f"dict_admin 角色兜底查询失败（uid={uid}）: {e}")
        return False


# ============================================
# 渲染小件（徽章 / 表格 / 下拉选项，仿 users_admin_page 同一视觉语言）
# ============================================

def _badge(text: str, color: str) -> str:
    """小圆角徽章（HTML span）。text 由调用方保证已过 _esc。"""
    return (
        f'<span style="display:inline-block;background:{color};color:#fff;'
        f'padding:1px 10px;border-radius:10px;font-size:0.78em;'
        f'margin-right:4px;">{text}</span>'
    )


def _render_table(headers: List[str], rows: List[List[str]]) -> None:
    """只读 HTML 表格。单元格为调用方拼好的安全 HTML（文本已过 _esc）。"""
    header_cells = "".join(
        f"<th style='{get_table_header_style()}'>{h}</th>" for h in headers
    )
    cell_style = f"{get_table_row_style()}padding:8px;"
    row_htmls = [
        "<tr>" + "".join(f"<td style='{cell_style}'>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    ]
    st.markdown(
        f"<div style='{get_card_style()}'>"
        f"<table style='width:100%;border-collapse:collapse;'>"
        f"<tr>{header_cells}</tr>{''.join(row_htmls)}</table>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _project_options(projects: List[Dict[str, Any]]) -> Dict[str, int]:
    """「项目名（状态）→ id」下拉映射（selectbox 纯文本，不需转义）。"""
    options: Dict[str, int] = {}
    for p in projects:
        pid = int(p.get("id") or 0)
        status = str(p.get("status") or "active")
        suffix = "" if status == "active" else f"·{status}"
        options[f"{p.get('name')}（#{pid}{suffix}）"] = pid
    return options


def _anchor_label(anchor: str) -> str:
    """锚类型枚举 → 下拉展示标签（中文名＋英文原值，未知值回退原文）。"""
    return f"{ANCHOR_LABELS.get(anchor, anchor)}（{anchor}）"


def _value_type_label(value_type: str) -> str:
    """值类型枚举 → 下拉展示标签（中文名＋英文原值，未知值回退原文）。"""
    return f"{VALUE_TYPE_LABELS.get(value_type, value_type)}（{value_type}）"


def _project_role_label(role: str) -> str:
    """项目内职能枚举 → 下拉展示标签（中文名＋英文原值，未知值回退原文）。"""
    return f"{PROJECT_ROLE_LABELS.get(role, role)}（{role}）"


# ============================================
# Tab 1：主编驾驶舱
# ============================================

def _funnel_category_options() -> List[str]:
    """进度漏斗的范畴下拉选项：范畴包目录（category_pack.CATEGORIES），兜底 motion。"""
    try:
        from src.category_pack import CATEGORIES

        packs = CATEGORIES() if callable(CATEGORIES) else CATEGORIES
        options = [str(c) for c in packs]
    except Exception as e:  # noqa: BLE001 —— configs 不可读时兜底试点范畴
        logger.warning(f"枚举漏斗范畴失败，回退 motion: {e}")
        options = []
    if "motion" not in options:
        options.insert(0, "motion")
    return options


# R4-3：驾驶舱连通探测的表名（模块常量白名单 —— SQL 文本只拼常量，不收
# 调用方原文；同 _g6_license_stats 的常量表名先例）
_COCKPIT_PROBE_TABLES = {
    "projects": "dictionary_projects",
    "ai_proposals": "ai_proposals",
}


def _cockpit_db_ready(table: str) -> bool:
    """驾驶舱数据表连通探测（**只读**，R4-3：真 0 与取数失败的区分信号）。

    数据层（org_db.list_projects / ai_ledger.get_stats）把库不可用自折叠成
    []/全 0 口径 —— 页面单凭返回值分不清「真 0」与「取数失败」。本探测对
    相应表跑一发 ``SELECT 1 ... LIMIT 1``：能查 = 表在场＋库连通，空结果即
    真 0；查不动 = 数据库暂不可用，空结果按取数失败渲染（降级披露）。
    table 只接受 _COCKPIT_PROBE_TABLES 的常量值，其余一律拒绝（不拼 SQL）。
    """
    if table not in _COCKPIT_PROBE_TABLES.values():
        logger.error(f"驾驶舱连通探测拒绝非法表名: {table!r}")
        return False
    try:
        with get_db_cursor() as cursor:
            cursor.execute(f"SELECT 1 FROM {table} LIMIT 1")
            cursor.fetchall()
            return True
    except Exception as e:  # noqa: BLE001 —— 库不可用/表缺失折叠为探测失败
        logger.warning(f"驾驶舱连通探测失败（{table}）: {e}")
        return False


def _safe_cockpit_projects() -> Tuple[List[Dict[str, Any]], bool]:
    """驾驶舱项目取数兜底（R4-3）：返回 (projects, degraded)。

    异常 / None / 非 list（list_projects 契约返回 list[dict]）一律按取数
    失败（degraded=True，projects=[]）；空列表再过一发连通探测，区分
    「真 0」与「库不可用被数据层折叠成空」。
    """
    try:
        projects = org_db.list_projects()
    except Exception as e:  # noqa: BLE001 —— 数据层理论不抛，防御性兜一层
        logger.warning(f"驾驶舱项目列表取数异常: {e}")
        return [], True
    if not isinstance(projects, list):
        logger.warning(f"驾驶舱项目列表返回异常形态: {type(projects).__name__}")
        return [], True
    if not projects and not _cockpit_db_ready("dictionary_projects"):
        return [], True
    return projects, False


def _safe_cockpit_stats() -> Tuple[Dict[str, Any], bool]:
    """驾驶舱 AI 台账取数兜底（R4-3）：返回 (stats, degraded)。

    异常 / None / 非 dict（get_stats 契约返回 dict）按取数失败；全 0 口径
    （total=0）再过一发 ai_proposals 连通探测，区分真 0 与取数失败。
    """
    try:
        stats = ai_ledger.get_stats()
    except Exception as e:  # noqa: BLE001 —— 数据层理论不抛，防御性兜一层
        logger.warning(f"驾驶舱 AI 台账取数异常: {e}")
        return {}, True
    if not isinstance(stats, dict):
        logger.warning(f"驾驶舱 AI 台账返回异常形态: {type(stats).__name__}")
        return {}, True
    if not int(stats.get("total") or 0) and not _cockpit_db_ready("ai_proposals"):
        return {}, True
    return stats, False


def _render_cockpit_metrics(projects: List[Dict[str, Any]],
                            stats: Dict[str, Any],
                            projects_degraded: bool,
                            stats_degraded: bool) -> None:
    """规模与 AI 台账指标卡（R4-3：取数失败内联降级披露）。

    与 AI 协作区（ai_hub）口径一致：数据库不可用时指标为降级渲染，不代表
    没有数据 —— 取数失败的组画「—」并给内联提示；探测通过的空结果画 0
    （真 0）。两组（项目规模 / AI 台账）独立判定，一组失败不拖垮另一组。
    """
    if projects_degraded or stats_degraded:
        st.warning(
            "数据库暂不可用，指标为降级渲染 ——「—」为取数失败（不代表没有"
            "数据），0 为真实计数；库恢复后刷新即回真值。"
        )
    n_members = sum(int(p.get("member_count") or 0) for p in projects)
    st.markdown(f"<h3 style='{HEADER_H3}'>📊 规模与 AI 台账</h3>", unsafe_allow_html=True)
    org_cols = st.columns(2)
    with org_cols[0]:
        st.metric("词典项目", "—" if projects_degraded else len(projects))
    with org_cols[1]:
        st.metric("成员人次（合计）", "—" if projects_degraded else n_members)
    ai_cols = st.columns(4)
    with ai_cols[0]:
        st.metric("AI 提案总数",
                  "—" if stats_degraded else int(stats.get("total") or 0))
    with ai_cols[1]:
        st.metric("待裁决",
                  "—" if stats_degraded else int(stats.get("pending") or 0))
    with ai_cols[2]:
        st.metric("采纳率",
                  "—" if stats_degraded else _format_rate(stats.get("adoption_rate")))
    with ai_cols[3]:
        st.metric("平均不确定度",
                  "—" if stats_degraded else _format_uncertainty(stats.get("avg_uncertainty")))


def _render_cockpit_tab() -> None:
    """驾驶舱：规模与台账指标卡（st.metric）+ 十五工序漏斗 + 逐项目自检清单。

    进度漏斗（批次 3 Agent I）：src/pipeline_status.get_cluster_pipeline_status
    聚合语义分析段（工序 4–8）＋编纂成文占位段，format_funnel_segments 出渲染行；
    缺数段（表未建/无数据/库不可用）以灰色「未建/无数据：原因」如实展示，不编数。
    R4-3：规模/台账两组取数走 _safe_cockpit_* 兜底 —— 异常/异常形态/空结果
    且探测不过时内联降级提示「数据库暂不可用，指标为降级渲染」，指标画「—」，
    区分「真 0」与「取数失败」。
    """
    projects, projects_degraded = _safe_cockpit_projects()
    stats, stats_degraded = _safe_cockpit_stats()

    _render_cockpit_metrics(projects, stats, projects_degraded, stats_degraded)

    st.markdown(
        f"<h3 style='{HEADER_H3}'>⛓️ 进度漏斗（语义分析段 工序4–8 ＋ 编纂成文占位）</h3>",
        unsafe_allow_html=True,
    )
    funnel_cat = st.selectbox(
        "漏斗范畴（范畴包 configs/<category>/）",
        _funnel_category_options(),
        key="dict_admin_cockpit_category",
    )
    funnel_status = pipeline_status.get_cluster_pipeline_status(funnel_cat)
    study_code = funnel_status.get("study_code")
    if study_code:
        st.caption(
            f"范畴 {funnel_cat} → 研究代号 {study_code}：cs 侧（义位/聚类）按研究代号、"
            "标注侧（提交/信度）按包名查询。"
        )
    segments = pipeline_status.format_funnel_segments(funnel_status)
    if not segments:
        st.info("漏斗数据不可用（聚合结果为空，通常是数据库不可用）。")
    else:
        funnel_rows = []
        for label, text in segments:
            missing = text.startswith(pipeline_status.MISSING_PREFIX)
            color = _INACTIVE_GRAY if missing else "#2d3748"
            funnel_rows.append(
                "<div style='display:flex;padding:7px 0;"
                "border-bottom:1px solid #edf2f7;'>"
                f"<span style='min-width:200px;font-weight:600;'>{_esc(label)}</span>"
                f"<span style='color:{color};'>{_esc(text)}</span></div>"
            )
        st.markdown(
            f"<div style='{get_card_style()}'>{''.join(funnel_rows)}</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            "灰色行为缺数段（表未建 / 无数据 / 数据库不可用），如实缺数不给假数据；"
            "信度段 α 的达标线为 0.7（闸门 G2），分立复核 merged/split 由复核流程写入。"
        )

    st.markdown(f"<h3 style='{HEADER_H3}'>🩺 项目自检（≥1 名在用 chief 等约束）</h3>",
                unsafe_allow_html=True)
    if not projects and not projects_degraded:
        st.info("尚无词典项目：在下方「🏗️ 创建项目（建壳）」建壳并指定首位词典管理员。")

    # —— 建壳表单（批次 12 修复：创建项目此前无 UI 入口，词典管理链整体空转）——
    # 口径（架构 §8）：项目壳由平台管理员建壳并指定首位 chief；词典管理员亦可为
    # 自己的课题建壳（本区门已含 dict_admin）。chief 候选=有效六角色含 dict_admin
    # 的在用账号（首位词典管理员须能履行词典管理员职能）。
    candidates = []
    for u in users_db.list_users():
        if not u.get("active", True):
            continue
        eff = users_db.effective_six_roles(u)
        if "dict_admin" in eff:
            candidates.append(u)
    # R2-1：selectbox 选项文本由 Streamlit 自带转义（模块头部自订规则），
    # display_name 含 HTML 字符时预过 _esc 会双重转义（显示成 &lt;b&gt; 字面），
    # 这里直接用原文 —— 展示转义是控件职责，不是调用方职责。
    chief_opts = {f"{u['display_name']}（{u['username']}）": int(u["id"])
                  for u in candidates}
    with st.expander("🏗️ 创建项目（建壳并指定首位词典管理员）"):
        if not chief_opts:
            st.warning("当前没有可任 chief 的账号（有效角色含 dict_admin）——"
                       "请先在「👥 账号管理」为用户授予 dict_admin。")
        else:
            with st.form("dict_admin_project_create_form", clear_on_submit=True):
                pname = st.text_input("项目名称", key="dict_admin_proj_name")
                pcats = st.text_input("范畴包（逗号分隔，如 motion, speech）",
                                      value="motion", key="dict_admin_proj_cats")
                pchief = st.selectbox("首位词典管理员（chief）",
                                      options=list(chief_opts.keys()),
                                      key="dict_admin_proj_chief")
                pdesc = st.text_input("项目描述（可空）", key="dict_admin_proj_desc")
                if st.form_submit_button("创建项目"):
                    name = pname.strip()
                    if not name:
                        st.error("项目名称必填。")
                    else:
                        cats = [c.strip() for c in pcats.split(",") if c.strip()]
                        pid = org_db.create_project(
                            name, chief_opts[pchief], cats or ["motion"],
                            description=pdesc.strip())
                        if pid:
                            st.success(f"项目 #{pid}「{name}」已建壳，"
                                       "chief 已同事务入册——可在「👥 项目成员」与"
                                       "「🏷️ 定制属性」继续配置。")
                            st.rerun()
                        else:
                            st.error("建壳失败（名称重复或数据库异常），详见服务端日志。")
    for p in projects:
        pid = int(p.get("id") or 0)
        name = str(p.get("name") or f"项目#{pid}")
        ok, problems = org_db.project_selfcheck(pid)
        if ok:
            st.success(f"✓ {_esc(name)}：无阻塞")
        else:
            detail = "；".join(_esc(x) for x in problems)
            st.error(f"✗ {_esc(name)}：{detail}")


# ============================================
# Tab 2：项目成员
# ============================================

def _render_members_table(members: List[Dict[str, Any]]) -> None:
    """成员册只读表（chief 置顶由数据层排序保证）。"""
    if not members:
        st.info("该项目还没有成员（除建壳时的首位 chief 外）。")
        return
    rows: List[List[str]] = []
    for m in members:
        role = str(m.get("project_role") or "viewer")
        role_badge = _badge(
            _esc(PROJECT_ROLE_LABELS.get(role, role)),
            PROJECT_ROLE_BADGE_COLORS.get(role, "#718096"),
        )
        if int(m.get("active") or 0):
            status_badge = _badge("启用", _ACTIVE_GREEN)
        else:
            status_badge = _badge("已停用", "#e53e3e")
        granter = m.get("granted_by")
        rows.append([
            str(int(m.get("user_id") or 0)),
            _esc(m.get("username") or ""),
            _esc(m.get("display_name") or m.get("username") or ""),
            role_badge,
            status_badge,
            _esc(granter) if granter is not None else "—",
            _esc(m.get("granted_at") or ""),
        ])
    _render_table(
        ["用户 ID", "用户名", "显示名", "项目内职能", "账号状态", "授权人", "入册时间"],
        rows,
    )


def _render_add_member_form(project_id: int, me: Dict[str, Any]) -> None:
    """添加成员表单：list_users 选人 + 项目内职能；已入册者重入 = 改授职能。"""
    st.markdown(f"<h4 style='{HEADER_H3}'>➕ 添加成员 / 改授职能</h4>", unsafe_allow_html=True)
    users = users_db.list_users()
    if not users:
        st.info("暂无用户可入册（账号由平台管理员在系统管理区创建）。")
        return
    user_options: Dict[str, int] = {}
    for u in users:
        label = f"{u.get('username')}（{u.get('display_name') or u.get('username')}）"
        user_options[label] = int(u.get("id") or 0)

    with st.form("dict_admin_member_add_form", clear_on_submit=True):
        user_label = st.selectbox(
            "选择用户", list(user_options.keys()), key="dict_admin_mem_add_user",
        )
        role = st.selectbox(
            "项目内职能",
            list(org_db.PROJECT_ROLES),
            format_func=_project_role_label,
            key="dict_admin_mem_add_role",
        )
        submitted = st.form_submit_button("入册 / 改授", use_container_width=True)
    if not submitted:
        return
    uid = user_options[user_label]
    # R1-8（施工规范 §14 批次 12）：入册/改授是项目内授权写路径 —— 与同页
    # 媒体/快照调用点对齐，API 级中央闸门再兜一道（页面 tab 门之上纵深防御）
    try:
        guards.require_dict_admin()
    except PermissionError as e:
        st.error(f"⛔ {e}")
        return
    try:
        ok = org_db.add_member(project_id, uid, role, granted_by=int(me.get("id") or 0))
    except Exception as e:  # org_db 理论上不抛，防御性转译（规范 §5 通用约定）
        logger.warning(f"add_member 意外失败（project={project_id}, user={uid}）: {e}")
        st.warning("入册未生效：数据层返回异常（详见服务端日志），请稍后重试。")
        return
    if ok:
        st.success(f"已入册用户 id={uid} 为「{PROJECT_ROLE_LABELS.get(role, role)}」；"
                   "若其已在册则为改授职能。")
        logger.info(f"dict_admin {me.get('username')} 把用户 id={uid} "
                    f"入册项目 {project_id} 为 {role}")
        st.rerun()
    else:
        st.warning("入册未生效：可能职能未变化（重复授予同一职能）、用户/项目不存在"
                   "或数据库不可用（org_db 已记日志）。")


def _render_remove_member_form(project_id: int, members: List[Dict[str, Any]],
                               me: Dict[str, Any]) -> None:
    """移出项目表单：chief / 在途任务被拒时把 org_db 的返回转成 st.warning。"""
    st.markdown(f"<h4 style='{HEADER_H3}'>➖ 移出项目</h4>", unsafe_allow_html=True)
    if not members:
        st.info("无成员可移除。")
        return
    member_options: Dict[str, int] = {}
    for m in members:
        role = str(m.get("project_role") or "viewer")
        label = (f"#{int(m.get('user_id') or 0)} {m.get('username')}"
                 f"（{PROJECT_ROLE_LABELS.get(role, role)}）")
        member_options[label] = int(m.get("user_id") or 0)

    with st.form("dict_admin_member_remove_form", clear_on_submit=True):
        member_label = st.selectbox(
            "选择成员", list(member_options.keys()), key="dict_admin_mem_remove_user",
        )
        submitted = st.form_submit_button("移出项目", use_container_width=True)
    if not submitted:
        return
    uid = member_options[member_label]
    # R1-8：移出项目是成员管理写路径 —— 中央闸门兜底（同 add_member 口径）
    try:
        guards.require_dict_admin()
    except PermissionError as e:
        st.error(f"⛔ {e}")
        return
    try:
        ok = org_db.remove_member(project_id, uid)
    except Exception as e:  # 防御性转译：org_db 拒绝/异常都进 warning，不静默
        logger.warning(f"remove_member 意外失败（project={project_id}, user={uid}）: {e}")
        st.warning("移除未生效：数据层返回异常（详见服务端日志），请稍后重试。")
        return
    if ok:
        st.success(f"已把用户 id={uid} 移出项目。")
        logger.info(f"dict_admin {me.get('username')} 把用户 id={uid} 移出项目 {project_id}")
        st.rerun()
    else:
        st.warning("移除被拒：主编（chief）不可移除（请先改授他人）、该成员仍有在途任务"
                   "（open/in_progress，请先改派）、目标并非本项目成员，或数据库不可用。")


def _render_members_tab(me: Dict[str, Any]) -> None:
    """项目成员分区：项目下拉 + 成员表 + 入册/移出表单 + 本项目 selfcheck 结果。"""
    st.markdown(f"<h3 style='{HEADER_H3}'>👥 项目成员（三级权限链第二级：入册）</h3>",
                unsafe_allow_html=True)
    projects = org_db.list_projects()
    if not projects:
        st.info("尚无词典项目：项目壳由平台管理员创建（org_db.create_project 并册封"
                "首位 chief），之后本页维护成员册。")
        return
    options = _project_options(projects)
    project_label = st.selectbox(
        "选择项目", list(options.keys()), key="dict_admin_mem_project",
    )
    project_id = options[project_label]

    members = org_db.get_members(project_id)
    _render_members_table(members)

    left, right = st.columns(2)
    with left:
        _render_add_member_form(project_id, me)
    with right:
        _render_remove_member_form(project_id, members, me)

    st.markdown("")
    ok, problems = org_db.project_selfcheck(project_id)
    if ok:
        st.success("✓ 项目自检通过：chief 齐备且账号在用。")
    else:
        st.error("项目自检发现问题：" + "；".join(_esc(x) for x in problems))


# ============================================
# Tab 3：定制属性
# ============================================

def _render_define_field_form(project_id: int, me: Dict[str, Any]) -> None:
    """定义字段表单：code/展示名/挂锚/值类型/枚举白名单（逗号分隔）/必填声明。"""
    st.markdown(f"<h4 style='{HEADER_H3}'>📐 定义字段</h4>", unsafe_allow_html=True)
    with st.form("dict_admin_field_form", clear_on_submit=True):
        code = st.text_input("字段代码 code（项目内唯一，≤64 字符）",
                             max_chars=64, key="dict_admin_field_code")
        name = st.text_input("展示名（≤120 字符，如「语域」）",
                             max_chars=120, key="dict_admin_field_name")
        applies_to = st.selectbox(
            "挂锚类型 applies_to", list(dict_admin_db.APPLIES_TO),
            format_func=_anchor_label, key="dict_admin_field_applies",
        )
        value_type = st.selectbox(
            "值类型 value_type", list(dict_admin_db.VALUE_TYPES),
            format_func=_value_type_label, key="dict_admin_field_vtype",
        )
        enum_raw = st.text_input(
            "枚举值白名单（逗号分隔；仅 value_type=enum 使用）",
            key="dict_admin_field_enum",
        )
        required = st.checkbox("必填（表单侧强制，数据层不拒空值）",
                               key="dict_admin_field_required")
        submitted = st.form_submit_button("定义字段", use_container_width=True)
    if not submitted:
        return
    clean_code = code.strip()
    clean_name = name.strip()
    if not clean_code or not clean_name:
        st.error("字段代码与展示名不能为空。")
        return
    enum_values = _parse_enum_csv(enum_raw)
    if value_type == "enum" and not enum_values:
        st.error("enum 字段需要至少 1 个枚举值（逗号分隔白名单）。")
        return
    payload_enum: Optional[List[str]] = enum_values if value_type == "enum" else None
    # R1-8：定义字段是定制属性写路径 —— 中央闸门兜底（同页媒体/快照口径）
    try:
        guards.require_dict_admin()
    except PermissionError as e:
        st.error(f"⛔ {e}")
        return
    try:
        new_id = dict_admin_db.define_field(
            project_id, clean_code, clean_name, applies_to, value_type,
            payload_enum, required=required, created_by=int(me.get("id") or 0),
        )
    except Exception as e:  # dict_admin_db 理论上不抛，防御性转 st.error
        logger.warning(f"define_field 意外失败（project={project_id}, code={clean_code}）: {e}")
        st.error("定义字段失败：数据层返回异常（详见服务端日志），请稍后重试。")
        return
    if new_id > 0:
        st.success(f"已定义字段「{clean_code}」（id={new_id}）。")
        logger.info(f"dict_admin {me.get('username')} 在项目 {project_id} "
                    f"定义字段 {clean_code}（id={new_id}）")
        st.rerun()
    else:
        st.error("定义字段失败：code 可能与项目内已有字段重复、参数非法"
                 "（非 enum 字段不可携带枚举值）或数据库不可用（数据层已记日志）。")


def _render_fields_table(fields: List[Dict[str, Any]]) -> None:
    """字段定义清单（含已弃用，弃用字段灰徽章）。"""
    if not fields:
        st.info("本项目还没有定制字段：先在上方「定义字段」。")
        return
    rows: List[List[str]] = []
    for f in fields:
        active = str(f.get("status") or "active") == "active"
        status_badge = _badge("在用", _ACTIVE_GREEN) if active else _badge("已弃用", _INACTIVE_GRAY)
        enum_values = f.get("enum_values") or []
        rows.append([
            str(int(f.get("id") or 0)),
            _esc(f.get("code") or ""),
            _esc(f.get("name") or ""),
            _esc(ANCHOR_LABELS.get(str(f.get("applies_to")), f.get("applies_to"))),
            _esc(VALUE_TYPE_LABELS.get(str(f.get("value_type")), f.get("value_type"))),
            _esc("、".join(str(v) for v in enum_values)) if enum_values else "—",
            "是" if f.get("required") else "否",
            status_badge,
        ])
    _render_table(
        ["ID", "code", "展示名", "挂锚", "值类型", "枚举白名单", "必填", "状态"],
        rows,
    )


def _render_deprecate_field_form(fields: List[Dict[str, Any]]) -> None:
    """弃用字段表单：停写不删（存量值保留只读）。"""
    st.markdown(f"<h4 style='{HEADER_H3}'>🚫 弃用字段（停写不删）</h4>", unsafe_allow_html=True)
    active_fields = [f for f in fields if str(f.get("status") or "") == "active"]
    if not active_fields:
        st.info("没有可弃用的在用字段。")
        return
    field_options = {
        f"{f.get('code')}（{f.get('name')}）": int(f.get("id") or 0) for f in active_fields
    }
    with st.form("dict_admin_field_deprecate_form", clear_on_submit=True):
        field_label = st.selectbox(
            "选择在用字段", list(field_options.keys()), key="dict_admin_cf_dep_field",
        )
        submitted = st.form_submit_button("弃用", use_container_width=True)
    if not submitted:
        return
    fid = field_options[field_label]
    # R1-8：弃用字段是定制属性写路径 —— 中央闸门兜底（同页媒体/快照口径）
    try:
        guards.require_dict_admin()
    except PermissionError as e:
        st.error(f"⛔ {e}")
        return
    try:
        ok = dict_admin_db.deprecate_field(fid)
    except Exception as e:  # 防御性转 st.error
        logger.warning(f"deprecate_field 意外失败（field={fid}）: {e}")
        st.error("弃用失败：数据层返回异常（详见服务端日志），请稍后重试。")
        return
    if ok:
        st.success(f"已弃用字段 id={fid}：拒新写值，存量值保留只读。")
        st.rerun()
    else:
        st.error("弃用失败：字段不存在或已弃用（未变更不重复计）。")


def _coerce_value(value_type: str, raw: Any) -> Optional[Any]:
    """表单原始输入 → 数据层 value（类型不符返回 None，由调用方转 st.error）。

    number → float（须有限）；date → YYYY-MM-DD 字符串（R2-3：过正则后再用
    date.fromisoformat 验真实日历日期，2024-02-30 这类「格式对但日期不存在」
    一并拒绝）；bool → True/False；text/enum → 原字符串（R2-3：text 超过
    dict_admin_db.MAX_VALUE_TEXT_LEN 上限拒 —— 数据层 set_value 同款上限的
    表单侧前移，避免 1 万字符长文走到库门口才被拒）。调用方据 value_type 给
    专用报错（日期不存在/文本超长/非有限数字）。最终口径（enum 白名单等）
    仍由 dict_admin_db.set_value 把关 —— 本函数只做表单侧的格式转换。
    """
    text = "" if raw is None else str(raw).strip()
    if value_type == "number":
        try:
            number = float(text)
        except ValueError:
            return None
        if not math.isfinite(number):
            return None
        return number
    if value_type == "date":
        if not _DATE_RE.match(text):
            return None
        try:
            date.fromisoformat(text)
        except ValueError:
            return None
        return text
    if value_type == "bool":
        return text in ("是", "是（True）", "True", "true", "1", "是（1）")
    if value_type == "text" and len(text) > dict_admin_db.MAX_VALUE_TEXT_LEN:
        return None
    return text


def _render_write_value_form(fields: List[Dict[str, Any]], me: Dict[str, Any]) -> None:
    """为锚写值表单：字段 + 锚类型/锚 id + 按值类型录入；重复写即改值。"""
    st.markdown(f"<h4 style='{HEADER_H3}'>✍️ 为锚写值</h4>", unsafe_allow_html=True)
    active_fields = [f for f in fields if str(f.get("status") or "") == "active"]
    if not active_fields:
        st.info("没有在用字段可写值：先「定义字段」。")
        return
    field_options = {
        (f"{f.get('code')}（{f.get('name')}）"
         f"· 挂{ANCHOR_LABELS.get(str(f.get('applies_to')), f.get('applies_to'))}"
         f"· {VALUE_TYPE_LABELS.get(str(f.get('value_type')), f.get('value_type'))}"): f
        for f in active_fields
    }
    with st.form("dict_admin_value_form", clear_on_submit=True):
        field_label = st.selectbox(
            "选择字段", list(field_options.keys()), key="dict_admin_val_field",
        )
        field = field_options.get(field_label)
        if field is None:
            # 字段清单在两次渲染间变化（他人弃用等）：不让 KeyError 打崩页面
            submitted = st.form_submit_button("写入值", use_container_width=True)
            if submitted:
                st.error("字段清单已变化，请重试。")
            return
        value_type = str(field.get("value_type") or "text")
        anchor_choices = list(dict_admin_db.APPLIES_TO)
        anchor_type = st.selectbox(
            "锚类型（须与字段 applies_to 一致）",
            anchor_choices,
            index=anchor_choices.index(str(field.get("applies_to")))
            if str(field.get("applies_to")) in anchor_choices else 0,
            format_func=_anchor_label,
            key="dict_admin_val_anchor_type",
        )
        anchor_id = st.number_input(
            "锚 id（锚行主键，如 oald_senses.id）",
            min_value=1, step=1, key="dict_admin_val_anchor_id",
        )
        if value_type == "enum":
            enum_items = [str(v) for v in (field.get("enum_values") or [])]
            if enum_items:
                raw_value: Any = st.selectbox(
                    "枚举值（白名单内选一）", enum_items, key="dict_admin_val_enum",
                )
            else:
                raw_value = st.text_input(
                    "枚举值（该字段白名单为空，写入将被数据层拒绝）",
                    key="dict_admin_val_enum_fallback",
                )
        elif value_type == "bool":
            raw_value = st.selectbox(
                "布尔值", ("是（True）", "否（False）"), key="dict_admin_val_bool",
            )
        elif value_type == "date":
            raw_value = st.text_input("日期（YYYY-MM-DD）", key="dict_admin_val_date")
        elif value_type == "number":
            raw_value = st.text_input("数值（如 3.5）", key="dict_admin_val_num")
        else:
            raw_value = st.text_input("文本值", key="dict_admin_val_text")
        submitted = st.form_submit_button("写入值", use_container_width=True)
    if not submitted:
        return
    field_name = str(field.get("name") or field.get("code") or "")
    if str(anchor_type) != str(field.get("applies_to")):
        st.error(f"字段「{_esc(field_name)}」挂 "
                 f"{ANCHOR_LABELS.get(str(field.get('applies_to')), field.get('applies_to'))}"
                 f" 锚，不能写 {ANCHOR_LABELS.get(str(anchor_type), anchor_type)} 锚。")
        return
    if raw_value is None or str(raw_value).strip() == "":
        if field.get("required"):
            st.error(f"字段「{_esc(field_name)}」声明为必填，不能写空值。")
            return
        st.error("值不能为空。")
        return
    value = _coerce_value(value_type, raw_value)
    if value is None or (isinstance(value, str) and value == ""):
        if value_type == "date":
            # R2-3 专用报错二分：正则过但 fromisoformat 拒 = 格式对但日期不存在
            if _DATE_RE.match(str(raw_value).strip()):
                st.error("日期不存在：年月日组合不是真实日历日期"
                         "（如 2024-02-30），请核对后重填。")
            else:
                st.error("日期格式须为 YYYY-MM-DD。")
        elif value_type == "number":
            st.error("数值字段的值必须是有限数字。")
        elif value_type == "text":
            # R2-3 专用报错：text 在空值拦截之后只可能因超长失败
            # （上限与 dict_admin_db.MAX_VALUE_TEXT_LEN 同源，数据层再兜一道）
            st.error(f"文本超长（≤{dict_admin_db.MAX_VALUE_TEXT_LEN} 字符），"
                     "请精简后重试。")
        else:
            st.error("值不能为空。")
        return
    try:
        # R1-8：为锚写值是定制属性写路径 —— 中央闸门兜底（同页媒体/快照口径）
        guards.require_dict_admin()
    except PermissionError as e:
        st.error(f"⛔ {e}")
        return
    try:
        ok = dict_admin_db.set_value(
            int(field.get("id") or 0), str(anchor_type), int(anchor_id), value,
            updated_by=int(me.get("id") or 0),
        )
    except Exception as e:  # 防御性转 st.error
        logger.warning(f"set_value 意外失败（field={field.get('id')}）: {e}")
        st.error("写入失败：数据层返回异常（详见服务端日志），请稍后重试。")
        return
    if ok:
        st.success(f"已为锚 {anchor_type}:{int(anchor_id)} 写入字段"
                   f"「{_esc(field_name)}」的值。")
        st.rerun()
    else:
        st.error("写入失败：字段可能已弃用、锚类型与字段 applies_to 不符、"
                 "值不符合类型/枚举白名单，或与现值完全相同（未变更）。")


def _render_fields_tab(me: Dict[str, Any]) -> None:
    """定制属性分区：定义字段 + 字段列表（含弃用）+ 为锚写值（EAV）。"""
    st.markdown(f"<h3 style='{HEADER_H3}'>🏷️ 定制属性（EAV：字段定义 × 锚值）</h3>",
                unsafe_allow_html=True)
    projects = org_db.list_projects()
    if not projects:
        st.info("尚无词典项目：定制字段挂项目（custom_fields.project_id），"
                "请先由平台管理员建壳。")
        return
    options = _project_options(projects)
    project_label = st.selectbox(
        "选择项目", list(options.keys()), key="dict_admin_cf_project",
    )
    project_id = options[project_label]

    _render_define_field_form(project_id, me)

    fields = dict_admin_db.list_fields(project_id, include_deprecated=True)
    _render_fields_table(fields)

    left, right = st.columns(2)
    with left:
        _render_deprecate_field_form(fields)
    with right:
        _render_write_value_form(fields, me)

    st.markdown("")
    st.markdown(
        f"<div style='{get_card_style()}'>"
        f"<strong>口径提示</strong>"
        f"<p style='margin:6px 0 0 0;color:#4a5568;'>required 是表单侧强制必填的"
        f"声明（本页写入前拦截空值），数据层「存什么算什么」；字段弃用只停写不删行，"
        f"存量值随词条装配的定制属性区继续展示；字段定义后无更新接口，改枚举/改名"
        f"请弃用旧 code 后以新 code 重建。</p>"
        f"</div>",
        unsafe_allow_html=True,
    )


# ============================================
# Tab 7：媒体库（批次 4 Agent M；批次 8 Agent W 开通上传通道；资产归词典管理员）
# ============================================
# media_db 契约（§3-E）只含 register_asset / bind_asset / list_assets_for_anchor；
# R6-12 起列表查询与审定流转也下沉数据层（media_db.list_assets /
# advance_binding_status / next_binding_status 单一实现），本模块不再自留
# 这两份 SQL —— 页面只调数据层。仍留在本模块的少量只读辅助：
#   * _find_asset_by_sha256（登记去重预检）/ _list_media_bindings（流转取数）。
# 批次 8 上传通道：登记资产双轨之一 —— st.file_uploader 白名单文件先落盘
# data/media/{kind}/YYYYMM/{sha256 前 16 位}{后缀}（目录自动建），再复用同一条
# register_asset 登记链（license 必填、sha256 去重口径不变）；既有「服务器路径
# 登记」保留，两轨并存。上传全链不抛异常，失败一律 st.error 转述。

def _find_asset_by_sha256(sha256: str) -> Optional[Dict[str, Any]]:
    """按内容指纹查资产（**只读**）：登记前去重预检，命中即「已存在，复用」。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT id, kind, file_path, source, license, status
                   FROM media_assets WHERE sha256 = %s""",
                (sha256,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.warning(f"查询媒体资产指纹失败（按未命中处理）: {e}")
        return None


def _list_media_bindings(limit: int = MEDIA_LIST_LIMIT) -> List[Dict[str, Any]]:
    """绑定列表（**只读**）：绑定 × 资产联查，id 降序（审定流转的取数源）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """SELECT b.id, b.asset_id, b.anchor_type, b.anchor_id,
                          b.purpose, b.caption, b.sort_order,
                          b.status AS binding_status, b.created_at,
                          a.kind, a.file_path, a.license,
                          a.status AS asset_status
                   FROM media_bindings b
                   JOIN media_assets a ON a.id = b.asset_id
                   ORDER BY b.id DESC LIMIT %s""",
                (max(1, int(limit)),),
            )
            return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.warning(f"读取媒体绑定列表失败（按空列表处理）: {e}")
        return []


def _render_media_register_form(me: Dict[str, Any]) -> None:
    """登记资产表单：license 必填（空许可 st.error）+ sha256 去重「已存在复用」。"""
    st.markdown(f"<h4 style='{HEADER_H3}'>📦 登记资产</h4>", unsafe_allow_html=True)
    with st.form("dict_admin_media_register_form", clear_on_submit=True):
        file_path = st.text_input(
            "资产文件路径（服务器/仓库相对路径，须真实存在）",
            key="dict_admin_media_path",
            help="register_asset 会读取该文件计算 sha256 与大小；"
                 "仓库相对路径优先（便于换机）。",
        )
        kind = st.selectbox(
            "资产形态 kind", list(media_db.KINDS),
            format_func=lambda k: MEDIA_KIND_LABELS.get(k, k),
            key="dict_admin_media_kind",
        )
        source = st.text_input(
            "来源 source（如 ModernChineseDict/images）",
            key="dict_admin_media_source",
        )
        license_text = st.text_input(
            "许可 license（必填，如 CC BY 4.0 / 自产 TTS）",
            key="dict_admin_media_license",
            help="无许可的资产不入库（D⑥ 许可纪律同款硬约束）。",
        )
        submitted = st.form_submit_button("登记资产", use_container_width=True)
    if not submitted:
        return
    error = _media_register_error(file_path, kind, source, license_text)
    if error:
        st.error(error)  # 空 license 等必填缺失在表单侧给出可读拒绝
        return
    sha = _sha256_file(file_path)
    if sha is None:
        st.error("文件不可读：请确认路径真实存在且服务进程有读权限"
                 "（register_asset 同样要求文件可读）。")
        return
    existing = _find_asset_by_sha256(sha)
    if existing:
        st.warning(
            f"sha256 去重命中：资产 #{existing.get('id')} "
            f"（{existing.get('file_path')}）已存在，**复用该资产**，未重复入库。"
        )
        return
    asset_id = media_db.register_asset(
        str(file_path).strip(), kind, str(source).strip(),
        str(license_text).strip(),
    )
    if asset_id:
        st.success(f"已登记资产 #{asset_id}（状态=候选）。sha256 前 12 位：{sha[:12]}…")
        logger.info(f"dict_admin {me.get('username')} 登记媒体资产 #{asset_id} "
                    f"（kind={kind}, path={file_path}）")
        st.rerun()
    else:
        st.error("登记失败：文件不存在/参数非法/数据库不可用（media_db 已记日志）。")


def _render_media_bind_candidate() -> None:
    """上传 sha256 去重命中后的「直接绑定」区（session 复用候选驱动）。

    上传命中已登记资产时不重复落盘：把该资产记入 session 候选并在本区展开
    绑定表单（复用 _render_media_bind_form 的 cand 前缀实例，同键重复绑定
    幂等）；用户也可一键清除候选回到常规双轨登记。
    """
    candidate = st.session_state.get("dict_admin_media_bind_candidate")
    if not isinstance(candidate, dict) or not candidate.get("id"):
        return
    st.info(
        f"是否直接绑定？资产 #{candidate.get('id')}（{candidate.get('file_path')}）"
        "已登记，可直接在下方表单选锚与用途（同键重复绑定幂等，保留首次值）。"
    )
    _render_media_bind_form([candidate], key_prefix="dict_admin_media_bind_cand")
    if st.button("清除复用候选", key="dict_admin_media_bind_candidate_clear",
                 help="清除后回到常规双轨登记；不清除可继续用上方表单绑定该资产。"):
        del st.session_state["dict_admin_media_bind_candidate"]
        st.rerun()


def _render_media_upload_form(me: Dict[str, Any]) -> None:
    """上传落盘表单（批次 8 第二通道）：白名单文件 → 落盘 → register_asset。

    与既有「服务器路径登记」双轨（见 _render_media_register_form）：上传通道
    把文件写到 data/media/{kind}/YYYYMM/{sha256 前 16 位}{后缀}（内容寻址，
    目录自动建，同内容同路径），再走同一条登记链（license 必填、sha256 去重
    口径不变）。准入校验用纯函数 _validate_upload（扩展名/MIME 双白名单 +
    ≤50MB），落盘路径用 _upload_target_path（内容寻址）。任何失败只
    st.error/st.warning 提示，不抛异常；落盘成功但登记失败时文件保留，
    提示改走「服务器路径登记」按落盘路径补登。
    """
    st.markdown(f"<h4 style='{HEADER_H3}'>⬆️ 上传落盘（本地文件 → data/media）</h4>",
                unsafe_allow_html=True)
    with st.form("dict_admin_media_upload_form", clear_on_submit=True):
        upload = st.file_uploader(
            "选择媒体文件（png / jpeg / jpg / mp3 / mp4，单文件 ≤ 50MB）",
            type=MEDIA_UPLOAD_TYPES,
            key="dict_admin_media_upload",
        )
        source = st.text_input(
            "来源 source（如 自产截图 / CC BY 4.0 来源站点）",
            key="dict_admin_media_upload_source",
        )
        license_text = st.text_input(
            "许可 license（必填，与路径登记同款许可纪律）",
            key="dict_admin_media_upload_license",
            help="无许可的资产不入库（D⑥ 许可纪律同款硬约束）。",
        )
        submitted = st.form_submit_button("校验并上传落盘", use_container_width=True)
    if not submitted:
        _render_media_bind_candidate()
        return
    name = str(getattr(upload, "name", "") or "")
    size = getattr(upload, "size", 0) or 0
    mime = str(getattr(upload, "type", "") or "")
    # R2-2：准入校验带内容嗅探（魔数一致性）—— 未选文件（upload=None）不读
    # 字节，交由 _validate_upload 的「未选择文件」文案；校验通过后 payload
    # 必为 bytes，后续落盘/算 sha256 直接复用，不再二次 getvalue。
    payload = upload.getvalue() if upload is not None else None
    error = _validate_upload(name, size, mime, data=payload)
    if error:
        st.error(error)  # 白名单/大小/魔数拦截：表单侧给出可读拒绝，不落盘
        return
    ext = name.strip().lower().rsplit(".", 1)[-1]
    kind = MEDIA_UPLOAD_EXT_KINDS.get(ext)
    if kind is None:  # 理论不可达（_validate_upload 已挡白名单），防御一层
        st.error("文件类型不在上传白名单内（png/jpeg/jpg/mp3/mp4）。")
        return
    data = bytes(payload or b"")
    sha = hashlib.sha256(data).hexdigest()
    existing = _find_asset_by_sha256(sha)
    if existing:
        st.session_state["dict_admin_media_bind_candidate"] = {
            "id": int(existing.get("id") or 0),
            "kind": str(existing.get("kind") or ""),
            "file_path": str(existing.get("file_path") or ""),
        }
        st.warning(
            f"sha256 去重命中：资产 #{existing.get('id')} "
            f"（{existing.get('file_path')}）已登记，**复用该资产**，本次未重复"
            "落盘；是否直接绑定？见下方「复用候选」区。"
        )
        _render_media_bind_candidate()
        return
    target_abs = _upload_target_path(kind, data, _MEDIA_UPLOAD_BASE)
    if not target_abs:
        st.error("落盘路径计算失败（资产形态非法或内容不可读），上传已取消。")
        return
    try:
        os.makedirs(os.path.dirname(target_abs), exist_ok=True)
        with open(target_abs, "wb") as fh:
            fh.write(data)
    except OSError as e:
        logger.error(f"媒体上传落盘失败（{target_abs}）: {e}")
        st.error("落盘失败：无法写入 data/media（磁盘/权限问题，详见服务端日志）。")
        return
    rel_path = os.path.relpath(target_abs, _MEDIA_UPLOAD_BASE)
    # 入库路径：仓库相对路径优先（可移植，与加载脚本同口径）；
    # 进程 CWD 不在仓库根时 register_asset 读不到相对路径，降级用绝对路径。
    register_path = rel_path if os.path.isfile(rel_path) else target_abs
    asset_id = media_db.register_asset(
        register_path, kind, str(source or "").strip(),
        str(license_text or "").strip(), mime=mime,
    )
    if asset_id:
        st.success(f"已上传落盘 {rel_path} 并登记资产 #{asset_id}（状态=候选）。"
                   f"sha256 前 12 位：{sha[:12]}…")
        logger.info(f"dict_admin {me.get('username')} 上传媒体资产 #{asset_id} "
                    f"（kind={kind}, path={rel_path}, {size} 字节）")
        st.rerun()
    else:
        st.error("登记失败：参数非法/数据库不可用（media_db 已记日志）；文件已落盘 "
                 f"{rel_path}，可稍后用「服务器路径登记」按该路径补登记"
                 "（license 照填）。")


def _render_media_assets_table(assets: List[Dict[str, Any]]) -> None:
    """资产档案表（含许可列 —— 许可纪律可视）。"""
    if not assets:
        st.info("暂无资产记录（media_assets 为空、按状态筛选无命中，或数据库不可用）。")
        return
    rows: List[List[str]] = []
    for a in assets:
        status = str(a.get("status") or "")
        color = REVIEW_STATUS_COLORS.get(status, _INACTIVE_GRAY)
        rows.append([
            str(int(a.get("id") or 0)),
            _esc(MEDIA_KIND_LABELS.get(str(a.get("kind")), a.get("kind"))),
            _esc(a.get("file_path") or ""),
            _esc(a.get("source") or ""),
            _esc(a.get("license") or ""),
            _esc(str(a.get("sha256") or "")[:12]) + "…",
            _esc(_format_bytes(a.get("size_bytes"))),
            _badge(_esc(status or "—"), color),
        ])
    _render_table(
        ["ID", "形态", "文件路径", "来源", "许可", "sha256", "大小", "状态"],
        rows,
    )


def _render_media_bind_form(assets: List[Dict[str, Any]],
                            key_prefix: str = "dict_admin_media_bind") -> None:
    """绑定资产表单：四锚（word/sense/example/schema）× 用途，UNIQUE 幂等。

    key_prefix 区分同页多实例（批次 8：上传 sha256 复用候选的直绑表单用
    dict_admin_media_bind_cand 前缀；默认值即主绑定表单的既有 key，主流程
    行为不变）。
    """
    st.markdown(f"<h4 style='{HEADER_H3}'>🔗 绑定资产（四锚 × 用途）</h4>",
                unsafe_allow_html=True)
    if not assets:
        st.info("暂无资产可绑定：先在上方「登记资产」。")
        return
    asset_options = {
        (f"#{int(a.get('id') or 0)} "
         f"{MEDIA_KIND_LABELS.get(str(a.get('kind')), a.get('kind'))} "
         f"· {a.get('file_path')}"): int(a.get("id") or 0)
        for a in assets
    }
    with st.form(f"{key_prefix}_form", clear_on_submit=True):
        asset_label = st.selectbox(
            "选择资产", list(asset_options.keys()),
            key=f"{key_prefix}_asset",
        )
        anchor_type = st.selectbox(
            "锚类型（多态引用：词目/义位/例证/图式）",
            list(media_db.MEDIA_ANCHOR_TYPES),
            format_func=lambda t: MEDIA_ANCHOR_LABELS.get(t, t),
            key=f"{key_prefix}_anchor_type",
            help="锚行主键：word=现汉词条 zh_dict_entries.id 或 definitions.id；"
                 "sense=oald_senses.id（义位唯一锚）；example/schema 各按其表主键。",
        )
        anchor_id = st.number_input(
            "锚 id（锚行主键）", min_value=1, step=1,
            key=f"{key_prefix}_anchor_id",
        )
        purpose = st.selectbox(
            "用途 purpose", list(media_db.PURPOSES),
            format_func=lambda p: MEDIA_PURPOSE_LABELS.get(p, p),
            key=f"{key_prefix}_purpose",
        )
        caption = st.text_input(
            "图注 caption（例证媒体应含来源说明）", key=f"{key_prefix}_caption",
        )
        submitted = st.form_submit_button("绑定资产", use_container_width=True)
    if not submitted:
        return
    asset_id = asset_options.get(asset_label, 0)
    try:
        ok = media_db.bind_asset(
            asset_id, str(anchor_type), int(anchor_id), str(purpose),
            caption=str(caption or ""),
        )
    except Exception as e:  # media_db 理论上不抛，防御性转译
        logger.warning(f"bind_asset 意外失败（asset={asset_id}）: {e}")
        st.error("绑定失败：数据层返回异常（详见服务端日志），请稍后重试。")
        return
    if ok:
        st.success(f"已把资产 #{asset_id} 绑到 {anchor_type}:{int(anchor_id)}"
                   f"（用途 {purpose}，状态=候选；同键重复绑定幂等保留首次值）。")
        st.rerun()
    else:
        st.error("绑定失败：资产不存在、锚 id 非法（须为正整数）或数据库不可用"
                 "（media_db 已记日志；锚存在性由加载脚本/本页口径把关）。")


def _render_media_bindings_flow(bindings: List[Dict[str, Any]]) -> None:
    """绑定列表 + 审定流转（候选→审定→发布，逐级单步按钮）。"""
    st.markdown(f"<h4 style='{HEADER_H3}'>🧾 绑定列表与审定流转</h4>",
                unsafe_allow_html=True)
    if not bindings:
        st.info("暂无绑定记录（media_bindings 为空或数据库不可用）。")
        return
    rows: List[List[str]] = []
    for b in bindings:
        status = str(b.get("binding_status") or "")
        color = REVIEW_STATUS_COLORS.get(status, _INACTIVE_GRAY)
        anchor = str(b.get("anchor_type") or "")
        rows.append([
            str(int(b.get("id") or 0)),
            f"#{int(b.get('asset_id') or 0)} {_esc(b.get('file_path') or '')}",
            _esc(MEDIA_ANCHOR_LABELS.get(anchor, anchor)),
            str(int(b.get("anchor_id") or 0)),
            _esc(MEDIA_PURPOSE_LABELS.get(str(b.get("purpose")), b.get("purpose"))),
            _esc(b.get("caption") or "—"),
            _badge(_esc(status or "—"), color),
        ])
    _render_table(
        ["绑定 ID", "资产", "锚类型", "锚 id", "用途", "图注", "绑定状态"],
        rows,
    )

    flowable = [b for b in bindings if media_db.next_binding_status(b.get("binding_status"))]
    if not flowable:
        st.caption("没有可流转的绑定（全部已发布或状态未知）。")
        return
    flow_options = {
        (f"#{int(b.get('id') or 0)} "
         f"{MEDIA_PURPOSE_LABELS.get(str(b.get('purpose')), b.get('purpose'))} "
         f"→ {b.get('file_path')} · 当前 {b.get('binding_status')}"): b
        for b in flowable
    }
    flow_label = st.selectbox(
        "选择要流转的绑定（逐级单步：候选→审定→发布）",
        list(flow_options.keys()),
        key="dict_admin_media_flow_select",
    )
    binding = flow_options.get(flow_label)
    next_status = (media_db.next_binding_status(binding.get("binding_status"))
                   if binding else None)
    if st.button(
        f"➡️ 流转到「{next_status or '—'}」",
        type="primary",
        disabled=not next_status,
        key="dict_admin_media_flow_btn",
        help="逐级单步（不可跳级、不可回退）；乐观并发守卫 —— 两人同时流转只有一人生效。",
    ):
        if binding is None or next_status is None:
            st.error("绑定选择已变化，请重试。")
            return
        try:
            actor = guards.require_dict_admin()
        except PermissionError as e:
            st.error(f"⛔ {e}")
            return
        if media_db.advance_binding_status(
                int(binding.get("id") or 0),
                str(binding.get("binding_status")),
                next_status,
                reviewed_by=str((actor or {}).get("username") or "")):
            st.success(f"绑定 #{binding.get('id')} 已流转到「{next_status}」"
                       f"（审定人：{_esc(str((actor or {}).get('username') or '未知'))}）。"
                       "词条装配多模态区只取「发布」态绑定。")
            st.rerun()
        else:
            st.warning("流转未生效：绑定状态已被他人变更（乐观并发守卫）或数据库不可用。")


def _render_media_tab(me: Dict[str, Any]) -> None:
    """🖼️ 媒体库：登记资产（双轨：上传落盘 / 服务器路径；license 必填）·
    资产列表 · 绑定 · 审定流转。

    数据资产归词典管理员（帮助文档 §4.5/§六口径）：登记与审定都在本页，
    许可纪律是无许可不入库；词条装配只取「发布」态绑定。两条登记通道走
    同一条 register_asset 链（sha256 去重、license 必填口径一致）。
    """
    media_db.ensure_media_tables()
    st.markdown(f"<h3 style='{HEADER_H3}'>🖼️ 媒体库（数据资产归词典管理员）</h3>",
                unsafe_allow_html=True)
    st.caption(
        "登记资产双轨（⬆️ 上传落盘 / 服务器路径；sha256 去重，license 必填）→ "
        "绑定到四锚（词目/义位/例证/图式）→ 审定流转（候选→审定→发布，逐级单步）；"
        "义项脊柱媒体段与词条装配多模态区只取「发布」态绑定。"
    )
    _render_media_register_form(me)
    _render_media_upload_form(me)

    status_filter = st.selectbox(
        "资产列表按状态筛选", ("全部",) + tuple(media_db.MEDIA_STATUSES),
        key="dict_admin_media_asset_filter",
    )
    assets = media_db.list_assets(None if status_filter == "全部" else str(status_filter),
                                  limit=MEDIA_LIST_LIMIT)
    _render_media_assets_table(assets)

    st.markdown("")
    _render_media_bind_form(assets)
    st.markdown("")
    _render_media_bindings_flow(_list_media_bindings())


# ============================================
# Tab 8：出版导出（批次 8 G6 闸门执行页）
# 纯函数（G6 三卡摘要 / 闸门判定）无 st. 依赖，tests 直接测；
# DB/文件系统探测以可注入函数为默认实现（测试 monkeypatch/显式入参驱动）。
# ============================================

def _g6_check(key: str, status: str, title: str, detail: str) -> Dict[str, str]:
    """G6 检查项卡片数据（纯结构）：key/status/title/detail 四键。"""
    return {"key": key, "status": status, "title": title, "detail": detail}


def _g6_license_table_exists() -> Optional[bool]:
    """resource_registry 表在场探测（默认实现；None=库不可用探测失败）。"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS n FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
                (_G6_LICENSE_TABLE,),
            )
            row = cursor.fetchone()
            return bool(row) and int(row["n"] or 0) > 0
    except Exception as e:  # noqa: BLE001 —— 库不可用折叠为探测失败（占位）
        logger.warning(f"G6 许可终检：{_G6_LICENSE_TABLE} 在场探测失败: {e}")
        return None


def _g6_license_stats() -> Tuple[int, int]:
    """resource_registry 逐行许可审计（默认实现）→ (总行数, license 空值行数)。"""
    with get_db_cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(*) AS total, "
            f"SUM(CASE WHEN license IS NULL OR license = '' THEN 1 ELSE 0 END) "
            f"AS missing FROM {_G6_LICENSE_TABLE}"  # 表名来自模块常量白名单
        )
        row = cursor.fetchone()
        return int(row.get("total") or 0), int(row.get("missing") or 0)


def _g6_license_summary(
    exists_fn: Optional[Callable[[], Optional[bool]]] = None,
    stats_fn: Optional[Callable[[], Tuple[int, int]]] = None,
) -> Dict[str, str]:
    """G6 ① 许可终检（施工规范 §12）：resource_registry 逐行 license 审计。

    口径（架构规范 §3 G6「许可检查」/ D⑥ 许可纪律；批次 11 灰注转硬检——
    表随页面自举 registry_db.ensure_resource_registry_tables 建，数据面
    接通后本卡常态出硬结论）：
      * resource_registry 表未建（自举建表未生效）或库不可用 →
        灰注占位（降级如实，不渲染虚假健康状态）；
      * 表在场 → 逐行审计：license 空值行 >0 → 未过（❌ n/m 为空，
        无许可资源不得出版）；全非空 → 已过（✅ n 行）；
        0 行 → 已过但注明「空过（未登记资源）」。

    Args:
        exists_fn: 表在场探测（True/False，None=探测失败）；缺省查库。
        stats_fn: → (总行数, license 为空行数)；缺省查库。

    Returns:
        dict: {key, status, title, detail}（status ∈ passed/placeholder/failed）。
    """
    exists = _g6_license_table_exists if exists_fn is None else exists_fn
    stats = _g6_license_stats if stats_fn is None else stats_fn
    try:
        present = exists()
    except Exception as e:  # noqa: BLE001 —— 注入函数异常同折叠为占位
        logger.warning(f"G6 许可终检探测异常: {e}")
        present = None
    if present is None:
        return _g6_check(
            G6_KEY_LICENSE, G6_PLACEHOLDER, "许可终检",
            "数据库不可用：resource_registry 在场与许可审计无法执行"
            "（占位不拦内部快照、拦 published）。",
        )
    if not present:
        return _g6_check(
            G6_KEY_LICENSE, G6_PLACEHOLDER, "许可终检",
            "resource_registry 表未建（页面自举建表未生效，D⑥ 数据面未接通）："
            "许可终检占位 —— 建表接通后逐行 license 审计；"
            "占位不拦内部快照、拦 published。",
        )
    try:
        total, missing = stats()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"G6 许可终检审计异常: {e}")
        return _g6_check(
            G6_KEY_LICENSE, G6_PLACEHOLDER, "许可终检",
            "resource_registry 在场但许可审计失败（详见服务端日志）：按占位处理"
            "（占位不拦内部快照、拦 published）。",
        )
    if missing > 0:
        return _g6_check(
            G6_KEY_LICENSE, G6_FAILED, "许可终检",
            f"resource_registry {missing}/{total} 行许可（license）为空：无许可"
            "资源不得出版（D⑥ 许可纪律）—— 先补录许可再出版。",
        )
    if total == 0:
        return _g6_check(
            G6_KEY_LICENSE, G6_PASSED, "许可终检",
            "resource_registry 已建：0 行审计空过（未登记资源）—— 登记后"
            "逐行许可审计才有实质约束。",
        )
    return _g6_check(
        G6_KEY_LICENSE, G6_PASSED, "许可终检",
        f"resource_registry 共 {total} 行，license 逐行非空（审计通过）。",
    )


def _g6_style_version(path: str) -> Optional[str]:
    """从 style.yaml 文本解析 style_version 字段值（纯函数；无字段返回 None）。

    体例终检硬检口径（批次 11）：configs/style.yaml 在场**且**含
    ``style_version:`` 字段才算体例文件已研制。版本行形如
    ``style_version: 1.0``（允许行尾注释与成对引号）——只解析这一个键，
    不引完整 YAML 解析：本检查不该被 YAML 语法错误拖垮，正则足够。
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    for line in text.splitlines():
        matched = _G6_STYLE_VERSION_RE.match(line)
        if matched:
            version = matched.group("value").strip().strip("'\"").strip()
            return version or None
    return None


def _g6_style_summary(candidates: Optional[List[str]] = None) -> Dict[str, str]:
    """G6 ② 体例终检：style.yaml 在场＋style_version 字段硬检（批次 11 接真）。

    口径（架构规范 §3 G6「体例终检」/ §7 词典层体例文件）：
      * 候选路径（configs/、config/、data/、仓库根）任一存在 style.yaml
        **且**能解析出 style_version 字段 → 已过（在场路径与体例版本如实
        展示）；
      * 文件在场但缺 style_version 字段 → 占位（体例文件研制不完整）；
      * 全部缺位 → 占位「体例文件未研制」；
      * 工单线（体例配置页 6.7 的版本对比/变更工单）批次 12 接入后升级为
        版本对比检查；占位不拦内部快照、拦 published。

    Args:
        candidates: 候选绝对路径清单（测试可注入 tmp_path）；缺省取模块常量
            候选相对路径拼仓库根。
    """
    paths = list(candidates) if candidates else [
        os.path.join(_MEDIA_UPLOAD_BASE, rel) for rel in _G6_STYLE_CANDIDATE_RELS
    ]
    found: List[str] = []
    for path in paths:
        try:
            if os.path.isfile(path):
                found.append(path)
        except OSError:  # 防御：异常路径按缺位处理，不让单路径拖垮检查
            continue
    if found:
        version: Optional[str] = None
        for path in found:
            version = _g6_style_version(path)
            if version:
                break
        shown: List[str] = []
        for path in found[:2]:
            try:
                shown.append(os.path.relpath(path, _MEDIA_UPLOAD_BASE))
            except ValueError:  # 跨盘等 relpath 失败 → 原样展示
                shown.append(path)
        if version:
            return _g6_check(
                G6_KEY_STYLE, G6_PASSED, "体例终检",
                f"style.yaml 在场：{'、'.join(shown)}（体例版本 style_version "
                f"{version}，五节体例已研制；版本对比与变更工单归体例配置页 "
                "6.7，批次 12 工单线接入）。",
            )
        return _g6_check(
            G6_KEY_STYLE, G6_PLACEHOLDER, "体例终检",
            f"style.yaml 在场但未含 style_version 字段（{'、'.join(shown)}）："
            "体例文件研制不完整 —— 补 style_version 后转硬检；"
            "占位不拦内部快照、拦 published。",
        )
    return _g6_check(
        G6_KEY_STYLE, G6_PLACEHOLDER, "体例终检",
        "style.yaml 不在场（体例文件未研制）：体例终检占位 —— 体例文件按架构"
        "规范 §7 词典层清单研制入 configs/ 后转硬检；占位不拦内部快照、"
        "拦 published。",
    )


def _g6_scan_backups(backups_root: Any) -> Tuple[Optional[float], str]:
    """扫灾备根内最新 *.sql.gz / *.tar.gz（纯文件系统函数，tests 注 tmp_path）。

    口径（批次 11 备份新鲜硬检）：灾备备份＝scripts/backup_db.sh 落地产物
    （db/YYYYMMDD-HHMM.sql.gz ＋ media/YYYYMMDD-HHMM-media.tar.gz 同批），
    全树递归取最新 mtime；目录不存在 / 扫描失败 / 无匹配文件 → (None, '')。

    Returns:
        tuple: (最新 mtime, 相对 backups_root 的文件路径)；无产物 (None, '')。
    """
    root = str(backups_root)
    latest_ts: Optional[float] = None
    latest_rel = ""
    try:
        for dirpath, _dirnames, filenames in os.walk(root):
            for fname in filenames:
                low = fname.lower()
                if not (low.endswith(".sql.gz") or low.endswith(".tar.gz")):
                    continue
                try:
                    ts = os.stat(os.path.join(dirpath, fname)).st_mtime
                except OSError:
                    continue
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts
                    try:
                        latest_rel = os.path.relpath(
                            os.path.join(dirpath, fname), root)
                    except ValueError:  # 跨盘等 relpath 失败 → 文件名兜底
                        latest_rel = fname
    except OSError as e:
        logger.warning(f"G6 备份新鲜：backups 目录扫描失败（{root}）: {e}")
        return None, ""
    return latest_ts, latest_rel


def _g6_backup_summary(
    export_root: Any = None, backups_root: Any = None
) -> Dict[str, str]:
    """G6 ③ 备份新鲜：data/backups 灾备产物 mtime ＋ data/exports 最近快照。

    口径（批次 11 接真；架构规范 §6 备份三件套 / §15 运维性备份归平台管理员）：
      * 主证据＝data/backups/ 树内最新 *.sql.gz / *.tar.gz（备份脚本
        scripts/backup_db.sh 的落地产物）；参考证据＝data/exports 最近
        snapshot-* 目录（内容域快照是交付物，**快照≠灾备备份**）；
      * 灾备产物在场 → 已过（两条时间如实展示）；
      * 灾备产物缺席 → 占位「备份任务未运行」（即使快照在场）；
      * 新鲜度阈值（如「24 小时内有备份」）未设：运维工单未建，不编假阈值，
        本版只验「在场＋时间如实展示」；阈值化归批次 12 运维工单。

    Args:
        export_root: exports 根（缺省 export_center.EXPORT_ROOT；测试注入 tmp_path）。
        backups_root: 灾备根（缺省仓库 data/backups；测试注入 tmp_path）。
    """
    root = str(export_root) if export_root is not None else str(
        export_center.EXPORT_ROOT)
    broot = str(backups_root) if backups_root is not None else os.path.join(
        _MEDIA_UPLOAD_BASE, "data", "backups")

    backup_ts, backup_rel = _g6_scan_backups(broot)
    snap_ts: Optional[float] = None
    try:
        with os.scandir(root) as it:
            for entry in it:
                if not entry.name.startswith("snapshot-"):
                    continue
                try:
                    ts = entry.stat().st_mtime
                except OSError:
                    continue
                if snap_ts is None or ts > snap_ts:
                    snap_ts = ts
    except OSError as e:
        logger.warning(f"G6 备份新鲜：exports 目录扫描失败（{root}）: {e}")

    def _fmt(ts: Optional[float]) -> str:
        """时间戳 → 'YYYY-MM-DD HH:MM'（None → '—'，G6 备份卡展示口径）。"""
        return "—" if ts is None else datetime.fromtimestamp(ts).strftime(
            "%Y-%m-%d %H:%M")

    if backup_ts is None:
        if snap_ts is None:
            return _g6_check(
                G6_KEY_BACKUP, G6_PLACEHOLDER, "备份新鲜",
                "备份任务未运行（data/backups/ 未探测到 *.sql.gz / *.tar.gz "
                "灾备产物、data/exports 亦无内容域快照）：由平台管理员运行 "
                "scripts/backup_db.sh 或配置 cron（§6 备份三件套）；"
                "占位不拦内部快照、拦 published。",
            )
        return _g6_check(
            G6_KEY_BACKUP, G6_PLACEHOLDER, "备份新鲜",
            "备份任务未运行（data/backups/ 未探测到 *.sql.gz / *.tar.gz 灾备"
            "产物）：仅有内容域快照 " + _fmt(snap_ts) + "（快照≠灾备备份，"
            "§15 运维性备份归平台管理员）——运行 scripts/backup_db.sh 或配 "
            "cron 后转已过；占位不拦内部快照、拦 published。",
        )
    parts = [
        f"最近灾备备份（data/backups）：{_fmt(backup_ts)}（{backup_rel}）",
        f"最近内容域快照：{_fmt(snap_ts)}",
    ]
    return _g6_check(
        G6_KEY_BACKUP, G6_PASSED, "备份新鲜", "；".join(parts) + "。",
    )


def _g6_checklist(
    exists_fn: Optional[Callable[[], Optional[bool]]] = None,
    stats_fn: Optional[Callable[[], Tuple[int, int]]] = None,
    style_candidates: Optional[List[str]] = None,
    export_root: Any = None,
    backups_root: Any = None,
) -> List[Dict[str, str]]:
    """G6 三卡组装（顺序固定：许可 → 体例 → 备份；各卡独立降级不互相拖垮）。"""
    return [
        _g6_license_summary(exists_fn, stats_fn),
        _g6_style_summary(style_candidates),
        _g6_backup_summary(export_root, backups_root),
    ]


def _g6_gate_blockers(checks: List[Dict[str, str]]) -> List[str]:
    """G6 未全过项清单（纯函数）：「标题：徽章名」——占位与未过同拦 published。"""
    return [
        f"{c['title']}：{G6_STATUS_LABELS.get(c['status'], c['status'])}"
        for c in checks if c.get("status") != G6_PASSED
    ]


def _g6_gate_open(checks: List[Dict[str, str]]) -> bool:
    """G6 闸门是否放行（纯函数）：三项全过（无占位/未过）才 True。"""
    return not _g6_gate_blockers(checks)


def _g6_license_passed(checks: List[Dict[str, str]]) -> bool:
    """许可终检单项是否已过（快照 license_checked 旗标口径，非全闸门）。"""
    for check in checks:
        if check.get("key") == G6_KEY_LICENSE:
            return check.get("status") == G6_PASSED
    return False


def _advance_export_status(batch_id: int, from_status: str, to_status: str,
                           published_by: Optional[str] = None) -> bool:
    """快照状态单步流转（export_center 契约未含的页面私有辅助，docstring 留痕）。

    流转表（单向，无回退）：ready→published（G6 三项全过才放行 —— 闸门在
    页面层，本函数只做乐观并发单步）；ready→revoked（撤销，**单向不可逆**：
    撤销表示该快照作废、退出出版通道，如需再出版须重新生成快照 —— 不做
    revoked→ready 回退，防「撤销又复活」造成审计断链；published 亦为终态）。
    乐观并发守卫：UPDATE ... WHERE id=%s AND status=当前态 —— 两人同时流转
    只有一人生效（与 media_db.advance_binding_status 同款，R6-12 下沉）。

    出版留痕（R3-4b）：流转到 published 且 published_by 非空时，随流转写入
    export_batches 的 published_by（操作人，当前会话用户 username）与
    published_at（NOW()）—— 列语义即出版人，revoked 流转不写（撤销留痕走
    服务端日志）。列由 export_center.ensure_export_tables 幂等迁移（出版
    页入口已先调）；未传（既有调用方/测试缺省）维持旧 UPDATE 形态不碰这两列。

    Returns:
        bool: 流转生效 True；id 非法 / 流转表外 / 状态已变 / 库不可用 False。
    """
    try:
        bid = int(batch_id)
    except (TypeError, ValueError):
        return False
    if bid <= 0:
        return False
    allowed = {("ready", "published"), ("ready", "revoked")}
    if (str(from_status), str(to_status)) not in allowed:
        logger.error(
            f"非法快照流转被拒：{from_status!r} → {to_status!r}（单向流转表外）"
        )
        return False
    actor = str(published_by).strip() if published_by is not None else ""
    try:
        with get_db_cursor() as cursor:
            if actor and str(to_status) == "published":
                cursor.execute(
                    "UPDATE export_batches SET status = %s, "
                    "published_by = %s, published_at = NOW() "
                    "WHERE id = %s AND status = %s",
                    (str(to_status), actor, bid, str(from_status)),
                )
            else:
                cursor.execute(
                    "UPDATE export_batches SET status = %s "
                    "WHERE id = %s AND status = %s",
                    (str(to_status), bid, str(from_status)),
                )
            return cursor.rowcount > 0
    except Exception as e:  # noqa: BLE001
        logger.error(f"快照状态流转失败（id={bid}）: {e}")
        return False


def _render_g6_checklist(checks: List[Dict[str, str]]) -> bool:
    """G6 检查清单三卡（许可/体例/备份），返回闸门是否放行（三项全过）。"""
    cols = st.columns(3)
    for col, check in zip(cols, checks):
        status = str(check.get("status") or "")
        badge = _badge(
            _esc(G6_STATUS_LABELS.get(status, status)),
            G6_STATUS_COLORS.get(status, _INACTIVE_GRAY),
        )
        with col:
            st.markdown(
                f"<div style='{get_card_style()}'>"
                f"<b>{_esc(check.get('title') or '')}</b> {badge}"
                f"<div style='color:#4a5568;font-size:0.85em;margin-top:6px;"
                f"line-height:1.5;'>{_esc(check.get('detail') or '')}</div></div>",
                unsafe_allow_html=True,
            )
    if _g6_gate_open(checks):
        st.success("✅ G6 三项全过：闸门放行，可将 ready 快照标记为 published"
                   "（装配→出版）。")
        return True
    st.warning(
        "🚧 G6 未全过（" + "、".join(_g6_gate_blockers(checks)) + "）："
        "占位项不拦「生成内容域快照」（内部快照，MANIFEST 如实标注、不得对外"
        "交付），但拦 status ready→published 流转。"
    )
    return False


def _render_snapshot_builder(
    license_passed: bool, me: Dict[str, Any]
) -> None:
    """「生成内容域快照」按钮：guards 闸门 → export_center.build_content_snapshot。

    license_checked 旗标＝许可终检单项结论（非全闸门）：未过/占位时生成的
    快照按内部快照登记（MANIFEST 如实标注「未过（仅内部使用）」）。
    """
    st.markdown(
        f"<h4 style='{HEADER_H3}'>📦 内容域快照（§15 内容性导出唯一正式出口）</h4>",
        unsafe_allow_html=True,
    )
    st.caption(
        "内容域逐表 CSV 打包（词条资源/定制属性/例证/对译/媒体元数据；账号安全"
        "数据显式排除，缺表如实跳过并记录）。许可终检未过/占位时生成的快照按"
        "**内部快照**登记（license_checked=0），不得对外交付 —— 对外交付须 G6 "
        "三项全过后流转 published。"
    )
    if st.button("📦 生成内容域快照", key="pub_build_snapshot", type="primary"):
        try:
            actor = guards.require_dict_admin()
        except PermissionError as e:
            st.error(f"⛔ {e}")
            return
        result = export_center.build_content_snapshot(
            actor, license_checked=license_passed)
        if result.get("ok"):
            st.success(
                f"快照已生成：批次 #{result.get('batch_id')}，"
                f"共 {result.get('rows_total')} 行。"
            )
            st.caption(f"zip 路径：{result.get('zip_path')}")
            included = "、".join(result.get("tables_included") or []) or "（空）"
            skipped = "、".join(result.get("tables_skipped") or []) or "无"
            st.markdown(f"- 包含表：{included}\n- 跳过（表未建）：{skipped}")
            logger.info(
                f"dict_admin {me.get('username')} 生成内容域快照批次 "
                f"#{result.get('batch_id')}（license_checked={license_passed}，"
                f"{result.get('rows_total')} 行）"
            )
        else:
            st.error(str(result.get("error") or "快照构建失败（详见服务端日志）。"))


def _render_exports_table(exports: List[Dict[str, Any]]) -> None:
    """快照清单只读表（批次/文件/行数/许可终检/状态/时间）。"""
    if not exports:
        st.info("暂无快照记录：点上方「生成内容域快照」建立第一份"
                "（export_batches 为空或数据库不可用）。")
        return
    rows: List[List[str]] = []
    for e in exports:
        status = str(e.get("status") or "")
        lic = "已过" if e.get("license_checked") else "未过（内部快照）"
        rows.append([
            str(int(e.get("id") or 0)),
            _esc(str(e.get("file_path") or "")),
            str(int(e.get("rows_total") or 0)),
            lic,
            _badge(
                _esc(EXPORT_STATUS_LABELS.get(status, status)),
                EXPORT_STATUS_COLORS.get(status, _INACTIVE_GRAY),
            ),
            _esc(str(e.get("created_at") or "—")),
        ])
    _render_table(["批次", "快照文件", "行数", "许可终检", "状态", "生成时间"], rows)


def _render_exports_flow(
    exports: List[Dict[str, Any]], gate_open: bool, blockers: List[str]
) -> None:
    """快照状态流转区：ready→published（G6 全过才可用）／ready→revoked（单向撤销）。"""
    ready = [e for e in exports if str(e.get("status") or "") == "ready"]
    if not ready:
        st.caption("无 ready 态快照可流转（published/revoked 为终态，清单见上）。")
        return
    options: Dict[str, Dict[str, Any]] = {}
    for e in ready:
        label = (f"#{e.get('id')} · {e.get('file_path')} · "
                 f"{e.get('rows_total')} 行 · {e.get('created_at')}")
        options[label] = e
    label = st.selectbox(
        "选择 ready 态快照（逐条单步流转，乐观并发守卫）",
        list(options.keys()), key="pub_flow_select",
    )
    row = options[label]
    if not gate_open:
        st.warning(
            "G6 未全过（" + "、".join(blockers) + "）：published 流转禁用 —— "
            "占位项不拦内部快照，但须三项全过才能出版交付。"
        )
    col_pub, col_rev = st.columns(2)
    with col_pub:
        if st.button(
            "📤 标记 published（出版交付）", key="pub_publish_btn",
            type="primary", disabled=not gate_open,
            help="G6 三项全过才可出版；published 为终态；出版人/时间随流转留痕"
                 "（export_batches.published_by / published_at）。",
        ):
            try:
                pub_actor = guards.require_dict_admin()
            except PermissionError as e:
                st.error(f"⛔ {e}")
                return
            if _advance_export_status(
                int(row.get("id") or 0), "ready", "published",
                published_by=str((pub_actor or {}).get("username") or ""),
            ):
                st.success(
                    f"快照 #{row.get('id')} 已标记 published（出版交付，G6 已放行）。"
                )
                st.rerun()
            else:
                st.warning("流转未生效：快照状态已被他人变更（乐观并发守卫）"
                           "或数据库不可用。")
    with col_rev:
        if st.button(
            "🚫 撤销快照（ready→revoked，单向不可逆）", key="pub_revoke_btn",
            help="撤销表示该快照作废、退出出版通道；不可逆 —— 如需再出版须"
                 "重新生成快照（口径见 _advance_export_status docstring）。",
        ):
            try:
                guards.require_dict_admin()
            except PermissionError as e:
                st.error(f"⛔ {e}")
                return
            if _advance_export_status(int(row.get("id") or 0), "ready", "revoked"):
                st.success(
                    f"快照 #{row.get('id')} 已撤销（ready→revoked，单向；"
                    "如需再出版请重新生成快照）。"
                )
                st.rerun()
            else:
                st.warning("撤销未生效：快照状态已被他人变更（乐观并发守卫）"
                           "或数据库不可用。")


# ============================================
# 🗂️ 资源登记（批次 11 AV2：D⑥ resource_registry 数据面——G6 许可终检取数表）
# ============================================

# 表单字段上限（registry_db 列宽同款：应用层先拒超长值，不入库）
_REGISTRY_FORM_LIMITS = {
    "name": registry_db.MAX_NAME_LEN,
    "version": registry_db.MAX_VERSION_LEN,
    "coverage": registry_db.MAX_COVERAGE_LEN,
    "license": registry_db.MAX_LICENSE_LEN,
}


def _registry_form_error(name: Any, version: Any, coverage: Any,
                         license_text: Any) -> Optional[str]:
    """资源登记表单校验（纯函数）：必填缺失/超长返回错误文案，合法返回 None。

    口径（D⑥ resource_registry：name/version/coverage/license 四项必填；
    长度上限与 registry_db 列宽一致）。页面先给可读错误，registry_db 数据层
    再拒一道（纵深防御）。
    """
    checks = (
        ("name", "资源名称", name),
        ("version", "资源版本", version),
        ("coverage", "覆盖说明", coverage),
        ("license", "许可（license）", license_text),
    )
    for key, label, value in checks:
        if not isinstance(value, str) or not value.strip():
            if key == "license":
                return "许可（license）必填：无许可资源不得登记（D⑥ 许可纪律）。"
            return f"{label}必填。"
        if len(value.strip()) > _REGISTRY_FORM_LIMITS[key]:
            return f"{label}超长（≤{_REGISTRY_FORM_LIMITS[key]} 字符）。"
    return None


def _render_registry_table(resources: List[Dict[str, Any]]) -> None:
    """已登记资源只读表（ID/名称/版本/覆盖/许可/登记人/登记时间）。"""
    rows = [
        [
            str(int(r.get("id") or 0)),
            _esc(str(r.get("name") or "")),
            _esc(str(r.get("version") or "")),
            _esc(str(r.get("coverage") or "")),
            _esc(str(r.get("license") or "")),
            _esc(str(r.get("registered_by") or "—")),
            _esc(str(r.get("created_at") or "—")),
        ]
        for r in resources
    ]
    _render_table(
        ["ID", "资源名称", "版本", "覆盖说明", "许可", "登记人", "登记时间"],
        rows,
    )


def _render_registry_form(me: Dict[str, Any]) -> None:
    """资源登记表单：name/version/coverage/license 四项必填。

    写路径纵深防御（§15）：tab 入口已过角色门，登记调用点再过
    guards.require_dict_admin 中央闸门，通过后调 registry_db.register_resource
    （数据层守卫：必填/超长先拒，UNIQUE(name, version) 去重复用既有行）。
    """
    st.caption(
        "外部资源（语料库/参考词典/媒体包等）进入平台先在此登记：四项必填，"
        "同（名称, 版本）重复登记复用既有行；**许可必填** —— 无许可资源根本"
        "进不了库（D⑥ 许可纪律），G6 许可终检逐行审计的就是本表。双人双签"
        "审定线（技术录入＋词典管理员审定）批次 12 接入。"
    )
    col_a, col_b = st.columns(2)
    with col_a:
        name = st.text_input("资源名称（如 enTenTen21）", key="pub_reg_name")
        coverage = st.text_input(
            "覆盖说明（如 996 全义项）", key="pub_reg_coverage")
    with col_b:
        version = st.text_input("资源版本（如 2021）", key="pub_reg_version")
        license_text = st.text_input(
            "许可（如 CC BY 4.0）", key="pub_reg_license")
    if st.button("🗂️ 登记资源", key="pub_reg_submit", type="primary"):
        err = _registry_form_error(name, version, coverage, license_text)
        if err:
            st.error(f"⛔ {err}")
            return
        try:
            guards.require_dict_admin()
        except PermissionError as e:
            st.error(f"⛔ {e}")
            return
        rid = registry_db.register_resource(
            name, version, coverage, license_text,
            registered_by=str(me.get("username") or ""),
        )
        if rid:
            st.success(
                f"资源已登记：#{rid}（同（名称, 版本）已存在时复用既有登记行；"
                "许可变更批次 12 走审定工单。）"
            )
            logger.info(
                f"dict_admin {me.get('username')} 登记资源 #{rid}："
                f"{name} v{version}（coverage={coverage}, "
                f"license={license_text}）"
            )
        else:
            st.error(
                "登记未生效（数据层校验拒绝或数据库不可用，详见服务端日志）。"
            )


def _render_resource_registry_section(me: Dict[str, Any]) -> None:
    """🗂️ 资源登记块（登记表单＋资源清单；清单读取降级不拖垮本 tab）。"""
    st.markdown("")
    st.markdown(
        f"<h4 style='{HEADER_H3}'>🗂️ 资源登记（D⑥ 资源发布域数据面）</h4>",
        unsafe_allow_html=True,
    )
    try:
        resources = registry_db.list_resources(limit=50)
    except Exception as e:  # noqa: BLE001 —— list_resources 常态自降级为 []
        logger.warning(f"资源清单读取异常: {e}")
        resources = []
    if resources:
        _render_registry_table(resources)
    else:
        st.info(
            "暂无登记资源：语料库（enTenTen21）、参考词典（OALD/现汉7）、媒体包"
            "等进入平台的外部资源都应在此登记（license 必填）——登记后 G6 许可"
            "终检的逐行审计才有了审计对象。"
        )
    st.markdown("")
    _render_registry_form(me)


def _render_publication_tab(me: Dict[str, Any]) -> None:
    """📤 出版导出：G6 闸门执行页（工序 15；§15 内容性导出唯一权利人=词典管理员）。

    G6 三卡检查清单（许可终检/体例终检/备份新鲜——批次 11 灰注转硬检）＋
    🗂️ 资源登记块（许可终检数据面）＋内容域快照（生成＋清单＋ready→published /
    ready→revoked 单步流转）：占位项不拦内部快照、拦 published；快照生成/
    资源登记/状态流转都在 guards.require_dict_admin 闸门之后（纵深防御：
    tab 入口已过角色门，写路径调用点再过中央闸门）。
    """
    st.markdown(f"<h3 style='{HEADER_H3}'>🚧 G6 出版闸门检查清单（装配→出版）</h3>",
                unsafe_allow_html=True)
    st.caption(
        "G6 放行条件（架构规范 §3 闸门表）：许可检查＋体例终检＋备份新鲜三项全过，"
        "才允许把 ready 快照标记为 published —— 侵权/脏快照拦在出版之前。"
    )
    checks = _g6_checklist()
    gate_open = _render_g6_checklist(checks)
    blockers = _g6_gate_blockers(checks)
    _render_resource_registry_section(me)
    _render_snapshot_builder(_g6_license_passed(checks), me)
    st.markdown("")
    st.markdown(f"<h4 style='{HEADER_H3}'>🗂️ 快照清单与状态流转</h4>",
                unsafe_allow_html=True)
    exports = export_center.list_exports(limit=20)
    _render_exports_table(exports)
    st.markdown("")
    _render_exports_flow(exports, gate_open, blockers)


# ============================================
# 页面入口
# ============================================

def render_dict_admin_page() -> None:
    """📖 词典管理区入口（区级页面；页内八 tab，集成步骤挂进 app.py；
    批次 8 G6 末位增「📤 出版导出」tab；批次 11 该 tab 增「🗂️ 资源登记」块，
    G6 三卡灰注转硬检）。

    role gate 在函数入口（纵深防御 §6-4）：未登录提示登录；会话判定不过时
    再实时查库兜底；两层都不过渲染 st.warning「仅词典管理员」并 return ——
    页面内容（含各 tab 的取数）一概不执行。
    """
    me = _current_user()
    if not me:
        st.warning("请先登录后再访问词典管理区。")
        return
    if not _is_dict_admin(me) and not _db_confirms_dict_admin(me):
        st.warning("⛔ 仅词典管理员可访问词典管理区（dict_admin 角色；过渡期 admin "
                   "视为兼有）。如需权限请联系平台管理员授予。")
        return

    # 页面自举：业务表幂等就位（CREATE TABLE IF NOT EXISTS，开销可忽略；
    # users 表由登录链路的 ensure_user_tables 先行，这里顺带再兜一次；
    # 媒体两表随批次 4 媒体库 tab 一并就位；resource_registry 随批次 11
    # 出版 tab 的资源登记块与 G6 许可终检一并就位——表在场后许可终检
    # 出硬结论，不再以「表未建」灰注常态存在）
    org_db.ensure_org_tables()
    ai_ledger.ensure_ai_ledger_tables()
    dict_admin_db.ensure_dict_admin_tables()
    media_db.ensure_media_tables()
    registry_db.ensure_resource_registry_tables()

    st.markdown(f"<h1 style='{HEADER_H1}'>📖 词典管理</h1>", unsafe_allow_html=True)
    st.markdown(
        f"<h2 style='{HEADER_H2}'>词典管理员工作台（阶段 1 MVP）</h2>",
        unsafe_allow_html=True,
    )
    st.caption(
        "主编驾驶舱（自检 + AI 台账指标）· 项目成员（三级权限链第二级）· "
        "定制属性（EAV 字段与锚值）· 数据导入（批次台账，业务写入批次 3）· "
        "词条浏览器 · 任务分配（回避制/负荷上限校验批次 3）· "
        "媒体库（上传/登记/绑定/审定，双轨登记）· 出版导出（G6 闸门执行页＋"
        "资源登记数据面，批次 11 三卡灰注转硬检）。"
    )

    # 批次 2 集成：数据工具页（G）与任务分配 tab（H）并入本区——
    # 延迟导入避免模块加载顺序耦合；三个模块互不引用、无环。
    # 批次 4：义项脊柱随词条浏览器义项 expander 懒加载（data_pages 内接线），
    # 本区新增 🖼️ 媒体库 tab（媒体登记/绑定/审定，media_db 常量做下拉）；
    # 批次 8：媒体库开通上传落盘通道（登记双轨，见 _render_media_upload_form）；
    # 批次 8 G6：末位增 📤 出版导出 tab（G6 三卡检查清单＋内容域快照，
    # export_center 只读调用，状态流转为本模块私有单步辅助）；
    # 批次 11：出版 tab 增 🗂️ 资源登记块（registry_db 数据面，G6 许可终检
    # 取数表），三卡灰注转硬检（体例=style.yaml+style_version，备份=
    # data/backups 灾备产物）。
    import src.data_pages as data_pages
    import src.collab_pages as collab_pages

    (tab_cockpit, tab_members, tab_fields, tab_import,
     tab_browser, tab_assign, tab_media, tab_publish) = st.tabs(
        ["🧭 主编驾驶舱", "👥 项目成员", "🏷️ 定制属性", "📥 数据导入", "📖 词条浏览器",
         "📋 任务分配", "🖼️ 媒体库", "📤 出版导出"],
    )
    with tab_cockpit:
        _render_cockpit_tab()
    with tab_members:
        _render_members_tab(me)
    with tab_fields:
        _render_fields_tab(me)
    with tab_import:
        data_pages.render_import_page()
    with tab_browser:
        data_pages.render_browser_page()
    with tab_assign:
        collab_pages._render_assign_tab(me)
    with tab_media:
        _render_media_tab(me)
    with tab_publish:
        _render_publication_tab(me)
