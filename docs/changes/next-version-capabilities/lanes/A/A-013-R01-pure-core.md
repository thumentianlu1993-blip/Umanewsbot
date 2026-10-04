# A013-R01-PURE-CORE-001：纯合同核心交付

状态：纯core实现及离线TDD完成，原R两项finding已修复，待同上下文复审；未合并/发布，R01整卡未完成。开发起点72177361561235378e9a78de3d3c8018e50a06f7，stacked分支codex/next-version-race-data-20261003，F01依赖固定06b01aea9041eacb3deae9f46968eb06fd459cb6；原R方案子集批准9b5d567ab4b1eaff4b36c8830632a483ba94443a。只负责两个新增Python文件及本交付文档，不改共享映射、模型、迁移或hook，不运行数据库/网络/旧full/PG。F03完整0/45、真实scope、O03公开探针及R01整卡仍未完成。

## 先行测试设计（对照已有test_cases.md及已审A012）

1. 合同：显式scope/candidate锚点、F01实体/版本、nullable event、独立应推进集合、aliases带明确证据、完整审核收据及不可变输入。mutation为缩scope、换candidate/version、少审字段冒充完整、无证别名、输入突变/未知枚举/非UTC/缺字段。边界为零分母/unknown/部分严重错/有界输入。
2. 汇总：10目标4审1错=25%；S全应推进分母，transport不当信息错；多错/重复/repair留历史、输入coverage不完整如实报告；[start,end)及carryover、168/48分别计算、真实有效区间不从计划推。mutation为E/N、重复计场、repair删除旧错误、未审当正确、deadline=end入本窗、重叠时长相加、无启用证据补全时间。
3. 时延：源(a,b]/公开(v0,v1]开闭及300/600等号、仅核验上界、无probe、clock未知、空/矛盾区间、版本/权限不匹配。mutation为lower=h不区分开闭、首次成功晚直接判late、内部可见当公开、unknown当pass或负时延clamp0。
4. GREEN后仅跑本新unittest及固定F01离线最小相关回归，原始stdout/stderr/退出状态按每次run存专用runtime；不实现ORM/事务/Celery/部署，相关PG/rollback用例本轮不声称覆盖。无新代理、无共享文件覆盖。人工确认统一根AGENTS.md，本派单纯core范围已有授权。

## 实现与输入边界

仅新增`server/stable/services/race_timeliness_contracts.py`和`server/stable/test_race_timeliness_contracts.py`。输入DTO为frozen dataclass持有校验后的JSON字节字符串，to_dict返回新副本。F01以原字节消费，未复制公共Action/来源精度枚举；实体、源时间和input_version经F01.parse_input验证，capability复用F01.CAPABILITIES。内部复用F01的纯wire guard/UTC/hash工具，属于固定06b依赖，F01变更时须同时验证本core。

| API | 精确合同/输出 |
|---|---|
| parse_report(value, expected_scope_sha256=..., expected_candidate_sha256=..., expected_coverage_sha256=...) | 三个锚点须由调用者独立固定；scope包含完整target/nullable event/声明资料可审核状态/应推进区间/全部所引用F01版本与明确alias证据。coverage含scope摘要、expected origin IDs、proof_ref、complete/gaps及相同window/as_of；原清单被缩小不能靠重算包内hash自证。版本/当前版本/收据均闭合，完整审核须确实覆盖关键字段集合 |
| summarize(ReportInput) | E/已完整审核D与S/全部应推进N分离；未审/部分/严重错/transport/资料missing/unknown分列。记录同ID同字节幂等、冲突拒绝；repair仅关联历史、不删旧错误。显式alias才能去重，unknown target保留且complete_denominator=false；[start,end)和carryover分开。有效时长只并集真实声明区间且clip至window/as_of，单窗计算，没有相加O06/O08的API |
| parse_latency(value, expected_context_sha256=...) | context绑定candidate、strong target、capability、F01版本和选定源证据、内容/public/权限版本、300/600及显式as_of。外部probe必须同版本/同目标/证据与UTC时刻；未来probe拒绝。缺probe可表达，内部可见只为unverified |
| evaluate_latency(LatencyInput) / LatencyBounds、classify_bounds | 源(a,b]与真实可见(v0,v1]给双开区间；全部时间算整数微秒，避免float舍入等号。lower=h开端为late、闭端不能；upper≤h及精确h为met。首个成功读取只上界，晚于h不直接late；unknown/clock未知/矛盾或空区间不pass |

