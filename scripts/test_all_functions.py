#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
功能测试脚本 - 逐个测试各个模块
"""

import sys
import os

# 确保项目根目录在路径中
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

print("=" * 60)
print("🧪 后端功能测试")
print("=" * 60)

all_tests_passed = True

# 测试1: 检查环境变量配置
print("\n【测试1】检查环境变量配置...")
api_key = os.getenv("GLM_API_KEY")
if api_key:
    print(f"✅ GLM API Key 已配置: {api_key[:20]}...")
else:
    print("❌ GLM API Key 未配置 (检查 .env 文件)")
    all_tests_passed = False

db_host = os.getenv("DB_HOST")
db_user = os.getenv("DB_USER")
if db_host and db_user:
    print(f"✅ 数据库配置: {db_host}/{db_user}")
else:
    print("❌ 数据库配置不完整")
    all_tests_passed = False

# 测试2: 导入主要模块
print("\n【测试2】导入主要模块...")
try:
    import streamlit as st
    print("✅ streamlit")
except Exception as e:
    print(f"❌ streamlit 导入失败: {str(e)}")
    all_tests_passed = False

try:
    import numpy as np
    print("✅ numpy")
except Exception as e:
    print(f"❌ numpy 导入失败: {str(e)}")
    all_tests_passed = False

try:
    import pandas as pd
    print("✅ pandas")
except Exception as e:
    print(f"❌ pandas 导入失败: {str(e)}")
    all_tests_passed = False

# 测试3: 导入数据库模块
print("\n【测试3】导入数据库模块...")
try:
    from data.word_database import get_db_manager
    print("✅ word_database 模块导入成功")
except Exception as e:
    print(f"❌ word_database 模块导入失败: {str(e)}")
    all_tests_passed = False

# 测试4: 测试数据库连接
print("\n【测试4】测试数据库连接...")
try:
    db = get_db_manager()
    test_word = db.get_word(word="test")

    if test_word:
        print(f"✅ 数据库连接成功，查询到测试数据: {test_word.get('word', 'N/A')}")
    else:
        print("⚠️ 数据库连接成功，但测试单词不存在")
        print("   说明：数据库可能为空，这是正常的")
        print("   建议：先添加一些测试单词到数据库")

except Exception as e:
    print(f"❌ 数据库连接失败: {str(e)}")
    all_tests_passed = False

# 测试5: 测试LLM服务
print("\n【测试5】测试LLM服务...")
try:
    from services.llm_service import get_llm_service
    llm = get_llm_service()
    print("✅ LLM服务模块导入成功")

    # 测试简单的单词分析
    print("   正在测试单词分析功能...")
    test_result = llm.analyze_word("hello")
    if "error" in test_result:
        print(f"❌ LLM 分析失败: {test_result.get('error')}")
        all_tests_passed = False
    else:
        print("✅ LLM 单词分析功能正常")
        content = test_result.get('choices', [{}])[0].get('message', {}).get('content', '')
        if content:
            print(f"   返回内容预览: {content[:50]}...")

except Exception as e:
    print(f"❌ LLM 服务测试失败: {str(e)}")
    all_tests_passed = False

# 测试6: 测试单词数据文件
print("\n【测试6】测试单词数据文件...")
try:
    import json
    data_file = "data/movement_verbs.json"
    if not os.path.exists(data_file):
        print(f"❌ 单词数据文件不存在: {data_file}")
        all_tests_passed = False
    else:
        with open(data_file, 'r', encoding='utf-8') as f:
            words_data = json.load(f)
        print(f"✅ 单词数据文件存在: {len(words_data)} 个单词")

        # 检查数据结构
        if words_data and isinstance(words_data, list):
            sample = words_data[0]
            if all(key in sample for key in ['word', 'chinese', 'category', 'subclass']):
                print("✅ 数据结构正确")
            else:
                print("❌ 数据结构不正确")
                print(f"   示例: {sample}")
        else:
            print("❌ 数据格式不正确")

except Exception as e:
    print(f"❌ 单词数据测试失败: {str(e)}")
    all_tests_passed = False

# 测试7: 测试关系数据文件
print("\n【测试7】测试关系数据文件...")
try:
    import json
    relations_file = "data/word_graph_relations.json"
    if not os.path.exists(relations_file):
        print(f"⚠️ 关系数据文件不存在: {relations_file}")
        print("   这是可选的，可以手动创建")
    else:
        with open(relations_file, 'r', encoding='utf-8') as f:
            relations_data = json.load(f)
        print(f"✅ 关系数据文件存在")
        print(f"   范畴数量: {len(relations_data.get('metadata', {}).get('relation_types', []))}")

except Exception as e:
    print(f"⚠️ 关系数据测试失败: {str(e)}")

# 测试8: 测试各个页面模块
print("\n【测试8】测试各个页面模块...")

pages_to_test = [
    ('pages/home.py', '首页'),
    ('pages/learn.py', '学习页面'),
    ('pages/chat.py', '对话页面'),
    ('pages/word_detail.py', '单词详情页面'),
    ('pages/words.py', '单词库页面'),
    ('pages/settings.py', '设置页面'),
]

for page_file, page_name in pages_to_test:
    if os.path.exists(page_file):
        try:
            with open(page_file, 'r', encoding='utf-8') as f:
                content = f.read()
            print(f"✅ {page_name}: {page_file}")
        except Exception as e:
            print(f"❌ {page_name}: {str(e)}")
            all_tests_passed = False
    else:
        print(f"⚠️ {page_name}: 文件不存在 {page_file}")

# 测试9: 测试应用主文件
print("\n【测试9】测试应用主文件...")
try:
    with open('app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 检查关键配置
    checks = [
        ('st.set_page_config', '页面配置'),
        ('st.sidebar.radio', '侧边栏导航'),
        ('pages import home', '首页导入'),
    ]

    for check_str, check_name in checks:
        if check_str in content:
            print(f"✅ {check_name}: 已配置")
        else:
            print(f"⚠️ {check_name}: 未配置")

except Exception as e:
    print(f"❌ 应用主文件测试失败: {str(e)}")
    all_tests_passed = False

# 测试10: 检查依赖安装
print("\n【测试10】检查Python依赖...")
try:
    import subprocess
    result = subprocess.run(
        ['/home/pmy/dev/miniconda3/envs/p312/bin/pip', 'list', '--format=json'],
        capture_output=True,
        text=True,
        timeout=10000
    )

    packages = result.stdout
    required_packages = ['streamlit', 'mysql.connector', 'pandas', 'numpy', 'requests']

    for pkg in required_packages:
        if pkg in packages:
            print(f"✅ {pkg}")
        else:
            print(f"❌ {pkg} - 未安装，需要安装")

except Exception as e:
    print(f"❌ 依赖检查失败: {str(e)}")

# 总结
print("\n" + "=" * 60)
if all_tests_passed:
    print("🎉 所有核心测试通过！")
    print("")
    print("✅ 可以启动应用:")
    print("   streamlit run app.py")
    print("   然后访问: http://localhost:8501")
else:
    print("⚠️ 部分测试失败，请检查上述错误")
    print("")
    print("💡 需要安装的依赖:")
    print("   pip install mysql-connector-python")

print("=" * 60)
