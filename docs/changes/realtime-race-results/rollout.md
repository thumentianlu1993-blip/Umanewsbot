# 准实时赛事赛果 rollout

## 当前状态与边界

本专项 worktree：`/Users/mentianlu/.codex/worktrees/97f5/umanews`。

2026-07-16 已执行 `git fetch origin main`，确认：

- 初始 PLAN 基线：`9b6177026053f5174dfd768fbdf5ad4d57eb99a1`。
- 进入测试先行前重新核对并安全快进至 `8dd935e3`；离线 TDD 期间继续安全快进，当前 `HEAD == origin/main == 283bacf2cdc5ff97423b50ff46cfda2a87120a2b`。
- 快进过程先 stash 本专项文档，恢复时只在 `docs/current_state.md`、`docs/project_status.md` 发生同日顶部记录冲突；已同时保留上游历史事实和本专项状态，未读取或复用历史 runtime 产物。
- 专项分支：`codex/realtime-race-results-plan`

当前变更范围为本 change 的五份文档、状态/决策/部署文档、准实时测试与服务、模型和前向 migrations `0033` 至 `0041`；TRA provisional publication 新口径还将新增 publication admission/authority/marker/incident 的后续 migration，编号从实现时 latest main 向前分配。没有读取或复用历史抓取会话的 runtime artifact；仅使用隔离 SQLite/PostgreSQL/Redis 测试和受控来源 proof，没有启动生产 crawler、生产连接或订阅购买。

2026-07-17 发布审核前实现状态：前向 migrations 已延伸至 `0045`；TRA Free 单 event results runner、唯一 provisional admission、公开读取门、官方复核 incident 创建、只读后台和容器 secret 隔离已 GREEN，registry digest 为 `1d801e95b2770c741503a75dbcba93aca407a6cd681f3471813f1e7d5586fa32`。当天响应多 event cache、racecard 自动身份初始化、官方 marker apply、incident 告警/长期探针和各地区官方 adapter 尚未完成；首轮可发布范围只能是经人工/manifest 预先审核 racecard 与 identity 的精确 TRA provisional allowlist，不能宣称正式赛果自动复核已上线。

执行顺序锁定：历史赛事任务先完成。latest main 已把第一期 1998–2026 正式详情分母收口为 `8032 = 6534 complete + 1491 evidence gap + 7 not_due`，global verifier `errors=0`；生产 historical runner 为空，历史网络和功能开关关闭。因此可进入业务 DB 零写入的只读来源 proof。任何 shadow、tracking 初始化或业务写入仍须先生成并审核精确 event allowlist/ownership generation、无 active runner/lease/checkpoint、source registry digest、共享 host/限速和资源窗口组成的 SHA handoff manifest。

## 阶段 0：方案与产品范围已确认（已完成）

入口：五份 artifacts 完成且只包含 plan。

动作：

