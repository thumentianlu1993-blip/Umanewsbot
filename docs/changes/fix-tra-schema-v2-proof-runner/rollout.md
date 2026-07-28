# The Racing API schema v2 proof runner 发布与 proof 方案

## 阶段 1：本地无网络修复

- 从最新 `origin/main` 创建独立 worktree；
- 测试先行取得 schema v2 真实 RED；
- fake transport 完成实现和回归；
- 独立 reviewer 审核安全、预算、SSRF、证据真实性和 v1 兼容；
- review 通过后冻结 fingerprint，停止等待用户授权。

## 阶段 2：代码发布

只有用户明确授权当前 fingerprint 的 commit/push/PR 后才能发布代码。该修复不需要 migration，
不需要启用 worker/beat，不修改数据库或 provider registry。合并、部署仍是独立授权。

## 阶段 3：最多 3 请求只读 proof

需要新的、针对精确 reviewed fingerprint 的用户授权。执行前必须：

1. 核对 registry 文件 SHA-256、schema v2、terms/evidence、有效期和 `max_requests`；
2. 只检查 secret 文件路径、owner、类型和 `0600` 门禁，不输出内容；
3. 选择一个明确 region，记录选择依据；
4. 创建全新、不可覆盖的 output 目录；
5. 确认 lifecycle、race-live scheduler 和 provider 自动写入保持关闭；
6. 使用 `--max-requests <= 3 --region <region> --confirm-network-proof`；
7. 不重试、不跟随 redirect、不扩大分页或地区范围。

## 验收

- 实际请求数不超过授权值；
- 请求 host/path/query 与 registry route contract 一致；
- 每次 HTTP 状态、耗时、大小、collection/field 元数据已去敏保存；
- secret、原始赛事名、马名、外部 ID 和原始 body 不进入 artifact；
- 成功或失败 artifact 均保留并计算 SHA-256；
- 数据库、Celery、赛事状态、新闻和 QQ 均零写/零 dispatch；
- 只有多个日期、多个地区的后续独立 proof 才能讨论覆盖率和 P50/P95。

## 回滚

本轮本地修复没有数据库或生产状态。未发布时只需停止；已发布代码如需回滚，使用发布前镜像或
回滚提交。proof artifact 是审计证据，不删除、不覆盖；它不构成业务数据，无需数据库回滚。

