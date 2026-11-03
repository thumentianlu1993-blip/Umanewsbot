# QQ下线发布与恢复记录

下文原68063962发布包及准备状态保留为历史；最新执行与验收见文末。授权边界引用根[AGENTS.md](../../../AGENTS.md)。

- 固定候选：`680639625dee9d6ab70ae31f7e095cd5f0c85155`，生产ad50abdb的QQ窄回移包。
- manifest：[release-manifest.json](release-manifest.json)，SHA256 `a38b36aa2c5c1d6cdef1ce02eafb5078c224e28dbe606984b50e1fefc3419e8e`。
- 主线PR包含并发修复与资料；合并该PR不等于部署整个main。生产只构建上述候选，记录实际镜像ID和标签核对后再切换。
- 迁移：无新增迁移，维持stable.0079；继续使用受保护0079同schema发布流程，不绕过历史保护标记。
- 配置：QQ_CHANNEL_ENABLED、QQ_PUSH_ENABLED、MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED全部false；其他flag保持原值。
- 服务：web、worker、beat、race_sync_v2_worker按既有受保护顺序排空/重建；Nginx按原流程恢复。DB/Redis不重建。独立OneBot `9f77b49ec509a223cf30a9360350dfc6b358a193126afb1ba278b61f2cc2c98c` 取消自动重启并停止，不删除容器和挂载。
- 数据：不批量删除/清队列；旧消息自然消费时将符合条件的非sent投递标为skipped/qq_channel_disabled，保留sent、消息回执、历史请求/响应载荷。先私有保存相关投递状态快照。

## 预检、备份与切换

1. 核对manifest、候选源码、当前应用镜像、四应用、DB身份/schema、配置摘要与OneBot身份；任何漂移先重新绑定，不默认授权。单一release coordinator遵守现有生产release lock；发现P04/其他任务持锁不抢占、不代释放。本包没有向其他会话发送消息的动作。
2. 连续三次有界采样（间隔20秒），1分钟负载不超过2核、可用内存至少2GiB、SwapFree至少1GiB，磁盘空间足够备份和镜像。条件不满足不启动重型备份/构建、不停止服务。构建和备份继续受限时及资源观察约束，失败仅停止本包。
3. 私有保存现有.env、Compose配置、旧应用镜像身份/保留tag、OneBot inspect/挂载/重启策略、相关投递记录；凭据不入库或输出。用固定候选和复制后的运行配置显式设置三false。受保护`deploy/deploy_0079.sh`负责候选构建、自己的新备份/摘要/TOC、schema与在途状态检查、停止Beat、排空worker、关闭态发布与同intent恢复，禁止跳过preflight。
4. 新备份TOC通过不等于完整恢复通过。生产历史唯一索引异常及P02完整恢复缺口仍存在；本包无schema/历史批修，不以数据库整体恢复作为常规回退手段。若受保护发布步骤拒绝或备份预算失败，保持未切换状态，不能改hash/阈值放行。
5. 候选四应用启动后逐一确认版本和三false、旧QQ任务仍注册；验证网页/后台与Beat无QQ周期。若需要读取Beat持久schedule，待Beat停止后保存副本，只在副本或受保护检验中检查，不在线改共享shelve或删除全部定时任务。
6. 固定OneBot身份、无共享挂载使用者再次核实后，在现有生产release lock保护的独立短操作中执行：按完整容器ID将restart设为no，再正常stop；验证Stopped和restart=no。保留全部挂载与日志。若锁被其他任务持有则等待，不能无锁操作。

## 验收与异常恢复

通过只读任务日志/数据库计数/队列注册信息，观察至少10分钟：旧QQ任务可被消费为停用，但无新派生QQ重试、OneBot探测及新增sent事实。不要通过实际发送消息测试下线。保留停用前的sent分母与已有在途未知状态，无法归因时不宣称零发送已证实。UI无发送/重跑入口，公开网页、后台、新闻发布和非QQ通知的只读状态正常；比较DB/worker CPU与负载，不把QQ下线等同赛事术语查询已优化。

异常沿原固定intent、镜像与false配置执行`deploy/deploy_0079.sh resume`或前向修复。普通旧代码回滚仍被既有策略禁止；不自动恢复OneBot、QQ开关或重新投递历史消息。服务不能恢复时按受保护流程保持失败状态并报告，不用删除恢复标记/迁移记录强行启动。未来重新启用QQ不在本包范围内。

## 证据及剩余条件

私有目录`/Users/mentianlu/.codex/runtime/qq-retirement-20261103/`保存生产身份、配置摘要、RED/GREEN、固定源PG收据与原reviewer复审。发布方案审核及主线PR检查收口后才能提交G2选择；准备阶段当时不得称生产已下线；实际执行结果见后文。


## 2026-11-03 已执行及最终验收失败

用户确认操作2后，PR271合并为adfa98827d80af5847cdf6e4e999d9cd8e436656。资源连续三次达标后，原0079入口完成候选68063962的同schema发布；镜像为eed3bf6b70136631c8fc322bae542cb7d84be923612b0125f550cfbdb33cb202。本次新备份917915919字节，通过摘要及TOC校验；不宣称完整恢复通过。旧worker自然排空，计划的cancel_consumer因发布已完成而在状态校验前退出，未执行。OneBot在独立锁内停止，restart=no，挂载保留。

最终Celery验收发现Kombu 5.7.0与redis 5.2.1不兼容。新版本的web健康，但三个后台服务重启循环；已在锁内停止worker、race_sync_v2_worker、beat，保留web、DB、Redis及全部队列，QQ保持关闭。受保护入口退出0及complete收据不等于后台业务验收通过。私有证据位于本机qq-retirement-20261103及生产/opt/umanews-qq-retirement-20261103。

