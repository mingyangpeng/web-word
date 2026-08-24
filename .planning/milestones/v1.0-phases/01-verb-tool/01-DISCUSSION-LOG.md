# Phase 1: 设计系统基础 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-26
**Phase:** 01-verb-tool
**Areas discussed:** 颜色系统, 响应式断点, 可访问性优先级, 主题切换机制

---

## 颜色系统选择

| Option | Description | Selected |
|--------|-------------|----------|
| 现代科技风（蓝/紫渐变） | 主色调: 蓝色→紫色渐变，暗色模式: 深蓝/深紫背景 | |
| 自然运动风（绿/青色调） | 主色调: 绿色→青色，暗色模式: 深绿/深青背景 | |
| 简约现代风（蓝灰色系） | 主色调: 蓝灰色 (#4a5568)，辅助色: 浅蓝 (#63b3ed)，暗色模式: 深灰 (#1a202c) | |
| 高对比度无障碍风（橙/黑色） | 主色调: 橙色 (#ed8936)，背景: 白色/黑色，高对比度，符合 WCAG AA | |

**User's choice:** 白色，简约，学术风格
**Notes:** 最终选择蓝灰色系 + 白色背景，符合简约学术风格定位，高对比度易读性好

---

## 响应式断点选择

| Option | Description | Selected |
|--------|-------------|----------|
| 最小化改动（依赖 Streamlit 默认） | 仅在移动端自动堆叠，桌面/平板使用 `layout="wide"`，响应式断点: 1200px | |
| 精细控制（推荐） | 桌面 (>1200px): 三列布局，平板 (768-1200px): 两列布局，移动端 (<768px): 单列布局 | |
| 极简响应式 | 仅在 < 768px 时堆叠所有列，> 768px: `layout="wide"` | |
| 超响应式（优先移动端） | > 1024px: 标准布局，768-1024px: 缩小字体和间距，< 768px: 竖向布局 | |

**User's choice:** 不考虑移动端，只在桌面端用 Chrome 浏览器，极简响应式
**Notes:** 目标用户在桌面端 Chrome，依赖 Streamlit 原生响应式功能，减少开发复杂度

---

## 可访问性优先级

| Option | Description | Selected |
|--------|-------------|----------|
| 基础遵循 WCAG AA | 确保文字对比度 > 4.5:1，支持键盘导航（Tab 键），简单语义化 HTML 标签 | ✓ |
| 中等可访问性 | 基础 A + 语义化标签优化，添加 ARIA 标签到关键元素，增强表单标签 | |
| 高度可访问性 | 完全符合 WCAG AA/AAA 标准，详细的 ARIA 标签和角色，屏幕阅读器完全导航 | |

**User's choice:** 基础遵循 WCAG AA
**Notes:** 符合一般可访问性标准，Streamlit 默认元素已满足大部分要求，避免过度优化

---

## 主题切换机制

| Option | Description | Selected |
|--------|-------------|----------|
| Streamlit 原生 `st.color_picker` + 状态变量 | 简单实现，需要手动管理所有颜色变量，Streamlit 主题系统不完善 | |
| `st.set_theme()` API（Streamlit 1.25+） | 官方支持，Streamlit 内置主题管理，简单易用 | |
| `streamlit-extras` 库 + 自定义主题 | 更丰富的第三方组件，需要额外依赖 | |
| 无主题切换（固定浅色主题） | 无需实现，符合当前"简约学术风格"定位，减少复杂度 | ✓ |

**User's choice:** 无主题切换
**Notes:** 简化实现复杂度，符合"简约学术风格"定位，白色背景在学术/教育场景更合适

---

## Claude's Discretion

无

## Deferred Ideas

以下想法未包含在 Phase 1 范围内:

- **深色主题支持** - 技术可行但未实现
- **高级可访问性** - ARIA 标签、屏幕阅读器优化
- **自定义主题切换** - 用户选择主题颜色
- **复杂动画效果** - 在 Streamlit 中较难实现

---

*Phase: 01-verb-tool*
*Discussion log generated: 2026-05-26*
