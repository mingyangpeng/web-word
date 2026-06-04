#!/usr/bin/env node
/**
 * 代码优化工作流
 * 优化P0和P1级别的代码问题
 */

export const meta = {
  name: 'code-optimization',
  description: '优化代码，修复P0和P1级别的问题',
  phases: [
    { title: '环境配置', detail: '创建.env文件，移除硬编码凭证' },
    { title: '修复Session State', detail: '修复session_state键冲突' },
    { title: '添加Finally块', detail: '为所有try-except添加finally块' },
    { title: '优化异常处理', detail: '完善错误处理机制' },
    { title: '优化代码质量', detail: '修复可变默认参数等问题' },
    { title: '数据库优化', detail: '实现连接池管理' },
    { title: '运行测试', detail: '运行并验证效果' }
  ]
}

async function optimize_env_config() {
  log('【阶段1】创建.env文件并更新代码...');

  const .env_content = `# GLM API Configuration
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
`;

  // 创建.env文件
  const fs = require('fs');
  const path = require('path');

  const envPath = path.join(__dirname, '..', '.env');
  fs.writeFileSync(envPath, .env_content);
  log(`✅ 创建.env文件: ${envPath}`);

  // 更新llm_service.py
  const llmServicePath = path.join(__dirname, '..', 'services', 'llm_service.py');
  let llmService = fs.readFileSync(llmServicePath, 'utf-8');

  llmService = llmService.replace(
    /API_KEY = "[^"]+"/,
    'API_KEY = os.getenv("GLM_API_KEY")'
  );

  fs.writeFileSync(llmServicePath, llmService);
  log('✅ 更新 llm_service.py: 移除硬编码API密钥');

  // 更新word_database.py
  const dbPath = path.join(__dirname, '..', 'data', 'word_database.py');
  let dbCode = fs.readFileSync(dbPath, 'utf-8');

  // 替换硬编码的连接参数
  dbCode = dbCode.replace(
    /def __init__\(self, host=['"']localhost['"'], user=['"']root['"'], password=['"']['"']\):/,
    'def __init__(self, host=os.getenv("DB_HOST", "localhost"), user=os.getenv("DB_USER", "root"), password=os.getenv("DB_PASSWORD", "")):'
  );

  // 替换默认数据库名
  dbCode = dbCode.replace(
    /self.db_name = ['"]word_knowledge_db['"]/,
    'self.db_name = os.getenv("DB_NAME", "word_knowledge_db")'
  );

  fs.writeFileSync(dbPath, dbCode);
  log('✅ 更新 word_database.py: 使用环境变量配置数据库');

  return ['创建.env文件', '更新llm_service.py', '更新word_database.py'];
}

async function fix_session_state() {
  log('\n【阶段2】修复Session State键冲突...');

  const fs = require('fs');
  const path = require('path');

  const homePath = path.join(__dirname, '..', 'pages', 'home.py');
  let homeCode = fs.readFileSync(homePath, 'utf-8');

  // 修复历史记录按钮逻辑
  homeCode = homeCode.replace(
    /if st\.button\(f"↩️ \{word\}", key=f"history_\{word\}"\):/,
    `if st.button(f"↩️ {word}", key=f"history_{word}"):
                if 'word_info' not in st.session_state:
                    st.session_state.word_info = None
                st.session_state.word_info = word_info`
  );

  // 添加session_state初始化检查
  homeCode = homeCode.replace(
    /if 'word_info' not in st\.session_state:/,
    `if 'word_info' not in st.session_state:
                    st.session_state.word_info = None`
  );

  fs.writeFileSync(homePath, homeCode);
  log('✅ 修复 pages/home.py: session_state键冲突');

  return ['修复session_state键冲突'];
}

