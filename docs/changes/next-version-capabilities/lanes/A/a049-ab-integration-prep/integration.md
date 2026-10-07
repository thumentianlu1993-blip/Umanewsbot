# A049 A/B 集成候选准备

本卡只准备可审查的集成源码与静态测试计划。固定基线是
`90f73d8093df00827a7ec78cc41dc3d3b91730c0`，分支为
`codex/a049-ab-integration-prep`。最终 commit/tree、计划摘要与封存凭证写在候选外
`/Users/mentianlu/.codex/runtime/a049-ab-integration-prep-001/`，避免自引用提交哈希。

## 进入候选的原始交付

| 归属 | 固定源码 | 已有执行证据 | 集成方式 |
| --- | --- | --- | --- |
| A048 | `b94844022793283029980f2008b27127916691e4`；tree `5832da77400520f944594dc37b45ad2d47264d7e` | ROOT actual19 全通过；R4b9ab2cc / ROOT4188 审查 | 相对固定 main 的 9 文件精确补丁 |
| B049 | `3dd653139759b48c41d8d43fdab927e0e3b20ddb`；tree `bb280a7833be160405e3be10e3c4ca4a38bb5a17` | ROOT actual23 全通过；Rdac09a7d / ROOT4191 审查 | 相对固定 main 的 6 文件精确补丁 |

A/B 均以固定 main 为祖先；15 文件没有交集。不是以两个 tip 互相覆盖文件。
原 lane 文档保留其提交时的历史状态；其中“待 GREEN”不代表上述后续实际执行未完成。
已有 19/23 通过只证明各自原 tree 的窗口，不能作为集成 tree 的通过收据。

## 文件与提交归属

A 闭包包括 A045、A046、A047、A048 四份原文档；独立 stdlib audit 验证器；
career consumer service、同名管理命令、新测试；以及 `horse_race_records.py`
中保留既有 eligibility_text 的条件赋值。提交顺序为
`79c381c4 → 043152cc → 7321a796 → 55428d70 → bfbabac7 → 66d39b99 → b9484402`。

B 闭包包括 B048/B049 两份原文档；0081；`models.py`；readonly service、新测试。
提交顺序为 `d0f0889b → cab38b20 → 221f3f43 → fef24373 → 3dd65313`。
`models.py` 只追加 ledger QuerySet、TaskBudget、Step；main 的既有顶层模型 AST
逐项保留。0081 与模型均逐字匹配 B 固定 tip。

候选外 `source-manifest.json` 列出每个文件的归属、固定 blob 与触及提交；
`A.patch`、`B.patch` 保留完整差异；`dependency-closure.json` 记录 AST 本地依赖闭包
和直接私有符号检查。闭包中未变更的依赖逐字匹配固定 main。Django/stdlib
由既有执行环境提供；这里未导入业务模块或验证运行时依赖安装。

A049 自有变更仅为本说明及 catalog/rules 的增量登记：新增两个测试模块；
career review domain 与既有 horse 依赖；新 service/command/验证器路径；
0081 高风险登记。所有旧测试登记、旧领域标签、旧依赖与 skip 策略保留。
这是测试计划生成所需的依赖补齐，须由集成审查单独核验。

## 业务与迁移边界

A：从受审输入校验 cache/H01/H02/身份和全部原始行，经用户/档案/记录锁与时效检查，
调用原 writer 创建 career record，原子写候选消费和操作审计。回放保留后续合法关联；
dry-run 回滚；非出赛拒绝优先级和 finally 全库状态检查保持 A048 原实现。
Decimal 审计转换仍局限于 record distance，未扩大共享 JSON 转换器。

B：沿用 main 的 translation retry parent 身份与离线预算作用域，独立保留 readonly
slot，执行封闭 ORM source excerpt 读取，再提交 step 结果；失败不退还、不重读，
回放按持久化 envelope、参数、token 与严格 JSON 身份校验。未接入业务任务或外部 provider。
A 写 career/审核审计，B 写独立预算/step 账本；集成没有新增跨 lane 调用。
锁顺序及身份语义仍需真实集成执行验证。

迁移仅 `stable.0081_managed_readonly_steps`，依赖现有
`stable.0080_translation_retry_budget`；两个 CreateModel，无 RunPython。
须在新隔离数据库确认迁移图、约束和 ledger 写入限制。不得把 AST 校验写成
makemigrations --check 或数据库迁移成功。

不纳入 C055/C056、B050、admin UI、QQ 删除；不声明完整 H02/M01/M02 或生产验收。
原 A/B worktree 和既有 execution package 冻结，前后指纹在候选外核对。

## 保留分母的测试计划

静态目标为原 A19 与 B23 的集合并集，42 个不同 ID。其中 29 个新声明方法
（A10、B19），13 个旧回归。此数来自两份原 actual 收据和源码 AST；**不是候选 collect
或 execute 总数**。完整 ID、原收据路径与 SHA256 在 `test-set-union.json`。
候选 actual collected/executed count 初始为 null。

1. 原 R 先核验固定 candidate/tree、15 原文件字节、增量测试登记和迁移闭包。
2. ROOT 分配后在独立 PG/Docker 环境按该候选 collect。比较上述 42 ID、29 新方法
   均被收集，并保留原 actual 测试断言、子场景与执行控制，不删 ID、不改成 skip。
3. 执行原 42 ID 的集成窗口，要求全部通过、零新增 skip/error/expected-failure。
   保留原 A 非出赛四子场景 finally 状态检查、真实锁等待、B reserve/未知状态/回放约束。
   若需要新增交互用例，另登记 ID 后执行，不替换上述分母。
4. PR 正式入口 `.github/workflows/affected_tests.yml` 对 PR base/head/merge-test tree
   生成计划。本候选含模型、迁移、catalog/rules 变更，应进入 full；保留旧/新 catalog
   全量并集和所有 profile/batch/既有 skip 规则。静态 label 数不等于动态测试 ID 数。
5. `.github/workflows/full_regression.yml` 精确 candidate_sha 全量入口复用上述执行器。
   本地保存的 affected/full 静态计划均以固定 main 对 candidate 比较，核对旧 labels
   子集、新模块覆盖、零删除模块/声明 ID。若之后只以 candidate 作 base/head，仍需
   单独携带本基线比较凭证，不能省掉旧分母证明。
6. 真正 collect 后保存完整 execution plan、各 batch 收据、最终验证和清理证据。
   全量旧 discovered IDs 应保留，新增 IDs 应出现；发现动态收集差异需逐项解释并
   经 ROOT/R 核验。禁止仅以静态方法数、toolchain 或 validation-only 代替正式测试。

本卡仅运行 stdlib AST/Git 静态核验与纯静态计划生成；未启动 PG/Docker、未 collect、
未运行 native 业务测试、未发 CI/push/PR/merge/deploy。后续资源窗口与动作由 ROOT 分配。
