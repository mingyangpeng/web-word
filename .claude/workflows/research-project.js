export const meta = {
  name: 'research-project',
  description: '全面研究当前项目，并行分析多个方面',
  phases: [
    { title: '探索项目结构', detail: '分析项目目录结构和文件组织' },
    { title: '代码质量检查', detail: '检查代码质量、风格和最佳实践' },
    { title: '配置验证', detail: '验证配置文件的完整性和正确性' },
    { title: '数据库连接', detail: '检查数据库配置和连接状态' },
    { title: '依赖项检查', detail: '检查 Python 依赖和可用性' },
    { title: '文档完整性', detail: '检查文档是否完整和准确' },
  ],
}

phase('探索项目结构')
const structureInfo = await parallel([
  async () => {
    log('📁 分析目录结构...')
    const files = await Bash({
      command: 'find /Users/jhon/pmy/web-word -type f -name "*.py" -o -name "*.md" -o -name "*.yaml" -o -name "*.yml" -o -name "*.toml" -o -name "*.json" | grep -v __pycache__ | grep -v .git | grep -v ".claude" | sort',
      description: '列出项目中的 Python、文档和配置文件'
    })

    const directories = await Bash({
      command: 'find /Users/jhon/pmy/web-word -type d -maxdepth 2 | grep -v __pycache__ | grep -v .git | grep -v ".claude" | sort',
      description: '列出项目目录结构'
    })

    return {
      files: files.stdout.split('\n').filter(Boolean),
      directories: directories.stdout.split('\n').filter(Boolean)
    }
  },
  async () => {
    log('📊 分析文件大小和类型分布...')
    const stats = await Bash({
      command: 'find /Users/jhon/pmy/web-word -type f \( -name "*.py" -o -name "*.md" -o -name "*.yaml" -o -name "*.toml" \) -exec du -h {} + 2>/dev/null | sort -hr | head -20',
      description: '统计文件大小分布'
    })

    const extensions = await Bash({
      command: 'find /Users/jhon/pmy/web-word -type f \( -name "*.py" -o -name "*.md" -o -name "*.yaml" -o -name "*.toml" -o -name "*.json" \) -exec file {} \; | grep -oE "\.[a-z]+$" | sort | uniq -c | sort -rn',
      description: '统计文件类型分布'
    })

    return { sizeStats: stats.stdout, extensions: extensions.stdout }
  }
])

log('项目文件统计:')
structureInfo.forEach((result, i) => {
  if (i === 0) {
    log(`  - Python 文件: ${result.files.filter(f => f.endsWith('.py')).length}`)
    log(`  - 文档文件: ${result.files.filter(f => f.endsWith('.md')).length}`)
    log(`  - 配置文件: ${result.files.filter(f => f.endsWith('.yaml') || f.endsWith('.yml')).length}`)
    log(`  - 目录结构: ${result.directories.length}`)
  }
})

