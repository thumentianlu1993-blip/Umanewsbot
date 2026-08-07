# Lifecycle shadow 观察加固测试用例

## 1. 测试先行与 RED

实现授权后先新增测试并运行，RED 必须精确来自：

- `shadow_proposed` 仍使 `consecutive_failures` 增加；
- proposal duplicate 未清除既有失败；
- scanner 未传运行配置，worker 漂移只返回普通 disabled；
- 缺 `--no-deps` 的 wrapper `run` 仍会调用 fake Docker；
- 宿主一致性检查脚本尚不存在。

不得接受 fixture、导入、语法、migration 或 fake harness 错误作为 RED。

## 2. Application / Celery

1. 新建 shadow proposal 后 `last_success_at=now`、`consecutive_failures=0`、error 为空，event
   仍为 scheduled，只有一条 proposal。
2. control 预置失败计数后命中 proposal duplicate，失败计数归零、成功时间更新、无新增
   transition。
3. `decision_error` 仍增加失败计数，退避时间仍大于 now。
4. scanner dispatch kwargs 包含 expected enabled/mode，并继续路由 `celery`。
5. Beat 期望 `true/shadow`、worker 实际 `false/off`：返回固定 mismatch reason，logger error
   包含结构化字段，event/control/transition 零变化。
6. 期望与实际一致时正常产生 proposal。
7. 旧消息不带新参数时可正常反序列化，并保留现有 gate 行为。
8. 两 worker 重复执行仍只产生一条 proposal，失败计数最终为 0。
9. 完整 claim 时序：scanner claim 后以“已 claim 状态”为 task 调用前快照；mismatch 不产生
   额外业务写；TTL 前不重领；TTL 后 token/claim generation 更新；旧消息零写；修复配置后的
   新消息成功并清空 claim。每次真实 mismatch 只产生一条对应 error log。

## 3. Shell / Compose

10. wrapper `run --rm web ...` 在 fake Docker 调用前失败。
11. wrapper `-f FILE run --rm --no-deps -e A=B -e C=D web ...` 和 `--file=FILE` 形状原样
    调用 Compose，覆盖最新 Release B preflight。
12. `run --rm web command --no-deps`、未知/缺值 run option、`--` 前无 service 均失败；command
    argv 中的字符串 `run` 不会让 `exec/config/ps/up` 被误判。
13. 子命令前的 `--ansi never run ...`（未纳入 allowlist）、`--foo=run`、缺值 `-f` 和 global
    `-- run ...` 均在 fake Docker 前失败；合法 global options + 非 run 命令原样传递。
14. 仓库最新 main 的全部 wrapper one-off 均匹配 canonical grammar；release、Release B 和 P0
    one-off 的锁断言保持 load-bearing。
15. `config/ps/exec/up` 及其 allowlisted global options 原样传递。
16. 仓库受支持部署入口中的 wrapper one-off 均含 `--no-deps`；release 与 P0 one-off 的锁断言
    保持 load-bearing。
17. 一致性脚本对同 project/release/image/commit、同 `true/shadow` 的三服务返回 0。
18. 跨 project 双 worker/Beat、运行 one-off、project label 异常、三服务同一但非预期旧 image、
    错误 commit、wrong working directory、flag 缺失/重复/不一致均非零且零 mutation。
19. 任一 expected production 参数缺失、服务缺失/多 CID、stopped/restarting 或 inspect 失败均
    非零。
20. 环境输出只包含允许的 lifecycle 键，不泄露其他配置。
21. mode switch 锁竞争时零 Compose/零文件写；两 env 的路径、owner、0600、non-symlink、唯一
    key 任一失败均在 stop Beat 前拒绝。
22. enable 方向的第二份 rename、web 已重建、worker 重建一半、pre-Beat 核验、Beat 启动、Beat
    已启动后的最终核验失败，均收敛两 env 和 web/worker 为 false/off，Beat stopped，并验证
    runtime；不得只断言文件。
23. disable 方向任一步失败都不得恢复 true/shadow 备份；继续收敛 false/off。运行态恢复自身
    失败时尽力停止 worker/Beat、保留锁/备份/证据且非零退出。
