# 生产备份与 Nginx 配置收口规格

## 目标

1. `backup_db.sh` 在 low-cost Compose PostgreSQL 与 RDS 两种部署下都能生成真实、可校验、权限为
   `0600` 的 custom-format archive；失败不得留下可被误认成恢复点的正式文件。
2. `BACKUP_TARGET=oss` 必须使用已部署应用镜像中的 `oss2`，上传后以远端对象大小复核成功；endpoint
   或上传失败必须返回非零。
3. `restore_db.sh` 同时支持新的 `.dump` 与历史 `.sql.gz`，所有客户端命令均在正确网络边界内执行并
   `ON_ERROR_STOP` / `--exit-on-error`。
4. 仓库 Nginx 配置与当前生产已通过 `nginx -t` 的 HTTPS/ACME/retired-host 配置逐字一致。
5. 备份与恢复必须显式声明 `COMPOSE_FILE` 和实际 `EXPECTED_COMPOSE_PROJECT`；low-cost 的所有
   Compose 数据库与上传操作必须经受审 wrapper 绑定该 project，禁止按 checkout 目录名隐式选栈。

## 非目标

- 本变更不删除任何本地或 OSS 备份，不设置 OSS lifecycle policy。
- 本变更不执行数据库恢复，不启用 lifecycle enforce 或 race-live。
- 生产 endpoint 修改、首次 OSS 上传和 Nginx reload 只能在独立发布门禁内执行。