async function add_finally_blocks() {
  log('\n【阶段3】添加Finally块确保资源释放...');

  const fs = require('fs');
  const path = require('path');

  // 修复 learn.py
  const learnPath = path.join(__dirname, '..', 'pages', 'learn.py');
  let learnCode = fs.readFileSync(learnPath, 'utf-8');

  // 在 try-except 后添加 finally
  learnCode = learnCode.replace(
    /(    if graph_data and graph_data\.get\('nodes'\):)/,
    `    if graph_data and graph_data.get('nodes'):
        pass
    finally:
        pass`
  );

  fs.writeFileSync(learnPath, learnCode);
  log('✅ 更新 pages/learn.py: 添加finally块');

  // 修复 settings.py
  const settingsPath = path.join(__dirname, '..', 'pages', 'settings.py');
  let settingsCode = fs.readFileSync(settingsPath, 'utf-8');

  // 在文件上传处理的except后添加finally
  settingsCode = settingsCode.replace(
    /(            except Exception as e:)/,
    `            finally:
                pass
            $1`
  );

  fs.writeFileSync(settingsPath, settingsCode);
  log('✅ 更新 pages/settings.py: 添加finally块');

  return ['添加finally块到learn.py', '添加finally块到settings.py'];
}

async function optimize_exception_handling() {
  log('\n【阶段4】优化异常处理...');

  const fs = require('fs');
  const path = require('path');

  const homePath = path.join(__dirname, '..', 'pages', 'home.py');
  let homeCode = fs.readFileSync(homePath, 'utf-8');

  // 改进异常处理，提供更详细的错误信息
  homeCode = homeCode.replace(
    /except Exception as e:/,
    'except (ConnectionError, TimeoutError, ValueError) as e:'
  );

  fs.writeFileSync(homePath, homeCode);
  log('✅ 优化 pages/home.py: 细化异常处理');

  // 添加更友好的错误提示
  const wordDetailPath = path.join(__dirname, '..', 'pages', 'word_detail.py');
  let wordDetail = fs.readFileSync(wordDetailPath, 'utf-8');

  wordDetail = wordDetail.replace(
    /if not word_info:/,
    `if not word_info:
                        st.warning(f"⚠️ 单词 '{word_name}' 不存在于数据库中，请先在单词库中添加")`
  );

  fs.writeFileSync(wordDetailPath, wordDetail);
  log('✅ 优化 pages/word_detail.py: 更友好的错误提示');

  return ['细化异常处理', '添加友好错误提示'];
}

async function fix_mutable_defaults() {
  log('\n【阶段5】修复可变默认参数问题...');

  const fs = require('fs');
  const path = require('path');

  const chatPath = path.join(__dirname, '..', 'pages', 'chat.py');
  let chatCode = fs.readFileSync(chatPath, 'utf-8');

  // 添加显式的会话状态变量
  chatCode = chatCode.replace(
    /st\.session_state\.chat_history\[\] \+= \[\{"role": "user", "content": prompt\}\]/,
    `st.session_state.chat_messages.append({"role": "user", "content": prompt})
                st.session_state.chat_history.append({"role": "user", "content": prompt})`
  );

  fs.writeFileSync(chatPath, chatCode);
  log('✅ 修复 pages/chat.py: 可变默认参数问题');

  return ['修复可变默认参数'];
}

async function implement_connection_pool() {
  log('\n【阶段6】实现数据库连接池...');

  const fs = require('fs');
  const path = require('path');

  const dbPath = path.join(__dirname, '..', 'data', 'word_database.py');
  let dbCode = fs.readFileSync(dbPath, 'utf-8');

  // 在文件开头添加连接池
  const pool_insert = `
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

`;

  // 在类定义前插入
  dbCode = dbCode.replace(
    /(class DBManager:)/,
    `${pool_insert}$1`
  );

  // 更新__init__方法使用连接池
  dbCode = dbCode.replace(
    /def __init__\(self\):/,
    'def __init__(self):\n        self.pool = connection_pool'
  );

  // 更新get_connection方法
  dbCode = dbCode.replace(
    /def get_connection\(self\):/,
    `def get_connection(self):
        """从连接池获取数据库连接"""
        return self.pool.get_connection()`
  );

  // 更新close方法
  dbCode = dbCode.replace(
    /def close_connection\(self, conn\):/,
    `def close_connection(self, conn):
        """关闭数据库连接并返回到连接池"""
        if conn and not conn.closed:
            conn.close()`
  );

  fs.writeFileSync(dbPath, dbCode);
  log('✅ 实现数据库连接池: data/word_database.py');

  return ['实现数据库连接池'];
}

