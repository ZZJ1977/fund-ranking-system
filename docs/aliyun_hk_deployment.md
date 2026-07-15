# 阿里云香港轻量服务器部署说明

本文档面向“香港轻量应用服务器 + IP/临时域名 + Docker Compose”的展示部署方案。

适合场景：

- 给老师、同学、面试官或少量用户试用。
- 不想做中国大陆 ICP 备案。
- 暂时没有正式域名，先用服务器公网 IP 访问。

不适合场景：

- 大规模多人同时使用。
- 正式金融产品上线。
- 需要长期账号体系、审计、权限隔离和稳定 SLA 的生产服务。

## 1. 购买服务器

在阿里云控制台进入“轻量应用服务器”，创建实例：

| 项目 | 建议 |
|---|---|
| 地域 | 中国香港 |
| 镜像 | Ubuntu 22.04 LTS 或 Ubuntu 24.04 LTS |
| 规格 | 2 核 4G 起步 |
| 硬盘 | 60GB 或更高 |
| 带宽 | 3Mbps 起步，演示可用 |

香港地域通常不需要中国大陆 ICP 备案。后续如果换成中国大陆地域并绑定域名，需要按云服务商备案流程处理。

## 2. 开放防火墙

在实例详情页打开“防火墙”，保留或添加：

| 端口 | 协议 | 来源 | 用途 |
|---|---|---|---|
| 22 | TCP | 建议限制为自己的公网 IP | SSH 登录 |
| 80 | TCP | 0.0.0.0/0 | Web 访问 |

本方案暂时只开放 80。等有正式域名后，再开放 443 并配置 HTTPS。

## 3. 登录服务器

在本地终端执行：

```bash
ssh root@你的服务器公网IP
```

如果使用密钥登录：

```bash
ssh -i ~/.ssh/你的密钥.pem root@你的服务器公网IP
```

首次登录后建议更新系统：

```bash
apt update
apt upgrade -y
```

## 4. 安装 Docker 和 Compose

Ubuntu 服务器可使用 Docker 官方安装脚本：

```bash
apt install -y ca-certificates curl git openssl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker --version
docker compose version
```

如果服务器拉取镜像慢，可以在阿里云容器镜像服务 ACR 控制台查看“镜像加速器”，再配置 `/etc/docker/daemon.json`。

## 5. 拉取项目

```bash
cd /opt
git clone https://github.com/ZZJ1977/fund-ranking-system.git
cd fund-ranking-system
```

如果已经 clone 过：

```bash
cd /opt/fund-ranking-system
git pull
```

## 6. 准备生产环境配置

复制配置模板：

```bash
cp deploy/env.production.example .env.production
```

编辑：

```bash
nano .env.production
```

建议内容：

```text
FUND_RANKING_HOST=0.0.0.0
FUND_RANKING_PORT=8000
FUND_RANKING_DB=data/fund_ranking.db
PUBLIC_HTTP_PORT=80
PUBLIC_HOST=你的服务器公网IP
```

`data/` 会保存 SQLite 数据库和净值缓存，`reports/` 会保存每次分析生成的报告、图片和下载文件。

## 7. 一键部署

运行：

```bash
bash scripts/deploy_hk_lightweight.sh
```

脚本会：

1. 创建 `.env.production`，如果还不存在。
2. 创建 `data/`、`reports/` 和 `deploy/secrets/`。
3. 生成 Nginx Basic Auth 密码文件。
4. 构建并启动应用容器和 Nginx 容器。
5. 检查 `/health` 是否正常。

部署完成后访问：

```text
http://你的服务器公网IP
```

浏览器会弹出用户名和密码。用户名/密码就是脚本里创建 Basic Auth 时输入的内容。

## 8. 常用运维命令

查看容器：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

看日志：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f
```

重启：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml restart
```

停止：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml down
```

更新代码并重新部署：

```bash
cd /opt/fund-ranking-system
git pull
bash scripts/deploy_hk_lightweight.sh
```

健康检查：

```bash
curl -fsS http://127.0.0.1/health
curl -fsS http://你的服务器公网IP/health
```

如果浏览器打开后看到 Nginx 的 `500 Internal Server Error`，通常是 Basic Auth 密码文件权限过严，Nginx 容器无法读取。执行：

```bash
cd /opt/fund-ranking-system
chmod 644 deploy/secrets/.htpasswd
docker compose --env-file .env.production -f docker-compose.prod.yml restart nginx
```

然后重新打开：

```text
http://你的服务器公网IP
```

## 9. 临时域名

没有正式域名时，可以先直接用 IP：

```text
http://你的服务器公网IP
```

如果只是为了演示一个“像域名”的地址，也可以使用 IP 映射类临时域名，例如：

```text
http://你的服务器公网IP.sslip.io
```

临时域名只适合演示。正式分享时建议购买域名，配置 DNS，再上 HTTPS。

## 10. 安全提醒

- Basic Auth 在 HTTP 下不是严格安全方案，密码可能被中间网络看到；演示密码不要复用重要密码。
- 不要开放 8000 端口，应用容器只应该通过 Nginx 反向代理访问。
- 不要提交 `.env.production` 和 `deploy/secrets/.htpasswd`。
- 如果要长期公开访问，下一步应配置 HTTPS、访问日志、限流、定期备份、报告文件清理和更完整的免责声明。
- 本项目输出是历史表现分析和研究辅助，不构成个性化投资建议、收益承诺或买卖指令。

## 11. 官方参考

- [阿里云轻量应用服务器文档](https://help.aliyun.com/zh/simple-application-server/)
- [阿里云轻量应用服务器防火墙设置](https://help.aliyun.com/zh/simple-application-server/user-guide/manage-the-firewall-of-a-server)
- [阿里云远程连接 Linux 服务器](https://help.aliyun.com/zh/simple-application-server/user-guide/connect-to-linux-server-remotely)
- [阿里云备案服务器检查](https://help.aliyun.com/zh/icp-filing/basic-icp-service/user-guide/icp-filing-server-access-information-check)
- [Docker Engine Ubuntu 安装文档](https://docs.docker.com/engine/install/ubuntu/)
