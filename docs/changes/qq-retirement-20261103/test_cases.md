# 验证范围

| 场景 | 验收与证据 |
|---|---|
| 真实故障形状 | synthetic连接拒绝、attempt=0/max=3；旧生产代码RED为retrying，候选标记skipped，重复消费不派生重试、不探测URL或OneBot |
| 并发停用与旧实例 | 旧启用worker读出记录后另一worker标记停用；原实现RED为SENT，修复后原子claim失败，保留停用、次数和历史载荷 |
| 并发所有权 | 两PG连接、旧claim过期后新owner、sender已提交sent；不借用新owner凭证、不覆盖sent回执 |
| 全路径 | 手动API/Admin/action、自动/地区窗口、旧任务、文本/图片/fallback、共享通知均遵守关闭总许可 |
| 界面与非QQ回归 | 历史明确标停用、无发送/重跑入口；网页发布与邮件等共享能力仍可用 |
| 调度与依赖 | Compose解析含所有profile，不含OneBot服务；Beat无QQ周期，其他任务保留 |
| 隔离与边界 | PG16、固定镜像、network=none、1CPU/2GiB、合成空库；120项通过、0失败/错误/skip，退出码0、无OOM |
| 生产验收 | 尚未执行：四应用固定候选/三个开关false、旧QQ消息终止而不重试、无新增sent事实、OneBot停止且restart=no、公开页面与后台正常、负载对照 |

窄候选测试收据：`/Users/mentianlu/.codex/runtime/qq-retirement-20261103/test-receipt-final.json`；测试源tree为`d3c043ba7f8dacc2541239d004454ec43e368cc3`。主线PR CI结果单独记录，不称全量生产验收已通过。