24. 成功路径顺序精确为 lock→stop Beat→双文件替换/复核→web/worker→pre-Beat verify→Beat→
    final verify→release；web/worker/Beat 均使用 `--no-deps --force-recreate`，且不调用 scanner、
    race-live 或业务写命令。pre-Beat verify 允许 expected project 的旧 Beat 容器处于 stopped，
    但拒绝任何 project 的 running Beat。

## 4. 回归

25. 既有 lifecycle/enrollment SQLite 聚焦套件。
26. PostgreSQL claim/concurrency 套件。
27. `stable.test_single_migration_owner`、Release B 部署合同与
    `stable.test_race_live_p0_deployment_contract`。
28. Django check、`makemigrations --check --dry-run`、`sh -n`、两份生产 Compose config、
    `git diff --check`。

## 5. 生产形状验收（不属于自动化测试）

1. 关闭态部署后，宿主一致性脚本确认三服务来自同一隔离 release、同一 image、`false/off`。
2. 单独授权恢复现有 16 场 `true/shadow` 后，再次确认同 release/image/flags。
3. R1 前从既有 16 controls 冻结 2–4 场“尚未到 T、至少覆盖日本和英国”的精确观察清单，
   并记录 event ID、T、T+30、时区和 manifest/revision。若没有足够样本则 NO-GO。
4. 若实现/审核期间错过原计划窗口，只能重新生成并人工核对未来清单；不得用既有 proposal、
   补采旧边界或手工 scanner 冒充自然观察。
5. 每个边界允许 Beat 5 分钟调度误差及 worker 有界处理时间；核对 proposal、result code、
   failures、claim、队列和日志。
6. 任何 applied、公开状态变化、三服务 flags 漂移、重复 transition 或 claim 超 TTL 均 NO-GO。

## 6. 2026-08-08 真实 RED 证据

测试先行子代理新增 `server/stable/test_lifecycle_shadow_hardening.py`，实际命令为：

```text
cd server
/Users/mentianlu/Code/umanews/.venv/bin/python manage.py test stable.test_lifecycle_shadow_hardening -v 2
```

结果：发现 28 个测试，`FAILED (failures=38, errors=4)`；其中 subtest 会分别计入 failure。
失败全部对应尚未实现的目标合同：

- shadow proposal 与 duplicate 的 `last_success_at` 仍为空，失败计数未归零；真实
  `decision_error` 测试已通过并证明既有失败退避基线未被测试夹具破坏；
- scanner dispatch kwargs 缺少 expected runtime 字段，advance task 尚不接受对应参数，旧消息
  兼容测试已通过；
- wrapper 对缺 `--no-deps`、command argv 假 `--no-deps`、未知/缺值/歧义 option 仍直接调用
  fake Docker；合法 Release B 与非 run 透传形状已通过；
- `deploy/verify_lifecycle_runtime_coherence.sh` 与 `deploy/switch_lifecycle_mode.sh` 尚不存在，
  对应 fake-host 合同以明确的 missing-script assertion 失败；
- `deployment_lock.sh` 尚未 allowlist `lifecycle-mode-switch` action。

首次误用 worktree 相对路径 `../.venv/bin/python` 得到 exit 127，未被计作 RED；随后使用仓库主
虚拟环境的精确绝对路径重跑，Django test database、migration、fixture、语法和 system check 均
正常，以上 RED 均来自目标能力缺失。

## 7. 首轮代码 review findings 的测试先行证据

独立 reviewer 首轮提出 5 项 actionable finding 后，测试子代理只扩展既有 hardening 测试文件，
限定命令为：

```text
cd server
/Users/mentianlu/Code/umanews/.venv/bin/python manage.py test \
  stable.test_lifecycle_shadow_hardening.LifecycleShadowAttemptTests.test_proposal_duplicate_identity_conflicts_fail_closed \
  stable.test_lifecycle_shadow_hardening.LifecycleModeSwitchContractTests.test_old_checkout_cannot_mutate_a_different_physical_release \
  stable.test_lifecycle_shadow_hardening.LifecycleModeSwitchContractTests.test_enable_preflight_verifies_running_false_off_before_any_mutation \
  stable.test_lifecycle_shadow_hardening.LifecycleModeSwitchContractTests.test_every_compose_mutation_is_bound_to_expected_project_identity \
  stable.test_lifecycle_shadow_hardening.LifecycleModeSwitchContractTests.test_production_canonical_env_is_a_non_overridable_trust_root \
  stable.test_lifecycle_shadow_hardening.SupportedDeployOneOffInventoryTests.test_all_deploy_wrapper_run_calls_are_canonical_and_lock_contracts_remain \
  -v 1
```

