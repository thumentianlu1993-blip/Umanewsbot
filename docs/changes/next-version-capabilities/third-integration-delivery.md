# PR237 合并交付确认材料

## 2026-10-05 实际合并回执

用户明确批准“同意仅合并 PR237，不发布”。权限恢复后重新核对下文固定 head/base、正式交付收据 SHA、`tests` 与 `test-plan-gate` 成功、strict 与 enforce_admins 均 true；候选没有新增 workflow 改动。将 Draft 转 ready 后，以 `--merge --match-head-commit 3a55a9891e3e557027876b18403ef7b5fb39401a` 正常远端合并，没有管理员绕过。

- GitHub 状态：`MERGED`，北京时间 `2026-10-05 02:22:23`。
- merge commit / 合并后实查 main：`22e130adf4464fd3c5dd63ccd3f508c4a853d464`。
- 两个 parent：获准 base `907f8de699b31a6fcc80acc78e9ba070aadc4f28` 和 head `3a55a9891e3e557027876b18403ef7b5fb39401a`，顺序及字节相同。
- 合并 tree：`e04bf4fdfeab1862bd5e05c99121b04c68631a9a`，与下文正式受验 tree 完全相同。
- 迁移、生产配置/开关应用、构建/重启、数据动作、真实抓取、付费调用及对外消息均未执行。本次没有发布。
- 原 PR235/236 的内容已完整包含，不需重复取得其合并批准或单独合并；本次不关闭或修改它们。

以下保留审批时的固定材料；其中“待合并”表示原记录时点，当前合并状态以上述实际回执为准。

## 审批前固定材料

2026-10-04，Asia/Shanghai。固定 [PR #237](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/237) head `3a55a9891e3e557027876b18403ef7b5fb39401a`，base `907f8de699b31a6fcc80acc78e9ba070aadc4f28`。当前 Draft/open、可合并，尚未合并或发布。人工确认统一依根 [AGENTS.md](../../../AGENTS.md) G2。

## 本次代码范围

本候选完整包含 PR236 的 F01 共享合同、U01 等级筛选、F02 只读导出与隔离验证、Q01/Q02 QQ 解耦与入口/专属依赖退出、H01 目标集合计数、U02 七天首页与来源返回；再加入 A013 时效账本纯合同/计算核心、C013 公开探针纯合同/比较核心，以及两者的共享测试映射。相对主线共 162 个文件，含规划及历史证据；相对 PR236 为 13 个文件。

新增两项纯核心尚未接入真实来源、持久账本、业务 hook、页面读取或探针定时执行，不能视作 R01/O03 已上线。另含 H01 测试观察器最小修复：保留首次取得的持锁证据，防止后续零值覆盖；原 PG 验证类及生产计数代码不变。

没有新增数据库迁移。继承 PR236 的 settings 与两个生产 Compose 文件包含 QQ 专属任务/服务声明变化；仅合并不应用生产配置或退出现有服务。A015/A016、B012/B013/B014、C015/C016、O02 完整恢复及其后续开发不在本候选内。

## 固定验证

- 原独立 R 已批准 A013 `2a7ccbfe`、C013 `baa6345e` 两个固定纯核心；组合字节/映射审核 `e540f375` 通过。H01 观察器修复和最终控制绑定经原 R `cc6f0793` 复审通过，新增 4 项目标 assertion RED→GREEN 独立复验通过。
- 正常 pull_request CI [37156495695](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/37156495695) 于北京时间 06:20:35 完成。full 共 6,462 项、47 批：6,452 通过、10 项明确 skip，0 failure、0 error、0 unexpected success，ID 全部唯一且每批 lifecycle complete。tests 与 test-plan-gate 均成功。
- 10 项 skip 保持主线许可：8 项缺真实缓存输入、1 项未启用镜像修复契约、1 项要求 root EUID。未缩分母，skip 不计通过。
- 候选目录外的主线 `907f8de6` 原 verifier，以 Python isolated 模式核实际 CI 镜像、独立收集 ID/分批、19 个 control blobs、source/base/head/tree、strict 与管理员约束，真实退出 0，正式状态 `verified`。原 verifier SHA256 `7e58cb72042dd76ef064f9121589f1a06655aad6befc1278d389ffc8799c7d7d`。
- 受验 merge/test SHA `c4445e7f704435948d0a78ed16c2f905a4244b2e`，tree `e04bf4fdfeab1862bd5e05c99121b04c68631a9a`；正式 plan digest `80c593fa26ad1d55e4338309d2300632365ea6a8be28d0cb43eae0234a55871a`。原计划 content_digest `b6aaec20b7b6c335405469bf93e92edc2b5b5d76db7c3cec5be38946ff6d022f` 是不同字段，不与正式 plan digest 混称。
- 正式收据 `/Users/mentianlu/.codex/runtime/third-integration-evidence/delivery-3a55a989.json`，SHA256 `8dfd125685670af68aa1e5f82a45511ecf016ae36f04492cf6c1890063ee96b6`。原始完整 CI 输入副本 SHA256 `d1a0164c5c900a8e383d8e5ce478aa519fa3cc6c4ec5d7f059fbae984d4dd4a1`。
- 实际 CI image `sha256:c82c62e822071608e149ed7e37532b92e938d3bb0c548432764dc9b6a6a404f7`；image artifact `11285624242`，396201746 字节，ZIP SHA256 `bb406b31856ff478906ada7c504e9de0707cfb268e692bb9a2c52b460fcfb819`。测试证据 artifact `11285589405`，ZIP SHA256 `43a689a9ff3c0448c095fbd49e3d27c442dd528a8f34cee1f1639c203fe2b42f`。
- 使用本任务专用 Docker 配置指向 `umanews-impact-ci`，只做可信镜像收集核验；结束后无运行容器，自有校验进程退出。一个无关历史退出容器保留，未清理他人资源。没有使用运输替代或修改 verifier 检查。
- 最后只读复核：head/base 与上述固定值一致、PR OPEN/Draft/MERGEABLE、mergedAt=null；main 的必需检查为 test-plan-gate，strict=true、enforce_admins=true。

旧 `4e8993c8` CI 的 6,458 项/47 批及唯一观察器失败保持原记录。本次通过来自修复后全新完整 CI，未用局部测试替换旧失败；纯核心与自动测试不等于真实来源、视觉、公开自然周期或生产验收。

## 建议与执行边界

建议只合并 PR237，暂不发布。它完整包含 PR236/235，因此无须先逐个合并旧候选改变 base；本次综合候选替代此前尚未答复的合并问题，旧问题未答不算批准。

获准后先重核固定 head、实时 main/base 和 strict 必需检查。通过远端合并，随后核远端 main、tree 与 PR 状态并回写；结果未知先核真实状态，禁止重复副作用。固定对象变化时按根 AGENTS 处理，不切换或清理他人工作树。

本次只合并的生产动作均为 0：迁移、配置/feature flag 应用、构建/重启、生产数据写入、真实抓取、付费调用和对外消息。生产继续现有版本。若需撤回合并，按实际 merge commit 准备 revert PR 并走正常确认；本材料不授权 force-push 或生产回滚。

“合并并发布”的精确包尚未就绪：O02 完整引用图与整库恢复仍未完成，F02 新真实样本为 0，F03 完整来源格为 0/45。选择等待发布包时，先补技术条件和固定服务/配置/验证/回滚清单，再依 G2 确认，不预批准未来未知发布。
