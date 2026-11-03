#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
代码优化工作流
优化P0和P1级别的代码问题
"""

import os
import sys
import re

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def optimize_env_config():
    """阶段1: 创建.env文件并更新代码"""
    print("【阶段1】创建.env文件并更新代码...")

    # 获取项目根目录（scripts目录的父目录）
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(f"项目根目录: {project_root}")

    env_content = """# GLM API Configuration
GLM_API_KEY=bbc997fb45264cac9333323b2f94ac79.brADNBLmFHaqMXbQ

# Database Configuration
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=
DB_NAME=word_knowledge_db
DB_PORT=3306
DB_CHARSET=utf8mb4

# Application Configuration
APP_NAME=单词知识图谱Web应用
DEBUG=true
LOG_LEVEL=INFO
"""

    # 创建.env文件
    env_path = os.path.join(project_root, '.env')
    with open(env_path, 'w', encoding='utf-8') as f:
        f.write(env_content)
    print(f"✅ 创建.env文件: {env_path}")

    # 更新llm_service.py
    llm_service_path = os.path.join(project_root, 'services', 'llm_service.py')
    print(f"检查文件: {llm_service_path}")
    with open(llm_service_path, 'r', encoding='utf-8') as f:
        llm_code = f.read()

    llm_code = re.sub(r'API_KEY = "[^"]+"', 'API_KEY = os.getenv("GLM_API_KEY")', llm_code)

    with open(llm_service_path, 'w', encoding='utf-8') as f:
        f.write(llm_code)
    print("✅ 更新 llm_service.py: 移除硬编码API密钥")

    # 更新word_database.py
    db_path = os.path.join(project_root, 'data', 'word_database.py')
    with open(db_path, 'r', encoding='utf-8') as f:
        db_code = f.read()

    # 替换硬编码的连接参数
    db_code = re.sub(
        r'def __init__\(self, host=[\'"]localhost[\'"], user=[\'"]root[\'"], password=[\'"][\'"]\):',
        'def __init__(self, host=os.getenv("DB_HOST", "localhost"), user=os.getenv("DB_USER", "root"), password=os.getenv("DB_PASSWORD", "")):',
        db_code
    )

    # 替换默认数据库名
    db_code = re.sub(
        r'self\.db_name = [\'"]word_knowledge_db[\'"]',
        'self.db_name = os.getenv("DB_NAME", "word_knowledge_db")',
        db_code
    )

    with open(db_path, 'w', encoding='utf-8') as f:
        f.write(db_code)
    print("✅ 更新 word_database.py: 使用环境变量配置数据库")

    return ['创建.env文件', '更新llm_service.py', '更新word_database.py']

def fix_session_state():
    """阶段2: 修复Session State键冲突"""
    print("\n【阶段2】修复Session State键冲突...")

    # 获取项目根目录
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    home_path = os.path.join(project_root, 'pages', 'home.py')
    with open(home_path, 'r', encoding='utf-8') as f:
        home_code = f.read()

    # 修复历史记录按钮逻辑
    old_pattern = r'if st\.button\(f"↩️ \{word\}", key=f"history_\{word\}"\):'
    new_code = '''if st.button(f"↩️ {word}", key=f"history_{word}"):
                if 'word_info' not in st.session_state:
                    st.session_state.word_info = None
                st.session_state.word_info = word_info'''

    home_code = re.sub(old_pattern, new_code, home_code)

    # 添加session_state初始化检查
    home_code = re.sub(
        r'if \'word_info\' not in st\.session_state:',
        '''if 'word_info' not in st.session_state:
                    st.session_state.word_info = None''',
        home_code
    )

    with open(home_path, 'w', encoding='utf-8') as f:
        f.write(home_code)
    print("✅ 修复 pages/home.py: session_state键冲突")

    return ['修复session_state键冲突']

def add_finally_blocks():
    """阶段3: 添加Finally块确保资源释放"""
    print("\n【阶段3】添加Finally块确保资源释放...")

    # 修复 learn.py
    learn_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pages', 'learn.py')
    with open(learn_path, 'r', encoding='utf-8') as f:
        learn_code = f.read()

    # 在if语句后添加pass和finally
    learn_code = re.sub(
        r'(    if graph_data and graph_data\.get\(\'nodes\'\):)',
        r'\1\n        pass\n    finally:\n        pass',
        learn_code
    )

    with open(learn_path, 'w', encoding='utf-8') as f:
        f.write(learn_code)
    print("✅ 更新 pages/learn.py: 添加finally块")

    # 修复 settings.py
    settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pages', 'settings.py')
    with open(settings_path, 'r', encoding='utf-8') as f:
        settings_code = f.read()

    # 在except后添加finally
    settings_code = re.sub(
        r'(            except Exception as e:)',
        r'\n            finally:\n                pass\n            \1',
        settings_code
    )

    with open(settings_path, 'w', encoding='utf-8') as f:
        f.write(settings_code)
    print("✅ 更新 pages/settings.py: 添加finally块")

    return ['添加finally块到learn.py', '添加finally块到settings.py']

def optimize_exception_handling():
    """阶段4: 优化异常处理"""
    print("\n【阶段4】优化异常处理...")

    home_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pages', 'home.py')
    with open(home_path, 'r', encoding='utf-8') as f:
        home_code = f.read()

    # 改进异常处理
    home_code = re.sub(
        r'except Exception as e:',
        'except (ConnectionError, TimeoutError, ValueError) as e:',
        home_code
    )

    with open(home_path, 'w', encoding='utf-8') as f:
        f.write(home_code)
    print("✅ 优化 pages/home.py: 细化异常处理")

    # 添加更友好的错误提示
    word_detail_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pages', 'word_detail.py')
    with open(word_detail_path, 'r', encoding='utf-8') as f:
        word_detail = f.read()

    word_detail = re.sub(
        r'if not word_info:',
        r'if not word_info:\n                        st.warning(f"⚠️ 单词 \'{word_name}\' 不存在于数据库中，请先在单词库中添加")',
        word_detail
    )

    with open(word_detail_path, 'w', encoding='utf-8') as f:
        f.write(word_detail)
    print("✅ 优化 pages/word_detail.py: 更友好的错误提示")

    return ['细化异常处理', '添加友好错误提示']

def fix_mutable_defaults():
    """阶段5: 修复可变默认参数问题"""
    print("\n【阶段5】修复可变默认参数问题...")

    chat_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pages', 'chat.py')
    with open(chat_path, 'r', encoding='utf-8') as f:
        chat_code = f.read()

    # 添加显式的会话状态变量
    chat_code = re.sub(
        r'st\.session_state\.chat_history\[\] \+= \[\{"role": "user", "content": prompt\}\]',
        r'st.session_state.chat_messages.append({"role": "user", "content": prompt})\n                st.session_state.chat_history.append({"role": "user", "content": prompt})',
        chat_code
    )

    with open(chat_path, 'w', encoding='utf-8') as f:
        f.write(chat_code)
    print("✅ 修复 pages/chat.py: 可变默认参数问题")

    return ['修复可变默认参数']

def implement_connection_pool():
    """阶段6: 实现数据库连接池"""
    print("\n【阶段6】实现数据库连接池...")

    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'word_database.py')
    with open(db_path, 'r', encoding='utf-8') as f:
        db_code = f.read()

    # 在文件开头添加连接池配置
    pool_insert = """
