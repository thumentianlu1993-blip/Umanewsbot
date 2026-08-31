# G3：Montjeu 1999 凯旋门 targeted-horse 真实 proof

状态：`已执行并按 provider_partial 安全停止`。批准只覆盖本文固定 seed、host/path、最多累计
`16 GET` 和 `0` 数据库写入。首次 edge-blocked search 消耗 1 GET；固定 User-Agent 后的重跑在 fresh
exclusive proof `83a1e914…5dca0` 下消耗 2 GET。search 返回 200 并定位 `hrs_3521238`，horse results
返回 200 但没有唯一 1999 Arc occurrence，因此未继续 profile/parent，累计 `3/16`、数据库写入 0。

2026-08-30 项目所有者再次确认本页 exact G3 后，凭据与 fresh proof 均已就绪并完成上述运行。该确认始终
不覆盖四地区样本、批量或写库；safe-stop 后没有把剩余额度解释为修改 seed 或继续 profile 的授权。

## 固定输入

- 外部证据：France Galop 官方 1999 凯旋门历史赛果存档。
- source payload SHA-256：
  `50cd02479fdca9155be2c9ccfc0b6d1bc0a0e89c16305807462315beffd6f1a1`。
- seed：
  `docs/changes/export-graded-race-horses-2000-current/research/montjeu_1999_arc_targeted_seed.v1.json`。
- seed SHA-256：
  `d642f8ea5c64f6d1b7166aba6bb4ba9bba5f3776b38d8fd68f77f5e280290814`。
- TRA OpenAPI version：`1.4.4`。
- selected endpoint contract SHA-256：
  `d291af21a5a646ec803e9bafcdeb8786b87593dff6dfc10220da8ce00a66a0c9`。

## 唯一允许的网络范围

- Host：`api.theracingapi.com:443`，仅 HTTPS、禁止 redirect。
- Paths：
  - `/v1/horses/search?name=Montjeu`；
  - `/v1/horses/hrs_*/results?limit=100&skip=N`；
  - 唯一已确认候选的 `/v1/horses/hrs_*/pro`，只有 `404` 才回退 `/standard`；
  - 该马 sire/dam 的 `/v1/horses/hrs_*/pro`，只有 `404` 才回退 `/standard`。
- 不允许 `/v1/results`、racecards、人物接口或任意其他 host/path。
- 不允许数据库写入、发布、QQ/邮件通知或 race-live 状态推进。

## 精确预算

- exact-name candidates ceiling：`3`；
- 每候选 horse-results page ceiling：`3`；
- parent profile ceiling：`2`，最大深度 `1`；
- 无额外 retry reserve；`429/5xx` 重试同样消耗总预算，预算耗尽即 safe-stop；
- request ceiling：`1 + 3*3 + 2 + 2*2 = 16`；
- 客户端最小请求间隔：`0.25s`，即不超过 `4 req/s`；
- 估算正常耗时：约 `4–15s`，若 `Retry-After` 更长则按服务端要求等待。

## 账号级并发前置条件

one-shot runner 已接入账号级 `exclusive_file` limiter。执行前仍必须现场只读确认没有其他 TRA
active claim/request，并生成最多 `15` 分钟有效、`0600`、SHA-bound 的 exclusive-account proof；若无法
证明调用窗口独占，或 proof 过期，本 proof 不执行。所有进程共用一个 `0700` budget root，attempt 在
发请求前持久化，进程崩溃不返还额度；每次 request reservation 和 `Retry-After` defer 都重新核验
`valid_until`，预计越过独占窗口时立即 safe-stop。不得仅因“请求量小”忽略账号级 `5 req/s` 上限。

proof 不再允许手写：先在本机 runner host 与 production host 分别运行
`capture_racing_api_host_process_preflight.py --host-role=runner|production`，scope manifest 都使用本页固定
seed SHA；2 分钟内由 production Django command `generate_racing_api_exclusive_account_proof` 合并两端
process evidence 与 settings/DB/Celery/Redis 证据。完整命令和失败边界见
[exclusive_account_preflight_20260830.md](exclusive_account_preflight_20260830.md)。

## 输出

runner 保持在当前凭据已注入的本机 Codex 进程，建议私有 artifact root：

```text
/Users/mentianlu/.codex/umanews-racing-api-horse-exports/proof-montjeu-1999-arc-<UTC_TIMESTAMP>
```

输出只包括不可变 response cache、脱敏 request ledger、normalized profile/parent/career/target race、
manifest 和最后发布的 `COMPLETE`。`database_writes` 必须为 `0`。凭据仅由环境或 `0600` secret 注入，
不得进入命令行、日志、artifact 或聊天。

## 执行命令模板

```bash
RACING_API_HORSE_EXPORT_NETWORK_ENABLED=true \
python runtime/research/racing_api_horse_export.py \
  --seed docs/changes/export-graded-race-horses-2000-current/research/montjeu_1999_arc_targeted_seed.v1.json \
  --approved-seed-sha256 d642f8ea5c64f6d1b7166aba6bb4ba9bba5f3776b38d8fd68f77f5e280290814 \
  --output-dir /Users/mentianlu/.codex/umanews-racing-api-horse-exports/proof-montjeu-1999-arc-<UTC_TIMESTAMP> \
  --max-search-candidates 3 \
  --max-results-pages-per-horse 3 \
  --max-parent-profiles 2 \
  --request-ceiling 16 \
  --openapi-fingerprint docs/changes/export-graded-race-horses-2000-current/research/tra_openapi_fingerprint_20260829.json \
  --approved-openapi-fingerprint-sha256 c1dad02e0e53a48e6e7d889af2ce97032c79d0fbf56fe002ac67c6589a3a8b92 \
  --account-budget-root /Users/mentianlu/.codex/umanews-racing-api-account-budget/montjeu-proof-<UTC_TIMESTAMP> \
  --credential-alias tra-primary \
  --account-scope-id montjeu-1999-arc-proof \
  --account-scope-manifest-sha256 d642f8ea5c64f6d1b7166aba6bb4ba9bba5f3776b38d8fd68f77f5e280290814 \
  --account-request-ceiling 16 \
  --exclusive-account-proof /Users/mentianlu/.codex/umanews-racing-api-account-budget/montjeu-exclusive-proof-<UTC_TIMESTAMP>.json \
  --exclusive-account-proof-sha256 <FRESH_PROOF_SHA256> \
  --allow-network
```

`RACING_API_USERNAME`、`RACING_API_PASSWORD` 必须由受控环境另行注入，禁止在命令文本中展开。
上述 fingerprint 参数只读本地冻结文件，不调用 `/openapi.json`，所以不增加已批准 host/path 或 16 GET
预算；任何内部 selected contract/schema 或文件 SHA 漂移都会在账号预算、client 和首个 GET 前停止。

## 验收和 safe-stop

成功必须同时满足：唯一 `hrs_*` 候选由 1999 Arc 冠军 occurrence 证明；Pro 或明确 Standard fallback；
results 分页总数守恒；1999 Arc 唯一命中；目标马为实际出赛且 position=1；全场 non-runner 被排除；
父母 profile 数不超过 2；manifest/response hashes 完整；请求数不超过 16；数据库写入为 0。

任一身份歧义、目标赛事缺失/多匹配、分页漂移、未知 runner 状态、schema drift、401/403、预算耗尽、
账号并发无法排除或输出目录非空，都必须以非成功状态停止，不得改成“近似命中”。
