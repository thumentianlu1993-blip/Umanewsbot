# HRN 正文残留边界与机构译名修复规格

## 背景

历史 HRN 正文边界已收紧到 `.article-body`，但 Gate 6 人工抽查仍发现两类残留：

- 部分赛前分析正文容器内嵌 Bootstrap 视频弹窗，`Race Video ×` 被当作正文；
- HRN 美国文章中的 `The Jockey Club` 被生产术语库的英国同名机构词条翻成“英国赛马会”。

这两类问题分别发生在 DOM 清洗和来源语境术语保护阶段，不能用公开模板隐藏、文章 ID 特判或中文词黑名单处理。

## 范围

1. HRN `.article-body` 内的交互式 dialog/modal 控件不得进入原文正文、翻译输入或公开正文。
2. HRN 美国新闻中的精确机构名 `The Jockey Club` 使用来源级确定性译名“美国赛马会”。
3. 保留普通正文中的段落、小标题、引用、列表、赛马表格及正文语句中的 `Race Video` 字样。
4. 不改变非 HRN 来源中同名英国机构的既有译名。
5. 修复发布后，仅对 Gate 6 剩余 36 篇重新 prepare；候选仍逐篇抽查并走既有批准、apply、verify、rollback 信任链。

## 非目标

- 不重写通用正文提取架构。
- 不建立包含 `Race Video`、`×` 或中文污染词的文本黑名单。
- 不修改公开模板以隐藏已入库脏文本。
- 不自动批准严重截断、编辑注或仍然翻译失败的文章。
- 不重发历史 QQ 消息。
- 不改变英国、香港或其他来源的 Jockey Club 赛事/机构译名。
- 不承诺本轮 36 篇全部可写入；未通过抽查者继续保留在失败或拒绝清单。

## 行为要求

### R1：HRN 交互控件按 DOM 结构移除

- 清洗范围仅限已命中的 HRN `.article-body`。
- `role="dialog"` 的交互式容器及其子节点在文本提取前删除。
- 删除计数写入 `body_cleaning.removed_rules`，便于审计。
- 页面没有 `.article-body` 时仍按既有规则 fail closed。

### R2：合法正文不得过度裁剪

- dialog 前后的正文、表格、标题、引用、列表保持原顺序和完整内容。
- 普通段落中出现 `Race Video` 或乘号字符时不得因文本命中而删除。
- 非 HRN 来源不受 HRN 专属结构规则影响。

### R3：HRN 的美国机构译名确定性保护

- 对 HRN 英文原文中的完整边界 `The Jockey Club` 使用内部占位符保护，并在 provider 输出后恢复为“美国赛马会”。
- 保护覆盖标题和正文中的全部合法出现；摘要若复制该来源占位符，也必须恢复为同一译名。
- 模型删除、篡改或伪造占位符时沿用现有 fail-closed 校验与重试。
- 来源级映射优先于生产术语库中同表面文本的英国机构词条。
- 非 HRN 文章继续走既有术语库，不应用该来源级映射。
- `The Jockey Clubhouse` 等较长单词不得命中；匹配大小写不敏感，但必须满足两侧非英文字母/数字边界。
- Dummy fallback 与真实 OpenAI-compatible provider 使用同一来源术语计划；Dummy 仍不可作为生产发布翻译，但不得生成相反译名。

### R4：历史重处理保持受控

- 重新 prepare 的精确范围是 Gate 6 结束时仍未 apply 的 36 篇。
- prepare 不写业务字段；每篇候选必须人工抽查正文完整性、污染、机构译名和截断。
- 只有通过抽查的文章才能进入最多 10 篇的批准 manifest。
- 翻译失败写入失败 artifact 后跳过；抽查拒绝写明原因，不得自动放行。
- apply 后必须运行独立 verify；rollback artifact、receipt 和各 SHA 继续沿用既有合同。

## 失败边界

- DOM 缺少可信 `.article-body`：保持 `selector_not_found`，不得回退页面级节点。
- HRN dialog 结构漂移且污染仍出现：候选抽查拒绝，暂停该文章写入并记录新结构。
- 来源级机构占位符校验失败：翻译失败，不得降级接受模型自由译名。
- 候选正文截断、编辑注残留或合法首尾缺失：拒绝，不得因本轮修复目标较窄而放行。
- receipt、manifest、fingerprint、CAS 或 SHA 任一漂移：沿用既有 fail-closed 行为。

## 验收标准

1. 等价真实 HRN fixture 中的 `Race Video ×` dialog 不进入 `body_ja_raw`。
2. dialog 前后合法正文和表格保持完整，正文语句中的同词不被删除。
3. HRN 文章中的 `The Jockey Club` 确定性恢复为“美国赛马会”，不出现“英国赛马会”。
4. 非 HRN 英国文章仍可使用既有“英国赛马会”术语。
5. 聚焦测试、受影响回归、Django check 和迁移漂移检查通过。
6. 最新独立代码 review 无 actionable finding。
7. 发布前不 commit、push、部署或写生产；发布后重新 prepare 36 篇也不等于自动批准。