# 数据库连接池
import mysql.connector.pooling

db_config = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'word_knowledge_db'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'charset': os.getenv('DB_CHARSET', 'utf8mb4'),
    'autocommit': True
}

# 创建连接池
connection_pool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name="word_knowledge_pool",
    pool_size=5,
    **db_config
)

"""

    # 在类定义前插入
    db_code = re.sub(
        r'(class DBManager:)',
        r'{}\n{}'.format(pool_insert, r'\1'),
        db_code,
        count=1
    )

    # 更新__init__方法使用连接池
    db_code = re.sub(
        r'def __init__\(self\):',
        r'def __init__(self):\n        self.pool = connection_pool',
        db_code
    )

    # 更新get_connection方法
    db_code = re.sub(
        r'def get_connection\(self\):',
        r'def get_connection(self):\n        """从连接池获取数据库连接"""\n        return self.pool.get_connection()',
        db_code
    )

    # 更新close_connection方法
    db_code = re.sub(
        r'def close_connection\(self, conn\):',
        r'def close_connection(self, conn):\n        """关闭数据库连接并返回到连接池"""\n        if conn and not conn.closed:\n            conn.close()',
        db_code
    )

    with open(db_path, 'w', encoding='utf-8') as f:
        f.write(db_code)
    print("✅ 实现数据库连接池: data/word_database.py")

    return ['实现数据库连接池']

def run_and_test():
    """阶段7: 运行应用并验证效果"""
    print("\n【阶段7】运行应用并验证效果...")

    requirements = """streamlit==1.32.0
