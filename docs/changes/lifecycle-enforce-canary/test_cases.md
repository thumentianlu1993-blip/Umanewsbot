# lifecycle enforce canary 测试矩阵

## RED 取得要求

先新增测试并在未实现代码上运行。RED 必须分别证明：canary prepare/apply 命令不存在或拒绝目标行为、
`true/enforce` 仍被脚本拒绝、运行时 enforce 缺少 canary 证据仍会写入。fixture、迁移、导入或 shell
语法错误不计有效 RED。

## Manifest 与 apply

1. prepare 生成恰好两场、canonical、带 raw/content SHA 的只读 artifact。
2. 单场、三场、重复 ID、未知字段、apply 过期、runtime window 不覆盖最晚 T+30+24h、错误
   SHA/OID、symlink/超限文件拒绝。
3. apply 非 false/off、未确认、manifest/expected commit 不一致时零写。
4. event/control updated_at、status、visibility、时间、时区、schedule hash/generation、enrollment SHA
   任一漂移时两场全部零写。
5. 任一 active claim/manual pause 时全部零写。
6. 合法 apply 只把目标 control shadow→enforce，其他 control 保持 shadow。
7. 范围外已有 enforce 时 verifier/apply 拒绝；PostgreSQL 两个不同 cohort 并发 promotion 最多一个成功。
8. manifest_data 和 OperationLog 包含精确原值、新值、raw/content SHA、commit、event IDs。
9. 同 manifest 重放零 control 更新时间变化、零重复日志；不同 manifest 冲突拒绝。
10. promotion 精确写 inactive/空 activation ID；activation 两场原子 CAS 为 active/同一 ID；部分 active、
    ID 不同、不同 manifest、并发 activation 均拒绝或安全重放。

## Runtime

11. enforce control + 匹配 active canary 在 T 产生 scheduled→running applied，公开状态更新且缓存失效。
12. T+30 从 running→finished；直接从 scheduled 补采也只产生一次 applied。
13. 缺 canary、错误 env SHA/IDs、event 不在 env cohort、generation/hash/enrollment 漂移均不写状态。
14. 范围外 enforce control 即使带自洽伪造 canary evidence 也不能公开写。
15. 其他 shadow control 在 global enforce 下仍只 proposal。
16. 两 worker 并发/重复任务只有一次有效 applied 与一次缓存失效。
17. web/worker 已是 enforce 但 activation 未完成时，queued scanner 实际运行仍零 claim/零 applied；
    已排队任务在 runtime 改 off、mode、pause、visibility 或
    canary 握手漂移时零写。
18. apply 24h 窗口到期后，event 187 在其 T/T+30 前仍处于合法 runtime window。
19. cancelled/postponed 与赛果字段语义不回归；不伪造临时/正式赛果。

## 部署脚本

19. promotion wrapper 在 shared lock 内做宿主 false/off 前后核对；锁竞争或 resident 漂移时零 DB 写。
20. true/enforce 缺 manifest/SHA/精确 `186,187` 参数时，在 compose/env mutation 前拒绝。
21. preflight verifier 失败：零 compose mutation、零 env 写、释放锁。
22. stdin loader 拒绝空、截断、超限、尾随额外字节和错误 SHA；current/recreated web 接收相同 expected SHA。
23. 成功顺序：lock→false/off coherence→stdin canary verify/disarm→stop Beat→rewrite→web only→
    stdin DB verify→worker→web/worker coherence→stdin atomic activate→active verify→Beat→final coherence→release。
24. DB verifier 前不得启动 worker；verifier/activation/final coherence 失败均收敛 false/off，Beat/worker 安全。
25. 三服务 canary env SHA/IDs 不一致时 verifier fail closed。
26. true/enforce→false/off 不依赖 manifest 可用；旧 queued task 被事务内 gate 阻断。
27. 不启动 race-live、不手工调用 scanner、不发送 QQ、不访问网络。

## 回归与静态检查

