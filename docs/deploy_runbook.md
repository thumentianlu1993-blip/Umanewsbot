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

## 新闻抓取健康排查

### 后台入口

日常先看业务后台：

- `/admin/` 工作台的“最近来源状态”
- `/admin/sources/` 来源管理列表

重点确认：

- 最近抓取时间
- 运行状态
- 最近结果摘要
- 是否显示“运行中”“运行超时”“成功无新增”“失败”或“长时间未运行”

“成功无新增”表示抓取任务正常执行，但本轮抓到的文章都已存在；这不等同于抓取失败。
“运行中”表示最新抓取记录已开始但尚未写入最终结果；如运行中记录超过 60 分钟仍未完成，后台会显示“运行超时”，需要检查 worker / beat 日志和对应 `CrawlJob`。
“长时间未运行”只用于仍启用的来源；停用来源不纳入该告警。

### 服务器查询

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c "from stable.models import CrawlJob; from django.utils import timezone; [print(timezone.localtime(j.started_at).strftime('%F %T'), j.source.name if j.source_id else '-', j.status, j.success_count, j.fail_count, (j.error_message or '')[:120]) for j in CrawlJob.objects.select_related('source').order_by('-started_at')[:20]]"
```

### 当前内置抓取频率

- netkeiba 新着顺：每小时 `00` 分抓取，周日重赏时段另有高频补抓。
- netkeiba 访问量榜：每小时 `16` 分抓取第一页。
- netkeiba 注目数榜：每小时 `26` 分抓取第一页。
- JRA 官方新闻：每 12 小时扫描当前月和上月。

部署涉及抓取调度变更后，必须重启 `beat / worker / web`，并在连续一个小时内确认 netkeiba 新着顺、访问量榜和注目数榜分别按 `00/16/26` 分生成错峰 `CrawlJob`；周日重赏高频补抓分钟不得与访问量榜 / 注目数榜重合。

### JRA 日期解析验收

如 JRA 曾出现 `time data '5月31日' does not match format '%Y年%m月%d日'`，部署后可以手动触发或等待下一次任务：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py crawl_news jra
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c "from stable.models import CrawlJob, NewsSource; source=NewsSource.objects.get(source_site='jra', source_mode='official'); print(source.last_crawl_status, source.last_crawl_message); print(CrawlJob.objects.filter(source=source).order_by('-started_at').values('status','success_count','fail_count','error_message').first())"
```

若单篇 JRA 详情页结构异常，预期行为是跳过该篇、继续处理同轮其他新闻，并在 `last_crawl_message` / `CrawlJob.error_message` 中留下“跳过 N 条”摘要；列表页、网络或数据库异常仍按整轮失败排查。

## 2026-06-25 三个运营改造 change 合并、部署与归档

### 合并范围

- `codex/fix-crawl-freshness-and-health`：抓取新鲜度、JRA 日期解析、来源健康摘要和 netkeiba `00/16/26` 分错峰调度。
- `codex/add-selection-term-quick-add`：后台候选详情页 / 文章编辑台原文选区快速加入术语库。
- `codex/add-selection-term-quick-add` 后续提交：新增术语成功后的 15 秒一次性浮层，可点击后仅将该术语应用到当前文章已有中文字段。
- 注意：`fix-crawl-health-running-and-schedule-stagger` 是抓取 change 的后续返修 OpenSpec 目录，随抓取 change 一并归档。

### 部署前检查

- 服务器部署前 HEAD：`268100d`。
- 服务器工作树：干净。
- 外部导入锁：`ExternalDataImportLock.locked_by_run_id=None`。
- 最近外部导入 run：`run_id=120` 等均为 `paused`，没有运行中的长导入。

### 部署步骤与结果

- 本地发布分支从 `origin/main` 合并两个代码分支后推送到 `main`，合并后提交为 `7f54f13`。
- 部署前备份 `.env`：`.env.backup.three-changes-20260625_003714`。
- 服务器 `/opt/umanewsbot` 执行 `git pull --ff-only origin main`，从 `268100d` 更新到 `7f54f13`。
- 执行 `bash ./deploy_lowcost.sh`，重建 `web / worker / beat`，`db / redis / nginx` 保持运行。
- 迁移结果：`No migrations to apply`。
- `collectstatic` 结果：`0 static files copied`，`360 post-processed`。
- 容器状态：`web` healthy，`db / redis` healthy，`worker / beat` running，`nginx` running。
- 验证：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
  - `http://127.0.0.1/healthz/`：`200`。
  - `http://127.0.0.1/`：`200`。
  - 运行态调度确认：`crawl-netkeiba-latest-hourly=00`，`crawl-netkeiba-access=16`，`crawl-netkeiba-attention=26`，三者 `crawl_interval_minutes=60`。

