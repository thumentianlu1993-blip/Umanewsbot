# 部署运行手册

## 服务器信息记录方式

不要把敏感信息硬编码进仓库，但应按如下方式记录：

- 服务器公网 IP：记录在运维文档或受控密码库中
- 域名：记录在仓库文档中
- DNS 提供商：记录在仓库文档中
- ECS 地域与实例规格：记录在仓库文档中
- `.env` 实际值：只保存在服务器与受控密钥管理位置，不写入仓库

敏感信息包括但不限于：

- root 密码
- API Key
- OSS AccessKey
- `.env` 完整内容

## 域名、DNS、ECS、Nginx、Docker Compose、.env 的关系

- 域名：用户可见入口，例如 `umafans.run`
- DNS：负责把域名解析到 ECS 公网 IP
- ECS：承载 Docker 容器的主机
- Docker Compose：编排 `web / worker / beat / db / redis / nginx`
- Nginx：处理入口请求、静态资源、反向代理
- `.env`：决定 Django 与部署链路运行方式，如 Host、CSRF、SITE_URL、安全策略等

## 本轮修复时验证过的关键检查命令

### 服务器代码版本

```bash
cd /opt/umanewsbot
git rev-parse --short HEAD
```

### 查看 `.env` 关键项

```bash
grep -E '^(ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|SITE_URL|SECURE_SSL_REDIRECT|SESSION_COOKIE_SECURE|CSRF_COOKIE_SECURE|SECURE_HSTS_SECONDS|SECURE_HSTS_INCLUDE_SUBDOMAINS|DJANGO_ADMIN_URL)=' .env
```

### 查看容器状态

```bash
docker compose -f docker-compose.prod.lowcost.yml ps
```

### 查看 nginx 容器中的真实配置

```bash
docker exec umanewsbot-nginx-1 sh -c 'cat /etc/nginx/conf.d/default.conf'
```

### 查看 web 容器中的真实环境变量

```bash
docker exec umanewsbot-web-1 sh -c 'env | grep -E "^(ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|SITE_URL|SECURE_SSL_REDIRECT|SESSION_COOKIE_SECURE|CSRF_COOKIE_SECURE|SECURE_HSTS_SECONDS|SECURE_HSTS_INCLUDE_SUBDOMAINS|DJANGO_ADMIN_URL)="'
```

### 查看日志

```bash
docker logs --tail=120 umanewsbot-web-1
docker logs --tail=120 umanewsbot-nginx-1
docker logs --tail=120 umanewsbot-worker-1
docker logs --tail=120 umanewsbot-beat-1
```

## 以后遇到“HTTP 301 / HTTPS 400 / 域名不通”时的排查顺序

### 1. 先确认 DNS

- 本地 `nslookup`
- 必要时查公共 DNS
- 确认是否已解析到目标 ECS 公网 IP

### 2. 再确认服务器代码版本

- `git rev-parse --short HEAD`
- 不要假设服务器已经是本地最新 commit

### 3. 确认 `.env`

- 是否仍是旧域名/旧 IP/旧安全配置
- 是否包含正确的 `ALLOWED_HOSTS`
- `SITE_URL` 是否与当前阶段一致

### 4. 确认 nginx 运行态

- 不只看仓库里的 `nginx.conf`
- 必须进入 `nginx` 容器读取真实 `default.conf`

### 5. 确认 Django 运行态

- 进入 `web` 容器检查真实环境变量
- 再看 `web` 日志里是否有 `DisallowedHost`、CSRF、重定向等问题

### 6. 最后再看浏览器现象

- 浏览器现象只能说明“外部表现”
- 不能替代对 `nginx`、`.env`、容器环境变量、日志的核对

## 标准流程

### 备份 `.env`

```bash
cd /opt/umanewsbot
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
```

### 检查 HEAD

```bash
git rev-parse --short HEAD
```

### 查看 nginx 容器配置

```bash
docker exec umanewsbot-nginx-1 sh -c 'cat /etc/nginx/conf.d/default.conf'
```

