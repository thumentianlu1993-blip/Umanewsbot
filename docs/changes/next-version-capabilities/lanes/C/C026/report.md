# C026 ORM loader/detail 局部实现交付

任务 `C026-O03-ORM-LOADER-DETAIL-IMPLEMENT-001`，按 C024 `aa1b0bd060d71463cfc0f94d452ef53b1f0aad18` 与原 R `f3199e5fa049768ea6505caf6c2a5c3d01426e63` 的已审方案实施。局部实现及诊断测试已完成，待 ROOT 登记实际 mapping 并交同原 R 独立 review；未 push、更新 PR、合并或发布。

## 固定来源及范围

- 新 managed worktree `/Users/mentianlu/.codex/worktrees/c026-orm-loader-detail/umanews`，独立分支 `codex/c026-orm-loader-detail`；工具初始 detached 已在此 worktree 纠偏，旧工作树保留。
- stacked 起点 `78c65869166d3f56b0f8fc8469e8415dd78be121`，依赖未合并 PR238；不修改其候选。
- 真实 RED source `519792c74edb85330e25d003549493597acfb692`：fixture 已通过真实 gate/Client200，唯一 failure 为无行为桩返回 None，没有独立 snapshot。
- 最小两项 GREEN source `ad7d1f1eb9a5762bee745ddcac6547b45789731f`。
- 最终 15 项 source `e7e67d47e858a762f40170d8f575666333423eda`；其 tree 与 content_digest 在 `module-plan.json` 绑定。报告提交另保存最终 HEAD/parent。
- 仅新增 `public_probe_orm_loader.py`、`test_public_probe_orm_loader.py`、独立 `public_probe_orm_fixture.py` 及本 C026 文档；无 stable.tests 重导出。views/templates/adapter/models/settings/shared runner/mapping 均未修改。

## 实现行为

`load_public_result_snapshot(event_id, canonical_subject, audience, as_of)` 只接受正整型单 event、严格相对 canonical detail 路径、anonymous、aware time。外层事务/关闭 autocommit 明确拒绝。两个短顶层事务分别先设置本事务只读 REPEATABLE READ：第一个物化 published/canonical、现有 read gate、revision/observation/items、显式 source identity 对应的 projection；退出后在新事务重新读取版本/配置/可信 standing-policy 与现有 gate，使用新的观察时点复核有效期。发生变化返回 `input_changed`，不重试、不签响应 proof。

DTO 为 frozen dataclass 与 tuple，仅返回白名单字段和内部版本摘要，无 ORM/lazy manager/raw payload/文件路径/审计人。单组最多200行、序列化256KiB，超限 unverified，不截断称完整。绑定依赖 source_key/external_race_id/external_runner_id 与 ParticipantSourceIdentity 唯一对应，名字/名次/下标不用于身份推断；身份成立后独立比较 revision item 与 projection 字段。

沿现有分支保留 multisource 已发表版本仅 fetch 到期不撤销的规则；撤销身份时拒绝。历史页面缺 current 证据仍保留原 view200，loader unverified；legacy301独立处理，hidden/draft404不改页面语义。未接生产 view/模板/adapter，无网络或 writer 调用。

`read_boundary_loaded` 仅表示本地读取边界。real_source_proof/response_binding/SLA 始终 unverified、projection_complete=false；source时间、execution及完整F01 generations 缺失有 missing 标识。不签 O03/public_verified；复核之后的页面变化、真实 response binding、活性、CSS/SLA仍未完成。field provenance fallback 无法逐字段严格对账时保持 unverified，不扩大为完整来源证明。

## 实际测试与技术恢复

先冻结完整 `test_cases.md`，再最小 RED→同例 GREEN→必要新模块验证。所有诊断计划为手工精确 ID 枚举，**不是 collector 或 formal impact/full 证据**；base/head/test/tree/content_digest由既有 git_input.inputs 绑定，不带旧全套 domains/skips/test_ids。

| 阶段 | 实际结果 |
|---|---|
| 最小 RED 两项 | fixture/gate/Client项通过；snapshot None目标断言1 failure；0 error/skip，teardown成功 |
| 同例 GREEN 两项 | 2项通过，0 failure/error/skip，teardown成功 |
| 最终新模块 | 15项实际执行，canonical ID多重集合精确一致，无重复；0 failure/error/skip，lifecycle complete/exit0 |

最终覆盖：input边界、合法匿名Client/context/content独立对账、同名强身份、隐藏/草稿/unknown/失配path、legacy301和历史缺件、过期/拒绝live source、observation漂移、PG publication不可变约束、projection缺身份/字段冲突、外层事务拒绝、真实只读RR与异常恢复、快照内writer已提交仍见旧版本而新读检出变化、policy/event/projection变化、multisource fetch expiry/identity revoke、行数上限、复核时点权限到期。

原两项前四轮均为 fixture/setup 缺件，不计 RED：publication audit与published必须同事务按顺序提交、current pointer必须低于next_revision_no、现有TRA provisional gate要求route/terms摘要。完整模块首轮12项通过、2项fixture违反PG不可变规则；修为合法预先创建official multisource版本，以及断言已发表audit不能被删除。未禁用触发器或修改资格规则；相关原日志均按 setup 分类保留。