1. 首次方案审核已建立持久 reviewer 会话，结论为 `REVISE`。
2. reviewer 检查真实代码复用、source terms、状态机、幂等、资源隔离、RED 清单和 rollout gates。
3. 九项 actionable findings 已修复，并在同一 reviewer 会话完成两轮限定复审，最终 `APPROVED`。
4. 用户已确认六项产品决定，并将香港范围修正为 G1-G3、日本修正为 G1-G3/JpnⅠ-Ⅲ/J-G1-3。
5. 原 reviewer 随后被运行环境回收，`list_agents` 已无法恢复；已将原九项 findings 全部关闭、最终 APPROVED 和本次唯一范围修正交接给替代 reviewer，仅复审修正及直接触及路径。
6. 替代 reviewer 的首轮限定复审提出两项 findings；修订后复审全部关闭，最终 `APPROVED`。
7. 进入下一阶段前发现 latest main 前进至 `8dd935e3`；receipt/chunk/current-year due 直接变化已完成方案修订，并由同一替代 reviewer 限定复审 `APPROVED`。现在只进入离线 RED，historical handoff 门禁不变。
8. 首个离线 TDD 切片已实现发布 mode resolver：5 项目标测试与 3 项相邻赛事回归共 `8/8` 通过；首次代码 review 的两项 P2 已修复，同一 reviewer 限定复审 `APPROVED`。
9. 随后仅因主线 Docker 打包策略前进，再次安全快进至 `201ab2d8`；该主线变化不改变准实时模型、handoff 或 mode resolver 设计。当前继续下一离线 RED 切片。
10. 第二个离线 TDD 切片完成六态状态机纯函数 RED -> GREEN，准实时模块与相邻回归 `10/10`；同一代码 reviewer 完整只读审核 `NO ACTIONABLE FINDINGS / APPROVED`。
11. 第三个切片送审前发现主线前进至 `f1b801ba`；增量仅修复历史详情 chunk dry-run 并新增其测试，不触及准实时文件。专项改动经 stash、`ff-only`、恢复后无冲突，断网专项与相邻回归仍为 `13/13`。
12. 第三轮完整 review 发现等价 JSON 数字 hash 抖动一项 P2；新增 finding RED 后归一化整数型 float，并显式把五种 approved phase 排除于内容 hash。修复后准实时模块与相邻回归 `15/15`，同一 reviewer 限定复审关闭唯一 P2，结论 `NO ACTIONABLE FINDINGS / APPROVED`。
13. 第四个离线切片为 ProjectionControl 基础所有权行取得真实 RED，并新增显式一对一模型与 `0033` 前向 migration；不自动建行、不回填数据、不接 importer/revision/CAS。SQLite 专项、相邻赛事与历史 chunk/receipt 回归初次 `38/38`。
14. 送审前主线前进至 `49e3b222`，增量只修复历史详情 distance upgrade 并扩展其测试；专项经 stash、`ff-only`、恢复无冲突，合并回归增至 `41/41`，check 与 migration drift 继续通过。
15. 新 reviewer 完整审核对 ProjectionControl/0033 无 finding，但发现既有 mode resolver 的 event allowlist 默认/truthiness fail-open P2；新增 RED 后改为只有显式布尔 `True` 放行，组合回归 `42/42`，等待同一 reviewer 限定复审。
16. 同一 reviewer 限定复审确认唯一 P2 `CLOSED`，没有直接 P0/P1 回归，ProjectionControl/0033 与当前完整范围结论 `NO ACTIONABLE CORRECTNESS ISSUES / APPROVED`。
17. 最终状态同步复审前主线又前进至 `700a2a96`，增量只修复历史 importer 中文名 fallback 并新增其测试；专项再次无冲突快进，加入完整 historical import primitive 后组合回归 `49/49`，check/migration drift 继续通过。
18. 最终纯文档 reviewer 建议在 allocator 接入前阻断 revision counter 0；新增真实 RED 后，在模型与未发布 `0033` 增加两个 `>=1` 数据库约束，latest-main 组合回归 `50/50`，等待同一 reviewer 限定复审。
19. 后续离线切片完成 `0034`-`0038`、owner transfer、revision allocator、source network permission、轮询窗口、短事务 claim、DB host reservation 和 checkpoint 双 CAS；准实时模块当前 `63/63`。主线前进至 `5decfa4d` 时仅带入历史导入事实文档，专项再次通过 stash + `ff-only` 安全恢复；本批等待组合回归与统一代码 review。
20. latest-main 组合回归 `103/103` 后统一 review 为 `REVISE`：P1 指出过期 claim 可提交 checkpoint，P2 指出 4652 待导入与实际生产事实矛盾。P1 已分别用真实 RED 覆盖过期 lease 与缺失 expiry，两者均在 mutation 前拒绝；P2 已改为真实 remaining 与缺失 SHA handoff manifest。第二次修复后组合回归 `105/105`，等待同一 reviewer 再次限定复审。
21. 同一 reviewer 限定复审已关闭 P1/P2 并 `APPROVED`。其后新批次逐项完成 due-selector、host outcome/circuit、默认关闭的 Celery selector 与独立 poll route、TRA Free 合成 fixture contract、append-only observation recorder；准实时 `82/82`、latest-main 组合 `122/122`，check/migration drift/diff check 通过。本批无真实网络、worker、生产写入或发布，等待复用既有 reviewer 会话审核新增范围；Compose config 因本 worktree 无 `.env` fail closed，未读取其他 worktree secret。
22. 新批统一 review 指出两个 P2：损坏 claim lease 会被回收、迟到 host success 会清除较新 circuit。已分别取得真实 RED，现以损坏 lease fail closed 和 reservation version CAS 修复；新增定向 `4/4`、相关并发类 `17/17`、准实时 `85/85`、与 historical detail chunk/import receipt/import primitives 组合 `122/122`，check/migration drift/diff check 通过，等待同一 reviewer 限定复审。PostgreSQL 行锁/`skip_locked` 仍是独立门禁。
23. 同一 reviewer 已限定复审关闭上述两个 P2，结论 `APPROVED`。随后独立 worker 部署契约取得真实 RED 并完成 GREEN：三份 Compose 增加固定消费 `race_live` 的独立 worker，普通 worker 显式只消费 `celery`，live 默认并发 1、prefetch 1、soft/hard time limit 45/60 秒，scheduler 保持默认关闭；准实时 `88/88`、相邻历史组合 `125/125`、Compose 解析和脚本检查通过，等待同一 reviewer 审核新增配置范围。未启动真实 worker/Redis/PostgreSQL。
24. worker 增量已由同一 reviewer `APPROVED`。后续完成 authority/conflict policy 与 observation -> revision/pointer/LKG/projection apply；公开赛事页已区分 provisional/official/corrected/conflict/stale，且 shadow 不泄漏。SQLite 准实时 `101/101`、相邻历史组合 `138/138`。真实 PostgreSQL 16 并发门禁发现并修复 nullable JOIN `FOR UPDATE` 和锁等待旧 JOIN 快照两层问题；新增 `0039` deferred pointer/supersedes guards，PG 专项 `4/4`、迁移 apply/reverse/re-apply 通过。下一门禁为真实 broker 离线 fixture runner、后台/监控和本批完整审核；历史 SHA handoff 前仍不联网或启生产 worker。
25. 本批代码 review 返回两个 P1：caller 可伪造 official authority，且 shadow 同内容重放无法晋级公开。两项均按真实 RED 修复：持久 source authority + approved 约束、publication audit、一次性 shadow promotion 与共享物化路径。SQLite 准实时 `103/103`、相邻历史组合 `140/140`；PostgreSQL 直接 15 项首次发现 deferred 旧行像问题，改为重读当前 revision 后 `15/15`，`0040` 迁移往返通过。下一步复用同一 reviewer 限定复审这两项 finding。
26. 两个 P1 限定复审 `APPROVED`。随后完成完全断网的 TRA fixture runner：安全默认 disabled，受控路径/大小/JSON/identity，实际文件 bytes SHA，observation -> shadow revision -> checkpoint，成功继续按窗口探针、失败 5 分钟重试，且 offline 永远禁止物化公开投影。SQLite 准实时 `107/107`、相邻历史组合 `144/144`；下一门禁为本批 review 和真实 Redis broker 隔离测试。
27. runner review 唯一 P2 指出 T+7d 后被固定 10 分钟 fallback 覆盖；补真实 RED 后已删除 fallback，checkpoint 原样保存窗口算法的停止 `None`。目标 `5/5`、准实时 `108/108`、相邻历史组合 `145/145`，等待同一 reviewer 限定复审。
28. P2 限定复审 `APPROVED`。随后以临时 PostgreSQL 16 + Redis 7 + 独立 live worker 完成真实 broker smoke：selector 领取 1 场，worker 写 `1 observation / 1 revision / success checkpoint`，claim 释放、shadow result 0；普通 `celery` queue 的 1 条消息未被 live worker 消费。全部临时资源已清理。
29. 后台只读观测面与赛事级 kill switch 已 RED -> GREEN：10 个 live 模型只读注册，tracking 全字段只读、唯一 action 通过 lock-version CAS 停用并使在途 claim generation 失效、单次审计。Django admin POST 已实测。目标 `5/5`、准实时 `113/113`、相邻历史组合 `150/150`，等待代码 review。
30. 专项再次安全快进至 latest main `c40a8c2b`。新主线已记录历史一期正式详情总账收口、global verifier 零错误、无 historical runner 且网络/功能开关关闭；这满足来源 proof 的执行顺序，但不自动授予 shadow event ownership。专项与最新新增四组历史测试的组合回归 `249/249`（1 skip）通过。
31. 完整 `stable` 发现 `1837` 项，终态 `2 failures / 13 errors / 23 skipped`；干净 `origin/main@c40a8c2b` 临时 worktree 精确复跑同一 15 项得到完全相同错误，确认均为主线日期漂移、未跟踪 `tmp` helper 或既有 historical runner fixture/import-path 问题。本专项未修改这些路径，也未借用历史运行产物。Django check、migration drift、三份 Compose config、worker 脚本语法和 diff check 通过；临时 baseline worktree/synthetic `.env` 已清理。
32. 最终完整只读 review 返回 2 项 P1、1 项 P2：TRA non-finisher 状态丢失、公开投影以内部顺序伪造非完赛名次、生产 live worker 无 CPU/内存限制。三项均取得真实 RED（3 tests / 4 failures）后修复：6 类已知状态保真、结果投影/页面显示客观状态、`0041` 扩展 choices、两份生产 worker 固定 0.25 CPU/384M 默认。目标 `3/3`、准实时 `116/116`、latest-main 组合 `252/252`（1 skip）、SQLite 迁移至 `0041` 和静态门禁通过，等待同一完整-review会话限定复审。
33. 上述 2 项 P1、1 项 P2 已由同一 review 会话限定复审关闭并 `APPROVED`。随后新增受控 TRA Free proof runner，按多轮真实 RED 覆盖 secret/registry/请求预算/schema/脱敏/原子 artifacts；离线 proof + 准实时 `123/123`、相邻历史组合 `259/259`（1 skip）。
34. 首个真实来源窗口已完成：run01 因本地代理 DNS 返回非公网地址安全阻断；未弱化 SSRF 门禁。run02 在一次性容器固定经独立 DNS 审计的公网地址后完成 3 个 Free 请求，regions 55、racecards 10、results 0，业务 DB 零写入且不保存 raw/实体值。该证据只确认认证/端点/schema，不满足四赛日、已完赛结果、延迟或 Basic 升级门槛；等待本增量代码 review。
35. proof runner 完整 review 返回唯一 P2：一次性 proof 错误依赖长期 automation 许可。新增 proof-only registry RED 后已解耦两类权限，automation key 仍须显式 bool，生产/shadow adapter 的长期许可门禁不变；latest-main 组合回归 `260/260`（1 skip），等待同一新 reviewer 会话限定复审。
36. 同一 reviewer 限定复审关闭 P2 并 `APPROVED`，另记录完成时间复用开始时间、未知状态误写 DNF 两个非阻塞建议。两项均取得精确 RED 后修复：后置独立 aware clock、无效/倒退时钟无 partial artifact，unknown/raw status 保真；latest-main 组合 `261/261`（1 skip），等待本后续增量完整 review。
37. 后续增量 review 对实现正确性无异议，唯一 P2 为时钟 fail-closed 契约缺完整自动化覆盖。已新增 naive/倒退/非 datetime/exception、正式与同名前缀临时目录零残留、最后一次 transport/sleep 后才调用 clock 的回归；组合 `262/262`（1 skip），等待限定复审。
38. 上述唯一 P2 已限定复审关闭并 `APPROVED`。为取得时间型门槛，Codex 本地 automation `tra-free-proof` 已启用，每日 06:30（本机时区）至多运行一次同一受控 proof；达到四个不同赛事日期且至少一个非空 results 窗口后不再联网，只提示主任务汇总。automation 不改 tracked 文件、不连接生产/业务 DB，artifact 仍进入本地 gitignore 目录。
39. 用户把 TRA 调整为 provisional public 首发主链、官方来源改为异步复核。该重大口径修正的首轮方案 review 为 `REVISE`，提出 publication admission/read gate、TRA supplemental 不可变量、racecard 全集完整性、不可变 marker、incident 闭环和迁移口径缺口；现已全部写入 spec/design/RED/tasks/rollout/runbook，同一 reviewer 限定复审逐项关闭并给出 `APPROVED`。
40. 用户已授权进入上线推进。专项先 stash 后 `ff-only` 对齐 `origin/main@283bacf2`；四份顶部状态文档冲突已同时保留主线赛事身份/关联事实和本专项事实，`race_events.py` 自动合并仅涉及主线新增 re-export 与专项追加实现。当前从新增公开准入能力的真实 RED 开始；实际生产发布仍须在最新成功代码 review 后取得一次新授权。
41. 首次完整代码 review 因原生 reviewer 模型容量中断而未通过门禁；人工补充检查提出 4 个 P1、1 个 P2：网络后旧时钟、incident 跨轮 replay、日历 read gate、缺生产初始化路径和 raw official marker 旁路。旧时钟、incident replay、日历 gate 与 marker evidence 已按真实 RED 修复；同一 reviewer 仍须完成限定复审和原生 review。
42. 生产初始化缺口已按真实 RED 补齐：严格 manifest/commit/event baseline，dry-run/apply/verify、全事务、精确 replay、四层 shadow policy、allowlist、host budget、control/tracking/source/participant/racecard/audit 均可执行；未来 manifest、人工锁和 TRA authority 错写继续 fail closed。SQLite 初始化器与 runner 聚焦 `13/13`，PostgreSQL 初始化并发及既有锁语义 `5/5`。
44. 首次成功原生完整 review 已关闭此前 findings，但新增唯一直接 P1：赛事日历逐场 public-read gate 在 40 场时产生 `525` 次查询。真实 RED 后已改为批量 resolver，固定加载 live revision、publication、source、四层 policy 与 allowlist，硬门禁为 40 场 `<=12`；公开状态 `6/6`、SQLite 专项 `160/160`、PostgreSQL `5/5` 通过。发布仍停在同一 reviewer 限定复审与复审后新授权之前。
45. 最终本地候选镜像为 `sha256:4a281e426e3299287c948bc6fe7d6e2d0fcda52dbaa322da8db9982530b5b099`；镜像内 check、初始化器+TRA runner `13/13`、registry SHA 和无 secret 检查通过。完整源码树 `160/160`、三份 Compose、worker shell、migration drift 与 diff check 独立通过；部署契约测试读取仓库根文件，不把其在运行镜像中缺 Compose/源 registry 的预期失败误报为业务回归。
46. 用户授权原冻结提交后，远端 main 已前进至 `ccb56f7d`，包含赛事身份 PostgreSQL 锁修复与生产证据。原提交已安全推送到独立分支，不覆盖 main；发布整合改为从最新 main 建立单父分支并重放准实时补丁，冲突只在两份顶部状态文档且完整保留双方事实。SQLite 组合 `180/180`（1 skip）、PostgreSQL 精确目标 `6/6`、整合镜像 `sha256:87f8603320f8...73bcf` 的 check/`13/13`/registry/no-secret 通过；该整合树必须由同一 reviewer 复审并在成功后重新取得授权。


