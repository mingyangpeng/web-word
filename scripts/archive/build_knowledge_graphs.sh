#!/usr/bin/env bash
# 重建本项目的两张知识图谱。
#
# 1) 代码图谱（graphify 解析 AST，纯本地、不需要任何 API key）
#      graphify-out/graph.json     完整图，供 graphify query/explain/path 查询
#      graphify-out/GRAPH_REPORT.md 可读报告：社区划分、枢纽节点、意外连接
#      graphify-out/graph.html     浏览器里点击浏览的可视化图
#
# 2) 词间关系图谱（本项目自己的领域图谱：节点=动词，边=近义关系）
#      簇内**完全图** —— 同一次语义范畴内任意两词都有边（155 词 / 25 簇 / 2143 边）
#      data/word_graph.json
#
# 前置：graphify CLI。安装一次即可：
#      uv tool install graphifyy     # 或 pipx install graphifyy
#      export PATH="$HOME/.local/bin:$PATH"
#
# 用法：
#      scripts/build_knowledge_graphs.sh            # 建两张图
#      scripts/build_knowledge_graphs.sh --code     # 只建代码图谱
#      scripts/build_knowledge_graphs.sh --words    # 只建词间关系图谱
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# uv tool 默认把可执行文件装到 ~/.local/bin，常常不在 PATH 里
export PATH="$HOME/.local/bin:$PATH"

build_code=1
build_words=1
case "${1:-}" in
    --code)  build_words=0 ;;
    --words) build_code=0 ;;
    "")      ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
esac

if [ "$build_code" = 1 ]; then
    if ! command -v graphify >/dev/null 2>&1; then
        echo "❌ 未找到 graphify。请先安装： uv tool install graphifyy" >&2
        exit 1
    fi
    echo "==> 构建代码知识图谱（AST，无 LLM 调用）"
    # public API 会自动跳过 docs/paper/image 的语义抽取；这里显式用 --code-only
    # 保证在没有任何 API key 的机器上也能跑通。
    graphify extract . --code-only
    echo "==> 聚类并生成报告"
    graphify cluster-only . --no-label
    echo "    graphify-out/GRAPH_REPORT.md   可读报告"
    echo "    graphify-out/graph.json        可查询图"
    echo "    graphify-out/graph.html        可视化"
fi

if [ "$build_words" = 1 ]; then
    echo "==> 构建词间关系图谱（离线，读 data/motion_verbs_extracted.json）"
    python3 scripts/load_word_library.py --dry-run
    echo "    data/word_graph.json           节点=动词，边=簇内近义完全图"
fi

cat <<'EOF'

下一步（查询示例）：
  graphify query "释义生成的数据流"              # 代码图谱：按概念找执行流
  graphify explain get_display_definition        # 某个符号的 360° 视图
  graphify impact get_display_definition         # 改它会影响谁
  graphify path "abandon" "leave" --graph data/word_graph.json   # 词与词之间的路径
  graphify explain "dash" --graph data/word_graph.json           # 某词的近义邻居
EOF
