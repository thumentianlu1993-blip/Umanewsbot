# C-004 / Q01 全QQ停用与网页解耦方案（待协调/原R审核）

日期：2026-10-03（Asia/Shanghai）；DDL：2026-10-06 18:00。工作树bc9b、分支codex/next-version-product-ui-20261003。本卡base为U01固定交接`03e5afbbfd2f31cef19285de3f0758a8d6134602`；U01行为不再改。本轮只规划，未新增测试/行为代码、未变生产、未外发。

F01依赖消费已测已审`0e05029c`的合同定义（只读Git对象，不cherry业务模块）。该合同的LoaderInput/DecisionOutput/PublicSummary校验不授予发布或发送权限；网页公开权限继续由现有workflow/publication校验负责。Q01不为QQ新建DTO、不扩展F01协议，不把QQ投递状态作为网页成功条件。

## 目标、现状及边界

版本要求关闭QQ全部自动/手动/重试/遗留周期路径，保持网页发布和非QQ通知。根AGENTS为唯一G1/G2/G3来源；本轮规划按既有派单推进，行为实现等待方案审核派单，主线/发布/外发不在当前动作中。

当前只读代码确认：单个`QQ_PUSH_ENABLED`只挡自动入口；手动链、delivery执行和ops QQ可绕过。唯一实际QQ HTTP POST位于`services/onebot.py BotPusher._post_message`，图片失败会降级再发文字。没有读生产开关或队列，不声称QQ当前已停。

不删配置/群目标/历史投递表、不新增迁移、不批量清队列或改历史SENT，不停OneBot服务。Q02另负责入口移除、QQ专属周期/容器/健康探针依赖清理；Q01先使旧入口明确停用、旧周期任务无害结束。

## 路径盘点（固定base代码）

| 起点与函数 | 数据/调用流及当前缺口 | Q01处理 |
|---|---|---|
| `tasks.publish_article`、`services/automation.publish_article_automatically`、`views`候选发布分支 | 保存网页公开状态后→`enqueue_qq_auto_push_for_article`→on_commit→auto task | enqueue统一停用后直接返回；保持网页保存、后续马匹关联扫描、公开校验 |
| `tasks._qq_push_after_source_elevation` | 已公开文章来源升权→auto task dispatch | 总开关前置，无QQ入队 |
| `qq_auto_push.enqueue_qq_auto_push_for_article`、`qq_auto_push_article_task` | 自动筛选/QQ曝光配额→ensure deliveries→delay | 入队与执行均校验；关闭时不创建delivery/曝光、不调队列 |
| `settings.CELERY_BEAT_SCHEDULE['qq-production-regions-window']`→`qq_production_regions_window_task`→`qq_region_window_task` | 每5分钟派地区窗口、占额度/建delivery→delivery task | 老beat消息也在task入口skipped，无派生任务；专属调度移除归Q02 |
| `views.article_push_api`→`pushing.enqueue_push_for_article`→`push_article_task`→`push_article_to_targets` | 手动API未检查QQ_PUSH_ENABLED；service会把文章status改PUSHED/PUSH_FAILED | 各层前置关闭；API鉴权/对象存在校验后410、queued=false/reason；不写文章status、不建成功/失败PushLog |
| `admin.NewsArticleAdmin.push_view` | POST手动入队且提示成功 | 关闭时不解析发送表单/入队，明确停用warning；GET停用提示；按钮/目标入口物理移除归Q02 |
| `views.production_window_rerun`的QQ分支及`production_window_preview` | QQ rerun在probe前已把window改PENDING/增加rerun计数；preview调用QQ选择器 | QQ分支在修改/claim/OneBot probe前停用；publish分支保持；预览返回停用而不占额 |
| `qq_windows.select_qq_window_deliveries`、`qq_auto_push.ensure_qq_push_deliveries` | 可被上述入口或直接调用，占配额/曝光/建delivery | 服务端也前置空结果/qq_channel_disabled，避免绕过task |
| `tasks.qq_push_delivery_task` | 迟到消息先节流apply_async，再process；失败RETRYING再次apply_async | 总开关必须在节流前；关闭后不重排，执行端再次校验 |
| `qq_auto_push.process_qq_push_delivery` | is_online→claim增加attempt→网页URL探测→send | disabled早退，不probe/claim/检查URL；停用异常单列，不能当发送失败而重试 |
| `ops_notifications.send_ops_notification`→`send_production_summary_notification`及identity冲突task | 独立ops开关+QQgroup便发送，不受QQ_PUSH_ENABLED约束；同函数还发邮件 | 仅QQ子渠道记录SKIPPED/qq_channel_disabled、不send；邮件分支保持 |
| `notifications.send_automation_notification`、warning email、`tasks.send_notification_task` | 当前QQ/SMS/WeChat为预留SKIPPED，EMAIL真实发送 | QQ停用原因统一；不全局关闭通知task/ops总开关或邮件去重 |
| `onebot.BotPusher.send_group_message/_post_message/is_online` | send_group无渠道检查，图片fallback可第二次POST；is_online发GET | 发送最后边界及直接_post调用均阻断；关闭时is_online返回False/qq_channel_disabled且零GET |

全server非测试Python扫描：实际BotPusher调用方为pushing、qq_auto_push、ops_notifications、tasks/views窗口探测；未发现management命令直接发送（现有repair命令只统计QQ历史）；signals中的suppress_qq_push是历史修复线程上下文，不替代总开关，也不改变其保护语义。

## 推荐统一策略与停用状态