### 归档结果

- `openspec/changes/archive/2026-06-24-fix-crawl-freshness-and-jra-date-parse/`
- `openspec/changes/archive/2026-06-24-fix-crawl-health-running-and-schedule-stagger/`
- `openspec/changes/archive/2026-06-24-add-selection-term-quick-add/`
- `openspec/changes/archive/2026-06-24-reapply-terms-after-quick-add/`
- 正式规格已同步：
  - `openspec/specs/crawl-freshness-and-source-health/spec.md`
  - `openspec/specs/termbase-and-race-priority/spec.md`
- 归档后 `openspec validate --all` 通过。

### 后续观察

- 抓取错峰的“连续小时自然生成 `CrawlJob`”仍需等待调度运行后确认；本次已确认代码和运行时 Celery Beat 配置加载为 `00/16/26` 分。
- 如外部马名数据导入重新启动，继续遵守“导入期间不执行 `git pull / build / up / deploy_lowcost.sh`”的互斥规则。

## 自动化运营 MVP 部署与验证

### 关键环境变量

自动化能力通过 `.env` 控制，建议生产首次部署时先关闭：

```bash
AUTOMATION_ENABLED=false
AUTO_REVIEW_THRESHOLD=75
MANUAL_REVIEW_THRESHOLD=45
AUTO_REWRITE_ENABLED=false
AUTO_PUBLISH_CONTENT_SOURCE=base_translation
HIGH_VALUE_SOURCE_RULES=netkeiba:access,netkeiba:attention
HIGH_VALUE_WARNING_SCORE_THRESHOLD=90
AUTO_DUPLICATE_LOOKBACK_DAYS=7
AUTO_DUPLICATE_HIGH_THRESHOLD=0.86
AUTO_DUPLICATE_REVIEW_THRESHOLD=0.72
AUTO_PUBLISH_BATCH_LIMIT=4
AUTO_PUBLISH_PEAK_BATCH_LIMIT=10
AUTO_PUBLISH_PEAK_DAY_OF_WEEK=6
AUTO_PUBLISH_PEAK_START_HOUR=13
AUTO_PUBLISH_PEAK_END_HOUR=16
AUTO_PUBLISH_INTERVAL_MINUTES=15
REWRITE_CONFIDENCE_MIN=60
AUTO_PUBLISH_REQUIRE_COVER=false
REWRITE_PROVIDER=fallback
REWRITE_MODEL=deepseek-ai/DeepSeek-V3
REWRITE_MAX_TOKENS=2600
REWRITE_TIMEOUT_SECONDS=90
AUTOMATION_ENABLE_EMAIL=false
AUTOMATION_NOTIFY_EMAILS=
AUTOMATION_WARNING_EMAIL_ENABLED=true
AUTOMATION_WARNING_NOTIFY_EMAILS=754652181@qq.com
AUTOMATION_WARNING_EMAIL_DEDUP_HOURS=24
```

`refine-automation-publish-gates` 实施后，短期建议保持 `AUTO_REWRITE_ENABLED=false` 和 `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`，先用基准翻译稿跑自动发布门禁。真实恢复 AI 改写时，按现有 OpenAI-compatible / SiliconFlow 配置补齐 Key，将 `AUTO_REWRITE_ENABLED=true`，并将 `AUTO_PUBLISH_CONTENT_SOURCE=rewrite`、`REWRITE_PROVIDER` 设置为对应 provider。

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

验证门禁字段、重复状态和普通词种子：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.models import NewsArticle, TermEntry, WorkflowStatus; print(hasattr(WorkflowStatus, 'DUPLICATE'), NewsArticle.objects.exclude(gate_issues=[]).count(), TermEntry.objects.filter(notes__icontains='non_horse_common_word').count())"
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

自动化门禁优化上线后，单篇验证重点查看：

- 后台候选详情页是否展示 blocker / warning / info。
- `warning` 是否仍允许文章进入 `automation_status=publish_ready`。
- 高度重复文章是否进入 `workflow_status=duplicate`。
- 中等相似文章是否转入 `workflow_status=pending_review`。
- 高价值来源文章是否在评分阶段放行，但不绕过 blocker。