每个target必须显式material_availability=available/missing/unknown，不从未审/未执行反推缺资料。unknown发生时刻不能入窗口审核分母并会破坏测量完整性，部分严重错误仍blocking。report的measurement_complete仅是本输入的信息审核/记录/声明有效窗覆盖完整性，**不是R01整卡或公开SLA验收通过**；公开时延必须另用外部probe合同。比率为一般float比值，严格验收可用整数分子分母交叉比较，不能靠四舍五入。

摘要与proof_ref只校验形状/一致性，不认证调用者的真实收据。source时间含义、完整资料门槛、合法absence、alias强映射、origin集合及有效启用/健康区间均须调用者独立取得并冻结；有限记录无法推出全集或恢复瞬时漏事件。钟误差须由来源证明提前向外扩入端点，否则clock_trusted=false。没有真实F03/O03及scope证据，本core不发起补取，不声明真实SLA/无损审计。

有界输入复用F01 wire上限1MiB/depth64/nodes100000，另限targets1000、records5000、每target100版本；约束会拒绝超量，不截断后宣称完整。core只import dataclasses/datetime/json和现有F01，无ORM/网络/当前时钟/随机数/资源操作。

## 2336首交原始RED/GREEN证据（保留，非本修订最终证据）

专用runtime：`/Users/mentianlu/.codex/runtime/a013-r01-pure-core/`。每项.log保存真实stdout/stderr，配.receipt.json记录命令/退出状态/当轮code及test SHA；未覆盖失败日志，也未拼接旧full或PG成功。

| 组/文件前缀 | RED → GREEN | 说明 |
|---|---|---|
| red-contract → green-contract | 7项，缺校验NotImplementedError → 7 PASS | 初始脚手架只有API，没有行为。将一处合成event_id改为与canonical一致；RED本身失败原因始终是目标行为缺失，不是该fixture |
| red-summary → green-summary | 6项NotImplementedError → 同组6 PASS（连合同组共13） | E/D、S/N、repair及窗数学 |
| red-material-contract → green-summary | 1项拒绝新显式资料状态 → 正确接受并汇总 | 防止把无审核记录推成missing；该字段先行RED再加实现 |
| red-latency-behavior → green-latency | 8项NotImplementedError → 8 PASS | red-latency初次因脚手架缺新签名/类失败，保留原输出但**不作为有效RED**；补齐空API后才取得有效行为RED |
| red-hardening → green-hardening | 6项中1失败+1错误 → 6 PASS | 已有identity资料时间被误用为result时延未拒绝；非法alias泄漏TypeError。补capability一致性及稳定ContractError |
| red-snapshot-boundary → green-snapshot-boundary | 2项中1失败+1错误 → 2 PASS | unknown target不得声称strong分母完整；显式as_of合同及未来probe |
| red-coverage-anchor → green-coverage-anchor | 1行为失败 → 1 PASS | 缩origin证明清单必须被外部固定SHA拒绝 |
| final-verified-offline | 47 PASS / 0失败错误skip，0.124s | 新core30项 + 固定F01离线17项；命令如下 |

```sh
PYTHONPATH=server PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest stable.test_race_timeliness_contracts stable.test_content_contracts -v
```

`final-offline`是加独立coverage锚点前的46 PASS，不能证明最终代码；`final-bound-offline`47项有1辅助器KeyError（先对缺coverage取hash），保留失败，不当通过；修正测试辅助器让缺字段到达真实核心拒绝后取得以上最终47 PASS。本轮没有skip、未运行Django full、PG、数据库/事务/队列/真实网络，savepoint/账本故障/探针连通性等真实接入不在本交付中。

2336首交code SHA256 `a080e97733426d69942cdb0b4769738d362a7c02722577dfc2073b6a96a1441e`；test SHA256 `7a4e16253b7a44e6d1562adb28449661e72199f31a30917ad8f3bfd58d6dcedc`。2336首交运行输出绑定上述当时字节，独立review需固定本交付commit；Git/原始证据与模型/生产状态分开。

## 精确影响映射proposal（尚未登记，root负责共享映射）

| 变更/依赖path | 必须选测模块 | 执行profile |
|---|---|---|
| server/stable/services/race_timeliness_contracts.py | stable.test_race_timeliness_contracts；stable.test_content_contracts | 现有纯unittest，无Django setup/DB/网络；本修订共61项 |
| server/stable/test_race_timeliness_contracts.py | stable.test_race_timeliness_contracts | 同纯unittest，本修订44项；不能只登记旧F01模块漏新core |
| 后续变更server/stable/services/content_contracts.py或F01-contract-examples.json | 既有F01影响集并追加stable.test_race_timeliness_contracts | 本core反向依赖，不能把F01 fixture或validator变化仅当文档 |
| 本lane交付.md | 文档引用/围栏、git diff --check | 不触发业务测试扩张 |

