# A034：已有赛绩补连实现准备，待五例 GREEN 窗口

任务 `A034-GREEN-IMPLEMENT-PREP-001`。ROOT 已核固定 RED `af6109eae75dd144d81f6d0c2d949a0eca40d132` 的唯一首例为有效业务失败（真实 fixture 前置成功，record.event_id None!=1，1 failure/0 error/0 skip）；其余四组未执行，不称其已取得 RED。完整测试设计见 [A034 test_cases](A-034-h03-career-link-test_cases.md)，方案基于已审 `44f79a62`。当前指令覆盖本地实现与静态准备；没有 PG 窗口、测试运行或生产授权，G2/G3 未触发。

## 实际实现与责任范围

仅实现新 `horse_career_record_link_from_cache.py`，新增本 A 报告；原 RED 测试/fixture 字节不变，未作测试技术修正。A032 helper/shared writer/admission/models/settings/catalog/B/C 保持原样。原 service 签名原样保留，调用方仍须提供可信原 bytes/独立 expectedSHA/H01-H02候选和版本、明确选中行/目标/binding SHA/profile及record baseline。

1. adapter→H02 真实复算规范摘要一致/reusable/单 cache scope；只选唯一 selected_row_sha，稳定 provider/race/horse ID、slot/operator/venue/date/namespace/timezone 齐全，拒源行直带 event/result 绑定，started/exact 以原 normalizer 判定。原件强马 ID 与 producer source 完全一致。
2. 外层 atomic，profile 阻塞锁串行化本入口；private/current verified H01 身份/人工 RACE_RECORD 锁核验。record→event→enrollment→source→binding 固定子锁序 nowait。锁前 binding discovery 仅发现 enrollment PK，之后全部归属/合同读取使用锁后对象；绑定 FK cache 显式用锁后实例。不扩大到旧 writer 全局线性化。
3. timezone.now 服务端实时采样，真实固定 policy loader/parser/route_for 和原 binding_admission_reason(racecard/check_runtime=False)；原 flags/review/terms/有效期/manifest/identity digest/registry/撤销/URL/场地合同保留，额外只读核现有 enrollment authority/state/retired_at 与 binding schema。四个赛事锚与 source/current row 精确一致；首片 same-year/edition，名称不回退。缺既有合同即 blocked，无创建/换绑/flag/网络动作。
4. 现有 record profile/source ownership、raw 精确行指纹及 normalizer/writer 事实一致、无旧 normalization issues；结果不关联、只允许 unlinked 或本 event 已连。安全检查后再读同 profile/module/H03角色的 H02消费 key：同完整输入 SHA 的 APPLIED 原请求返回 already_applied，跳过 writer/normalization/audit；异输入/歧义拒绝。只有未消费 key 再核两 baseline，所以首写改变 updated_at 后原完整 baseline 可重投。
5. 完整投影共享 `_race_record_values` 的 **31 个管理字段**，所有旧值保留，仅改 event_id；用原 writer 显式 record 参数，重复/旧歧义固定 blocked。writer 返回 RaceRecordUpsertResult.record，分别检查返回内存 issues 和 refresh_from_db 后 issues/真实关联/同条数；所有其他 record 字段严格保护，profile仅允许原 refresh 的派生字段和时间变化。无变化已关联目标输入跳过 writer，只消费审计一次。
6. 写后重新采样实时 clock/load policy，要求 policy.digest 与锁后初检一致，再核原 binding 合同。过期/漂移/postcondition 用内部拒绝异常退出外层 atomic 后返回 blocked，避免普通 return 留下写入。candidate APPLIED/默认 confidence0/日期 JSON-safe/inputSHA/H01/H02/原件/binding/policy证据/result和本地actor、单 operation log 与 writer 同事务；数据库/save/log异常回滚并传播，不误记成功。55P03资源忙单独 blocked，不自动重试。

