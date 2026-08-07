# 英国 racecard 级别后缀精确匹配任务

## 探索与方案

- [x] (integration) 从最新 `main@12d76e61` 创建独立干净 worktree。
- [x] (integration) 只读复核 event 924 生产 baseline、既有 blocker artifact 和匹配代码。
- [x] (integration) 用生产镜像执行一次无 raw、无 DB 写入的单请求候选诊断，确认来源存在且
  唯一差异为末尾 `(Group 3)`。
- [x] (application) 固化 spec、design、test cases、tasks、rollout 五份 artifacts。
- [x] (application) 完成方案审核并关闭全部 P0/P1；同一 reviewer 限定复审结论为
  `VERDICT: APPROVED`。

## 测试先行

- [x] (application) 在 `test_race_live_racecard_sync.py` 添加 event 924 同形 suffix variant RED。
- [x] (application) 添加异级基础名称排除、禁止双级别派生、同级不重复、额外文字、非 G1-G3
  和 ambiguous RED。
- [x] (application) 添加 event original、alias、series canonical、年度 series name、
  MajorRaceEvent name/normalized_name/aliases 的隔离路径 RED，并覆盖 active/year/汉字拒绝。
- [x] (application) 实际运行并记录目标能力缺失导致的 RED。

## 实现

- [x] (application) 由实现 subagent 在 `race_live_racecard_sync.py` 添加固定 G1-G3 token 映射。
- [x] (application) 由实现 subagent 对候选 normalized name set 执行同级保留、异级排除、无 token
  才派生的三分支。
- [x] (application) 保持 `_match_events()`、parser、registry、initializer、模型和 Compose 不变。
- [x] (application) 更新 `docs/decisions.md`、`docs/current_state.md`、`docs/project_status.md` 和本
  change artifacts，明确确定性变体与生产门禁。

## 验证与审核

- [x] (application) 运行目标测试、准实时受影响组合、Django check、migration drift、diff check。
- [x] (integration) 回归既有 PostgreSQL initializer/竞争测试。
- [x] (application) 委派未参与实现的 reviewer subagent，实际执行 Codex 原生只读 review。
- [ ] (application) 修复 findings 时复用同一 reviewer 会话限定复审。
- [ ] (operations) 成功代码 review 后记录 fingerprint、approved parent/content hash，并等待本任务

## 发布后

- [ ] (operations) 授权后部署精确冻结镜像，保持所有 live 开关关闭并验证 mount/health/queue。
- [ ] (integration) 选择仍在 today/tomorrow 窗口内的显式英国 G1-G3 event 运行受控 prepare。
- [ ] (operations) blocker 时停止；成功 manifest 单独报审，不在本任务中自动 initializer apply。
- [ ] (operations) 按 evidence-only allowlist 追加事实，复用代码 reviewer 审核后提交。
