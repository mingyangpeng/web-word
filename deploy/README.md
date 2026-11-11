# deploy/ — 公网部署三件套（Nginx / Caddy / 自检）

> 对应 `docs/DEPLOYMENT.md` 的「六、公网部署」节。RV4-7/R4-7（`/app/static/*`
> 绕登录门）的公网处置方案在此落地为可执行清单，不再口头挂账。
> 平台形态：Streamlit 单容器（8501）＋ MySQL（仅 127.0.0.1）。

## 一、三个文件是什么

| 文件 | 用途 | 选型 |
|------|------|------|
| `nginx.conf.example` | 完整独立 nginx.conf 样例：443 TLS（证书路径占位）、`/` 反代 127.0.0.1:8501（WebSocket 升级头齐全）、`/app/static/` RV4-7 折中限速＋不索引、`/_stcore/stream` 握手 10r/m（login 口径）、安全头、gzip、`client_max_body_size 50m`（媒体上传） | 目标机已有 nginx 或偏好细粒度控制 |
| `Caddyfile.example` | 同语义 Caddy v2 样例：自动 HTTPS（免证书路径）、WebSocket 原生支持；vanilla Caddy 无内置限速，差异在文件头如实注明 | 小团队/不想手管证书 |
| `validate.sh` | 静态自检：nginx 括号配平＋必需指令存在性＋占位符提醒、Caddyfile 基本形态、bash 语法自检。**不要求目标机有 nginx 二进制** | 修改样例后先跑一遍 |

两者**二选一**，不要同时挂（都占 443）。

## 二、启用步骤

### Nginx

```bash
sudo cp deploy/nginx.conf.example /etc/nginx/nginx.conf   # 或合入 conf.d 站点文件
sudo vim /etc/nginx/nginx.conf      # 改三处占位：
#   * server_name lexischema.example.com（出现两处：80 与 443）
#   * ssl_certificate     /etc/letsencrypt/live/REPLACE-ME/fullchain.pem
#   * ssl_certificate_key /etc/letsencrypt/live/REPLACE-ME/privkey.pem
sudo nginx -t                       # 语法检查（证书文件此时应已存在）
sudo systemctl reload nginx         # 首次用 start
```

> **nginx -t 与证书占位（实测记录 2026-11-11，nginx:alpine）**：`nginx -t`
> 会实读证书文件——样例里的 `REPLACE-ME` 占位路径不存在时直接
> `emerg: cannot load certificate`，**语法再对也过不了**。两条路：
> ① 先签发真证书（certbot，命令见上）；② 语法预验时临时挂自签证书：
>
> ```bash
> openssl req -x509 -newkey rsa:2048 -keyout /tmp/privkey.pem \
>     -out /tmp/fullchain.pem -days 1 -nodes -subj "/CN=placeholder"
> docker run --rm -v $PWD/deploy:/conf:ro \
>     -v /tmp:/etc/letsencrypt/live/REPLACE-ME:ro \
>     nginx:alpine nginx -t -c /conf/nginx.conf.example
> ```
>
> 实测输出：`syntax is ok` / `test is successful`（exit 0）；仅有
> `listen ... http2 is deprecated` 告警——样例刻意用跨版本兼容写法
> （`http2 on;` 指令需要 nginx ≥1.25.1，老发行版直接 unknown directive），
> 新版仅告警不报错，见样例内注释。

证书签发（http-01 挑战，本样例已留 `/.well-known/acme-challenge/` 路径）：

```bash
sudo certbot certonly --webroot -w /var/www/html -d <实际域名>
```

### Caddy

```bash
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile
sudo vim /etc/caddy/Caddyfile       # 把 lexischema.example.com 改成实际域名
sudo systemctl reload caddy         # 证书自动申请签发，无需 certbot
```

### 修改样例后的自检（任何机器可跑，无需 nginx）

```bash
bash deploy/validate.sh
```

## 三、RV4-7/R4-7 处置权衡（`/app/static/` 直链的取舍）

**结论：反代层 `deny all` 不可行，落地为「限速＋不索引＋限文件类型」折中。**

推理链（每步都已对照源码核实，见 §四核实记录）：

1. 图谱页 `st.iframe(url)` 嵌入的 URL 是**相对路径**
   `/app/static/word_graph_<指纹>.html`（`src/graph_export.py`
   `ensure_graph_html` 返回值；词簇图 `ensure_cluster_html` 同型）。
   相对路径由**浏览器**按当前页面 origin 解析 → 浏览器会直接向
   `/app/static/` 发 GET，该请求经反代打到 `location /app/static/`。
