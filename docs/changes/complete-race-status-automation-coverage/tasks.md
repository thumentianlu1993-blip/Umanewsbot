# 补齐赛事状态自动更新完整链路：任务清单

## 0. 范围和基线

- [ ] (operations) 从用户批准后的最新 `origin/main` 建立独立 clean worktree，记录 commit、tree 和并行任务边界。
- [ ] (operations) 重新只读核对生产 image/revision、migration leaf、10 个开关、policy/registry SHA、服务、资源和三队列。
- [ ] (application) 冻结生产 census：未来赛事、source identity、enrollment、lifecycle authority、official revision、publication 和 incident。
- [ ] (operations) 确认本变更不触碰 France 2023 External staging、TRA 马匹 canonical、新闻、QQ 和旧 `race_live`。

## 1. 先写会失败的测试

- [ ] (integration) 增加 standing policy v2 RED：先到先得授予（一次性授予、同轮 `tiebreak_order` 平局、授予后粘滞、result-only 来源无竞争资格、失效回池重新授予）和 v1 不可静默升级。
- [ ] (integration) 增加 discovery RED：30 天分类、today/tomorrow 请求窗口、守恒统计、等待/未找到/多解分离。
- [ ] (integration) 增加最近 7 天恢复清单 RED，以及 new-enrollment/continuation 状态分离 RED。
- [ ] (application) 增加 lifecycle admission RED：data-sync enrollment 可以授权 lifecycle，legacy registry 保持不变，双 authority 拒绝。
- [ ] (application) 增加共享 validator RED：lifecycle writer、result writer 和 public reader 的通过/拒绝必须一致。
- [ ] (application) 增加 late-admission RED：允许有证据的 `scheduled -> finished`，不得伪造 running。
- [ ] (application) 增加 755/756/757 同形态审计修复 RED：未经来源证据复核的旧 official revision 不能直接公开；证据复核、不可变候选、dry-run、批准、apply、verifier 链路完整；同内容重放幂等。
- [ ] (application) 增加 correction RED：相同内容幂等、合法变化 supersede、无 marker 冲突、低优先级不得覆盖。
- [ ] (integration) 增加 PostgreSQL 并发 RED：discovery/reconciliation/schedule/lifecycle/result/correction/双 authority/并发授予竞争。
- [ ] (operations) 增加发布和 kill-switch RED：policy SHA 漂移、服务恢复、一个 selector 周期停止写入、`race_live` 不变。

## 2. 最小实现

- [ ] (integration) 将 standing policy parser 和 runtime policy 升级为 v2，加入 `enrollment_eligible` / `tiebreak_order` 先到先得语义，重新生成精确 SHA。
- [ ] (integration) 修改 enrollment census：按先到先得授予纳管（同轮 `tiebreak_order` 裁决、授予后粘滞、失效回池重新授予），result-only 来源只进更正渠道。
- [ ] (integration) 修改 TRA identity discovery：区分盘点窗口和来源窗口，补齐全部 outcome 计数。
- [ ] (integration) 增加有界恢复清单：只选择最近 7 天仍有 tracking 责任的未闭环 data-sync 赛事。
- [ ] (application) 实现唯一 `validate_data_sync_lifecycle_admission()`，不接受调用者布尔值绕过。
- [ ] (application) 修改 enrollment/control 协调：lifecycle 开启时建立 data-sync admission，关闭时保持 off。
- [ ] (application) 实现每批最多 20 场的 lifecycle admission reconciliation，保留 manual pause 和 legacy membership。
- [ ] (application) 实现停滞赛事审计修复命令：未闭环清单选择、来源证据复核、SHA 锁定候选、dry-run/apply/verifier 和 OperationLog；不硬编码 event ID。
- [ ] (application) 让 lifecycle task、result projection 和 public read 共用同一 validator。
- [ ] (application) 为 late admission、authority conflict 和恢复成功补齐稳定 reason code 与 incident 收口。
- [ ] (operations) 扩展 `audit_race_data_sync`，输出完整分类、守恒、两类 authority、stuck official 和 correction watch。
- [ ] (operations) 更新 `.env.example`、policy SHA 绑定、运行手册和回滚说明；不新增第二套总开关。
- [ ] (operations) 运行 migration drift；若出现新 migration，立即停止并回到方案审核。

## 3. 本地和隔离验证

- [ ] (application) 运行相关 SQLite/Eager 全套测试，确认新增 RED 变 GREEN 且现有赛事页面回归不退化。
- [ ] (integration) 在独立 PostgreSQL 16 执行并发、事务回滚、重复派发和 correction 套件。
- [ ] (operations) 运行 Django check、migration drift、compileall、Compose 三配置、diff check 和 secret scan。
- [ ] (operations) 用脱敏生产结构 fixture 重放 956 成功链和 755/756/757 停滞链，验证数量守恒。
- [ ] (operations) 运行独立只读代码 review；修复 finding 后在同一 reviewer 上下文复审。
- [ ] (operations) 重新读取 spec/design/test/tasks/rollout，检查角色、状态、开关、测试和发布顺序一致。

## 4. 用户交付确认前的候选包

- [ ] (operations) 固定 PR、commit、image、policy/registry SHA、是否有 migration、配置变化、服务重建范围和回滚 image。
- [ ] (operations) 计算新备份、新镜像、runtime 增长和 8 GiB 保底所需磁盘；不足时不请求发布执行。
- [ ] (operations) 给用户提供一次 G2/G3 发布包选择：只合并不发布，或合并并执行精确发布包。
- [ ] (operations) 如选择提前单独交付审计修复：确认修复命令可切割为独立 G2 发布包（只含修复命令与既有表，不含自动化开关）。

## 5. 获得发布确认后

- [ ] (operations) 在 shared deployment lock 下创建并验证 PostgreSQL custom-format 备份和配置/镜像恢复点。
- [ ] (operations) 以 10 flags false、专用 worker stopped 的关闭态部署候选，确认 migration leaf 精确且 `race_live` 不变。
- [ ] (operations) 先运行 policy v2 的未来/恢复双 census 只读验收：分类守恒、route ambiguity=0、无意外 enrollment。
- [ ] (operations) 按 future discovery -> network/time/racecard -> lifecycle -> result apply/public -> correction 顺序启用。
- [ ] (operations) 执行 755/756/757 一次性审计修复（可先于本变更发布窗口独立执行）：来源证据复核、候选 SHA、dry-run、备份、批准、apply、verifier、公网验收；修复窗口内确认无自动化任务触碰目标赛事。
- [ ] (operations) 等待至少一场新的 today/tomorrow 赛事自然完成 identity、enrollment、time/racecard 和 lifecycle。
- [ ] (operations) 等待正式赛果自然公开，核对任务、数据库、claim、revision、publication、页面和 SLO。
- [ ] (operations) 完成一轮自然无变化 correction 验收；真实 correction 作为持续监控，不生产造数。
- [ ] (operations) 复核 lock absent、四服务 exact、restart/OOM=0、资源、三队列、root/www/healthz。
- [ ] (operations) 将最终生产事实写回 current_state、decisions、deploy_runbook、project_overview、project_status 和本 change rollout。
