# 350-target winner seed v2 独立审核请求

状态：等待非实现者决定；不是 approval
proposal：`f950593c8f2d2043d1bbdfe81167eb29258f8acf3d60928a5af1c4b2840df787`

## 审核对象

- 39 条 candidate：37 条 `add_missing_organizer_official_seed`、2 条
  `replace_conflicting_existing_seed`；
- grade：G1 3、G2 4、G3 32；
- discipline：flat 28、jumps 11；
- authority：39/39 `organizer_official`；
- target key 与 seed ID：各 39/39 唯一；
- 15 条带 country suffix，24 条未带；后者进入 TRA 时仍须 exact-name 唯一，若多候选必须停止；
- 唯一重复马名为 `Bright Picture`，对应两个不同 target，必须保留两条 occurrence，不能按名称预合并。

两条替换需优先审核：

| target | 旧第三方 winner | France Galop official winner | disposition |
| --- | --- | --- | --- |
| 2026-07-14 Paris (G.P. de) | GERARD TER BORCH | Maltese Cross | replace |
| 2026-07-05 Saint-Cloud (G.P. de) | ZELMAN | Calandagan (IRE) | replace |

审核输入目录：
`/Users/mentianlu/.codex/umanews-held-winner-seed-extension-final-v2-20260830.Ibybid/artifact`

必须逐字绑定：

- `existing-seed-bindings.jsonl`：
  `9fd7a3e15336e766d9b3d9acd0f3dd308449548ab8e59893210ea6bc226125d9`；
- `new-seed-candidates.jsonl`：
  `ae5be072e7e2536caf96a822811a8d610a7506db37200d4c487726d4a431e845`；
- `all-held-targeted-horse-seeds.jsonl`：
  `6e91cc1f679ba95219f8d60f4e5d4cdbe3aceed0b8ad0f83c066f4040031deda`。

## 决定文件合同

只有非实现者实际完成审核后，才能在仓库外私有目录创建 regular JSON decision。必需结构如下；尖括号为审核人
填写内容，不是可直接执行的决定：

```json
{
  "schema_version": "held-winner-seed-extension-approval-decision.v1",
  "decision": "approve",
  "proposal_manifest_sha256": "f950593c8f2d2043d1bbdfe81167eb29258f8acf3d60928a5af1c4b2840df787",
  "approved_outputs": {
    "existing-seed-bindings.jsonl": "9fd7a3e15336e766d9b3d9acd0f3dd308449548ab8e59893210ea6bc226125d9",
    "new-seed-candidates.jsonl": "ae5be072e7e2536caf96a822811a8d610a7506db37200d4c487726d4a431e845",
    "all-held-targeted-horse-seeds.jsonl": "6e91cc1f679ba95219f8d60f4e5d4cdbe3aceed0b8ad0f83c066f4040031deda"
  },
  "reviewed_by": "<non-implementation reviewer>",
  "reviewed_at": "<timezone-aware ISO 8601>",
  "decision_source_reference": "<immutable review reference>",
  "reason": "<review conclusion covering 39 candidates and two replacements>",
  "independence_acknowledgement": "REVIEWER_IS_NOT_THE_IMPLEMENTATION_AUTHOR"
}
```

实现者不得自行填充、签署或发布该文件。decision SHA 生成后，publisher 还会重放 proposal 全部绑定输入并
重新核对 exact member set；任一漂移都不会生成 COMPLETE。
