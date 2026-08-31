# 四地区样本与 313 个冠军锚点批次计划

状态：`PROPOSED_NOT_APPROVED`。本文件记录离线准备结果，不授权调用 The Racing API、写入 External
staging/canonical/production 数据库、发布页面或发送通知。

## 1. 313 个 reviewed winner-anchor 批次计划

- artifact root：
  `/Users/mentianlu/.codex/umanews-targeted-batch-plan-313-20260829.ESBLjZ`
- manifest SHA-256：
  `de9f321784f927ac1ca76ac7e9f504b79afa93a9590db546dc1dc0208655c247`
- batch plan SHA-256：
  `88c002273c837e8f4373b209d7c59f2efaa1dbfc6e790e16f0c335c62cf3653d`
- 输入 seed manifest/ledger SHA-256：
  `37f5d6430540bfff979475f4022de7df52b2bee16d8a650060120199d7a4dfc6` /
  `b89635351522b6ee2081c874f5647e1359e028998e3055205dee391d59c00ec7`
- 313 个 seed：英国 198、法国 115；按地区和 actual race year 分组，共 24 批，每批不超过 20 匹。
- 每个 seed 最坏 `16 GET`，计划总上限 `5,008 GET`；同进程 cache 可能降低实际数，但不能把节省额度转给
  范围外请求。
- 单批并发固定为 1，不超过 `4 req/s`，批次间隔 30 分钟；计划跨度 690 分钟。理论最小请求间隔时间
  1,252 秒不含网络延迟、`Retry-After`、复核和 safe-stop，因此不能用作完成承诺。
- 每一批都要重新取得限时 exclusive-account proof 和绑定该批 seed ledger/request ceiling 的独立精确 G3。
  Montjeu N1 未成功前不得启动任何一批。
- 网络 CLI 已接入独立 execution ledger：严格下一 ordinal、单一 claim、已完成 artifact 重验和 30 分钟间隔。
  safe-stop 后必须按已消耗请求与未完成 seed 生成新的 retry G3，旧 approval 不可重放。设计与命令见
  [targeted_batch_execution_ledger_20260830.md](targeted_batch_execution_ledger_20260830.md)。

313 个 seed 只是用冠军名字定位 313 个已经有完整结果证据的目标 occurrence，不是 313 匹最终 canonical
horse，也不是四地区全部 actual starters。每个锚点命中唯一 TRA race 后，必须提取该场全部实际出赛的
`hrs_*`，跨赛事去重，再为这个稳定 ID census 生成第二阶段 profile/parent/full-career 计划和新预算。

## 2. 爱尔兰外部参赛马名字样本

- 目标：`ireland:2024:ireland-irish-champion:flat`，Leopardstown，G1。
- 人工复核来源：Netkeiba 英文结果页
  `https://en.netkeiba.com/db/race/2024B1091405/`。
- 结果表共 8 行，冠军为 `Economics`；此处只把冠军作为 TRA 定向查找锚点，不能据此声称八匹马已导出。
- capture root：
  `/Users/mentianlu/.codex/umanews-ireland-sample-reference-2024-20260829.wWvoAk`
- capture manifest/reference/source HTML SHA-256：
  `9446e218c36b98649a9e733f407696b788cb0a448e42dab375c9ea940953624c` /
  `82d6b2da2ec72e065d8603048ab42e0c5a47d21d6609bb38d413af626c526429` /
  `4045fd0a7877f9ee6dac673696fd5478c7fc13bff2406a7107bd180a89450db9`。
- 持久 capture runner 记录 `network_requests=1 / database_writes=0`；这个计数只代表最终冻结抓取，不代表
  其前用于发现 URL 的公开网页搜索和探查总量。Netkeiba 当前只作为 frozen human-reviewed reference，
  不推导系统化抓取许可。

## 3. 四地区 4 匹样本提案

- artifact root：
  `/Users/mentianlu/.codex/umanews-four-region-sample-proposal-20260829.3j4hCB`
- manifest SHA-256：
  `8e28dffb8bc4c62630c80d466db9409c3174f1eed1b76f732d2bab6f8556538f`
- seed ledger SHA-256：
  `c7e90af9b2c962650e58580efa1fa89f7b40b73957d511dd45e3e9d9873e7eb9`
- 状态：`PROPOSED_NOT_APPROVED / execution_ready=false`；生成过程
  `network_requests=0 / database_writes=0`，`PREPARED` 精确绑定 manifest SHA。

| 地区 | 锚点马 | 受审目标赛事 | 来源分类 |
|---|---|---|---|
| 英国 | Majborough | 2024 Triumph Hurdle G1 | frozen human-reviewed result |
| 爱尔兰 | Economics | 2024 Irish Champion Stakes G1 | frozen human-reviewed Netkeiba result |
| 法国 | ZELMAN | 2026 Grand Prix de Saint-Cloud G1 | frozen human-reviewed result |
| 美国 | Thorpedo Anna | 2024 Acorn Stakes G1 | TOBA grading/history evidence |

本样本最多 `4 × 16 = 64 GET`，仍使用并发 1、最小间隔 250ms、同一批次内 cache。运行前的硬阻断：

1. Montjeu N1 必须先成功证明账号 entitlement、schema 与完整历史链。
2. 项目所有者必须分别批准爱尔兰/美国 occurrence binding，以及上述精确 manifest/ledger 的样本 G3。
3. 执行时必须重新确认 TRA 凭据、账号独占窗口、预算和 OpenAPI fingerprint；任一漂移即重建提案。
4. 输出仍只允许不可变 HTTP cache、request ledger、normalized/matrix artifact，数据库写入固定为 0。

样本成功也不能授权 24 批计划或全量写库。四地区字段非空率、North America 路由差异和实际请求量必须先
形成脱敏报告，再据结果收紧第二阶段预算与 gap 分类。

## 4. 验证证据

- 四地区提案单元测试：`2/2`。
- 313 batch plan 单元测试：`2/2`。
- 爱尔兰 Netkeiba capture 单元测试：`2/2`。
- `runtime/research` 全量：`300/300`。
- 当前进程凭据检查：用户名 `missing`、密码 `missing`；未执行 Montjeu 或四地区付费请求。

完整 `stable` suite 仍保留既有 `4,445` 已执行、`32 failures / 144 errors / 128 skipped` 的非绿色结论，
不能用本研究目录的聚焦通过覆盖。