原 writer 已保护 raw/source refs/external idempotency，本片不建立第二个赛绩 writer。来源总数/authority/中文术语/公开状态等完整持久字段后验保护。此片不实现 result马归属、跨年、全量新增/更正/撤销、完整career/full-profile或生产并发；真实现有合同或源强字段缺失仍 blocked，合成 fixture 不提供现实授权。

## 已做与未做的验证

AST语法通过；原函数完整 keyword 签名与 RED 相同；自动从共享 `_race_record_values` AST 提取全部必填/可选管理 key，与 WRITER_FIELDS 集合精确相等（31），并对应真实模型字段。原测试/fixture和所有共享代码/八controls与 RED字节相同。工作流契约、4项文档测试及 diff 检查通过。以上仅静态准备，不证明业务 GREEN、rollback或PG并发已运行。

首五 GREEN 仍是 test_cases 中同一五 canonical IDs；没有新增 ID 或放宽原断言。申请 ROOT 单容器/无网络官方镜像与原八controls的精确五 ID Django 窗口，600秒总窗含60清理/540止测，2CPU/4GiB/256PID/3GiBtmpfs/非root10001/ROsource/NNP。镜像拟复用 `sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905`，由 ROOT 重新绑定；未分配前不得启动。固定 GREEN SHA、测试 tree、计划/hash、owner/heartbeat/锁、实际 executed IDs/rawlog/lifecycle/inspect/PID清理证据需封存；任何 fixture/import失败不冒充业务失败或 GREEN。

五例全部通过后才按实际影响提出精确回归选择：本片局部 H01/H02/A032/共享career writer，以及读取的 binding 合同中直接相关现有方法；不直接扩大相邻全模块，正式 core要求保留。新增路径 catalog未改，交 ROOT/C精确映射或专用窗口。出现共享契约无法承载时交 ROOT，不改 schema、权限或其他 lane。

最新额度13%已用/87%剩余；每5分钟核验/<=1%停止/每批目标<=3%。本地实现待真实五例 GREEN，随后仍需独立 review；未 push/PR/合并/部署/生产/真实网络/付费/公开权限变化。


## 首五窗口失败与日期类型技术修正

`A034-FIRST-FIVE-GREEN-PG-WINDOW-001` 固定958e388d/tree43199cd2，仅原五ID一次；实际5 failures/0 errors/0 skips，lifecycle complete，均在共同首次FK None!=event PK断言失败。负向、故障/幂等后续及PG锁子例未走到，不称保护通过或锁证据。原始结果/runtime封存于 `/Users/mentianlu/.codex/runtime/a034-first-five-green-pg-window-001`，green-receipt SHA `db129d87312ec70c8497ca6bc1234bd578d36f63b70c4f45d11cde6b0bb6e0a6`。worker37.451秒/总窗48.636秒；owner26411/runner26436及进程组gone、flock可重取、Docker0、12源码hash未变，已实际释放。

静态确认 `_parse_date_precision` 返回 `parsed.isoformat()`，`_normalize_race_record`保留ISO字符串；模型DateField/readback为date。新入口此前直接事实比较会把有效日期误拒。技术修正仅在新入口确认exact后 `date.fromisoformat(normalized['race_date'])`，不改原bytes/行摘要/共享normalizer/writer，也不改原RED测试/fixture或任何断言。用原 `_record_contract` 的无DB类型诊断可复现字符串导致record_fact_conflict、typed date通过；这仅静态类型衔接诊断，不是五例GREEN证据。原traceback没有输出blocked reason，不能把定位说成原log已记录的唯一原因。

本轮不重跑、不扩大范围；固定修正候选后交ROOT申请同五ID新窗口，剩余实现行为仍待实测。最新额度14%已用/86%剩余。


## 日期修正后四组通过，安全反例准备修正

