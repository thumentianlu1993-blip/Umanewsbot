# A047：consumer 的 audit_structure 类型修复

基础候选为 `55428d705ef71ff1a24e714f65746ace45e3b4b8`。ROOT 仅执行过一次 A003：原 19 个 ID 分两批全部运行，`lifecycle=complete`，结果为 **10 PASS / 9 ERROR / 0 FAIL / 0 SKIP**，report exit1、child1/parent2，**不是 GREEN**。九个 ERROR 均遇到首次记录快照的 `audit_structure` 异常，多项方法在 `positive_rollback` 前置阶段报错，后续竞态及 TTL 断言尚未验证。旧九项回归 PASS；新增十项中唯一 PASS 为 `test_legacy_writer_preserves_explicit_eligibility`，仅验证 legacy writer 保留显式资格属性。输入拒绝方法 `test_binding_private_baseline_identity_and_manual_lock_fail_closed` 在 `positive_rollback` 前置 apply 报 ERROR，其后续输入拒绝断言未触达，不能据此声称绑定、私有状态、基线、身份或人工锁的拒绝分支已经通过。

原报告位于 `/Users/mentianlu/.codex/runtime/a046-root-green-window-prep-003/output/report.json`，SHA 为 `ce7bb2d5a2d0c36a913eedb077dfab3618b879c1184d34871bd3192dc2d0ecb1`。原 strict26 环境、venv preflight 及 guest 检查、真实 Git 和 PG 均通过。ROOT 清理核验 `/Users/mentianlu/.codex/runtime/a046-root-execution-audit-003/cleanup-verification.json` 记录自有容器 absent、running 为空、parent70536/child70560/attach70575 已消失、FD 已重获、sealed2060 不变，实际 PG stop0/status3。原输入与结果完整保留，本次修订没有重跑或分配窗口。

## 类型证据与最小修复

`HorseRaceRecord` 恰有一个 `DecimalField`：`distance_meters_normalized`，`max_digits=10`、`decimal_places=3`，允许为空。真实 writer 将 `normalize_distance(...).meters` 写入该字段。normalizer 返回数值；consumer 调用 `refresh_from_db()` 后，依照数据库字段合同读回 `Decimal`。fixture 的距离为 `1400m`。审计 `_state` 遍历全部 concrete fields，因此该字段进入共享 `_json_safe`；后者接受 date/datetime、字符串键字典、列表以及 None/str/int/bool，明确拒绝 Decimal。真实栈在 `_json_safe(_state(record))` 处失败，尚未持久化 candidate/审计。栈与报告没有记录该字段的实际值；`1400.000` 只是依据 schema/fixture 的类型回归示例，并非新捕获的 live 值。

业务修复仅涉及自有 consumer：`_record_audit_state` 复制原完整状态，仅把距离字段的 exact finite Decimal 通过 `str` 转换，无 float 或 rounding；其他字段及嵌套值仍交给未改动的共享严格校验。None 保持 None；非有限值或非 Decimal 的非空距离以 `audit_record_distance` 拒绝。全部键、日期、来源及审计字段保留。创建与 replay 共用此函数，使 JSON 审计回执和重新读取的记录使用相同表示；距离或其他记录事实改变仍会比较出差异。该 helper 不写入或规范化记录，不吞异常，不取消审计或事务。用户/私有状态/来源绑定、锁顺序/TTL、权限、dry-run 回滚、原始来源保留、既有合法 link 校验及业务权限边界均未改变。

## 独立标准库验证

新增 `scripts/verify_a047_record_audit_stdlib.py` 仅把 `_state`、`_record_audit_state` 和原 `_json_safe` 的函数 AST 提取到标准库命名空间，不导入 Django 或业务模块，不运行 ORM/PG/native 业务测试或 discovery。六项独立类型方法覆盖 Decimal 精度/scale 与 JSON 往返、None/date/嵌套来源值、相同创建/replay 快照及事实漂移、非有限/错误字段类型、未知/嵌套类型及深度继续拒绝，以及不修改原对象。这六项单独列出，不计入原 exact19 分母；原测试文件及期望字节保持一致。

在原基础路径使用 `--baseline-source` 时，六方法套件 exit1，报告 failures2/errors6；这是 subtest 计数，不是六个不同业务 ERROR。在修复路径 exit0，六方法 PASS。runtime `/Users/mentianlu/.codex/runtime/a047-audit-structure-green-fix-001` 保留 red/green stdout/stderr 及 `stdlib-red-green.json`。这些结果只验证序列化类型合同，不能证明完整 consumer GREEN，也不能证明真实创建/replay/link/并发/TTL 行为。共享 `_json_safe`、model、writer、command 及原 19 项测试字节未改变。

原 R 的 `649dc01b163ea07891c1f2d8ca97112dd1399ce0` 审核结论为 `REVISE_DOCUMENTATION_ONLY_CODE_TYPE_CONTRACT_APPROVED`：代码类型合同及 R 独立 21 项类型检查通过，唯一 P2 为上述 PASS 方法与覆盖边界表述。本次仅纠正文档并改为中文，未重复已通过的类型检查，未修改代码、脚本、原测试或实际结果。

## 后续及未执行边界

ROOT 将文档修订后的固定候选与独立封存证据交原 R 窄复审，通过后才另行准备绑定新 source 的 host 包并分配 PostgreSQL 窗口，复验未改变的 exact19。既有 A003 完整报告和清理材料仍是历史证据，不能复用旧 source/window。此处未授权或执行 Docker/PG/native/collect/publish/push/merge/deploy/install/network 操作，也未创建新代理；尚无完整 GREEN。
