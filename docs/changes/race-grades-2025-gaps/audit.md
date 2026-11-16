# 42 场等级与 11 项年度目录对账

2026-11-16 只读生产快照；当前未应用生产。42 条等级输入包含英国 2026 年 20 场 Premier Handicap、香港 19 场繁体等级、香港 2027 年 3 场四岁系列。只修正显示与等级筛选；不批量改写这 42 条原始事实。

| 年度目标 | 已有 event | 比赛 | 结论与动作 |
|---|---|---|---|
|60648|20875|Dick Poole|13 行名单、11 行赛果已有；补目录关联|
|74321|20873|Remsen|12 行名单、11 行赛果已有；补目录关联|
|74385|20876|Commonwealth Cup|7 行名单、6 行赛果已有；补 1 条 PU 赛果及目录关联|
|74382|20877|Temple Gwathmey|8 行名单、8 行赛果已有；补目录关联|
|74384|20878|Colonial Cup|9 行名单、7 行赛果已有；补 2 条 F 赛果及目录关联|
|74276|20879|Noel Laing|7 行名单、7 行赛果已有；补目录关联|
|60625|20880|Classic Chase|2025-01-11 冰冻取消，目录 cancelled/ready，草稿保持|
|74077|20881|Brooklyn|2025 未办，目录 not_held/ready，event=null|
|74108|20882|Cougar II|2025 停办，目录 not_held/ready，event=null|
|74326|20883|Robert J. Frankel|按用户口径 2025 不存在；not_held/ready；不改 2026、不记录延期|
|74389|20884|Tokyo City Cup|旧取消误标；补 2025-10-25 四匹完整名单和赛果，同事务转 finished/published|

六场来源与原有 56 行名单、50 行赛果逐项核对。进一步直接审核 NSA 原件发现原解析器遗漏 3 条未完赛赛果：Commonwealth 的 BELFAST BANTER 为 PU，Colonial 的 LITTLE TRILBY 与 COOL JET 为 F；补 3 条正式名次为空的赛果并同步三条既有名单状态。Remsen 的 Probably Dreaming 经 NYRA 官方明确列为 Scratches，Dick Poole 两匹为 NONRUNNER。未完赛与未出走严格区分。Tokyo 次序为 Privman、Pony Express、Gaming、Mining District，比赛为一英里无分级赛。保留原 event ID、slug，不新增重复赛事。

## 来源与证据

- 六场原始来源：Sporting Life Dick Poole 878548、HRN Aqueduct 2025-12-06 第 9 场、NSA 四份官方 PDF。原件 SHA 绑定在数据清单中，逐行重放记录为私有运行目录 `source-audit.log`。
- [Classic 取消赛日](https://www.sportinglife.com/racing/results/2025-01-11)：Warwick 冰冻取消。
- [NYRA 官方回顾](https://www.nyra.com/belmont/news/2026-stakes-schedule-for-belmont-park-fall-meet-out-now/)：Brooklyn 前次举办于 2024，2026 回归，核实 2025 未办。
- [CHRB Del Mar 2025 申请](https://www.chrb.ca.gov/DocumentRequestor2.aspx?Category=MTGAGENDAITEMS&DocumentID=00052295&SubCategory=)：明确 Cougar II 暂停以平衡奖金预算。
- [Santa Anita 官方赛前](https://www.santaanita.com/news/grade-ii-twilight-derby-giii-autumn-miss-and-tokyo-city-cup-highlight/)、[官方稿件转载赛果](https://pastthewire.com/privman-finds-second-wind-in-tokyo-city-cup/)、[Sporting Life 完整赛果](https://www.sportinglife.com/racing/results/2025-10-25/santa-anita/886826/race-2-tokyo-city-cup-stakes)：同日、同赛场、同赛名和四匹编号匹配，完整来源状态 WEIGHEDIN；不补造缺失的落后距离。

来源与生产快照留在仓库外 `/Users/mentianlu/.codex/runtime/race-grade-coverage-20261116/`；不将第三方网页全文或生产运行字段提交仓库。发布清单的完整 SHA 见最终 rollout，清单漂移必须重新演练。

## 已执行诊断

- 42 条等级真实 RED 后 GREEN；SQLite、PostgreSQL 等级/页面各 45 项通过。
- 目录工具原 7 项失败已修复：关系字段 save 使用 field name，派生 series_key 与数据库和收据保持一致。
- 独立审核两项反例真实 RED：字段级人工锁、已有名单/赛果不完整。返修后工具 12 项通过，包括批次中途失败原子回滚与命令 SHA 校验。
- Linux PostgreSQL 16、断网、只读源码、1 CPU/2 GiB、独立临时数据库组合 57 项通过；精确 11 项 dry-run/apply/replay/restore/replay 完成，原有 50 条赛果守恒、新增 Tokyo 4+4 行及 NSA 3 条未完赛结果、公开页 HTTP 200，2026 哨兵保持。诊断镜像初始 SQL_ASCII 配置错误已修为 UTF8；不把环境失败计为应用缺陷。
- 固定树范围 CI、审核复查与生产交付状态另见 rollout。

第二轮审核发现 NSA 非完赛遗漏，前次 54 行演练仅是中间结果，已撤销完整性结论。新增 PU/F 不可当非出走的真实 RED，补齐后工具 14 项 GREEN；最终隔离 PostgreSQL 组合 59 项通过；演练确认 60 行名单、57 行赛果、原有 50 条赛果不变，应用/幂等/精确恢复均通过。
