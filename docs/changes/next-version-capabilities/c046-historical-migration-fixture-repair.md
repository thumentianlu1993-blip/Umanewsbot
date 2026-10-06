# C046 历史迁移测试夹具最小修复准备

## 实际问题与范围

PR #243 固定失败 head `bcefcce1daa3e5134ecb0a258a8efe567c1aadc9` 的正式
pull_request run `37473996245` attempt 1 执行了 6,753 唯一测试 ID / 48 批，6 批失败。
159 条 failure/error 记录含子测试，归并为 108 个测试 ID；新增 50 个测试均执行且无失败或跳过。
本修复基于该真实失败，不重复制造 RED。

`0080_translation_retry_budget.py` 被复制进历史 0078 夹具，又进入原 0079
迁移合同和回滚 harness 的目标路径清单，导致原固定合同按预期拒绝未审迁移。
修复只调整测试输入，不放宽生产准入。

## 修复内容

- 共用历史 helper 默认维持 0078：显式剔除 0079、0080 两个已知后代文件；0079
  夹具仅剔除 0080。仅根目录精确文件名匹配，不按编号、glob 或未知文件自动裁剪。
- helper 继续真实执行原合同散列校验。只在测试作用域绑定临时目录，按 cleanup 恢复；不替换返回值、预期 hash 或生产模块字节。
- 0079 合同和 artifact 测试使用隔离目录；PG migration 测试同时隔离
  MigrationLoader 输入，保留原 0078→0079 schema、锁超时、真实 dump/restore 和未知 recorder 拒绝断言。
- 原 0078 host/rollback harness 共用默认 helper 自动取得真实历史路径集合。
  `test_t14_drain_failure_never_stops_web_or_releases` 原断言保留，只追加 stderr 诊断。
- 加两项窄保护测试：已知当前目录仍被两代原合同拒绝；在复制源中追加未知 0081
  文件后，两代 helper 都应真实拒绝。正式 collect 计数尚待确认，不提前声称全量分母不变。

生产 0078/0079 服务与固定合同、rollback ceiling、0080 migration、models、runner、CI、catalog/skip 均保持原字节。

## 159 条记录与二次症状

| 分类 | 原记录数 | 修复输入 |
| --- | ---: | --- |
| 0078 contract drift | 110 | 原 0078 历史目录 |
| 0079 contract drift | 6 | 0079 历史文件与 MigrationLoader 目录 |
| 原 0078 rollback ceiling 拒绝 | 36 | fake git-ls-tree 历史目标路径清单 |
| intent/manifest 未生成的二次读取错误 | 6 | HostHarness 初始合同拒绝发生在 prepare 前 |
| drain fault 未到达 | 1 | top-level build 后的 preflight 合同校验 |

最后一项单独核对：原断言已运行，说明未捕获的 60 秒 subprocess 超时没有发生；
最后事件 `compose:build web` 的下一步是 preflight，离线替身会调用原 0078
合同，而其目录 manifest 确定不匹配。原 assertion 未包含 stderr，故此定位是原日志加
源码静态链路证据，修复后的实际 drain 到达仍须窄回归验证，不能假称已通过。
另外 6 项须在原故障分支实际生成 intent/manifest 后验证，不能仅凭静态归因闭环。

## 验证状态与后续

已做 AST 解析、旧测试方法/断言保留扫描、静态历史逐文件 manifest 对照和
`git diff --check`。历史 0078/0079 manifest 分别精确恢复原固定 hash；未知文件保留并使
静态 hash 不匹配。未导入候选、未运行 Django/PG/Docker，未推送、更新 PR 或重跑 CI。

提交固定后交 ROOT 与原 reviewer；请求 123 个唯一窄回归 ID（85 django、38
release-postgres），包含全部 108 个原失败 ID、0079 完整局部合同、两项新保护和原回滚
未知/高版本/嵌套路径拒绝。精确列表在专用 runtime 的 `minimal-regression-request.json`。
资源、执行预算与正式 collect 由 ROOT 分配；通过后再绑定新候选，不能复用 PR #243
原失败 head 的授权或称其已变绿。交付规则统一引用根 [AGENTS.md](../../../AGENTS.md)。