### 自动发布批次验证

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import auto_publish_batch_task; print(auto_publish_batch_task.delay(limit=1))"
docker logs --tail=120 umanewsbot-worker-1
```

验证后台“已发布内容”列表、前台首页和文章详情页是否出现自动发布稿。

### 自动发布批量规则验证

生产默认规则：

- 常规时段：每 15 分钟最多自动发布 4 篇
- 每周日北京时间 13:00-16:00：每 15 分钟最多自动发布 10 篇

检查运行时配置：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web sh -c 'env | grep -E "^(AUTO_PUBLISH_BATCH_LIMIT|AUTO_PUBLISH_PEAK_BATCH_LIMIT|AUTO_PUBLISH_PEAK_DAY_OF_WEEK|AUTO_PUBLISH_PEAK_START_HOUR|AUTO_PUBLISH_PEAK_END_HOUR|AUTO_PUBLISH_INTERVAL_MINUTES)="'
```

检查任务按当前时间解析出的批量上限：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import _resolve_auto_publish_batch_limit; print(_resolve_auto_publish_batch_limit())"
```

### 异常通知验证

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import send_notification_task; send_notification_task.delay('rewrite_failed', {'title': '通知测试', 'article_id': 1})"
```

如果邮件未启用，后台日志中应出现 `NotificationLog(status=skipped, channel=email)`；如果邮件已启用，应出现 `sent` 或具体失败原因。

### 高价值 warning 邮件验证

`warning` 初期不阻断自动发布，但高价值文章出现 warning 时应发送或跳过并留痕：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.models import NotificationLog; print(NotificationLog.objects.filter(type='high_value_warning').order_by('-created_at').values('status','target','error_message')[:5])"
```

如果 `AUTOMATION_WARNING_EMAIL_ENABLED=true` 但没有配置 `AUTOMATION_WARNING_NOTIFY_EMAILS`，应看到 `status=skipped` 且自动发布不被阻断。同一文章同一 warning 组合 24 小时内重复触发时，也应记录 skipped 去重日志。

### 2026-06-24 自动发布门禁优化生产上线结果

- 部署 PR：#4 `[codex] refine automation publish gates`。
- 生产提交：`42a4622`。
- 部署前 `.env` 备份：`.env.backup.refine-automation-20260624_013323`。
- 生产灰度策略：`AUTO_REWRITE_ENABLED=false`，`AUTO_PUBLISH_CONTENT_SOURCE=base_translation`，高价值 warning 邮件发送到 `754652181@qq.com`。
- 迁移：`stable.0009_automation_publish_gates` 已应用。
- 健康检查：`http://umafans.run/healthz/` 与 `/` 均返回 `200`，`web` 容器 healthy。
- 验收查询：`WorkflowStatus.DUPLICATE=True`，首批非马名普通词种子数量 `14`，`python manage.py check` 通过。
- 部署日志曾出现一次字段已存在异常，原因为容器启动迁移与手工迁移并发；后续 `showmigrations`、`check` 和健康检查均正常。

### 自动化排障顺序

1. 先查 `.env` 中 `AUTOMATION_ENABLED`、`AUTO_REWRITE_ENABLED`、`AUTO_PUBLISH_CONTENT_SOURCE`、阈值、邮件配置和模型配置
2. 再查 `beat` 是否加载 `auto-publish-batch` 与 `detect-automation-anomalies`
3. 查看 `worker` 日志是否有评分、改写、校验、发布异常
4. 后台文章详情页查看 `AutomationLog`
5. 后台操作日志页查看 `NotificationLog`
6. 如果内容质量不稳，先关闭 `AUTOMATION_ENABLED`，不要急着回滚代码

## QQ 群自动推送部署与验证

### 关键环境变量

自动 QQ 推送默认关闭，生产首次部署建议保持：

```bash
QQ_PUSH_ENABLED=false
QQ_PUSH_SCOPE=high_value_only
QQ_PUSH_MAX_ATTEMPTS=3
QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS=5
QQ_PUSH_SENDING_STALE_SECONDS=600
QQ_PUSH_MIN_INTERVAL_SECONDS=60
ONEBOT_BASE_URL=http://onebot:3000
ONEBOT_ACCESS_TOKEN=
ONEBOT_TIMEOUT_SECONDS=30
```

`QQ_PUSH_SCOPE` 支持：

- `high_value_only`：默认，仅推 `score_total >= AUTO_REVIEW_THRESHOLD` 的已发布文章
- `all_public`：推所有公开 URL 可访问的已发布文章

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

### 配置群目标

进入 Django Admin：

```text
/django-admin/stable/pushtarget/
```

配置 `name`、`group_id`，并将测试群设为 `is_active=true`。自动推送只看 `is_active`，`is_default` 仅用于手动推送默认群。

### OneBot 网关安全边界

OneBot API 不得公网裸露。推荐 Docker 内网访问：

