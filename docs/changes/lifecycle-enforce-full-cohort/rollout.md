# 生命周期全量 enforce cohort 发布方案

## 当前基线

- 仓库基线：`origin/main@4097e386ca6f50e2cf7f9332776a72a9a43fdfd6`；
- 生产运行镜像 revision：`a7e3783ff7d188481cecd421cd2595f43e9a706b`；
- 生产 lifecycle：`true/enforce`，canary IDs `186,187`；
- event 186 已于 `2026-08-11 16:05 +08` applied 为 running，并于 `16:35 +08` applied 为
  finished；各一条、范围外 applied 为 0；公开详情和日历显示“赛果待确认”；
- event 187 尚待自身 T/T+30；race-live 关闭。

## R0：代码发布前

- 保全 event 186 transition/control/page/log 证据；
- 独立 review 通过并冻结 fingerprint；
- 发布包明确 registry/membership migration、新 env keys、兼容顺序、服务重建和 false/off 恢复路径；
- 不把代码合并授权视为生产启用授权。

## R1：关闭态部署

固定顺序如下，任一步失败后续零执行：

1. 把旧 canary artifact、raw SHA、event IDs、approved commit 和 activation ID 保全为独立只读授权证据，
   不依赖随后会被清空的 env；
2. 取得共享 deployment lock，以容器 hostname 冻结 lifecycle worker 节点，先停止 Beat、等待该 worker
   active/reserved 双采样均归零，再停止 worker；drain/探测失败时不做备份后的任何写入；
3. 在 Beat/worker 已静止且任何 env/DB 写入尚未发生时备份数据库和原始 canonical/active env，记录
   mode 600、SHA-256、数据库
   catalog/可恢复性，并冻结旧 image/revision；任一备份失败后续零执行；
4. canonical/active env 同时改为 `false/off` 并清空 canary root，重建 web，验证真实 resident runtime；
   `false/off + 非空 root` 必须 fail closed；
5. 通过 stdin 和显式 SHA/旧 canary 独立冻结的 `LEGACY_CANARY_APPROVED_COMMIT`/IDs 把已保全 artifact
   传给旧兼容命令完成并验证 legacy disarm；不得使用新 registry 的 release commit 代替旧授权；单纯
   false/off 不能算 disarm，artifact 缺失时后续零执行；
6. 验证 DB canary evidence inactive、event 186/187 无 active runtime authorization、claim=0；
7. 部署新代码和 registry/membership migration；由新代码执行 186 terminal control 降级，187 如合格则
   迁入 membership，历史 transition metadata 不改；
8. 验证 migration plan、web/worker/Beat coherence、race-live 关闭、HTTP 健康。

旧 artifact/root 缺失或 disarm 失败时 fail closed，不继续 registry prepare/promotion。
上述 legacy disarm 只属于 `predecessor_root_sha256=""` 的首代 registry 迁移。successor artifact 必须携带
64 位小写 predecessor root，wrapper 不接受任何 legacy artifact/SHA/commit/IDs 参数，也绝不调用旧 canary
verifier；predecessor 缺失、类型错误或非 canonical SHA 均在加锁和服务变更前 fail closed。

## R2：只读 census 与 dry-run

冻结 aware UTC `census_cutoff` 和 allowlisted canonical `selector_scope/scope_sha256`（含 window 端点、
explicit IDs、limit、order、predecessor carry），输出全部 inspected、included、
blocked reason、blocked_by_scope；生成缺 control 的 strict v2 enrollment 批次和 registry artifact。
prepare/dry-run 前后业务表指纹一致。美国赛事无受审
allowlist 时阻断，不从 DB 自证。cutoff 后新增/更新赛事单列 successor pending。

## R3：false/off apply

先 apply/verify enrollment 批次（<=20），再 promotion 批次（<=100）；activation 事务重算
`eligible_at_cutoff ∩ frozen_scope`，
核对 registry count、membership SHA、范围外 active membership=0、claim=0，并同时 retire predecessor。
registry 在此前保持 inactive。任一失败不启动 Beat，不触碰 race-live。
进入 registry enable 时允许且只允许受审的 `false/off + Beat stopped` admission；最终仍按
web healthy、registry/DB/env 四元 root、worker coherence、Beat-last 的顺序恢复。

## R4：分级 enforce

1. `datetime_7d_canary`：UTC `cutoff <= T < cutoff+7d`，按 `(T,event_id)` 取前 20 场；
2. 第一档必须至少观察一场经新 registry 路径真实完成 T 与 T+30，并满足范围外/重复 applied=0、
   stale root blocked、页面与缓存一致；仅经过 30–60 分钟但没有边界事件不允许扩大；
3. `datetime_30d`：carry forward 仍合格 predecessor，再按 `(T,event_id)` 补至未来 30 天最多 100 场；
4. `no_time_canary`：carry forward predecessor，再加入明确受审无时间 IDs并真实验收当地次日规则；
   验收前无时间样本不进入 active registry；
5. `full_eligible`：重新进入 false/off，生成 predecessor-bound generation，覆盖 cutoff 时全部合格赛事；
6. 每档激活后恢复 Beat，验证 batch claim、applied 唯一性、页面/缓存、worker RSS、DB lock wait、
   queue age 和范围外零写。

## 停止与恢复

发现 revision/root/count/membership/schedule/generation/timezone 漂移、范围外或重复 applied、claim 泄漏、
O(N) 单场锁、worker/Beat/coherence/HTTP 异常或 race-live 被启动时，立即在共享锁内收敛 `false/off`。
保留 control/evidence/transition，不自动反向修改已经合法推进的赛事状态。

registry 距到期 72 小时必须进入 successor prepare；到期后 scanner/task 零写。successor retirement/activation
失败时 predecessor 保持唯一 active，不允许半切换。

若数据库 activation 已成功而 env rewrite/rebuild 失败，恢复路径保持 `false/off` 且 Beat stopped；同一
artifact 重试必须先以 raw SHA、membership SHA、member count 强校验数据库 active registry，复用其现有
activation ID，禁止生成第二个 ID。最终 verifier 同时比较 env resident 与数据库的
root/membership/count/activation 四元组。

promotion 自身的失败恢复不是 best effort：canonical/active env 清 root、web/worker 重建和 host-wide
`false/off + Beat stopped` coherence 必须逐项成功。任一步失败都再次停止 Beat/worker、保留 deployment
lock、artifact snapshots、数据库/env backup 证据，并明确要求人工恢复；禁止在未证明 false/off 时释放锁。

## 并行边界

设计、本地测试和 review 可与其他只读/代码任务并行；生产 census/apply、env 修改、服务重建和 Beat
切换必须由唯一 release coordinator 持锁执行，且不得与新闻批次、赛果 apply、迁移或其他生产写任务并发。
