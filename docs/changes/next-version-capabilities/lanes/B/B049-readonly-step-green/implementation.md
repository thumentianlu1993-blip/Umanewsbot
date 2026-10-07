# B049 私有只读 step 实现候选

## 范围与当前证据

任务 `B049-READONLY-STEP-GREEN-001`，从固定实际 RED
`221f3f43409b036049cc14d697685137c860322e` 隔离实现。沿用已批准 B047 合同
`02a47d0c7470c8aeb5c4bc75b1df550dae0cfeaf`；本次仅修改
`server/stable/services/managed_readonly_steps.py` 和本说明。两张只读账本模型及
0081 迁移保持 RED 字节，未接入 task、provider、API、UI 或生产权限体系。

ROOT 的实际 RED 共执行固定 23 个方法：14 个失败方法、9 个通过方法、15 条失败记录
（timeout 两个 subcase）、0 ERROR、0 SKIP，生命周期 complete。
原 R 审查 `f258c8fe927ddf4325998a12ee02d623114627f2` 接受业务 RED，结论
`ACCEPT_ACTUAL_BUSINESS_RED_WRAPPER_FAILED_RETAINED`。9 个通过方法不表示完整能力通过；
缺失 step 的早期失败遮挡了部分深层断言，需固定测试在 GREEN 中实际到达。

原 wrapper `failed/exit2` 保留：marker 检查误读 `runner.log`，实际 marker 位于唯一官方
`results/b048-readonly-step-red-23.log`。旧 003 包、输出和 seals 不修改或重跑。
未来如准备新 host 包，必须从新包绑定的唯一官方 batch.log 读取 marker，并先验证正确来源、
缺失 marker、仅 runner.log 伪 marker 均按合同处理；不得靠复制 marker 或更改旧报告修复历史状态。

实际证据路径：

- `/Users/mentianlu/.codex/runtime/b048-root-red-window-prep-003/results/b048-readonly-step-red-23.json`，SHA256 `b6064a9e53132736037e1e159bc4139ff276abaf9bfa3528908328d06cb8d900`。
- `/Users/mentianlu/.codex/runtime/b048-root-execution-audit-003/root-business-red-receipt.json`。
- `/Users/mentianlu/.codex/runtime/r-b048-actual-red-003/review-receipt.json`，SHA256 `1f33ba40662bf5b8b8c9824563fe0a44801c7013f21d2c604b2e1b3c2ae26b62`。

## 实现与持久化顺序

1. 在事务外核验 offline parent scope、调用线程、封闭 reader、参数和 outer atomic。
   短事务按 parent → read root → Article → Run → step 顺序锁定并校验完整身份、版本、
   原期限与授权 epoch。固定逻辑名 `source_excerpt:1` 下只有一个 step。
2. 若不存在 step，原子增加独立 tool counter 并插入 UUID/token 固定的 inflight step；
   提交后才发出私有 reservation。额度为 0 时不创建 step、不读业务源。
   完成记录在授权和 envelope 校验后返回缓存；其他既有状态一律拒绝重读。
3. 封闭 reader 在独立短事务核验当前 scope 的已提交 token，释放全部自建事务和行锁后
   执行原有限 ORM SELECT。该 SELECT 的原 AST 和字节保留，同一行材料计算输入 SHA，
   source pair / digest 改变拒绝；SQL、URL、调用方 source ID 不开放为参数。
4. 第二次持久化事务重新锁定并核验身份、epoch、期限、token 和 inflight 状态；
   校验固定 JSON 字段、精确类型、标题/正文界限、8 KiB 上限、结果 SHA 及时间顺序，
   条件更新 completed。提交成功后才返回结构化结果。

缓存身份包含 original operation / parent budget / read budget UUID、Article/Run PK、
claimed_at、claim UUID、source pair、input SHA、有效期限、三个版本、epoch、tool、参数与
逻辑键。fresh scope nonce 仅用于本次 token 所有权，不进入持久幂等键。缓存返回 JSON 副本。