本proposal不新增runner/框架，不修改根catalog或impact映射。root整合时需将实际现有profile/模块登记生效后才声称CI已映射；缺登记不得悄然退回full。本地纯测试不证明自动CI已执行。

下一步仅交原R只读代码review；actionable纯技术finding在原上下文修复复验。F03完整0/45、scope/JG1、O03实际probe、数据库ledger、hook、迁移/部署仍未解锁或完成；没有新G2/G3动作。

## 原R返修：A013-R01-01 / A013-R01-02

返修base固定2336ddb53eda432b31c3dbf563aa513b57dc4430，原R报告commit `6f339a4923beff1e000c6d293181eb978076052b`。仅原三个责任文件，F01依赖/来源/实际接入边界不变。旧`a013-r01-pure-core` manifest及40文件本轮指纹全部匹配，原日志/包不覆盖；新独立runtime `/Users/mentianlu/.codex/runtime/a013-r01-review-repair/`。

| Finding | 修复与反例 |
|---|---|
| A013-R01-01 P2 | deadline记录不经occurred窗口先过滤；有已接收的known-time收据且截止在[start,end)即归原窗S，后来repair不删违约。新增秒/微秒窗边界、deadline=end归下一窗、旧deadline迟到在下一窗作carryover、缺/未知/未来证据不造违约 |
| A013-R01-02 P1 | 窗口E/D保持原口径；独立输出historical_severe_error_targets（截至as_of已发现历史）、window_severe_error_targets（本窗已知发生时刻发现）、open_severe_error_targets/open_severe_record_ids（截至as_of尚开放）。原severe_error_targets成为open计数兼容别名，blocking只取open；普通clean audit不暗示repair |

receipt合同新增必需`recorded_at`，与`occurred_at`分开：记录时刻≤显式as_of、已知发生时刻≤记录时刻。旧发生时间未知仍为null，不能从recorded_at补原发生时间；未知时间严重发现仍block，独立有效repair可关闭当前问题但不补历史时刻。没有已获得收据不能由deadline过去直接算S；新快照保留迟到recorded_at/occurred_at而不倒写旧快照。

repair.payload必须含`resolves`、按每个原record ID精确对应的`resolved_versions`、`resolved_fields`。版本必须与原错误input_version完全相同；audit修复字段为其真实error_fields非空子集（clean audit不能作修复origin），transport/deadline的字段集合为空。repair自身input_version仍须是该目标声明的F01版本；错误target/ref/version/字段或未知/无效修复时间拒绝。原发生时刻已知时不能提前修复，修复记录不能早于所关联发现收据。部分字段修复继续block，只有对应原错误全部字段的明确repair集合闭合才解除；同场另一错误未修复仍block。首次完整修复时点按证据排序确定，history及窗口信息错误率不删除。此为尚未接入的纯core收据合同收紧，消费方须提供这些显式字段，不是在现有业务数据中自动补值。

`carryover_record_ids`保存进入窗口时尚未闭合的历史事项；窗内修复后其carryover历史可仍在，但当前open计数关闭。迟到deadline的carryover依据截止归属，其他问题保留发生时刻语义。unknown原时刻修复后record_coverage_complete仍可能false，不声称恢复了原历史。

### 返修验证

- `red-original-review-repros.log/receipt`：原两个最小反例2 FAIL、0error，代码字节确为2336首交；修前代码/测试另存`red-original-code.py/tests.py`，不是环境或import失败。
- `red-review-boundaries.log`：8项，3FAIL/3error/2PASS；包含迟到违约、修复后阻断及尚无新诊断字段/未知时刻repair约束的真实旧行为，完整失败日志保留，不称8项全RED。
- `green-review-boundaries.log`：两最小反例+上述8边界共10 PASS；另补repair version/字段/有效时刻、部分字段闭合、clean/wrong-target及recorded_at/as_of验证。
- **本修订最终** `final-recorded-time-offline.log/receipt`：61 PASS / 0failure/error/skip，0.189s；新core44+固定F01最小17。`final-repair-offline`60项是recorded_at最终收紧前的中间通过，不替代最终61项。运行命令同上，纯unittest无Django setup/DB/网络/队列/旧full/PG。

本修订code SHA `0d677c5d15544a1e6de5c210408c3544e9ea605d9fc62a1aa167ae6a32e37f7b`；test SHA `49bf222fb48f03098399ca0ba724562afb273f5d10b28d30e3f4ad2815a3a37a`。git diff --check、仅原3文件范围检查通过。交原R同上下文复审，仍不声称R01整卡/真实SLA/CI已映射或生产完成。
