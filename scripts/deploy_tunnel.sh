#!/bin/bash
# Cloudflare Tunnel 部署脚本
# 用于将本地 Streamlit 应用暴露到公网

set -e

PROJECT_DIR="/home/pmy/megatron_2025/pmy/web-word"
APP_PORT="8501"
TUNNEL_NAME="streamlit-word-graph"
DOMAIN="word-graph.local"  # 部署后会替换为实际域名

echo "================================"
echo "Cloudflare Tunnel 部署工具"
echo "================================"
echo ""
echo "项目目录: $PROJECT_DIR"
echo "应用端口: $APP_PORT"
echo "隧道名称: $TUNNEL_NAME"
echo ""

# 检查 cloudflared 是否安装
if ! command -v cloudflared &> /dev/null; then
    echo "❌ cloudflared 未安装"
    echo ""
    echo "请先安装 cloudflared:"
    echo ""
    echo "Ubuntu/Debian:"
    echo "  wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb"
    echo "  sudo dpkg -i cloudflared-linux-amd64.deb"
    echo ""
    echo "或使用 curl (需要 sudo):"
    echo "  curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared"
    echo "  sudo chmod +x /usr/local/bin/cloudflared"
    echo ""
    exit 1
fi

echo "✅ cloudflared 已安装: $(cloudflared version)"

# 检查是否已登录
echo ""
echo "检查 Cloudflare 登录状态..."
if ! cloudflared tunnel info $TUNNEL_NAME &> /dev/null 2>&1; then
    echo "❌ 未登录或隧道不存在"
    echo ""
    echo "=== 第一步：登录 Cloudflare ==="
    echo "运行以下命令登录:"
    echo "  cloudflared tunnel login"
    echo ""
    echo "该命令会打开浏览器，选择你的域名后，会在本地生成一个证书文件"
    echo "证书位置: ~/.cloudflared/cert.pem"
    echo ""
    read -p "登录完成后按 Enter 继续..."
fi

# 检查/创建隧道
echo ""
echo "检查/创建隧道..."
if cloudflared tunnel info $TUNNEL_NAME &> /dev/null 2>&1; then
    echo "✅ 隧道 '$TUNNEL_NAME' 已存在"
else
    echo "创建新隧道 '$TUNNEL_NAME'..."
    cloudflared tunnel create $TUNNEL_NAME
    echo "✅ 隧道创建成功"
fi

# 获取隧道 ID
TUNNEL_ID=$(cloudflared tunnel info $TUNNEL_NAME | grep "ID" | awk '{print $2}')
echo "隧道 ID: $TUNNEL_ID"

# 创建配置文件目录
mkdir -p ~/.cloudflared

# 创建配置文件
echo ""
echo "创建隧道配置文件..."
cat > ~/.cloudflared/$TUNNEL_NAME-config.yml <<EOF
tunnel: $TUNNEL_ID
credentials-file: ~/.cloudflared/$TUNNEL_ID.json

ingress:
  - hostname: word-graph.local
    service: http://localhost:$APP_PORT
  - service: http_status:404
EOF

echo "配置文件已创建: ~/.cloudflared/$TUNNEL_NAME-config.yml"

# 运行隧道服务
echo ""
echo "================================"
echo "=== 启动 Streamlit 应用 ==="
echo "================================"
echo ""
echo "Streamlit 将在端口 $APP_PORT 上运行"
echo "请保持此终端窗口打开，隧道将持续运行"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

cd $PROJECT_DIR

# 启动 Streamlit
/home/pmy/dev/miniconda3/envs/p312/bin/streamlit run app.py \
    --server.port=$APP_PORT \
    --server.address=0.0.0.0 \
    --server.headless=true
