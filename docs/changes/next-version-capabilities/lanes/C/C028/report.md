# C028 首批隔离集成与测试登记

任务 C028-FIRST-RESULT-INTEGRATION-PREP-001，2026-10-06（Asia/Shanghai）。范围为 ROOT 指定的已审首片及共享 catalog/impact 最小登记。完成本地 assembly 与静态验证，尚未进行集成独立 review、正式容器收集/执行、push、PR、合并或发布。根 `AGENTS.md` 是唯一门禁来源，本任务不等于 G2。

## 基线、来源与文件边界

实时 `git ls-remote origin refs/heads/main` 确认 `6e6aded22764ebee3d6a97f2834f47d4b4baa7bb`。从该 SHA 新建独立 worktree `/Users/mentianlu/.codex/worktrees/c028-first-result-integration/umanews`、分支 `codex/c028-first-result-integration-prep`。C027 演示树和进程未改动，记录时原 PID 49107 / 127.0.0.1:8767 仍运行。

以下审核状态来自 ROOT 明确交接，C 未自行签发批准。使用 `cherry-pick -x` 记录来源；只迁入确切变更，无 ROOT 协调历史。

| 来源 | 输入提交 | 集成提交 | 内容 |
| --- | --- | --- | --- |
| A028，原 R 已审 | `bd843f8c4320b63984a6db4cf52f8532dcbbf27a` | `f64cce1b` | H02 纯离线缓存分类、16 测试、A 报告 |
| A029，已审 plan-only | `2e7b78559f4ebf74f524763d1b3f61ad4a1c03ba` | `703c0661` | 仅计划文档，不宣称实现 |
| A030，APPROVED_LOCAL_OFFLINE_ADAPTER | `87515c372ad43b8a731de05f4ccf3650b107e30c` | `05948bd3` | 绑定 HKJC 字节适配、18 测试、A 报告 |
| C027，原 R 23b8dcfb APPROVED | `1c105f4b` → `43860979` → `23eae7f53360c986303bc46685f191764c70af1b` | `3f8c30e9` → `59b00878` → `49a3cbb4` | 演示、SQLite 冷连接一行修复、1 测试、C 报告 |
| B035 + R01 CLOSED，APPROVED_LOCAL_CODE | `57b72b4ca8f8cfd5feeb79926848b99963785403` → `4bdeb6101f604dbdf06f48a8ce8ac97b38b7b55c` | `deb4e639` → `57a84e1a` | 正文清洗证据、script/style 摘要防泄漏、12 测试、fixture 与报告示例 |

来源 assembly 固定 `57a84e1a90b157475534a047cf49814066bc6b90`。21 个来源文件逐一与 A030 最终树、C027 最终树和 B035 返修树对应 Git blob 相等，跨线无路径重叠、无冲突；B035 与 R01 在自身文件上的叠加属于明确获准修复。A030 祖先 A028/A029 各迁入一次，无重复。

只修改本新集成树：上述确切源文件、`tools/test_impact/catalog.json`、`tools/test_impact/rules.json` 及本 C 报告。后台与 QQ 继续暂缓；主线已合并 QQ 代码保持。本次没有生产查询、旧包修复、抓取、付费调用、消息发送或自动发布。

## 最小 catalog/impact 登记

登记前在固定 assembly 上运行真实 Git 计划，实际失败于四个新增模块 `catalog drift`；独立 selector 列出十个未映射路径。原规则未被 full 或已有高风险路径掩盖。

登记提交 `434a63ccd08a55cf72c1053d0920a9a2ca1e3815`：

| 模块 | 实际发现 / AST 方法数 | profile | domain |
| --- | --- | --- | --- |
| `stable.test_horse_cache_reuse` | 16 | python | horse_cache_reuse |
| `stable.test_horse_source_cache_reuse_adapter` | 18 | django | horse_cache_reuse |
| `stable.test_c027_public_time_sqlite` | 1 | python | module:stable.test_race_public_time |
| `stable.test_article_content_trace` | 12 | django | news_translation |

四模块由现有 unittest loader 在专用最小 Django / dummy DB/cache、禁止 dotenv 与 socket 的新进程中只收集，47 个唯一 canonical ID 与 AST 方法集合完全相等；业务测试执行数为零。C027 是独立 SQLite wrapper 的 unittest.TestCase，不访问项目数据库；正式 worker 的 python profile 仍按既有 setup 初始化 Django。两个 SimpleTestCase 使用 django profile，保留数据库禁止行为，不改执行器。

