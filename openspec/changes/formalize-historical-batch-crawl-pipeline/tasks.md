## 1. 分片计划与 artifact 服务

- [x] 1.1 (integration) 在实现前按完整 `test_cases.md` 加入 plan builder 失败/成功回归，再实现 selection/approval/manifest/image/tool SHA 读取与不可变身份校验。
- [x] 1.2 (integration) 实现 typed recipe 与 target-binding policy：首批覆盖 discovery/cache、五地区详情 preparer、cached parser、packager 和 merger，解析实际 events CSV、selection subset、provider/candidate JSONL，证明目标集合与 shard scope 精确一致；禁止任意 argv 和无 policy 工具。
- [x] 1.3 (integration) 实现 stage descriptor 与 shard 校验：同一 stage 目标恰好覆盖一次、地区一致、单 shard 最多 250 目标、请求预算 1..250、输入输出路径和工具均受控且不跨 shard 冲突。
- [x] 1.4 (application) 新增 plan builder 管理命令，为每个 shard 创建独立 artifact 挂载根与资源账本命名空间，原子生成 scope、runner plan、stage manifest 和 summary，并调用现有 `validate_runner_plan()` 做最终兼容校验。
- [x] 1.5 (integration) 为正式 plan 增加 `resource_limits` 身份，令 runner 在创建/恢复 run 和取双锁前与实际 settings 比较；保留 legacy smoke 兼容但禁止正式 descriptor 降级。

## 2. 日期与详情碎片合并

- [x] 2.1 (integration) 在实现前加入 date/detail 合并、输入乱序稳定 SHA、重复去重、冲突转 gap、complete/gap 互斥、无证据遗漏拒绝和人工 evidence 防漂移测试。
- [x] 2.2 (integration) 新增 tracked `merge_historical_race_batch_fragments.py`，实现 date/detail 两模式、canonical JSONL、完整输入身份、complete/gap 分母和“临时目录完整构建后一次 rename”的原子发布。
- [x] 2.3 (integration) 将 merger 加入 historical runner 显式 Python tool 白名单及工具 SHA 契约；确认 `tmp/`、artifact 工具根和未批准工具继续拒绝。

## 3. 数据库阶段验收

- [x] 3.1 (application) 在实现前加入 date、detail-source、final 三阶段数据库验收测试，覆盖来源/数量/模块/visibility/provenance 漂移和非零退出码。
- [x] 3.2 (application) 新增 `verify_historical_race_batch_stage` 管理命令，逐 target 输出机器可读报告；PostgreSQL 使用 `SET TRANSACTION READ ONLY`，并保持 one-off 无网络和 published=0 门禁。

## 4. 文档与运行入口

- [x] 4.1 (operations) 更新 `docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md` 和必要决策记录，说明 descriptor、shard、gap、人工 evidence、备份、恢复和禁止使用 `tmp/` 的口径。
- [x] 4.2 (operations) 更新 OpenSpec tasks/test cases 与历史 runner 运维命令，记录 batch006 approved selection/approval SHA 和正式分片验收清单。

## 5. 完整验证与代码审查

- [x] 5.1 (integration) 运行新工具/runner/历史批次聚焦测试、完整 stable、Django check、迁移漂移、OpenSpec strict/all、shell 与 diff 检查。
- [x] 5.2 (integration) 运行 1250 targets/10 shards/每场 20 runners-results 性能契约，确认 artifact 编排不超过 30 秒/256 MiB，数据库 verifier 不超过 20 条查询。
- [x] 5.3 (integration) 执行反复 `/review -> 修复 -> 重新 review`，直到一次 review 无任何 actionable finding；不得以测试通过替代 review。

## 6. batch006 生产应用

- [x] 6.1 (operations) 从最新 main 双构建可复现 AMD64 镜像，完成写前备份、身份核对、只替换 web/worker/beat 和 runner 强化 smoke，保持公开及常驻开关关闭。
- [ ] 6.2 (operations) 使用 approved 1061 场 selection 生成正式 stage descriptor、shards 和 runner plans，核对完整覆盖、请求预算、工具 SHA、磁盘与 approval 后启动 crawl。
- [ ] 6.3 (operations) 对 complete targets 依次执行日期、详情来源和最终候选 dry-run；每次 apply 前独立备份，写后运行正式 verifier，gap 累计到统一审核账本。
- [ ] 6.4 (operations) 完成 batch006 全批汇总、逐地区 events/runners/results、error=0、published=0 和无遗留 runner/队列/事务验收，再生成下一标准批次。
