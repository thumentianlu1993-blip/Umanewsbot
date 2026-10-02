# 测试计划与执行设计

状态：方案已获用户批准，实施中；代码已创建，默认策略、strict检查和定时运行尚未激活。

## 1. 一次迭代怎样流转

开发者修改代码 → 解析固定 base/head 和实际受测 tree → 列出新增/修改/删除/改名路径
→ 匹配领域与跨领域依赖 → 加核心检查 → 输出可读理由及精确测试 ID
→ 按类分批执行 → 聚合核验完整性与真实退出状态 → 生成简短报告。

选测失败在执行前结束；不能退回 `manage.py test stable`。运行失败也不能通过自动扩大或重跑
把先前失败隐藏掉。测试基础设施错误与业务断言失败分开报告。

拟新增：

- `tools/test_impact/rules.json`：路径/少量顶层符号到领域的映射、领域依赖、风险及运行配置。
- `tools/test_impact/catalog.json`：领域到测试模块/类，核心冒烟、专用发布合同及预期 skip 配置。
- `scripts/plan_affected_tests.py`：生成计划，不运行测试、不建数据库。
- `scripts/run_test_plan.py` / `scripts/verify_test_plan.py`：执行和聚合。
- `scripts/verify_delivery_test_evidence.py`：在候选工作树外从固定受信 base 执行的交付核验器。
- `.github/workflows/affected_tests.yml`：普通 PR 的统一入口及最终 `test-plan-gate`。
- `.github/workflows/full_regression.yml`：显式高风险/定时/手动的全量配置入口。

复用已有有界 runner 的隔离、收集、失败传播和证据校验实现；提取共用模块时保留
`run_bounded_stable_tests.py --group/--batch` 的原 50 项映射合同，不把它悄悄改成另一种语义。
当前已进入实现阶段，保留原有界入口语义。

## 2. 判断影响范围

### 固定 Git 输入

CI 使用 PR 的精确 base/head，并解析对应合成合并提交，记录 `base_sha/head_sha/test_sha/test_tree`。
对实际受测合并树相对 base 的差异选测；执行代码与计划必须来自同一受测树。
冲突、无法拉取 ref、空/非法 SHA、路径越界、符号链接逃逸均失败，不能按空 diff 放行。
基线前移后旧证据过期：交付核验器在 integration lock 内重新读取远端 main、PR head 和合并树，
发现不同就返回 `STALE_BASE`，不执行 merge。代理在所属干净分支整合最新 main 后 push，
触发 synchronize 重新选测；冲突按既有流程解决，绝不修改共享 main。只重跑新计划要求的范围。
未来启用默认策略时同时要求服务端 strict required checks（分支必须最新，含管理员约束），
由 GitHub 在实际合并时挡住“本地刚核验完，main 又前移”的竞态；交付工具使用精确 head 匹配且禁止 admin bypass。
当前只读查询 rules/branches/main 返回 []，不据此宣称传统 branch protection 也一定不存在；
实施时须查询两种配置并验证实际生效。若不能建立严格检查，则保持新策略诊断模式，不宣称自动交付已就绪。
这是自动技术检查，不新设人工门禁；配置变化仍按根 AGENTS.md 的既有交付流程处理。
合并 commit 与受测 commit 不同时，只有完整 Git tree 相同且其余证据身份一致才允许使用原结果，明确记录关联。

本地默认比较 merge-base 与工作区，包含 staged、unstaged、untracked、删除/改名的旧新路径。
未提交内容写入内容摘要，本地结果只标 local，不冒充 Linux CI 交付证据。
PR 删除测试时仍按旧测试所属领域选回归，并在报告列出删除 ID；不能靠删测试得到零选集。

### 规则不是同名文件猜测

映射以业务领域为单位，显式列下游依赖。例如来源解析 → 名单/结果规范化 → 持久化 → 公开判定，
改变解析器时会联动后几层，不能只选 parser 单测。模板必须同时映射对应 view 和字段展示测试。
每个领域有受审入口、类清单和负责人责任说明；非测试业务路径没有匹配时产生 `unmapped`。
纯文档白名单只包含说明文件，不把 JSON/SQL、策略、测试夹具、源码包里的 Markdown 一律当纯说明。

初期需登记当前 216 个测试文件及项目外部离线测试，建立全部生产路径的分类覆盖检查；
可暂标高风险或未映射，不能凭空给“低风险”标签。选测准入至少覆盖马匹页面/资料、新闻翻译、
赛事来源解析/结果公开、历史批次四类常见改动，全部用真实近期 diff 作不执行测试的回放。

