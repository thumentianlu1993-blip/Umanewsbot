# Reviewed occurrence 合并与四地区局部总账（2026-08-30）

## 结论

已将磁盘上现有的 `384` 条 reviewed held rows 归一成 `350` 条 held occurrences，覆盖 `350` 个
唯一 target。减少的 `34` 行不是赛事丢失，而是 France Galop 官方结果与 ZEturf reviewed result 对同一
`target_key + local_date` 的重复引用；每组保留 France Galop 为主 occurrence，并把 ZEturf 的 URL、证据
SHA、field size 和 starter names 保存为 corroborating reference。不同日期仍视为不同 occurrence；同一
authority 出现同 target/date 重复时失败关闭，不由程序任意选一行。

将这 `350` 条 held occurrences 与已审核的 `113` 条 2026 英法 `not_due` 输入装配后，首次得到覆盖全部
`12,048` 个 reviewed COMPLETE targets 的四地区局部 occurrence ledger：`350 held + 113 not_due +
11,585 unaccounted`。该总账状态是 `needs_occurrence_review / PREPARED`，不是完成、不是 runner seed，
也不授权 API 请求或数据库写入。

## Reviewed held consolidation artifact

- root：`/Users/mentianlu/.codex/umanews-reviewed-occurrence-consolidation-v2-20260830.wJIln5`
- proposal manifest SHA-256：
  `71c4454e4d6a6023bdd1bcb15940e928bc1be075f5b66ed966d34ec838be07cd`
- generator SHA-256：
  `381aec79ed72d757aabee8e551f209a978ac4ff75c67acc24250307e6a774bb2`
- `held-occurrences.jsonl`：350 行，SHA-256
  `7bfe5a6994a331c3b562340e14b09ebff6607a2c47aa049c25bab3e6cfca821f`
- `corroborating-references.jsonl`：34 行，SHA-256
  `865bb89ac3ab80ca18732d6d69f8add1a41d4b9fbcba5ccd6d9051680643d985`
- 状态：`PREPARED_NOT_EXECUTABLE / execution_ready=false`；网络 `0`；数据库写入 `0`

输入守恒：

| reviewed input | rows |
| --- | ---: |
| France Galop current held | 71 |
| Finale 跨年 approved occurrence | 1 |
| legacy GB/FR reviewed results | 312 |
| 合计 | 384 |
| exact same target/date corroborating refs | 34 |
| consolidated held occurrences | 350 |

## 四地区局部 occurrence ledger

- root：`/Users/mentianlu/.codex/umanews-four-region-occurrence-ledger-partial-v4-20260830.VKDCE1`
- manifest SHA-256：
  `e032f62c7fe63e6456d5fe9c3ddbc0dcb9080f67cdb4d0e6e6d79783477b5d65`
- generator SHA-256：
  `3472e360fd44fb1d28fc8981cfa756d164dc0b5beae10c3626ca1882261a4015`
- `occurrence-ledger.jsonl`：350 行，SHA-256
  `be8caf5b808d554f77636b704f477fb63774e92dd92383a29948c495c5770f77`
- `non-held-target-ledger.jsonl`：113 行，SHA-256
  `bbb53e57685f9805ca5b5a7a34cb93fa089f1d623d53cebc406b1c101f2912e5`
- `unaccounted-targets.jsonl`：11,585 行，SHA-256
  `c09c501fbd1e0c9240c7d288f69c68680b1db7aecb5b046013d026aa4557e296`
- 状态：`needs_occurrence_review / PREPARED`；网络 `0`；数据库写入 `0`

v4 compiler 不再接受裸 `--occurrence-jsonl/--non-held-jsonl`。它只接受 proposal roots，并重验各自
manifest、唯一 marker、generator、target manifest/ledger/as-of binding 和 output member SHA/size/rows。
本次两个输入均为 `PREPARED_NOT_EXECUTABLE`，所以 manifest 显式保存
`input_execution_ready=false`；即使未来恰好把 target 数补齐，在输入 approval 就绪前也只会得到
`needs_input_approval / PREPARED`，不能生成 `COMPLETE`。

| region | held | not_due | unaccounted |
| --- | ---: | ---: | ---: |
| GB | 198 | 40 | 2,956 |
| IRE | 0 | 0 | 1,957 |
| FR | 152 | 73 | 1,666 |
| USA | 0 | 0 | 5,006 |
| 合计 | 350 | 113 | 11,585 |

discipline 继续独立：held 为 GB flat/jumps `86/112`、FR flat/jumps `100/52`；not_due 为 GB flat
`40`、FR flat/jumps `43/30`。unaccounted 明确保留 GB flat/jumps `1,494/1,462`、IRE
`683/1,274`、FR `1,197/469`、USA `4,802/204`。

## 门禁与下一步

1. `350 held` 只表示已有 reviewed result evidence；尚未证明 runners、unique `hrs_*`、profile 或 career
   已完成。
2. `113 not_due` 到期后必须以新 as-of artifact 重算；不能永久排除。
3. TOBA 自动匹配尚未独立批准，因此本总账未消费 `3,730` 个 TOBA occurrences。
4. IRE 1,957、USA jumps 204 和英法历史 gap 仍需 authority/result evidence；不得用 route 存在代替 held。
5. 本 artifact 仅用于离线 coverage/audit；proof-only G2、Montjeu N1、批量 G3、production backup/apply
   继续是独立门禁。

新增 compiler approval/drift 用例后，occurrence 专项 `14/14`；publisher/calendar/coverage/occurrence/
TOBA/consolidation 聚焦 `37/37`，完整 research suite `331/331`。测试中的 argparse usage 与 OpenAPI
safe-stop 文本来自预期负例，suite 最终 exit `0`。另一个空目录 replay 的 manifest 逐字节一致，SHA 同为
`e032f62c7fe63e6456d5fe9c3ddbc0dcb9080f67cdb4d0e6e6d79783477b5d65`。
