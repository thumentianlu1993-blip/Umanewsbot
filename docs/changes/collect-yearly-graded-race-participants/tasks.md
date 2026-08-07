# 单年度分级赛全部参赛马研究任务

## 0. Pre-declared hypotheses

- 离线实现 PASS：61 项计划用例对应的新增/受影响自动化测试、synthetic、workflow contract、
  py_compile、YAML 和 diff check 全部通过；任何 invariant/identity/manifest 确定性错误均为
  BLOCKER。
- 正式单年 artifact `outcome=complete`：全部发现 URL 已分类；所有范围内赛事解析成功且至少
  一匹受控状态的实际参赛马；`participant_status_unresolved=0`；强制英文缺失为 0；profile
  transport/unresolved/ambiguous/error 为 0；所有计数不变量成立。目标地区零赛事只有在
  direct labels 或完整 other URL classification manifest 证明后才允许。
- `outcome=partial`：允许生成可审计 artifact，但必须明确列出非零 race retryable errors、
  unresolved participant status、`profile_unresolved`、其他名称/profile issues 或不完整
  other classification；不得写成八地区完整成功。
- `outcome=blocked`：year/region manifest/tool/input/upstream/index/item SHA 漂移、非法
  manifest、coverage/invariant 破坏或无法形成任何可信赛事输入时确定性停止，不生成 final。
- 网络请求预算和各阶段 time budget 在实现 workflow 时冻结到 README/test；达到时间预算只以
  exit 75 安全停止并续跑，不把它改成 partial success。正式网络 run 本 change 尚未授权。

## 探索、规格与审核

- [x] (integration) 核对最新 `origin/main`、主工作区脏状态和旧研究分支提交/文件边界。
- [x] (integration) 审计旧 collector 的年份、地区、前五名、profile、Wikipedia/Wikidata、
  checkpoint 和输出合同。
- [x] (application) 核对公开 RaceEvent/HorseProfile 页面实际暴露的地区、结果和名称字段。
- [x] (integration) 编写 spec、design、test_cases、tasks、rollout。
- [x] (integration) 完成独立方案审核并在同一 reviewer 会话修订至 APPROVED。

## 测试先行

- [x] (integration) 先新增年份、八地区、region manifest、全部参赛状态和名称完整性测试。
- [x] (operations) 先新增 workflow DAG、year input、source-stage 和无 Wikimedia job 静态合同测试。
- [x] (integration) 运行聚焦测试并记录真实 RED。

## 实现

- [x] (integration) 从 `c7cb5d7d` 只移植通用 checkpoint/manifest/HTTP/分片/fan-in 基础层到
  新 collector，不移植旧状态文档或 Wikipedia 实现。
- [x] (integration) 实现必填单 year、自然年范围和跨年 resume 拒绝。
- [x] (integration) 实现八地区/等级规范化、exact URL region manifest 与覆盖状态。
- [x] (integration) 把前五名 parser 改为全部实际参赛马 parser，覆盖非数字状态和 non-starter。
- [x] (integration) 实现 UmaFans-only profile/name 提取、语言证据和 required-English 门禁。
- [x] (integration) 实现 profile shards、canonical merge、review queue 和新 7 文件 finalize。
- [x] (integration) 删除新入口中的全部 Wikipedia/Wikidata host、阶段、字段和输出。
- [x] (operations) 实现简化的 tests → races → profiles → merge → finalize workflow。
- [x] (integration) 编写 region manifest 与新 collector README。

## 验证、审核与发布门禁

- [x] (integration) 将聚焦 RED 转为 GREEN，运行受影响回归、py_compile 和 diff check；
  当前 collector 聚焦回归 `83/83`。
- [x] (operations) 验证 workflow YAML、现有 workflow contract tests 和 synthetic artifact。
- [x] (integration) 由未参与实现的 reviewer 执行首轮原生只读代码 review；结论为 `REVISE`。
- [x] (integration) 修复首轮 `7 P1 + 4 P2` 的 findings 1–11，并完成离线复验。
- [x] (integration) 复用同一 reviewer 会话执行第二轮限定复审；结论为
  `REVISE（2 P1 + 3 P2）`。
- [x] (integration) 修复第二轮的 resume 累计请求预算、暂定赛果门禁、受控别名、搜索分页和
  逐地区 coverage 五项 finding，并完成离线复验。
