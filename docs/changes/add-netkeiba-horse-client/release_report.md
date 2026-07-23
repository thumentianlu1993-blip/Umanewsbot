# add-netkeiba-horse-client 发布报告

## task 5.3 无写入候选

- 执行日期：2026-07-24（Asia/Shanghai）
- 生产版本：`4972a6b2eb35167d5783f5c37908b8b3d190160d`
- 审查：`APPROVED`，P0/P1/P2=`0/0/0`，session
  `019f9095-2025-7a80-96be-b50800b18d82`
- 批次：`p0batch-20b59bda0608`
- 原审核工作簿 SHA-256：
  `bee158e6d70c099c550102df6f9221b2d6bbb5fb75697d50a06d6d87b61cbc9f`
- 批次批准 SHA-256：
  `51ac349ebd45848abb89c9f29545e695a760d245e09e72fcecc0de4bfaefa44f`

### 冻结对象与绑定

- 完整对象：61；blocker：39；artifact/blocker 交集：0。
- research：
  `1afce80f871cc703e0527113bc4f33db06766770029ebf380444b77108fb115b`
- mapping：
  `e96c8aa9a2fa965f9cc18b0b5931bc47af48f882d8c3833ef9b35a2fe414e826`
- authority：
  `759ac2dcdcbff1c22f62424f7c6167c417ae99d9d669c14a0ef0fa38ab1f7bdb`
- combined candidates：
  `6975c975c662ae6fd1bc8711f2ded68a9c71818d4c79de411208eb07fdadf50d`
- production snapshot：
  `0e0ad3dcf447912d5de6d19714c10e67862b3cd4b327274706da6338e5c45733`
- commit artifact：
  `1abbf475927c1e4391ab1ce851b3cd28958da2ec65641c28ec4f49e9608c4894`
- release candidate：
  `8ef0f718803f7772db5b498925a71651e5c68cb331aeafa50f03dc831f8848fe`

### 预计动作与公开范围

- profile creates：0
- profile updates：61
- race record creates：1,490
- race record updates：0
- P0 source upserts：61
- module audits：244
- 自动首发：0
- 已公开且跳过首发：61
- 新身份：0

### 零写入验收

- 重复 prepare-release 的 candidate 文件字节和 SHA 一致。
- approvals ledger 保持 3 行；`release_candidate_prepared=1`、
  `release_approved=0`；未生成 v2 release manifest。
- HorseProfile、HorseP0Source、HorseRaceRecord、HorseProfileCompletionRun、
  OperationLog 和公开计数均与执行前一致。
- 宿主和 `web / worker / beat / race_live_worker` 的
  `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`。
- 未运行 `--commit`、`--retry-publish`，也未传 `--approved-by`。

当前停在 task 5.4 前。正式写入必须取得针对 release candidate
`8ef0f718803f7772db5b498925a71651e5c68cb331aeafa50f03dc831f8848fe`
的新授权。

## task 5.4 首次正式写入结果

- 用户已授权上述 candidate，批准人 `mentianlu`；生成的 v2 release manifest SHA-256 为
  `5320c33c44d387b14e827b109353ffe5068d997bd9c62d9df903cb5de91e0c90`。
- 数据库 apply 在 `イエローマジック` 的 strict-complete 复验处 fail closed，原因是该马真实
  无胜场，而当前完整度逻辑不能区分“major-wins 未审核”和“已审核确认暂无胜绩”。
- 61 行中有 10 匹真实无胜场；不得为通过门禁而虚构胜场。
- PostgreSQL 事务整批回滚；马匹业务表、completion run、OperationLog 和公开计数均零变化，
  自动首发未运行，网络保持 false。
- task 5.4 未完成。建议通过新测试锁定“approved empty major-wins”语义，实施窄修并独立复审；
  部署后重新生成 candidate，任何新 SHA 都必须重新授权。
