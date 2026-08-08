# 设计

## 根因

`_duplicate_identity_sha256()` 把完整 `event.source_refs` SHA 放进赛事核心身份。生产 12 对记录
指向相同 HKJC 官方结果 URL、相同缓存内容、相同客观赛事字段和 runner/result，但分别来自相邻
TJCIS season catalog，因 manifest、season label 和采集 provenance 不同而产生不同身份 SHA。

## 最小实现

新增纯读取 helper `_official_result_identity(source_refs)`：仅从嵌套的受审官方结果记录返回
`source_provider + url + content_sha256`。满足该合同后，duplicate digest 使用官方结果身份、客观赛事字段、
runner 和 result；不满足时继续使用赛事名和完整 `source_refs` SHA。

完整 `source_refs` 仍由 `_event_snapshot()` 哈希，并继续参与 `series_precondition_sha256`。因此 catalog
provenance 发生变化仍会使 census/overlay 漂移失败，只是不再被误认为另一场赛事。

## 安全边界

- 单独出现 `result_url` 或自称 `official` 不可信；必须匹配唯一 `approved_detail_sources` 行及内容 SHA。
- URL 复用仍不能单独合并：客观字段、runner、result 任一不同都会得到不同摘要。
- 旧 census 的 code identity 与 precondition 不匹配，必须部署后重新生成。
- 本变更不需要 schema migration；回滚为部署上一代码镜像，尚未 apply 数据时零数据回滚。

## 生产证据

只读复核的 12/12 对均满足唯一受审官方结果身份，且 provider、URL、缓存内容 SHA、runner/result
逐对一致。`1871/2123` 仅展示名存在赞助商后缀差异，其余客观字段一致。当前没有需要用户判断的
模糊赛事；survivor、target、path 和 edition 的最终 overlay 仍必须由新 census 逐项审核。