- [x] (integration) 复用同一 reviewer 会话执行第三轮限定复审；结论为
  `REVISE（4 P1 + 2 P2）`。
- [x] (integration) 修复第三轮的 crash-safe write-ahead ledger、详情地区二次核验、人工审核
  赛果、provisional error/coverage/outcome、HTTP 错误分类和 `errors.json` 名称完整性六项
  finding，并完成离线复验。
- [x] (operations) 补齐 ledger artifact/restore workflow 合同及 hard cancellation 限制说明。
- [x] (integration) 复用同一 reviewer 会话执行第四轮限定复审；结论为
  `REVISE（3 P1）`。
- [x] (integration) 修复第四轮的 pending conflict non-final、profile 缺真实详情名禁止
  fallback、provisional 终态 `evidence_gap` 并继续正式 DAG 产出 partial 7 文件三项 finding。
- [x] (operations) workflow 接受 `evidence_gap`、修正 races index 路径并新增完整离线
  harness；workflow 静态合同当前 `11/11`。
- [x] (integration) 复用同一 reviewer 会话执行第五轮限定复审；结论为
  `REVISE（1 P1 + 3 P2）`。
- [x] (integration) 修复第五轮的真实 `HttpClient` 严格允许受控 `/horses/?q=&page=`、
  coverage error 优先、unresolved 错误保留 region/country/source URL、空 CSV 固定表头四项
  finding，并完成离线复验。
- [x] (integration) 复用同一 reviewer 会话执行第六轮限定复审；结论为
  `REVISE（1 P1 + 1 P2）`。
- [x] (integration) 修复第六轮的受控 ISO alpha-2/alpha-3 国家代码归一化，以及全部未知状态
  行成为终态 `evidence_gap`、保留逐行证据并由完整 DAG 产出 partial 7 文件两项 finding。
- [x] (integration) 复用同一 reviewer 会话执行第七轮限定复审；结论为
  `REVISE（2 P1 + 2 P2）`。
- [x] (integration) 修复第七轮的 index/request ledger 权威且 progress 可安全重建、共享
  profile URL 逐 occurrence identity 校验、`region_unresolved` 进入
  source/errors/partial coverage、Middle East 同 region 仍逐 country 冲突检查四项 finding。
- [x] (integration) 复用同一 reviewer 会话执行第八轮限定复审；结论为
  `REVISE（2 P1）`。
- [x] (integration) 修复第八轮的统一 stage monotonic deadline、discovery
  queue/visited/discovered/inflight 精确 checkpoint/resume、profile 分页 deadline 与后续页
  404 fail-closed。
- [x] (operations) workflow 合同锁定 discovery progress/request ledger 即使无 run manifest
  也必须上传恢复；workflow 静态合同保持 `11/11`。
- [x] (integration) 复用同一 reviewer 会话执行第九轮限定复审；结论为
  `REVISE（P0=0 / P1=0 / P2=1）`。
- [x] (integration) 修复第九轮唯一 P2：discovery retryable 错误重试耗尽后保存精确
  progress/request ledger 并 exit `75`，resume 从 inflight URL 精确继续；确定性 4xx 保持
  permanent。
- [x] (integration) 复用同一 reviewer 会话执行第十轮限定复审；结论为
  `REVISE（2 P1 + 1 P2）`。
- [x] (integration) 修复第十轮的 sitemapindex/urlset 类型与目标年份过滤、generic `other`
  profile 多语 alias 交集加附加 identity、coverage 只由实际 in-scope graded 证据驱动且
  Listed-only 不得 `covered` 三项 finding。
- [x] (integration) 复用同一 reviewer 会话执行第十一轮限定复审；结论为
  `REVISE（P1=1）`。
- [x] (integration) 修复第十一轮唯一 P1：AU/DE generic `other` 可由 alias 交集加出生年份
  满足附加身份，详情存在 country 时必须一致，Middle East 仍强制 country。
- [x] (integration) 复用同一 reviewer 会话执行第十二轮限定复审；结论为
  `REVISE（P1=1）`。
- [x] (integration) 修复第十二轮唯一 P1：direct/search 共用公共 group validator，逐
  occurrence 校验 alias/region/country/birth year，任一冲突整组 fail closed 并保留 review。
