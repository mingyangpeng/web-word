---
created: 2026-05-26
title: Phase 2 Context
---

# Phase 2: 主内容区重新设计 - 上下文

## Domain

重新设计动词输入和释义展示的核心区域，采用 Google 风格搜索界面，展示学术导向的语义分解结果。

**Phase 范围:**
- Google 风格搜索框（顶部固定，实时搜索）
- 四模块释义展示（范畴锚定、核心释义、多维辨异、图式示例）
- 语义分解表格（emoji + 颜色编码）
- 动词示例库（分类标签页）
- 学术导向的布局设计

---

## Locked Requirements

来自 ROADMAP.md:

### UI-01: 重新设计动词输入区域
**目标:** 改进搜索框和生成按钮

**实现方式:**
- Google 风格搜索框在顶部固定
- 输入即触发实时搜索（无需点击按钮）
- 空状态显示欢迎信息和提示语
- 搜索结果直接展示在搜索框下方

**约束:**
- 依赖 Phase 1 定义的颜色系统（白色 + 蓝灰色系 #4a5568）
- 依赖 Phase 1 定义的可复用组件（get_card_style 等）

### UI-02: 优化释义对比展示
**目标:** 更好的布局和视觉层次

**实现方式:**
- 卡片式分层展示
- 四个模块分卡片呈现，可折叠展开
- 每个模块清晰标注

**约束:**
- 学术文档参考：data/基于图式范畴化的英语移动动词多维释义模板研究.docx
- Talmy 位移事件框架：运动、路径、方式、方向、体相

### UI-03: 改进语义分解表格
**目标:** 更好的可视化

**实现方式:**
- Emoji 图标 + 颜色编码
- 四种语义要素：方式、路径、方向、体相
- 蓝色（运动类型）、绿色（路径类型）、橙色（方向类型）、紫色（体相类型）

### UI-04: 添加动词示例库
**目标:** 快速选择常用动词

**实现方式:**
- 分类标签页
- 按范畴分类（方式聚焦类、路径聚焦类、体相聚焦类）
- 点击标签快速切换

---

## Decisions

### 搜索输入区域 (UI-01)

**决策:** Google 风格搜索框在顶部固定，输入即触发实时搜索

**理由:**
- 类似 Google 的搜索体验更流畅
- 减少用户操作步骤（无需点击生成按钮）
- 实时反馈提升交互体验

**实现细节:**
- 搜索框使用 Phase 1 定义的输入框样式
- 输入框下方显示欢迎信息和提示语（空状态）
- 防抖处理（Debounce 300ms）避免频繁触发
- 搜索结果直接展示在搜索框下方

---

### 释义展示布局 (UI-02 & UI-03)

**决策:** 卡片式分层展示四模块释义，语义表格使用 emoji + 颜色编码

**理由:**
- 卡片式布局清晰区分不同模块，可折叠展开
- 学术研究需要层次化信息展示
- Emoji 和颜色编码提升可读性和辨识度

**实现细节:**
- 四个模块卡片：
  1. 原型与位移事件分析
  2. 范畴锚定
  3. 核心释义与多维辨异
  4. 图式示例
- 每个卡片可点击折叠/展开
- 语义表格：
  - 方式 🏃 → 蓝色
  - 路径 🛤️ → 绿色
  - 方向 🎯 → 橙色
  - 体相 💪 → 紫色

---

### 动词示例库 (UI-04)

**决策:** 分类标签页展示，按范畴分类

**理由:**
- 用户可以根据需要查看不同类别的动词
- 分类清晰，易于导航
- 避免一次性展示过多动词

**实现细节:**
- 三个标签：方式聚焦类、路径聚焦类、体相聚焦类
- 每个标签页显示该类别动词
- 点击标签快速切换到该类别
- 标签页使用 Phase 1 的 badge 风格

---

## Canoncial Refs

来自 ROADMAP.md 和 PROJECT.md:

