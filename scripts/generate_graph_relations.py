#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
使用 LLM 生成单词知识图谱关系 - 简化版

该脚本从 movement_verbs.json 中读取单词数据，使用 LLM 分析它们之间的关系
并生成知识图谱数据保存到单独文件中
"""

import sys
import os
import json
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.llm_service import get_llm_service


def load_verbs_data():
    """加载单词数据"""
    filename = "data/movement_verbs.json"
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)


def build_graph_relations_prompt(verbs):
    """
    构建 LLM 提示词

    Args:
        verbs: 单词数据列表

    Returns:
        str: LLM 提示文本
    """
    # 按范畴组织单词
    categorized = {}
    for verb in verbs:
        cat = verb['category']
        if cat not in categorized:
            categorized[cat] = []
        categorized[cat].append(verb)

    words_text = ""
    for cat, verbs_list in categorized.items():
        words_text += f"\n{cat} ({len(verbs_list)} 个动词):\n"
        for v in verbs_list:
            words_text += f"  - {v['word']}: {v['chinese']} ({v['subclass']})\n"

    prompt = """你是一个语言学专家，需要为以下英语移动动词构建知识图谱关系。

""" + words_text + """

请分析这些单词之间的关系，包括：
1. 近义词关系（意义相近）
2. 反义词关系（意义相反）
3. 相关词关系（属于同一范畴或次范畴）
4. 同音词关系（发音相同）
5. 词族关系（具有相同的词根或前缀/后缀）

输出格式要求：
```json
{
  "relations": {
    "synonym": {"word1": ["word2", "word3"], ...},
    "antonym": {"word1": ["word2"], ...},
    "related": {"word1": ["word2", "word3"], ...},
    "homophone": {"word1": ["word2"], ...},
    "family": {"word1": ["word2", "word3"], ...}
  },
  "analysis": "简短的关系分析说明"
}
```

请确保：
- 关系分析基于语言学理论
- 同一个词只出现一次
- 输出只包含 JSON，不要其他文字
- 嵌套关系要合理
"""

    return prompt


def analyze_with_llm(verbs):
    """
    使用 LLM 分析单词关系

    Args:
        verbs: 单词数据列表

    Returns:
        dict: 关系数据
    """
    print("正在调用 LLM 分析单词关系...")
    print("=" * 60)

    llm = get_llm_service()

    prompt = build_graph_relations_prompt(verbs)

    try:
        response = llm.chat([
            {"role": "system", "content": "你是语言学专家，擅长分析单词之间的关系和构建知识图谱。"},
            {"role": "user", "content": prompt}
        ])

        # 提取 JSON
        content = response.get('choices', [{}])[0].get('message', {}).get('content', '')

        # 移除可能的 Markdown 代码块标记
        if content.startswith('```json'):
            content = content[7:]
        if content.startswith('```'):
            content = content[3:]
        if content.endswith('```'):
            content = content[:-3]
        content = content.strip()

        relations = json.loads(content)

        print(f"✅ LLM 分析完成")
        print(f"   发现 {len(relations.get('relations', {}))} 种关系类型")

        for rel_type, words in relations.get('relations', {}).items():
            print(f"   {rel_type}: {len(words)} 对")

        return relations

    except Exception as e:
        print(f"❌ LLM 分析失败: {str(e)}")

        # 返回空的关系数据
        return {
            "relations": {
                "synonym": {},
                "antonym": {},
                "related": {},
                "homophone": {},
                "family": {}
            },
            "analysis": f"LLM 分析失败: {str(e)}"
        }


def save_relations_data(relations, filename="data/word_graph_relations.json"):
    """
    保存关系数据到 JSON 文件

    Args:
        relations: 关系数据
        filename: 输出文件名

    Returns:
        str: 文件路径
    """
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    # 添加元数据
    output = {
        "metadata": {
            "created_at": datetime.now().isoformat(),
            "source": "LLM Analysis of Movement Verbs",
            "total_words": len(relations.get('relations', {})),
            "relation_types": list(relations.get('relations', {}).keys())
        },
        "relations": relations.get('relations', {}),
        "analysis": relations.get('analysis', '')
    }

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ 关系数据已保存到: {filename}")
    return filename


def print_relation_summary(relations):
    """打印关系摘要"""
    print("\n【知识图谱关系摘要】")
    print("=" * 60)

    for rel_type, word_pairs in relations.items():
        if word_pairs:
            print(f"\n{rel_type.upper()} 关系:")
            for word1, words in word_pairs.items():
                print(f"  {word1} <-> {', '.join(words)}")


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 单词知识图谱关系生成脚本")
    print("=" * 60)

    # 1. 加载数据
    print("\n【步骤 1/4】加载单词数据...")
    verbs = load_verbs_data()
    print(f"✅ 加载了 {len(verbs)} 个单词")

    # 2. 分析关系
    print("\n【步骤 2/4】使用 LLM 分析单词关系...")
    relations = analyze_with_llm(verbs)

    # 3. 打印摘要
    print("\n【步骤 3/4】打印关系摘要...")
    print_relation_summary(relations.get('relations', {}))

    # 4. 保存数据
    print("\n【步骤 4/4】保存关系数据...")
    filename = save_relations_data(relations)

    # 5. 显示示例
    print("\n【示例】近义词关系:")
    example_synonyms = relations.get('relations', {}).get('synonym', {})
    for word, related in list(example_synonyms.items())[:3]:
        print(f"  {word} <-> {', '.join(related)}")

    print("\n【示例】反义词关系:")
    example_antonyms = relations.get('relations', {}).get('antonym', {})
    for word, related in list(example_antonyms.items())[:3]:
        print(f"  {word} <-> {', '.join(related)}")

    print("\n" + "=" * 60)
    print("✅ 知识图谱关系生成完成！")
    print("=" * 60)
