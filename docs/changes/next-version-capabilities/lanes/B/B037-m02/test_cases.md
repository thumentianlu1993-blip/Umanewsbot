# B037 测试清单：自动重试 claim/fence

输入为最终已审 B036 方案（来源 `82b0c725`，原 R 复审由 ROOT 确认 APPROVED_PLAN_ONLY）。固定实现基线 `2c72521c55b6cdc24f7650d172b48079cbff969a`。本清单落成该方案的测试设计，不扩大业务；当前只有测试准备，真实 RED 尚未执行，应用代码尚未修改。

## 首批 RED（五项，单批）

模块 `stable.test_translation_claim_fence`，类 `TranslationClaimFenceRedTests`。测试直接捕获 selector 既有 delay envelope 再调用 task.run，不用新签名 TypeError 作为 RED。

| ID 后缀 | 业务断言 | 可捕获 mutation |
|---|---|---|
| test_same_preclaimed_message_is_consumed_once | provider 返回前同消息入场，调用仅一次；成功派发仅一次 | 删除 claimed→executing 消费保护 |
| test_late_success_cannot_overwrite_new_claim | mock provider 内 stale 回收并新领取；旧结果不覆盖新状态/正文，零派发 | 删除成功写入归属核对 |
| test_late_terminal_exception_cannot_notify_or_fail_new_claim | 同上但旧 provider 抛 terminal 异常；新轮状态不变、零通知 | 异常分支先写状态/同步通知再核归属 |
| test_terminal_notification_observes_committed_article_and_exact_run_once | 通知时无事务，article+指定run都已失败；重投不通知 | 独立写run终态、通知在事务内或重复登记 |
| test_terminal_run_save_failure_rolls_back_without_notification | run保存失败时 article/run终态全部回滚、通知零 | 失败状态与run不原子、直接发送后回滚 |

TransactionTestCase 使 on_commit 真实退出最外层事务后执行；邮件、provider 和 automation 调度均替身。可控交错不是数据库真并发证据。首批完整 canonical ID = `stable.test_translation_claim_fence.TranslationClaimFenceRedTests.` + 表内后缀。

## GREEN 扩展（须各先取得有效 RED）

按 B036 方案再覆盖：源内容改变、run/article身份不符与缺 envelope、claimed_at保持、deadline精确边界与不得续期、保存成功原子回滚、终态重投、派发失败释放与stale归属/通知回滚、notify失败不回流provider、受管翻译明确run及无锁外部调用、JSON claim metadata兼容。分别拒绝删除输入摘要/fence/deadline/指定run/提交后通知的 mutation。

非法值、空值、旧 preclaimed 消息均 fail closed；普通首次翻译/force/manual 保留现有行为与人工字段保护。无 models/settings/migration变化。无新权限或对外发送开关。deadline只约束准入/回写，跨轮费用预算与outbox不在本片，按方案保留真实缺口。

PG并发后续两独立连接在消费点同步，证实只有一位消费成功及统一 article→run 锁顺序，事务不包provider；无需多容器。禁止以顺序测试替代该项。

## 执行与资源申请

当前 C029 占用 collector，**未运行 DB 测试、未启动任何容器**。请求 ROOT 释放后分配现有隔离 PG runner，运行首批五项：`python server/manage.py test stable.test_translation_claim_fence.TranslationClaimFenceRedTests --verbosity 2 --noinput`，需 runner 显式使用其测试设置/测试库和 mock-only 环境，不用项目 dotenv/真实 broker。新模块临时精确 label 仅用于 RED 诊断，不是正式 catalog/full 收据。

首批建议单 runner，2 CPU / 4 GiB、硬超时180秒（库迁移准备由 ROOT 独立计量/复用现有测试库），无其他并行任务、无新镜像或容器构建。如既有 runner 契约更严格沿其约束。命令/实际镜像/隔离DB设置及连接范围由 ROOT 回传后绑定运行 receipt，未经窗口不执行。

GREEN 同例之后扩展上列场景及 PG 真并发；相邻回归优先现有 recovery 测试、provider元数据/术语人工字段保护和 M01 mock。最终模块 catalog、共享 tasks 的 impact/full由 ROOT/C整合，不改共享登记或降低门槛。记录实际日志、exit、固定SHA和输入摘要，失败环境不算 RED。