```env
ONEBOT_BASE_URL=http://onebot:3000
```

如果临时映射到宿主机，只允许：

```yaml
ports:
  - "127.0.0.1:3000:3000"
```

不要使用公网 `0.0.0.0:3000:3000`。

### 灰度启用

确认测试群和 OneBot 网关可用后，把 `.env` 改为：

```bash
QQ_PUSH_ENABLED=true
QQ_PUSH_SCOPE=high_value_only
```

重启 worker / beat：

```bash
docker compose -f docker-compose.prod.lowcost.yml up -d worker beat
```

### 验收命令

检查配置：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec worker sh -c 'env | grep -E "^(QQ_PUSH_ENABLED|QQ_PUSH_SCOPE|QQ_PUSH_MAX_ATTEMPTS|QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS|QQ_PUSH_SENDING_STALE_SECONDS|QQ_PUSH_MIN_INTERVAL_SECONDS|ONEBOT_BASE_URL|ONEBOT_TIMEOUT_SECONDS)="'
```

查看交付记录：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.models import QQPushDelivery; print(QQPushDelivery.objects.order_by('-created_at').values('id','article_id','target_id','status','attempt_count','last_error_type')[:10])"
```

查看 worker 日志：

```bash
docker logs --tail=160 umanewsbot-worker-1
```

后台排查入口：

```text
/django-admin/stable/qqpushdelivery/
```

### 停用和回滚

最快停用方式：

```bash
QQ_PUSH_ENABLED=false
docker compose -f docker-compose.prod.lowcost.yml up -d worker beat
```

停用自动 QQ 推送不会影响公开网站、自动发布或后台手动推送。若 OneBot 网关异常，可先停掉 OneBot 容器或把目标群 `is_active=false`。

## 专有术语候选发现灰度部署

## 正式术语库恢复与赛事等级修复部署

### 适用场景

用于修复正式术语库缺失、马名或比赛名翻译未命中、赛事等级识别不足导致自动评分偏低的问题。本流程覆盖：

- 正式术语 `race_grade` 字段迁移
- 术语候选池基础内容字段迁移
- 正式术语种子数据 dry-run 与导入
- 执行日 0:00 后候选新闻池批量验收

### 部署前备份

```bash
cd /opt/umanewsbot
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
mkdir -p backups
docker compose -f docker-compose.prod.lowcost.yml exec db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backups/pre-termbase-race-grade-$(date +%Y%m%d_%H%M%S).sql
```

如生产使用标准 Compose 文件，将 `docker-compose.prod.lowcost.yml` 替换为 `docker-compose.prod.yml`。

### 部署与迁移

```bash
cd /opt/umanewsbot
git pull origin main
docker compose -f docker-compose.prod.lowcost.yml build web worker beat
docker compose -f docker-compose.prod.lowcost.yml up -d web worker beat
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py migrate
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py check
```

### 术语导入 dry-run

默认种子文件位于容器内 `server/stable/data/terms_seed.csv`。先执行预检：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py import_terms --dry-run
```

确认输出中的错误数量为 `0`。若生产已经存在部分术语，默认 `upsert` 会显示更新数量；如需严格新增模式，可显式执行：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py import_terms --dry-run --mode create
```

### 正式导入术语

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py import_terms
```

### 核验正式术语

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.models import TermEntry; print(TermEntry.objects.count()); print(list(TermEntry.objects.filter(source_ja__in=['キタサンブラック','宝塚記念']).values('term_type','source_ja','target_zh','race_grade','aliases_ja')))"
```

期望：

- `キタサンブラック` 为启用马名术语，中文译词为 `北部玄驹`
- `宝塚記念` 为启用比赛术语，`race_grade=G1`

### 执行日候选新闻池批量验收

验收不只看单篇文章。按服务器当前时区执行日 0:00 后进入候选新闻池的全部文章检查：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py validate_candidate_news_since_midnight --format json
```

如需指定起点：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py validate_candidate_news_since_midnight --since 2026-06-09 --format json
```

逐篇确认：

- `terms` 中已有正式术语命中
- 未命中的马名和比赛名存在术语候选证据
- `race_grade` 与 `race_priority` 合理
- `score_total` 与 `review_mode` 不再出现明显低估

### 单篇文章重跑