## 阶段 1：来源 proof

阶段 1A（等待历史 handoff）：只做完全离线 harness、合规 fixture、schema contract、fake clock 和请求预算测试，不发送真实请求。

阶段 1B（历史 handoff 完成后）：本地/候选环境只读网络；业务 DB 零写入；订阅成本 £0。每个 source 的真实联网必须满足：生产/正式 shadow 使用 `approved + automation_allowed`，一次性 proof 使用显式、未过期的 `proof_network_allowed`、证据 SHA、固定 registry digest、批准 manifest 和请求预算；unknown/expired/digest drift/manual/blocked 均在首个请求前 fail closed。

样本：The Racing API 至少四个赛日、每地区 10 场候选/至少 3 场正式重点；官方来源按相同赛事人工/只读对照。重点赛事不足时延长日历观察，不降低分母。

日本 J-G1-3 不使用上述通用日本样本替代：原始分母是首个可观测日起 90 天内正式总账的全部合资格障碍分级赛，至少需要 3 场已完赛且覆盖窗口内实际举办的每个等级；不足延长至最多 180 天并记录 availability gap。每份报告固定输出 original/active/deferred 及逐赛事/等级缺口。

通过门槛：

- identity precision 100%。
- 正式目标命中 100%；完整赛果至少 99%。
- 有可信来源更新时间时暂定结果 p95 <= 10 分钟；否则使用 `[previous_successful_poll_at, first_seen_at]` 区间的保守上界，失败轮询区间单独报告。
- 字段/退赛/DQ/DNF/同着可表达；未观察到改判时明确保持 correction gate off。
- source terms/许可状态逐源可判定，禁止来源保持 blocked/manual。

