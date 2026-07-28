# 测试用例

## 测试原则

新增行为必须先看到由能力缺失造成的真实 RED。既有 PR #24 已实现的 HTML 解析和评分规则不伪造
历史 RED；只为兼容状态、checkpoint、恢复、分片、错误语义、原子输出和 workflow 阶段合同
建立新 RED。

全部自动化测试使用临时目录、HTML/JSON fixture 和 fake HTTP client，不访问公网。

## RED/GREEN 矩阵

1. `test_finished_status_labels_are_accepted`
   - “已结束”和“已完赛”均进入范围。
   - RED mutation：源码只接受单一状态。
2. `test_resume_skips_completed_items`
   - 首次处理 N 个后中断；resume 不再次调用已完成 item。
   - RED：没有 checkpoint/stage runner。
3. `test_duplicate_item_does_not_duplicate_rows`
   - 同页面、同马匹重复运行，consolidate key/行唯一。
4. `test_stable_shard_assignment`
   - 输入顺序和进程变化不改变 shard；所有 shard 无漏无重。
   - 两个 lookup key 收敛到同一 profile URL 时，merge 后只有一个 canonical horse。
   - 同一 QID 可由多匹马/多 search shard 引用；一匹马候选跨 entity shard 后仍看到完整集合。
   - 无 profile URL 的同马跨两场仍按 `region|normalized_name` 归并；不同来源 identity 的
     同名马保持分离；身份不足 seed 最多 ambiguous。
5. `test_merge_is_deterministic_and_conflicts_fail_closed`
   - 相同内容重复可幂等去重；同 key 不同内容抛错；不同输入顺序字节一致。
6. `test_atomic_write_ignores_incomplete_temp_file`
   - 未 rename 的临时文件不污染正式 checkpoint；正式文件始终是完整 JSON。
7. `test_cache_hit_avoids_network`
   - 已完成 success item 再运行时 fake client 调用数为 0。
8. `test_partial_page_failure_preserves_other_results`
   - 一个页面失败仍保存其他成功页及错误 item。
9. `test_match_statuses_are_not_forced_exact`
   - probable、ambiguous、no_page 保持各自状态。
10. `test_transport_failure_is_not_no_page`
    - profile、搜索全部失败、entity 批次部分失败和缺实体分别传播 error_code；
      finalize 的 match status 为空、进入 review queue，summary error 不变量成立。
    - 部分 search 成功为空 + 部分失败、已有候选 + 另一查询失败均不评分；重试全部成功后
      才可产生四类状态。
11. `test_final_output_schema_and_empty_names`
    - 全部约定文件和列存在；中文、日文、英文名为空仍保留列。
12. `test_finalize_does_not_use_network`
    - finalize 仅读 checkpoint。
13. `test_progress_is_saved_on_budget_stop`
    - 时间预算在 item 边界安全停止，progress 可继续。
14. `test_top_five_requires_positions_one_through_five`
    - 合法同着 `1,2,2,4,5` 接受；五个唯一完赛结果行是完整性条件。
    - 重复同一马或非完赛状态行混入拒绝。
15. `test_manifest_drift_fails_closed`
    - cutoff、base URL、input SHA 或 shard 参数漂移拒绝 resume。
16. `test_interrupted_resume_matches_uninterrupted_baseline`
    - synthetic 小样本注入固定 clock，首次人为中断，续跑最终字节与不中断基线一致。
    - 真实 clock 下 resume 不重写既有 item 的抓取时间；同一冻结 tree 重复 finalize 字节一致。
17. `test_workflow_has_stage_artifacts_and_no_runtime_source_patch`
    - workflow 多 job、有阶段上传/下载、长 job 有 timeout；不修改 tracked collector。
    - matrix `fail-fast: false`；budget 比 timeout 少至少 10 分钟；stage+shard progress 独立；
      artifact 名绑定 run/attempt/stage/shard；安全停止仍上传。
    - DAG 包含 `merge_entities -> score_horses(matrix) -> merge_scores -> finalize`；
      finalize 只下载完整 merged score index。
18. `test_workflow_second_attempt_resumes_only_stopped_shard`
    - 一个 shard 安全停止后第二 attempt 读取兼容 checkpoint；其他已成功 shard 不重跑。
19. `test_redirect_allowlist_blocks_before_request`
    - sitemap/race/profile/Wikidata 外链、私网、越界 scheme/port 均不产生越界 transport 调用。
20. `test_item_index_and_tool_drift_fail_closed`
    - 篡改单 item、index、collector source SHA 或 parser/scorer/schema version 后拒绝
      resume/merge/finalize。