如需重跑文章 `3961`：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import translate_article_task, process_article_automation_task, discover_term_candidates_task; article_id=3961; translate_article_task.delay(article_id); process_article_automation_task.delay(article_id); discover_term_candidates_task.delay(article_id)"
```

重跑后进入后台文章详情页核验中文标题、翻译元数据、自动评分原因和术语候选证据。

### 回滚方式

- 数据导入错误：优先使用后台停用错误术语，或用 `import_terms --mode upsert` 导入修正 CSV。
- 代码异常：回滚到上一 commit 并重启 `web/worker/beat`。
- 数据结构回滚：仅在确认无法通过停用术语或代码回滚恢复时，使用部署前数据库备份还原。

### 部署前配置

首次部署保持默认关闭：

```env
TERM_DISCOVERY_ENABLED=false
TERM_DISCOVERY_PROVIDER=rules
TERM_DISCOVERY_MIN_CONFIDENCE=60
```

执行代码部署、数据库迁移与检查：

```bash
docker compose -f docker-compose.prod.lowcost.yml up -d --build web worker beat
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py migrate
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py check
```

### 单篇手动验证

在后台候选新闻详情页点击“重新发现术语”，或执行：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import discover_term_candidates_task; print(discover_term_candidates_task.run(ARTICLE_ID))"
```

检查后台“术语候选”列表，确认候选类型、上下文、来源文章、置信度、冲突信息和出现次数合理；接受一条测试候选后，确认正式术语库新增记录且操作日志完整。

### 逐步启用

1. 先保持关闭，抽查若干单篇手动发现结果。
2. 将 `TERM_DISCOVERY_ENABLED=true`，只重启 `web` 与 `worker`。
3. 每日抽检待审核候选，重点观察误报、跨类型冲突和证据增长。
4. 根据质量谨慎调整 `TERM_DISCOVERY_MIN_CONFIDENCE`，不要在未抽检时降低阈值。

### 监控与关闭

- 通过 `TaskExecutionLog(task_name=discover_term_candidates)` 查看任务成功与失败。
- 观察候选池每日新增量、拒绝比例、平均证据数量和正式术语冲突。
- 若误报或任务异常增加，将 `TERM_DISCOVERY_ENABLED=false` 并重启 `web` 与 `worker`；无需回滚迁移或删除候选数据。
- 不进行历史全量回溯，不允许绕过工作人员审核直接写入 `TermEntry`。

### 本次执行记录（2026-06-07）

实际部署时确认的若干细节，供后续运维复用：

- 连接方式：`ssh root@47.239.167.86`（公网 IP，端口 `22`，公钥认证）；部署目录 `/opt/umanewsbot`，compose 用 `docker-compose.prod.lowcost.yml`。
- 服务器 `git pull origin main` 走 HTTPS 远端，从 `7123e4e` 快进到 `e2e3e07`。
- **`web` 容器启动脚本会自动执行 `migrate`**：`docker compose up -d` 重建 `web` 后，迁移 `0006` 已在启动时应用，随后显式 `migrate` 会显示 `No migrations to apply`，属正常。
- 生产数据库名与用户均为 `horse_news`；迁移前快照命令：
  ```bash
  docker compose -f docker-compose.prod.lowcost.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > backups/pre-0006-<时间戳>.sql
  ```
- 本次备份产物：`.env.backup.20260607_033207` 与 `backups/pre-0006-20260607_033207.sql`（74M）。
- 验证：`check` 0 issues；候选/证据计数 `0/0`；`nginx → web` 与外网 `umafans.run` / `www.umafans.run` 均 `200`；`worker` 无报错。
- 本轮保持 `TERM_DISCOVERY_ENABLED=false`，未改 `AUTOMATION_ENABLED`（线上为 `true`）与 HTTPS。

## 公开首页资讯流生产部署（2026-06-22）

### 部署内容

- GitHub PR #1 `[codex] Upgrade public home info feed` 已从 draft 转为 ready，并合并到 `main`。
- merge commit：`e834f58`；实现提交：`1c9be7d`。
- 服务器 `/opt/umanewsbot` 从 `62a6a02` 快进到 `e834f58`。
- 本次不包含数据库迁移、生产 `.env` 开关调整或 Compose 架构变更。
- 新增公开站点静态资源 `stable/public.css`，首页与详情页不再以后台 `console.css` 作为主要样式入口。

### 部署前状态与备份

- 服务器存在未跟踪 `.env.backup.*` 和 `imports/`，保留不清理。
- 服务器 tracked diff 仅为部署脚本权限位变化：
  - `deploy_lowcost.sh`
  - `deploy/deploy_lowcost.sh`
  - `deploy/docker/compose-wrapper.sh`
- 上述权限位变化是为了修复此前 `Permission denied`，内容无差异，部署时予以保留。
- 部署前 `.env` 备份：`.env.backup.20260622_140844`。

### 部署命令

