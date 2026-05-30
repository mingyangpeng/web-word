# 测试指南

## 安装依赖

```bash
pip install pytest pytest-cov zhipuai
```

## 运行测试

```bash
# 运行所有测试
pytest

# 运行测试并生成覆盖率报告
pytest --cov=src --cov-report=html

# 运行特定测试文件
pytest tests/test_api.py

# 详细输出
pytest -v
```

## 覆盖率报告

打开 htmlcov/index.html 查看覆盖率报告
