# C-003 / U01 精确影响映射建议

日期：2026-10-03（Asia/Shanghai）。此文只提出映射，不修改共享 rules/catalog。行为候选仍绑定 `3ac1e3a750e68bafe7950fa726481a02ecccfad6`；生产/交付基线保持 `907f8de699b31a6fcc80acc78e9ba070aadc4f28`。

## fail-closed 结果

正式 `plan_affected_tests.py --base 907f… --head 3ac…` 退出1，以下10个路径及两个view符号未登记。纯实现父提交5c660…到3ac…同样报告fixture与两个符号，不能通过缩base消除。没有删选集、使用full-reason绕过或改共享规则。

## 行为依赖映射

`rules.paths` 精确新增：

| 路径 | 建议既有domain | 理由 |
|---|---|---|
| `docs/changes/next-version-capabilities/lanes/C/U01-offline-cases.json` | `module:stable.test_race_information_display_pages`、`module:stable.test_race_information_display`、`module:stable.tests.test_race_field_normalization` | 第一个测试模块真实读取33案例及期望；它是行为fixture，修改可改变等价断言，不能归docs静态；后两者覆盖共享解析/展示合同 |

`rules.symbols["server/stable/views.py"]` 精确新增 `_public_race_calendar_base_queryset` 与 `_public_weekly_focus_events`，均建议以下既有domains，不新建测试模块或改变profile/dependency图：

- `module:stable.test_race_information_display_pages`：等级标签/颜色/筛选两flag及SQL/Python等价。
- `module:stable.test_race_information_display`：共享投影与来源合同。
- `module:stable.test_historical_race_calendar_integrity`：历史重点集合、公开边界、canonical及分页。
- `module:stable.test_race_calendar_default_date_window`：基础queryset参与日期窗口。
- `module:stable.test_race_calendar_responsive_ui`：公开卡片及周焦点入口。
- `module:stable.test_race_public_time`：queryset日期与周焦点时间边界。
- `module:stable.test_public_new_regions`：地区/等级交集及公开地区覆盖。
- `module:stable.test_race_news_exposure`：周焦点在首页/新闻入口的消费者回归。

保持现有core自动纳入与catalog依赖展开。更宽的service/template高风险规则仍生效，不因新增符号映射而降级。

## 静态证据路径建议（协调者最终核定）

下列九路径建议逐项加入`rules.docs`精确白名单；不得添加`docs/**/*.json`或HTML通配，避免将测试fixture、运行manifest、可执行产物误归静态。扫描scripts/server/tools/.github未见运行入口消费这九路径；当前引用为文档/调度证据。协调者应再次核用途，若新增运行消费者则转行为domain或high-risk。

| 未映射路径 | 当前内容用途及建议理由 |
|---|---|
| `docs/changes/next-version-capabilities/dispatch_state.json` | 协调执行台账，由协调者维护；本候选继承快照，不是业务服务配置 |
| `docs/changes/next-version-capabilities/inheritance.json` | 原规划文件来源与哈希，静态溯源 |
| `docs/changes/next-version-capabilities/task_index.json` | 开发任务索引，非运行规则 |
| `docs/changes/next-version-capabilities/lanes/C/F04-prototype.html` | 文档链接的合成离线原型，不含业务网络请求/提交；结构/响应式证据另做静态/浏览器检查 |
| `docs/changes/next-version-capabilities/lanes/C/F05-public-evidence.json` | 公开页面只读观察摘要，非业务fixture |
| `docs/reports/2026-10-02-capability-evidence/backlog-browser-observations.json` | 历史backlog公开观察证据 |
| `docs/reports/2026-10-02-capability-evidence/browser-observations.json` | 能力基线公开观察证据 |
| `docs/reports/2026-10-02-capability-evidence/news-design-home-observation.json` | 新闻首页单次观察，规划引用 |
| `docs/reports/2026-10-02-capability-evidence/thread-requirements.json` | 规划会话需求整理，非运行配置 |

## 仅诊断的模拟结果

只对内存副本加入以上精确映射，再调用现有`select_changes`：`mode=full`、246 domains、293 labels，未修改仓库rules/catalog。该数字是标签选择，不是准确test数量或执行收据；容器collection后才有实际数量/批次。

规则/目录变更本身依现行政策保持旧覆盖并验证新覆盖，所需full不会免除。最终由规则owner提交、原R审核，绑定受审控制SHA和候选集成SHA生成正式计划；本线按该计划收集并执行，固定RED/198输入focused结果只作诊断。