`views.py/tasks.py` 等大文件按顶层函数进行 AST 前后比较仅用于受审的精细映射：函数体、装饰器、
参数默认值均计入；辅助函数映射到所有调用领域。新增/删除/改名或解析失败必须得到明确领域或报缺口。
顶层 import/常量/模块初始化变化不得因函数体不变而忽略，扩大到整文件已登记领域。
`models.py`、迁移、全局 settings/URL 装载、依赖清单与锁文件直接高风险，首版不做精细豁免。

### 对规则本身的修改

普通 PR 内先从固定 base 取校验器，候选规则也做结构与覆盖校验；旧、新规则要求的领域取并集。
但这只是早期反馈：候选能够修改 workflow，因此同名绿色 job 本身不构成独立可信证明。

最终由**候选工作树之外的交付核验器**保证验证步骤执行：协调者从刚核验的固定 main/base 提取
`verify_delivery_test_evidence.py` 到隔离临时目录，用 `python -I` 运行，不导入候选模块；只读解析 JSON 和 Git 对象。
该工具重新生成受信计划，查询 GitHub 实际 run/attempt/job/步骤状态，检查实际运行的 workflow blob SHA、
runner 摘要、执行集及收尾结果，输出绑定 base/head/tree 的 delivery receipt；缺少收据则协调者不调用 merge。
候选只删校验步骤、伪造同名成功 job、上传另一 run 的 artifact，都会因 workflow/步骤/选集身份不符被拒绝。

允许的 workflow/runner 身份默认来自 base。选测工具、规则、catalog、CI 配置变化属于高风险，
还须匹配独立审核绑定的准确新 blob/内容指纹，由交付协调者提供，不能从 PR 自报的 artifact 读取允许名单。
这复用既有独立审核，不增加人工门禁。首个引导 PR 的核验器也从独立审核锁定的准确对象提取，
由协调者在候选目录外执行并记录来源，不将“base 尚无工具”当作通过。

使用 pull_request 只读 token，无生产 secrets；不使用 pull_request_target 执行候选代码。
信任边界明确：本方案保护遵循交付工具的仓库开发流程、防止误配/陈旧或伪造普通CI结果；
不声称 GitHub 一个同名 check 能防住有仓库管理权限的人主动绕过工具或修改保护设置。
新策略生效必须同时验证协调者入口与 strict 检查，单独部署一个 workflow 不算完成。

## 3. 核心检查、分组及专用环境

核心冒烟拟从现有测试选取：应用装载/健康、匿名公开边界、新闻公开可见性、马匹详情字段、
赛果公开判定、Celery 路由与幂等保护。不是每类随便留一个 happy path；精确 ID 及所保护的行为
在实施时纳入 catalog 审核，目标不超过 60 项、测试执行约 30 秒，不能为了数字删安全检查。
纯说明文档只做引用/格式/工作流约定检查，不运行业务冒烟或建立 PG。

运行配置分为纯 Python、Django PostgreSQL16、发布/恢复 PostgreSQL16 专用配置。
有事务/锁/并发的检查必须使用真实隔离 PG，不能改 SQLite 来提速。

**具体隔离机制**：依赖安装/下载先在准备阶段完成，形成记录 digest 的 CI 测试镜像；测试阶段用
`docker run --network none --cap-drop ALL --security-opt no-new-privileges` 运行非 root 进程，
不挂载 Docker socket、SSH agent、生产路径、云凭据或宿主网络。容器仅有 loopback；PG16 的 server/client
预装在同一测试容器中，合成 PG 进程只监听 127.0.0.1，按 profile 创建 bounded_ci/release_0078_ci。
各分片是不同容器/数据目录；纯Python配置不启动PG。当前采用单个CI执行job内最多4个容器并行，各自独立限时及报告，避免重复下载镜像。必要时增加只允许指定loopback端口的进程级检查，
但它只是辅助，真实出站隔离由网络命名空间保证。

因此独立 Python、curl、pg_dump 和管理命令子进程仍位于同一无出站网络的容器内。
现有发布入口测试使用 fake Docker/Compose，真实恢复用 PG 子进程；不需要把宿主 Docker socket 交给用例。
用例若尝试起真实子容器，应因无daemon/socket/权限而失败；若未来出现必须用真实多容器的测试，
另定义受审专用 profile，不能退回宿主网络。验证包括外部命令/独立进程出站失败、容器启动拒绝及合成 PG 可用。

