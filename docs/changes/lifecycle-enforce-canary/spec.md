# lifecycle enforce canary 规格

## 目标

在不启用 race-live、不接入新数据源、不扩大赛事范围的前提下，为生产赛事 `186`、`187`
建立可审计、可验证、可回退的 lifecycle enforce 灰度能力。canary 启用后，现有生命周期时间规则
可以把这两场赛事的公开 `RaceEvent.status` 从 `scheduled` 推进为 `running`，并在 T+30 推进为
`finished`；临时/正式赛果仍由独立结果链路表示，不因本 change 伪造。

## 范围

- 复用 `RaceEventLifecycleControl`、`RaceEventLifecycleTransition`、现有 scanner/advance task 和
  `switch_lifecycle_mode.sh`。
- 新增严格的 enforce canary manifest prepare、关闭态 apply/verify 和原子审计。
- 允许受审入口从 `false/off` 切到 `true/enforce`，但必须绑定精确 manifest SHA 和 event ID。
- 将精确 canary raw SHA 与 event IDs 写入 canonical/active env 和三服务 settings，作为独立于
  control 的运行时信任根；运行时同时校验 settings、control 证据与当前 event。
- canary manifest 本次生产内容必须且只能包含 event `186`、`187`。
- 其他已纳管赛事保持 control=`shadow`；全局 enforce 下仍只生成 shadow proposal。
- 紧急停止继续使用全局 `false/off`；不依赖修改或删除 canary control 才能止写。

## 非目标

- 不启用或修改 race-live worker、赛果 polling、新闻门禁、QQ、provider API。
- 不修改赛事时间、赛果、参赛马或来源字段。
- 不新增生命周期状态、不改 T/T+30 规则、不补历史赛事。
- 不把 event ID 硬编码进应用状态机；精确范围由受审 manifest 与发布授权绑定。
- 本实现轮不 commit、push、PR、部署或写生产。

## 验收标准

1. prepare 只读生成规范 JSON，冻结代码 OID、apply 新鲜期限、运行有效期限、原 enrollment SHA、赛事/控制快照、
   schedule generation/hash 和目标 mode。
2. apply 仅在严格 `false/off` 下、单事务、逐行锁定后执行；任一赛事漂移则全部零写。
3. apply 只把 manifest 内 control 从 `shadow` 提升为 `enforce`，并在 `manifest_data` 与
   `OperationLog` 保存 canary SHA 和原/新值；同 manifest 重放零重复审计。
4. apply 拒绝非两场 manifest、已有 claim、manual pause、非 scheduled/非 published、时间/时区/
   generation/enrollment 漂移、范围外 enforce control；所有 promotion 由固定 PostgreSQL advisory
   transaction lock 全局串行。
5. promotion 只能经共享部署锁 wrapper 执行；管理命令的 settings 检查不能替代宿主三服务
   `false/off` coherence。
6. `true/enforce` 切换在任何 env/容器写操作前验证当前 `false/off` 运行态和 DB canary；失败零变更。
7. 运行时 event 不在 env cohort、env/control SHA 不一致、control activation_state 非 active、两场
   activation ID 不一致、manual pause/visibility
   漂移或全局/任务握手漂移时不产生 applied transition。
8. event 186/187 在 enforce 下各只产生一次有效 applied；缓存失效；重复任务不重复状态或审计。
9. 其他 control 即使携带自洽的伪造 canary block，也无法越过 env cohort；正常 shadow control 只 proposal。
10. 从 `true/enforce` 切 `false/off` 仍可用；任一切换失败收敛至 off，Beat 保持停止或恢复到已验证状态。
11. manifest 通过有界 stdin 进入 current/recreated web；不依赖未挂载的 host 路径或容器内临时文件。
