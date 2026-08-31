# 当前年度日期老化刷新

日期：2026-08-31

## 结论

target catalog 仍精确绑定 12,048 条 reviewed COMPLETE 目标与 `2026-08-29` 范围事实；下游执行日期推进到
`2026-08-31` 后，4 个 8 月 30 日目标已从 `not_due` 转为到期结果 gap。当前权威分区为：

- total：12,048；
- due：11,939；
- bulk 2005+：10,795；
- pre-2005 targeted：1,144；
- not_due：109。

变化赛事为 France de Meautry G3、Grand Prix de Deauville G2、Prix Quincey G3 与英国 Prestige G3。

## Artifact

- calendar audit manifest：`0044293b0cf8b26469c85159f63d18ab271715a155ee74c8fbb8d89e05483415`；
- non-held proposal：`560b5f8a09e481c69afb30dccdb59d5cbe4f5f1120fd17b8238bb13fa7aae28e`；
- coverage：`9f7378d932fa7ce2e2ef929c9917ad1043745fd3a57d0dd2c521cafef464ce55`；
- bulk readiness：`99f13cc80909ec2ad30b70288f0af9475bb0f115f57999872b43637823e1442a`；
- bulk plan manifest/plan：`39eb0ec0f1b98500ac6a11965e88ad08e8c9d32476666c0e656aa2aca79418e` /
  `657d2af9d2907a94afa9c37b897f95caabd8ad53d3ccf051b77bc801d7ff7e16`；
- occurrence manifest：`7d4303ac4d97030f7156e5737c0dbc10893dc0f4d845e20abf3ce295cb9a7f31`；
- completion audit v4：`3342772dd4a723ecc5cc4a6a52d02988bb952d75d0915cd9f0f1f62fdda5d13e`。

occurrence artifact 仍是 PREPARED：350 held、109 not_due、11,589 unaccounted；输入未批准。completion audit
仍为 `AUDITED_INCOMPLETE`，approved provider IDs=0，production/public 未审计。

## 执行影响

新 bulk plan 仍为 32 batches、88 region-year units、108 date ranges、21,708 GET ceiling。旧 G3 绑定旧完整
plan SHA，不能复用。新 ordinal-1 只生成 proposal
`ac2235ae9d01b43e0870d82daba4dda89cad1bbb86332aef58c41f94decb4402`，状态
已由 exact approval `4473b1164ad3caaf8b5733ff6c0d530d8f396b51a0e2731381cd0ff8c856bee9`
批准；仍没有 proof、claim、network 或 database write。

## 验证与生产边界

- 日期/coverage/occurrence/bulk 专项：36/36；
- 完整 runtime/research：587/587；
- candidate/identity/module/global/staging Django 链：106/106；
- Django check、migration check、py_compile、git diff check：通过；
- change test IDs：344/344 唯一。

event 956 后续仅为 selected France 2023 补充释放了真实关闭态窗口；该 release 不扩大到本 memo 的 bulk scope。
selected runner 已以 fresh proof 完成 5/5 seeds、19 GET、0 database writes，并恢复 exact PR133 运行态后释放原锁；
reference/TRA canonical registry 未写，`race_live=7543` 未消费。bulk ordinal 1 仍未生成 proof、claim 或请求。
