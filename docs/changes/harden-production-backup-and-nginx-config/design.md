# 设计

## 备份

- low-cost：在现有 Compose `db` service 内执行 `pg_dump --format=custom` 与 `pg_restore -l`。
- RDS：使用隔离 `postgres:16` client 连接外部 endpoint；密码只通过环境传递，不进入命令行或日志。
- `COMPOSE_FILE` 不设默认值：`docker-compose.prod.yml` 明确表示 RDS，
  `docker-compose.prod.lowcost.yml` 明确表示 Compose PostgreSQL；`EXPECTED_COMPOSE_PROJECT` 同样必填。
  low-cost 的 dump/TOC/restore 与 OSS one-off 都经 `compose-wrapper.sh` 传入物理 project directory 和
  精确 project name，避免误连其他同名 service。
- 先写 `mktemp`、校验非空和 TOC，再以 `mv` 原子发布正式 `.dump`；trap 清理临时 archive/TOC。
- caller 显式 `BACKUP_TARGET` 优先于 `.env`，保证 release wrapper 可强制 local rollback snapshot。
- OSS 上传由 `docker compose run --rm --no-deps web` 执行，archive 只读挂载；`put_object` 后用
  `head_object.content_length` 与本地大小精确比较。

## 恢复

- `.dump` 先列 TOC，再以 `--clean --if-exists --exit-on-error --single-transaction` 恢复。
- 历史 `.sql.gz` 先 `gzip -t`，解压到临时文件，再以 `psql --single-transaction -v ON_ERROR_STOP=1`
  执行，避免管道前半段失败被吞掉。

## Lifecycle promotion 复核

- promotion 将本次受审 `COMPOSE_FILE` 与 `EXPECTED_COMPOSE_PROJECT` 显式传给备份脚本。
- low-cost archive 在同一 Compose project 的 `db` service 内二次 `pg_restore -l`；RDS archive 使用隔离
  `postgres:16` client 二次复核，不调用标准 RDS Compose 中不存在的 `db` service。

## Nginx

- 仓库文件采用当前生产挂载文件，SHA-256 固定为
  `a506e857d959529deb6cfbbe8712864031defddfb8583c628d64e50197748b9c`。
- 保留 HTTP ACME challenge、正式 Let's Encrypt TLS、HSTS 和静态/媒体/健康/代理路由；退休的
  `hipilot.umafans.run` 保持 `410`。