环境为标准隔离PG16.15/CPython3.12.3/Django5.2.1；缓存镜像 `sha256:ab8494e6202dced04a6c2b5b885b3d1f2d9c80776ec8ae8d97f3552aae6b3ecc`。源/控制只读挂载，无外网，仅容器PG loopback；isolation报告 external Python/curl/nested Docker blocked。未下载/构建镜像，未使用真实DB/Redis/队列/provider。

## 资源和交接

ROOT将原标准窗口转交到北京时间14:36（含清理）；每次仅1容器、2CPU/4GiB/256PID/network none/read-only rootfs/cap-drop ALL/NNP。任务私有 DOCKER_CONFIG/context 固定既有 daemon，用户默认 context未改。最终容器 CID `e395e38aec7a109f5d6f701e7b6cce72091dc23846e95c048c608674c55200c6`，最小GREEN CID `9f37e72ec3c181ce9d3653743275870876f5a1d2b1b72ab0e06d4afc05469c94`，inspect已保存；其余观察到的CID以setup inspect/日志为准，不补造未获取完整ID。标准runner均自动清理，最终running=0，仅保留其他任务旧exited容器。ROOT负责释放分配状态。

证据目录 `/Users/mentianlu/.codex/runtime/c026-orm-loader-detail-001`：red-pg16、green-pg16、module-pg16与module-summary、各历史setup目录/计划、实际inspect、最终容器清单、15项test-ids及handoff-receipt。最初继承plan已单列历史，当前计划不继承旧batch元数据。

额度开始71%，最近两次72%；未触及73%/30分钟停止条件。14:36前完成清理和回传，不扩任务。原G1覆盖局部实施；门禁统一引用根 AGENTS.md。ROOT下一步登记15个实际IDs/mapping并交同原R，review返修仍在原范围执行；正式full和最终交付由ROOT协调。


## C026-R01 返修准备断点（待实际 RED）

原 R `f77ff5301fc1705517a389f3153b692156a76d41` 唯一P2指出确认标志直接复制projection，未独立核对writer phase规则。当前已修独立official fixture并添加两个错误标志反例；loader仍保留受审旧行为以取得实际RED。没有容器/PG执行，不能继承原15通过作为返修通过。当前ROOT占用窗口，已备最小两项诊断计划，等待调度；返修只涉及owned loader/test/fixture/C文档，不改views/models/writer/权限/schema/proof。起点2026-10-05 14:49:27 Asia/Shanghai，额度73%，本轮最多15分钟或74先到。


## C026-R01 实际返修完成（2026-10-05）

同原 R 唯一 P2 已完成本线修复，待原 R 限定复审，不将作者自验视作 review 通过。

- RED source `471c180cc2c655f3f83c8229d2702b9a58979c21`：provisional错误True与official错误False两个反例均实际失败，错误为 `read_boundary_loaded != unverified`；合法gate、正确值和loaded前置断言通过。2 failure、0 error/skip、teardown成功，属于行为RED，无setup失败。
- GREEN source `6dcea3d50c672154376566f63ec9deadca8324cf`：loader仅增加2行，按既有writer的revision.phase规则推导 expected_confirmation（official/corrected=True、provisional=False），不符返回projection_mismatch/unverified。独立fixture修为同规则，两个反例通过；不改view/model/writer/gate/schema/proof，仍允许合法provisional非confirmed表格。
- 同一GREEN source完整新模块17方法必要回归通过，原15+新增2；实际canonical ID多重集合精确且无重复，0 failure/error/skip，exit0/lifecycle complete，完整PG teardown成功。包含同名identity、multisource fetch-expiry与revoke、事务/并发、真实Client原语义。本轮没有重跑无关测试或formal full。
- ROOT重新分配标准窗口起点2026-10-05 14:59:51 Asia/Shanghai，12分钟资源上限；同样单容器/2CPU/4GiB/256pids/networknone/readonly/capdropALL/NNP，固定缓存镜像，私有context；完成提前清理，running=0，仅原无关exited容器保留。
- 原始证据 `/Users/mentianlu/.codex/runtime/c026-r01-confirmed-projection-repair-001`：red/green/module计划与原JSON/log、17项test-ids、summary、RED和模块实际inspect、owned-container-events及最终资源清单。计划均手工精确诊断，非collector或formal impact证据。GREEN瞬时inspect未捕获，实际CID从该独占窗口daemon events恢复，不伪造inspect。
- 实际RED CID `4dedc056e9baaa37b9c59d6bb436fa6dfd568e0547c1ec8eb8406276ae56fe94`，17项模块CID `eab89f4a05dcbcd3bc388e6a0613cde24da02b60668ba675eb45a4d8eadc9fa3`；全部自有容器由标准runner自动移除。未改默认Docker context/他人资源，无下载/构建/外部API/生产动作。
- 起点额度73%，在15分钟/74检查点前完成；资源分配由ROOT回收。本轮只局部修复原finding，mapping与原R官方指纹复审由ROOT协调，不自行新reviewer/合并/发布。
