# Cloudflare Tunnel 部署指南

## 📖 概述

使用 Cloudflare Zero Trust Tunnel 将本地 Streamlit 应用暴露到公网，无需公网 IP 和端口映射。

**优势**：
- ✅ 完全免费
- ✅ 自动 HTTPS 证书
- ✅ 全球 CDN 加速
- ✅ 安全加密传输
- ✅ 无需修改路由器端口映射

---

## 🚀 快速开始

### 第一步：安装 cloudflared

```bash
# 下载并安装 cloudflared (Ubuntu/Debian)
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb

# 或使用 curl (需要 sudo)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
sudo chmod +x /usr/local/bin/cloudflared

# 验证安装
cloudflared version
```

### 第二步：登录 Cloudflare

```bash
# 运行登录命令
cloudflared tunnel login
```

该命令会：
1. 打开浏览器，要求你选择一个域名
2. 下载验证文件
3. 验证成功后，证书保存在 `~/.cloudflared/cert.pem`

### 第三步：创建隧道

```bash
# 创建隧道
cloudflared tunnel create streamlit-word-graph

# 或直接使用部署脚本
./scripts/deploy_tunnel.sh
```

### 第四步：启动应用

#### 方式1：使用部署脚本（推荐）

```bash
./scripts/deploy_tunnel.sh
```

该脚本会自动：
1. 检查 cloudflared 安装
2. 登录 Cloudflare
3. 创建隧道
4. 启动 Streamlit 应用

#### 方式2：手动启动

```bash
# 终端1：启动 Streamlit
/home/pmy/dev/miniconda3/envs/p312/bin/streamlit run app.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true

# 终端2：启动隧道
cloudflared tunnel --config ~/.cloudflared/streamlit-word-graph-config.yml run
```

---

## 🔧 配置说明

### 隧道配置文件

位置：`~/.cloudflared/streamlit-word-graph-config.yml`

```yaml
tunnel: <隧道ID>
credentials-file: ~/.cloudflared/<隧道ID>.json

ingress:
  - hostname: word-graph.local
    service: http://localhost:8501
  - service: http_status:404  # 所有未匹配的请求返回 404
```

### 修改域名

编辑配置文件中的 `hostname`：

```yaml
ingress:
  - hostname: your-domain.com
    service: http://localhost:8501
  - service: http_status:404
```

### 自定义域名

#### 拥有自定义域名（如 example.com）

```bash
# 1. 添加 DNS 记录
cloudflared tunnel route dns streamlit-word-graph word-graph.example.com

# 2. 更新配置文件
ingress:
  - hostname: word-graph.example.com
    service: http://localhost:8501
  - service: http_status:404
```

#### 使用 Cloudflare 域名

```bash
# 1. 添加 DNS 记录
cloudflared tunnel route dns streamlit-word-graph streamlit-word-graph.yourdomain.com

# 2. 更新配置文件
ingress:
  - hostname: streamlit-word-graph.yourdomain.com
    service: http://localhost:8501
  - service: http_status:404
```

---

## 🌐 访问应用

部署成功后，通过以下方式访问：

### 本地测试

```bash
# 在同一台机器上
curl http://localhost:8501
```

### 远程访问

```bash
# 使用隧道域名
curl https://word-graph.local

# 使用自定义域名
curl https://your-domain.com
```

---

## 📊 管理命令

### 查看隧道列表

```bash
cloudflared tunnel list
```

### 查看隧道详情

```bash
cloudflared tunnel info streamlit-word-graph
```

### 列出所有路由

```bash
cloudflared tunnel route dns list streamlit-word-graph
```

### 停止隧道

```bash
# 找到 cloudflared 进程 PID
ps aux | grep cloudflared

# 停止进程
kill <PID>
```

---

## 🔒 安全配置

### 1. 限制访问（可选）

使用 Cloudflare Access 控制访问权限：

```bash
# 安装 cloudflared access
cloudflared access login

# 创建访问策略
cloudflared access requests create --domain word-graph.local
```

### 2. 配置速率限制

在 Cloudflare 控制面板中：
- 进入 `Security` → `WAF`
- 添加速率限制规则
- 限制每个 IP 每分钟请求数

### 3. 启用 HTTPS

Cloudflare 自动提供 HTTPS，证书由 Cloudflare 管理。

---

## 🛠️ 故障排查

### 问题1：无法登录 Cloudflare

**错误**: `Error: Account ID not found`

**解决**:
```bash
# 检查登录状态
cloudflared tunnel list

# 重新登录
cloudflared tunnel login
```

### 问题2：隧道无法连接

**检查步骤**:
```bash
# 1. 检查 cloudflared 版本
cloudflared version

# 2. 检查配置文件
cat ~/.cloudflared/*.yml

# 3. 检查 Streamlit 是否运行
curl http://localhost:8501

# 4. 检查隧道日志
cloudflared tunnel --config ~/.cloudflared/*.yml run --loglevel debug
```

### 问题3：无法通过域名访问

**检查步骤**:
```bash
# 1. 确认 DNS 记录正确
cloudflared tunnel route dns list streamlit-word-graph

# 2. 检查 DNS 是否生效
nslookup word-graph.local

# 3. 检查隧道状态
cloudflared tunnel info streamlit-word-graph
```

---

## 📝 与 nginx 代理对比

| 特性 | Cloudflare Tunnel | nginx |
|------|-------------------|-------|
| 部署难度 | ⭐ 简单 | ⭐⭐⭐ 复杂 |
| 公网 IP | ❌ 无需 | ❌ 需要 |
| HTTPS | ✅ 自动 | ⚠️ 需配置 |
| CDN 加速 | ✅ 全球节点 | ❌ 需第三方 |
| 费用 | ✅ 免费 | ⚠️ 服务器成本 |
| 配置 | ✅ 简单配置文件 | ⚠️ 需编辑配置 |

**推荐**: 对个人项目或小型应用，Cloudflare Tunnel 更简单且免费。

---

## 🔄 自动启动（可选）

### 使用 systemd（Linux）

创建服务文件 `/etc/systemd/system/streamlit-tunnel.service`:

```ini
[Unit]
Description=Streamlit Word Graph with Cloudflare Tunnel
After=network.target

[Service]
Type=simple
User=pmy
WorkingDirectory=/home/pmy/megatron_2025/pmy/web-word
ExecStart=/home/pmy/dev/miniconda3/envs/p312/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable streamlit-tunnel
sudo systemctl start streamlit-tunnel
```

### 使用 screen/tmux

```bash
# 创建新会话
screen -S streamlit

# 在会话中运行
./scripts/deploy_tunnel.sh

# 分离会话 (Ctrl+A, D)
# 重新连接
screen -r streamlit
```

---

## 📞 技术支持

- [Cloudflare Tunnel 官方文档](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)
- [cloudflared GitHub](https://github.com/cloudflare/cloudflared)
- [项目文档](./CLAUDE.md)

---

**最后更新**: 2026-06-03
