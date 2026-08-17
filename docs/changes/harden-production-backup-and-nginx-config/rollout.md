# 发布与回滚

## 发布顺序

1. 锁定 merge SHA、image、release dir；确认 lifecycle `false/off`、race-live 关闭。
2. 部署代码但不修改数据库 schema；Django check、migration plan 和服务健康通过。
3. 备份 canonical/active `.env`，显式写入当前部署的 `COMPOSE_FILE` 与
   `EXPECTED_COMPOSE_PROJECT`，并把 `OSS_ENDPOINT` 从不可解析旧值改为
   `https://oss-cn-hongkong.aliyuncs.com`；不得输出凭据。
4. 执行 `BACKUP_TARGET=local ./deploy/backup_db.sh`，验证 `.dump` 非空、0600、TOC、SHA。
5. 执行一次 `BACKUP_TARGET=oss ./deploy/backup_db.sh`，要求本地 archive 成功、OSS upload verified、
   bucket 中对象大小一致；失败不清理本地恢复点。
6. 对 Nginx mounted config 先做备份，核对 candidate SHA，执行 `nginx -t` 后仅 smooth reload。

## 回滚

- 代码/镜像按现有 release rollback；恢复 `.env` 备份后重建受影响应用服务。
- Nginx 配置恢复发布前备份，`nginx -t` 通过后平滑 reload。
- 已生成的有效 `.dump` 与已上传 OSS 对象保留，不因代码回滚删除。
- 本变更无 migration；禁止以数据库 restore 作为普通代码回滚步骤。

## 停止条件

- archive 为空、TOC 无效、SHA/权限异常；
- Compose mode/project 缺失，或 resident service 的 Compose project 与声明值不一致；
- OSS endpoint 不可解析、上传异常或远端大小不一致；
- Nginx syntax 失败、证书路径缺失或任一 healthz 非 200；
- lifecycle/race-live 开关发生非预期变化；
- 发布锁、revision、image 或 release dir 不一致。
