# Occurrence input 独立审核交接（2026-08-30）

## 当前状态

已实现 `publish_occurrence_input_approval.py`，但没有创建任何 approval。publisher SHA-256 为
`d7f29a64e720c7bc65c8ef56064631f7375221d47ae605a18497d2d02b99657c`。它只接受独立 reviewer 提供的
`occurrence-input-approval-decision.v1` 文件，并要求命令同时传入 decision 文件的 exact SHA。

publisher 在输出前重验：proposal root 无多余成员、PREPARED marker、manifest、generator、reviewed
COMPLETE target、全部 JSONL 的 SHA/size/rows，以及 decision 对全部 output SHA 的逐项绑定。输出仅复制
原始字节，新增 `APPROVED` marker 和 `execution_ready=true` manifest；网络和数据库写入均为 0。

`independence_acknowledgement=REVIEWER_IS_NOT_THE_IMPLEMENTATION_AUTHOR` 是治理声明，不是程序能够独立
证明的人员身份。实现者不得自己生成 approve decision；reviewer 必须实际查看 evidence 与 issue 文件。

## 待审核 proposal A：reviewed held consolidation

- root：`/Users/mentianlu/.codex/umanews-reviewed-occurrence-consolidation-v2-20260830.wJIln5`
- manifest SHA：`71c4454e4d6a6023bdd1bcb15940e928bc1be075f5b66ed966d34ec838be07cd`
- 目标：确认 384 reviewed inputs 中 34 组 same-target/date 引用应保留 official 主 occurrence + third-party
  corroboration，输出为 350 held occurrences。
- output SHA：
  - `held-occurrences.jsonl`：`7bfe5a6994a331c3b562340e14b09ebff6607a2c47aa049c25bab3e6cfca821f`
  - `corroborating-references.jsonl`：`865bb89ac3ab80ca18732d6d69f8add1a41d4b9fbcba5ccd6d9051680643d985`

## 待审核 proposal B：official calendar not_due subset

- root：`/Users/mentianlu/.codex/umanews-official-calendar-non-held-proposal-v2-20260830.CDYApz`
- manifest SHA：`f2cf6609df3456db045a84b15ab1299e2416aaef36aee32a33337c1739ddbd9a`
- 目标：只批准 113 个 future `not_due` dispositions；不得把 260 个 past schedule、2 个 source unmatched
  或 123 个 target issues 解释为已解决。
- output SHA：
  - `non-held-target-ledger.jsonl`：`bbb53e57685f9805ca5b5a7a34cb93fa089f1d623d53cebc406b1c101f2912e5`
  - `past-schedule-needs-result.jsonl`：`76fbbcfbd0830d1585c8629be602acc42883eabcfbacf30dd435f634eb818e76`
  - `calendar-source-unmatched.jsonl`：`4dab85e7d1d15daa2cecd43baeaf93bf302806a2ba06509b8adf371fed43fa4c`
  - `calendar-target-issues.jsonl`：`582db9d9defbdf2caa9a6f9065463ef1eb1dc99b9e3231d94186580394e36352`

## 决定文件合同

reviewer 应为每个 proposal 单独生成决定文件，填入真实 reviewer、时区时间、审核记录引用和理由；下例
只是字段结构，不是批准决定，不能直接执行：

```json
{
  "schema_version": "occurrence-input-approval-decision.v1",
  "decision": "pending_reviewer_action",
  "proposal_schema_version": "<exact proposal schema>",
  "proposal_manifest_sha256": "<exact manifest sha256>",
  "approved_outputs": {
    "<exact output filename>": "<exact output sha256>"
  },
  "reviewed_by": "<independent reviewer>",
  "reviewed_at": "<timezone-aware ISO-8601>",
  "decision_source_reference": "<immutable review record>",
  "independence_acknowledgement": "REVIEWER_IS_NOT_THE_IMPLEMENTATION_AUTHOR",
  "reason": "<what was checked and why the exact rows are approved>"
}
```

publisher 只接受 `decision=approve`；上述 `pending_reviewer_action` 必然失败。两个 proposal 应分别审批、
分别发布，随后用 approved roots 重建 occurrence ledger。TOBA、HRI、历史 gap、TRA 和 production 门禁不在
这两个 approval 的授权范围内。

publisher + occurrence compiler 聚焦 `18/18`，包含相邻 proposal/coverage/TOBA 的组合 `37/37`，完整
research suite `331/331`；当前仍未生成真实 decision 或 approval artifact。
