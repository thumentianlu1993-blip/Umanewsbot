# 任务清单

## 方案与测试

- [x] (integration) 审计 PR #24、Actions 日志和现有采集器，记录真实根因与可复用逻辑。
- [x] (integration) 编写 spec、design、test_cases、tasks、rollout。
- [x] (integration) 完成独立方案 review 并取得 APPROVED。
- [x] (integration) 记录最新 `origin/main` OID，完成 branch/main 差异与文件重叠 preflight；
  在 RED 前安全整合主干。若整合改变本方案内容，回到同一方案 reviewer 复审。
- [x] (integration) 新增离线自动化测试并记录真实 RED。

## 实现

- [x] (integration) 实现原子文件、manifest、progress、稳定分片和确定性合并基础层。
- [x] (integration) 实现 races 阶段 checkpoint、完整 1—5 校验与恢复。
- [x] (integration) 实现 profiles lookup checkpoint、全局 canonical merge、缓存和稳定分片。
- [x] (integration) 实现 wikidata_search 阶段 checkpoint与 transport/no_page 分离。
- [x] (integration) 实现 QID-owned wikidata_entities 分批 cache、全局 entity merge、
  horse-owned 完整候选评分和恢复。
- [x] (integration) 实现 merge_scores completion index，并让 finalize 只接受完整 merged 输入。
- [x] (integration) 实现纯离线 finalize 和原子最终输出。
- [x] (operations) 把 workflow 改为小样本验证 + 多阶段 artifact DAG，删除运行时源码 patch。
- [x] (integration) 更新研究 README。

## 验证与审核

- [x] (integration) 聚焦测试全绿、编译和 diff check。
- [x] (integration) synthetic 小样本端到端与人为中断/恢复通过。
- [x] (operations) workflow 静态校验通过。
- [x] (integration) 未参与实现的 reviewer 执行只读原生 code review；首次会话
  `019f9f89-876b-7531-a685-fcd5767d7cee` 结论为 `REVISE`。
- [x] (integration) 针对首次 reviewer 的 7 组 findings 完成测试先行返修。
- [x] (integration) 复用同一 reviewer 会话复审至 APPROVED。
- [x] (integration) 更新 current_state、project_status；如无治理/产品/部署变化，不改 decisions、
  deploy_runbook、project_overview。

## RED 证据

2026-07-27 使用临时 venv 运行：

```text
/tmp/graded-top5-venv/bin/python -m unittest \
  runtime.research.test_collect_2026_graded_top5_wikipedia
```

真实结果：`Ran 14 tests`，`failures=3, errors=10`。失败均由目标能力尚不存在或现有行为不兼容
导致：缺少 atomic/checkpoint/shard/merge/manifest/resolution/URL gate API；源码不接受“已结束”；
重复马未拒绝；workflow 仍是单 job 且运行时 patch 源码。合法同着用例已通过，说明该项属于既有
可复用行为，不伪造 RED。

## GREEN 证据

2026-07-27 使用项目现有虚拟环境运行：

```text
/tmp/graded-top5-venv/bin/python -m unittest \
  runtime.research.test_collect_2026_graded_top5_wikipedia -v
```

初次 GREEN 结果：`Ran 21 tests`，`OK`。新增覆盖 index 内容漂移、预算安全停止与 resume、
中断/续跑 item digest 等价、profile URL 全局收敛、身份证据不足不得 exact、resolution error、
search 子请求成功缓存复用、纯离线且重复执行逐字节一致的 finalize，以及 PR 默认不运行公网 DAG。

另外通过 `py_compile`、Ruby YAML 静态解析（`11` 个 jobs）和 `git diff --check`。本轮未运行
完整公网采集，未 commit、push、部署或写生产。

## 首次 code review 返修 RED/GREEN

2026-07-27 首次 reviewer 会话 `019f9f89-876b-7531-a685-fcd5767d7cee` 返回 `REVISE`。返修先新增
6 个真实失败入口，初次运行 `Ran 26 tests`，结果 `failures=2, errors=4`：缺少 index 全身份绑定、
request count 累计、完整 manifest 重算、真实 synthetic smoke、profile detail 错误传播，且 workflow
仍存在 attempt 通配覆盖。

GREEN 后聚焦测试为 `Ran 27 tests / OK`。新增实现包括：单一精确 source attempt、真实
safe-stop/resume/fan-in/finalize artifact、具名 upstream/manifest/input/tool index 绑定、profile
detail retryable error、全阶段结构化错误、实际 request count 聚合、manifest 全字段与 URL digest
重算。本轮仍未联网采集、commit、push、部署或写生产；下一门禁是复用原 reviewer 会话复审。

限定复审随后发现 1 个直接 P1：真实 stage 把退出码 `75` 转为 success，使不完整 races/profile/
search/entity/score checkpoint 可能进入下游。新增 workflow 合同先 RED，修复后恢复 `27 tests /
OK`：真实 stage 保留非零退出使 job failure，所有 checkpoint upload 继续 `if: always()`；仅 tests
job 的 synthetic smoke 在同一 job 内显式断言 75 后立即恢复。未联网、commit、push 或部署。
