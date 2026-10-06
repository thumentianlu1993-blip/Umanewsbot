# A032：真实 RED 后的七字段 GREEN 候选

任务 `A032-H03-BASIC-PROFILE-IMPLEMENT-001`；已审范围沿A031最终7c0eb503，集成base2c72521c，新A树独立。首次实际RED固定在 `73758be2433242fce37f682754472d13e961a943`（tree1612d9897b241dc9c25f73337bec2f43de6ab05c）后才开始业务实现。本候选仍待ROOT分配GREEN窗口与独立review，不声称可用/交付或H03完成。

## 已取得的业务 RED 和窗口释放

ROOT独占分配现有impact-ci PG容器，受信8controls从2c725/6e6导出并与RED树及B原件逐字比较。固定镜像 `sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905`，未build/pull。官方django profile运行唯一ID `stable.test_horse_basic_profile_from_cache.BasicProfileFromCacheTests.test_persists_seven_fields_and_json_safe_date_without_publication`：PG16.15/Django5.2.1/Linux，lifecycle complete，executed1/failures1/errors0/skips0/exit1；fixture/候选通过后因真实数据库country仍空、未成为AUS的AssertionError失败，有效能力RED。

证据 `/Users/mentianlu/.codex/runtime/a032-h03-red-pg-window-001/`，red-receipt SHA `c2d7baef1c9ba7a2b69b4823868185b2eb858e5dbd03744b0199858b52d65897`。实际inspect约束nonroot10001/networknone/RO source和controls/capdropALL/NNP/2CPU/4GiB/256pids/3GiBtmpfs。worker35.5秒、全窗46.6秒；容器0、owner80998/runner81039实时不存在、fcntl锁可重获，ROOT已收到释放交接。600秒总预算包含最后60秒清理，外层540秒停止线。没有host PG、自制PG测试驱动、真实.env、来源或生产访问。此前A032准备驱动已被ROOT指定官方路径取代，不进入本次或GREEN执行。

## 实现后的数据流

1. 候选仅允许plain JSON结构；原bytes再过已审HKJC adapter及独立expectedSHA；重新H02规划，目标候选规范SHA必须完全一致且reusable/单cache_ref/已有profile。原件时间不改；无法绑定输入直接blocked，无取源fallback。
2. 原件只取七字段，birth_date转date；既有model field.clean及max_length校验，不截断或清空。actor必须已存本地用户，只用于原有审计、不冒来源许可/人审。输入摘要绑定H02候选、H01快照摘要、实体版本集合、as_of/TTL、规范UTC预期baseline与固定来源角色；因此改变这些绑定参数需新请求版本，完整原请求重投不变。
3. 外层atomic，profile select_for_update(of=self)重读并关联TermEntry；仅DRAFT/READY且hidden_at空。当前verified keys沿旧casefold规范，flat/name不升级身份；同namespace矛盾或规范重复拒绝。局部其他profile按JSON键icontains预筛后做精确casefold数组比对，最多100个匹配候选，超过即blocked；只是失败闭合的局部冲突检查，不声称全库唯一/旧writer并发合同已完成。
4. 安全核验后查同profile/PROFILE/固定source角色的raw消费key；APPLIED且同输入摘要返回既有结果和只读current gate，profile/candidate/log零写。异摘要/重复消费行/非APPLIED/异常receipt拒绝。**只有未消费新key**才检查updated_at；旧输入不自动重取新baseline。
5. 薄候选保存接缝：JSON payload/diff/audit中的date/datetime严格ISO安全化，confidence默认0；内存候选恢复typeddate，调用既有horse_profiles.apply_data_candidate，复核field/module锁、完成度、APPLIED和既有log。保存输出收据也在同一外层atomic，任何create/apply/log异常传播并整体回滚，无孤儿或自动补跑。全部字段已相同/全module锁仍消费一次；日后解锁不复用旧版本写入。
6. 返回applied/already_applied/blocked、before/after、skipped_locked、candidate ID、input SHA/旧来源时间和只读发布gate；published=false、review_status不变。新服务没有发布/producer/network/QQ/中文名/术语/血统/履历写入口，不改shared models/views/settings/catalog/B翻译面，无migration。

## test_cases 增补与验证状态