新增`QQ_CHANNEL_ENABLED = env_bool('QQ_CHANNEL_ENABLED', False)`作为所有QQ路径的总许可；旧QQ_PUSH_ENABLED及地区窗口/目标开关保持历史含义，自动路径必须总许可与原开关同时满足。仅设置旧开关True不能恢复本版QQ；总许可缺失/非True按关闭处理。恢复总许可是未来单独发布范围，当前不允许启用或外发。

共用`qq_channel_enabled()`和固定原因`qq_channel_disabled`放现有onebot模块，避免新服务模块/catalog漂移；terminal发送抛明确停用异常，不能返回伪OneBot成功payload。各业务入口正常返回skipped/空结果或明确停用响应，避免把网页发布抛成失败。发送前最后复核可挡同进程已变更状态；静态settings在各进程启动时加载，不能宣称单改.env即可热生效。

迟到delivery：保留SENT及message_id/sent_at原样；仅用条件UPDATE/CAS把未发送可处理状态PENDING/RETRYING/FAILED/SKIPPED和stale SENDING结束为既有SKIPPED，`last_error_type=NOT_ELIGIBLE`、`last_error=qq_channel_disabled`，不增加attempt_count，不清历史response/request。非stale SENDING不强覆盖，返回“停用/在途待核”，防止覆盖真实在途回执。task在节流前走此分支，不self.retry/apply_async；process同样防直调用，发送间隙遇停用异常不会进入发送失败重试。

已有停用标记`SKIPPED + last_error=qq_channel_disabled`在auto task、ensure/select及process均不自动重新发送，即使以后总许可开启；显式重新授权与重新创建/激活交付另属恢复包。未访问的旧pending队列仍需恢复前专项盘点，不在开发阶段批量改库。

手动停用不建虚假SUCCESS/FAILED PushLog（该enum无SKIPPED，避免为停用加迁移），沿已有OperationLog/TaskExecutionLog记录停用结果；QQ通知有现成SKIPPED可记录，但日志不含token/请求全文。窗口不新建/claim或改旧窗口为失败；旧rerun接口明确停用。

不用总开关关闭`MULTIREGION_OPS_NOTIFICATIONS_ENABLED`或共享异常探测/摘要定时任务，否则会损害邮件告警。网页发布仍保留workflow_status/published_to_web_at、公开权限、质量门禁和关联扫描，不借本卡改变出版策略。

## 文件与责任锁定

本卡仅下列QQ块，其他线程改动保留；不改models/migrations/F01或B模型适配。

- `services/onebot.py`：许可helper、停用异常、send_group/_post/is_online。
- `services/pushing.py`：enqueue_push_for_article、push_article_to_targets停用早退。
- `services/qq_auto_push.py`：enqueue/ensure/process及停用CAS；不改内容打分/来源/翻译。
- `services/qq_windows.py`：select_qq_window_deliveries前置停用；不改共享发布配额算法。
- `services/ops_notifications.py`：send_ops_notification仅QQ分支；`services/notifications.py`仅QQ预留分支原因。
- `tasks.py`：push_article_task、_qq_push_after_source_elevation、qq_auto_push_article_task、qq_push_delivery_task、qq_region_window_task、qq_production_regions_window_task的前置/返回；不改翻译、抓取、发布任务主体。
- `views.py`：article_push_api、production_window_rerun/preview的QQ分支；不改U01日历函数或其他API。
- `admin.py`：NewsArticleAdmin.push_view停用处理；入口移除留Q02。
- `app/settings.py`：只新增QQ_CHANNEL_ENABLED配置，保留旧参数；beat键删除留Q02。
- 现有QQ/通知/发布测试模块内新增回归；必要的旧mock QQ fixture显式允许总许可以保留原启用态回归，禁用态不能通过mock掉许可来绿测。实际diff后报精确选测与unknown，不擅改共享rules/catalog。

## 部署与恢复面（仅列清，不执行）

停用包需明确QQ_CHANNEL_ENABLED=false、QQ_PUSH_ENABLED=false、MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED=false、MULTIREGION_ROLLBACK_DISABLE_QQ_WINDOWS=true；旧群目标/OneBot参数保存但不输出敏感值。新代码默认总许可False，发布仍须精确包。web/worker/beat加载同SHA和配置后才可定义停用切点；先协调旧sender结束或有界等待，再检查在途，不把切点前已发生发送计为切点后新发送。已经开始HTTP的旧进程不能由新guard撤销，不声称在途发送被取消。

不purge共享Celery、不批量封存生产delivery。只读运行验收核任务派生/重试为0、QQ send HTTP为0、新SENT为0、队列迟到的停用原因、网页发布/邮件正常；不得为验收发真实测试消息。

恢复必须另外绑定旧pending/retrying/stale/inflight清单、时间范围和配置；仅恢复flag可能唤醒未访问的历史队列，不能称“只恢复新消息”。本卡触及的停用SKIPPED不自动恢复；后续显式恢复策略与授权不在本卡。

## 待审核结论及风险

推荐批准总许可默认False、停用API410/明确UI反馈、CAS终止迟到delivery且保留在途/SENT、ops仅停QQ。共享文件涉及约10个模块，3小时原估算偏紧，先完成mock RED→最小guard→回归；若审核选择删入口/停服务或批量数据封存，会扩到Q02/生产范围，应由协调者重排，不能夹带实现。

当前阻塞仅方案审核/实现派单；未拿生产快照不妨碍mock开发，生产切点与在途验收属于后续精确发布包。
