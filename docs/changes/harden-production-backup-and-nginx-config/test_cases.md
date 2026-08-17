# 测试用例

1. low-cost backup 使用 Compose db，生成 `.dump`、mode 0600、TOC 有效且无临时文件。
2. pg_dump 失败时返回非零，backup 目录不留下正式或临时文件。
3. RDS backup 使用隔离 postgres client，命令日志不含密码。
4. caller 的 `BACKUP_TARGET=local` 覆盖 `.env` 中的 `oss`。
5. OSS 上传远端大小相同时成功，不同时非零失败。
6. OSS 上传使用受审应用镜像，不依赖宿主 Python/oss2。
7. low-cost/RDS custom archive 恢复走正确客户端与 fail-closed 参数。
8. lifecycle promotion 对 low-cost `.dump` 使用精确 Compose project 的 db 复核，对 RDS `.dump` 使用
   隔离 postgres client，禁止调用不存在的 db service。
9. `.env.example` 使用可解析的香港 OSS endpoint。
10. Nginx 包含 ACME、TLS/cert/HSTS、公开路由和 hipilot 410 合同。
11. 缺少显式 `COMPOSE_FILE` 时在任何 Docker 调用前失败；模板明确 RDS mode 与默认受审 project。
12. low-cost backup/restore 命令均携带精确 `--project-directory` 与 `--project-name`。
13. 被 release wrapper 直接调用的 backup/restore 脚本保持 executable mode。