### 查看 web 环境变量

```bash
docker exec umanewsbot-web-1 sh -c 'env | grep -E "^(ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|SITE_URL|SECURE_SSL_REDIRECT|SESSION_COOKIE_SECURE|CSRF_COOKIE_SECURE|SECURE_HSTS_SECONDS|SECURE_HSTS_INCLUDE_SUBDOMAINS|DJANGO_ADMIN_URL)="'
```

### 查看日志

```bash
docker logs --tail=120 umanewsbot-web-1
docker logs --tail=120 umanewsbot-nginx-1
```

## 自动化运营 MVP 部署与验证

### 关键环境变量

自动化能力通过 `.env` 控制，建议生产首次部署时先关闭：

```bash
AUTOMATION_ENABLED=false
AUTO_REVIEW_THRESHOLD=75
MANUAL_REVIEW_THRESHOLD=45
AUTO_PUBLISH_BATCH_LIMIT=3
AUTO_PUBLISH_INTERVAL_MINUTES=15
REWRITE_CONFIDENCE_MIN=60
AUTO_PUBLISH_REQUIRE_COVER=false
REWRITE_PROVIDER=fallback
REWRITE_MODEL=deepseek-ai/DeepSeek-V3
REWRITE_MAX_TOKENS=2600
REWRITE_TIMEOUT_SECONDS=90
AUTOMATION_ENABLE_EMAIL=false
AUTOMATION_NOTIFY_EMAILS=
```

真实启用 AI 改写时，按现有 OpenAI-compatible / SiliconFlow 配置补齐 Key，并将 `REWRITE_PROVIDER` 设置为对应 provider。

### 部署步骤

```bash
cd /opt/umanewsbot
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
git pull origin main
docker compose -f docker-compose.prod.lowcost.yml build web worker beat
docker compose -f docker-compose.prod.lowcost.yml up -d
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py migrate
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py check
```

如生产使用标准 RDS 方案，将 compose 文件替换为 `docker-compose.prod.yml`。

### 验证自动化字段与迁移

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.models import NewsArticle, AutomationLog, NotificationLog; print(NewsArticle.objects.count(), AutomationLog.objects.count(), NotificationLog.objects.count())"
```

### 灰度启用自动化

先把 `.env` 中 `AUTOMATION_ENABLED` 改为 `true`，再重启相关容器：

```bash
docker compose -f docker-compose.prod.lowcost.yml up -d web worker beat
docker logs --tail=120 umanewsbot-worker-1
docker logs --tail=120 umanewsbot-beat-1
```

### 手动触发单篇自动化验证

进入后台候选新闻详情页，点击“重新自动化处理”；或在服务器执行：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import process_article_automation_task; process_article_automation_task.delay(ARTICLE_ID)"
```

将 `ARTICLE_ID` 替换为已翻译文章 ID。

### 自动发布批次验证

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import auto_publish_batch_task; print(auto_publish_batch_task.delay(limit=1))"
docker logs --tail=120 umanewsbot-worker-1
```

验证后台“已发布内容”列表、前台首页和文章详情页是否出现自动发布稿。

### 异常通知验证

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import send_notification_task; send_notification_task.delay('rewrite_failed', {'title': '通知测试', 'article_id': 1})"
```

如果邮件未启用，后台日志中应出现 `NotificationLog(status=skipped, channel=email)`；如果邮件已启用，应出现 `sent` 或具体失败原因。

### 自动化排障顺序

1. 先查 `.env` 中 `AUTOMATION_ENABLED`、阈值、邮件配置和模型配置
2. 再查 `beat` 是否加载 `auto-publish-batch` 与 `detect-automation-anomalies`
3. 查看 `worker` 日志是否有评分、改写、校验、发布异常
4. 后台文章详情页查看 `AutomationLog`
5. 后台操作日志页查看 `NotificationLog`
6. 如果内容质量不稳，先关闭 `AUTOMATION_ENABLED`，不要急着回滚代码