- `.planning/ROADMAP.md` - Phase 2 详细目标和工作内容
- `.planning/PROJECT.md` - 项目背景和约束
- `.planning/REQUIREMENTS.md` - Phase 2 具体需求 (UI-01 到 UI-04)
- `.planning/STATE.md` - 项目状态跟踪
- `data/基于图式范畴化的英语移动动词多维释义模板研究 —— 兼论英汉图式对齐与译义转化.docx` - 学术文档参考
- `src/app.py` - 当前 Streamlit 应用实现
- `src/design_system.py` - 设计系统模块

---

## Codebase Context

**现有代码结构:**
- `src/app.py` - 单文件实现（所有样式和逻辑混在一起）
- `src/design_system.py` - 设计系统模块

**可复用资产:**
- 颜色系统：PRIMARY_COLOR, SECONDARY_COLOR, SUCCESS_COLOR, etc.
- 间距系统：SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL
- 组件样式：get_card_style(), get_button_primary_style(), get_input_field_style(), get_badge_style(), get_table_style()

**集成点:**
- app.py 第 34-49 行：Sticky 搜索栏实现
- app.py 第 206-302 行：主区域组件（需要重构）
- design_system.py：所有设计系统组件

**学术参考内容:**
- Talmy 位移事件框架：运动、路径、方式、方向、体相
- 四模块释义模板：范畴锚定 → 核心释义 → 多维辨异 → 图式示例
- 英汉图式对齐类型：完全对齐、部分对齐、零对齐、错位对齐

---

## Specifics

### 搜索框实现细节

1. **Sticky 定位**
   ```python
   position: sticky;
   top: 1.5rem;
   z-index: 999;
   background: rgba(255, 255, 255, 0.98);
   backdrop-filter: blur(12px);
   ```

2. **实时搜索防抖**
   - 输入停止 300ms 后触发搜索
   - 使用 `st.session_state` 存储当前搜索词

3. **空状态展示**
   - 欢迎标题和副标题
   - 提示语：输入动词后立即显示分析结果

### 卡片式展示结构

```python
# 四个卡片组件
def card_header(title, icon):
    """卡片标题栏"""
    pass

def prototype_event_card(prototype, events):
    """原型与位移事件分析"""
    pass

def template_card(anchor, core, distinction, example):
    """四模块释义模板"""
    pass

def alignment_card(alignment_type, translation):
    """英汉图式对齐"""
    pass
```

### 语义分解表格

```python
def semantic_table(data):
    """
    语义分解表格
    data: {"方式": [...], "路径": [...], "方向": [...], "体相": [...]}
    """
    pass
```

### 分类标签页

```python
# 三个分类
CATEGORY_MODE = "方式聚焦类"
CATEGORY_PATH = "路径聚焦类"
CATEGORY_MANNER = "体相聚焦类"

# 可选动词列表
VERBS_BY_CATEGORY = {
    CATEGORY_MODE: ["跑进来", "冲进来", "滑进来", ...],
    CATEGORY_PATH: ["走进去", "冲出去", ...],
    CATEGORY_MANNER: ["站着", "躺着", ...],
}
```

---

## Deferred Ideas

以下想法未包含在 Phase 2 范围内，可能在未来阶段考虑:

- **高级搜索功能** - 模糊搜索、多词组合搜索
- **动词词库动态加载** - 从数据库或文件加载更多动词
- **收藏功能** - 收藏常用动词
- **打印/导出功能** - 打印分析结果或导出为 PDF
- **对比功能** - 并排对比多个动词
- **历史记录** - 查看之前的查询历史

---

## Success Criteria (from ROADMAP.md)

Phase 2 完成的验收标准:

1. 搜索框在顶部固定，输入后立即显示结果
2. 释义展示有清晰的视觉层次和折叠功能
3. 语义分解表格在两种主题下都清晰可读（Phase 1 固定浅色主题）
4. 示例库可按分类快速切换
5. 整体布局符合学术研究导向

---

## Plan Context

此上下文将指导后续阶段:

**Phase 3 (侧边栏重构):**
- 侧边栏仍保持原有结构
- 主内容区采用新设计系统

**Phase 4-7:**
- 所有 UI 组件遵循 Phase 2 定义的学术导向布局
- 语义分解展示保持一致风格

---

*Created: 2026-05-26*