同时禁 dotenv、清理环境，memory broker/cache/邮件，固定时间与测试配置。GitHub artifact 上传在用例容器退出后
由宿主执行，只上传结果，不赋予用例网络。镜像构建/依赖缓存与“测试通过”证据分开。
本地能使用相同隔离镜像才运行该回归入口；Docker/PG镜像不可用时明确报告，允许只做静态/计划检查，
转由 Linux CI 执行权威回归，不自动回退到可能读取生产配置的本机环境。

按测试类分批，保留 setUpClass/tearDownClass 与类内约束，单批最多 200 项，最多 4 批并发。
普通计划目标 ≤400；超过则明确标记 expanded，显示原因和预计批次，不截断、不自动命名为 full。
单类展开后超过 200，报告分组设计缺口，由实施拆类或定义受审专用组；不能自动拆散有共享状态的类。
首版先按真实收集数量分配，后续积累时长再均衡，不把“并行”误称为“少跑了测试”。

`stable.tests` 重导出 `tests_legacy`：catalog 使用 canonical 测试 ID，别名展开后去重需有记录，
重复目录装载不得暗中漏测；原始人为重复 label 仍拒绝。新增测试必须参与收集，固定 manifest 漂移就失败。
同一 ID 的不同环境只有明确注册的环境验证才允许重复；不能把重复当新增覆盖。
发布合同 49+18 项由专用配置拥有，进入全量时从普通 stable 分片移出，避免既 skip 又重复执行。
纯离线 research/P0 合同也注册进 catalog；现有手动 `full_network` 抓取流程不迁入自动测试。

## 4. CI、全量与停止规则

普通 PR 工作流不使用顶层 paths 过滤，确保任何 PR 都产生明确的 `test-plan-gate`：文档 PR 也执行
轻检查并报告通过，避免必须检查永远 pending。门禁聚合使用 always()，只接受计划所需 job 全部成功；
取消、漏 artifact、缺片、错 test tree、意外 skip、teardown 错误、超时均失败。
同 PR 新提交取消旧测试任务；只取消隔离自动测试，不取消生产发布或现有手动真实抓取工作流。
每批容器独立 PG 与临时目录，单批 timeout 10 分钟（专用恢复合同保留现有上限），失败保留证据。

PR 分类为 high-risk 时直接调用相同 full profile；纯局部改动不能因“未命中缓存”或“准备上线”自动 full。
全量调度建议北京时间每天 03:30 检查 main；main 自上次成功完整运行后发生变化则执行，无变更每周至少一次，
以发现时间相关漂移。任一失败后不得因 SHA 未变化跳过下一次计划运行。手动输入仅允许具体 SHA 和理由。
这只是建议配置，本轮不创建自动化或触发全量。

取消默认 baseline+candidate 双全量：候选必须自己通过，旧失败不是放行理由。
如需判断失败是否原有，只重放失败 case/class 的固定 base，诊断结果不改变候选失败状态。
首版不复用跨提交成功结果；缓存 pip 下载不等于复用“测试通过”。同一受验树已获得所需 Linux 证据时，
上线只核验其仍有效并做发布检查，不让本地再重复一次全量。

全量发现遗漏后：保持失败状态与失败 ID，相关领域暂停精细选测，扩大为完整领域；无法定位才升级 full。
修复缺陷同时补对应表和“原 diff 必须选到该测试”的回归。没有自动 quarantine/xfail/永久排除。
预期 skip 必须在 catalog 按配置列具体 ID、原因及复核期限；新增、过期或原因不符的 skip 拒绝。
可在专用环境执行的 PG/性能测试分配到对应 profile，不因默认 flag 关闭就当全部通过。

TDD 说明和 codex_workflow 明确：最小 RED → 同例 GREEN → 影响计划要求的回归 → 停止。
只有新增改动/失败/映射缺口/明示风险才扩大。所有工具输出“为何选择”，不把测试范围变成新的人工门禁。

## 5. 上线前检查与证据

PR 默认仅在 deploy、Compose、Dockerfile、迁移、settings、依赖、恢复服务/命令及其夹具变化时跑发布合同。
普通应用发布仍要求：该受测树上的 0079 必要合同、check、迁移计划/配置校验和业务回归证据。
如果 PR 未运行所需发布合同，则上线准备只补该专用组（现状 67 项，后续随代码更新），不补 stable 全量。
真实发布仍走现有 coordinator、备份、队列排空、版本/页面验收，不改变任何生产门禁。

