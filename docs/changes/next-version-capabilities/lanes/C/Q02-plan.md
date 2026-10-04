# Q02 QQ使用入口与专属运行依赖退出方案（待原R审核）

2026-10-03 Asia/Shanghai。依tasks.md Q02/QG-02，DDL10/07 18:00。只读盘点基准 `7d15ffaa7df5f67233747499ab0c57e94fba25ac`；依赖已审Q01@`924a2a37edda1695a45a9c6275d24403d23bc702`，不是生产已停用。仅本方案和离线清单，无业务/配置/服务动作。

## 目标、真实状态与边界

QQ短期停用的既有冻结范围包括发送、重试、按钮与专属依赖；网站应独立运行。Q01已具备总许可false、API410、发送末端guard及旧任务停用CAS；尚不能据代码审核推断生产发送为0。当前Admin仍渲染QQ推送链接、仅写ArticleStatus.PUSH_READY的“标记为可推送”；QQ窗口仍有重跑/预览，地区生产展示QQ等待/失败，容易诱导进入停用流程。

根AGENTS.md是唯一门禁来源；本次已有指令覆盖方案准备，实施仍待本方案原R审核。发布和生产停用交O06，按根文件处理，不在本方案新增通用门禁。本线不改main/PR235，不拉Q02以外实现，不新增权限体系/模型/队列，不删除历史数据；只读历史查看延续现有staff权限。

## 行为与文件边界

入口显示统一复用`qq_channel_enabled()`，总许可false时执行下列停用呈现；boolTrue仅保留Q01既有受控兼容能力，不新增恢复按钮或自动恢复。无需新的UI flag或扩大恢复条件。

| 面 | 拟修改 | 保留合同 |
|---|---|---|
| admin.py NewsArticleAdmin | 从列表/只读字段/操作fieldset实际去除推送链接；从get_actions去除mark_published_ready，并在该旧动作直接POST路径复核停用，不能只藏按钮 | 翻译、待审核、网页workflow/publication不动；旧push URL维持Q01权限/对象合同与明确未入队提示 |
| console窗口detail/preview + views上下文 | qq_push停用窗口移除重跑按钮与发送预览入口，显示“QQ渠道已停用”，历史决策详情仍可读；旧直达preview只显示终止原因，不呈现预计QQ文章 | publish窗口的预览/重跑原样，Q01重跑不claim/不计数合同保留 |
| region_production模板 + view | QQ栏改为明确历史计数/停用说明，不将pending提示成可操作重试；公开发布状态不由QQ失败决定 | 不清空历史计数，不改region业务汇总查询、抓取/翻译/术语入口 |
| Django Admin历史模型/inline | PushTarget、QQPushDelivery、PushLog等历史查看保留，不新增发送入口；存量PUSH_READY/PUSHED/PUSH_FAILED只作为历史状态解释 | 不取消注册、不删除历史对象、不扩大权限；现有配置编辑并非发送许可，不因编辑而恢复 |
| public模板 | 当前扫描未发现QQ入口；作为验收面，不为搜索“push”而误删发布能力 | 新闻/赛事/马匹公开路径、HTTP与SEO维持 |

`mark_published_ready`名似网页发布，实际仅queryset.update(status=PUSH_READY)，因此只处理该QQ旧动作，不能按名称删除网站publish_ready业务。修改shared views/admin/tasks/settings前遵守root集成排队，保留其他线改动。拟业务文件仅上述UI适配与终止原因；专属调度/Compose由operations owner排队整合，本方案不自行改部署面。

## 旧任务兼容与终止原因

保留五个旧注册名及参数：push_article_task、qq_region_window_task、qq_production_regions_window_task、qq_auto_push_article_task、qq_push_delivery_task。不能删代码使已排队任务NotRegistered，也不能purge共享队列。Q01的reason=`qq_channel_disabled`及skipped结果维持；QQ delivery停用标记不隐式恢复，fresh/SENT及不可变claim token保护保持。

实施前核每个入口当前日志落点：已有TaskExecutionLog写reason的复用原记录；停用早退发生在_start_task_log前、仅返回字典的入口，补一条最小执行审计（同次调用只一条），detail写固定终止原因，既有SUCCESS表示任务已正常终止而非消息已发送，UI说明明确。不改共享日志枚举，不伪造PushLog/NotificationLog成功，不补写所有历史任务/批量delivery。旧Delivery处理仍完全按Q01，不新增attempt或回退他人claim。

## 专属依赖盘点与O06差异

