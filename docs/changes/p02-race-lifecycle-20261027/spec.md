# P02 九地区赛事可信自动更新：实施规格

## 状态与依据

- 2026-10-27 产品访谈及方案评审已完成；用户随后授权测试先行开发和子 Agent 独立实现评审，明确不合并、不部署。实际实现边界见 [implementation.md](implementation.md)。
- 代码基线：`e4df6bdaf85318eb9588489807e4b9a40bb01665`；独立分支 `codex/p02-race-lifecycle-design-20261027`。
- [原始交接规格](../business-project-handoff-20261026/02-race-lifecycle/spec.md)及其 26 张卡保留原文、百分比和历史事实。本目录细化本次实施，访谈的新决策取代旧建议，不提高原卡进度。
- 已执行隔离 PostgreSQL 回归和有界免费公开来源取样；真实自动化用途、请求额度、生产运行态、CI、自然赛日仍未验证。来源页面存在不代表适配器可用。
- 人工确认仅按[根 AGENTS.md](../../../AGENTS.md)执行。

## 已确认的产品规则

| ID | 行为与验收 |
|---|---|
| S01 | 日本、香港、英国、爱尔兰、法国、美国、澳大利亚、德国、中东九地区；中东本期仅阿联酋、沙特，其他国家后续处理。各地区独立验收、分批交付。 |
| S02 | 全部 G1/同等级（含 JpnI、J-G1）及人工指定赛事为重点，可信确定资料发布后 5 分钟内公开更新；其他目标赛事 10 分钟。 |
| S03 | 官方、商业 API、合格专业媒体均可直接确认；一个合格来源即可。赛事身份、该项能力、完整性、成熟度和版本新鲜度必须成立。不能要求所有媒体等待官方。 |
| S04 | 名单有“预想/确定”，赛果有“待确认/已确认”。预想名单在有效开赛前 30 分钟隐藏；待确认赛果在有效开赛后 60 分钟隐藏，显示“资料更新中”，继续补查。确定资料不受此临时资料截止限制。 |
| S05 | 两个合格来源的关键事实冲突且不能裁决时，隐藏受影响的整张名单或赛果表，显示“资料核实中”；其他无冲突内容保留。明确后续更正可直接更新。 |
| S06 | 延期、改期、取消、退赛、非完赛、并列必须识别。有效改期重算未来截止、作废旧任务；时间到达本身不能证明开赛或完赛。 |
| S07 | 首次确认赛果后主动追踪 7×24 小时：首日较密集、其后每日复查。窗口后仍接受明确更正；更正不重置窗口以制造无限高频轮询。 |
| S08 | 按场次关键资料计错，严格 <1%；应推进赛事任一阶段超时计一次卡顿，严格 <3%，包括来源缺失。占位提示不算更新成功。 |
| S09 | 一个地区异常回放通过且至少一个完整真实赛日全流程通过，可小范围交付；随后观察 7 天。样本不足不宣称长期达标。 |
| S10 | 重估工期，不沿用 10 月 30 日硬截止。干净独立 worktree、独立分支，复用已有成果。 |

## 目标赛事集合与缺失语义

本期围绕现有公开 canonical 赛事日历和本次批准的地区目标清单运行；不是自动抓取九地区所有级别比赛。实施第一步导出完整目标清单，包括尚未建成 canonical 的待匹配条目，记录 region、country、当地赛日、来源身份、重点依据和覆盖窗口。现有日历缺漏由覆盖审计列出，不能以“未建档”删除分母。新增全级别扫描另行处理。

中东清单必须拆 AE/SA；日本分别标中央/地方/障碍，各地按现有日历赛事类型记录。重点是已在目标集合中的赛事优先级，不是把所有目标缩成 G1。未确定时间只展示当地赛日，不能补 00:00。日期赛没有精确开赛时刻时不计算虚构的 ±30/60 分钟；使用来源可用后的 5/10 分钟期限，同时以当地赛日结束后 60 分钟作为独立的“赛日资料缺失”检查点，明确这是技术兜底而非实际开赛时间。

清单在赛日前冻结基线，后发现的漏项追加并保留发现时间；不能通过改名单、撤公开或切源抹除历史错误/超时。无赛事地区标无样本，不能标验收完成。

## 资料合格条件

- 赛事匹配使用 provider race ID 与 canonical 映射、当地日期/场地/场次等证据；只靠同名不能自动合并。
- 确定名单必须覆盖全体申报参赛者及已知退赛，马匹身份可区分，来源明确为最终申报/确定名单。来源缺少确定语义时仍为预想。
- 已确认赛果必须覆盖全部应核验参赛者的名次或退赛/未完赛/失格等状态；只有前三/前五、摘要、普通战报不能晋级。并列保留相同名次，展示顺序独立。
- 时间、赛事身份、名单/退赛、名次和完赛状态是关键资料。赔率、奖金、分段等非核心缺失不阻塞；有展示的骑师等字段不能凭推断补值。
- 确认属于资料成熟度；内部旧枚举 official 不代表数据一定来自官方。来源身份与成熟度分别保存。
- source updated time 缺失不等于不可信：用前次无此版本与首次见此版本的观测区间，并校验版本内容；不能伪造精确首发时间或把抓取时间当首发。
- 相同原始数据的镜像不是独立佐证，但可提供替代访问渠道。关键冲突不能由站点优先级或抓取先后直接覆盖。