证据至少含 base/head/test SHA 与 tree、规则/catalog/runner/依赖摘要、Python/Django/PG/OS 实际版本、
配置 profile、选中理由、精确选集、实际执行集、预期/实际 skip、失败、各批退出状态与收尾状态。
聚合器从受信计划核验，而非仅信任候选写出的 passed=true；artifact 绑定 run ID/attempt/提交与 job 状态。
发生环境/计划漂移则重跑相应范围；不得拿另一个 SHA 的旧绿灯拼出本次成功。

默认日志只输出范围、计数、耗时和最多 10 个失败摘要，完整堆栈存 artifact；同一根因聚合显示但保留全部 ID。
报告区分 docs-only/targeted/expanded/full，不能把 targeted 写成“全部测试通过”。

## 6. 性能与实现边界

验收观察普通 PR P50/P95、测试条数、准备时间、实际测试时间、总 runner-minutes、失败首次定位时间。
目标：文档无需 PG；普通计划 ≤400 项且 P95≤8分钟；全量不再每 PR 双跑；日志摘要有固定上限。
不能用过滤失败、降低断言或把测试换成 mock 调用次数达标。若准备耗时占主导，再优化依赖/容器准备，
不先重写整个测试框架。无业务模型/迁移、无真实 Celery worker/生产队列变化。


## 7. 三份旧工作流的迁移表

| 现有工作流 | 新 PR 唯一归属 | 保留的手动语义 | 切换动作 |
|---|---|---|---|
| release_0078_contract.yml | release profile拥有49+18合同；affected_tests拥有普通回归；full_regression拥有全量 | 保留精确SHA/理由的手动入口，known-failures仍可复核历史50项；旧full入口显式标明full，不默认供普通PR使用 | 新gate验证后移除本文件pull_request触发；不再默认baseline/candidate两套全量 |
| p0_participant_contract.yml | catalog的p0_bridge拥有compiler、execution ledger、adapter合同一次 | 现状没有手动入口，无需增设 | 将执行定义提成可复用离线脚本/profile，移除旧pull_request触发；不能留下第二个自动job |
| research_graded_race_participants.yml | research_contracts拥有剩余离线单测、workflow合同和synthetic安全停止/续跑/fan-in/finalize smoke；共享P0编译器/账本转p0_bridge | 保留workflow_dispatch输入验证、tests前置job、official_results/races依赖tests、profiles→merge→finalize及completion_bundle依赖；checkpoint与cancel-in-progress=false保持 | PR切换后移除此文件pull_request；手动tests调用相同离线脚本，网络stages条件不变，不与PR同事件双跑 |

catalog为每个canonical测试ID和synthetic场景标唯一owner，普通PR同一场景只能执行一次；不同场景的
smoke启动与续跑不是可随意删掉的重复。手动研究运行仍必须先通过输入校验和全部原有离线前置检查，
不能因PR已经测过就跳过它；这属于另一次有明确输入的手动任务。
切换静态合同检查所有workflow触发器、needs链和共享清单，防止遗漏旧入口。

设计依据：[GitHub严格状态检查](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)、
[Docker none 网络](https://docs.docker.com/engine/network/drivers/none/)。这些说明支撑机制选择，不代表仓库已经配置。


## 实现审查后的细化

- 交付时保存并取回同run的测试镜像，由候选外的受信runner/worker/entrypoint独立重收集，再比较精确分片和ID；不建立需要每次新增测试都改动的全站ID清单。
- 分片只允许回传自身唯一结果文件，不能覆盖收集计划。超时后明确删除容器，不只终止Docker客户端。
- full调度使用成功artifact内真正受测SHA，不能使用触发workflow的ref代替手动输入。
- PostgreSQL16明确UTF-8；历史性能合同明确开启合成环境性能flag；research离线profile包含其已有脚本导入路径。
- 完整catalog收集可以单独进行，输出“只收集，未执行”；与运行全部测试分开报告。

- 纯文档使用精确base提取的候选外只读checker，保留原有门禁唯一性等全部合同，候选Python测试只在隔离容器执行。
- 首次manual引导须base尚无工具、独立审核绑定exact head、实际步骤/控制文件匹配，且受测完整tree等于实时合并tree；其后不适用此例外。
- 显式release/toolchain不要求差异非空；普通affected空差异仍拒绝。删除测试记录旧模块及其声明ID，继承展开不冒充静态声明清单。
- 非root及无真实缓存/daemon导致的10项既有skip按精确ID和原因登记至2026-10-16，报告单列覆盖缺口；不放宽其他skip。
