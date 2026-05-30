"""
简单截图脚本 - 用于捕获 Streamlit 应用
"""

import time
import subprocess
import os

# 启动 Streamlit
print("🚀 启动 Streamlit 应用...")

proc = subprocess.Popen(
    ['streamlit', 'run', 'src/app.py', '--server.port=8501', '--server.headless=true', '--server.address=0.0.0.0'],
    stdout=open('/tmp/streamlit.log', 'w'),
    stderr=subprocess.PIPE
)

print(f"进程 PID: {proc.pid}")

# 等待应用启动
time.sleep(8)

print("✅ 应用已启动，访问: http://localhost:8501")
print("📊 正在尝试截图...")

# 等待页面加载
time.sleep(3)

print("💡 提示: 请在浏览器中访问 http://localhost:8501 查看应用")
print(f"   或使用 Playboard 打开: {os.path.expanduser('~/Library/Containers/com.microsoft.vscode-sessions/Data/SessionData')}")

# 检查进程状态
if proc.poll() is None:
    print(f"🔄 应用正在运行 (PID: {proc.pid})")
    print("   按 Ctrl+C 停止应用")
else:
    print("❌ 应用已退出")

# 保持运行
try:
    proc.wait()
except KeyboardInterrupt:
    print("\n🛑 停止应用...")
    proc.terminate()
    proc.wait(timeout=5)
    print("✅ 应用已停止")