```bash
cd /opt/umanewsbot
git fetch origin main
git pull --ff-only origin main
./deploy_lowcost.sh
```

脚本结果：

- 重建并重启 `web / worker / beat`。
- `migrate` 显示 `No migrations to apply`。
- `collectstatic` 成功处理公开静态资源，生产首页引用 `/static/stable/public.2eec24723b45.css`。
- `web` 容器为 healthy，`db / redis` healthy，`worker / beat` up。

### 验证结果

```bash
curl -I http://umafans.run/healthz/
curl -I http://umafans.run/
curl -I http://umafans.run/static/stable/public.2eec24723b45.css
docker compose -f docker-compose.prod.lowcost.yml ps
docker logs --tail=80 umanewsbot-web-1
docker logs --tail=80 umanewsbot-nginx-1
```

结果：

- `http://umafans.run/healthz/` 返回 `200`，响应体为 `{"status": "ok"}`。
- `http://umafans.run/` 返回 `200`。
- 首页 HTML 包含 `home-page`、`headline-card`、`news-card` 和“原站热度”。
- 首页引用 `/static/stable/public.2eec24723b45.css`，不再引用旧 `console.css`。
- `public.css` 可访问并包含移动端 `news-card`、`headline-card`、`-webkit-line-clamp` 和 390px 视口布局规则。
- 浏览器生产验收：
  - 桌面端：轻导航、主头条和热门模块显示正常。
  - 390px 移动端：普通新闻卡约 `128px` 高，右侧缩略图约 `104px x 78px`，首屏头条后可见 3 条普通新闻，无横向溢出。
  - 详情页：标题、封面、来源、公开详情结构和 `public.css` 引用正常，控制台无错误。

### 回滚方式

本次无数据库迁移。若公开首页出现严重问题，优先回滚代码与容器：

```bash
cd /opt/umanewsbot
git checkout 62a6a02
./deploy_lowcost.sh
```

如需保持 `main` 分支语义，优先在 GitHub revert `e834f58` 后服务器 `git pull --ff-only origin main` 并重新执行 `./deploy_lowcost.sh`。

## 移动端首页密度 follow-up 生产部署（2026-06-23）

### 部署内容

- GitHub PR #2 `[codex] Polish mobile public home density` 已从 draft 转为 ready，并合并到 `main`。
- merge commit：`04e2ee9`；实现提交：`b6e93b9`。
- 服务器 `/opt/umanewsbot` 从 `e834f58` 快进到 `04e2ee9`。
- 本次不包含数据库迁移、生产 `.env` 开关调整或 Compose 架构变更。
- 主要变更是移动端 `stable/public.css` 首屏密度微调：收紧顶部与页面间距、头条图片比例从 `16 / 9` 改为 `16 / 7`、移动端隐藏头条摘要，普通新闻卡保持约 `128px` 高。

### 部署前状态与备份

- 部署前 `.env` 备份：`.env.backup.20260623_120201`。
- 服务器仍存在历史 `.env.backup.*` 与 `imports/` 未跟踪文件，保留不清理。
- 服务器 tracked diff 显示多个部署脚本权限位变化，属线上执行权限修正遗留，部署时保留不回滚。

### 部署命令

```bash
cd /opt/umanewsbot
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
git pull --ff-only origin main
chmod +x deploy_lowcost.sh deploy/*.sh deploy/docker/*.sh
./deploy_lowcost.sh
```

脚本结果：

- 重建并重启 `web / worker / beat`。
- `migrate` 显示 `No migrations to apply`。
- `collectstatic` 完成，生产首页引用 `/static/stable/public.9aaf4b105424.css`。
- `web` 容器为 healthy，`db / redis` healthy，`worker / beat` up。
- `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check` 返回 `System check identified no issues`。

### 验证结果

```bash
curl -I http://umafans.run/healthz/
curl -I http://umafans.run/
curl http://umafans.run/ | grep public
docker compose -f docker-compose.prod.lowcost.yml ps
docker logs --tail=80 umanewsbot-web-1
```

结果：

- `http://umafans.run/healthz/` 返回 `200`。
- `http://umafans.run/` 返回 `200`。
- 首页 HTML 包含 `home-page`、`headline-card`、`news-card` 和“原站热度”。
- 首页引用 `/static/stable/public.9aaf4b105424.css`，不引用 `console.css`。
- `public.css` 可访问并包含移动端 `max-width: 599px`、`aspect-ratio: 16 / 7` 和摘要隐藏规则。
- 浏览器生产验收：
  - 390px 移动端：首页头条约 `257px` 高，第一张普通新闻卡 `top=388`，普通新闻卡约 `128px` 高，右侧缩略图约 `104px x 78px`，首屏可见 4 条普通新闻，无横向溢出。
  - 详情页：公开详情结构、标题、封面正常，无横向溢出，控制台无错误。

