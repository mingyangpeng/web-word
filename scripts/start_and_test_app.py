#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
Streamlit 应用启动和测试脚本
"""

import sys
import os
import subprocess
import time
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
import socket
import json

print("=" * 60)
print("🚀 启动 Streamlit 应用测试")
print("=" * 60)

# 获取项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
print(f"项目根目录: {project_root}")

app_file = os.path.join(project_root, 'app.py')

# 检查应用文件是否存在
if not os.path.exists(app_file):
    print(f"❌ 应用文件不存在: {app_file}")
    sys.exit(1)
print(f"✅ 应用文件存在: {app_file}")

# 读取应用内容，检查关键配置
with open(app_file, 'r', encoding='utf-8') as f:
    app_content = f.read()

checks = {
    'set_page_config': 'st.set_page_config' in app_content,
    'sidebar_navigation': 'st.sidebar.radio' in app_content,
    'pages_import': any('import pages' in line or 'from pages import' in line for line in app_content.split('\n')),
    'db_manager': 'DatabaseManager' in app_content,
    'llm_service': 'LLMService' in app_content
}

print("\n应用配置检查:")
for check_name, result in checks.items():
    status = "✅" if result else "❌"
    print(f"  {status} {check_name}")

if not all(checks.values()):
    print("⚠️  部分配置缺失，可能影响功能")
else:
    print("✅ 应用配置完整")

# 启动 Streamlit 应用
print("\n正在启动 Streamlit 应用...")
print(f"工作目录: {project_root}")
print(f"应用文件: {app_file}")

# 使用 nohup 启动，并保存 PID
print("\n启动应用（后台运行）...")
process = subprocess.Popen(
    ['streamlit', 'run', app_file, '--server.port=8501', '--server.headless=true'],
    cwd=project_root,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

pid = process.pid
print(f"应用进程 PID: {pid}")

# 等待应用启动
print("\n等待应用启动...")
time.sleep(5)

# 检查进程是否还在运行
if process.poll() is not None:
    stdout, stderr = process.communicate()
    print(f"❌ 应用启动失败!")
    print(f"STDOUT: {stdout}")
    print(f"STDERR: {stderr}")
    sys.exit(1)

print("✅ 应用进程运行中")

# 检查端口是否监听
def is_port_open(port, host='localhost', timeout=5):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            result = s.connect_ex((host, port))
            return result == 0
    except:
        return False

if is_port_open(8501):
    print("✅ 端口 8501 已监听")

    # 尝试访问页面
    print("\n尝试访问应用页面...")
    try:
        response = requests.get('http://localhost:8501/', timeout=5)
        print(f"✅ HTTP 200 响应 (状态码: {response.status_code})")

        # 检查页面内容
        if response.status_code == 200:
            content = response.text
            if 'Streamlit' in content or '单词知识图谱' in content:
                print("✅ 页面内容正确")
            else:
                print("⚠️  页面内容可能不正确")

    except requests.exceptions.RequestException as e:
        print(f"❌ 访问失败: {e}")
else:
    print("❌ 端口 8501 未监听")

# 显示进程信息
print("\n进程信息:")
print(f"  PID: {pid}")
print(f"  工作目录: {project_root}")
print(f"  命令: streamlit run app.py")

# 保持运行
print("\n" + "=" * 60)
print("应用已启动，可以访问: http://localhost:8501")
print("按 Ctrl+C 停止应用")
print("=" * 60)

try:
    # 持续监控
    while True:
        time.sleep(2)
        if process.poll() is not None:
            print("\n⚠️  应用进程已退出")
            stdout, stderr = process.communicate()
            if stdout:
                print(f"STDOUT: {stdout}")
            if stderr:
                print(f"STDERR: {stderr}")
            break

except KeyboardInterrupt:
    print("\n\n正在停止应用...")
    process.send_signal(signal.SIGINT)
    process.wait(timeout=5)
    print("✅ 应用已停止")