phase('代码质量检查')
const codeQuality = await parallel([
  async () => {
    log('🔍 检查 Python 代码风格...')
    const pyflakes = await Bash({
      command: 'python -m py_compile /Users/jhon/pmy/web-word/src/*.py 2>&1 | head -20',
      description: '检查 Python 语法错误'
    })

    const importCheck = await Bash({
      command: 'python -c "import sys; sys.path.insert(0, \"/Users/jhon/pmy/web-word\"); import src.mysql_db, src.database" 2>&1',
      description: '检查模块导入'
    })

    return {
      syntaxErrors: pyflakes.stdout,
      imports: importCheck.stdout
    }
  },
  async () => {
    log('📝 检查代码注释和文档字符串...')
    const pyFiles = await Bash({
      command: 'find /Users/jhon/pmy/web-word/src -name "*.py" -type f',
      description: '查找所有 Python 文件'
    })

    const files = pyFiles.stdout.split('\n').filter(Boolean)
    let hasDocstring = 0
    let noDocstring = 0

    for (const file of files.slice(0, 10)) { // 只检查前10个文件
      const content = await Read({ file_path: file })
      const lines = content.content.split('\n')
      const hasModuleDoc = lines.some(line => line.trim().startsWith('"""') || line.trim().startsWith("'''"))
      const hasClassDoc = content.content.match(/class.*:\s*(?:"""|''')/g)
      const hasFunctionDoc = content.content.match(/def.*:\s*(?:"""|''')/g)

      if (hasModuleDoc || hasClassDoc?.length > 0 || hasFunctionDoc?.length > 0) {
        hasDocstring++
      } else {
        noDocstring++
      }
    }

    return {
      filesChecked: files.length,
      filesWithDocstring: hasDocstring,
      filesWithoutDocstring: noDocstring
    }
  },
  async () => {
    log('🔍 检查代码重复和复杂度...')
    const complexity = await Bash({
      command: 'find /Users/jhon/pmy/web-word/src -name "*.py" -type f -exec wc -l {} + | tail -1',
      description: '统计总代码行数'
    })

    const functionCount = await Bash({
      command: 'grep -r "^def " /Users/jhon/pmy/web-word/src --include="*.py" | wc -l',
      description: '统计函数数量'
    })

    const classCount = await Bash({
      command: 'grep -r "^class " /Users/jhon/pmy/web-word/src --include="*.py" | wc -l',
      description: '统计类数量'
    })

    return {
      totalLines: complexity.stdout,
      functions: functionCount.stdout,
      classes: classCount.stdout
    }
  }
])

log('代码质量报告:')
codeQuality.forEach((report, i) => {
  if (i === 0) log(`  - 语法错误: ${report.syntaxErrors || '✅ 无错误'}`)
  if (i === 1) log(`  - 模块导入: ${report.imports || '✅ 无错误'}`)
  if (i === 2) {
    log(`  - 总代码行数: ${report.totalLines}`)
    log(`  - 函数数量: ${report.functions}`)
    log(`  - 类数量: ${report.classes}`)
  }
})

phase('配置验证')
const configVerification = await parallel([
  async () => {
    log('📄 验证 config.yaml 配置...')
    const config = await Read({ file_path: '/Users/jhon/pmy/web-word/config/config.yaml' })
    const yamlContent = config.content

    const checks = {
      hasDatabase: yamlContent.includes('database:'),
      hasMySQL: yamlContent.includes('mysql:'),
      hasSQLite: yamlContent.includes('sqlite:'),
      hasPool: yamlContent.includes('pool:'),
      hasAppConfig: yamlContent.includes('app:'),
      hasLogging: yamlContent.includes('logging:')
    }

    log(`  - 包含 database: ${checks.hasDatabase ? '✅' : '❌'}`)
    log(`  - 包含 mysql: ${checks.hasMySQL ? '✅' : '❌'}`)
    log(`  - 包含 sqlite: ${checks.hasSQLite ? '✅' : '❌'}`)
    log(`  - 包含 pool: ${checks.hasPool ? '✅' : '❌'}`)
    log(`  - 包含 app: ${checks.hasAppConfig ? '✅' : '❌'}`)
    log(`  - 包含 logging: ${checks.hasLogging ? '✅' : '❌'}`)

    return checks
  },
  async () => {
    log('🔍 验证依赖项完整性...')
    const installed = await Bash({
      command: 'pip list --format=freeze | grep -E "(pymysql|pyyaml|streamlit|pandas)"',
      description: '检查已安装的关键依赖'
    })

    const missing = await Bash({
      command: 'pip list --format=freeze 2>/dev/null | grep -v -E "(pymysql|pyyaml|streamlit|pandas)" || echo "所有依赖已安装"',
      description: '检查可能缺少的依赖'
    })

    return {
      installed: installed.stdout,
      missing: missing.stdout
    }
  },
  async () => {
    log('📝 检查环境变量配置...')
    const envVars = await Bash({
      command: 'env | grep -E "(MYSQL|ZHIPU|OPENAI|DEEPSEEK)" | sort',
      description: '检查环境变量'
    })

    return {
      envVars: envVars.stdout
    }
  }
])

log('配置验证结果:')
configVerification.forEach(report => {
  if (report.hasDatabase !== undefined) {
    const allValid = Object.values(report).filter(v => typeof v === 'boolean').every(v => v === true)
    log(`  - 配置完整性: ${allValid ? '✅' : '❌'}`)
  }
  if (report.installed) {
    log(`  - 依赖安装: ${report.installed || '✅'}`)
  }
  if (report.envVars) {
    log(`  - 环境变量: ${report.envVars || '⚠️ 未设置'}`)
  }
})

phase('数据库连接')
const dbCheck = await parallel([
  async () => {
    log('🗄️  检查 MySQL 服务状态...')
    const status = await Bash({
      command: 'pgrep -x mysqld && echo "MySQL 已运行" || echo "MySQL 未运行"',
      description: '检查 MySQL 进程'
    })

    const config = await Read({ file_path: '/Users/jhon/pmy/web-word/config/config.yaml' })
    const mysqlConfig = config.content.match(/password:\s*(.+)/)?.[1] || 'N/A'

    return {
      mysqlRunning: status.stdout.includes('已运行'),
      passwordConfigured: mysqlConfig.length > 5
    }
  },
  async () => {
    log('🧪 测试 Python 模块导入...')
    const testImport = await Bash({
      command: 'python -c "from src.mysql_db import get_config, get_mysql_config; print(\'✅ 配置加载正常\')" 2>&1',
      description: '测试配置加载'
    })

    return {
      importSuccess: testImport.stdout.includes('✅') || testImport.stdout.includes('正常'),
      output: testImport.stdout
    }
  }
])

log('数据库检查:')
dbCheck.forEach(check => {
  if (check.mysqlRunning !== undefined) {
    log(`  - MySQL 服务: ${check.mysqlRunning ? '✅ 运行中' : '❌ 未运行'}`)
  }
  if (check.importSuccess !== undefined) {
    log(`  - 配置加载: ${check.importSuccess ? '✅ 正常' : '❌ 失败'}`)
  }
})

phase('依赖项检查')
const dependencyCheck = await parallel([
  async () => {
    log('📦 检查 requirements.txt...')
    const reqs = await Read({ file_path: '/Users/jhon/pmy/web-word/requirements.txt' })
    const packages = reqs.content.split('\n').filter(line => line.trim() && !line.startsWith('#'))

    return {
      totalPackages: packages.length,
      packages: packages
    }
  },
  async () => {
    log('🔍 检查已安装包版本...')
    const versions = await Bash({
      command: 'pip show streamlit pymysql pyyaml pandas | grep -E "^Name:|^Version:" | paste - - | sort',
      description: '检查关键包版本'
    })

    return {
      versions: versions.stdout || '未找到'
    }
  },
  async () => {
    log('💡 检查潜在的依赖问题...')
    const issues = []

    const streamlitInstalled = await Bash({
      command: 'pip show streamlit > /dev/null 2>&1 && echo "installed" || echo "not_installed"',
      description: '检查 Streamlit'
    })

    const pymysqlInstalled = await Bash({
      command: 'pip show pymysql > /dev/null 2>&1 && echo "installed" || echo "not_installed"',
      description: '检查 PyMySQL'
    })

    const pyyamlInstalled = await Bash({
      command: 'pip show pyyaml > /dev/null 2>&1 && echo "installed" || echo "not_installed"',
      description: '检查 PyYAML'
    })

    if (streamlitInstalled.stdout !== 'installed') issues.push('Streamlit 未安装')
    if (pymysqlInstalled.stdout !== 'installed') issues.push('PyMySQL 未安装')
    if (pyyamlInstalled.stdout !== 'installed') issues.push('PyYAML 未安装')

    return {
      issues: issues
    }
  }
])

log('依赖项检查:')
dependencyCheck.forEach(check => {
  if (check.totalPackages !== undefined) {
    log(`  - requirements.txt 包数: ${check.totalPackages}`)
  }
  if (check.versions !== undefined) {
    log(`  - 已安装包版本: ${check.versions}`)
  }
  if (check.issues !== undefined) {
    if (check.issues.length === 0) {
      log(`  - 依赖完整性: ✅ 完整`)
    } else {
      log(`  - 潜在问题: ${check.issues.join(', ')}`)
    }
  }
})

phase('文档完整性')
const docCheck = await parallel([
  async () => {
    log('📄 检查文档文件...')
    const docs = await Bash({
      command: 'find /Users/jhon/pmy/web-word -maxdepth 1 -name "*.md" -type f | sort',
      description: '查找所有 Markdown 文档'
    })

    const docFiles = docs.stdout.split('\n').filter(Boolean)

    const docStats = await Promise.all(
      docFiles.slice(0, 5).map(async (doc) => {
        const content = await Read({ file_path: doc })
        return {
          file: doc.split('/').pop(),
          lines: content.content.split('\n').length,
          size: content.content.length
        }
      })
    )

    return {
      totalDocs: docFiles.length,
      docs: docStats
    }
  },
  async () => {
    log('🔍 检查代码示例和注释...')
    const hasExamples = await Bash({
      command: 'grep -r "example" /Users/jhon/pmy/web-word/src --include="*.py" -i | head -5 || echo "无示例代码"',
      description: '搜索代码示例'
    })

    const hasInlineComments = await Bash({
      command: 'grep -r "# " /Users/jhon/pmy/web-word/src --include="*.py" | wc -l',
      description: '统计行内注释'
    })

    return {
      examples: hasExamples.stdout,
      inlineComments: hasInlineComments.stdout
    }
  },
  async () => {
    log('📖 检查文档交叉引用...')
    const docs = await Bash({
      command: 'find /Users/jhon/pmy/web-word -name "*.md" -type f | head -10',
      description: '查找文档文件'
    })

    const referencedDocs = await Bash({
      command: 'grep -r "\[.*\](.*\.md)" /Users/jhon/pmy/web-word/docs /Users/jhon/pmy/web-word/*.md 2>/dev/null | grep -oE "\[.*\]\([^)]+\)" | wc -l',
      description: '统计文档链接'
    })

    return {
      referencedDocs: referencedDocs.stdout
    }
  }
])

log('文档完整性:')
docCheck.forEach(check => {
  if (check.totalDocs !== undefined) {
    log(`  - 文档文件: ${check.totalDocs}`)
  }
  if (check.docs) {
    check.docs.forEach(doc => {
      log(`    - ${doc.file}: ${doc.lines} 行, ${doc.size} 字符`)
    })
  }
  if (check.examples !== undefined) {
    log(`  - 代码示例: ${check.examples || '无'}`)
  }
  if (check.inlineComments !== undefined) {
    log(`  - 行内注释: ${check.inlineComments} 处`)
  }
})

log('✅ 研究完成！')

return {
  success: true,
  structure: structureInfo[0],
  codeQuality: codeQuality,
  config: configVerification[0],
  database: dbCheck,
  dependencies: dependencyCheck,
  documentation: docCheck
}
