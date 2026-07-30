# 生产部署指南

本文档提供两套部署方式：

1. 标准模式：`ECS + RDS PostgreSQL + OSS`
2. 低成本模式：`ECS + 本机 PostgreSQL + OSS`

---

## 1. 文件说明

- 标准模式：`docker-compose.prod.yml`
- 低成本模式：`docker-compose.prod.lowcost.yml`
- Nginx：`deploy/nginx/nginx.conf`
- Compose 兼容包装脚本：`deploy/docker/compose-wrapper.sh`
- 脚本：
  - `deploy.sh` / `deploy/deploy.sh`
  - `deploy_lowcost.sh` / `deploy/deploy_lowcost.sh`
  - `deploy/backup_db.sh`
  - `deploy/restore_db.sh`
  - `deploy/rollback.sh`
  - `deploy/rollback_lowcost.sh`
  - `deploy/manual_release.sh`（受保护的手工 release 入口）
  - `deploy/resume_stopped_release.sh`（受审的服务恢复入口）
  - `deploy/rollback_pre_single_owner.sh`（首次发布的 pre-contract 回滚兼容桥）

## 1.1 单一 release task 与部署锁（fix-single-migration-owner）

数据库迁移和静态文件收集只有一个所有者：容器内脚本
`deploy/docker/run-release-tasks.sh`。它由宿主受保护 wrapper
`deploy/run_release_tasks.sh` 通过 `compose run --rm --no-deps web` 恰好执行一次；
web 常驻入口 `deploy/docker/start-web.sh` 只做依赖等待、可选 `seed_admin` 和
Gunicorn，不再执行任何 schema/static 准备。操作者不得直接调用内部 wrapper；
正常部署/回滚/手工恢复分别走下面的顶层入口，它们共享同一个 host-local
排他部署锁（默认 `/tmp/umanews-deployment.lock`，可用 `DEPLOYMENT_LOCK_DIR` 覆盖）：

1. 任意时刻只有一个 deploy/rollback/manual release/resume/p0 closed-admission 能持有锁
   （action ∈ deploy、rollback、manual-release、pre-contract-rollback、p0-closed-admission、
   resume-release）；竞争失败者立即非零退出，且不会删除赢家持有的锁。
2. 锁内只保存 PID、动作、UTC 开始时间、Compose 文件和 owner token 的 SHA-256；
   原始 token 不落盘、不打印。
3. 遗留锁一律 fail closed，绝不按时间或 PID 自动清理；必须先人工确认没有任何
   部署/回滚进程存活，才能手工删除锁目录。
4. release task 失败（依赖等待、迁移或静态收集任一非零）时，web/worker/beat/nginx/
   race_live_worker 全部保持停止，不会自动启动任何服务。

---

## 2. 标准模式（RDS）

### 2.1 配置

`cp .env.example .env` 后，重点填：

- `POSTGRES_HOST=your-rds-endpoint...`
- `POSTGRES_PORT=5432`
- `MEDIA_STORAGE_BACKEND=oss`
- `OSS_*`
- `ALLOWED_HOSTS`、`CSRF_TRUSTED_ORIGINS`、`SITE_URL`
- 翻译与 OneBot 配置

### 2.2 启动

```bash
./deploy.sh
```

部署顺序固定为：`.env` 检查 -> 获取部署锁 -> historical runner preflight ->
`pull nginx` / `build web` -> 停 beat -> 排空全部 Celery worker（快照必须完整包含
冻结的普通 worker 与 race_live_worker 节点）-> 停 worker -> 停原本运行的
race_live_worker -> 停 web -> 单次 release task -> 启动 web 并有界等待 healthy ->
启动 worker/beat/nginx -> 仅按原始运行态恢复 race_live_worker。任一步失败时后续
步骤零执行。

注意：`HISTORICAL_RUNNER_INITIAL_INSTALL=true` 只表示已有健康 web/db/redis 环境上的
historical runner 首次纳管预检，**不是**全新站点（greenfield）安装能力；没有既有健康
web 时 deploy 会在任何迁移之前 fail closed。

### 2.3 既有环境手工恢复

