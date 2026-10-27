# P02 来源能力盘点（2026-10-27）

本次新增地区研究遵循用户限定：免费、无会员、无付费墙；仅逐个公开入口有界取样，没有开启真实轮询。HTTP 200、可解析或已有历史脚本，均不等于来源已具备生产自动化权限、五类能力与 5/10 分钟容量。

访问证据见 [source-probes.json](source-probes.json)：URL、UTC 取样时刻、状态、字节数与原始 SHA256。解析结果见 [source-parse-report.json](source-parse-report.json)。原始 HTML 保留在本地 `/tmp/p02-lifecycle-20261027/sources/`，未把第三方整页与脚本提交进仓库。

| 地区/来源 | 赛程/名单/退赛/结果/更正证据 | 本次结论与缺口 |
|---|---|---|
| 日本中央 JRA | 已保存明确「出馬表」及完整结果样本；真实 producer → identity → writer → epoch → reader 的离线回归通过。更正/冲突/非完赛/并列使用独立合成异常回放 | 首区离线候选。真实首发时钟、全追踪库存请求额度、自然赛日、真实更正样本仍 UNKNOWN |
| 日本地方 NAR | 既有 parser/地区 fixture 回归；与中央独立身份合同 | 未完成本期真实赛日与全部能力验证 |
| 香港 HKJC | 既有地区 parser/fixture；逐来源准入和完整性检查复用 | 未完成本期确定名单/更正与 runtime 容量验证 |
| 英国/爱尔兰 Sporting Life | 既有名单/结果 parser、跨语言身份回归 | 未证明所有名单具有最终申报语义；缺真实更正/首发时钟和完整容量 |
| 法国 ZEturf（既有参考入口） | 既有结果 parser/fixture，拒绝非平地赛类型 | 仅参考 parser 可复用；本期目标赛事覆盖、确定名单与更正未核验。候选池中的 Geny/France Galop 等仍待逐赛样本 |
| 美国 Horse Racing Nation | 既有结果 parser/fixture，名称和场次联合约束 | 不能从摘要或不完整结果晋级；确定名单、完整更正和时效能力待证 |
| 澳大利亚 Racing Australia | 免费 Results.aspx 实取 200；复用历史纯解析器，对 Kembla Grange 2026-07-25 第1场解析 11 个名单行、7 个名次行 | 有完整结果候选结构；还需逐一确认其余行退赛语义、最终名单及修订发现。未接入 P02 常驻生产 adapter，未证明高频额度 |
| 德国 Deutscher Galopp / GaloppOnline | 官方结果索引直接访问 403，已停止；GaloppOnline 200，但结果内容是指向同一受限官方入口的 iframe | 没有通过更换代理/登录/参数绕限制；不能把镜像入口当独立来源或已可抓。现有历史 fixture 不是当前可访问证明 |
| 阿联酋 ERA | 免费赛事页 200，页面有官方 Declarations 标记；按页面及公开 bundle 指定的 `/ajax/racecard-declarations` 请求得到 1 张表、12 行 | 有最终名单候选。样本是阿拉伯马赛事，不代表本期纯血马目标覆盖；结果、退赛、更正、身份映射与请求额度仍待证 |
| 沙特 JCSA | 免费新页面及已有公开 `api/meeting-info/.../Results/True` 均 200；Saudi Cup 历史页解析 14 行、13 个正式名次 | 第14行未完赛语义、赛名缺失需联合赛程身份；新赛程名单入口转到公开 Issuu 页面，尚未证明可稳定机读；没有接入会员或付费资源 |

首区选择以现有 JRA 完整离线链为依据；**目前没有一个地区被声明为已真实验收或达到 SLA**。AU/DE/AE/SA 的新常驻 adapter 不以旧历史修复脚本冒充完成。九地区路线合同和 fail-closed 能力/额度报告已实现，缺口保留，不提高原 R11 卡进度。

容量工具必须输入冻结的真实目标清单（含缺源/未匹配目标）、各来源逐能力证据、实际 host 预算及有效期；没有证据时 `runtime_verified` 必须为 false。全量请求回退按重点 60 秒、其他 120 秒，计入全部七天库存及至少 30% 余量。生产 manifest 为空，因此本轮没有生成任何真实网络请求授权。