新增 H02 domain 的依赖为现有 `horse_target_inventory` 与 `module:stable.test_p0_horse_completion_source_clients`，覆盖实际引用的 H01 helper 和 strict validator；两个新服务精确映射至该 domain。C027 加入既有公开时间 domain；B035 加入 news_translation。B035 报告 examples.json 精确映射 news_translation，不扩大 docs 白名单。

C027 两个演示启动/浏览器脚本、B035 行为 baseline fixture 精确列为 high_risk；没有放宽生产服务原有风险级别。四个新 tests/profile 已登记，保留 core 与依赖展开。未知邻接服务、演示脚本、fixture 仍抛 unmapped。

八个计划/执行/收集/证据验证/工作流控制文件逐字等于 main；docs 白名单、AST symbol 映射、module_initialization_full、allowed_skips、dedicated_batch_modules 不变，旧 domain 标签、依赖、test、profile、owner 覆盖全部保留。未改阈值、白名单或正式准入算法。

## 静态验证与精确计划

- JSON parse、现有 validate_catalog、来源 Python AST、source blob 对齐、控制不变、覆盖保留与未知邻居拒绝：PASS。
- `python3 -m unittest scripts.tests.test_test_impact scripts.tests.test_impact_evolution`：34 tests / 6.071s / OK。仅映射技术合同，不是业务 CI。
- `git diff --check`：PASS。
- 固定登记候选计划：base=6e6，head=test=434a63cc，tree=`07ac6ce934b3ccce17ceb0d5ddadd363d621b108`，mode=full，261 domains / 314 labels。计划 digest=`d6a6a1cb9654b360c3fd75df30f892f670b86f112c81edab2e722d1b44b21b0b`。
- rules semantic digest=`bffa9ca8214d5534dd2f1959560778566b40d85ae4bdd2ee7a7044c6bcf8fe3a`；catalog semantic digest=`5b7f9c3280980118e7efb1b145734bdb00239af566d42ba4df74cd5fcda0c1ef`。

full 是现行 catalog/rules 演进及高风险路径的正确结果，不缩选、不覆盖 mode、不将 47 个新用例冒充整个集成验收。314 labels 不是测试数；实际数量、去重与分片由官方容器 collector 决定。本文提交后重新生成绑定最终 HEAD 的 Git 计划，精确 SHA/tree/digest 在同一 runtime 最终计划和 ROOT 交接中提供，避免文档自引用。

证据目录 `/Users/mentianlu/.codex/runtime/c028-first-result-integration-prep-001`：

| 文件 | 性质 |
| --- | --- |
| `plan-unregistered.log` | 固定 assembly 的真实 catalog drift |
| `mapping-before.txt` | 固定 assembly 的十路径 unmapped |
| `new-tests-collection.json` | 47 native canonical ID 及 profile；diagnostic_only，执行数 0 |
| `static-contracts.json` | 21 source blob、八控制、覆盖和邻居合同 |
| `mapping-contract-tests.txt` | 实际工具输出摘录，明确其来源和技术合同性质 |
| `assembly-plan.json` | 固定登记提交 Git 计划 |
| `final-plan.json` | 本文提交后固定最终候选 Git 计划 |
| `local-diagnostic-plan.json` | 工作区诊断，非正式计划，不用于交付 |

## 正式收集预算与待办

ROOT 安排原 R 对最终 assembly + mapping 独立复审。下一阶段建议只执行官方 `scripts/run_test_plan.py --collect-only`，精确绑定最终 SHA/tree/plan 和经核验镜像 ID：

- 一个容器，network none、non-root、cap-drop ALL、no-new-privileges、只读 source/control。
- 现行固定预算：4 GiB memory、2 CPU、pids 256、3 GiB tmpfs；collector 单次硬超时 600 秒。优先复用 ROOT 核验的现有镜像，本任务未请求或执行新构建。
- collector 输出完整 canonical 集合、别名、profile 和真实分片数后，再向 ROOT 给正式执行预算；每批 ≤200、最多四容器，普通 profile 600 秒、release-postgres 2100 秒保持现有合同，实际并发由 ROOT 分配。
- 本次不跑旧全套，不启动 Docker/PG，不以 native collection 或历史 A/B/C 窄测代替正式收据。旧 metadata manifest 若因输出变化漂移，仍 fail closed，不顺带改旧包。

最终 Git 计划 head=test 为本地候选，属于精确快照的准备证据，不是 PR 合成 merge 交付收据；后续真实 PR 应绑定实时 base/head/merge 并由候选外验证器检查。审批/合并/发布仍由 ROOT 按根 AGENTS.md 推进。额度最近剩余 92%；既有额度停止规则继续，未创建新会话或 subagent。
