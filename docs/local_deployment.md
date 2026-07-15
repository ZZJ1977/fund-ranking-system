# 本地部署说明

本文档面向从 GitHub clone 项目后，希望在自己电脑本地运行 Web 分析台的用户。

## 1. 环境要求

- Python 3.10 或更高版本
- macOS、Linux 或 Windows
- 可以访问互联网，用于安装 Python 依赖和抓取公开基金数据

## 2. 克隆项目

```bash
git clone <your-repo-url>
cd fund-ranking-system
```

如果项目目录不是 `fund-ranking-system`，进入实际目录即可。

## 3. 一键启动 Web 版

macOS / Linux 推荐：

```bash
bash scripts/run_web.sh
```

脚本会自动：

1. 创建 `.venv` 虚拟环境。
2. 安装项目依赖。
3. 启动本地 Web 服务。

如果希望服务在后台运行，并把日志写到本地文件：

```bash
bash scripts/start_web.sh
tail -f tmp/fund-ranking-web.log
bash scripts/stop_web.sh
```

启动成功后打开：

```bash
open http://127.0.0.1:8000
```

健康检查地址：

```text
http://127.0.0.1:8000/health
```

Windows PowerShell 用户可以手动执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\fund-ranking-web.exe --host 127.0.0.1 --port 8000
```

然后在浏览器打开：

```text
http://127.0.0.1:8000
```

## 4. 手动安装和启动

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/fund-ranking-web --host 127.0.0.1 --port 8000
```

## 5. Docker 启动

如果本机已经安装 Docker，可以使用：

```bash
docker compose up --build
```

启动成功后打开：

```text
http://127.0.0.1:8000
```

Docker 会把运行产物保存在本地目录：

```text
data/
reports/
```

查看容器健康状态：

```bash
docker compose ps
```

停止服务：

```bash
docker compose down
```

## 6. 配置文件

可以复制示例配置：

```bash
cp .env.example .env
```

默认配置：

```text
FUND_RANKING_HOST=127.0.0.1
FUND_RANKING_PORT=8000
FUND_RANKING_DB=data/fund_ranking.db
```

建议本地演示时保持：

```text
FUND_RANKING_HOST=127.0.0.1
```

这表示服务只允许本机访问，避免暴露到公网。

## 7. 运行测试

```bash
.venv/bin/python -m pytest -q
```

Windows：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 8. 命令行运行

生成 demo 数据并分析：

```bash
.venv/bin/fund-ranking --demo --profile balanced
```

使用真实数据文件分析：

```bash
.venv/bin/fund-ranking \
  --input data/raw/real_fund_nav.csv \
  --metadata data/raw/fund_metadata.csv \
  --profile balanced
```

## 9. 本地生成文件

运行后会在本地生成：

```text
data/fund_ranking.db
data/raw/*.csv
data/processed/*.csv
reports/*.md
reports/*.csv
reports/*.png
reports/web/
```

这些文件是本地运行产物，已经在 `.gitignore` 中忽略，不需要上传 GitHub。

## 10. 安全说明

本项目默认是本地应用：

- Web 服务默认绑定 `127.0.0.1`，只允许本机访问。
- 不读取用户隐私文件。
- 不上传本地文件。
- 不执行删除系统文件等破坏性操作。
- 仅从公开基金数据接口抓取基金净值和基金名称。

不要将本项目默认配置直接作为公网服务开放。如果需要公网部署，需要额外增加登录认证、限流、日志、HTTPS、任务队列和合规审核。

## 11. 常见问题

### 依赖安装慢

可以更换 pip 镜像源，或稍后重试。

### 页面分析失败

可能原因：

- 基金代码不存在。
- AkShare 上游数据接口暂时不可用。
- 网络连接不稳定。
- 基金成立时间太短，指定日期之后数据不足。

可以尝试：

- 使用默认基金池。
- 换常见基金代码。
- 把起始日期调晚。

### 端口被占用

换一个端口：

```bash
FUND_RANKING_PORT=8010 bash scripts/run_web.sh
```

或手动：

```bash
.venv/bin/fund-ranking-web --host 127.0.0.1 --port 8010
```
