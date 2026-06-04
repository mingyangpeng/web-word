#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
后端功能完整测试总结报告
"""

import sys
import os
import subprocess

print("=" * 80)
print(" " * 20 + "后端功能测试总结报告")
print("=" * 80)

results = {}

# 运行数据库测试
print("\n【模块1】数据库功能测试")
print("-" * 40)
result = subprocess.run(
    ["/home/pmy/dev/miniconda3/envs/p312/bin/python", "scripts/test_database.py"],
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    capture_output=True,
    text=True,
    timeout=30000
)
results['database'] = result.returncode == 0
print(result.stdout)

# 运行 LLM 服务测试
print("\n【模块2】LLM 服务测试")
print("-" * 40)
result = subprocess.run(
    ["/home/pmy/dev/miniconda3/envs/p312/bin/python", "scripts/test_llm_service.py"],
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    capture_output=True,
    text=True,
    timeout=120000
)
results['llm_service'] = result.returncode == 0
print(result.stdout)

# 总结
print("\n" + "=" * 80)
print(" " * 25 + "测试结果汇总")
print("=" * 80)

for module, passed in results.items():
    status = "✅ 通过" if passed else "❌ 失败"
    print(f"{module:15} {status}")

all_passed = all(results.values())

print("\n" + "=" * 80)
if all_passed:
    print(" " * 28 + "🎉 所有测试通过！")
    print("")
    print("后端功能正常运行，可以启动应用:")
    print("  streamlit run app.py")
    print("  然后访问: http://localhost:8501")
else:
    print(" " * 30 + "⚠️  部分测试失败")
    print("")
    print("请检查失败模块的输出详情")
print("=" * 80)
