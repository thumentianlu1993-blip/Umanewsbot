# 生命周期全量 enforce cohort 测试

## 1. 真实 RED

1. 3 场以上、升序唯一成员可构建/加载 registry；旧代码因 exact-two 失败。
2. 同一 registry 可聚合多个 strict enrollment SHA；旧代码因 single-source SHA 失败。
3. P2/非 featured 合格赛事被 selector 纳入。
4. draft/hidden、非 scheduled、取消/延期、manual lock、缺日期、未知地区、错误时区、美国空
   allowlist 被逐原因排除。
5. registry 声明范围缺 control 或 census 少/多成员时 prepare/activation 零写失败。
6. 一名成员 schedule/generation 漂移时 promotion 不产生部分 active cohort。
7. 相同 artifact replay 不修改 `updated_at`、不重复 OperationLog。
8. 范围外、旧 root、inactive、错误 SHA/activation 的 enforce control 零 claim/零 applied。
9. 旧激活排队任务在 off/rotation 后零写。
10. 250 个 due controls 按 100/100/50 claim，交集为空，第四轮为 0。
11. 单场验证不加载/锁整个 201 成员 cohort。
12. legacy event 186 canary provenance 保持可读；event 187 可安全迁入新 registry。
13. census 后新增赛事、blocked→eligible 更新进入 successor pending；cutoff 前成员漂移阻断 activation。
14. predecessor retirement 与 successor activation 同事务；due legacy/旧 generation member 均零 claim。
15. 有时间 authority boundary、无时间当地次日/DST、registry 到期和跨到期排队任务均 fail closed。
16. 数据库存在 30 天外合格赛事时，`datetime_7d_canary` 仍能按 scope 精确激活；`full_eligible` 少任何
    合格赛事必须拒绝。
17. 无时间赛事在 `no_time_canary` 之前不属于 active membership，验收后才能进入 full scope。
18. 7/30 天窗口端点、相同 T 的 event ID 排序、>100 稳定截断与 predecessor 超限 fail closed。
19. `no_time_canary` successor 不丢失仍合格的 predecessor datetime 授权。

## 2. PostgreSQL

1. 同一 registry 并发 promotion 结果为 applied+replay，cohort 完整；
2. 不同 registry 并发竞争只允许一个完整赢家，失败方零部分写；
3. 两 scanner 对 >=200 due controls 使用 `skip_locked` 得到互斥批次；
4. 两 worker 同一赛事只产生一次 applied transition；
5. promotion 在 mutation 后制造审计失败时 control/evidence/log 全回滚；
6. 单场 apply 锁范围不随 registry 成员数增长。
7. 数据库条件唯一约束拒绝两个 active registry；membership `(registry,event)` 不可重复。

## 3. 运维合同

1. 新 registry trust root 在 canonical/active env 各键恰好一次，web/worker/Beat 完全一致；
2. legacy canary 与 registry trust root 不可同时启用；
3. artifact 必须 regular、非 symlink、mode 600、有界、canonical、raw/content SHA 正确；
4. false/off promotion 前验证 release/image/commit、共享锁、无 lifecycle active/reserved/claim；
5. web healthy、worker coherence、registry activation 成功前 Beat 不启动；
6. 任一步失败恢复 `false/off`，Beat 不启动，race-live 不触碰；
7. 扩容 generation 必须绑定 predecessor，成员摘要不匹配拒绝；
8. 旧 v1 auto-discover 不可达。
9. registry 到期前 72 小时 rotation 告警；到期后 scanner/task 零写。
10. `false/off + 非空 env root` 必须启动失败；env root 已清但独立 artifact 完整时旧 disarm 可成功；
    artifact 缺失时后续零执行。
11. 数据库或原始 env 备份失败时零 env 写、零 disarm、零 migration；备份内容必须来自清 root 前版本。
12. legacy disarm 只接受旧 artifact 独立冻结的 40-hex approved commit，不能借用新 registry release commit。
13. promotion 在 backup 前依次停止 Beat、drain/停止 worker；任一 probe/drain/stop 失败后续零备份后写入。
14. promotion 成功留下 Beat stopped，registry switch 只对此路径接受 stopped admission，且 Beat 始终最后启动。
15. DB activation 后 env/rebuild 故障收敛 false/off；同 artifact 重试复用严格校验所得既有 activation ID，
    错 root/membership/count/ID 均 fail closed。
16. caller membership SHA/count 在 activation 前与 artifact、DB 双重绑定；最终验证同时覆盖 env resident 与
    DB root/membership/count/activation 四元组。
17. promotion recovery 的任一 env rewrite、容器重建或 false/off coherence 失败均保持 Beat/worker 停止、
    不 release 共享锁并保留证据；只有精确验证 false/off 后才可释放锁。
18. promotion wrapper 只接受单行 `outcome/batch_members/total/remaining` canonical 输出；total 必须固定，
    partial 的 remaining 必须按 1–100 的 batch 单调下降，applied/replay 只能在 remaining=0 终止；旧字段、
    多行、未知 outcome 或矛盾计数均 fail closed。
19. 首代 registry（空 predecessor）必须提供独立 legacy artifact/SHA/approved commit/186,187 并完成 disarm；
    successor（64-hex predecessor）禁止 legacy 参数且 canary verifier 不可达；非法 predecessor 在锁和服务
    变更前 fail closed。

## 4. 回归

- 既有 lifecycle 时间、DST、延期、取消、无时间次日、幂等、缓存测试；
- strict v2 enrollment 1–20 场及不同 manifest 不覆盖 provenance；
- 双赛事 canary 历史安全测试保留并参数化，不以降低断言获得 GREEN；
- race-live 零 dispatch、QQ 零发送、新闻门禁不受影响；
- Django check、migration drift、shell syntax、workflow contract、`git diff --check`。

## 5. RED 真实性与性能证据

- 所有 RED 必须成功收集；失败必须是目标行为 assertion，不接受 ImportError、未知命令、fixture、迁移、
  语法或环境错误。新增模型/命令测试可通过现有 app registry/`call_command` 捕获并转换为带明确能力
  文案的 assertion failure，不能让测试加载阶段报错。
- 保存每项 RED 的测试名、失败断言和目标能力映射。
- O(1) 测试比较 1、201、1001 成员时单场验证的固定查询数，并检查 SQL 不出现全成员 `IN (...)` 或
  Python 全量迭代；PostgreSQL 并发测试同时读取实际锁定 relation/tuple 范围。
- fault injection 分别覆盖 promotion 批内回滚、最终 activation CAS 失败、registry receipt/OperationLog
  写失败，确认 registry/membership/control/log 无部分状态。
