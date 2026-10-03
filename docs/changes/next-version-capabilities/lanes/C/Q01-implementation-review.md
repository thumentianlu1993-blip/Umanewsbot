# C-005 / Q01 实现提测包（待原R代码审核）

日期：2026-10-03，Asia/Shanghai；DDL10/06 18:00。方案原R在`54e972504ab677f5f6edd66775898b53ffc9344c` APPROVED；本卡base固定`03e5afbbfd2f31cef19285de3f0758a8d6134602`，U01不改。受测行为head `5b30966f69857c4ecc7a0310074f85ac11609030`，最终文档/测试head由交接消息绑定。

## 已实现

总许可`QQ_CHANNEL_ENABLED`默认False，只有bool True授予QQ链路许可；旧自动推送/地区/ops配置不能绕过。所有原方案列明的发送入口/service/末端消费同一helper，停用原因固定`qq_channel_disabled`。OneBot status GET与text/image/direct _post均有guard，图片fallback不会捕获停用异常再发送。

手动API保留登录/staff/404合同，停用返回410/queuedfalse；Admin GET/POST明确提示且不入队。窗口preview/rerun的QQ检查在claim/计数/配额/网络前，publish分支维持。自动入队在注册和执行on_commit时都检查，来源升权/旧周期task早退；网页公开保存、关联扫描不依赖QQ。

迟到delivery在节流前结束，不产生apply_async；process直调用同样保护。停用CAS只处理pending/retrying/failed/skipped/stale sending，不覆盖SENT或fresh SENDING；相同停用标记不重复更新，不隐式恢复。若本执行者已claim但尚未HTTP时收到明确停用异常，按同attempt/time/status条件结束并退还本次attempt；不能抢其他执行者/SENT的回执。

人工发送仅在真实发送返回成功/失败后写本次PushLog，停用异常不伪造FAILED/永久QUEUED，也不把文章改PUSH_FAILED。旧已保存PushLog/QQ配置/目标/历史delivery不删除；没有迁移/批量封存。ops仅QQ子渠道SKIPPED，邮件与warning去重维持。

变化严格限方案列出的QQ块，另维护必要旧QQ测试fixture显式总许可True（全部mock）以保留启用态合同；没有Q02按钮移除、beat键删除、OneBot容器/健康探针退出。

## 真实RED与宿主结果

- 最小RED固定`0215846a77c91f1fcfa59d1420342da95c236a83`：3case/5failure/0error，HTTP200≠410、迟到状态retrying≠skipped、text/image/direct post三次mock调用；无外发。
- 扩展RED固定`6700efa9d82bb01218feb5fb485adf2e3883756a`：13case/23行为failure/0error，覆盖fanout/commit/publication/mail/历史状态。期间修正了测试mock序列化和未导入符号，只有无infraerror的真实RED用于结论。
- 实现后宿主72项：70PASS+2显式PG-only skip，0error；随后新增Admin GET/invalid POST和warning邮件去重2项宿主PASS。合计74个已定义短测试（宿主并发2项不能算PASS）。
- diffcheck与workflow contract PASS。宿主或短PG不是最终影响策略收据。

## 固定Linux/PG证据

采用既有独立DOCKER_CONFIG/TMPDIR、Git archive/只读源码/nonroot/network-none，immutable image `sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905`。实际PG16.15 Ubuntu aarch64、Python3.12.3/Django5.2.1、Linux6.8.0-100/glibc2.39。

- 行为5b309固定短PG：collection72项/1批batch-000，72PASS/0failure/0error/0skip，lifecyclecomplete/exit0，总8.9515秒；两连接CAS实际运行，网页/邮件/迟到/on_commit覆盖通过。
- 最小021584固定PG RED：collection3项/1批，3case/5failure/0error/0skip，complete/exit1，总8.1200秒，与宿主同缺陷。
- 两批仅lo、外Python/curl blocked、nested Docker daemon blocked。没有接生产DB/Redis/外部OneBot。
- PG后新增两项普通UI/邮件测试仅宿主验证；核心实现字节未变化，不冒称最终74项都已有PG收据。
- 完成后docker ps空，无在途container/batch，已向协调者释放资源，不继续自动full。

