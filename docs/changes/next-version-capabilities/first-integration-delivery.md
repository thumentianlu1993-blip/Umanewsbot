# PR235 首批交付确认材料

2026-10-03 Asia/Shanghai。仅绑定 PR #235 head `39f0bb96f4f24d15b625ca404c50cede9ebf05dd`，base `907f8de699b31a6fcc80acc78e9ba070aadc4f28`。当前 PR 为 Draft/open，尚未合并或发布。人工确认只依根 AGENTS.md G2。

## 可交付内容

F01 共享内容合同；U01 赛事等级筛选与卡片/详情标签口径一致，支持分页前可信等级筛选；F02 只读导出与转存校验工具基础。后续 Q01/Q02、H01 PG、B005 接通实现不在本 PR。F02 真实新增样本仍为0，不能把工具代码交付当作采样完成。

## 已完成验证

- 原独立 R 业务、合并/实际映射与 C006 fixture 修复审核 APPROVED，最终控制绑定 `39511a834e4f2a1eee3ab849c8226102aa7c2906`。
- 真实 pull_request CI run `37062783533` / attempt1：full 6236 项，10 个原许可环境skip，0失败/错误，tests/test-plan-gate SUCCESS。
- 候选目录外 main907 原 verifier（SHA256 `7e58cb72042dd76ef064f9121589f1a06655aad6befc1278d389ffc8799c7d7d`）独立重收集精确 ID/分批，核 actual image、原始结果、control blobs、strict+admins、实时base/head，最终 status=verified。
- 受验 merge `2891807724828518c6524bf2d374953a73035850`，tree `63c8fdec928720a45dd31d127d9d5ae69f6931de`，plan digest `70967cfb9391dc884928590ac1d43353e908b859e0563f19f1d70b248044704c`。
- 私有正式收据 `/Users/mentianlu/.codex/runtime/first-integration-evidence/delivery-39f0bb96.json`，SHA256 `bcebaa222c920f5166afddbb7558de70793b6dc5066c98b63812b2bf49e79cf9`。

GitHub整文件下载异常的恢复只替换固定image artifact11252217981的输运。分段获得396175642字节，与authenticated GitHub前后metadata官方SHA `48dc0fbe56bb57bb96a0f61bb41b9d12566d072e148fb2ca4f56a70fad57e7df`一致；原R独立核实际cache/shim输出并批准 `77fb48fe2c4d6b828b86102b6b0f5d581e50ebc1`。其它所有GitHub调用真实透传，原verifier代码及检查未改。输运收据没有替代正式交付收据，旧卡住进程已终止，验证结束无容器占用。

## 本次可批准的交付范围

建议只合并 PR #235，不发布。合并前再核head/base与必需检查，受审SHA或主线变化时按真实情况补验；通过远端合并，不切换/清理其它工作树。合并后核远端main/tree与PR状态，再登记已合并。合并失败或结果未知先查实际收据，不重复副作用。

此选择不包含迁移、配置/feature flag变化、构建/重启生产服务、生产采样/写入/删除、抓取/模型调用或对外发送，生产四应用保持当时现版本。独立后续开发继续按原调度。

合并并发布的精确包尚未就绪：本版rollout要求 O02 关闭两处已知唯一约束恢复缺陷，当前O02未完成，不能将旧SHA/TOC校验等同整库恢复。若选择等待合并发布，将先完成该技术条件并提交固定发布包后再确认，不以本材料预授权任意未来包。19:07–19:13只读生产证据见O01文档；schema0079、U01 Unicode能力齐全，另有旧QQ定时任务，不构成可立即停服证明。
