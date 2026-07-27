# P0 官方出马页面 URL 定时发现发布报告

## 发布身份

- 发布时间：`2026-07-27`。
- PR：`#32`。
- 生产 revision：
  `cfba71518f1024d54cd5553b7f0bb35c780f5959`。
- 批准集成 HEAD：
  `6574871dcf84cbd6a7ac446b9b8db7e12601924f`。
- 批准 fingerprint：
  `20c044d87826358f351ba542716df8a1d36ed4c06475830af6c327577c3b64c8`。
- 批准 content hash：
  `5a2e80d72c47b8d39792128ab6c429d5deb731aa1fee32feb566f7b7a5a1bc7e`。
- 应用镜像：
  `sha256:a11d072d8a8fc9cc268db996bc916751cea51fe0b7a7cdfc16b715ab0f3e4bf7`。

## 恢复点

- `.env.backup.pre-p0-url-20260727T062445Z`，mode `0600`。
- `backups/db/pre-p0-url-20260727T062445Z.dump`，mode `0600`，
  `259806424` bytes。
- 数据库备份 SHA-256：
  `5a02d4b2e2da1f9040920e046bf4bff75790c9dc5ee4a9aed82390acfd894e76`。
- 容器内 `pg_restore -l` 通过。

## 关闭态验证

- `P0_RACECARD_URL_DISCOVERY_ENABLED=false`。
- 直接调用返回 `{"enabled": false}`。
- `TaskExecutionLog`：`0 -> 0`。
- 宿主持久化目录子项：`0 -> 0`。
- 未发 provider 请求、未写 generation。

## 启用状态

- worker/beat：
  `P0_RACECARD_URL_DISCOVERY_ENABLED=true`。
- Celery timezone：`Asia/Shanghai`。
- crontab：`30 6,18 * * *`。
- task：
  `stable.tasks.discover_p0_racecard_urls_task`。

## 两次受控运行

两次结果一致：

- `future_expected=6`
- `orphans=5`
- `listing_reachable=3`
- `found=0`
- `not_available=8`
- `blocked=6`
- `errors=2`

generation：

1. `d25176d9f07f960704caf13943f617a40e0a80a022557db9888e271791119ef9`
2. `5868715fb4406b552132adf4e7a24372dba72253d20b25196ffc1368b2ce68db`

`current` 指向第二代，generation verifier 通过。

## Provider 覆盖

- BHA：3 场，保存官方日期索引并明确标为“需人工确认”。
- Equibase：DMR/CNL 从生产香港主机连接超时；两场均为
  `source_error/error_without_previous`，未保存或猜测 URL。
- France Galop：身份不足，显示“暂无”。
- 美国 orphan：5 场缺少窗口时间/稳定 route 身份，显示“暂无”。
- JRA/HKJC/NAR：当前窗口没有可启用目标或仍受既定 provider contract 阻断。

当前结论是“任务已启用、BHA 可用、Equibase 生产网络降级”，不是全地区成功。每日两次调度
会继续按原 contract 低频重试 Equibase。

## 数据与公开影响

- 新增 `TaskExecutionLog=2`。
- 两次运行完整时间范围内以下模型的 `updated_at` 命中均为 `0`：
  `RaceEvent`、`RaceEventRunner`、`RaceEventResult`、`ExternalRaceEntry`、
  `ExternalRaceResult`。
- 未写赛事、出马、赛果或新闻业务表。
- 未启用 race-live、lifecycle、历史抓取、公共发布或 QQ。
- 文档仅保存在服务器
  `/opt/umanewsbot/runtime/upcoming_racecard_urls/current/latest.md`，未公开暴露。

## 健康与剩余风险

- Django check 通过。
- 回环与公网 healthz 通过。
- web/worker/beat 均使用同一新镜像，db/redis/nginx 正常运行。
- beat 重启补投了其他既有周期任务；验收快照默认队列为 `19`，未删除这些任务。
- 剩余风险为 Equibase 生产网络超时，以及审核记录的三个非阻塞 P2；后续修复需要新任务、
  测试、review 和发布授权。
