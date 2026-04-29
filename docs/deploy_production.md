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

---

## 4. HTTPS 证书

将证书放到：

- `deploy/certs/fullchain.pem`
- `deploy/certs/privkey.pem`

Nginx 会自动挂载并启用 HTTPS。

如果还没有正式域名，可先为公网 IP 生成一份临时自签证书做上线验证；浏览器会提示证书不受信任，但不影响功能验收。

---

## 5. 上线后验证

1. 服务状态

```bash
docker compose -f docker-compose.prod.yml ps
# 或
docker compose -f docker-compose.prod.lowcost.yml ps
```

2. 健康检查

```bash
curl -I https://your-domain/healthz/
```

3. 页面验证

- 前台：`https://your-domain/`
- 后台：`https://your-domain/admin/login/`
- Django Admin：`https://your-domain/django-admin/`

4. 任务验证

```bash
docker compose -f docker-compose.prod.lowcost.yml logs -f worker
docker compose -f docker-compose.prod.lowcost.yml logs -f beat
```

---

## 6. 备份建议

- 标准模式：RDS 自动备份 + `backup_db.sh` 额外快照
- 低成本模式：强烈建议每日定时执行：

```bash
BACKUP_TARGET=oss ./deploy/backup_db.sh
```