`A034-DATE-REPAIR-FIVE-GREEN-001` 固定49e28af4/treeb0d616da，原五ID一次。实际0 failures/2 errors/0 skips：实际补连/字段保护、原baseline重投、写后六类故障/issue/expiry回滚、PG两请求锁等待四完整方法通过。安全方法的两项 RaceEvent反例在准备阶段用QuerySet.update写edition_year/local_date，被现有模型集中身份门禁 ValidationError 拒绝；未到其H03 blocked断言，因此仍非五组GREEN。原log确有 A034_PG_LOCK_EVIDENCE first_pid70/second_pid72/Lock/blocking_pids[70]。worker40.920秒/总窗51.811秒；owner30060/runner30094及进程组gone、flock可重取、Docker0、12源码hash未变。runtime `/Users/mentianlu/.codex/runtime/a034-date-repair-five-green-001`，green-receipt SHA `6b2504a8b030cc07989cdfac28b445ad66b68c906b1ea0510bbc704135695c7a`，13原证据封存；未重跑/扩大。

必要测试技术修正只改该安全方法的准备：RaceEvent取新实例、setattr、save(update_fields)，遵守原validate_event_years/路径集中合同；跨届反例提供现有schema合法的**合成负向跨届证据**（actual_year/原因/HTTPS example.test/approved=True），使模型允许保存，再要求首片仍blocked。这不是现实批准、离线权限或正向source/binding许可，不绕过或mock模型验证；日期错位也同样经save。反例目标和H03拒绝/全状态零写断言保留。原指定RED正向方法、其余所有方法和fixture字节语义不变，service保持49e修正字节原样；共享模型/其他lane未改。

修正后仅静态/原RED方法AST对比/工作流契约/4文档测试/diff检查，业务执行为零。固定修正候选交ROOT申请原同五ID新窗口；局部回归清单仍等五GREEN后提出，不自行执行。


## 同五 GREEN 已通过，待 ROOT 分配精确回归

`A034-SECURITY-FIXTURE-FIVE-GREEN-001` 固定04226d2c/tree769e026f：同五精确ID实际executed一致，5/5 PASS，0 failure/error/skip/意外成功，lifecycle complete/exit0。负向方法声明25种模型变体+缺4强字段+旧as_of/live期限+policy SHA，六类写后故障/内存或持久issue/写后expiry回滚，原baseline重投和字段/计数保护均走到并无子例失败；子例不是独立collector IDs，覆盖枚举依据固定源码与完整方法零error结果，原runner没有另列成功子例。真实PG first_pid70/second_pid72/Lock/blocking_pids[70]，第一applied第二already_applied、单消费。

worker40.159秒/总窗50.607秒，原官方镜像/八controls/资源限制实证；owner33164/runner33192及进程组gone、flock可重取、Docker0，12个唯一源码hash与固定Git bytes复核未变（before有13项含一重复测试项，未虚增唯一文件数量）。runtime `/Users/mentianlu/.codex/runtime/a034-security-fixture-five-green-001`，green-receipt SHA `06356402116e2ee28bf6d4b9dee033ada206c269ddcd471747cd82fd227a8d28`，13原证据hash含rawlog/JSON/subcase声明/PG锁/资源/PID释放。当前仅局部五例GREEN，不是formal/full/独立review/真实来源或生产验证。

提出**23个已有精确方法**回归（5 A032 identity/date、3 H01、4 H02、4 HKJC adapter、5共享career writer/counters、2既有policy/binding），完整ID与每项理由封存在 `/Users/mentianlu/.codex/runtime/a034-five-green-handoff/regression-proposal.json`。均静态核存在于直接类定义，仅方法选取不展开继承/全模块；原五例已在同业务树取得有效Linux证据，无变化不建议机械重跑。正式catalog/core要求由ROOT/C保留，本清单不替代，不改catalog，不把unknown转空/全量。本轮仅提出和申请同边界新窗口，未执行回归。若ROOT要求正式core或不同清单，应以新精确allocation绑定执行。

本 A报告回写为docs-only；service、原测试/fixture及controls与实测04226d2c字节完全一致，局部GREEN不因docs-only状态说明被改写成其他受测SHA。下一步ROOT核证/回归分配/独立review；A无资源占用、不自行发布。最新额度14%已用/86%剩余。
