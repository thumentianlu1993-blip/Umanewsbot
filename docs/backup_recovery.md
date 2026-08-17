# 备份与恢复指南

## 1. 备份策略

### 标准模式（RDS）

- 主策略：RDS 自动备份 + PITR
- 补充策略：手动快照 `./deploy/backup_db.sh`

### 低成本模式（本机 PostgreSQL）

- 必做：每日备份并上传 OSS
- 建议命令：

```bash
BACKUP_TARGET=oss ./deploy/backup_db.sh
```

### 媒体（OSS）

- 建议开启 Bucket 版本控制
- 建议配置生命周期策略

## 2. 备份命令

脚本默认生成 PostgreSQL custom-format `.dump`，只有在归档非空、`pg_restore -l` 通过并设置为
`0600` 后才发布正式文件。低成本部署使用 Compose `db`，RDS 使用隔离 PostgreSQL client。

`.env` 或当前命令必须显式设置以下两个值，脚本不会按 checkout 名称或缺省 low-cost 模式猜测：

```bash
# 标准 RDS
COMPOSE_FILE=docker-compose.prod.yml
EXPECTED_COMPOSE_PROJECT=umanewsbot

# 低成本本机 PostgreSQL：COMPOSE_FILE 改为 docker-compose.prod.lowcost.yml，
# EXPECTED_COMPOSE_PROJECT 填当前 resident stack 的真实 project name。
```

low-cost 的 dump、TOC、restore 与 OSS one-off 均通过仓库 Compose wrapper 绑定该 project；两项任一
缺失或非法都会在数据库操作前失败。

本地备份：

```bash
./deploy/backup_db.sh
```

备份并上传 OSS：

```bash
BACKUP_TARGET=oss ./deploy/backup_db.sh
```

成功输出必须同时包含 `Backup created`、`Backup SHA-256`、`Backup TOC entries`，OSS 模式还必须包含
`OSS upload verified`。仅有本地文件或上传调用返回不代表远端恢复点成立；必须复核远端对象大小。

## 3. 恢复命令

从备份文件恢复：

```bash
./deploy/restore_db.sh backups/db/<file>.dump
```

历史 `.sql.gz` 仍兼容，但新备份统一使用 `.dump`。恢复会清理/覆盖数据库对象，只能在业务写入已停止、
备份 SHA 与 TOC 已核对、且取得精确生产授权后执行。

## 4. 恢复流程建议

1. 先暂停写入操作（避免脏数据）
2. 做一次当前快照备份（保底）
3. 恢复数据库
4. 重启服务
5. 验证后台、前台、任务链路

## 5. 恢复后验证

- 后台可登录
- 文章、术语、日志可读
- 前台文章和图片可显示
- 触发一篇文章翻译与推送测试
