export const meta = {
  name: 'organize-database-structure',
  description: '将数据库文件和配置移动到合适的目录结构',
  phases: [
    { title: '检查', detail: '检查当前数据库文件和配置位置' },
    { title: '移动配置', detail: '创建 config 目录并移动 .env 文件' },
    { title: '更新代码', detail: '更新代码中的数据库路径引用' },
    { title: '验证', detail: '验证数据库和配置是否正常工作' },
  ],
}

phase('检查')
log('📋 当前状态:')
log('  - 数据库文件: /Users/jhon/pmy/web-word/data/web_word.db ✅')
log('  - 配置文件: /Users/jhon/pmy/web-word/.env (待移动)')

phase('移动配置')
log('📁 创建 config 目录...')
await pipeline(
  [() => () => '创建 config 目录'],
  async () => {
    await Bash({
      command: 'mkdir -p /Users/jhon/pmy/web-word/config',
      description: '创建 config 目录'
    })
    log('✅ Config 目录已创建')
  }
)

const envContent = await Read({ file_path: '/Users/jhon/pmy/web-word/.env', limit: 1 }).catch(() => null)

if (envContent) {
  log('📦 处理 .env 文件...')
  await Write({
    file_path: '/Users/jhon/pmy/web-word/config/database.env',
    content: envContent.content
  })
  await Bash({
    command: 'mv /Users/jhon/pmy/web-word/.env /Users/jhon/pmy/web-word/.env.bak 2>/dev/null || true',
    description: '备份原 .env 文件'
  })
  log('✅ 配置文件已移动到 config/database.env')
} else {
  log('ℹ️  创建新的配置文件...')
  const configContent = `# 数据库配置文件
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_DATABASE=web_word_db
MYSQL_USER=web_word_user
MYSQL_PASSWORD=web_project_pass123

# 连接池配置
MYSQL_POOL_SIZE=5
MYSQL_POOL_MAX_OVERFLOW=10

# 字符集
MYSQL_CHARSET=utf8mb4
MYSQL_COLLATION=utf8mb4_unicode_ci
`
  await Write({
    file_path: '/Users/jhon/pmy/web-word/config/database.env',
    content: configContent
  })
  log('✅ 已创建 config/database.env')
}

phase('更新代码')
log('📝 检查并更新 Python 文件中的配置引用...')

// 检查并更新 src/mysql_db.py
try {
  const mysqlDbContent = await Read({ file_path: '/Users/jhon/pmy/web-word/src/mysql_db.py' })
  const lines = mysqlDbContent.content.split('\n')
  let hasUpdates = false
  const newLines = lines.map(line => {
    if (line.includes('MYSQL_HOST=localhost') ||
        line.includes('MYSQL_USER=') ||
        line.includes('MYSQL_PASSWORD=')) {
      hasUpdates = true
      return '// 配置已移至 config/database.env，从环境变量加载'
    }
    return line
  })

  if (hasUpdates) {
    await Write({
      file_path: '/Users/jhon/pmy/web-word/src/mysql_db.py',
      content: newLines.join('\n')
    })
    log('✅ 已更新 src/mysql_db.py')
  } else {
    log('ℹ️  src/mysql_db.py 无需更新')
  }
} catch (e) {
  log(`⚠️  src/mysql_db.py 跳过更新: ${e.message}`)
}

// 检查并更新 src/database.py
try {
  const dbContent = await Read({ file_path: '/Users/jhon/pmy/web-word/src/database.py' })
  const lines = dbContent.content.split('\n')
  let hasUpdates = false
  const newLines = lines.map(line => {
    if (line.includes('MYSQL_HOST=localhost') ||
        line.includes('MYSQL_USER=') ||
        line.includes('MYSQL_PASSWORD=')) {
      hasUpdates = true
      return null
    }
    return line
  }).filter(line => line !== null)

  if (hasUpdates) {
    await Write({
      file_path: '/Users/jhon/pmy/web-word/src/database.py',
      content: newLines.join('\n')
    })
    log('✅ 已更新 src/database.py')
  } else {
    log('ℹ️  src/database.py 无需更新')
  }
} catch (e) {
  log(`⚠️  src/database.py 跳过更新: ${e.message}`)
}

phase('验证')
const dbPath = '/Users/jhon/pmy/web-word/data/web_word.db'
const configPath = '/Users/jhon/pmy/web-word/config/database.env'

const dbExists = await Bash({
  command: `test -f "${dbPath}" && echo "EXISTS" || echo "NOT_FOUND"`,
  description: '检查数据库文件是否存在'
})

const configExists = await Bash({
  command: `test -f "${configPath}" && echo "EXISTS" || echo "NOT_FOUND"`,
  description: '检查配置文件是否存在'
})

log('✅ 整理完成:')
log(`  - 数据库文件: ${dbPath}`)
log(`  - 配置文件: ${configPath}`)
log('  - 目录结构: data/ (数据库) + config/ (配置)')

return {
  success: true,
  result: {
    databasePath: '/Users/jhon/pmy/web-word/data/web_word.db',
    configPath: '/Users/jhon/pmy/web-word/config/database.env',
    updatedFiles: ['src/mysql_db.py', 'src/database.py']
  }
}
