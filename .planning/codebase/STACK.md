# Technology Stack

**Analysis Date:** 2026/05/29

## Languages

**Primary:**
- Python 3.11 - Web application backend

**Secondary:**
- JavaScript (Node.js) - Project statistics script

## Runtime

**Environment:**
- Python 3.11+

**Package Manager:**
- pip - Package installation and dependency management
- Lockfile: requirements.txt (2 dependencies)

## Frameworks

**Core:**
- Streamlit [latest] - Web UI framework for data applications
- Streamlit components [latest] - Custom JavaScript/HTML component embedding

**Data Processing:**
- pandas - Data manipulation and CSV export

**Build/Dev:**
- Node.js - Development environment (for scripts)

## Key Dependencies

**Critical:**
- streamlit - UI framework with no-code component system
- pandas - Data handling and CSV export functionality

## Configuration

**Environment:**
- .streamlit/config.toml - Streamlit server and client configuration
  - headless mode enabled
  - port 8501
  - error details shown

**Build:**
- requirements.txt - Python dependencies (streamlit, pandas)

## Platform Requirements

**Development:**
- Python 3.11+
- Node.js (for statistics script)

**Production:**
- Hugging Face Spaces (deployment target)
- Any platform supporting Python 3.11+

## Database

**Storage:**
- SQLite 3 - Local database file (data/web_word.db)
  - Row factory enabled for dict access
  - WAL mode enabled
  - Foreign keys enabled
  - Context manager for connection handling

## Design System

**Custom Implementation:**
- design_system.py - Centralized design system module
  - Color palette (PRIMARY_COLOR, SECONDARY_COLOR, etc.)
  - Spacing system (SPACE_XS through SPACE_XL)
  - Typography scale (headers, body text)
  - WCAG AA contrast ratio compliance utilities
  - Reusable component style functions

## Project Structure

**Source Files:**
- src/app.py - Main Streamlit application (979 lines)
- src/database.py - SQLite database module (179 lines)
- src/design_system.py - Design system module (568 lines)

**Scripts:**
- scripts/get-stats.sh - Bash wrapper for Node.js statistics script
- scripts/get-stats.js - Project statistics generator

## Deployment

**Current:**
- Hugging Face Spaces (noted in CLAUDE.md as deployment target)
- Streamlit automatically serves via HF Spaces

---

*Stack analysis: 2026/05/29*
