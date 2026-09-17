# 实施验证记录

前一完整候选：`3a47a22d45b19cfc4061b2450b25f6167f56b4eb`（应用与 `939d07edccce6702bcb6c96243e073bac0e60295` 一致，后续仅修正测试合同），PR [#203](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/203)。隔离 worktree 与分支不改动用户原工作区。

## 2026-09-18 最终候选验收

最终代码与测试提交为 `d0bb40fb8defe3e9de1029aa255edd2e06e1e0c6`，[完整 CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/35242927242) 的三个测试作业已完成并上传构件。候选 5,012 tests / 16 failures / 29 errors / 20 skipped，耗时 2002.034s，45 个不同失败 ID 与当前主线同应用 Linux 参考完全相同；相对本轮固定历史基线也无新增失败。此前旧文案断言已消失。不是全套全绿，未删除或忽略原有 45 项失败。

同一提交的 45 项发布合同全过（484.649s），Django check 正常、迁移无变化，前后指纹均为 `ef832c7ac3fad1d2c6708deed7b0d77eb9d9c8b5e41643468f6514474ed74234`。完整计数、失败 ID 与原始 result.json SHA 见 [最终 CI 摘要](evidence/ci_final_summary.json)。本机逐 ID 比较已通过，GitHub 工作流整体状态以该 run 页面为准，不拿作业状态代替业务或生产验收。

此后交接提交只更新 docs，不替换已验证应用/测试 SHA。发布绑定上述 `d0bb40fb`；应用与上一候选 `3a47a22d` 完全一致，变化仅为一条已审核测试文案和文档。生产仍未合并、部署或写入。

## 测试与独立审核

- 行为回归先 RED 后实现；核心返修 7 项、身份修复返修 2 个分支，详见 test_cases.md / CODE_REVIEW.md。
- 核心与身份修复组合 PostgreSQL 16：264 tests，0 failures，0 errors，0 skipped。覆盖正式证据回退、D−4/跨日频率、租约/行锁、JRA真实编码与截断页、候选/公开门禁、TRA接管、状态/时区与两条身份修复。
- 核心 SQLite：257 tests，跳过 1 个 PostgreSQL 行锁专属测试；该用例已在 PostgreSQL 通过。
- Django check、makemigrations --check --dry-run、两份 Compose 配置解析、git diff --check 通过；无新增迁移。
- 固定只读 reviewer 第四轮后 APPROVED，725 个应用/部署/配置 blob 与第四轮审核清单完全一致。随后浏览器发现详情状态遗漏，新增 1 个两场景测试真实 RED 后作一行模板修复；模块 12 项 PostgreSQL 全过（累计 265 个不同定向用例），第五轮增量审核 APPROVED。
- 当前 main 本机全量：4,961 tests / 18 failures / 194 errors / 18 skipped；早期核心候选：4,998 / 26 / 194 / 18；新增 8 个失败 ID 已逐项归因，3 项此前修复，5 项按批准语义调整测试。后五项先独立 PG RED，再扩展完整模块 68 项 PG 全过，第六轮 APPROVED。原全量运行早于后续修正，不作为最终候选全量通过的证明。
- 所有自动测试仅使用本机/CI合成服务；socket guard 拒绝外部地址，不加载生产 .env，不访问真实业务接口。

- 本地浏览器通过真实 Django 模板渲染核验详情、历史赛事及日历：13 行未编号名单，北京/当地双时区，过期赛事上下状态一致；只使用隔离合成赛事及已缓存官方 fixture，临时浏览器和 HTTP 服务已关闭。该检查验证内容与基础布局，不代表生产自然调度或完整字体资源验收。

## CI

最终代码 CI：[35230550096](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/35230550096)。45 项发布合同已通过（505.828s），Django check 无问题、迁移无变化，Linux 测试前后指纹均为 `f7a5b08dd15c724bde02df95bf65ea2a609e2f873fc310fe80db7965c494db7b`，构件 commit 为 `3a47a22d45b19cfc4061b2450b25f6167f56b4eb`。attempt 2 已产出完整构件：5,012 tests / 17 failures / 29 errors / 20 skipped，2178.573s；46 个不同失败 ID。相对固定历史基线及当前主线同代码 Linux 参考，都仅多出一条 canonical 详情测试的旧文案断言，详见下节与 evidence/ci_summary.json。不能将此构件称为全量通过。

另已重新下载 [当前主线应用版本的 Linux 构件](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34463096933)：`9a88243f`，4,961 tests / 16 failures / 29 errors / 20 skipped，共 45 个不同失败 ID。`git diff 9a88243f 45da57b6 -- server deploy scripts .github requirements.txt` 为空。此构件来自 9 月 10 日，作为同代码的历史 Linux 参考，不能冒充今日同环境重跑；已逐 ID 比较，两份对照均仅多出上述一条旧文案断言；原有 45 个失败全部保持。

工作流的固定历史基线为 `a88bcbf669bd609e30f97c8a07f009881d2da705`，不是当前 main。另在本机相同隔离 PostgreSQL 环境比较当前 main `45da57b618469a7b788753db8584d3b5ada6c56f` 与核心候选，平台相关旧失败单独保留，不冒充 Linux 全量通过。

## 最终候选第一次运行超时

同一 run 的 attempt 1 候选在 60 分钟上限被取消，仅上传部分 stable.log，没有 result.json，自动比较因缺少候选完整结果失败。这不是全量通过，也不能据此推定新增失败数量。成功的基线与 45 项发布合同保留，仅重跑同一候选作业（attempt 2），没有更改代码、删减测试或提高超时上限。

按已收集的 5,012 个测试顺序及最后固定输出锚点，部分日志约推进至第 4,956 项前后；该推断不等于已定位某条用例卡死。相邻历史打包用例单独重放 0.640s 通过，相关文件未被本 PR 修改。attempt 2 的完整测试于 15:38 UTC 上传，耗时 2178.573s，未再次超时。作业汇总/比较仍在运行时，已直接按最新 artifact ID 10505258133 下载并校验 commit 与完整 result.json；未依赖工作流总状态猜测测试完成。

## 首轮 Linux 全量诊断

`9d51281d` 的 [首轮 CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/35227711594) 实际运行 5,004 项，21 failures / 29 errors / 20 skipped。相对当前主线同代码的 Linux 参考，恰好多出上述已复现并修正的 5 个测试 ID；其余 45 个失败 ID 完全相同，没有额外平台特有差异。最终应用相同的 `3a47a22d` 完整结果见上节，不能用首轮结果替代。

## 最后一条旧状态文案断言修正

完整 Linux 构件唯一新增失败为 `RaceResultRecoveryPublicPageTests.test_finished_filter_shows_recovered_canonical_and_confirmed_winner`：详情基础资料已统一使用“已完赛”，旧测试仍要求模型原始文案“已结束”。正式 winner、日历去重和 finished 筛选在失败前均已通过，响应也确有正确冠军。

本地先复现 1 test / 1 failure 的真实 RED，仅把该断言文字改为“已完赛”；整个 canonical 页面与状态模块 PostgreSQL 16 共 19 项全部通过，无跳过。冠军、去重、权限及取消/延期保护均保留，应用文件与 `3a47a22d` 无差异。后续测试/文档提交不替换已冻结应用版本；PR 同 HEAD 的最新完整 CI 作为最终测试提交验收，不能把这 19 项定向通过改写为此前全量只有 45 个失败。

## 生产边界

2026-09-17 只读现场仍为 `9a88243f`。本次没有合并、部署、开启 JRA、回补正式赛果或执行生产身份修复。历史 79 场只冻结为缺口清单，结果补齐为 0。两条精确身份 manifest 与其他证据的 SHA 已逐文件复核一致；PLAN 批准 SHA 保持不变。发布与数据动作严格使用 rollout.md 的精确范围。
