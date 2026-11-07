# 测试指南

## 安装依赖

测试依赖已包含在 `requirements.txt` 中，直接装全量即可：

```bash
pip install -r requirements.txt
```

只装测试所需的最小集合：

```bash
pip install pytest pytest-cov zhipuai pymysql pyyaml pandas streamlit
```

> `streamlit` 是必需的：界面测试用 `streamlit.testing.v1.AppTest` 渲染真实应用。

## 运行测试

`pytest.ini` 已配置 `testpaths = tests`，并且默认带上覆盖率参数
（`--cov=src --cov-report=html --cov-report=term`），所以直接跑 `pytest` 即可。

```bash
# 全部测试（默认含覆盖率）
pytest

# 详细输出
pytest -v

# 跳过覆盖率，跑得更快（推荐日常迭代用）
python -m pytest -q -p no:cacheprovider --no-cov

# 只跑某个文件 / 某个用例
pytest tests/test_security.py
pytest tests/test_phase5.py -k degradation
```

## 覆盖率报告

`pytest` 结束后会在终端打印覆盖率摘要，同时生成 HTML 报告：打开 `htmlcov/index.html`
即可查看逐行覆盖情况。

## 测试隔离约定

测试**不得**真实访问智谱 API 或 MySQL。`tests/test_phase5.py` 用 autouse fixture 把所有外部
依赖默认替换为「不可达」，任何漏掉的 patch 都会立刻显式失败，而不是静默触网或连库。
新增涉及外部调用的用例请沿用这一约定。

## 测试文件一览

| 文件 | 覆盖内容 |
|------|----------|
| `tests/test_phase5.py` | 释义分级策略（DB → 实时 LLM → MOCK → 兜底）、LLM 结果持久化契约、缺少 API key / 调用异常时不崩溃 |
| `tests/test_phase4.py` | Phase 4 界面打磨：侧边栏折叠、统计区、热门动词前端筛选（AppTest） |
| `tests/test_pages.py` | 六页路由冒烟（search/graph/corpus/domain/annotate/category，AppTest） |
| `tests/test_search_bar.py` | 固定置顶搜索栏回归测试 |
| `tests/test_security.py` | 输入校验（SQL 注入 / XSS）、密钥掩码 |
| `tests/test_schema.py` | 建表 SQL 结构、迁移幂等、簇完全图、词间关系约束（假游标单元测试） |
| `tests/test_migration_integration.py` | 真实 MySQL 上的 v1→当前迁移：业务数据不丢、旧表清理、幂等（无 DB 则 skip） |
| `tests/test_word_source.py` | 词表数据源：Levin 筛选表解析、释义优先级链 |
| `tests/test_category_study.py` | 范畴深挖：d1 xlsx 解析锚点、8 表灌入/查询/幂等、图式推导与对齐分布（无 DB 则数据层 skip） |
| `tests/test_zh_dict.py` | 《现汉7》词典：mdx 解析锚点（跑6义项/同形词/裸义项号）、拼音声调与 CJK 扩展区唯一键、例句回挂（业务数据备份/恢复隔离） |

> 2026-09 清理：`tests/test_api.py`（测试旧版 `src/api.py`，该模块已删除）与
> `tests/conftest.py`（`test_db` fixture 是无人使用的空实现）已一并移除，
> 测试总数从 41 降至 34，剩余用例全部为当前主流程的真实覆盖。

## 静态检查

```bash
flake8 src/     # 配置见 .flake8（max-line-length = 100）
mypy src/       # 配置见 mypy.ini
black src/      # 格式化
```

CI（`.github/workflows/ci-cd.yml`）在 push 与 PR 时运行 `pytest -v`、`flake8 src/`、
`mypy src/`；其中的 Hugging Face 部署任务当前已注释禁用（原因见该文件内的 TODO）。