失败处理：不购买升级；先区分计划层级、地区覆盖、接口、身份匹配和来源自身延迟。需要联系支持或官方机构时，先由用户授权联络范围。

## 阶段 2：本地模拟

模式：fixture + fake clock + 本地 PostgreSQL + eager/测试 worker；无生产网络。

验收：

- 所有 RED -> GREEN，状态机/重放/冲突/回滚/缓存/队列隔离通过。
- 200 due target 性能和慢源/429/worker crash 故障注入通过。
- 历史 runner 相关测试和现有赛事页面/导入 tests 无回归。
- SQLite 和 PostgreSQL 证据分层报告。

回滚：删除本地测试 DB/容器即可；不影响 production/historical runtime。

## 阶段 3：单地区 shadow

默认英国，因为 The Racing API Free 是最小 API proof 路径；若 source proof 显示英国覆盖/许可不合格，则经用户确认改为香港。不会静默切换地区。

部署顺序：

1. 历史任务已安全完成/暂停并按 manifest 交接，目标 event ownership 已精确转为 live。
3. 备份、迁移；所有 live mode 仍 off。
4. 启动独立 `race_live` worker，不启动公开写入。
5. 开单地区 `shadow` + 精确 event allowlist；Beat 只发 due tasks。

开 shadow 前先演练 mode 单调门禁：global/region/source 任一 `off` 时，即使 event 配置为 public 也必须无网络任务、无公开写入；只有逐层显式放宽上限且所有门禁允许时，effective mode 才能到 shadow。

