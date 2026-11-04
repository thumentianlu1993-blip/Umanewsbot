# B106 RED2 成本夹具窄修复

操作：B106-RED2-COST-FIXTURE-REPAIR-001。新候选只完成静态准备，未 collect/执行/分配资源。此文补充先前 handoff，第二方法恢复改为一个有限 worker + 主控制连接；两方法仍串行。其余范围、两目标断言、B105 文档与业务模块保持。

## 已观察与诊断

ROOT 原实际固定包 `/Users/mentianlu/.codex/runtime/b106-article-term-exact2-red-host-binding-001`、source `6c6e25bb25b1bc1598e053dc5f9cf11d95a4f901` 的原生结果是 1 FAIL + 1 ERROR：RED1 实际 v2 read 缺少 term_snapshot；RED2 consumer 返回 cost_unreconciled，Article/provider/read 重放联合前置在原 line427 报 ERROR。这不是两个 RED，不能进入 GREEN。原包只读，不重跑不改写。ROOT 清理证明路径 `/Users/mentianlu/.codex/runtime/root-b106-exact2-red-closeout-001/closeout.json`，SHA256 `70c19afa3ef0651c868d752347c8e7c97cd4f78675877d45b3ad719374765b4e` 由 ROOT 交接给定，本卡不重新检查资源。

源码定位：read 故障后测试明确要求 requests_reserved=0、零 request attempts/create，故此断点没有模型成本。恢复沿原 consumer 的 resolver → provider.translate → _request_completion；原 SDK response 取得后 core.record_usage 只 journal 已知 usage，不带 receipt，得到 usage_reported/unreconciled。core._admission 对这种记录返回 cost_unreconciled，不能继续受保护保存。先前日志没有单独打印 provider observer，不能凭 consumer 最终返回认定从未到达 provider；这一阶段定位来自原零请求前置与上述实际源码链。本修复增加实际 usage/receipt 观察，待新窗口验证。

## 修复

只改第二方法恢复片段，复用已有 RemainingReadonlyE2EFixture.wire_gate(after_usage_choices) 和 running_workers(count=1)。消费 worker 建立全新合法 scope，暂停在原 response choices 前；原 provider 已把 USAGE journal 提交，主控制连接必须读取实际 usage_reported/known/unreconciled、空 receipt，且实际 provider resolution 已观察一次。复用原 no_business_locks 检查同步点没有持有业务事务/锁。

控制连接构造原 synthetic_offline_usage_v1 receipt，绑定实际 budget UUID、实际 attempt PK 和实际 journal usage SHA，调用原 core.record_usage(mode=offline_test)；必须得到 allowed/offline_usage_reconciled，刷新 ORM 确认 reconciled/offline_reconciled、原 usage 不变、非空 receipt SHA，才 release。成本许可不是 fake SDK 提供的，不 patch admission/record_usage/保存，不直接写 ledger，不新增槽位，不改业务源码。真实对账失败是夹具 ERROR，不是目标 RED。

CaptureQueriesContext 放在消费 worker 的同一实际连接内；词典 SELECT 目标仍覆盖完整恢复消费。实际 provider 与 Article translated、一次 read/create、原 step PK/UUID/SHA/read_at/result 全等前置原样保留。目标仍为实际 resolution 等于 read 前冻结值、零新增 TermEntry/TermAlias/ExternalHorseAlias SELECT。SDK 构造禁令、scope 关闭检查和原 worker finally/join/PG 连接关闭均保留。失败/退出路径沿原 releases finally 释放 gate，无新增线程框架。worker gate 8秒、join12秒，主+worker两个连接在既有上限3内。

## 固定交接

新 runtime `/Users/mentianlu/.codex/runtime/b106-red2-cost-fixture-repair-001` 包含 prepare.json、plan.json、resource-request.json、source.diff、launcher-command.txt 和原入口/controls 字节。plan 仍 exact2 原方法 ID，绑定修复 SHA/tree；运行入口不变，ROOT 原窗口只必要 source/runtime/plan/hash/目标 FAIL classifier 重绑定。旧实际包和原准备包只读保留。没有实际 RED/GREEN、Docker/PG 执行或 OS 隔离能力重资格证明。

静态校验：AST parse、仅第二方法 AST 变化、RED1 文件原字节一致、原两个目标断言及原联合恢复前置 AST 不变、B105 三文档原字节一致、业务模块无 diff、git diff --check。ROOT 先交原 R 窄复审，再安排新窗口；本修复不取得实现/合并/发布权限。