## 来源池

以下来源沿用本次访谈确认的候选池。每个“地区×赛程/名单/退赛/结果/更正”格分别验证；网站级列入不等于全部能力可用。每格状态为待核验/回放可用/真实验证可用/受限/不可用，保留主源、备源或明确缺口。

| 地区 | 官方及基础来源 | 专业来源池（实际提供该场完整内容才可用） |
|---|---|---|
| JP | JRA、NAR；TRA 按实际覆盖 | netkeiba、競馬ブック、競馬ラボ |
| HK | HKJC；TRA 按实际覆盖 | SCMP HK Racing、Racing and Sports、Breednet |
| GB | BHA 等官方入口；TRA | Racing Post、At The Races、Sporting Life、Racing TV、Racing and Sports |
| IE | HRI 等官方入口；TRA | IrishRacing、Racing Post、ATR、Sporting Life、Racing TV、Racing and Sports |
| FR | France Galop；TRA 按实际覆盖 | Geny、Racing Post、ATR、Racing TV、Racing and Sports |
| US | Equibase；TRA 按实际覆盖 | DRF 详细 Chart、TDN 完整结果块、Racing Post、ATR、Racing and Sports |
| AU | Racing Australia 及州级官方；TRA 按实际覆盖 | Racing and Sports、Breednet、Racing Post、ATR |
| DE | Deutscher Galopp；TRA 按实际覆盖 | GaloppOnline、Racing Post、ATR、Geny |
| ME: AE/SA | ERA、JCSA；TRA 按实际覆盖 | Racing Post、ATR、Racing TV、Racing and Sports、TDN |

待补完整样本且不能宣称已接通：日本 Sponichi；英爱 Timeform；法国 Paris-Turf、Equidia、Turfomania、CanalTurf、Turfoo；美国 BloodHorse、Horse Racing Nation；澳大利亚 Racenet、Punters、Racing.com。TRA 已购买不证明套餐覆盖、速率或再展示权。禁止绕过登录、付费墙或访问限制。

本次访谈查阅入口（作为研究线索，接入时重新取具体比赛样本与用途凭据）：[netkeiba](https://race.sp.netkeiba.com/?pid=payback_list)、[Keibabook](https://stest.keibabook.co.jp/cyuou/seiseki/202604040801)、[KeibaLab](https://www.keibalab.jp/db/race/202610120508/raceresult.html)、[SCMP](https://www.scmp.com/sport/racing/race-result/archive)、[Racing Post](https://www.racingpost.com/results/)、[ATR](https://www.attheraces.com/results)、[Geny](https://www.geny.com/course/1638471-2026-03-20-le-croise-laroche-prix-de-lambersart/arrivee-rapports)、[DRF](https://www1.drf.com/StakesResults/MainMenu.do)、[TDN](https://www.thoroughbreddailynews.com/pdf/tdn/tdn260525.pdf)、[Breednet](https://www.breednet.com.au/results/daily-results)、[GaloppOnline](https://galopponline.de/statistiken-ergebnisse/)。

## 质量与时效口径

报告分地区、重点/常规、当日及滚动 28 天，并保留历史失败：
- N：窗口内按清单应服务的去重赛事；延期/取消仍保留，已确认取消以取消信息正确公开作为完成，不再要求赛果。
- E：其中公开关键事实曾经错误的赛事数，一场多错只计一次；后来修复不抹去当窗错误。
- U：关键资料无法完整审核的场数；分别报来源缺失、身份缺失、未审。报 E/N 与可审核样本中的错误率，U>0 不得把未知当正确宣称全范围达标。
- D：至少一个业务资料义务已到期的赛事数；L：其中任一义务超时未公开完成的赛事数。L/D <3%；占位、冲突和缺来源都可能计入。D=0 显示无到期样本。
- 有可靠首发时刻 t：公开探针见目标版本 p，p−t ≤300/600 秒。仅有首发区间 [a,b]：时延在 [p−b,p−a]，保守上界达标才记证实达标；区间跨线记不确定，不冒充成功。
- 临时资料截止亦是义务到期点；无来源时同样计卡顿。延期只调整未到期义务；已发生的超时保留。页面隐藏是否及时另计，不能替代资料更新时效。
- 统计长期达标需完整覆盖与足够样本。7 天报告可如实报零错误，但不等于证明长期 <1%。回放样本与自然样本不能混合。

## 范围外

不恢复旧 8 线调度，不重做 Django/Celery，不推进后台改造或 QQ，不自动购买/扩抓，不重写新闻/履历消费者。P03/P04/P05 只接收稳定的结果版本接口；不在本项目重复实现。历史修复先审计原 R09 清单，生产修改另绑具体清单，不全站盲目重写。