验收至少 10 场/3 场重点，连续两个真实赛日：来源成功率、延迟、canonical shadow、资源、新闻队列、web p95、历史控制表均达标。shadow 不更新 `RaceEventResult` 当前投影和公开 badge。

回滚：地区 mode off -> 停 `race_live` worker -> 保留 observation/audit；无需反向迁移。

## 阶段 4：五地区 shadow

每地区独立 source gate。许可或稳定接口未通过的地区只能完成 fixture/人工技术验证，既不发自动网络请求，也不计作真实 shadow 或“可公开 shadow 通过”。美国若只有不完整 TRA Core 和未授权网页，不得为了阶段齐全伪称通过。

通过门槛：

- 每地区至少 10 场、3 场正式重点；identity 错配 0。
- provisional/official 分类错误 0，公开写入 0。
- host 请求符合预算，无 403/robots 绕过；429 可恢复且 circuit 有效。
- live worker 资源和队列不影响 web/news/QQ；历史 runner 状态零触碰。
- source coverage/terms matrix 由用户审核。
- 日本 shadow 报告必须分列 G1-3、JpnⅠ-Ⅲ、J-G1-3；J-G1-3 没有有效 deferred artifact 时属于 active 分母，不得因通用 10 场/3 场达标而省略。

## 阶段 5：暂定赛果灰度

