# Release B 官方赛事身份最小修复

## 目标

解除生产 v2 census 中 12 组香港同赛记录被 TJCIS season catalog provenance 阻断的问题，
同时保留来源审计和缺少可靠官方身份时的严格拒绝行为。

## Requirements

### Requirement：只有受审官方结果证据可以替代完整来源摘要

当 duplicate boundary 的 event 同时具备以下证据时，等价摘要必须使用该官方结果身份：

- `detail_discovery.urls.result_url` 是无凭据、无 fragment 的 HTTPS URL；
- `source_authority=official`；
- `source_provider` 非空；
- `approved_detail_sources` 中恰好一条记录与 provider、URL、official authority 精确匹配；
- 该受审记录具有合法 64 位十六进制内容 SHA。

官方结果身份由 provider、URL 和内容 SHA 组成。赛事客观字段、runner 和 result 仍必须一致；
赛事展示名与 catalog manifest/season label 不参与这一分支的同赛判断。

### Requirement：没有受审官方结果证据时保持原有 fail-closed

任一官方结果条件不满足时，等价摘要继续包含规范化赛事名和完整 `source_refs` SHA。
不同来源记录不得因为名称或日期相似而自动合并。

### Requirement：完整 provenance 继续受审计和漂移保护

`event.source_refs` 不得改写、删除或迁移。完整 `source_refs` SHA 继续进入 event snapshot、
series precondition 和不可变审核 artifact；本变更只缩小 duplicate equivalence digest 的身份字段。

## 非目标

- 不新增模型、数据库 migration、配置或 feature flag；
- 不改变采集、解析、runner/result、公开页面或 full_network workflow；
- 不自动批准旧 census、旧 overlay 或旧 manifest；
- 不放宽缺少官方结果证据的赛事。
