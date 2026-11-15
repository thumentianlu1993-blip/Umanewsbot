# 集成方案

从最新origin/main建立独立codex/p01-main-integration-20261114分支，旧PR314及原分支保留。
三方应用P01范围增量，不整体merge旧栈；冲突逐处保留main新配置和关注列表实现，仅插入P01受控分支。
旧0083/0084/0085 P01迁移未曾发布，重编号0086/0087/0088，挂接主线0085_merge_us_divisions。
保留已上线France字段与美国分场迁移，不引入原分支未上线的horse_article_pair_receipt_index依赖。

默认P01 mode=off、index/feed/dispatch=false保持；已有模型预算、QQ许可和赛事抓取权限不改变。
发布需新增表、nullable外键与索引、P01表不可变证据trigger；无历史业务回填。
生产迁移/备份/恢复及服务切换必须在完整Compose链和单一发布锁内，精确动作在rollout.md冻结。
本轮集成发生迁移范围变化，最终发布包按根AGENTS.md核对授权；不得把旧无迁移PR说明当本包说明。

旧镜像写入探针实际发现新增news_generation仅有Python默认会使旧ORM插入违反NOT NULL。
已为该列增加数据库默认0；新FK仍nullable。关闭态下旧镜像可前向兼容新schema，不逆迁移/drop新表。
若后续已接管P01任务，则不再直接恢复不理解active_news_run的旧镜像，按P01既有暂停及前向修复流程。
