# PR246 固定候选只合并交付包

2026-10-09（Asia/Shanghai）。开发切片、源码独立审核、正式完整 CI、候选目录外的实际受信核验及该次资源独立收尾均已完成。PR246 仍为 OPEN Draft，未合并、未部署、未启用，也没有生产验收。本文件提交可审的“只合并，不发布”对象；通用确认规则仅引用根 [AGENTS.md](../../../AGENTS.md)。

## 固定对象与业务结果

| 项目 | 精确值 |
| --- | --- |
| PR | [PR246](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/246) |
| head / trusted source | `1b3d0fab49c112fc6e3c86eab7cdf6e11cde79b2` |
| base | `90f73d8093df00827a7ec78cc41dc3d3b91730c0` |
| 受验合成 merge | `df0709a605d844c2bf71616173c23adb9213b6eb`，parents 为上述 base/head |
| head 与受验 tree | `e1aca24ea9b27d62c78c2faeff973e2c0b1f00e6` |
| 正式完整 CI | [run 37768260485](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/37768260485)，attempt 1，原生 pull_request |

PR246 包含 PR245 的全部提交：已用 Git 验证 PR245 head `c6ed21a434d41bb0721987437a4d7f7663eb7be2` 是本 head 的祖先。因此建议直接以 PR246 统一交付；不需要先另合并 PR245。旧 PR、失败运行及历史交付包保留，未当作新授权。

本候选提供两项受限能力：

- 冻结审核材料的香港生涯赛绩消费者：核精确身份、权限、原期限和幂等凭据，赛绩、审计与派生计数同事务提交；重放保持持久状态，dry-run 经过真实写入路径后回滚。没有新增公开入口或自动生产补录。
- 持久化只读步骤接入受管理的翻译恢复流程：同一完整身份和原期限下复用已完成读取，已完成翻译重投返回不可变收据；撤权、来源/版本/身份漂移或不完整状态拒绝继续读取、模型请求和落库。普通未登记翻译路径保持原行为，普通 metadata 的 tuple→JSON 数组兼容已恢复；私有 checkpoint 围栏保持。

同时修复正式测试源码绑定和候选外 verifier 的八项受信依赖闭包。该切片的技术交付完成，不表示完整 M02 的模型计划、通用累计预算与跨进程恢复全部完成，也不表示相关生产权限或对外工具已开放。

## 已验证证据

| 验证项 | 结果 |
| --- | --- |
| 精确源码独立 review | R-B080，0 findings；收据 `1dac08c079b9050b8219da4e237bb2ded1879df7d26688e143db42f1478c1346` |
| 本 head 正式 full | 6,839 项：6,829 PASS、10 已声明 SKIP；未缩分母，跳过不计通过 |
| CI 结果独立审核 | R-B081 接受完整结算，收据 `584b2cca42cae37ed9b77b367eb19bdcb791f1a00af1d8a04ad1c3dfe605d0d7` |
| 实际候选外 verifier | 原 CLI `642ece96f33ad6d9d5ff05b7955714aa0441779ef386aae586217f01e1c1b908`，实际 exit 0、status verified |
| 实际镜像 | `sha256:da9d77844bcabb9c72313031509088d0d6f9edf4e59b5e41e944295947dd7075` |
| 交付收据 | `9c32c8d379ccfbd436fbbe734d3e804b8a37f210bff4fd56b902e7ffc81a0987` |
| ROOT 独立资源收尾 | `6a4102180e87191a1c79c352dbcab4087ea53ca7a7e51e0bb15f89a626c31947` |
| 实际交付与收尾独立审核 | commit `dbd4dfe1ec0a124fcd3713f58cb515974a35bfb0`，收据 `e26cbe545d436d533bf93a006f457b3305b2e561719850b2e81159965c461b6a`，0 阻断项，无需重跑 |

实际 verifier 耗时 325.398 秒，从本次 CI 镜像独立 collect 并比较 mode/count/batches，再验证已完成的 CI 业务报告；不是在本地重跑全量业务方法。十项 SKIP 保留原声明，其中九项 collection skip 与一项 runtime root-EUID skip 分开，不冒充覆盖。

监督器原 exit 1 / FAILED_OR_CLEANUP_UNKNOWN 保留：其缺失容器判断未覆盖实际 Docker 的 `[]` stdout 加小写错误格式。ROOT 随后独立核实 owner/runner/PGID 消失、owned CID 明确缺失且不在完整库存、无运行容器、旧停止容器六字段原样、两把锁同 dev/inode/0600 可重取并释放。原 R 已接受该独立收尾，未把监督器改写为成功。后续函数格式补丁只用于未来兼容，不替换本次原件或要求重跑。

实际原件位于 `/Users/mentianlu/.codex/runtime/b086-stopped-baseline-preflight-001/`；17 件实际索引 SHA `0446175fd79b60a336a4aaf5f9d93ce661f3b0f3a982fc95c69fdaa68d3f12b4`。旧 33 件封存与实际记录保留；源码、测试清单、报告和审核收据各自绑定精确版本。

## 此次只合并的动作与边界

1. 收到本精确对象的 G2 决定后，ROOT 重核实时 head/base/merge、必需检查和 strict/admin 保护，以及是否仍满足已有证据绑定。
2. 将本 Draft 转为可合并状态，通过远端将该固定 PR 合入 main；不绕过保护、不直接改本地 main、不切换或清理其他工作树。
3. 读取真实合并结果，核实际 commit、parents/tree 与获准对象关系，登记“已合并”；既有只合并步骤不拆分重复确认。

| 影响面 | 此次动作 |
| --- | --- |
| 迁移 | 只纳入 `0081_managed_readonly_steps` 源码（两个 CreateModel，依赖 0080）；不执行任何数据库迁移、回填或 DDL |
| 配置与开关 | 不修改生产配置，不开启 enforce、race-live、自动发布或其他功能开关 |
| 服务 | 不构建生产镜像，不部署、重启或重建任何生产服务 |
| 生产数据与外部访问 | 无生产业务写入、采集扩张、付费调用或对外发送 |
| 验证 | 合并前检查精确绑定和保护；合并后核真实 main commit/tree，交付台账分开记录合并和发布 |
| 回退 | 保留 Git 审计历史，若合入内容需撤回，按真实 main 形成可审 revert；本次没有生产数据库恢复动作 |

0081 的精确生产迁移、运行镜像、服务意图和恢复合同尚未完成。既有历史 release/rollback guard 不等于支持新迁移，不能绕过；生产是否已应用 0080 也须在另行发布包中现场核验。因此当前推荐“只合并，不发布”，另一个当前可执行选择是保留 Draft。若用户希望合并并发布，先完成包含精确 commit/image、迁移链、备份、配置、服务重启、验证和回滚的生产包再提交决定；本文件不授予该发布范围。

本文件建立新的 PR246 交付选择，未代替用户作出决定，也未把旧 PR245 待答事项当成批准。


## 后续执行结果

2026-10-09 00:40（Asia/Shanghai），用户明确批准“合并 PR246”后，ROOT已完成上述只合并动作。实际main/merge为`582846d4b525378e8b44d03674be1d47b71e7a65`，parents与获准base/head一致，tree与受验树一致。GitHub将包含的PR245标为merged；没有另行合并、删除分支或发布。生产迁移/部署/启用仍未执行。原批准时文档保存在runtime的approved-delivery.md，实际merge-receipt.json SHA256 `a1d3ae5f2592f4075e15f37a6170fea112842db7a17fd1bdc24947ded0ed43cc`。
