# 执行记录

- [x] (operations) 只读核对运行代码、开关、四应用及独立OneBot身份，保留私有证据。
- [x] (integration) 生产形状零次离线重试与旧worker领取停用记录均取得真实RED。
- [x] (application) 从生产ad50abdb回移QQ关闭与界面退出，不加入其他业务/迁移。
- [x] (integration) 修复原子claim复活已停用记录，保留旧任务注册及历史载荷。
- [x] (operations) 固定源、固定镜像、network-none的PG16回归120项通过。
- [x] (integration) 原代码reviewer确认P1修复关闭；最终固定源测试收据已补齐。
- [x] (operations) 发布方案独立review与原代码reviewer最终差异绑定完成。
- [x] (operations) 原QQ包最终CI41601244128通过：6855通过、10项明确豁免；早前41597754516的6项日期夹具失败已修复，不能把该失败轮记为通过。
- [x] (application) 固定赛历测试业务日期，消除硬编码2026年与真实日期加60天跨年冲突；该模块25项离线测试通过，原reviewer独立复审APPROVED。
- [x] (operations) 用户明确“剩余10项无需回归了，继续推动QQ下线”。不引入额外设施；十个精确ID的既有环境skip按本次明确人工决定仅接受至2026-11-03，保留覆盖缺口，不声明零skip。固定生产包不变。
- [x] (operations) 用户先后确认原QQ包与兼容性恢复包；PR271/272已合并，固定生产68063962后前向发布9def4a7b，未部署整个main/P02。
- [x] (operations) 恢复后650秒观察通过：零新增QQ发送/重试/投递，历史784条sent保留，OneBot退出，四应用零重启、网页/broker正常；最终load1=0.88，不把下线等同数据库性能优化。

- [x] (integration) 真实失败镜像复现Redis transport版本冲突；固定旧生产可用依赖并加入构建检查。
- [x] (integration) 固定源121项PG与真实隔离Redis/Celery消费通过；原代码reviewer复审APPROVED。
- [x] (operations) 恢复方案补齐保护标记、精确完成凭据、信号清理/停止复核/失败保锁；6项故障注入及原方案reviewer复审通过。
- [x] (operations) 恢复主线CI41634318456：49批、6856通过、10项本任务明确豁免；目录外交付核验verified。
- [x] (operations) 新备份校验、同schema发布、独立后台激活完成；21:17:49 CST验收基线及21:28:39 CST最终观察均通过，独立交付收据已保存。
