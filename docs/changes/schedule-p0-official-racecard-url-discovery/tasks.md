# P0 官方出马页面 URL 定时发现任务

## 1. 测试先行

- [x] (application) 新增 P0 枚举、有界 orphan、窗口、DST、状态转移、并发和 generation
  原子切换 RED。
- [x] (integration) 新增 route contract、安全 transport、六 provider adapter fixture RED。
- [x] (operations) 新增 Celery schedule、默认关闭、Compose 持久化 mount RED。
- [x] (integration) 实际运行聚焦测试并保存真实 RED 证据。
- [x] (integration) 为 Equibase HEAD 精确路径、BHA 日期索引、France Galop 认证跳转补真实 RED。

## 2. 实现

- [x] (application) 实现 P0 可判窗目标、有界 orphan 审计与 canonical state，不修改业务表。
- [x] (integration) 实现官方 URL route registry、adapter 契约和受控 HTTP。
- [x] (application) 实现旧 URL 保护、stale-run CAS、锁、无环 SHA 和 generation/current
  原子发布。
- [x] (application) 实现 Celery task、脱敏 `TaskExecutionLog` 和默认关闭配置。
- [x] (operations) 增加 `.env.example` 与 default worker 持久化 bind mount。
- [x] (integration) 为 JRA、NAR、HKJC、英国、法国、美国补齐唯一 adapter 分流、正向存在证据
  与离线 fixture；模板 URL 仅为 unverified。
- [x] (application) REFACTOR：保持 adapter 无副作用，统一包含 identity/duplicate 冲突的封闭
  outcome/reason enum、计数与渲染。
- [x] (integration) 增加 event/root identity source、HEAD verification 与 BHA/Equibase
  provider route；France Galop 保持 fail closed。
- [x] (integration) 实现批内请求去重、每 host 最小间隔、零正文 HEAD 和 provider contract
  digest。

## 3. 验证与审核

- [x] (application) 聚焦/回归测试 GREEN，核对业务表零变化。
- [x] (operations) 运行 Django check、迁移漂移、compile、Compose config、Celery 默认队列
  消费 smoke、legacy OpenSpec strict、diff check。
- [x] (integration) 用 fake transport dry-run，审计 expected/found/暂无/blocker 与 SHA。
- [x] (application) 启动未参与实现的 reviewer subagent，实际调用 Codex 原生 `/review`。
- [x] (application) 复用原 reviewer 审核 provider route 增量；两项原 finding 关闭，无直接
  P0/P1 回归，限定复审 `APPROVED`。
- [x] (operations) 停在发布门禁，列明精确配置、route、宿主路径与非影响。

## 4. 后续独立发布门禁

- [x] (integration) 用最终 provider-route 实现执行精确 no-write bounded proof，关闭 findings；
  proof 后若代码/registry 改变则重做 proof。
- [x] (application) 修复 `TaskExecutionLog` 漏记 `listing_reachable`，并以 pre-proof
  fingerprint + 精确 post-proof allowlist 重做 v3 proof。
- [x] (application) proof 完成后由同一 reviewer 审核最终代码、registry 与直接修复路径；
  代码候选 fingerprint 已冻结，审核状态文档增量另做最终限定复审。
- [ ] (operations) 最新成功 review 后取得用户对精确版本的发布授权。
- [ ] (operations) 备份 `.env` 与部署状态，创建受限权限宿主目录。
- [ ] (operations) 默认关闭部署并验证 transport/file write 为零。
- [ ] (integration) 按 provider contract 独立启用 route，单次受控运行并核对文档。
- [ ] (operations) 取得定时启用授权后才设置 `P0_RACECARD_URL_DISCOVERY_ENABLED=true`。
- [ ] (operations) 验证两次调度、持久化、SHA、覆盖与告警；写回 evidence-only closure。
