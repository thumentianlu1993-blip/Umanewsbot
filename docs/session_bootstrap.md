# 新 Session 启动模板

## 使用方式

未来每次新开工时，Codex 必须先阅读以下文件：

1. [AGENTS.md](E:/Codex/AGENTS.md)
2. [docs/current_state.md](E:/Codex/docs/current_state.md)
3. [docs/decisions.md](E:/Codex/docs/decisions.md)
4. [docs/deploy_runbook.md](E:/Codex/docs/deploy_runbook.md)
5. [docs/codex_workflow.md](codex_workflow.md)

如任务涉及部署、回滚、运维，再继续阅读：

6. [docs/deploy_production.md](E:/Codex/docs/deploy_production.md)
7. [docs/alicloud_hongkong_step_by_step.md](E:/Codex/docs/alicloud_hongkong_step_by_step.md)
8. [docs/rollback_guide.md](E:/Codex/docs/rollback_guide.md)
9. [docs/backup_recovery.md](E:/Codex/docs/backup_recovery.md)

## 启动要求

现行八阶段固定为：
`探索 -> spec/design -> 方案审核 -> 用户确认实现 -> 测试先行 -> 子代理实现 -> 独立 reviewer 会话 /review -> 用户授权后发布`。

开始干活前，Codex 必须先用自己的话总结：

- 当前项目是什么
- 当前阶段是什么
- 当前线上真实状态是什么
- 当前任务目标是什么
- 当前已知阻塞点是什么
- 本次任务位于新工作流的哪个阶段，下一道门禁是什么

在完成这一步之前，不要直接进入实现或部署动作。方案审核通过后还必须先汇报根因、范围、
测试与 RED、历史数据边界、风险/回滚和 reviewer 结论，并等待用户明确“确认实现”“开始实现”
或同义授权；确认前不得写测试、改应用代码/配置/迁移、启动实现 subagent 或重处理历史数据。后续必须遵守
`docs/codex_workflow.md` 的测试先行、subagent 实现、连续 reviewer 会话 `/review`
以及用户在最新一轮成功 review 后针对当前任务明确授权才能发布的门禁。同一需求首次方案审核和首次代码审核各建立一个 reviewer 会话，后续复审复用各自原会话；只有会话不可恢复时才新建，并记录原因、上轮 findings 与交接。审核 subagent
必须实际调用产品自身只读 `/review`，或对应范围且显式包含
内层只读 override 的原生 CLI 审核。每次尝试前后只运行仓库跟踪的
对应范围运行 `python3 .codex/scripts/review_fingerprint.py`（发布前未提交改动统一走
`--uncommitted`；base/commit 仅允许无 staged/unstaged/untracked 的完全 clean 工作树，
ignored 不计，并必须先解析为
不可变 OID，并在 helper 与原生 review 中使用同一个 `--base <oid>` / `--commit <oid>`），并返回命令/模式、内层启动头、范围、
fingerprint 完整原始输出/总 hash/HEAD-status-tracked-untracked 摘要、退出或完成状态；
禁止 heredoc、shell 重定向、临时文件和内嵌替代实现。helper 不跟随 symlink，并对 regular
内容/权限、symlink target、目录 mode、全局竞态、未跟踪 directory leaf、特殊类型与 Git 命令失败 fail closed；单次调用内部至少两份完整快照必须完全一致。首次状态库/网络的
外层 sandbox 失败时只可对完全相同的命令申请升级重跑，内层不是 read-only、指纹变化、
无法确认桌面只读完成状态或重跑仍失败均阻塞，普通 diff 检查不能替代。任何 subagent active 时，主代理只能继续派新
subagent 或等待/接收结果，直到全部结束。既有在途任务先到安全检查点，再按新流程
处理尚未完成的行为，不伪造历史 RED、不重做已完成生产动作。发布后状态回写只走
evidence-only closure，并复用同一需求既有代码 reviewer 会话审核；文件精确限于 current state、project
status、deploy runbook、必要发布 decisions 和本任务 release report，不得夹带代码、测试、
配置、迁移、spec、tasks、skills、agents。原生 review 的
completed/CLI exit 0 只表示执行成功；首次审核只有范围完整、指纹不变、内层只读且 actionable findings
清零才算成功。复审只核对上轮具体漏洞、对应修复和直接触及路径；仅该漏洞的直接 P0/P1
回归可以新增阻塞，其他新发现记录为后续建议后结束，禁止扩展为无关加固。成功 review 后，
发布只要求本任务用户明确授权且实际发布内容与受审内容一致。授权后 staging 前重算完整
fingerprint；显式 stage 全部受审改动后，只在 HEAD 仍为 approved parent、无 unstaged/
untracked/conflict 且 index content hash 与 approved content hash 一致时继续。

## 推荐启动提示词

可直接复用下面这段作为未来新 session 的开场提示：

```text
请先阅读 AGENTS.md、docs/current_state.md、docs/decisions.md、docs/deploy_runbook.md、docs/codex_workflow.md。
阅读后请先用你自己的话总结：
1. 这个项目当前的产品定位
2. 当前线上真实状态
3. 当前阶段目标
4. 本次任务的阻塞点或注意事项
5. 本次任务所处的工作流阶段与下一道门禁

在没有完成这段总结之前，不要直接开始修改代码、部署或给结论。实现必须交给
subagent；方案审核通过后先停下汇报，在我明确说“确认实现”“开始实现”“继续实现”或同义授权前，
不要写测试、改应用代码/配置/迁移、启动实现 subagent 或处理历史数据；同一需求首次方案审核和首次代码审核分别交给未参与对应工作的 reviewer，后续复审复用各自原 reviewer 同一会话；在我明确说“上线”“发布吧”
或同义授权前，不要 commit、push、merge、创建 PR、部署或写生产。发布授权必须是
本任务最新成功 review 之后给出；let's go、其他任务授权或更早授权不算。review 后受审内容若变化，
回到该需求既有 reviewer 会话复审变化及直接触及路径，再重新取得本任务授权。
completed 或 exit 0 不等于审核通过；范围、只读、指纹和 actionable findings 清零四项
门禁必须全部满足。复审仅检查上轮具体漏洞、修复和直接触及路径；只有直接 P0/P1 回归继续阻塞，
其他新发现记为后续建议后结束。授权后 staging 前重算完整 fingerprint；显式 stage 全部
受审改动后，只在 HEAD 仍为 approved parent、无 unstaged/untracked/conflict 且 index 的
content_manifest_sha256 与 approved content hash 一致时继续。漏 stage、夹带或内容变化均停止。
任意 subagent 工作期间，主代理只能继续派新的 subagent 或等待/接收结果；直到全部
active subagent 结束，不得读、改、测、调研、发消息或处理其他工作。部署后只可在
同一授权下仅向 current state、project status、deploy runbook、必要发布 decisions 或本任务
release report 追加事实证据，并复用同一需求既有代码 reviewer 会话审核后提交；代码、测试、配置、迁移、
spec、tasks、skills、agents 禁入。不要重复部署或为证据 commit 自身 SHA 生成递归文档更新。
```