结果：发现 6 个测试，`FAILED (failures=10)`；其中 proposal identity 的 6 个 subtest 分别计数，
one-off inventory characterization 已通过。逐项证据：

- 旧 checkout 可在 `EXPECTED_RELEASE_DIR` 指向另一物理目录时取得锁并完成切换，未在任何 mutation
  前拒绝；
- enable 的第一个 verify 仍发生在停 Beat、改文件及重建 web/worker 之后，没有 running
  `false/off` 前置 census；
- mode-switch 的 Compose mutation argv 只有 `-f`，没有显式绑定 expected project directory/name；
- 生产脚本仍要求调用者提供 `CANONICAL_ENV_FILE`，没有把 `/opt/umanewsbot/.env` 固定为不可覆盖
  trust root；测试 harness 只在复制后的脚本中替换受审硬编码常量，生产脚本不获得测试绕过；
- proposal dedupe 碰到 event/kind/generation/reason/to/from 任一身份冲突仍返回成功 duplicate，清除
  failure；6 个字段冲突均取得 RED；
- 仓库当前三个受支持 wrapper one-off 已全部满足 `run --rm --no-deps`，Release、Release B、P0
  锁/调用合同也已存在，因此该项是新增的全仓 characterization GREEN，不伪造 RED。它将在未来新增
  非 canonical one-off 时失败。

首次将 `py_compile` 路径写成 worktree 根相对路径导致命令在测试前 exit 1，未计作 RED；修正为
`stable/test_lifecycle_shadow_hardening.py` 后重新执行以上限定测试，Django test database、migration
与 system check 正常。

## 8. 2026-08-08 GREEN 与主线程复验

- 首轮实现新增聚焦：`stable.test_lifecycle_shadow_hardening`，`28/28 OK`；review
  findings 测试先行后扩展至 `34/34 OK`。
- lifecycle/enrollment + 单一 migration owner + P0 deployment 与 hardening 合并回归：
  `291/291 OK`。
- 隔离 PostgreSQL 16：lifecycle claim/concurrency + enrollment concurrency，`6/6 OK`；临时
  容器结束后已自动删除，没有使用其他任务的数据库。
- Release B 直接部署合同：`1/1 OK`。
- `manage.py check`、`makemigrations --check --dry-run`、目标 `compileall`、workflow contract、
  四个 shell `sh -n`、两份 production Compose `config --no-env-resolution --no-path-resolution`
  和 `git diff --check` 均通过。
- 首轮 review 的 5 项 finding 已在代码层修复：proposal duplicate 六字段身份冲突 fail closed；
  mode switch 在锁前绑定物理 release、启用前核验运行态 `false/off`、固定 canonical env trust
  root、所有 Compose mutation 显式绑定 project directory/name；全仓 one-off inventory 合同保持
  load-bearing。以上修复仍须由同一独立 reviewer 复审，不能据此提前视为 APPROVED。
- worktree 在验证前快进整合至最新 `origin/main@11abe4bf2d2badbfe1daa2f5fdd8f8e97f5f0093`；
  主线工作流集中化与 Release B 证据增量未覆盖本 change 的应用/operations 文件。四份项目状态
  文档先移除本 change 追加段、快进后再追加，未覆盖主线记录。

## 9. 第二轮代码 review：跨 project 实例安全收敛 RED

第二轮 reviewer 指出：最终 coherence 若因其他 Compose project 的 running worker/Beat 或
running one-off 失败，现有恢复只按 expected project 的 service name 停止，不能让宿主收敛。
测试子代理新增 fake-host Docker census，限定命令为：

```text
cd server
/Users/mentianlu/Code/umanews/.venv/bin/python manage.py test \
  stable.test_lifecycle_shadow_hardening.LifecycleModeSwitchContractTests.test_final_coherence_failure_stops_only_verified_rogue_cids \
  stable.test_lifecycle_shadow_hardening.LifecycleModeSwitchContractTests.test_host_cleanup_probe_or_stop_failure_keeps_lock \
  -v 1
```

