# 中文动词释义优化器

## What This Is

A Streamlit-based tool that provides optimized Chinese verb definitions through semantic decomposition based on Talmy's motion event typology (1985). The app breaks down verbs into semantic elements: Way (方式), Path (路径), Direction (方向), and Manner/Aspect (体相) to provide richer, more precise meanings.

## Core Value

Enable accurate understanding of Chinese motion verbs through explicit semantic decomposition, helping users grasp the subtle differences between similar verbs (e.g., "跑进来" vs "冲进来").

## Requirements

### Validated

- Streamlit frontend with sticky search bar
- Semantic decomposition template (MOCK_DEFINITIONS)
- Mock statistics display (total queries, avg rating, hot verbs)
- Mock user feedback UI (rating + text input)

### Active

- Redesign main content area with improved layout
- Refactor sidebar structure
- Change navigation approach
- Implement multi-view design
- Improve data display and interaction

### Out of Scope

- Backend API integration (LLM, database) — separate milestone
- Real-time backend data connections

## Context

- **Technical Environment**: Python 3.11, Streamlit, Pandas
- **Domain**: Chinese linguistics and motion event typology
- **Current State**: Frontend complete with mock data; backend services pending
- **Target Platform**: Hugging Face Spaces (free hosting for ML/AI apps)

## Constraints

- **Streamlit Limitation**: No server-side templates or advanced UI components; limited customization
- **Single File**: Currently all code in app.py (to be refactored for maintainability)
- **Language**: Chinese interface, English technical comments
- **Performance**: Streamlit has some performance overhead for heavy UI updates

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Streamlit framework | Rapid prototyping, easy deployment to Hugging Face | ✓ Good — quick to build and deploy |
| Single-file initial codebase | Fast iteration on core functionality | ✓ Good — now ready for modularization |
| Mock data placeholder | Focus on UI/UX first before backend integration | ✓ Good — clear scope for this milestone |
| Semantic decomposition template | Based on validated research (Talmy 1985) | ✓ Good — theoretically grounded |

---
*Last updated: 2026-05-26 after complete UI/UX redesign milestone initialization*
