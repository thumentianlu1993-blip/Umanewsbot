# Release B 生产数据 apply 报告

## 结果

2026-08-09，Release B 对 production revision
`75294a4dea51538962741ec6c0835dc3090558ff` 完成精确 manifest-bound apply 和独立 verifier。
receipt `#1` 状态为 `verified`，maintenance 已退出，服务已恢复。

## 精确绑定

- reviewed manifest：`89387fab38f4c2a435c3b009802907a6b9710547354b38f91c3057546f41e96b`
- action scope：`d7052d4392c027522ffde7c14955c98a2bc4ebfa99714c8681237c0ab65900bd`
- approval：`f5df52d3320aae1c611f652fbcd5e41a438c73b43be346f8ed6fca5f4de55ecf`
- maintenance evidence：`840d87a8c5319fb09047d702fb4592a82a4c956a2b1ee582b11a525a8dfdc661`

## 恢复与验证证据

- 写前备份：
  `/opt/umanewsbot/backups/db/pre-release-b-data-apply-path-staging-20260808T172850Z.dump`
- 备份：`413103571` bytes、mode `0600`、TOC `1308`
- 备份 SHA-256：`af6aa018da8a14311de4ad86801e729af1c7b9fe40bcb1adca050c0d868a832a`
- rollback SHA-256：`acb1fc2b2dee46f979517d496be1f81169c27fa56a4be6042ae8e97b7be3342c`
- verifier：`errors=[]`
- verifier result SHA-256：`f71c2bc93dc5ff93a7b12ef81518958e9c79ba5ecf65b17e39e30927ebadf0ac`
- manifest-bound active canonical links：`12`

首次 apply 调用因 one-shot 进程缺少显式 write flag 在任何写入前 fail closed；只对精确 apply
进程设置 `HISTORICAL_RACE_BACKFILL_ENABLED=true` 后成功，全局 `.env` 和常驻 flags 未打开。
最终 active maintenance gate 为零，Django check、worker/beat 与内外 HTTP healthz 均通过。
域名 443 当前拒绝连接，因此本报告不声称 HTTPS 健康。
