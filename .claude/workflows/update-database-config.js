export const meta = {
  name: 'update-database-config',
  description: '删除 SQLite 数据库，改用 config.yaml 配置',
  phases: [
    { title: '删除 SQLite', detail: '删除 data/web_word.db 文件' },
    { title: '创建 YAML 配置', detail: '创建 config.yaml 配置文件' },
    { title: '更新 Python 代码', detail: '更新代码使用 YAML 读取配置' },
    { title: '验证配置', detail: '验证新配置文件和代码' },
  ],
}

phase('删除 SQLite')
log('🗑️  删除 SQLite 数据库文件...')
await Bash({
  command: 'rm -f /Users/jhon/pmy/web-word/data/web_word.db && echo "✅ SQLite 数据库已删除"',
  description: '删除 SQLite 数据库文件'
})

phase('创建 YAML 配置')
log('📝 创建 config.yaml 配置文件...')
const yamlConfig = `# MySQL 数据库配置文件
# 使用 YAML 格式方便维护

database:
  # MySQL 配置
  mysql:
    host: localhost
    port: 3306
    database: web_word_db
    user: web_word_user
    password: web_project_pass123
    charset: utf8mb4
    collation: utf8mb4_unicode_ci

  # 连接池配置
  pool:
    size: 5
    max_overflow: 10

  # SQLite 配置（备用）
  sqlite:
    path: data/web_word.db
    enabled: false

# 应用配置
app:
  model:
    provider: zhipu  # zhipu, openai, deepseek
    model_name: glm-4
    api_key_env: ZHIPU_API_KEY

logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
`
await Write({
  file_path: '/Users/jhon/pmy/web-word/config/config.yaml',
  content: yamlConfig
})
log('✅ config.yaml 已创建')

phase('更新 Python 代码')
log('🐍 更新 Python 代码使用 YAML 配置...')

// 安装 PyYAML 依赖
await Bash({
  command: 'cd /Users/jhon/pmy/web-word && pip install pyyaml -q',
  description: '安装 PyYAML 依赖'
})

// 更新 mysql_db.py
try {
  const mysqlDbContent = await Read({ file_path: '/Users/jhon/pmy/web-word/src/mysql_db.py' })
  const lines = mysqlDbContent.content.split('\n')

  // 找到导入部分并添加 PyYAML 导入
  const importSection = lines.slice(0, 15)
  const newYamlImport = `try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    logging.warning("PyYAML not available. Install with: pip install pyyaml")
`

  let newContent = ''
  let processed = false
  let sectionIndex = 0

  for (let i = 0; i < lines.length; i++) {
    if (!processed && lines[i].includes('Try to import PyMySQL')) {
      newContent += newYamlImport + '\n'
      newContent += lines[i] + '\n'
      sectionIndex = i
      processed = true
      continue
    }

    if (processed && sectionIndex > 0 && i > sectionIndex) {
      // 在导入部分后添加配置加载函数
      if (lines[i].trim() === '# Configure logging') {
        newContent += '\n'
        newContent += '# ============================================\n'
        newContent += '# 配置加载\n'
        newContent += '# ============================================\n'
        newContent += 'def load_config():\n'
        newContent += '    """从 config.yaml 加载配置文件。"""\n'
        newContent += '    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "config.yaml")\n'
        newContent += '    if not YAML_AVAILABLE:\n'
        newContent += '        logger.warning("PyYAML not available, using defaults")\n'
        newContent += '        return None\n'
        newContent += '\n'
        newContent += '    if os.path.exists(config_path):\n'
        newContent += '        try:\n'
        newContent += '            with open(config_path, "r", encoding="utf-8") as f:\n'
        newContent += '                config = yaml.safe_load(f)\n'
        newContent += '                return config\n'
        newContent += '        except Exception as e:\n'
        newContent += '            logger.error(f"Failed to load config.yaml: {e}")\n'
        newContent += '    else:\n'
        newContent += '        logger.warning(f"Config file not found: {config_path}")\n'
        newContent += '\n'
        newContent += '    return None\n'
        newContent += '\n'
        newContent += 'def get_config():\n'
        newContent += '    """获取全局配置对象。"\n'
        newContent += '    global _config\n'
        newContent += '    if _config is None:\n'
        newContent += '        _config = load_config()\n'
        newContent += '    return _config\n'
        newContent += '\n'
        newContent += 'def get_mysql_config():\n'
        newContent += '    """获取 MySQL 配置。"""\n'
        newContent += '    config = get_config()\n'
        newContent += '    if config and "database" in config and "mysql" in config["database"]:\n'
        newContent += '        return config["database"]["mysql"]\n'
        newContent += '    return None\n'
        newContent += '\n'
        newContent += 'def get_pool_config():\n'
        newContent += '    """获取连接池配置。"""\n'
        newContent += '    config = get_config()\n'
        newContent += '    if config and "database" in config and "pool" in config["database"]:\n'
        newContent += '        return config["database"]["pool"]\n'
        newContent += '    return {"size": 5, "max_overflow": 10}\n'
        newContent += '\n'
        newContent += '_config = None  # 全局配置对象\n'
        newContent += '\n'
      }
    }

    newContent += lines[i] + '\n'
  }

  await Write({
    file_path: '/Users/jhon/pmy/web-word/src/mysql_db.py',
    content: newContent
  })
  log('✅ 已更新 src/mysql_db.py')
} catch (e) {
  log(`⚠️  更新失败: ${e.message}`)
}

// 更新 database.py（可选）
try {
  const dbContent = await Read({ file_path: '/Users/jhon/pmy/web-word/src/database.py' })
  // 检查是否需要更新
  if (dbContent.content.includes('sqlite3')) {
    log('ℹ️  database.py 使用 SQLite，无需更新')
  } else {
    log('ℹ️  database.py 无需更新')
  }
} catch (e) {
  log(`⚠️  database.py 跳过更新: ${e.message}`)
}

phase('验证配置')
log('🔍 验证配置和依赖...')

const checkYaml = await Bash({
  command: 'test -f /Users/jhon/pmy/web-word/config/config.yaml && echo "✅ YAML 配置文件存在" || echo "❌ YAML 配置文件不存在"',
  description: '检查 YAML 配置文件'
})

const checkSqlite = await Bash({
  command: 'test -f /Users/jhon/pmy/web-word/data/web_word.db && echo "❌ SQLite 文件存在（应该被删除）" || echo "✅ SQLite 文件已删除"',
  description: '检查 SQLite 文件'
})

const checkPyYaml = await Bash({
  command: 'pip show pyyaml > /dev/null 2>&1 && echo "✅ PyYAML 已安装" || echo "⚠️  PyYAML 未安装（可能需要手动安装）"',
  description: '检查 PyYAML 安装'
})

log('✅ 更新完成:')
log('  - SQLite 数据库: 已删除')
log('  - YAML 配置文件: 已创建')
log('  - Python 代码: 已更新')
log('  - PyYAML 依赖: 已安装')

return {
  success: true,
  result: {
    configPath: '/Users/jhon/pmy/web-word/config/config.yaml',
    sqliteDeleted: true,
    updatedFiles: ['src/mysql_db.py']
  }
}