- lifecycle/enrollment/shadow hardening 聚焦套件；
- PostgreSQL claim/apply 并发套件；
- Django `check`；
- `makemigrations --check --dry-run`；
- `sh -n`、workflow contract、`git diff --check`；
- 受影响部署脚本 fake harness 查询/调用序列断言。

## 实现前 RED 证据（2026-08-10）

聚焦命令：

```bash
cd server
/Users/mentianlu/Code/umanews/.venv/bin/python manage.py test \
  stable.tests.test_lifecycle_enforce_canary
```

结果：`Ran 4 tests`，`FAILED (failures=4)`；测试完成收集、数据库创建与 Django system check 均正常。
四项失败均由目标防护尚未实现导致：

- 范围外、control 内自洽伪造的 enforce evidence 当前仍得到 `action=applied`，公开状态会被修改；
- 两条 `activation_state=inactive` 的 canary control 当前仍被 scanner claim（实际 `claimed=2`）；
- mode switch 尚不接受 `true/enforce`，也没有独立 canary SHA/IDs、有界 stdin 与分阶段启动合同；
- `false/off` recovery 尚未清空 canonical/active env 的两项 canary trust root。

这些 RED 不来自导入、fixture、迁移、语法或环境错误。

实现后主线程新增一项 load-bearing RED：active canary 存在时，范围外 `mode=shadow` control 被 scanner
claim 后旧实现返回 `noop`，没有生成 proposal；根因是 canary cohort 门禁早于 per-control effective mode。
最小修复改为仅当目标 control 自身为 enforce 时按有序 cohort 预锁并校验。修后聚焦与组合回归
`142/142 GREEN`；隔离 PostgreSQL 16 两份不同 cohort 并发 promotion `1/1 GREEN`，证明 advisory
transaction lock 最终只允许一份 promotion 成功。

## 第 1 轮代码 review RED/GREEN（2026-08-10）

独立 reviewer 首轮结论为 `REVISE`，提出 3 项 P1 与 1 项 P2。主线程先补四条 load-bearing 测试并确认
旧实现真实失败：

- promotion command/wrapper 未把独立授权 IDs 传入并与 manifest 比较；
- global enforce scanner 会给范围外 enforce control 写 claim；
- 首次发布旧 resident 缺少 canary 空键时，严格 false/off coherence 错误失败；
- event 合法推进后，同 manifest 的 disarm/reactivate 因比较动态快照失败。

修复后新增测试分别锁住：写前 ID mismatch 零写、真实 scanner 零 claim/零 dispatch、false/off 缺键
bootstrap、合法进展后的新 activation ID。当前组合回归 `146/146 GREEN`；隔离 PostgreSQL 16 并发
promotion `1/1 GREEN`。Django check、`makemigrations --check --dry-run`、四个 shell `sh -n`、workflow
contract 与 `git diff --check` 全部通过，隔离容器已删除。

第 2 轮 reviewer 确认前三项 P1 已关闭，但指出 reactivation 仅检查状态枚举，不能证明状态来自本
canary。主线程新增“外部直接把 event 改为 running、无 canary applied transition”负例，旧实现真实
RED；修复为 applied transition 写 canary provenance，并在 reactivation 时验证精确状态链、generation、
reason、T/T+30 时间连续性与 manifest/activation 证据。修后组合回归 `147/147 GREEN`，PostgreSQL
并发专项再次 `1/1 GREEN`。

第 3 轮同一 reviewer 复核 metadata 构造点、applied 创建路径、外部/普通 transition 拒绝与合法
reactivation 正例，结论 `APPROVED`，无 P0/P1。记录 1 项非阻塞 P2：首次 tick 已过 T+30 时，现有
状态机允许带 canary provenance 的 `scheduled→finished` 合法补采，但同 manifest reactivation 当前只
接受两段 finished 链；该限制不扩大写入范围、不影响首次 canary，可在后续恢复兼容性 change 增补。
