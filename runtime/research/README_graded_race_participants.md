# 单年度分级赛全部参赛马研究采集器

`collect_graded_race_participants.py` 是独立、只读、artifact-only 的研究入口。它不导入
Django、不连接数据库、不读取生产凭据；网络阶段只访问 UmaFans 公共页。

## 阶段

固定 DAG：

```text
races -> profiles[0..3] -> merge_profiles -> finalize
```

`--year` 必填，范围为 `1984..当前 UTC 年`。每个 output 目录只绑定一个年份、collector
identity 和可选地区清单 SHA；任一漂移都会拒绝续跑。

正式网络运行示例仅用于展示参数，不代表运行授权：

```sh
python3 runtime/research/collect_graded_race_participants.py \
  --year 2025 \
  --stage races \
  --request-budget 5000 \
  --output-dir runtime/research/output/2025-graded-race-participants
```

四个 profile shard 分别使用
`--stage profiles --shard-index 0..3 --shard-count 4 --request-budget 2000`。正式 `races`
阶段的冻结请求预算为 `5000`，每个 `profiles` shard 为 `2000`；run manifest 和 stage
checkpoint 均绑定该预算，resume 时仍须传入相同值。`merge_profiles`、`finalize` 和
`synthetic_smoke` 不联网，不传 `--request-budget`。全部 profile shard 完成后运行
`merge_profiles` 和 `finalize`。达到 `--time-budget-seconds` 时退出码为 `75`；保留
checkpoint 后用完全相同的年份、代码、地区清单和请求预算加 `--resume` 继续。

离线 synthetic：

```sh
python3 runtime/research/collect_graded_race_participants.py \
  --year 2025 \
  --stage synthetic_smoke \
  --output-dir /tmp/graded-race-participants-smoke \
  --limit 1
```

首次通过 `--limit 1` 模拟安全停止并返回 `75`；第二次移除 `--limit` 可验证字节等价续跑、
四分片 fan-in 和最终七文件。

## 关键语义

- 只从已完赛赛事正式结果表认定实际参赛。
- 数字名次、同着、受控非完赛和赛后取消资格保留。
- 退赛、取消出赛和 non-runner 排除；未知状态不纳入 occurrence，进入复核。
- 中文、日文尽力提取；日本和中国香港以外地区要求英文名。
- 泛化 `other` profile 不凭唯一同名自动 resolved。
- `final/` 精确生成七个规划文件；`summary.json` 的 `outcome=partial` 不得描述为完整覆盖。

请求超时、重试和请求数都记录在 stage checkpoint；单元测试和 synthetic 不访问公网。

## GitHub Actions workflow

`.github/workflows/research_graded_race_participants.yml` 的默认边界是离线验证：

- pull request 和 `workflow_dispatch full_network=false` 只运行 collector 单元测试、workflow
  静态合同，以及固定 `2025` fixture 的 synthetic 安全停止/续跑；
- `year` 在 dispatch 时必须显式提供，且同时由 shell 和 collector 校验为
  `1984..当前 UTC 年`；
- 可选地区清单必须用仓库相对路径和精确小写 SHA-256 成对提供；workflow 先拒绝 symlink、
  工作树外路径和 SHA 漂移，collector 再校验 JSON schema、年份和 URL；
- workflow 对 `races` 显式传 `--request-budget 5000`，对每个 profile shard 显式传
  `--request-budget 2000`；同一 stage 的 fresh/resume 共用该调用，merge/finalize 不传预算；
- 只有另行授权并显式选择 `full_network=true`，才会进入
  `tests -> races -> profiles[0..3] -> merge_profiles -> finalize`。

正式阶段的 artifact 名固定包含 `run_id/run_attempt/stage/shard`。`races`、四个 profile shard
和 merged profiles 分别上传自己的精确 checkpoint；fan-in job 显式下载所有上游 shard。
安全停止或暂时网络错误以退出码 `75` 保持 job failure，同时由 `if: always()` 上传当前
checkpoint。后续如获授权，可用同一仓库中的精确 `source_run_id`、`source_attempt` 和
`source_stage=races|profiles` 三元组重新 dispatch；三项必须全空或全有。

请求预算使用 crash-safe write-ahead ledger。races artifact 上传整个 `stages/races/`，其中
包含精确队列续跑所需的 `discovery_progress.json`、`discovery_request_ledger.json` 和正式
stage 的 `request_ledger.json`；因此 discovery 在创建 `run_manifest.json` 或 races index
前停止时，只要 progress/ledger 已落盘，`if-no-files-found: error` 仍能匹配该 stage 目录。
下一次 dispatch 把 artifact 恢复到 output 根，progress/ledger 回到精确的
`stages/races/` 路径。profile artifact 同样上传并恢复整个
`stages/profiles/shards/<shard>/`，不得收窄到 `items/`、`index.json` 或 `progress.json` 而
遗漏 `request_ledger.json`。

races index 的真实路径是 `stages/races/shards/0/index.json`。其中 terminal
`evidence_gap`（当前用于 `error_code=result_not_final`）不是网络重试或永久失败：races job
保持退出 `0`，继续执行 profiles、merge 和纯离线 finalize，最终生成七文件
`outcome=partial` artifact。只有真实 `retryable_error` 映射为 `75`；`permanent_error`、
未知状态或非暂时性错误继续 fail closed。

races 和 profiles job 的 `timeout-minutes=75`，脚本 time budget 为 `3600` 秒，正常情况下给
退出码 `75`、原子 checkpoint 和 artifact post-step 留出 15 分钟余量。但 GitHub Actions 的
hard cancellation 或 runner timeout 可能直接终止 runner，`if: always()` post-step 无法保证
执行；workflow 不声称已捕获这种中断。遇到此类状态只能从最后一份已成功上传的精确 artifact
恢复，并把本次未上传部分视为未知。

单个 workflow run 只执行一次有界 stage 调用，不在 YAML 内循环重试，也不声称能自行跨 run
收敛。是否再次 dispatch 属于独立的监控/操作授权。确定性配置、manifest、schema、identity
或 checkpoint 漂移直接失败，不自动 fresh fallback。

`finalize` 不联网，只 fan-in 已验证 checkpoint；最终 artifact 的上传 allowlist 精确为本年度
三份 CSV、`source_manifest.jsonl`、`summary.json`、`errors.json` 和 `README.md` 七个文件。
workflow 只有 `actions: read` 与 `contents: read`，不运行 Django、数据库、Celery、Docker 或
生产写入。
