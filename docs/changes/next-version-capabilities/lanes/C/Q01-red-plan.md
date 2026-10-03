# C-004 / Q01 mock OneBot RED与回归计划（未执行）

日期：2026-10-03（Asia/Shanghai）。与Q01-plan同base `03e5afbbfd2f31cef19285de3f0758a8d6134602`，方案审核前不创建或执行新增行为测试；以下是拟测试合同，不是RED/PASS证据。覆盖总矩阵TC-Q01中Q01部分；按钮移除/专属服务退出另由Q02覆盖，生产零外发账本归后续发布验收。

## 第一批必须取得真实RED

复用已登记`stable.tests_legacy.PushTests/QQAutoPushTests`的脱敏文章/目标fixture。全部HTTP、Celery delay/apply_async、邮件为mock或locmem；fixture群号合成，任何缺mock触网由隔离容器阻断。

1. **手动HTTP入口**：staff登录→`article_push_api`，设QQ_CHANNEL_ENABLED=False，同时QQ_PUSH_ENABLED=True、有效目标。patch push_article_task.delay和OneBot requests.get/post，POST期望410、queued=false/reason=qq_channel_disabled且delay/get/post全0、文章workflow/status/发布时间原样。旧代码忽略总许可返回200/queued=true并调用delay，因此是有效行为RED，不能因未登录/不存在fixture而失败。
2. **terminal直接调用**：QQ_CHANNEL_ENABLED=False，mock requests.post的合法OneBot成功响应，调用现有send_group_message（有图/无图）以及直接_post_message。断言post调用0且有明确停用结果/异常，不能返回成功。旧代码至少POST一次，捕捉绕过入口；RED测试不先import尚不存在helper/异常类而因ImportError失败。
3. **迟到delivery**：有效公开文章/目标、RETRYING历史delivery、旧开关True但总许可False、非eager。调用qq_push_delivery_task.run，patchHTTP/publicURL check/self.apply_async，期望SKIPPED停用、attempt未增、三类网络调用/重排0。旧实现会进入节流重排或process；分开固定时间让两分支各真实触发，不能让不合格fixture掩盖缺陷。

每一最小RED先固定提交和失败日志再改对应行为，失败必须来自禁止发送/入队/状态断言，不能由infra、missing module、无权限或随机时钟造成。

## 场景矩阵

| ID | 场景 | 必要断言 |
|---|---|---|
| Q01-01 | 所有legacy自动/地区/ops开关True，总许可False或缺失 | OneBot GET/POST为0，总许可不能被旧开关绕过 |
| Q01-02 | terminal有图/无图、直接_post、图片异常fallback | disabled零POST/无fallback第二发，不伪成功；启用态纯mock原协议/错误脱敏仍回归 |
| Q01-03 | staff手动API、非staff、未登录、不存在文章 | staff410/queuedfalse；原鉴权/404保留，无队列/日志伪成功 |
| Q01-04 | Admin push_view GET/POST有效/无效表单 | 停用提示、零queue、无成功消息；文章不被改PUSH_FAILED/PUSHED |
| Q01-05 | 直接pushing service、enqueue、迟到push_article_task | 零网络/queue；任务skipped理由；不写文章status、无虚假成功/失败PushLog |
| Q01-06 | 手动/自动网页发布，OneBot mock抛错 | 正常workflow/公开时间/公开页面、关联扫描仍执行；QQ入队0；网页完成不依赖OneBot |
| Q01-07 | source elevation/on_commit自动入队 | commit callback被执行也不delay；关闭前注册、执行前关闭的callback不入队 |
| Q01-08 | auto task直接run/旧消息，ensure/select直调用 | 不建delivery/QQ曝光/配额，不派子任务；既有数据保留 |
| Q01-09 | region/prod window旧beat消息、缺失/历史时间窗口 | skipped/停用，不创建QQ窗口、占额或fanout；共享publish窗口照常 |
| Q01-10 | QQ窗口preview/rerun与publish窗口rerun | QQ停用检查先于PENDING写入/rerun_count/claim/probe；publish功能保持 |
| Q01-11 | PENDING/RETRYING/FAILED/SKIPPED/stale SENDING迟到任务 | CAS→SKIPPED/NOT_ELIGIBLE/qq_channel_disabled，attempt_count/历史payload不变；0retry/节流重排 |
| Q01-12 | SENT/fresh SENDING；CAS前另一执行者已改SENT | 不覆盖发送回执；fresh在途标待核，不假称撤销，条件UPDATE输给SENT不降级 |
| Q01-13 | process直调用、发送前停用异常 | 统一停用状态、不当SEND_FAILED/RETRYING；不会因兜底异常catch再发/重排 |
| Q01-14 | ops QQ+email同时配好，通知总开关True | QQ SKIPPED/固定原因、post0；EMAIL正常locmem一封；cooldown/签名不变 |
| Q01-15 | automation QQ预留渠道、warning email、其它channels | QQ原因停用；email逻辑/去重与既有SMS/WeChat预留状态保留 |
| Q01-16 | 后续总许可True但已标停用SKIPPED | 无自动恢复/reclaim；旧未处理pending恢复范围明确为待授权，不伪装全封存 |
| Q01-17 | env配置和旧参数 | 默认False、env_bool严格读取；OneBot/群目标历史配置保留，不输出token/请求正文 |
| Q01-18 | 新发送路径/裸HTTP漏网扫描 | 全server非测试代码仅受guard保护的OneBot发送边界；新增调用者必须登记，未知fail closed |

QQ既有启用态测试可显式override总许可True并全部mock发送，保留原协议/幂等/限流/脱敏/来源门禁；不得删原测试、降低断言或在disabled测试中启用总许可。静态扫描只是补充，不替代真实task/API/服务回归。

## 测试模块与隔离执行

优先新增到已登记`server/stable/tests_legacy.py`（PushTests、QQAutoPushTests、QQWindowServiceTests、相关API/Admin/通知/自动发布类），必要独立模块先交规则owner登记，不静默unknown。该模块通过`stable.tests`重新导出；实际collection核label/profile，不凭名称推数量。

先宿主隔离SQLite用于有效RED与快速修复；状态CAS/任务迟到、on_commit、窗口事务在固定Linux/PG16、network-none执行。采用既有独立DOCKER_CONFIG/TMPDIR、immutable image、固定Git SHA；每批<=200，总并发<=2，先获协调窗口再运行。不接真实生产DB/Redis/Celery，不用外部模型/邮件/QQ网关。

按真实实现diff生成正式907f→本卡候选计划，保留旧/新规则覆盖与必要full。新views符号/配置/fixture若unknown交协调规则owner，focused诊断不冒充交付收据。U01已交03e5的证据不因Q01文档新head重做，也不称Q01已测。

任务顺序：

- (integration) 固定最小手动/terminal/迟到RED，记录真实失败。
- (integration) 总许可与发送末端guard→业务早退/CAS→非QQ和网页解耦回归。
- (application) API/Admin/窗口旧接口停用反馈，不清理Q02入口。
- (integration) 固定候选Linux/PG及影响策略要求检查，原R代码review/复审。
- (operations) 整理停用切点/在途/配置与恢复范围交协调者，开发阶段不执行发布或真实外发。
