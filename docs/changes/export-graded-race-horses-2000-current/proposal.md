# 四地区分级赛参赛马与完整资料回填提案

## 背景

现有系统已具备英国、法国、爱尔兰、美国分级赛目标总账、The Racing API（TRA）访问、External staging、
身份审核与 P0 资料发布的分层能力，但尚未把 2000 年至当前范围内的全部实际参赛马稳定 ID、完整资料、
血统和生涯履历闭合到数据库。历史实现曾按年度范围查询 TRA `/v1/results`，与 provider 当前明确建议的
“每次查询一个自然日”不一致，也会放大分页漂移和恢复成本。

## 目标

- 冻结并守恒四地区赛事范围：2000–2020 全部 G1；2021–当前全部 G1/G2/G3，flat 与 jumps 均包含。
- 2005+ 按地区 × 自然日调用 TRA results，恢复目标赛事及 actual starters；2000–2004 以受审 winner anchor
  走 targeted horse 路径。
- 取得全部唯一 `hrs_*` 后零 search 拉取 profile、二代血统和完整 career，并保留逐字段来源与 gap。
- 先写 External staging/candidate，经过跨语言身份与模块审核后再事务化写入 canonical 数据库。
- 以 target、occurrence、runner、provider horse、identity、profile、career、receipt 和公开页全链路守恒证明完成。

## 范围

- 地区：GB、FR、IRE、USA。
- 年份与等级：2000–2020 G1；2021–执行年度 G1/G2/G3。
- 参赛口径：正式赛果中的 actual starters；withdrawn、NR、NP 不计为出赛。
- 数据入口：TRA `/v1/results`、`/v1/horses/{horse_id}/pro`、`/v1/horses/{horse_id}/results`；
  `/v1/horses/search` 只用于无 stable ID 的受审 targeted seed。

## 非目标

- 不把 TRA 返回反推为赛事应到分母。
- 不以马名单键合并日文、中文、英文或罗马字名称。
- 不自动批准 identity/module review，不自动公开页面，不触发 QQ、邮件或 `race_live`。
- 不把 HTTP 200、任务 SUCCESS、staging 行存在或单批 COMPLETE 当作全量完成。

## 关键设计

1. 2005+ 固定为一个地区、一个自然日一个 range；批次只负责聚合连续日期并保留逐页 checkpoint。
2. 所有网络批次绑定 target、plan、OpenAPI fingerprint、账号 scope、request ceiling、proof 与 G3 approval SHA。
3. safe-stop/resume 只从已验证的下一页继续，累计请求不丢失；429、entitlement、schema 或 proof 漂移均停止新请求。
4. 全局 merge 的 bulk source 数由冻结 batch plan 决定，不写死；本次 2026-09-01 计划为 88 bulk +
   65 pre-2005 targeted = 153 个 source stable ledgers。
5. provider ID 是身份主键；JRA/JBIS/HKJC 本地名与海外英文名只通过受审 authority crosswalk、DOB/sex/sire/dam
   等强证据关联，名称仅作召回。

## 验收

- 12,048 target 范围守恒，当前执行日 11,939 due、109 not_due。
- 所有已举行 target 均有唯一终态 occurrence，actual starters 与 provider race payload 守恒。
- 全部唯一 `hrs_*` 均有完整、可重放的 profile/pedigree/career artifact 和唯一身份终态。
- staging、identity、module、canonical apply、public verifier 均有 exact-SHA receipt；全量重放零业务写。
- 最终 global audit 才可发布 `AUDITED_COMPLETE`；任一 unresolved provider/source/identity gap 均保持 incomplete。

## 风险与缓解

- provider 限速或 entitlement：账号级 limiter、单并发、4 req/s、逐批 ceiling 与 safe-stop。
- 长批次 proof 过期：短批次、逐页 checkpoint、fresh proof resume，不复用旧授权。
- 跨语言重复：stable provider ID + authority crosswalk + 强生物信息 + 人工审核。
- 生产资源与赛事链竞争：shared deployment lock、fail-closed 窗口、队列只读守恒、完整恢复后释放锁。
- 当前年度继续产生赛事：执行日期单调推进并重建下游 SHA；未来 target 保留 `not_due`，赛日后自动回到结果缺口。
