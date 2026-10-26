# 第三批累计候选 PR242：只合并交付包

2026-10-06。当前结论：正式测试、原独立审核与候选外受信交付验证完成；尚未获得本包 G2，未合并或部署。人工门禁仅引用根 AGENTS.md。

## 精确绑定与实际能力

- PR：[242](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/242)，OPEN / Draft / MERGEABLE / CLEAN。
- base：`6e6aded22764ebee3d6a97f2834f47d4b4baa7bb`。
- head：`558df2a3bf83d590ccbdb010d3f73dc70d528041`。
- tree：`4ac8e2bc13f3d37d2fa84c98985da05a8f828083`。
- 受测 merge ref：`580067726f04ec96f267204a3047e58748b661f5`。

包含尚未合并的 PR240、PR241 的累计内容，再加入 A034 既有赛绩补连及 B039 翻译结果检查点：离线 HKJC 缓存复用与基本资料处理；既有单条赛绩的强身份赛事补连；正文清洗证据；翻译 claim/deadline 防护及同 claim 完整结果检查点恢复；SQLite 公开时间兼容与马匹搜索空态修复。没有重复创建来源或扩大真实抓取权限。完整 H03/M02、真实来源覆盖、可靠 outbox、跨轮费用准入与自动恢复尚未完成。

A036 命令入口、B041 离线预算台账及其 0080 迁移、C041 首页空态文案均不在本候选内。

## 完成证据

- A034 原 R `ca118aa960a609922f4b1aee81fdfb3e7c38eacf`、B039 原 R `fb8baef62d64cfe08bfe70bea143a8ce836a9947` 批准局部实现；C036 原 R `bdda4cb9` 批准集成准备。ROOT 已核来源 blob、审核报告和前后指纹。
- pull_request full：[run 37458330323](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/37458330323)，47 批，6,703 唯一测试，6,693 通过、10 项允许跳过，35 项新增测试实际执行；完整分母保持。
- ROOT 从实际 main 提取候选外受信核验器，下载该 CI 镜像并重新收集完整 ID、分批，核对 artifact、strict branch protection、base/head/merge tree；exit 0，receipt status `verified`。
- 收据：`/Users/mentianlu/.codex/runtime/pr242-trusted-delivery-001/delivery-receipt.json`；SHA256 `b173b012ffd7efddca655a925f89a68672c1d66ee19a182fc23f9dc0db3d8fb0`。
- 监督进程 78434、执行进程 78496 均已退出，ROOT 实时确认专用 Docker 空，验证资源已释放。

## 提议的 G2 范围

推荐仅将上述精确 PR 合入远端 main，不发布。获准后重新核对 head/base/required checks 与保护规则，在短时 integration lock 内将 Draft 转 ready 并执行受保护远端合并，再验证 main 实际包含候选并登记合并结果。若 base/head 或所需检查变化，按根 AGENTS.md 重新判断，不复用失效绑定。

| 动作 | 本包内容 |
| --- | --- |
| 迁移 | 无；本候选没有迁移文件变更 |
| 配置变化 | 无生产配置或环境变量变化 |
| 服务重建/重启 | 无 |
| 生产数据动作 | 无 |
| 功能开关/公开自动化 | 无启用或改值 |
| 真实抓取、付费、外部通知 | 无 |
| 验证 | 合并前精确绑定与 required checks；合并后远端 main/候选包含关系 |
| 回滚 | 生产运行版本不变，无需生产回滚；若主线需撤销，按实际 merge commit 准备 revert PR、验证并依根 AGENTS.md 交付 |

本次不提供“合并并发布”执行包：尚未完成本候选的生产运行态、互斥窗口和部署适用性核对。若用户希望发布，须先补成可审的精确发布包，再按 G2 选择。PR240/241 保持原状；本包不授权关闭旧 PR。

## 剩余项目风险

10/06 18:00 容量节点未达到完整真实分母及保守吞吐证据；本候选通过不消除该缺口。10/09、10/16 联调与 10/23 完整候选、10/28 全量、10/30 验收仍需按实际证据推进，不缩分母或压缩观察窗口。暂缓后台、F04 真人效率基线及 QQ 下线的用户决定保持。