前提：五地区 shadow 结论已审核；只选择已满足自动化许可和 provisional 质量门槛的地区，不要求不合格地区一起开启。

模式：`provisional_public` + 精确 event IDs allowlist，不用随机百分比。

首批：每地区最多 3 场正式范围内赛事，按赛事等级、时间和来源成熟度选择，默认只开一个地区；页面显示“暂定赛果”和更新时间。官方冲突/来源 stale 自动冻结，不升级 official。香港包含 G1-G3，日本平地/泥地包含 G1-G3/JpnⅠ-Ⅲ；J-G1-3 只有独立 proof 通过后才进入灰度。

The Racing API 是暂定赛果首发主链：完整 API 结果通过唯一 publication admission 后立即公开，不等待官方二次复核返回。每个首批 event 必须预先绑定可执行且有版本的官方复核路由；复核任务与前台发布并行，官方一致则升级 official，官方不同则原子显示官方 revision，T+2h 未到则只开一个 incident 并保持明确标注的 provisional。adapter 不得决定 `project_current`。

验收：浏览器/后台检查、p50/p95、0 错配、0 未标暂定、告警与 kill switch 演练。至少两个窗口后才扩大。

回滚：先把默认关闭的公开 read gate/global mode 设为 off，并用 policy version 使详情、结果列表和 cache 立即隐藏既有 published live revision；再停止新 admission/投影写入。保留 canonical/observation/publication audit，重新开启只恢复当前获准 revision。