产物`/Users/mentianlu/.codex/runtime/q01/`：`pg-focused-5b309.json`、`pg-5b309/execution-plan.json`与`batch-000.json/log`；`red-focused-021584.json`、`red-pg-021584/execution-plan.json`与`batch-000.json/log`；`red-local.log`、`red-expanded.log`。

GREEN receipt SHA256 `7a7d3487b04b1b8a78bd954fb9caa3a9ed13e28bca7fed5d20a80a5aa98dfa30`；RED receipt SHA256 `83c1449eec8664666af103f9ab20502610df36d7c91bb72e5b223d318605c1ce`。

实际命令均前缀`env -u DOCKER_CONTEXT -u DOCKER_HOST DOCKER_CONFIG=/Users/mentianlu/.codex/runtime/c003-impact-docker TMPDIR=/Users/mentianlu/.codex/runtime/c003-impact-temp python3 scripts/run_test_plan.py`，按固定计划collect，再固定image执行`--batch batch-000`；原RED通过同runner自动collect/run。计划保留精确base/head/tree/hash/labels和diagnostic_only标记。

## 18场景追溯

| 方案场景 | 测试/核对 |
|---|---|
| Q01-01 | all_old_task_entrypoints + channel_permission布尔/缺失 + direct services |
| Q01-02 | terminal_disabled / enabled_gateway协议与图片fallback / terminal_shutdown_after_claim |
| Q01-03 | manual_api + disabled_api_auth_and_missing（登录/staff/404） |
| Q01-04 | admin_post/window_rerun；新增admin_get_and_invalid_post（宿主） |
| Q01-05 | direct_manual_service_and_late_task，无PushLog/网页status漂移 |
| Q01-06 | web_publication_survives_gateway_failure，手动/自动公开及关联扫描 |
| Q01-07 | commit_callback_rechecks_shutdown + 两个旧来源升权启用态回归 |
| Q01-08 | direct_auto_services/no配额/delivery + auto task无fanout |
| Q01-09 | old_task_entrypoints/window早退 + 原QQWindowServiceTests启用态 |
| Q01-10 | admin_post_and_window_rerun + publish_window_rerun不受影响 |
| Q01-11 | late_delivery + pending_states，attempt/历史payload保护 |
| Q01-12 | fresh/SENT状态矩阵 + 两连接sender commit赢旧快照与双worker停用 |
| Q01-13 | terminal_shutdown_is_not_manual_failure_or_retry_after_claim |
| Q01-14 | ops_email_and_automation_email_continue QQ跳过/邮件mock一封 |
| Q01-15 | automation QQ/SMS/WeChat预留、email；新增warning邮件去重（宿主） |
| Q01-16 | old_disabled_delivery_does_not_resume process/task/ensure |
| Q01-17 | channel_permission布尔/缺失；配置/历史保留由diff核对 |
| Q01-18 | 代码发送路径扫描与末端覆盖，非测试实际POST仅受保护的onebot；不是运行账本 |

## 正式策略阻塞与精确映射建议

正式907f→5b309计划fail-closed，唯一unknown为`views.py:article_push_api,production_window_preview,production_window_rerun`。建议各符号精确映射既有`module:stable.tests_legacy`及`module:stable.test_multiregion_rollout_change`，不改catalog/profile/dependency，不缩base/降高风险full。本线没有修改共享rules/catalog，交协调者/owner受审整合。

原R需审本卡03e5→最终head，重点末端typed停用异常、CAS所有权/fresh/SENT保护、邮件独立、API/Admin明确结果、启用态mock fixture范围。代码review与正式impact/full、未来生产零外发账本分别记录；本线不自标完成。

## 生产/恢复仍未执行

生产配置/服务/队列没有改变，QQ尚未宣称停用。方案中的web/worker/beat同SHA配置、旧进程在途切点、未处理pending恢复范围及QQ渠道false/旧窗口配置仍交协调者按精确发布包组织。未purge共享队列、未批量改库、未启用总许可、未停网关、未发送真实测试消息。