### 回滚方式

本次无数据库迁移。若移动端首页密度出现严重问题，优先在 GitHub revert `04e2ee9`，然后服务器执行：

```bash
cd /opt/umanewsbot
git pull --ff-only origin main
./deploy_lowcost.sh
```

如需临时直接回退到上一生产版本，可 checkout `e834f58` 后重新部署，但后续仍应通过 GitHub revert 保持 `main` 分支语义一致。

## 外部赛马数据导入运行手册

### 默认状态

外部赛马数据导入默认不运行：

```bash
EXTERNAL_HORSE_DATA_IMPORT_ENABLED=false
EXTERNAL_HORSE_DATA_ALLOW_NETWORK=false
```

Celery 任务 `stable.tasks.import_external_horse_data_task` 不加入默认全量 Celery Beat 调度，生产只能由人工明确触发。

### 生产执行前

1. 确认代码已部署并执行迁移。
2. 备份数据库。
3. 确认同一时间没有其他外部赛马数据导入任务运行。
4. 首次执行建议先不抓赔率，先只补 `entry/result/horse/history`。
5. 首次真实请求建议使用更保守限速：`8-10` 秒请求间隔，小批量执行。

### 依赖检查

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data --check-dependency
```

### dry-run

dry-run 不写入外部数据表：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data --year 2026 --month 5 --dry-run
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data --race-id 202605310101 --dry-run
```

### 单月小批量真实导入

必须同时打开配置和命令参数：

```bash
EXTERNAL_HORSE_DATA_IMPORT_ENABLED=true
EXTERNAL_HORSE_DATA_ALLOW_NETWORK=true
EXTERNAL_HORSE_DATA_REQUEST_INTERVAL_SECONDS=10
EXTERNAL_HORSE_DATA_JITTER_SECONDS=2
EXTERNAL_HORSE_DATA_MAX_RACES_PER_RUN=10
EXTERNAL_HORSE_DATA_MAX_HORSES_PER_RUN=30
EXTERNAL_HORSE_DATA_FETCH_ODDS=false
```

执行：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data \
  --year 2026 --month 5 \
  --allow-network \
  --max-races 10 \
  --max-horses 30 \
  --no-fetch-horse-detail
```

如需补单匹马，并且人工已知可信日文马名：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data \
  --horse-id 1000000000 \
  --horse-name マヤノライジン \
  --allow-network
```

### 验收查询

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data --lookup-name マヤノライジン
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data --stats-run-id <run_id>
```

重点看：

- `status`
- `failure_count`
- `coverage_stats.race_count`
- `coverage_stats.entry_count`
- `coverage_stats.result_count`
- `coverage_stats.unique_horse_id_count`
- `coverage_stats.unique_horse_name_count`
- `coverage_stats.missing_horse_id_or_name_count`

### 日志与停止

```bash
docker logs --tail=200 umanewsbot-web-1
docker logs --tail=200 umanewsbot-worker-1
```

如需停止：

1. 关闭 `EXTERNAL_HORSE_DATA_IMPORT_ENABLED=false` 和 `EXTERNAL_HORSE_DATA_ALLOW_NETWORK=false`。
2. 停止正在执行导入的命令或 Celery worker。
3. 保留外部数据表记录，新表不参与主新闻链路，不影响前台发布。

### 2026-06-23 首次生产小批量结果

- 部署提交：`58a6e82`。
- `.env` 备份：`.env.backup.external-horse-data-20260623_231514`。
- `stable.0008` 迁移已应用，`web` healthy，`/healthz/` 返回 `200`。
- `python manage.py import_external_horse_data --check-dependency` 返回 `keibascraper import ok`。
- dry-run 目标：`2026-05`，最多 10 场，预计 20 个请求。
- 真实导入参数：`2026-05`，最多 10 场，不抓赔率，不补马匹详情，请求间隔 10 秒 + 2 秒抖动。
- 结果：`run_id=1`，`status=paused`，成功 10 场，失败 0，因批量上限跳过 326 场。
- 写入：10 场比赛、151 条出走、143 条赛果、143 个唯一马 ID/马名索引。
- `2026-06-24` 已补充按月续跑逻辑：再次执行同一月份时会跳过已落库 race，只处理下一批未导入 race。
- 第二批续跑结果：`run_id=2`，已跳过首批 10 场，继续成功导入 10 场，失败 0；累计 20 场比赛、274 个唯一马 ID/马名索引。
- 第三批续跑结果：`run_id=3`，继续成功导入 30 场，失败 0；累计 50 场比赛、695 个唯一马 ID/马名索引，`/healthz/` 返回 `200`。
- 长循环导入中断记录：`run_id=4` 到 `run_id=8` 均成功；`run_id=9` 成功 7 场后进程退出码 `137` 中断，已标记为 `partial` 并释放导入锁。中断后累计 182 场比赛、2401 个唯一马 ID/马名索引，`/healthz/` 返回 `200`。

## QQ Bot / OneBot 生产运行态配置（2026-06-24）

### 配置结论

- OneBot 网关：独立 Docker 容器 `umanewsbot-onebot-1`
- 镜像：`mlikiowa/napcat-docker:latest`
- 访问边界：
  - 宿主机仅绑定 `127.0.0.1:3000 -> 3000` 和 `127.0.0.1:6099 -> 6099`
  - 应用容器通过 Docker 网络别名 `http://onebot:3000` 访问
  - 不对公网暴露 OneBot API 或 NapCat WebUI