- [x] (integration) 复用同一 reviewer 会话执行第十三轮限定复审；结论为
  `REVISE（1 P1 + 1 P2）`。
- [x] (integration) 修复第十三轮的 canonical group 全 aliases 确定性多 query、候选按
  canonical profile URL 去重，以及冲突 error 保留 expected/actual 双侧
  aliases/region/country/birth 与 profile URL/conflict fields 两项 finding。
- [x] (integration) 复用同一 reviewer 会话执行第十四轮限定复审；结论为
  `REVISE（1 P1 + 1 P2）`。
- [x] (integration) 修复第十四轮的 profile URL 全链路严格 canonical trailing slash，以及
  Middle East country missing/uncontrolled/mismatch 保留 expected/actual 双侧事实和明确
  reason 两项 finding。
- [x] (integration) 复用同一 reviewer 会话执行第十五轮限定复审；结论为
  `REVISE（P1=1）`。
- [x] (integration) 修复第十五轮唯一 P1：profile URL 按原始 path 只接受正整数真实路由，
  拒绝重复 slash、slug、dot/编码绕过等，并把 synthetic 改为合法数值 ID。
- [x] (integration) 复用同一 reviewer 会话执行第十六轮限定复审；结论为
  `REVISE（P1=1）`。
- [x] (integration) 修复第十六轮唯一 P1：profile URL 基于原始 `str` 严格校验，不先做
  NFKC/trim，拒绝 Unicode whitespace/control、全角字符和 percent encoding 等绕过，只接受
  ASCII 正整数路由，并在全部身份入口一致执行。
- [x] (integration) 复用同一 reviewer 会话执行第十七轮限定复审；结论为
  `REVISE（2 P1）`。
- [x] (integration) 修复第十七轮两项 P1：所有 profile URL 原始字段不预先 normalize；
  HTML profile `href` 使用严格 resolver；HTTP profile 请求禁用自动 redirect，对原始
  `Location` 严格解析并限定同 host，final URL 直接执行严格校验。
- [x] (integration) 复用同一 reviewer 会话执行第十八轮限定复审；结论为
  `REVISE（P1=1）`。
- [x] (integration) 修复第十八轮唯一 P1：absolute profile href、redirect `Location` 与
  final URL 必须和对应 source/request hostname 精确一致，禁止 allowlist 内 bare/`www`
  hostname 相互切换。
- [x] (integration) 复用同一 reviewer 会话执行第十九轮限定复审；结论为
  `APPROVED（P0/P1/P2=0/0/0）`；该结论现仅作为历史审阅快照。
- [x] (integration) 更新 current_state、project_status 和本 change rollout 候选状态。
- [x] (integration) 对五文档写回后的完整差异执行第二十轮最终确认；结论为
  `REVISE（P2=1）`。
- [x] (integration) 修复第二十轮唯一 P2：标准五地区 region 明确匹配时允许 profile country
  缺失，存在 country 冲突仍 fail closed；AU/DE/Middle East 不放宽。
- [x] (integration) 复用同一 reviewer 会话执行第二十一轮最终确认；结论为
  `REVISE（P2=1）`。
- [x] (integration) 修复第二十一轮唯一 P2：country fact 显式区分
  missing/controlled/uncontrolled，非空未知值不再按 region 回填并 fail closed；标准五地区
  仅 missing 可按明确 region 通过，AU/DE/Middle East 不放宽。
- [x] (integration) 复用同一 reviewer 会话执行第二十二轮最终只读确认；结论为
  `APPROVED（P0/P1/P2=0/0/0）`，批准 fingerprint
  `21a32cf22ef48207d44880d21ec2059ccdd711fe6758a80ee60cb069277f61ce`。
- [x] (operations) 用户授权后完成 feature commit
  `34626865d5cfe336a97fd7a375238e76c8afbec2`、push、PR #50、merge
  `d47dd513e666874243815c2feee7cc755ce483ba`。
- [x] (operations) default `main` 执行 `full_network=false` workflow run `30555834994`；
  conclusion=`success`，离线 artifact 已核验，完成本变更定义的生产部署。
- [x] (operations) 只读核验服务器与公网 healthz；因 `/opt/umanewsbot` 长期 dirty 且本变更无
  Django runtime/DB 变化，未 pull、重建、重启、迁移或备份，服务器 HEAD 保持 `be1c89bf`。
