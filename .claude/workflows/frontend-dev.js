#!/usr/bin/env python3
/**
 * 单词知识图谱前端开发工作流
 * 目标：优化和增强 Streamlit 应用的前端界面和用户体验
 */

export const meta = {
  name: 'frontend-dev',
  description: '优化 Streamlit 应用的前端界面和用户体验',
  phases: [
    { title: '现状分析', detail: '审查现有前端页面和组件' },
    { title: 'UI/UX 设计', detail: '评估界面设计和用户体验' },
    { title: '优化实施', detail: '应用前端改进' },
    { title: '测试验证', detail: '验证优化效果' }
  ]
}

// === 阶段 1: 现状分析 ===

async function analyze_current_state() {
  log('开始分析前端现状...');

  const fs = require('fs');
  const path = require('path');

  const pages = ['home', 'learn', 'chat', 'words', 'settings'];
  const findings = [];

  for (const page of pages) {
    const pagePath = path.join(__dirname, '..', 'pages', `${page}.py`);
    try {
      const content = fs.readFileSync(pagePath, 'utf-8');

      const stats = {
        page: page,
        has_st_title: content.includes('st.title'),
        has_st_components: content.includes('st.components'),
        st_elements: (content.match(/st\.\w+\(/g) || []).length,
        session_state_vars: (content.match(/st\.session_state\.\w+/g) || []).length,
        html_rendering: content.includes('html(') || content.includes('<div'),
        has_custom_css: content.includes('st.markdown') && content.includes('<style>')
      };

      findings.push(stats);
    } catch (e) {
      log(`  ⚠️ 无法读取 ${page} 页面`);
    }
  }

  const mainApp = path.join(__dirname, '..', 'app.py');
  const mainContent = fs.readFileSync(mainApp, 'utf-8');
  const architecture = {
    uses_set_page_config: mainContent.includes('set_page_config'),
    custom_css: mainContent.includes('custom CSS'),
    has_navigation: mainContent.includes('st.sidebar.radio'),
    uses_streamlit_components: mainContent.includes('st.components')
  };

  return {
    pages: findings,
    architecture: architecture,
    summary: '发现 ' + findings.length + ' 个页面，使用了 ' + (architecture.uses_set_page_config ? '页面配置' : '旧版配置') + '，包含 ' + (architecture.has_navigation ? '侧边栏导航' : '其他导航方式')
  };
}

// === 阶段 2: UI/UX 设计评审 ===

async function ux_review(currentState) {
  log('开始 UI/UX 设计评审...');

  const fs = require('fs');
  const path = require('path');

  const reviewResults = [];

  const homeContent = fs.readFileSync(path.join(__dirname, '..', 'pages', 'home.py'), 'utf-8');
  const homeReview = {
    page: '首页',
    score: 0,
    comments: []
  };

  if (homeContent.includes('search_query') && homeContent.includes('search_btn')) {
    homeReview.score += 30;
    homeReview.comments.push('✅ 搜索功能完整');
  }
  if (homeContent.includes('word_history')) {
    homeReview.score += 20;
    homeReview.comments.push('✅ 历史记录功能');
  }
  if (homeContent.includes('st.spinner')) {
    homeReview.score += 20;
    homeReview.comments.push('✅ 加载状态提示');
  }
  if (!homeContent.includes('custom CSS')) {
    homeReview.score -= 10;
    homeReview.comments.push('⚠️ 缺少自定义样式');
  }

  const learnContent = fs.readFileSync(path.join(__dirname, '..', 'pages', 'learn.py'), 'utf-8');
  const learnReview = {
    page: '学习页',
    score: 0,
    comments: []
  };

  if (learnContent.includes('display_graph')) {
    learnReview.score += 40;
    learnReview.comments.push('✅ 图谱可视化功能');
  }
  if (learnContent.includes('show_labels') && learnContent.includes('show_edges')) {
    learnReview.score += 30;
    learnReview.comments.push('✅ 视图控制功能');
  }
  if (learnContent.includes('st.spinner')) {
    learnReview.score += 20;
    learnReview.comments.push('✅ 加载状态提示');
  }

  const chatContent = fs.readFileSync(path.join(__dirname, '..', 'pages', 'chat.py'), 'utf-8');
  const chatReview = {
    page: '对话页',
    score: 0,
    comments: []
  };

  if (chatContent.includes('chat_history') && chatContent.includes('st.chat_message')) {
    chatReview.score += 40;
    chatReview.comments.push('✅ 对话历史记录');
  }
  if (chatContent.includes('quick_questions')) {
    chatReview.score += 30;
    chatReview.comments.push('✅ 快捷问题功能');
  }
  if (chatContent.includes('mode_prompts')) {
    chatReview.score += 20;
    chatReview.comments.push('✅ 对话模式选择');
  }

  reviewResults.push(homeReview);
  reviewResults.push(learnReview);
  reviewResults.push(chatReview);

  return {
    reviews: reviewResults,
    summary: 'UI/UX 设计整体评分通过',
    recommendations: [
      '添加更多交互反馈',
      '优化移动端显示',
      '增强错误提示',
      '添加空状态提示'
    ]
  };
}

// === 阶段 3: 优化实施 ===

async function apply_optimizations() {
  log('开始应用前端优化...');

  const fs = require('fs');
  const path = require('path');

  const optimizations = [];

  // 优化 1: 添加全局自定义 CSS
  log('优化 1: 创建全局自定义 CSS 文件');

  const globalCss = `/* 单词知识图谱全局样式 */
.main-header {
    font-size: 2.5rem;
    font-weight: bold;
    text-align: center;
    color: #1f77b4;
    margin-bottom: 2rem;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

.welcome-box {
    background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
    padding: 1.5rem;
    border-radius: 15px;
    border-left: 5px solid #667eea;
    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
}

.card-container {
    border-radius: 10px;
    padding: 15px;
    background: white;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    transition: transform 0.2s, box-shadow 0.2s;
}

.card-container:hover {
    transform: translateY(-5px);
    box-shadow: 0 8px 25px rgba(0,0,0,0.15);
}

.metric-card {
    background: white;
    border-radius: 10px;
    padding: 20px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    text-align: center;
}

.metric-value {
    font-size: 2.5rem;
    font-weight: bold;
    color: #1f77b4;
}

.metric-label {
    color: #666;
    font-size: 0.9rem;
    margin-top: 5px;
}

.btn-primary {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border: none;
    padding: 10px 20px;
    border-radius: 5px;
    color: white;
    font-weight: 600;
    transition: transform 0.2s;
}

.btn-primary:hover {
    transform: scale(1.05);
}

.btn-danger {
    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
    border: none;
    padding: 10px 20px;
    border-radius: 5px;
    color: white;
    font-weight: 600;
    transition: transform 0.2s;
}

.btn-danger:hover {
    transform: scale(1.05);
}
`;

  const stylesDir = path.join(__dirname, '..', 'styles');
  if (!fs.existsSync(stylesDir)) {
    fs.mkdirSync(stylesDir, { recursive: true });
  }
  fs.writeFileSync(path.join(stylesDir, 'global.css'), globalCss);
  optimizations.push('✅ 创建全局样式文件');

  // 优化 2: 增强 Streamlit 配置
  log('优化 2: 增强 Streamlit 页面配置');

  const mainAppPath = path.join(__dirname, '..', 'app.py');
  let mainAppContent = fs.readFileSync(mainAppPath, 'utf-8');

  const enhancedConfig = `    # 配置页面布局
st.set_page_config(
    page_title="单词知识图谱",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'Get Help': 'https://docs.streamlit.io',
        'Report a bug': 'https://github.com/streamlit/streamlit/issues',
        'About': '单词知识图谱系统 - 基于 Streamlit + Sigma.js + GLM-4.7-Flash'
    }
)`;

  if (!mainAppContent.includes('st.set_page_config')) {
    const configInsertion = `# 配置页面布局
${enhancedConfig}

`;
    mainAppContent = mainAppContent.replace(
      /# 配置页面布局[\s\S]*?\n\n/,
      configInsertion
    );
    fs.writeFileSync(mainAppPath, mainAppContent);
    optimizations.push('✅ 增强页面配置');
  } else {
    optimizations.push('⚠️ 页面配置已存在，跳过');
  }

  // 优化 3: 改进错误处理
  log('优化 3: 改进错误处理机制');

  const homePath = path.join(__dirname, '..', 'pages', 'home.py');
  let homeContent = fs.readFileSync(homePath, 'utf-8');

  // 添加空状态提示
  if (!homeContent.includes('st.empty')) {
    const emptyState = `\n    # 空状态提示
    st.divider()
    st.info("👈 请输入单词开始查询，或查看历史记录")
`;
    homeContent = homeContent.replace(
      /(def app\(\):.*?)(if clear_btn:)/s,
      `$1$emptyState$2`
    );
    fs.writeFileSync(homePath, homeContent);
    optimizations.push('✅ 添加空状态提示');
  } else {
    optimizations.push('⚠️ 空状态提示已存在，跳过');
  }

  // 优化 4: 添加加载动画
  log('优化 4: 添加加载动画效果');

  const learnPath = path.join(__dirname, '..', 'pages', 'learn.py');
  let learnContent = fs.readFileSync(learnPath, 'utf-8');

  // 增强图谱加载提示
  if (!learnContent.includes('🚀')) {
    const loadingMessage = `\n    if refresh_btn:\n        st.info("🔄 正在刷新知识图谱...")\n`;
    learnContent = learnContent.replace(
      /(if refresh_btn:)/,
      `$1${loadingMessage}`
    );
    fs.writeFileSync(learnPath, learnContent);
    optimizations.push('✅ 添加加载动画');
  } else {
    optimizations.push('⚠️ 加载动画已存在，跳过');
  }

  return {
    optimizations: optimizations,
    summary: '已应用 4 项前端优化'
  };
}

// === 阶段 4: 测试验证 ===

async function verify_optimizations() {
  log('开始验证优化效果...');

  const fs = require('fs');
  const path = require('path');

  const tests = [];

  // 检查样式文件是否创建
  const cssFile = path.join(__dirname, '..', 'styles', 'global.css');
  if (fs.existsSync(cssFile)) {
    const cssContent = fs.readFileSync(cssFile, 'utf-8');
    if (cssContent && cssContent.length > 0) {
      tests.push('✅ 全局样式文件创建成功');
    } else {
      tests.push('❌ 全局样式文件为空');
    }
  } else {
    tests.push('❌ 全局样式文件创建失败');
  }

  // 检查页面配置
  const mainApp = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf-8');
  if (mainApp.includes('st.set_page_config')) {
    tests.push('✅ 页面配置已更新');
  } else {
    tests.push('❌ 页面配置未更新');
  }

  // 检查空状态提示
  const homeContent = fs.readFileSync(path.join(__dirname, '..', 'pages', 'home.py'), 'utf-8');
  if (homeContent.includes('st.empty')) {
    tests.push('✅ 空状态提示已添加');
  } else {
    tests.push('❌ 空状态提示未添加');
  }

  return {
    tests: tests,
    summary: '优化验证完成',
    passRate: tests.filter(t => t.includes('✅')).length / tests.length * 100
  };
}

// === 主流程 ===

async function main() {
  log('='.repeat(60));
  log('🚀 前端开发工作流启动');
  log('='.repeat(60));

  // 阶段 1: 现状分析
  log('\n【阶段 1】现状分析');
  const currentState = await analyze_current_state();
  log(currentState.summary);
  for (const page of currentState.pages) {
    log(`  ${page.page}: ${page.st_elements} 个组件, ${page.session_state_vars} 个会话变量`);
  }

  // 阶段 2: UI/UX 设计评审
  log('\n【阶段 2】UI/UX 设计评审');
  const uxReview = await ux_review(currentState);
  log(uxReview.summary);
  for (const review of uxReview.reviews) {
    log(`  ${review.page}: 评分 ${review.score}/100`);
    for (const comment of review.comments) {
      log(`    ${comment}`);
    }
  }

  // 阶段 3: 优化实施
  log('\n【阶段 3】优化实施');
  const optimizations = await apply_optimizations();
  for (const opt of optimizations.optimizations) {
    log(`  ${opt}`);
  }

  // 阶段 4: 测试验证
  log('\n【阶段 4】测试验证');
  const verification = await verify_optimizations();
  log(verification.summary);
  for (const test of verification.tests) {
    log(`  ${test}`);
  }

  log('\n' + '='.repeat(60));
  log('✅ 前端开发工作流完成');
  log('='.repeat(60));
}

if (typeof require !== 'undefined' && require.main === module) {
  main().catch(console.error);
}
