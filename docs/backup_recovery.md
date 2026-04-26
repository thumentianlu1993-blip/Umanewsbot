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

本地备份：

```bash
./deploy/backup_db.sh
```

备份并上传 OSS：

```bash
BACKUP_TARGET=oss ./deploy/backup_db.sh
```

## 3. 恢复命令

从备份文件恢复：

```bash
./deploy/restore_db.sh backups/db/<file>.sql.gz
```

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

