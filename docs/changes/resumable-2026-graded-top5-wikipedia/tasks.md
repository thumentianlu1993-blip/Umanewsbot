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

## 正式 run 跨 run 续跑返修

- [x] (integration) 记录源 run `30241479829` 与恢复 run `30246234850` 的确定性失败链，锁定
  完成 stage/shard 字节级 no-op 与 `source_stage` 前缀恢复合同。
- [x] (integration) 新增完成 races no-op、safe-stopped shard 继续和 workflow source-stage
  前缀三组离线回归并取得真实 RED。
- [x] (integration) 实现完成 stage/shard 校验后直接返回，不重试 retryable errors，不重写
  item/index/progress/request count；只允许 `safe_stopped=true` 继续。
- [x] (operations) workflow dispatch 增加受控 `source_stage`，与 source run/attempt 三元绑定，
  只恢复源阶段及之前的精确网络 stage/shard artifact。
- [x] (integration) 将本轮 RED 转绿，运行聚焦测试、编译、YAML/静态合同与 diff check。
- [ ] (integration) 复用既有 reviewer 会话完成直接路径复审；之后仍需新的发布/联网授权。

### 本轮真实 RED

2026-07-27 使用现有临时 venv 运行：

```text
/tmp/graded-top5-venv/bin/python -m unittest \
  runtime.research.test_collect_2026_graded_top5_wikipedia -v
```

结果：`Ran 30 tests`，`FAILED (failures=2)`。失败为：

- `test_completed_races_resume_is_byte_noop_even_with_retryable_errors`：第二次 resume 实际调用
  `race-b`，证明完成 races 中的 retryable error 被隐式重试并重写 checkpoint。
- `test_workflow_source_stage_restores_only_existing_prefix`：workflow dispatch 不存在
  `source_stage`，无法限定只下载源 run 已实际产生的 stage 前缀。

`test_safe_stopped_shard_resumes_retryable_items_and_finishes` 已通过，证明现有 runner 的安全停止
继续能力可复用；本轮 RED 不是 fixture、依赖或网络错误。未修改 collector/workflow/README，
未联网、commit、push、部署或写生产。

### 本轮 GREEN

实现后同一聚焦命令为 `Ran 30 tests / OK`。完成 checkpoint 的 resume 现在先验证
index/items、计划输入覆盖、progress stage/total/processed/request count 以及
`progress.index_sha256`；只有 `safe_stopped=false && processed==total` 且 index key 完整覆盖
计划输入时才返回既有 progress，整个 checkpoint tree 字节不变。`safe_stopped=true` 继续缺失
item 并允许重试 retryable error。

workflow dispatch 已新增允许空值的新 run choice 和五个受控 `source_stage`；source selector
三者全有或全空，各网络 stage 只下载源阶段前缀内的精确 run/attempt/name artifact，merge
继续在当前 run 重建。另通过 collector/test `py_compile`、Ruby YAML 解析（`11` jobs）、
workflow 静态合同和 `git diff --check`；本机检查结果为 `actionlint=unavailable`。本轮仍未
联网、commit、push、触发 workflow、部署或写生产。

## Reviewer 019fa715 P1：身份边界与崩溃窗口

- [x] (integration) 明确旧 `0cdec…` artifact 仅为 evidence；修复后从新提交 fresh start，
  后续仅允许相同新 HEAD/collector identity 的 runs 互相 resume，跨 commit fail closed。
- [x] (integration) 强化 manifest 测试，显式覆盖 `base_commit` 与
  `collector_source_sha256` 漂移拒绝；不新增兼容迁移。
- [x] (integration) 为 periodic index 领先 progress、partial index 缺 progress 新增离线 RED，
  并保留同覆盖 hash 错误 fail-closed 断言。
- [x] (integration) 只对已验证且严格可证明的 index-ahead/partial-index 崩溃窗口重建
  safe-stopped 状态并继续；未知状态不得视为 completed。
- [x] (integration) 将本轮 RED 转绿，运行聚焦测试、编译、YAML jobs 和 diff check。
- [ ] (integration) 复用 reviewer 会话完成 findings closure 复审。

### 本轮 RED 证据

2026-07-28 运行：

```text
/tmp/graded-top5-venv/bin/python -m unittest \
  runtime.research.test_collect_2026_graded_top5_wikipedia -q
```

结果：`Ran 32 tests`，`FAILED (errors=2)`，且错误仅来自新增目标行为：

- `test_resume_recovers_verified_index_ahead_of_safe_stopped_progress`：
  `ValueError: stage progress index drift`。模拟 periodic index 比 safe-stopped progress 多一个
  已验证 success item 后，当前实现永久拒绝。
- `test_resume_recovers_verified_partial_index_when_progress_is_missing`：
  `ValueError: stage progress missing for resume`。模拟首个 partial index 已落盘、progress 尚未创建
  后，当前实现永久拒绝。

既有“完整同覆盖但 progress hash 错误必须拒绝”断言继续通过；manifest 测试新增
`collector_source_sha256` 漂移后也通过，证明旧 `0cdec…` 与新提交身份隔离已存在，不需要兼容
迁移。本阶段未修改 collector/workflow/README，未联网、commit、push、触发 workflow 或部署。

### 本轮 GREEN 与 findings closure

实现仅放宽两种已证明的崩溃状态：verified index 严格领先旧 safe-stopped progress，或 progress
缺失且 verified index 为严格 partial coverage。前者还要求旧 total 等于计划总数、processed
合法且严格落后、旧 request count 不大于当前 index；恢复以当前 index 的 items/request count
为累计起点，terminal item 跳过，retryable item 可重试。完整 index 缺 progress、同覆盖 hash
错、非法类型、coverage/identity/input/item 漂移均继续拒绝。

同一聚焦命令已由 `Ran 32 tests / errors=2` 收敛为 `Ran 32 tests / OK`。另通过 collector/test
`py_compile`、Ruby YAML 解析 `11` jobs 和 `git diff --check`；`actionlint` 仍不可用。P1-1
无需代码兼容层：manifest 的 base commit 与 collector SHA 漂移测试已绿，README/rollout 明确
旧 `0cdec…` 仅为 evidence、新提交 fresh start。本轮未联网、commit、push、触发 workflow、
部署或写生产。
