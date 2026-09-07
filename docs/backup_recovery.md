# 备份与恢复指南

0078 发布的专用恢复点由 `deploy/release_0078.py` 调用下述既有备份脚本生成；
`BACKUP_TARGET=local` 与本次 `BACKUP_DIR` 不会被 `.env` 覆盖。每个新 release 使用新目录，
同一 release 的续跑复用原 SHA 绑定，不能拿另一发布的备份补签证明。

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
3. 将精确备份恢复到新空数据库/实例，使用与该 schema 兼容的镜像只读核验
4. 核验通过后按发布包切换连接并恢复服务
5. 验证后台、前台、任务链路

0078/0077 的逆向 migration 均不能代替备份恢复。旧0077 dump 对较新的0078库执行
`--clean`，可能保留 dump 中不存在的新增对象，不能因此认定回到了 exact0077。
跨世代恢复使用新空目标；不增加自动删库流程。恢复会丢失恢复点之后的业务变化，
精确恢复包必须说明该时间窗口。

`pg_restore --list` 只能证明 TOC 可读。开发演练需使用合成数据实际 dump/restore，核对
recorder、catalog、非空 `profile_snapshot`、关键行及关联；不下载生产 dump 作为测试输入。

## 5. 恢复后验证

- 后台可登录
- 文章、术语、日志可读
- 前台文章和图片可显示
- 翻译和推送链路按根 `AGENTS.md` 对应的精确发布包验证