移除 web 自动迁移后，`docker compose up web` 不再隐式准备 schema。需要手工执行
release task（例如 collectstatic 失败后单独重跑）时：

```bash
COMPOSE_FILE=docker-compose.prod.yml ./deploy/manual_release.sh
# 低成本模式：COMPOSE_FILE=docker-compose.prod.lowcost.yml ./deploy/manual_release.sh
```

该入口自行获取同一部署锁，并且只有在 web、worker、beat、race_live_worker 四类应用
服务全部可验证为非运行（running、restarting 或状态不可读都会 fail closed）时才执行
一次 release task；完成后不启动任何服务。

只需恢复已停止的服务时，使用受审恢复入口：

```bash
COMPOSE_FILE=docker-compose.prod.yml ./deploy/resume_stopped_release.sh
# 低成本模式：COMPOSE_FILE=docker-compose.prod.lowcost.yml ./deploy/resume_stopped_release.sh
```

resume 同样先获取部署锁并核对四类应用服务全部停止，再按 web -> healthy ->
worker/beat/nginx 顺序启动，race_live_worker 只按可信冻结意图（六字段 mode-600 绑定文件）
恢复；它绝不执行 one-shot release task，意图文件不可信时只告警跳过 race-live，核心服务
照恢复，遗留意图文件只能人工核对后删除。

---

## 3. 低成本模式（本机 PostgreSQL）

适用场景：预算敏感、单机部署、可接受单点风险。

### 3.1 配置

`cp .env.example .env` 后，至少填：

- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `MEDIA_STORAGE_BACKEND=oss`
- `OSS_*`
- `ALLOWED_HOSTS`、`CSRF_TRUSTED_ORIGINS`、`SITE_URL`
- 翻译与 OneBot 配置

说明：低成本 compose 会自动把 `POSTGRES_HOST` 覆盖为 `db`，连接容器内置 PostgreSQL。

### 3.2 启动

```bash
./deploy_lowcost.sh
```

编排顺序、部署锁、手工恢复与标准模式一致，仅 Compose 文件为
`docker-compose.prod.lowcost.yml`（手工恢复时
`COMPOSE_FILE=docker-compose.prod.lowcost.yml ./deploy/manual_release.sh`）。

---

## 4. HTTP 域名接入

当你先做 HTTP 域名接入时：

- `ALLOWED_HOSTS` 填域名、`www` 子域名和必要的回环地址
- `CSRF_TRUSTED_ORIGINS` 同时预留 `http://` 与 `https://` 版本
- `SITE_URL` 先使用 `http://your-domain.com`
- `SECURE_SSL_REDIRECT=false`
- `SESSION_COOKIE_SECURE=false`
- `CSRF_COOKIE_SECURE=false`
- `SECURE_HSTS_SECONDS=0`

Nginx 当前会直接在 `80` 端口提供服务，不强制跳转 HTTPS。

---

## 5. HTTPS 证书

将证书放到：

- `deploy/certs/fullchain.pem`
- `deploy/certs/privkey.pem`

Nginx 会自动挂载并启用 HTTPS。

如果还没有正式域名，可先为公网 IP 生成一份临时自签证书做上线验证；浏览器会提示证书不受信任，但不影响功能验收。

---

## 6. 上线后验证

1. 服务状态

```bash
docker compose -f docker-compose.prod.yml ps
# 或
docker compose -f docker-compose.prod.lowcost.yml ps
```

2. 健康检查

```bash
curl -I http://your-domain/healthz/
```

3. 页面验证

- 前台：`http://your-domain/`
- 后台：`http://your-domain/admin/login/`
- Django Admin：`http://your-domain/django-admin/`

4. 任务验证

```bash
docker compose -f docker-compose.prod.lowcost.yml logs -f worker
docker compose -f docker-compose.prod.lowcost.yml logs -f beat
```

---

## 7. 备份建议

- 标准模式：RDS 自动备份 + `backup_db.sh` 额外快照
- 低成本模式：强烈建议每日定时执行：

```bash
BACKUP_TARGET=oss ./deploy/backup_db.sh
```