2. 图谱 HTML 内部还引 `/app/static/vis-network.min.js`，同为浏览器侧加载。
3. 因此 `location /app/static/ { deny all; }` 会让知识图谱/词簇图
   iframe 内 403，**图谱渲染成空白**——「仅允许本机反代内部跳转」同理不可行
   （浏览器请求就是外部请求，反代无法区分）。
4. 落地折中（两个样例均已实现）：
   - `limit_req` 30r/m/IP（抬高批量爬取成本）；
   - `X-Robots-Tag: noindex`（不进搜索引擎索引）＋ `autoindex off`（不列目录）；
   - nginx 侧仅放行 `.html/.js`，其余 `/app/static/` 路径 404（缩小直链面）。
5. **残余风险（如实标注）**：拿到完整直链的匿名用户仍能取到单个 HTML。
   缓解因素：文件名含 SHA256 指纹 12 位不可枚举（`data_fingerprint`），
   风险面收缩为「泄露出的单条直链」；图谱数据敏感度低
   （`docs/DEPLOYMENT.md` §五 P3 口径）；本项目既定定位是
   「编纂端低并发原型」（§五第一行）。三因素叠加，折中可接受；
   若未来数据敏感度升级，出路是改 Streamlit 路由（应用侧鉴权），非反代层。

## 四、核实记录（两件，读文件为准）

1. **docker-compose.yml 端口映射形态**：`web` 服务为
   `"8501:8501"`——**即 0.0.0.0:8501，宿主所有网卡可达**，不是 127.0.0.1。
   （MySQL 侧已是 `127.0.0.1:3306:3306`；`docker-compose.override.yml` 只把
   MySQL 的 ports `!reset []`，未动 web。）
   → 公网部署且反代同宿主时，应改为 `127.0.0.1:8501:8501`，让 8501 只听
   回环、公网流量一律经 443 反代进来。见下方「五、Docker 注意事项」。
2. **st.iframe 图谱 URL 是否经浏览器请求 `/app/static/`**：**是**。
   `src/graph_export.py` 的 `ensure_graph_html`/`ensure_cluster_html`
   返回相对路径 `/app/static/<文件>.html`；`src/app.py` 两处
   `st.iframe(url)`（知识图谱页 height=820、词簇图 height=520）把该相对路径
   写进 iframe 的 src，由浏览器发起请求；HTML 内 `vis-network.min.js`
   同路径加载（`src/.streamlit/config.toml` `enableStaticServing = true`）。
   这是 deny all 被否决的直接依据。

## 五、Docker 部署时端口映射注意事项

- **现状口径（如实）**：仓库根 `docker-compose.yml` 第 36 行 `ports: - "8501:8501"`，
  等价 `0.0.0.0:8501:8501`——公网服务器上这会**绕过反代直接暴露 Streamlit**
  （HTTP 明文、无限速、图谱直链同理暴露）。
- **反代同宿主部署时的推荐改法**（改部署机上的 compose 文件，本仓库样例
  不替你改——是否绑定回环取决于部署拓扑）：

  ```yaml
  ports:
    - "127.0.0.1:8501:8501"
  ```

  容器内 Streamlit 仍监听 `0.0.0.0`（`STREAMLIT_SERVER_ADDRESS=0.0.0.0`，
  Dockerfile 设定），收紧发生在宿主端口映射层，应用无感知。
- MySQL 绑定 `127.0.0.1:3306` 已合规，无需动；双栈开发机的
  `docker-compose.override.yml`（gitignored）将容器 MySQL 端口整体收进
  内部网络，与公网部署口径一致。
- 反代容器化（nginx 跑进 compose）时，web 应改为 **expose 而非 ports**，
  由 compose 内部网络互通；本三件套样例按「反代装在宿主」写就
  （`proxy_pass http://127.0.0.1:8501`），容器化反代时把 upstream 换成
  compose 服务名 `web:8501` 即可。

## 六、与 nginx 样例强相关的两个口径（改配置前必读）

1. **「login 端点 10r/m」的真实落点**：Streamlit 无独立 HTTP 登录端点——
   登录表单在应用页面内，提交走 WebSocket `/_stcore/stream`。样例把
   10r/m 限速挂在该端点的**握手请求**上（每浏览器标签页一次握手，
   正常用户无感；试口令的重连风暴被压住）。
2. **nginx `add_header` 不跨级继承**：`/app/static/` 块内定义了
   `X-Robots-Tag`，server 级安全头已在块内重复声明——改动时别删，
   删了 static 响应会丢 HSTS。
