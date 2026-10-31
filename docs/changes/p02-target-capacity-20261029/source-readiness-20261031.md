# P02 小范围来源准入与历史处置候选（2026-10-31）

本轮先补齐固定代码提交的目录外交付核验，再核对一个已有身份候选（NAR 门别 event199）的用途/额度与解析边界，并刷新既有19场已纳管未完成赛事。只做只读诊断、离线验证和处置候选，不修改生产、来源合同、解析器或调度。人工确认统一引用根 [AGENTS.md](../../../AGENTS.md)。

## 固定代码交付缺口已关闭

`8790c1b1faadd364acafd9fe31623b6931267c32` / [CI 40841675640](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/40841675640) 的完整测试为7,002项、51批、零失败批次和零skip；2026-10-31目录外受信校验器返回 `verified`。测试树 `77d2e2cec99ace2e42cdc7b52f7b8f48e2683027`，merge/test提交 `301092d324290bfa774c9ab0dc79169a338c8a95`。收据 `/Users/mentianlu/.codex/artifacts/p02-capacity-20261029/delivery-receipt.json`，SHA256 `6c597c8909be9ec560955f17890f3de81b1572569aec98d7ec3968b0ee45e8c3`。

此前本地Docker存储模式导致按摘要读取失败，已仅修正专用Colima profile；本轮确认overlay驱动，重新下载同轮产物，完成实际镜像与独立测试ID核对。未修改校验器或降低校验条件。该收据只绑定上述代码提交；本轮后续文档提交的检查另行记录，不能冒充新head收据。

## NAR单场准入结论：仍阻断

选择已有候选event199（2026-10-29门别11R、エーデルワイス賞），避免扩大采集范围。本轮没有重新抓取赛事或读取付费/会员页面；只复核10月29日已保存卡页和公开条款。并未完成NAR全地区覆盖或新SP适配器。

