"""
设置页面 - 系统配置
"""

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.constants import (
    DIFFICULTY_ALIAS_MAP,
    MASTERY_THRESHOLD,
    STATS_LIMIT_DEFAULT,
)
from config.logging_config import get_logger
from data.word_database import get_db_manager

logger = get_logger(__name__)


def app() -> None:
    """设置页面应用入口"""
    st.title("⚙️ 设置")
    st.subheader("📊 数据库状态")

    try:
        db = get_db_manager()
        words = db.get_all_words(limit=STATS_LIMIT_DEFAULT)
        total_words = len(words)

        # 一次性聚合查询关系类型计数（替代原 N+1 循环）
        relations_stats = db.get_relation_type_stats()

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("单词总数", total_words)
        with col2:
            st.metric("关系类型数", len(relations_stats))
        with col3:
            st.metric("总关系数", sum(relations_stats.values()))
        with col4:
            mastered = sum(
                1 for w in words if (w.get("proficiency_level") or 0) >= MASTERY_THRESHOLD
            )
            mastery_rate = (mastered / total_words * 100) if total_words else 0
            st.metric("掌握率", f"{mastery_rate:.1f}%")

        if relations_stats:
            st.divider()
            st.subheader("🔗 关系类型分布")
            st.bar_chart(relations_stats)

    except Exception as e:  # noqa: BLE001
        logger.exception("无法获取数据库状态")
        st.error(f"❌ 无法获取数据库状态: {e}")

    # ========== 导入单词 ==========
    st.divider()
    st.subheader("📥 导入单词")
    st.markdown("""
    从文本文件导入单词数据。

    文件格式要求：
    - 每行一个单词
    - 格式：单词 [音标] [词性] [难度]
    - 示例：
        ```
        happy /ˈhæpi/ adj simple
        intelligent /ɪnˈtelɪdʒənt/ adj medium
        run /rʌn/ verb medium
        ```
    """)

    uploaded_file = st.file_uploader(
        "选择单词文件",
        type=["txt", "csv", "md"],
        help="上传包含单词的文本文件",
    )

    if uploaded_file is not None:
        _import_words_from_file(db, uploaded_file)

    # ========== 数据库管理 ==========
    st.divider()
    st.subheader("🗄️ 数据库管理")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("🗑️ 清空所有单词"):
            if st.checkbox("确认清空所有单词", key="confirm_clear"):
                try:
                    words = db.get_all_words()
                    for word in words:
                        db.delete_word(word["id"])
                    st.success("✅ 单词库已清空")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    logger.exception("清空失败")
                    st.error(f"❌ 清空失败: {e}")

    with col2:
        if st.button("🔄 刷新数据"):
            st.session_state.words_data = None
            st.rerun()

    # ========== 系统信息 ==========
    st.divider()
    st.subheader("ℹ️ 系统信息")
    info_col1, info_col2 = st.columns(2)
    with info_col1:
        st.info("""
        **应用版本**: 1.1.0
        **技术栈**: Streamlit + Sigma.js + GLM-4.7-Flash + MySQL
        **API 提供商**: 智谱 AI
        """)
    with info_col2:
        st.info("""
        **数据存储**: 本地 MySQL 8.0
        **支持单词数量**: 理论上无限制
        **可视化**: 力导向图布局
        """)


def _parse_word_line(line: str) -> dict:
    """
    解析单行单词数据。

    支持格式：
        word
        word /phonetic/
        word /phonetic/ pos
        word /phonetic/ pos difficulty
        word pos
        word pos difficulty
    """
    parts = line.split()
    if not parts:
        return {}

    word = parts[0]
    pronunciation = None
    part_of_speech = None
    difficulty_level = "medium"

    if len(parts) >= 2:
        # 第二字段：音标 /.../ 或 词性
        if parts[1].startswith("/") and parts[1].endswith("/"):
            pronunciation = parts[1]
            if len(parts) >= 3:
                part_of_speech = parts[2]
            if len(parts) >= 4:
                difficulty_level = DIFFICULTY_ALIAS_MAP.get(
                    parts[3].lower(), "medium"
                )
        else:
            part_of_speech = parts[1]
            if len(parts) >= 3:
                difficulty_level = DIFFICULTY_ALIAS_MAP.get(
                    parts[2].lower(), "medium"
                )

    return {
        "word": word,
        "pronunciation": pronunciation,
        "part_of_speech": part_of_speech,
        "difficulty_level": difficulty_level,
    }


def _import_words_from_file(db, uploaded_file) -> None:
    """从上传的文件导入单词"""
    try:
        content = uploaded_file.read().decode("utf-8")
    except UnicodeDecodeError:
        st.error("❌ 文件编码不支持，请使用 UTF-8 编码")
        return

    imported_count = 0
    errors: list = []

    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        parsed = _parse_word_line(line)
        if not parsed:
            continue

        try:
            db.add_word(**parsed)
            imported_count += 1
        except Exception as e:  # noqa: BLE001
            errors.append(f"{parsed.get('word')}: {e}")

    st.success(f"✅ 成功导入 {imported_count} 个单词")
    if errors:
        st.warning(f"导入过程中遇到 {len(errors)} 个问题（仅显示前 10 个）：")
        for err in errors[:10]:
            st.write(f"  • {err}")


if __name__ == "__main__":
    app()