- 数据目录：
  - `/opt/umanewsbot/napcat/config`
  - `/opt/umanewsbot/napcat/qq`
- 机密文件：
  - `/opt/umanewsbot/runtime/secrets/onebot_access_token`
  - `/opt/umanewsbot/runtime/secrets/napcat_webui_token`

### 生产 `.env`

```env
ONEBOT_BASE_URL=http://onebot:3000
ONEBOT_TIMEOUT_SECONDS=30
QQ_PUSH_ENABLED=false
QQ_PUSH_SCOPE=all_public
QQ_PUSH_MAX_ATTEMPTS=3
QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS=5
QQ_PUSH_SENDING_STALE_SECONDS=600
QQ_PUSH_MIN_INTERVAL_SECONDS=60
```

`ONEBOT_ACCESS_TOKEN` 已写入生产 `.env`，但不得写入仓库文档。`QQ_PUSH_MIN_INTERVAL_SECONDS` 用于控制同一目标群两次自动发送尝试之间的最小间隔，避免批量补推或批量发布触发 QQ / NapCat 发送异常。

### 已配置群目标

- `PushTarget.group_id=1026525240`
- `name=UmaFans测试群`
- `is_active=true`

### 验证结果

- `docker ps` 显示 `umanewsbot-onebot-1` 正常运行。
- `ss -ltnp` 显示 `3000` 与 `6099` 均只监听 `127.0.0.1`。
- OneBot 直连测试返回 `{"status":"ok","retcode":0,...}`，消息发送到 `新闻测试(1026525240)`。
- Django 应用侧 `stable.services.onebot.BotPusher` 通过 `http://onebot:3000` 成功发送测试消息，返回 `retcode=0`。
- 重启 `worker / beat` 让它们读取新的 `.env`；Compose 同时按依赖短暂重建了 `db / web` 容器，但没有执行 `git pull`、没有 build、没有运行 `deploy_lowcost.sh`。
- 重启后 `web` healthz 返回 `{"status": "ok"}`，`web` 容器 healthy，`db / redis` healthy，`worker / beat` up。
- 2026-06-24 已部署 `add-qqbot-auto-push` 到 `main`，生产迁移 `stable.0010_qqpushdelivery` 已应用，`QQ_PUSH_ENABLED=true` 与 `QQ_PUSH_SCOPE=all_public` 已生效。
- 批量补推 126 篇存量公开文章时，`QQPushDelivery` 记录创建成功；NapCat / QQ 客户端返回 `EventChecker Failed ... 网络连接异常`，系统按 `send_failed` 记录并进入有限重试，未误标记成功。后续补推必须使用 `QQ_PUSH_MIN_INTERVAL_SECONDS` 或人工脚本限速。

### 自动推送上线步骤

1. 合入并部署 `add-qqbot-auto-push`。
2. 执行迁移，确认 `stable_qqpushdelivery` 表存在。
3. 确认 `QQ_PUSH_SCOPE=all_public` 和测试群 `PushTarget.is_active=true`。
4. 设置 `QQ_PUSH_ENABLED=true`。
5. 重启 `worker / beat`。
6. 发布或复用一篇公开文章触发自动推送，核对测试群消息、`QQPushDelivery` 和 worker 日志。

### 停用方式

停用自动推送：

```env
QQ_PUSH_ENABLED=false
```

停用 OneBot 网关：

```bash
cd /opt/umanewsbot
docker rm -f umanewsbot-onebot-1
```