超时、reservation 后退出、读取后退出、结果提交失败均保留已提交读槽和 inflight，
不退槽、不接管 token、不更换 UUID。reservation 插入失败与 counter 一起回滚；
完成更新失败仅回滚第二事务。数据库失败以 `ReadonlyAuditFailure(stage)` 保留原 cause。
结果提交后退出可在 fresh scope、原 executing envelope 下重放；不再次 prepare。

只读预算独立于 SDK request admission；pending request 或 unavailable model 不消耗、
阻断或重置 tool slot。代码只校验父任务身份、原有效期和 claim，未调用 SDK `_admission`，
不修改已有 request ledger。撤权不可逆；已开始的读无法撤销，撤权后不提交或披露其结果。

## 验证与后续窗口

静态验证只使用标准库、AST、Git 字节与 SHA；不导入 Django/stable、不 collect、不启动
PG/Docker。固定测试文件 SHA256 为
`6a7616377a42171cdb975ab12ce3cd0cc17d58a6b2d058eb33fb3f32c4246500`，
沿用 19 个新增方法与 4 个旧回归的原 23 个 ID、原 8 份控制文件。
静态 receipt 和候选封存位于
`/Users/mentianlu/.codex/runtime/b049-readonly-step-green-prep-001/`。

当前仅为实现候选，尚无实际 GREEN。下一步由 ROOT 安排原 R 只读代码审查；审查通过后，
仅 ROOT 可分配固定 SHA、固定 23 ID 的单次 PG/Docker GREEN 窗口。
资源仍为原 immutable image、1 容器、2 CPU、4 GiB、256 pids、3 GiB tmpfs、network none、
非 root、只读 source/control/rootfs、最多 3 PG client / 2 worker，整体 600 秒，
570 秒停止测试，30 秒清理。runtime request 仅是请求，不代表分配或执行。

## B049-R01 最小返修（STRICT-IDENTITY-FIX-002）

原 R 代码审查 `ecfe8280d702b1b73fd7e4ea827c1e04f1124cf5` 为 REVISE，仅一个 P2：
Python dict 宽松相等把 bool/int、float/int 视为等价；原身份校验仅重算 expected contract SHA，
未检查 stored envelope SHA。审查 receipt
`/Users/mentianlu/.codex/runtime/r-b049-readonly-step-code-001/review-receipt.json`，
SHA256 `cb9b7f2623ce58f762b95b0be24c23edbb9db02fadec31be7c958f51f676998e`。

返修增加 `_identity_bytes`：只接受精确 JSON 原生类型，dict 键必须是精确 str，拒绝 tuple、
set、UUID 对象、容器子类、循环结构与非 finite 数字；类型损坏统一为
`step_identity_changed`。stored envelope 与 expected contract 规范字节必须相同，
stored envelope 的实际 SHA 还必须匹配持久 idempotency SHA。JSON 键顺序可等价，
True/1 与 256.0/256 的规范字节不同。permit 保存 expected 的同一严格表示，guard 中
expected、current 都与该表示比较，消除宽松 dict 比较。

独立纯标准库反例 `/Users/mentianlu/.codex/runtime/b049-r01-strict-identity-fix-002/type_drift_contract.py`
抽取旧固定候选和新候选的纯函数执行；未 import 业务模块。实际复现旧候选的
permission_epoch True、article_id True、body_chars 256.0 三种存储身份漂移仍被接受，
包括有效 result 的缓存校验。新候选拒绝这三种漂移及其他非法 JSON、类型、SHA 反例，
共 22 个拒绝检查；合法身份/result 与仅键顺序变化仍可接受。该证据不声称普通受禁 writer
可以篡改数据库，也不替代固定 23 的真实 PG GREEN。

原 23 测试、原 SELECT 字节与 AST、models/0081/8 controls 保持。新封存位于上述 002 runtime；
原 001 和更早包原样保留。仍需原 R 上下文复审，未来新 host 包 official batch.log marker
来源及拒绝合同要求保持；无新窗口、业务执行或部署授权。
