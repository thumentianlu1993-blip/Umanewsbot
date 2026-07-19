# event 924 暂定赛果单赛事公开灰度发布报告

## 1. 结论

event `924` 已按最新成功 review 后取得的精确授权发布单赛事暂定赛果公开灰度，但生产
验收和 evidence closure 尚未完成。

- 公开范围只有 event `924`；
- `RACE_LIVE_SCHEDULER_ENABLED=false`；
- 未 claim、dispatch 或扩展其他赛事；
- promotion 前 BHA 观察与暂定赛果得到 `match`，但缺少 promotion 后 15 分钟内的新
  浏览器探测证据；
- 页面保持“暂定赛果”，未误标 `official_result`；
- kill switch 只完成 disable dry-run，未实际隐藏、验证和 restore。

## 2. 冻结版本

- approved parent：`353464c76c63d1e43043ccbefe0ebc88274b0888`
- approved content hash：
  `42c299cbde00f384a17b35095dc00a4654c9264ac99a24625b255cd080be3c06`
- approved fingerprint：
  `73a8356d1a79abba35cd652c5c90a5ffff8b8474b33a807c16d135f4367c9741`
- release commit：`91cf50ad677a1b8c9b253528c9db98481fd1031a`
- production image：
  `sha256:700ea78698fb67de602fb7e5447b997610e24e64de29df4591e4bb9e476087ef`

授权后 fingerprint 与 review 基线逐字节一致；显式 staging 后 index content hash 仍与
approved content hash 一致。release commit 已快进 `origin/main`，生产 checkout 与四个
app service 的 OCI revision 均为该提交。

## 3. 恢复点与部署

- 数据库备份：
  `/opt/umanewsbot/backups/db/pre-event924-provisional-public-20260719T040646Z.dump`
- bytes：`202,483,514`
- SHA-256：`a76c9d4788b36af08f64f4a9eddc90bc0a4ef4ecd239508bb5e40abffbe9e5be`
- 权限：`root:root 0600`
- `pg_restore -l`：通过
- 旧镜像 tag：`umanewsbot:rollback-pre-event924-ebab4aa8-20260719T041339Z`

`stable.0046_race_live_manual_verification_contract` 已应用。Django check、migration
drift、static collection、web health 和镜像 revision 均通过。

等待 SMTP 配置期间第一次恢复 Beat 时，Compose 因依赖配置重建了 db 容器；数据库持久卷
保持，容器恢复 healthy，promotion dry-run 在其后再次通过，未执行 restore。

## 4. SMTP 与 BHA preflight

QQ SMTP 使用 `smtp.qq.com:465 / SSL`，发件人与报警目标均为
`754652181@qq.com`。授权码只存在于被 Git 忽略的 `0600` 私密文件和生产 `.env`，
未进入日志或本文档。一次性新容器真实投递返回：

```text
sent=1 / recipient_count=1 / smtp_ssl=true / smtp_tls=false
```

BHA 由 release operator 在 promotion 前使用正常浏览器人工访问。Results、Newbury
fixture、`3:02pm` Hackwood Stakes 结果和 terms 页面均可用；只读取 objective
marker/positions，未调用页面后端 API、脚本抓取或批量下载。

## 5. Publication bundle

bundle：
`/opt/umanewsbot/runtime/race_live_publications/event924-public-91cf50ad-20260719T042103Z`

| artifact | SHA-256 |
| --- | --- |
| `promotion.manifest.json` | `2fedb9d381b275fb3dcc6e30c848a59c024da4dca0ec2227efb13925bceec3ba` |
| `disable.manifest.json` | `d441e0a1f134847abd4ebf3cf39c55c41be46d587723528e98958faa30014949` |
| `restore.manifest.json` | `cf96afb6363ed7621c7a153234b075e8708b544907956ca1745503739065cf6c` |
| `report.json` | `a582ec8782931f49c296e42a735a3a6f64e8bf4f02d35d32a35f44fe92e1966a` |

目录为 `0700`，文件均为 `0600`，没有 symlink；report 只包含 event `[924]`、release
commit 和三段 transition，`network_request_count=0`。

## 6. Promotion

promotion 依次执行 dry-run、apply、verify：

```text
ok=true
event_ids=[924]
transition=promote_shadow
network_request_count=0
```

数据库 commit time 为 `2026-07-19T04:37:17.201536Z`。终态：

- event `924`：`finished`，`result_confirmed_at=null`
- revision `2`：`provisional`，published，`official_confirmed_at=null`
- policies：global / UK / TRA / event 924 均为 `provisional_public v2`
- allowlist：仅 event `924`、enabled、`provisional_public v2`
- publication：`1`
- legacy results：`7`
- tracking：disabled，next poll null，active claim empty
- claim generation：`19`
- provider last attempt/success/hash/failure/stale：保持 shadow pre-state
- scheduler：false

## 7. BHA 首次人工复核

- 私有截图 SHA-256：
  `77b77a03a7c8c640db69db7f4d84965aad91b01bba243613eaa49773bd55a480`
- observed at：`2026-07-19T04:19:39Z`
- receipt SHA-256：
  `955ac30b6e345b5ec9226e0439b14df65bba515e39fd4cf29544402387823673`
- marker：`official_result`
- comparison：`match`
- incident：ID `1`，`resolved`
- resolved at：`2026-07-19T04:40:32.495902Z`
- due at：`2026-07-19T04:52:17.201536Z`

receipt dry-run、apply 和 replay dry-run 均 `ok=true`、`network_request_count=0`；
match 路线没有通知副作用。新增 official observation 和 marker evidence 各 `1`，
OperationLog `1`；没有把 provisional revision 改成 official。

截图 observed at `04:19:39Z`，早于 promotion commit `04:37:17.201536Z` 约 17 分
38 秒。`04:40:32.495902Z` 是该旧截图 receipt 的应用时间，不是 promotion 后的新
浏览器探测。因此，虽然数据库 incident 已 resolved，当前证据仍不能证明
“promotion commit 后 15 分钟内完成首次 manual probe”，该 SLA closure 未完成。

## 8. 页面与 kill switch

HTTP 详情与日历均返回 200。浏览器验收确认：

- “冠军 · 暂定”
- “暂定赛果”
- “尚待官方来源复核”
- 1–7 顺序与 revision/BHA 一致
- trainer/time/margin 缺失时显示 `-`
- 不显示“赛果已确认”
- 日历只对 event `924` 显示相同前五摘要

disable manifest 默认 dry-run 返回 `ok=true / event_ids=[924] /
network_request_count=0`。没有执行 disable apply、验证详情/日历隐藏或 restore，因此
不能把 dry-run 记为完整 kill-switch 演练；该验收未完成，当前灰度继续公开。

## 9. 收口状态

- app image/revision：四个 service 一致
- `/healthz/`：200
- scheduler：false
- tracking row universe：`[924]`
- enabled allowlist universe：`[924]`
- race-live queue：0
- HostBudget：failures `0`、circuit closed、lock version `22`
- historical runner：`migration_safe`
- historical enabled/network：false / false
- 可用磁盘：约 `5.2 GiB`

Beat 已恢复；普通新闻任务可以继续运行。当前没有待执行的 event 924 poll、claim、official
promotion 或范围扩展操作。发布已经生效，但 BHA promotion 后 15 分钟探测证据与完整
kill-switch 演练两项仍缺失，因此本报告只记录当前生产事实，不宣告 evidence closure
完成。
