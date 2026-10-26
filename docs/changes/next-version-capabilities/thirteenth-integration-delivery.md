# 第十三批交付：PR247 已报告 token 停止线

状态：技术交付与独立复核完成，用户已批准本精确对象只合并、不发布；现已合并并核验主线结果。2026-10-09（Asia/Shanghai）。人工确认仅引用根 [AGENTS.md](../../../AGENTS.md)。

## 固定对象与结果

- PR：[247](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/247)。
- HEAD：`27def1f700099146b678c92e796f4311fa4dc88a`。
- BASE：`582846d4b525378e8b44d03674be1d47b71e7a65`。
- 已验测试 merge：`5546c47850dfa1a380b4866927b7597efda2cc85`；tree：`6e502e75a562b8d9ec64ad4e2c510ab0d2145368`。
- 正式 pull_request CI：run `37876084991`，attempt 1；49 批、6845 唯一测试，6835 PASS、10 原允许 SKIP，零失败或错误。
- 同镜像可信验收实际 exit 0，325.39 秒；receipt `4cee72739b3da5e4c09e773b3b6db85b2b7f184e8191ac83985e126875e51e92`。
- ROOT 独立资源收尾已核：进程/PGID、owned 容器消失，旧停止容器保留，双锁可重新取放；收据 `f833d523284f521d542e65c250c4b38882c825be74f3a1af69ab0cfb777023a7`。
- 最终独立审核 commit `899191ff023d8e2b507c7171a56804551d25344d`，无 findings；回执 `6c7f25fa717fd959376091cd8358229e8ea6c823b5cccf83954e6bd8d2363c44`。ROOT 全读报告，核固定 Git 和 10 项封存通过。

## 行为与限制

在 offline_test 私有绑定的翻译质量重试中，policy v2 的累计已报告 token 达到阈值后，停止后续 slot/CAS/provider create，并保存失败收口及有限诊断。首轮及在途响应仍可超阈值；此功能不是硬 token 或真实费用上限。保留旧 v1 policy、身份/权限/来源/model/unknown/期限等围栏和合法 checkpoint 不重复计费规则。

差异仅四个业务文件、一个测试模块、两份说明和测试 catalog 登记，无新增 migration、生产配置、workflow 或供应权限。十项 SKIP 仍是明确覆盖缺口（八项真实缓存、一项真实 Docker 合同、一项 root EUID），原 review_by 为 10/16，不算 PASS、不自动延期。完整 M02/M03 和生产验收仍开放。

## 推荐交付：只合并，不发布

本包覆盖收到明确决定后，将固定 PR247 从 Draft 转为 ready，通过远端合并并核实际 main commit/parents/tree，登记真实合并结果。合并前复读 head/base/merge、required checks 和 strict/admin 保护；若对象实质变化则按根 AGENTS 处理，不绕过保护。

| 影响面 | 本包动作 |
| --- | --- |
| 迁移 | PR247 无新增迁移；不执行已有 0080/0081 或其他生产迁移 |
| 配置和开关 | 不改变生产配置，不启用自动发布、race-live、enforce 或模型生产入口 |
| 服务 | 不构建或发布生产镜像，不重建或重启服务 |
| 生产数据和外部动作 | 无生产数据写入、抓取扩张、付费调用或外部发送 |
| 验证 | 合并前重核精确身份和保护；合并后核真实 commit、parents、tree |
| 回退 | 如需撤回，形成保留审计历史的 revert；本包没有生产数据库恢复动作 |

若选择合并并发布，须先补齐精确生产运行版本、镜像、0080/0081 实际迁移状态、备份恢复、配置、服务动作及生产验收合同，另形成可审发布包。本文件不包含该发布动作，也不代表用户批准。可以继续保留 Draft。

## 当前执行条件

最后成功实时核验及可信 CLI 的最终复读绑定上述对象。此次收取最终审核时，新的 GitHub 复读因沙箱网络限制拒绝连接本地代理（operation not permitted），没有取得更新后的远端状态；不得把旧快照冒充当前状态。需在允许访问的环境重新完成合并前检查。未执行合并、部署或生产启用。

## G2 批准与执行断点（2026-10-09）

用户明确回复“批准按PR247交付包合并”。本包只合并授权已成立。GitHub 连接器实时读取确认 HEAD、BASE、测试 merge 与上述对象一致，仍为 OPEN/DRAFT、merged=false，tests 与 test-plan-gate 均 success。

本地 gh 仍被沙箱拒绝连接代理；连接器读取 branches/main/protection 返回 403 Resource not accessible by integration，无法完成本包承诺的 strict/admin/required checks 当前保护规则核验。因此未调用 ready 或 merge，不把可合并标志当作保护核验。恢复获准读取通道后从保护核验继续，同一包无需再次 G2；本次未发布或操作生产。

## 实际交付完成（2026-10-09 16:42，Asia/Shanghai）

网络恢复后，ROOT 在同进程 integration FD 锁内实时核对 strict=true、enforce_admins=true、GitHub Actions test-plan-gate 必需检查及 tests 成功，HEAD/BASE/测试树保持。转 ready 后再次核对，以精确 HEAD 约束远端 merge，实际主线提交 `275e98592f968e1586b76727e9a93927c8a87f6f`，父序为本包 BASE/HEAD，tree 为 `6e502e75a562b8d9ec64ad4e2c510ab0d2145368`，与受验树相同。合并时间 16:42:18。独立确认 owner 进程退出、原 dev/inode 锁可重取并释放。

收据：`/Users/mentianlu/.codex/runtime/pr247-merge-only-001/merge-receipt.json`。无部署、迁移、重启、配置或开关变化、生产数据动作和外发。前述读取阻塞已解除；完整 M02/M03 与生产验收仍开放。