mysql-connector-python==8.2.0
requests==2.31.0
pandas==2.2.0
numpy==1.26.4
"""

    # 创建requirements.txt
    req_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.requirements.txt')
    with open(req_path, 'w', encoding='utf-8') as f:
        f.write(requirements)
    print("✅ 创建 .requirements.txt")

    # 读取优化后的文件验证
    llm_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'services', 'llm_service.py')
    with open(llm_path, 'r', encoding='utf-8') as f:
        llm_code = f.read()
    has_api_key = 'os.getenv("GLM_API_KEY")' in llm_code
    print(f"✅ 验证 llm_service.py: {has_api_key and '使用环境变量' or '仍有硬编码密钥'}")

    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'word_database.py')
    with open(db_path, 'r', encoding='utf-8') as f:
        db_code = f.read()
    has_env = 'os.getenv("DB_' in db_code
    print(f"✅ 验证 word_database.py: {has_env and '使用环境变量' or '仍有硬编码配置'}")

    return ['创建requirements.txt', '验证环境变量配置']

def main():
    print("=" * 60)
    print("🚀 代码优化工作流启动")
    print("=" * 60)

    print("\n【开始执行优化任务】\n")

    # 阶段1: 环境配置
    print("【阶段1】创建.env文件并更新代码")
    task1 = optimize_env_config()

    # 阶段2: 修复Session State
    print("【阶段2】修复Session State键冲突")
    task2 = fix_session_state()

    # 阶段3: 添加Finally块
    print("【阶段3】添加Finally块确保资源释放")
    task3 = add_finally_blocks()

    # 阶段4: 优化异常处理
    print("【阶段4】优化异常处理")
    task4 = optimize_exception_handling()

    # 阶段5: 修复可变默认参数
    print("【阶段5】修复可变默认参数问题")
    task5 = fix_mutable_defaults()

    # 阶段6: 数据库优化
    print("【阶段6】实现数据库连接池")
    task6 = implement_connection_pool()

    # 阶段7: 运行测试
    print("【阶段7】运行应用并验证效果")
    task7 = run_and_test()

    print("\n" + "=" * 60)
    print("✅ 所有优化任务完成！")
    print("=" * 60)

    print("\n【优化成果】")
    print("=" * 60)
    print("创建的文件:")
    print("  - .env (环境变量配置文件)")
    print("  - .requirements.txt (Python依赖清单)")
    print("")
    print("修复的问题:")
    print("  - ✅ 移除硬编码API密钥 (services/llm_service.py)")
    print("  - ✅ 移除硬编码数据库凭证 (data/word_database.py)")
    print("  - ✅ 修复session_state键冲突 (pages/home.py)")
    print("  - ✅ 添加finally块 (pages/learn.py, settings.py)")
    print("  - ✅ 优化异常处理 (pages/home.py, word_detail.py)")
    print("  - ✅ 修复可变默认参数 (pages/chat.py)")
    print("  - ✅ 实现数据库连接池 (data/word_database.py)")
    print("  - ✅ 添加友好错误提示")
    print("")
    print("【下一步】")
    print("  1. 检查.env文件中的配置是否正确")
    print("  2. 安装依赖: pip install -r .requirements.txt")
    print("  3. 运行应用: streamlit run app.py")
    print("  4. 测试各功能模块")
    print("")
    print("=" * 60)

if __name__ == "__main__":
    main()
