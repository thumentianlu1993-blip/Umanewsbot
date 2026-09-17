# 代码审核与修复记录

本需求由主线程编写测试、实现与修复；固定只读 reviewer `race_code_reviewer` 六轮审核：核心代码两轮，补充的两条身份修复入口两轮，浏览器发现的详情状态遗漏一轮，全量结果相关测试合同一轮。
方案仍绑定 PLAN.md 的批准 SHA，不改写历史计划的“未实施”时间点叙述。

## 第一轮 REVISE

1. P1：真实 JRA Shift_JIS 页面不能按 UTF-8 解码。增加限定编码解析与原始字节 SHA，13 行官方表形状 fixture 贯通 HTTP、共享缓存、候选及展示。
2. P1：截断到完整第一行的响应会覆盖名单。增加 html/body/table/tbody/tr 完整闭合检查，保留合法人数减少能力。
3. P1：JRA 展示绕过字段范围。生成可展示标记与公开读取都要求 horse_name 准入，可选列逐字段过滤。
4. P2：成功官方 URL 未复用。有效 claim 提交事务保存 URL 与身份基线；改期、赛事身份变化使绑定失效。
5. P2：NAR 被送入 JRA。选择及领取只覆盖十个中央马场，地方赛事零请求。
6. P2：网络耗时跨分钟导致小时盘点跳过。开始网络前冻结本轮是否需要盘点；17 分启动、20 分返回仍纳管。
7. P2：关闭时收集的相同内容永久不能展示。重新开启后的新一次成功核验可创建可展示版本；开启本身不发布旧候选。

六项专项 RED 得到 5 failures、1 error；盘点原测试增加跨分钟网络模拟。修复后定向 257 例 SQLite 通过（跳过 1 个 PG 行锁专属测试）、PG16 全部通过，禁止外部网络。

首轮完整 Git 指纹受到并行全量测试未跟踪 runtime 生成物变化影响，未声称全树稳定；对首轮指纹中的非 runtime 1236 个 blob 逐个复核，无改变。

## 第二轮 APPROVED

同一 reviewer 复核原七项与直接修改路径，无新增 actionable 问题。另用未裁剪官方缓存验证新版完整性规则仍解析 13 行。

审核前后指纹一致：`a82f2901965aedb9814d2f9a15041f1ec6ffc076206d5504ecef6e1c5a57a1f6`。
指纹只通过临时 Git excludes 排除测试产生的未跟踪 `runtime/race_data_sync_repairs/` 和 `runtime/snapshots/`；受控代码、测试、配置与 fixture 仍计入。

此为代码审核通过，不是已合并、已部署或历史数据已恢复。Linux 全量 CI 与最终发布包另见 rollout.md 和验证记录。

## 第三轮 REVISE 与第四轮 APPROVED

补充审核范围仅为 829/104 精确身份修复入口、manifest 与回归测试。第三轮要求保留已有有效别名的语言、来源等元数据，并补足真实整批回滚证明。新增两项用例先得到真实 RED；修复后只新增缺少的法语（fr）/日语（ja）别名，停用同名别名直接拒绝，不自动激活。审计只列实际新增行。

整批回滚用例明确先完成 104 写入，再因 829 基线漂移失败，断言两条事件、别名与审计全部回滚。7 项 PostgreSQL 回归通过。同一 reviewer 第四轮 APPROVED，无新增问题；审核前后指纹一致：`0c2275a927bf1f29b78597b6839c74a6e01b531c20545a6e8ceed64a2ecadbbb`。指纹沿用第二轮两处测试生成物排除规则。

该结论覆盖 SHA 绑定的两条身份修复工具，不表示生产已执行。最终 Linux CI、提交和发布边界以验证记录及 rollout.md 为准。

## 第五轮 APPROVED

浏览器渲染发现详情顶部状态与基础资料原始状态矛盾：过期 scheduled、无正式结果的 finished 仍分别显示赛前/完赛。新增一个测试覆盖两场景，先得到 1 test / 2 failures 的真实 RED；模板仅将原始 get_status_display 替换为顶部既有 status_label。修复后整个状态模块 PostgreSQL 12 例通过，浏览器复验历史详情上下两处一致，日历状态与双时区文本正常。

同一 reviewer 增量复审 APPROVED，前后冻结指纹一致：`4cd8b9f6154a0eba90f602b33495858ddf68e897c0f5d21f9e754f266a3feec2`。无新判定分支、无数据变更。

## 第六轮 APPROVED

本机全量旧候选与当前 main 对照出现 8 个新增失败 ID：3 项已由此前时间文案、正式赛果夹具及 winner 单测修复，5 项在当时 HEAD 逐项复现。剩余 5 项均来自批准 PLAN 103–114 的正式完赛语义变化：历史分页的 finished 空赛果夹具，2 个继承的暂定发布测试、暂定冠军 hero 与 policy-off 日历测试。

仅调整测试合同，不更改应用：分页补 45 条 confirmed 赛果，保留所有 filter/第二页 5 条断言；暂定明细继续验证公开，hero/日历不显示正式冠军；授权关闭明确断言 top_results 清空；official/corrected 增加冠军正向断言。先在 PostgreSQL 得到 5 tests / 5 failures，再运行相关完整模块 68 项全过。

同一 reviewer 独立确认未弱化保护且符合已批准口径，VERDICT APPROVED。前后指纹一致：`fb9f4ec67adc1ba1f0813b055a176bdd8324a8c4ead419582cb3cda6b67c2479`。最终全量 CI 仍须完成，不能把旧候选全量失败解释为最终候选结果。
