# 生产上线检查清单

## A. 资源层

- [ ] ECS（香港）已创建并可 SSH
- [ ] OSS（香港）已创建并可读写
- [ ] 域名 A 记录已指向 ECS
- [ ] HTTPS 证书已放置（`fullchain.pem` / `privkey.pem`）

二选一：

- [ ] 标准模式：RDS PostgreSQL 已创建并放通
- [ ] 低成本模式：确认使用 `docker-compose.prod.lowcost.yml`

## B. 环境变量

- [ ] `.env` 已填写
- [ ] `DEBUG=false`
- [ ] `ALLOWED_HOSTS` 正确
- [ ] `CSRF_TRUSTED_ORIGINS` 正确
- [ ] `MEDIA_STORAGE_BACKEND=oss`
- [ ] `OSS_*` 完整
- [ ] 翻译 API Key 已配置
- [ ] OneBot 配置已配置（如使用）

## C. 部署验证

标准模式：

- [ ] `./deploy.sh` 成功

低成本模式：

- [ ] `./deploy_lowcost.sh` 成功

通用检查：

- [ ] `web/worker/beat/redis/nginx` 均为 `Up`
- [ ] `https://your-domain/healthz/` 为 200
- [ ] `/admin/login/` 可登录
- [ ] `/` 前台可访问

## D. 业务链路

- [ ] 抓取成功
- [ ] 自动翻译成功
- [ ] 编辑发布成功
- [ ] QQ 推送成功（或失败可见日志）

## E. 数据安全

- [ ] 能执行 `./deploy/backup_db.sh`
- [ ] 低成本模式已配置每日备份到 OSS
- [ ] 能执行 `./deploy/restore_db.sh <backup>`
- [ ] 回滚脚本可用