结果：发现 2 个测试，三个违规容器场景和三个失败注入场景共
`FAILED (failures=6)`。真实 RED：

- cross-project worker、cross-project Beat、expected project running one-off 三种场景均触发最终
  coherence 与 off 恢复 coherence 失败，但脚本没有执行宿主 `docker ps/inspect/stop`，只执行
  expected project 的 Compose `stop beat worker`；违规 CID 仍运行；
- fake host 同时提供无关 nginx CID，测试要求只可停止经过 running/service/project/oneoff label
  逐项验证的违规 CID，禁止按名称、宽 selector 或顺带停止无关容器；
- host enumeration、单 CID inspect、单 CID stop 分别注入失败时，测试要求非零且保留共享锁；现有
  脚本完全没有进入宿主 census，因此三个阶段调用证据均缺失。

fake verifier 只在 final `running/shadow` 和其后的 recovery `stopped/off` 暴露违规实例；前置
`running false/off` 与 pre-Beat `stopped shadow` 均保持成功，因此 RED 精确落在 reviewer 指出的
最终失败恢复路径，不是 fixture 或阶段序号错误。

## 10. 第三轮代码 review：Umanews 身份约束 RED

第三轮 reviewer 指出第二轮修复仅依据通用 `worker/beat` service name、project 是否不同和
one-off 标记决定 `docker stop`，可能停止其他应用。限定命令：

```text
cd server
/Users/mentianlu/Code/umanews/.venv/bin/python manage.py test \
  stable.test_lifecycle_shadow_hardening.LifecycleModeSwitchContractTests.test_final_coherence_failure_stops_only_verified_rogue_cids \
  stable.test_lifecycle_shadow_hardening.LifecycleModeSwitchContractTests.test_untrusted_generic_service_names_are_never_stopped \
  -v 1
```

结果：发现 2 个测试，`FAILED (failures=6)`。真实 RED：

- `other-app` project 的 worker 与 Beat 使用不受控 working directory、其他 image ID/revision，仍被
  精确 CID `docker stop`，之后错误地释放共享锁；
- `umanews-evil` 混淆 project 前缀即使指向看似可信路径仍被停止；测试另覆盖
  `umanews-evil` working-directory 前缀，防简单字符串前缀绕过；
- 可信旧 Umanews worker/Beat（expected project、受控 release 形状、精确 image/revision）尚未被
  自动停止；running one-off 虽被停止，但实现未读取/核对 working directory、image ID 和 OCI
  revision，因此正例的严格身份验证断言 RED；
- service/project label 缺失、oneoff/running label 异常、错误 image 和错误 revision 均作为
  fail-closed 负例保留：不得停止，必须非零并保留锁；无关 nginx 始终不得停止。

fake Docker 为每个 CID 分离提供 service/project/oneoff/running/working-dir/image/revision，测试要求
停止授权必须来自完整身份核对而不是名称；测试没有调用真实 Docker、网络或生产路径。

修复后主线程重新验证：hardening 扩展为 `37/37 OK`，与 lifecycle/enrollment、单一 migration
owner、P0 deployment 合并为 `294/294 OK`；隔离 PostgreSQL 16 `6/6`、Release B deploy
contract `1/1` 与全部静态门禁再次通过。恢复路径采用两阶段授权：先核验全部 CID 的精确 project、
物理 working directory 边界、image ID、OCI revision、service/one-off/running，再只停止可信旧
Umanews worker/Beat 或可信 running one-off；other-app、混淆前缀和无关容器均不停止。任一身份或
Docker 操作失败均保留锁并非零退出。本结论仍等待同一 reviewer 第四轮复审。

同一独立 reviewer 第四轮限定复审最终 `APPROVED`：原生
`codex review -c 'sandbox_mode="read-only"' --uncommitted` exit `0`，内层启动头为
`sandbox: read-only`；独立复跑 hardening `37/37 OK`，审前/审后 fingerprint 逐字节一致。
非阻塞建议是未来增加“首个可信候选后跟无效 CID”的单独用例；当前两阶段实现已先完成全量核验，
再执行候选 stop。写回本段后须重新冻结最终 fingerprint，不能复用审核前 content hash。
