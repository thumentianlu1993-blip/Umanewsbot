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
| 生产验收 | 固定9def4a7b观察650秒通过：四应用同镜像/零重启、三个QQ开关false，无QQ周期/在途/新增sent/新增投递/重试日志；784条历史sent原样保留，OneBot停止/restart=no且挂载完整，首页/healthz/admin登录200 |

窄候选测试收据：`/Users/mentianlu/.codex/runtime/qq-retirement-20261103/test-receipt-final.json`；测试源tree为`d3c043ba7f8dacc2541239d004454ec43e368cc3`。主线PR CI结果单独记录，不称全量生产验收已通过。


兼容性恢复新增证据：真实失败镜像Redis transport版本冲突RED；固定依赖后的121项PG与真实隔离Redis/Celery消费通过；激活保护6项故障注入及独立审核通过。主线CI41634318456为6856通过、10项本任务明确豁免，目录外核验verified。650秒生产观察单独绑定9def4a7b及镜像3724748524a1，不把CI、备份TOC或worker Running等同实际验收；亦不声明完整备份恢复通过。
