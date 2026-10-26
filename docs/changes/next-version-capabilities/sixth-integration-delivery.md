# PR240 首批成果交付确认材料

2026-10-06，北京时间。状态：正式测试与独立交付核验通过，等待 G2；尚未合并或部署。人工确认依据仅为根 AGENTS.md。

## 固定对象

- PR：https://github.com/thumentianlu1993-blip/Umanewsbot/pull/240
- base：`6e6aded22764ebee3d6a97f2834f47d4b4baa7bb`
- head：`2c72521c55b6cdc24f7650d172b48079cbff969a`
- 实际受测 merge：`b96c9a6aafbbf69990ffc373ab0eca6135f6860c`
- tree：`f8123282810407037b59a3a99e98a1e022eedb5d`
- 最近实时 PR 为 OPEN / Draft / MERGEABLE / CLEAN；base/head 未变。

## 已实现范围与限制

1. H02 离线缓存复用与既有 HKJC 缓存适配：复用可用原件，区分过期、身份冲突及无法确认；不增加真实抓取。
2. N01 正文清洗与前后证据：区分正文、污染和资料不足；清洗轨迹避免收录 script/style 代码文本。
3. 既有 U01/U02 公开页本地合成演示与 SQLite 日期兼容修复。
4. 必要测试目录和影响映射登记。

独立来源 review 与 C028 集成 review 已通过；C028 原 R 提交 `c4ec365ed40aeca4fae8dfcc9474254dabce39cc`。共 24 文件。A032、B037、C032 后续切片不在本 PR；真实来源基线、完整 H02/N01/U 系列验收并未完成。本地合成演示不代表生产公开验收。

## 正式验证

CI `37443876756`，固定 head，full 6,613 项：6,603 通过，10 项许可跳过，零失败/错误。候选目录外从固定 main 提取受信 verifier，以 `python -I` 实际下载本次 CI 镜像，独立收集完整 ID/分批并核对结果、workflow、runner、strict 分支保护和最终 base/head，返回 exit 0 / verified。

收据：`/Users/mentianlu/.codex/runtime/pr240-trusted-delivery-001/delivery-receipt.json`；SHA256 `46ddd91604066b2ae61b5e1ddcd8139636c7e8f538007db7428b3462d8d1e5d7`。核验自有进程退出，本地容器为空，窗口释放。

## 当前建议：只合并，不发布

批准对象仅上述 PR/head：必要时移除 Draft，通过远端正常受保护合并；复核实际 merge parents/tree/main 与受验对象一致。无迁移、配置变更、服务重建或重启、生产数据动作、功能开关、真实抓取、付费调用或对外发送。既有 QQ 停用代码不在本次变更；本次不部署 main，不能因此使暂缓的 QQ 下线在生产生效。

若只合并获准，本次不会执行生产发布。若后续需要发布，应另以准确提交、迁移/配置/服务/数据/开关清单、验证和回滚形成 G2 精确发布包；当前未形成或申请此包。合并前对象漂移或必要技术检查失效时，按根 AGENTS.md 处理；禁止绕过保护。

回退面：本次无生产状态变化；需要撤销共享主线时准备精确 revert 变更并按根 AGENTS.md 交付，不重置或改写 main 历史。