离线清单`Q02-offline-inventory.json`绑定当前代码SHA及各文件digest。仓库仅发现QQ周期键`qq-production-regions-window`（5分钟）和两个Compose的可选onebot/with-onebot服务声明（占位image）；Web/worker无该服务depends_on。未发现QQ专属Python包，requests、Celery、Redis、共享通知/日志必须保留。Python onebot/qq services及总许可/旧配置保留兼容，不移除安全guard。

| O06候选差异 | 准备/发布验证 | 恢复面 |
|---|---|---|
| 取消唯一QQ Beat周期键 | 离线验证其它Beat键/路由不变；实际Beat持久schedule需按已安装scheduler核失效键，新旧worker同SHA/config，总许可false | 固定旧schedule/镜像备份；恢复代码不等于授予发送许可 |
| 两份Compose移除QQ专属可选服务声明 | compose解析且Web/worker/beat依赖完整；发布前只读确认真实OneBot容器/部署文件/镜像/卷/资源owner（当前未核） | 停前固定实际资源和恢复指令，保留镜像、登录卷与备份；不删除凭据/卷 |
| 实际OneBot停止及专属监控退出 | 由O06绑定精确container身份/服务面；确认Q01同版本切点与fresh在途处理边界后只停止该专属服务，更新仅该组件健康告警 | 不down共享栈、不用remove-orphans/purge、不删除共用镜像；失败恢复原服务且许可仍false |
| 配置/文档 | 发布包列QQ总许可false及旧QQ flags关闭、必要Web/worker/Beat重建/重启；env示例和运维文档仅回写事实，不输出token | 备份脱敏配置摘要；恢复总许可true不夹带在UI/容器恢复中 |

仓库scripts/deploy/.github扫描未发现专属OneBot主动健康探针；外部监控、实际NapCat/登录卷、gateway当前状态都unknown，不能声称已移除。O06必须实时核对，不用旧部署记录做当前证据。无迁移/无生产数据动作的推荐包仍由root与operations最终绑定；运行账本需证明真实零发送，不对外发测试消息。

## 实施前RED与验收设计（尚未执行）

1. false下Admin列表/详情无发送链接、旧PUSH_READY action不在菜单，伪造直接action POST不改article状态/不dispatch；网页发布/翻译动作继续存在。先在现有fixture跑真实RED，再实现。
2. 停用QQ窗口无重跑/发送预览，历史详情清楚标停用；GET/POST旧链接零网络/入队/claim/计数，publish窗口不受影响。
3. 地区页面历史QQ计数仍可追溯，明确停用而非等待运营重试；公开新闻/赛事/马匹无QQ CTA，已有筛选和展示不变。
4. 五旧注册task均可消费；mock外部服务，返回/执行日志固定终止原因，不触发重试或URL探测；对已有日志入口不重复插入。保持Q01三项PG两连接/own-claim/SENT保护，按实际变更再申请短窗口，不复用旧收据冒称新实现通过。
5. 通知EMAIL与warning去重、TaskExecutionLog/OperationLog/NotificationLog及历史PushLog/QQ数据维持；不新增迁移，不删除共享依赖。
6. 离线解析Compose/Beat，确认无QQ专属周期但其它键与路由未变化，Web/worker无需OneBot也可导入运行；旧task名仍注册，零真实网络。
7. boolTrue兼容fixture与false停用两状态验证；true不作为本任务真实网络/恢复授权。按最终diff生成formal策略，未知映射fail closed，不缩full分母。

现有归属：stable.tests_legacy（QQ/Admin/window）、stable.test_multiregion_rollout_change（共享区域通知）、既有部署环境contract/Compose测试。实施时先定位准确现有类和label，不虚构本阶段执行集合。仅方案文档可用JSON解析、引用/digest核对与diffcheck；不对尚未改的行为编造RED/GREEN。

## 准备与交接

(application) 测试：最小UI/action/历史终止原因RED → UI适配实现 → 网页/共享日志回归。
(integration) 测试：旧任务兼容/记录合同 → 补缺失QQ终止原因 → Q01保护回归。
(operations) 测试：Compose/Beat离线合同 → 按owner整合专属声明退出 → O06固定资源发布/回滚验证。

本阶段未实现、未测试行为、未改变生产。清单是离线建议，非可apply生产manifest；未知资源由O06只读补齐后形成固定包。原R确认本方案后再实施，root负责与共享文件owners排队、actualfull及交付；本线不自标Q02完成。