21. `test_index_binds_manifest_upstream_inputs_and_tool_identity`
    - index 缺失或篡改 manifest SHA、具名 upstream SHA、计划输入 key digest、tool identity 时拒绝。
22. `test_request_count_is_persisted_and_resumed_cumulatively`
    - retryable item 重跑只累计实际新请求，merge/finalize 不重复计算同一阶段。
23. `test_profile_detail_transport_failure_is_retryable`
    - profile 搜索命中但 detail transport/parse 失败仍传播 error，匹配状态留空且禁止评分。
24. `test_synthetic_smoke_safe_stop_resume_matches_baseline`
    - 第一次返回 75 并保留 checkpoint，第二次执行真实 fan-in/finalize；恢复 item bytes 与不中断
      基线一致，最终 artifact 包含结构化错误和非零请求计数。
25. `test_completed_races_resume_is_byte_noop_even_with_retryable_errors`
    - 构造 `safe_stopped=false` 的完整 races stage，其中保留 retryable failure 且
      `request_count>0`；再次 resume 不调用 processor，不重试错误，item/index/progress/request
      count 全部字节不变。
26. `test_safe_stopped_shard_resumes_retryable_items_and_finishes`
    - 构造 `safe_stopped=true` 的 search shard；resume 会重试已有 retryable item、补齐未处理
      item，并把 shard 完成状态写回。
27. `test_workflow_source_stage_restores_only_existing_prefix`
    - dispatch 要求 `source_run_id + source_attempt + source_stage` 全有或全空，source stage 为受控
      choice。
    - 各网络 job 的源 artifact 下载 guard 只覆盖 source stage 及之前的精确 artifact；不会探测
      未来 artifact。完成上游依赖用例 25 的字节 no-op 保证 index SHA 不漂移。
28. `test_resume_recovers_verified_index_ahead_of_safe_stopped_progress`
    - 先保存 safe-stopped progress，再模拟 periodic `rebuild_index` 多落一个完整 success item
      后崩溃；resume 验证 index/item 后按安全停止继续，只处理剩余 key，不永久拒绝，也不把
      index-ahead 状态当 completed。
29. `test_resume_recovers_verified_partial_index_when_progress_is_missing`
    - 模拟第一轮 periodic index 已落盘但 progress 尚未创建；已验证 partial index 按
      safe-stopped 恢复，terminal item 不重跑，继续缺失 item。
    - 用例 25 中“相同完整覆盖但 progress hash 被篡改”继续要求 fail closed，证明恢复条件不是
      遇到任意 hash mismatch 都放行。
30. `test_manifest_recomputes_race_urls_and_all_identity_fields`
    - 除已有字段外显式篡改 `collector_source_sha256` 与 `base_commit` 都必须拒绝；旧 `0cdec…`
      artifact 与修复提交不兼容，不提供迁移。

## 验证层级

- 聚焦：`python -m unittest runtime.research.test_collect_2026_graded_top5_wikipedia`
- 编译：`python -m py_compile ...`
- workflow：YAML 解析/静态合同测试；如环境可用再跑 `actionlint`
- 小样本：fixture E2E + 一次安全停止/恢复
- GitHub：小样本 workflow 成功并可下载至少一个阶段 artifact
- 完整网络：只在小样本、review 和当前版本授权之后触发

## RED 证据记录

实现前记录失败测试名称、失败原因与命令输出摘要到 `tasks.md`。不要求既有已实现行为重新变红。
动态时间只在固定 clock fixture 中参与跨 run 字节比较。

## 正式 run 续跑回归

正式源 run `30241479829` 的 `wikidata_search` shard `0/1/3` 以 safe-stop `75` 结束，shard `2`
完成；源 run 在该失败阶段之后没有未来 stage artifacts。恢复 run `30246234850` 使用精确
source run/attempt 后仍重跑了已经完成的 races，导致 races index SHA 从 `b8bb…` 变为
`4734…`，四个 profiles shard 随后均以 `stage upstream index drift` 确定性失败。

上述 25—27 是对此真实失败路径的最小回归，不访问 GitHub 或公网；RED 必须分别证明“完成 stage
被重写”和“workflow 缺少精确 source stage 前缀”两项缺失行为。

reviewer 会话 `019fa715-f13b-77d0-a282-2b85ffb433c4` 的后续 P1 使用用例 28—30 收口：旧提交
artifact 只保留 evidence；新提交 fresh start；同 identity run 之间若崩溃在 index/progress
原子写之间，可以只接受严格可证明的 index-ahead/partial-index 状态。