### 前向修复方案（历史准备状态，执行结果见下文）

候选9def4a7be906a5e91d47ab5dd7ba888496f62b00仅固定原生产Celery依赖组合，并增加构建期Redis transport检查和回归。无迁移、无QQ开关变化，不重新启动OneBot。先完成隔离回归与独立review，再通过0079同schema入口发布；当前已停止的后台服务会被新发布意图保留为停止态。后续恢复必须在独立发布锁内同时核验原68063962的恢复意图、新候选的完成收据、实际schema/image/config，再仅恢复原意图中应运行的worker、race_sync_v2_worker及beat。不得改写旧/新intent或用无校验的Compose启动替代受保护发布；新恢复动作须纳入精确包后确认。


## 2026-11-03 兼容性恢复发布与观察

用户明确“合并并发布恢复包”。PR272固定头`c1739e7ae9553b7c3e201647561aaa189de9d704`合并为`6a42c26482fd211a6e20238ec92808c6b4ed77f7`。批准的恢复包manifest SHA256为`abba584ff9e38e729941fdaf91692cecd82369e7762a7b2de8ccea51a9a92e1c`；其绑定源码、原恢复收据、激活脚本、观察脚本、测试及目录外交付收据，私有证据在既有本机目录和生产`/opt/umanews-qq-retirement-20261103/compat`。

生产固定候选`9def4a7be906a5e91d47ab5dd7ba888496f62b00`，目录`/opt/umanews-release-9def4a7b-qq-compat-20261103/umanewsbot`，镜像`sha256:3724748524a1f03e2061c6f9fcffc467b9986582f8e72354877b5d62c466068e`。连续三次资源达标后，由原0079入口构建、生成新备份并执行同schema发布，21:13:11 CST退出0。备份917968745字节、1401行TOC；仅摘要/TOC验证，不声明完整恢复通过。配置SHA仍为`c2815ad4f419e362caca584d97019c24faabdb0a05b1e77463974823b846472e`，无迁移、配置变化或批量数据动作。

新intent为`944007d5d8b073766346b960fab0ea5becfc4d7274fd19e2c8e23ed6ed51cdef/intent.json`，SHA256 `c9d3bb4f6168ddf07e3d46e582a33a6ac422998c5d6f65c93c4f2bd0eb88c95a`；同目录complete SHA256 `2ad2dd1a5cf2569abc22e442e9b6fded88784c67ebbfebe90e89999c79ffbaa3`。它如实保留新发布开始时三个后台为false的意图。另行绑定的激活步骤在发布锁内核对原680运行意图、本次完成凭据、恢复标记、实时schema/image/config，才恢复worker、race_sync_v2_worker及beat；旧race_live_worker继续停止，全部队列保留。

首次激活调用遗漏原生发布的`UMANEWS_RELEASE_COMMIT`，构建参数默认unknown导致有效Compose摘要不匹配；检查在写activation-started或启动服务之前拒绝并释放自己的锁。只读核对确认.env及其他运行配置未漂移，补传同一候选SHA后摘要精确匹配，原已审核脚本原字节重试成功。未改manifest、原生intent或任何保护标记。

21:17:49 CST观察开始：四应用同镜像、重启计数0；两个worker实际broker ping与旧QQ注册正常；三个QQ开关false、无QQ周期/在途任务，OneBot停止/restart=no；784条历史sent原样保留，新增sent为0；首页/healthz/admin登录均200。21:28:39 CST最终检查通过，实际观察650.11191秒；四应用身份与重启计数均未变化，QQ新增sent/通知发送/投递行/重试日志均为0，无QQ在途任务，历史sent全字段保持原样；所有HTTP检查200。恢复前普通队列197、race_sync_v2队列0、旧race_live队列7543；只恢复原非QQ消费者，不清队列、不启动race_live、不发送QQ验证消息。

测试与审核：121项PG回归、隔离真实Redis消费、6项中断/标记/停止失败故障注入通过；原代码与方案reviewer均APPROVED。CI41634318456为49批6866项，6856通过、10项原有环境测试按本任务明确豁免。目录外核验第一次因本地临时路径不在VM共享挂载内失败；改用既有隔离共享目录，受信核验器字节不变，重跑verified。收据绑定合并测试对象`5115e53605ec96935440c63828819a05a5edbc5e`与tree `d5dc3805856767595e8a0ed83b34a4b9a766c633`，不是生产验收替代品。


最终生产验收收据：本机`/Users/mentianlu/.codex/runtime/qq-retirement-20261103/production-recovery-receipt.json`，远端`/opt/umanews-qq-retirement-20261103/compat/observation-complete.json`；新发布、激活、依赖版本、队列消费及观察摘要的脱敏副本保存在本机`recovery-receipts/`。普通队列曾从197降至29，两个worker均报告任务活动；旧race_live队列7543保持。OneBot完整容器ID、镜像和三处挂载按挂载目的地规范化比较一致，未删除登录数据。生产实际依赖为Celery5.4.0/Kombu5.6.2/redis5.2.1/billiard4.3.0/amqp5.4.0。公网HTTPS首页、healthz、admin登录入口均200，未用真实QQ发送做验证。最终load1为0.88，不据此宣称完成数据库性能优化。

本轮保留已存在的retrying/failed历史记录，不做批量状态清理；验收证明的是观察窗口内无新增QQ发送、重试或投递。生产历史唯一索引异常及P02完整恢复缺口仍不由此包解决。此次完成的是QQ停用和依赖故障后的后台恢复。
