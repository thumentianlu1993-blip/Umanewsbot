# 第一批设计与边界

公开 canonical 赛事是覆盖分母，当前来源 policy 仅限制抓取准入。新增纯查询 `build_public_race_coverage`，从 RaceEvent、登记、tracking、owner、结果行和公开读取门禁生成同一报告，供后台、命令和周期监控使用。不调用来源网络，不修改赛事事实。next_check_at 是下一次周期检查的预计时刻；next_poll_at 才是数据库中的实际抓取计划，两者单列。

监控使用现有 RACE_DATA_COVERAGE_ALERTS_ENABLED，每五分钟通过已有 race_sync_v2 队列运行。首发原用普通 celery 队列，生产发现监控排在 452 条任务后、期限仅 270 秒，故隔离新闻/翻译积压。Beat options 与直接 dispatch route 必须同时修改；coverage flag 独立于写入/发现开关，关闭写入开关仍可对账和告警。部署必须验证 race_sync_v2_worker 正在消费该队列；这一执行依赖要写入后续统一调度设计，不能把 flag=true 等同于有执行能力。

当前已有赛事 worker 并发为 1、soft/hard time limit 为 180/210 秒，SMTP timeout 30 秒，约 1.5 秒的生产 census 与业务任务共用该 worker。此小修正解决已观测到的普通队列饥饿；不承诺赛事队列自身长时间拥堵时仍可独立告警，第二阶段应设计独立监控执行能力与过期任务探测。

PostgreSQL 事务级 advisory lock 避免重叠 census；旧 discovery 不再写相同赛事的 coverage incident；全覆盖开关启用时，旧 SLO 的 stage/resolve/monitor 均委托新 census，避免已入库但不可公开的事件被旧任务关闭。关闭新开关后旧 SLO 仍按原行为记录。旧 data_sync_event incident 优先复用，缺口恢复、撤回或 canonical 合并后关闭；同一事件原因变化重开并清理旧通知收据。已人工暂停单列，监控不解锁。

告警为汇总邮件，单独 digest incident 租约串行投递；成功后才按相同 opened_at 回写子 incident。SMTP 失败保留未发送状态，使用既有退避/次数机制，耗尽六小时后允许重新尝试；成功后十五分钟内不发送另一份新缺口汇总。已发送且未变化的缺口不重发。外部 SMTP 无幂等键，接受后进程在回写前崩溃可能重复一次，属于 at-least-once，不能承诺 exactly-once 或收件箱可见。

## 七场历史闭环

固定 ID 772/828/830/833/970/975/976。原 TRA 来源已过期且只有 provisional revision，不能改 policy digest 或将暂定结果强行升格。使用已下载的 ZEturf / Sporting Life 参考结果，每场完整马号、马名和到着顺序重新解析校验；828 的 4 号、833 的 7 号有明确跌倒证据；772 使用第二来源补齐第八名。共 52 行，跌倒 2 行的 reported/official position 均空。

`recover_race_coverage_20261002` 默认只读 dry-run，必须给 manifest 原始字节 SHA。来源原始 HTML 在本地包内按 SHA 绑定，apply 无网络。命令只接受固定七场，校验公开/完赛/过去日期、canonical、无人工锁、无活跃 claim、事件及结果 baseline、完整参赛名单、owner CAS、无已确认结果。先全批预检，再在同一事务中调用既有 disenroll 退役过期登记并废止 claim，CAS 移交 historical owner，调用既有受审参考结果 writer。任一失败全批回滚；相同 manifest 仅在结果、owner、退役和审核收据均仍匹配时幂等返回。

保留全部旧 observation/revision/source identity，不延长来源权限，不改永久 provider route，不启动旧 race_live 队列。复用既有 `human_reviewed_reference` 审核类别，不伪造官方 receipt；实际 reviewer 明确为用户授权的 Codex，source_refs 标明核验方法，public_label 使用“参考赛果（完整性已核验）”，不声称自然自动恢复或人工逐行操作。

## 已发现但不在本批批量改写范围

另有 11 场已确认资料被当前 live 公开门禁遮挡，监控新增 publication_blocked 分类，不将数据库已确认误计为公开闭环。这是第二阶段分离“刷新权限”和“历史发布依据”的设计输入。当前全覆盖也包含日期缺失、人工暂停、owner 冲突及不支持来源地区，不自动扩展抓取覆盖。

不新增迁移，schema 保持 0079。第二阶段只在本批上线后设计。
