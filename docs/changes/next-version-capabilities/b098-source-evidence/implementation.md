# B098：私有来源 publication 回执

2026-10-09；基于主线 `275e98592f968e1586b76727e9a93927c8a87f6f`，仅 B097 已审核范围。
真实 RED 候选 `6eb44b73bbb0fddc8acb25056abecc04eba7eedf` 的两个方法已由 ROOT 在实际
PostgreSQL/Django 执行，三个 DB verified 子场景及消费者共四条缺 publication 的 FAIL，0 ERROR/skip；
原 R 回执 `ACCEPTED_ACTUAL_EXACT2_PUBLICATION_RED`，报告提交 `164320393f6ede79a69b5e5770357b81e70abc33`。
本候选实现与新增测试已完成静态检查；实际 GREEN、直接回归及原 R 代码审核待执行。

## 实现合同

- `initialize_read_budget(receipt_version=2)` 显式建立新离线 root；默认仍 v1，既有 root 不可升版。
  有限表绑定 workflow/query/result v2 与固定 job/origin/step v2；混合或未知版本拒绝。
  logical step、1 read/2 request/2 quality round/600 秒及原控制 codec/schema 均保留。
- 单条材料 SELECT 返回 source/excerpt 与 DB `published_at`、nullable verified、受限 evidence。
  `read_at` 是实际读时刻，不替代发布时间；DB 标记只忠实透传，不新增来源认证。
- JSON 在 SQL 使用 `Substr(Cast(... AS text),1,4097)`，再以 UTF-8 4096 bytes 校验。
  空对象标 `empty`，完整允许对象标 `projected`。没有截断后声称完整的结果。
- evidence 仅接受最多 8 个键的原生平面 dict：`source/method/source_url/timezone/raw/previous_published_at`
  各为最多 512 字符且 1024 UTF-8 bytes 的字符串；`repair_run_id` 为原生非负 int64；
  `verified` 为 bool/null。未知键、嵌套/数组、异常类型、重复键/坏 JSON、超限均拒绝。
  字符串和 URL 仅作为材料，不取 URL，不执行指令，不授予读或模型权限。
- 原 `_finish_step` 写入真实 step UUID 和 canonical result SHA；publication 参与该 SHA，
  已完成结果恢复还核验字段、类型、实际 UUID、身份、读时刻、哈希、权限和期限。
  拒绝后保留已提交 read slot/inflight，下一次为 unknown，不退款、不重新读取或启动 provider。
- 新注册消费者继续绑定真实 read UUID/SHA 到 progress、checkpoint provenance 与 final。
  read-completed 恢复保留原 publication/read_at/hash；checkpoint_saved 免费 apply 与 final 重投
  不增加 read/request，即使实时 publication 已变化。model_started unknown 不重新发送。

## 前置锁查询的有限修复

ROOT 明确授权 `translation_recovery._locked_translation_claim` 新增默认 False 的窄参数
`defer_publication_evidence`，仅两个私有 v2 调用开启。登记、claimed→executing、读槽 admission/permit/finish、
模型授权、checkpoint/final、完成态重投均经过这两条调用链；不跳过原 parent→readonly root→Article→Run
锁序、claim/source/permission/deadline 检查。返回 Article 的源 hash、实体解析、provider 和最终保存
均不访问该 deferred 字段；Django 保存只更新已加载字段。真实 CaptureQueriesContext 测试要求
登记→消费→完成重投期间唯一带 evidence 的 SELECT 为 SQL 限长的材料 SELECT。

人工重试 admin/原普通 selector 的建立阶段发生于显式 v2 root/登记前，沿原 v1 普通合同；
本切片不扩展普通生产入口，不改 models、迁移、Celery、来源认证或外部权限。

## 验证与限制

两条实际 RED 方法以及三个直接测试模块的既有全部测试方法字节保持。
新增方法覆盖三态、v1 精确字段/默认/拒绝升级、SQL 投影和惰性前置读取、坏证据及 UTF-8/总量/截断边界、
实际 read/checkpoint/final 免费复用、伪 UUID/重哈希坏结构、unknown/revoke/expiry/source/version、
v2 reported-token stop 的正常对照、停止、unknown 重投与免费 checkpoint apply。

实际测试由 ROOT 分配原固定 runner 资源窗口；静态 codec 检查不计实际 ORM GREEN。
恢复测试为 fresh scoped invocation，未声称跨进程重启证明或完整 M02/M03 验收。
无 push/PR、合并、发布、生产操作、真实 SDK、付费调用或扩抓。