| 项目 | 本轮证据 | 结论 |
|---|---|---|
| 身份 | 缓存可见日期、门别、11R与赛事名；自然键为2026-10-29/baba36/race11 | 保留候选；届次29不作场次 |
| 路由与解析 | 当前桌面fixture合同为www.keiba.go.jp及/KeibaWeb/；缓存为sp.keiba.go.jp及/KeibaWebSP_IPAT/ | 离线permits_url=false；既有桌面日期/场次正则不匹配，不能直接绑定 |
| 用途 | [NAR利用规约](https://www.keiba.go.jp/terms.html)写明转载/复制需事前许可；异常访问可能被封锁 | 未取得本项目自动获取/加工/展示用途的许可证明，不将匿名可读等同许可 |
| 额度与成本 | 本轮所读条款未给出数值请求额度；没有完整SP请求链和共享host负载证据 | quota_verified/request_costs_verified继续未证明，不填写零或猜测额度 |
| 能力与覆盖 | 单场旧卡页不证明实时退赛、完整赛果、更正、全地区目录或时钟 | runtime_verified保持未证明；不可生成有效生产manifest |

条款适用范围表述为该信息站全部公开信息，但本报告不据此作法律结论，也不将其解释为所有自动访问一概禁止；这里只判定现有证据不足以满足本项目准入合同。条款原文一次匿名请求200：2026-10-31T04:00:14.108712+00:00，18,233字节，SHA256 `d6327cf2afd9b8cc8120a3dc09f1cf16f473919f2e8891a4c590df2bc4e8e826`。未联系来源方、未发消息。

离线探针读取旧缓存SHA256 `bb290d515c66828a192c1a1af0078a38a6c79cebd31a674600956851fdca5c91`，禁用socket连接；身份四项均可见，现有桌面路由及header合同两项拒绝。探针只证明兼容性缺口，不是生产完整解析验收。首次探针因替换socket类破坏SSL导入而失败；改为禁止connect后完成，未将该基础设施错误当作产品RED。

## 19场运行态：有持续尝试，但结果合同被拒绝

生产只读快照 `2026-10-31T03:59:44.336667+00:00`，细查 `2026-10-31T04:01:59.077110+00:00`，应用提交仍为 `ad50abdb74b89669ab8ada2958b040877c1a1849`。查询使用REPEATABLE READ READ ONLY、单语句8秒，未改任务、配置或业务数据。全部19场仍为enrolled/enforce、公开赛果0行、tracking_enabled=true、awaiting_result；写入owner=data_sync。

旧control的last_result_code=enforce_applied且next_refresh_at为空，不表示当前没有同步任务。实际tracking和provider checkpoint持续尝试；19个result checkpoint均为source_runtime_contract_rejected。原有source identity仍是TRA，authority_version=1，没有本轮多来源binding；这是现状，不将v1无binding本身当作缺陷。

| event | 地区/当地赛日 | 连续失败（快照） | 最后成功时间UTC（不等于完整赛果） | 处置候选 |
|---|---|---:|---|---|
| 785 | france / 2026-10-10 | 517 | 2026-10-27 14:24:00.538803+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 790 | france / 2026-10-25 | 695 | 2026-10-27 12:10:22.637974+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 791 | france / 2026-10-25 | 665 | 2026-10-27 15:32:40.257143+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 839 | france / 2026-10-17 | 505 | 2026-10-27 15:52:35.067518+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 840 | france / 2026-10-17 | 525 | 2026-10-27 13:32:38.446455+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 841 | france / 2026-10-17 | 499 | 2026-10-27 16:45:31.677704+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 977 | united_kingdom / 2026-10-03 | 516 | 2026-10-27 14:34:35.143338+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 978 | united_kingdom / 2026-10-03 | 507 | 2026-10-27 15:34:02.905622+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 979 | united_kingdom / 2026-10-03 | 520 | 2026-10-27 14:04:53.060113+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 980 | united_kingdom / 2026-10-09 | 701 | 2026-10-26 17:36:00.268214+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 981 | united_kingdom / 2026-10-09 | 516 | 2026-10-27 14:33:04.968510+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 982 | united_kingdom / 2026-10-09 | 701 | 2026-10-26 17:36:00.446195+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 983 | united_kingdom / 2026-10-09 | 519 | 2026-10-27 14:15:17.737025+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 984 | united_kingdom / 2026-10-09 | 519 | 2026-10-27 14:15:17.551827+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 985 | united_kingdom / 2026-10-10 | 700 | 2026-10-26 17:44:34.083433+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 988 | united_kingdom / 2026-10-10 | 518 | 2026-10-27 14:24:00.358129+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 993 | united_kingdom / 2026-10-24 | 674 | 2026-10-27 14:25:34.855826+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 994 | united_kingdom / 2026-10-24 | 674 | 2026-10-27 14:25:36.471441+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |
| 995 | united_kingdom / 2026-10-24 | 672 | 2026-10-27 14:40:09.160084+00:00 | 保留义务；核实合同证据或准备免费替代来源，未执行 |

合同诊断仅读取registry和固定白名单字段，未读取密钥文件、未调用TRA、未触发同步。19条source.registry_digest均匹配当前配置roster；registry文件SHA匹配配置，valid_until=2026-12-31T23:59:59+00:00、automation_allowed=true。实际只读校验仍拒绝，原因是 `source registry evidence is stale`：evidence.verified_at=2026-09-26T17:15:00+00:00，代码要求不超过31天，新鲜度边界为2026-10-27T17:15:00+00:00。

这证明一个当前可复现的充分阻断条件，不证明历史所有失败均只由该条件导致。不得直接改verified_at、重算摘要或延长有效期冒充重新验证；也不能以数据库旧approval证明当前合同通过。受用户免费/无需会员约束，本轮不恢复TRA调用。具体生产修复或停用必须有目标、证据、回滚和执行边界，不能由本报告自动触发。

## 其他义务和时间边界

- 用固定10月29日起算窗口重读10,215场，原历史分类ID集合无增减：9,995有旧赛果未纳管、119无赛果未纳管、19在管无赛果、1临时发布不一致；10,114条legacy义务继续UNKNOWN。这里只证明这份基线集合，不声称当前全站义务已完整核实。
- 9,995条的处置候选：按既有来源及导入证据分批证明完整终态/版本/发布后再建议归档；不能将默认is_confirmed=true当作免除义务。119条的处置候选：先核对身份、赛日与取消依据；其中2条cancelled也不能直接关闭。均不自动启动高频历史轮询。
- event924仍需修订/发布一致性核对。本轮发现保存过bha_manual的official observation，但公开修订是provisional；观察存在不等于该版本已完成仲裁/发布，候选是审核证据链，不直接晋升official。
- event116/117现有最早official修订/发布支持原观察起点，截止分别为2026-10-31 07:13:00.178156 UTC、2026-11-01 08:09:04.847924 UTC；不能因本轮检查重新开始七天。过窗后仍保留可接收明确更正的规则，未证明完成连续自然观察。
- 原“未来81场”是10月29日基线，不是10月31日新的滚动28天分母。其中199、549–553、20565、20614共8场赛日已经过去；不得删出未完成库存，亦不能继续称其为未来目标。103条工作候选只作固定基线，完整动态库存仍未证明。

## 下一步与阻断

本轮交付核验已补齐，来源准入尚未闭合。下一步应先取得覆盖自动获取、加工/展示及请求预算的来源证据，或选择已有充分许可证明的免费替代来源，再推进解析适配和逐场绑定；不能先扩大SP白名单或调低频率就宣称许可问题解决。19场保留逐场处置候选，任何恢复/暂停/替换均未执行。P02受保护执行器及隔离恢复演练仍是后续工程事项，不能代替来源/容量准入。

## 固定证据

以下文件保存在本机artifact目录；交接时应取得同SHA文件，文件名不能代替证据。报告只含业务状态与摘要，不含凭据、raw错误或密钥路径。

- `/Users/mentianlu/.codex/artifacts/p02-source-readiness-20261031/obligations.py`：SHA256 `808573a5661a12dd46f667f557aafc441b614b8d83cb7c94ddc44d525db3ba07`。
- `/Users/mentianlu/.codex/artifacts/p02-source-readiness-20261031/obligations.json`：SHA256 `de391130ad9c1ddb0cf9ff0f873502d04e207986f2113b82eb2e6d692f0f4971`。
- `/Users/mentianlu/.codex/artifacts/p02-source-readiness-20261031/managed_detail.py`：SHA256 `99599318e23c50a3da4ad87b8877d0587e7200a12aef4580cd1d27d86a4d269f`。
- `/Users/mentianlu/.codex/artifacts/p02-source-readiness-20261031/managed_detail_with_reason.json`：SHA256 `7013dc67488303bde29173d4372259de7a09752759151b40a49458492003fdff`。
- `/Users/mentianlu/.codex/artifacts/p02-source-readiness-20261031/contract_diagnostic.py`：SHA256 `bfa02ac7263152cbde9e4af40e57c640881b0d5157300939aa3391cf6d80acfb`。
- `/Users/mentianlu/.codex/artifacts/p02-source-readiness-20261031/contract_diagnostic_final.json`：SHA256 `34aae79456b46e8803452c5358742c2170252ba8b791c598d3d920f44e6303c1`。
- `/Users/mentianlu/.codex/artifacts/p02-source-readiness-20261031/nar_offline_binding.py`：SHA256 `714be33c445bd9994bd7871eb6dde3ab8e42e0caee1ba8ee5f1baac2d78ce0d5`。
- `/Users/mentianlu/.codex/artifacts/p02-source-readiness-20261031/nar-offline-binding.json`：SHA256 `d2c897200fe3e65914ec2e195680cf2bf95b2bc7eb21b1621ef66f4d27770383`。
- `/Users/mentianlu/.codex/artifacts/p02-source-readiness-20261031/sources/manifest.json`：SHA256 `76b0448dc0b3215ee853e42121156d38f3f5b9c478f5752415f1a95cf4c43f20`。
- `/Users/mentianlu/.codex/artifacts/p02-source-readiness-20261031/sources/nar-terms.html`：SHA256 `d6327cf2afd9b8cc8120a3dc09f1cf16f473919f2e8891a4c590df2bc4e8e826`。

## 验证与评审

本轮10份原始证据引用及固定代码交付收据SHA核对通过；19行追踪、结果checkpoint、历史四类ID集合与8场已过赛日核对通过。workflow contract PASS、4项契约检查及git diff --check通过。本地相对8790c1b1影响计划为docs-only、0 labels；这是本地诊断，不替代新head CI。

独立子Agent及原生只读评审均PASS，无actionable finding，原生退出0；审前后指纹一致：`5f45f572c0c07ac89a5f6bcddf782ae2e6c300e04370ce453d36ea3178220a01`。日志`/tmp/p02-readiness-native-review.log`，SHA256 `2c6152cbc1e05d6903db3273e5ccd1d25ff45763fcb958b759b5a44757c585a3`。审核后仅回写本段与tasks评审勾选，另交原reviewer聚焦核对。来源准入和生产冻结仍BLOCKED。
