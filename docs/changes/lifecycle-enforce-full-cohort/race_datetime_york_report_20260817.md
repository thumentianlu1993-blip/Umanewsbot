# York 未来赛事时间补齐与 lifecycle 只读 census 报告

## 结论

- 生产 `2026-08-17` 向后 30 天共有 `94` 场 published/scheduled 赛事，执行前均缺少
  `race_datetime`。本批只选取 York Racecourse 官方已明确公布开赛时间的 8 场赛事，不猜测其他地区。
- event `946–953` 已写入 `race_datetime` 与 `local_start_time`，共 `16` 项字段更新；同时新增
  `16` 条字段权威记录、`16` 条字段变更审计和 `1` 条操作日志。赛事仍为 `published/scheduled`。
- 写后 8 个公开详情页、赛事日历、内外 `/healthz/` 均返回 `200`，详情页显示的英国当地时间与官方
  Order of Runnings 一致。
- lifecycle 仍为 `false/off`，race-live scheduler/monitor 仍为 `false`，没有生成 control、registry、
  membership 或 lifecycle transition。

## 冻结输入

- manifest：`artifacts/race-datetime-20260817-york/manifest.json`
- manifest SHA-256：`0b89c6c9082174190a0b121410b0da5e4bd3bd680ea6f8339db9b7b37e3ef24a`
- 官方来源：`https://www.yorkracecourse.co.uk/order-of-runnings.html`
- 官方 HTML SHA-256：`3c37c151bc24dd5724fe3687945c6781966104c632359917051af90a6eaa7c8e`
- 官方 fixture 页面 HTML SHA-256：`476cc5ac8a156e5a9609144b9b930a3ad8a83d1f89bfb37ee01033e5e0050610`
- 执行脚本 SHA-256：`8d6c9aad192cfee97de9e1c2cdb8fc3ceb738fc2f2c8e5bd2211d08992ec70e5`
- 生产证据目录：`/opt/umanews-ops-race-datetime-20260816T180705Z`

## 写入结果

| event | 赛事 | 当地时间（Europe/London） | UTC |
| --- | --- | --- | --- |
| 946 | Juddmonte International Stakes | 2026-08-19 15:35 | 2026-08-19 14:35Z |
| 947 | Great Voltigeur Stakes | 2026-08-19 15:00 | 2026-08-19 14:00Z |
| 948 | Yorkshire Oaks | 2026-08-20 15:35 | 2026-08-20 14:35Z |
| 949 | Lowther Stakes | 2026-08-20 13:50 | 2026-08-20 12:50Z |
| 950 | Nunthorpe Stakes | 2026-08-21 15:35 | 2026-08-21 14:35Z |
| 951 | Lonsdale Cup Stakes | 2026-08-21 14:25 | 2026-08-21 13:25Z |
| 952 | Gimcrack Stakes | 2026-08-21 15:00 | 2026-08-21 14:00Z |
| 953 | City of York Stakes | 2026-08-22 15:00 | 2026-08-22 14:00Z |

写前 custom-format 备份为
`/opt/umanews-ops-race-datetime-20260816T180705Z/pre-race-datetime.dump`，大小
`445791728` bytes、mode `0600`、TOC `1332`、SHA-256
`62770ed9f9d8c9c984e660461f733f2cd7949eccf1774f77cca7b144daa19111`。首次宿主校验因缺少可用
`pg_restore` 中止且数据库零写；随后只修正证据校验方式，使用数据库容器对同一 archive 校验通过，再在
重新取得共享锁后完成唯一一次 apply 与 verify。

## 只读 lifecycle census

- scope：`datetime_7d_canary`，limit `20`，production revision
  `93cfd240b9ba7e95caf79bf54e9c6d089885f11c`，generation `1`。
- 输出：`status=enrollment_required / inspected=9867 / included=8 / required=8 / ready=8 /
  blocked_us=0 / batches=1`。
- included IDs 与唯一 enrollment batch 均为 `946,947,948,949,950,951,952,953`。
- census SHA-256：`85979e3176b83d3787d864c4e592f59f538b72f5d25ed52152c105fd06043518`。
- enrollment plan SHA-256：`78885feea058fb828b4862af244290618c5da09105c33837fdf7aa491cc8ef1a`。
- lifecycle 四表前后指纹均为
  `28c5189900ac92d62a0dfd455911d2d9faba4e16814f9c5e83e631190e076b82`；计数保持
  `control=18 / transition=22 / registry=0 / membership=0`。

本报告只证明 8 场可进入 enrollment 准备，不构成 apply enrollment、promotion、activation、enforce
或 race-live 授权。