## 阶段 6：正式赛果灰度

只有地区官方来源/批准 feed 的 official marker、许可和延迟 proof 通过才进入 `official_public` + event allowlist。The Racing API、Racing Post、Sporting Life、Geny、HRN 等不能单独把赛事推进 official。

先对已存在 provisional 的 allowlist 验证：官方一致确认、官方不同结果修订、同着/DQ、官方延迟、T+24h correction probe。没有真实 correction 样本时，`corrected_result` 自动公开仍保持 event-level 关闭，可由管理员按官方证据手动确认。

## 阶段 7：正式公开

扩大顺序：单赛事 -> 单地区 allowlist -> 多地区 allowlist -> 经过审核的完整正式范围。每次扩大都保存目标 IDs、source route digest、指标和回滚点。

日本 J-G1-3 只有在独立 proof 完成后才可生成 deferred 候选：第 30 天只做来源 checkpoint；至少观察 90 天后仍无获准来源或最低样本下 identity/完整度/分类/字段状态/延迟门槛失败，或者延长至 180 天仍样本不足。必须由用户批准带 SHA、精确 event/grade 清单和 `review_due_at` 的 artifact 后才能排除；有效期不晚于 180 天且须在下一场合资格赛事前复评。其余日本范围可继续扩大，但报告必须同时显示 original/active/deferred；deferred 非零不得宣称日本完整范围完成。

最终门槛：

- 生产内容与受审 fingerprint 一致。
- 备份、迁移、worker/Beat route、flags、health、页面、admin、队列、资源和日志验收通过。
- 各地区 source terms/许可未过期；The Racing API 价格/计划在实际购买前重新核对。
- 历史赛事公开开关和 historical runner 独立安全契约不因本专项改变。

## Basic 购买流程

购买不是 rollout 的必经步骤。Free proof 达到 `design.md` 的全部门槛后：

1. 生成 Basic upgrade recommendation，列出 Free 证据、缺字段、预期收益、最新价格/税/退款/条款。
2. 向 The Racing API 支持书面确认计划层级是否解决具体字段/覆盖问题。
4. 只购买一个月 Basic，记录开始/续费/取消日期；首月复测，无收益则取消。
5. 不购买 £499 历史包、North America £49.99/月 add-on 或其他扩展，除非以后另立专项并获授权。

## 生产回滚

优先级：

1. 全局 `off` 或地区/source/event kill switch；mode 按所有适用 cap 取最小值，任何下层配置都不能覆盖该 off。
2. 关闭 provisional/official public read；将 current pointer 原子切回同 event/kind 的 last-known-good revision 并重建投影，或隐藏结果模块。
3. 停 Beat selector，再停独立 `race_live` worker；不 purge 新闻队列/Redis。
4. 保留 observations/revisions/OperationLog 供审计。
5. 若投影数据错误，只通过受约束 pointer/CAS 使用 last-known-good canonical revision 受控重投影；不删除 revision/observation 审计链。若数据库结构/事务异常，按验证过的备份恢复。
6. 不删除历史 runner 数据、不改其 checkpoint、不用普通 app rollback 重建 DB/Redis/shared network。

## 发布后证据

按仓库 evidence-only allowlist 追加真实 SHA、备份、migration、worker image、flags、event IDs、延迟、health、队列、资源和回滚演练结果。spec/design/tasks/test/config/代码变化不允许混入 evidence-only closure；若验收要求行为变更，回到完整 review 和新授权。
