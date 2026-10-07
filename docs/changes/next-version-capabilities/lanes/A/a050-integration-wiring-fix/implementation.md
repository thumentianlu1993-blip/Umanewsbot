# A050：A049 R01/R02 正式测试接线修正

从固定 `a6a456ce2645c96b2b698428cea034ab8537a7ed` 新建隔离分支
`codex/a050-integration-wiring-fix`。原 A049 和所有 lane 源码、测试断言、冻结包保持。
原 R 报告的两项 P1 是本次范围；源码仍未真实 collect/执行业务测试。
最终 commit/tree 与证据 SHA 在候选外
`/Users/mentianlu/.codex/runtime/a050-a049-r01-r02-integration-wiring-fix-001/receipt.json`。

## R01：profile 归属

catalog 只新增 `stable.test_horse_career_record_from_review` 与
`stable.test_managed_readonly_steps` 两条 `django` profile。旧 profile 条目完整保留；
其余 catalog 字段和 rules 不变。仍是 326 个 labels，原 42 ID、29 个新增业务声明
和原 skip 策略保留。A049 说明中“profiles 与基线不变”是当时的缺漏，本卡补齐。

## R02：实际冻结版本，而非宿主值

1. `run_test_plan.py` 校验正式 Git plan 的精确字符串 SHA/tree，解析 SHA 必须为真实
   commit，并核对其 tree；错误在 Docker 前拒绝。
2. 执行器按该 SHA 做 git archive，沿用受信 controls 的逐字相等检查，读取全部
   ls-tree 文件 mode/blob 和原 commit 对象。新的 stdlib `source_binding.py` 重算
   文件 blob、递归 Git tree、原 commit SHA，核对整个导出快照。多余、缺失、修改、
   符号链接和 mode 不一致均拒绝。
3. 已核验的 binding 与原 commit 原始字节写到只读 `/control`。它们由正式执行器
   产生，不从宿主 `A045_TEST_CODE_SHA` 或手写历史 SHA 取值；commit 对象还将 SHA
   与 tree 加密哈希绑定，单独伪造一个合法格式 SHA 不能通过。
4. 原 entrypoint 创建新的 synthetic commit 会改变实际 HEAD，令原 A 命令检查
   失败。因此必要闭包包含 `deploy/test-impact/entrypoint.sh`：仍复制到隔离临时目录，
   创建本地 Git 元数据，强制加入完整快照，write-tree 与原 commit tree 核对，
   写入原 commit 对象并把 HEAD 指向它。无需原父提交，也不复制宿主 Git 凭据。
5. worker 从只读 control 读取 plan/binding；在业务 setup 前重验内容、mode、tree、
   commit 和真实 Git HEAD。`.git` 是入口生成的元数据，不计入源码 tree；其实际
   HEAD 必须与正式 plan SHA 相等。其他多余文件不会被忽略。
6. 通过后 setup 清空环境，重建原隔离环境，再设置 `A045_TEST_CODE_SHA` 为上述
   已核验 SHA；不改原测试 guard。collect 与每个执行分片都走相同的绑定路径。

## 受信 controls 与依赖影响

变更 controls 为 `scripts/run_test_plan.py`、`scripts/test_plan_worker.py`、
`deploy/test-impact/entrypoint.sh`，并新增 `tools/test_impact/source_binding.py`。
helper 仅依赖 stdlib base64/hashlib/pathlib/re/subprocess；Git CLI 用于真实 HEAD 检查。
runner 原依赖 `git_input.py` 的 git/commit 和 core digest；worker 原依赖 core
的 digest/shard_tests、`run_bounded_stable_tests.py` 的 isolated_environment/flatten
保持。入口原 Dockerfile/Python/Git/PG 环境、只读挂载、network-none、非 root、资源
限制及 PG 清理逻辑不变；PG 在本卡没有启动。

`impact_ci.py` 的既有 `control_blobs` 枚举覆盖 runner/worker、deploy 目录和全部
`tools/test_impact/`，因此新 helper 自动进入版本凭据；无需改信任规则或工作流。
新静态正式计划保存全部 control path/blob 清单，供 R/ROOT 核验完整 control 闭包。
若使用候选外 `--controls` 包，必须重新审核并封存本候选上述文件和 helper；原 8 control
旧包不能覆盖新候选，执行器会在字节不等时拒绝。旧工具包从未修改。

## 离线验证与后续真实门槛

在既有 `scripts.tests.test_impact_delivery` 模块追加 10 个技术方法，不修改既有方法。
该模块共 21 项纯 stdlib 测试通过；新增方法随原 infrastructure/python profile 进入
正式全量，保留原模块的全部旧方法。它们不替换原 42 业务 ID，也不计入原 29 声明。

验证使用真实 collector/setup/main 函数，业务 loader、Django、Docker 边界以自有
合成对象替代，未导入候选业务测试。覆盖两模块全部 29 ID 的归属和缺少归属反例；
真实临时 Git 快照；缺失、错误类型、非法 SHA；错 tree、错 commit、改字节/mode、
缺失/多余/符号链接文件；宿主伪值被清除；真实 HEAD 不同；main 的 plan/binding
传递；正式执行器在 Docker 前拒绝不存在 commit 和错误 tree。日志和实际固定候选
archive/commit/入口恢复的独立离线检查在新 runtime，不能称为业务 collect。

原 15 A/B 文件、原业务测试字节及原技术测试类 AST 均核对不变。正式 affected/full
静态计划保留原 326 labels、原 skip 与 42 ID/29 声明；候选 collected/executed count
仍为 null。新增技术方法只扩大完整动态分母，不删旧方法。

原 R 窄复审后，由 ROOT 分配正式 full 执行。如果同一固定候选或另审的实际 merge
 tree 真实覆盖原 42，全部无 skip/error/expected-failure，保留 PG 锁/回滚断言，核对
旧完整 ID 和新方法的收集分母，并有绑定报告、退出码与清理证据，则不必另跑重复
42 窗口。静态计划、合成技术结果和旧 lane GREEN 都不是这一完成证据。

本卡没有 PG/Docker/业务 collect/native/CI/push/PR/merge/deploy；不纳入 C055/C056、
B050、admin UI 或 QQ 删除，不声明完整 H02/M01/M02 或生产验收。