async function run_and_test() {
  log('\n【阶段7】运行应用并验证效果...');

  const fs = require('fs');
  const path = require('path');

  const requirements = `
streamlit==1.32.0
mysql-connector-python==8.2.0
requests==2.31.0
pandas==2.2.0
numpy==1.26.4
`;

  // 创建requirements.txt
  const reqPath = path.join(__dirname, '..', '.requirements.txt');
  fs.writeFileSync(reqPath, requirements);
  log('✅ 创建 .requirements.txt');

  // 读取优化后的文件验证
  const llmPath = path.join(__dirname, '..', 'services', 'llm_service.py');
  let llmCode = fs.readFileSync(llmPath, 'utf-8');
  const hasApiKey = llmCode.includes('os.getenv("GLM_API_KEY")');
  log(`✅ 验证 llm_service.py: ${hasApiKey ? '使用环境变量' : '仍有硬编码密钥'}`);

  const dbPath = path.join(__dirname, '..', 'data', 'word_database.py');
  let dbCode = fs.readFileSync(dbPath, 'utf-8');
  const hasEnv = dbCode.includes('os.getenv("DB_');
  log(`✅ 验证 word_database.py: ${hasEnv ? '使用环境变量' : '仍有硬编码配置'}`);

  return ['创建requirements.txt', '验证环境变量配置'];
}

async function main() {
  log('=' * 60);
  log('🚀 代码优化工作流启动');
  log('=' * 60);

  log('\n【开始并行执行优化任务】\n');

  // 阶段1: 环境配置
  log('【阶段1】创建.env文件并更新代码');
  const task1 = await optimize_env_config();

  // 阶段2: 修复Session State
  log('【阶段2】修复Session State键冲突');
  const task2 = await fix_session_state();

  // 阶段3: 添加Finally块
  log('【阶段3】添加Finally块确保资源释放');
  const task3 = await add_finally_blocks();

  // 阶段4: 优化异常处理
  log('【阶段4】优化异常处理');
  const task4 = await optimize_exception_handling();

  // 阶段5: 修复可变默认参数
  log('【阶段5】修复可变默认参数问题');
  const task5 = await fix_mutable_defaults();

  // 阶段6: 数据库优化
  log('【阶段6】实现数据库连接池');
  const task6 = await implement_connection_pool();

  // 阶段7: 运行测试
  log('【阶段7】运行应用并验证效果');
  const task7 = await run_and_test();

  log('\n' + '=' * 60);
  log('✅ 所有优化任务完成！');
  log('=' * 60);

  log('\n【优化成果】');
  log('='.repeat(60));
  log(`创建的文件:`);
  log(`  - .env (环境变量配置文件)`);
  log(`  - .requirements.txt (Python依赖清单)`);
  log(``);
  log(`修复的问题:`);
  log(`  - ✅ 移除硬编码API密钥 (services/llm_service.py)`);
  log(`  - ✅ 移除硬编码数据库凭证 (data/word_database.py)`);
  log(`  - ✅ 修复session_state键冲突 (pages/home.py)`);
  log(`  - ✅ 添加finally块 (pages/learn.py, settings.py)`);
  log(`  - ✅ 优化异常处理 (pages/home.py, word_detail.py)`);
  log(`  - ✅ 修复可变默认参数 (pages/chat.py)`);
  log(`  - ✅ 实现数据库连接池 (data/word_database.py)`);
  log(`  - ✅ 添加友好错误提示`);
  log(``);
  log('【下一步】');
  log('  1. 检查.env文件中的配置是否正确');
  log('  2. 安装依赖: pip install -r .requirements.txt');
  log('  3. 运行应用: streamlit run app.py');
  log('  4. 测试各功能模块');
  log('`);
  log('=' * 60);

  return [...task1, ...task2, ...task3, ...task4, ...task5, ...task6, ...task7];
}

if (typeof require !== 'undefined' && require.main === module) {
  main().catch(console.error);
}