前一报告的14业务项＋1真实PG锁等待并发项保留，新增10项：READY仍不发布、draft但hidden_at拒绝、目标不存在不新建、flat同namespace矛盾拒绝、overlong不截断、空owner不清除、过期不fetch、candidate create失败无孤儿、实际apply/log写后失败全回滚、全字段相同仍一次消费/审计且gate只读。首用例逐字段核profile除七字段/completeness/updated_at外全属性不变，保护中文/身份/公开/career等。共25独立完整ID，非继承重复，不skip。

已实际执行：

- AST/正常导入/25ID收集及合成adapter→H02 reusable，无DB/network guard；不是业务测试执行。
- 相邻纯离线adapter18/H0216/H0121，共55通过，本地有限证据，不替代Linux PG业务GREEN。
- workflow contract及其4文档测试、git diff --check通过；最终A031输入与旧fixture字节保持。

准备脚本曾因未传PYTHONPATH无法导入stable、复制检查脚本残留已停用驱动路径而失败；均在无DB准备阶段修正并复验，通过日志/检查事实保存，不算RED/GREEN。没有第二次PG执行。新增业务实现仅静态可导入，实际保存/幂等/回滚/JSON查询/PG行锁尚待GREEN窗口，不宣称测试通过。

## 下一窗口请求与停止

ROOT可用同官方controls/image，固定新候选SHA/tree，诊断plan精确25IDs（先同一首RED转GREEN，后其余24），profile=django，非collector/catalog/full/正式交付。仍1容器/2CPU4GiB256pids3GiBtmpfs/RO/networknone；申请同600秒含60秒清理、540秒停止线；并发测试最多3连接（观察者＋2worker），预算失败不扩新build/权限/资源。实际资源分配与B排队由ROOT协调；当前只是候选，未启动容器或DB。

本轮仅service、独立tests和本A报告增补。旧A树保留；未push/PR/merge/deploy/生产/新身份/真实抓取/发布，无subagent/model CLI。最近额度10%已用、90%剩余。交固定候选和runtime后停止，等待GREEN资源；发现需共享schema/全局身份约束时回ROOT，不私扩。

## 首次 GREEN25 结果与测试基线修正

任务 `A032-FIRST-GREEN-25-WINDOW-001`，固定f3bcf547/tree d8a763dd按原25 ID执行一次，未修改被测树/ID/controls，不失败重跑。官方worker完成25项，24通过、1失败、errors0/skips0，PG16.15/Django5.2.1/Linux；唯一首用例在TermEntry总数硬编码1处失败，实际30。其前面的country七字段/date/JSON候选/APPLIED断言已过；其他24含原请求幂等、事务回滚及PG Lock等待断言通过，但此结果不能称整组GREEN。

根因只读定位：0009迁移有14个普通词种子，0030有13个普通术语＋2个概念，合计29；首次test保留迁移种子再加自有TermEntry=30，后续TransactionTestCase flush不重跑数据迁移。原测试假定全库只有自身fixture，是测试基线错误，不删除种子、不改迁移或业务service。修正统一记录setUp结束执行前计数，期望candidate/log各增1，profile/race record/TermEntry计数原样保留；仍严格拒绝术语增删，不把30硬编码为新期望。

并发原例只保留了“必须看到pg_stat_activity wait_event_type=Lock”的通过断言，没有打印原PID/等待行；首次证据只声明断言通过，不制造原始行。新固定测试增补first/second backend PID和pg_blocking_pids：必须明确second等待first，再把实测Lock/阻塞PID打印到官方原日志供后续封存；不加ID、不改业务行为，仍最多3连接。

原窗口worker45.8秒/总56.8秒，实际inspect仍约束一致；容器0、owner86466/runner86511实时不存在、flock可重获、六候选文件hash未变，已回ROOT释放。原件 `/Users/mentianlu/.codex/runtime/a032-first-green-25-window-001/green-receipt.json` SHA `44c00b83e701379a66588e51fd1bc8fb52239651a4914f887e18c1d02a373df5`，绑定10原件。原日志完整保留。

修正仅独立tests和本报告，业务service与f3bcf547逐字不变；无DB静态/import/25ID及合成检查通过，精确25ID集合与上一窗口相同。新固定SHA交ROOT申请同25复验，不自行复跑；修正后GREEN尚未执行，独立review仍待。额度起止10%已用、90%剩余。
