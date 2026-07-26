# 赛事生命周期地区来源调研（2026-07-25）

## 1. 结论

建议采用“地区主来源 + 官方复核来源”的组合：

| 地区 | 建议结构化主来源 | 官方复核/回退 | 当前结论 |
|---|---|---|---|
| 英国、中国香港 | The Racing API Pro | BHA/HKJC 官方页面或公告 | 可进入有界付费 proof；TRA 不取得 official authority |
| 日本 JRA | `miyamamoto/jrvltsql` + JRA-VAN Data Lab/JV-Link | JRA 官方公告 | 技术上可行；使用确定性采集器，不把 MCP 自然语言层放入生产写链路 |
| 日本 NAR/JPN1 | 地方競馬情報サイト官方 CSV，或经批准的地方競馬DATA/NV-Link | NAR/主办方官方公告 | `jrvltsql` 不覆盖；必须作为独立来源 proof |
| 美国 | The Racing API North America add-on | Equibase 人工/获授权 Data Sales API 复核 | 未发现与 JV-Link 同等级、可合规生产使用的 GitHub 库 |
| 法国 | The Racing API Pro | France Galop 官方页面/公告 | 可作为 P0 G1 的近期结构化主来源候选，需逐场/逐字段 proof |

建议首轮订阅 **The Racing API Pro + North America add-on**，公开月费合计
`£149.98`（未含税），另加 JRA-VAN Data Lab `¥2,090/月`。Free/Basic/Standard 都只有
today/tomorrow racecard，不能满足本任务至少 T-7 的近期赛前刷新。

The Racing API 套餐也覆盖爱尔兰，但 Umanews 当前 `RacingRegion`、时区合同、P0 分母和公开页面
均没有 Ireland。本 change **不接入爱尔兰**；只记录它是套餐附带能力，未来必须通过独立 change
新增地区模型、`Europe/Dublin`、身份映射、页面、测试和 rollout，禁止静默归入英国或 `other`。

## 2. 日本：JV-Link 项目

### 2.1 项目关系

- `miyamamoto/jvlink-mcp-server` 不是数据采集器；它面向已有的
  SQLite/DuckDB/PostgreSQL 赛马数据库提供 MCP 查询。
- 真正连接 JRA-VAN、解析 JV-Data 并写数据库的是
  [`miyamamoto/jrvltsql`](https://github.com/miyamamoto/jrvltsql)。
- 生产链路应直接读取 `jrvltsql` 的确定性数据库输出。MCP server 可用于人工诊断，
  不应介入自动字段写入、状态推进或赛果确认。

### 2.2 项目活跃度

2026-07-25 只读核对：

- `jrvltsql`：Apache-2.0，2026-07-21 仍有发布和修复提交，20 stars、8 forks、无公开
  issue；仓库包含单元、集成、E2E、数据布局及性能测试。
- `jvlink-mcp-server`：2026-06-21 更新到 v0.6.0，13 stars、2 forks；它同步
  `jrvltsql` schema，但不是采集正本。
- 用户已核实本站可在限速条件下使用日本方案；本调研据此不再把数据使用许可列为阻断项。
  实施时仍应将限速、署名/notice 和允许的公开字段固化到 provider contract。

### 2.3 生命周期字段覆盖

`jrvltsql` 已明确支持：

- `YS`：举办日程；
- `TK`：特别登记马；
- `RA`：赛事及出马表；
- `SE`：参赛马、骑师等；
- `AV/JC/TC/CC/WE`：取消、除外、骑师或举办信息变化；
- `0B15`：出走马名表发布后的实时赛事信息；
- `0B12`：成绩确定后的实时赛事、赛果和赔付；
- `HR`：赛果/赔付；
- PostgreSQL、SQLite 以及持续 JVRTOpen 读取。

JRA-VAN 公布的典型时间线包括：周四发布当周出走马名表，出马表发布后继续更新取消及
骑师变化，赛后按三名、五名、全马等确认阶段实时提供成绩。因此它比聚合 API 更适合
日本 JRA 的字段权威升级和结果确认。

### 2.4 唯一传输合同

- JV-Link COM 只支持 Windows 形态，文档建议 32-bit Python；现有 Linux 生产主机不能直接运行。
- 推荐部署一台独立 Windows collector，只运行一个采集实例。
- 唯一允许的跨主机传输方式是**不可变签名 snapshot**，不允许 collector 连接生产数据库，
  也不允许 Umanews 直接读取 collector 的活动数据库。
- collector 在本机 staging DB 完成一个批次后生成 envelope：
  `schema_version/snapshot_id/provider/provider_contract_version/collector_id/collector_git_sha/
  collector_build_sha/fencing_token/upstream_spec/high_watermark/source_observed_at/fetched_at/
  record_counts/payload_sha256/previous_snapshot_sha256`。
- payload 和 manifest 先写临时目录并 fsync；用独立 Ed25519 私钥签 manifest，原子 rename 后最后
  创建 `COMPLETE` marker。Umanews 只接受 registry 中活动 `collector_id + fencing_token`、
  签名和 hash 全部通过且存在 marker 的 snapshot。
- Umanews 使用受限 SFTP-only 只读账号主动拉取 export 目录；只允许生产出口 IP、公钥认证，
  collector 无生产入站凭据。验签公钥进入 provider registry，私钥只在 Windows secret store。
- 每个 upstream spec 单独 high-watermark；只有 Umanews 业务事务完整提交后才推进消费水位。
  `(provider,snapshot_id,payload_sha256)` 唯一，重复为 noop；乱序、缺前驱、schema/build/contract
  漂移均 fail closed。collector 切换必须先签发更高 fencing token，旧 token 立即拒绝。
- `jrvltsql` 自带的进程文件锁不是 Umanews 的单赛事幂等锁；进入 Umanews 后仍必须执行
  provider event identity、字段 authority、事务和审计门禁。
- 不使用 MCP 自然语言 SQL 执行生产写入。
- snapshot payload 保留 30 天，manifest/hash/消费 receipt 和字段变更审计长期保留；赛日目标
  RPO 5 分钟、RTO 30 分钟，非赛日 RPO 24 小时。超出目标只告警并让赛事进入 result pending，
  不以缺数据阻断时间状态推进。
- 回滚首先关闭 JRA provider kill-switch、撤销活动 fencing token/验签公钥并停止拉取；已由
  高权威事实确认的数据不自动反写，必要回退必须生成逐字段人工批准的 reverse candidate。

### 2.5 NAR/JPN1 缺口

`jrvltsql` 明确只支持 JRA，不支持 NAR。当前剩余 2026 P0 日本赛事为 `13` 场 G1 +
`6` 场 JPN1，因此只接入它仍会留下 `6/19` 的日本 P0 缺口。

NAR 官方“地方競馬情報サイト”在 2026 年新增 CSV 下载：

- 当日 racecard、赔率和赛果文件约每 2 分钟更新；
- 月度文件每日约 02:00 更新；
- 月度 racecard/赛事列表包含已经发布出马表的未来日期；
- 可下载 racecard、race list、payout/result 和 odds CSV。

该来源在技术和权威上优于再增加一层 MCP/NV-Link，但官网通用条款禁止未经许可转载或复制。
若用户已有单独许可，可直接将其纳入 proof；否则需取得书面许可，或使用已获批准的
地方競馬DATA/NV-Link 合同。

## 3. 美国：GitHub 候选审计

没有找到与 JV-Link 相当的“官方数据 SDK + 活跃导入器 + 明确生产许可”组合。

| 项目类型 | 实际做法 | 问题 |
|---|---|---|
| `ktarrant/equibase_scraper` | `requests` + BeautifulSoup 抓 Equibase HTML | GPL-3.0，但核心提交停在 2023；代码许可不覆盖数据或站点访问 |
| `Sixteen1-6/HorseRacing` | Playwright 连接本地 Chrome，抓 entries/PDF | MIT；遇机器人检测时要求人工处理验证码，不适合无人值守生产 |
| `gmalbert/horse-racing-predictions` | requests，失败时用 Playwright/stealth 绕 Imperva | 无明确 license；主动绕反爬，不可进入本项目 |
| 其他 Equibase parser/PDF 工具 | 解析已下载 PDF/XML 或历史数据集 | 不是实时 entries/results provider |

Equibase 页面明确声明禁止 robot、spider、scraper 等自动访问，也禁止未经书面同意重新发布。
因此即使 GitHub 仓库使用 MIT/GPL，也不会给 Umanews Equibase 数据访问和公开展示权。
本项目不得采用反爬、验证码绕过或 stealth 方案。

The Racing API North America add-on 是当前更合理的自助方案：

- 任意基础 plan 可加购，`£49.99/月`；
- 提供 meets、entries、results 独立端点；
- entries 响应含 `changes`，但 scratch、jockey change、postponed 的具体编码与延迟仍需真实 proof；
- 公布的 2026 USA 结果库存为 `15,594`，远高于 Core 的 `185`，add-on 才是美国完整数据集；
- add-on 的未来查询范围、结果临时/正式语义及修正事件没有公开 SLA，采购前必须书面确认。

建议购买一个月 add-on，以当前剩余 `50` 场美国 P0 为分母做滚动 proof；Equibase 只保留为
人工复核或另行签约的 Data Sales API，不做自动抓取。

## 4. 英国、中国香港与法国

The Racing API Core 宣称完整覆盖英国、爱尔兰、中国香港，并覆盖全球 Group 级赛事和部分
handicap。公开结果库存的 2026 数量为英国 `4,637`、爱尔兰 `1,238`、香港 `485`、
法国 `851`。

套餐对生命周期的关键差异：

- Free/Basic/Standard：racecard 仅 today/tomorrow；
- Pro：future racecard 最多提前 7 天；
- 今天的 racecard/赔率/结果标称约 3 分钟更新，明天约 15 分钟，更远未来每日更新；
- 更新频率不是 SLA，TRA 也不是赛场官方数据商。

因此：

- 英国/香港建议用 Pro 做 T-7 至 T0 的结构化主来源；
- HKJC/BHA 官方来源继续用于冲突解决、取消/延期及 official result 升级；
- 爱尔兰仅记录为套餐能力，本 change 不建模、不纳管、不查询；
- 法国 2026 剩余 P0 为 `24` 场 G1，理论上落在 Core 的 global Group 范围，但必须逐场验证；
- 法国使用 TRA 时，France Galop 保留为 official 复核，来源失败不阻止时间状态推进。

TRA Pro 仍无法满足 T-14/T-21。更早阶段只维护已有赛事日历和官方公告探测，结构化 runner
刷新从 T-7 开始；如果后续确需 T-14/T-21 的确定出马资料，应另行采购有 declarations/entries
提前期的供应商，而不是频繁轮询不存在的数据。

## 5. 推荐 proof 门禁

### 5.1 The Racing API Pro + North America

- 期限：一个月；
- 样本：每地区至少 10 场 P0；香港不足时覆盖全部可用 P0；
- 检查点：T-7、T-3、T-1、T0、开赛后 3/5/10/30 分钟、次日；
- 字段：时间、时区、runner、jockey、draw、scratch、postponed/cancelled、
  provisional/full result、结果修正；
- 输出：覆盖率、字段完整率、首次可用时间、结果延迟 P50/P95、修正次数、错误率；
- proof 只写脱敏 artifact/shadow candidate，不改变公开状态。

### 5.2 JRA-VAN / `jrvltsql`

- 固定一个 Windows collector 和一个 JRA G1 周末；
- 验证 `RA/SE/AV/JC/0B15/0B12/HR` 的实际字段映射和更新时间；
- 从官方 JV-Data 状态位冻结 result phase 映射：三名/五名/未知部分阶段只能 provisional，
  只有显式全马最终 marker 才能 official；正式后修正只能产生 corrected；
- 验证 collector 重启、JV-Link 维护窗口、断网恢复和重复导入；
- staging 到 Umanews 仅走已验签的不可变 snapshot；
- 先做 shadow，不直接写 `RaceEvent` 或 `RaceResult`。

### 5.3 NAR/JPN1

- 先冻结许可或用户已有许可证据；
- 选两场 JPN1 验证官方 CSV 的未来 racecard、两分钟更新、退赛/骑师变化和结果；
- 不与 JRA 表混用 provider event id。

## 6. 推荐决策

1. 采用用户提出的地区分流方向。
2. 日本把技术正本从 `jvlink-mcp-server` 调整为 `jrvltsql`；MCP 仅作诊断。
3. 日本拆为 JRA 和 NAR 两条来源，不能把 JRA 覆盖泛化到 JPN1。
4. 美国不采用 GitHub Equibase scraper，进入 TRA North America 单月 proof。
5. 英国、香港、法国使用 TRA Pro；爱尔兰留给独立 change。
6. TRA 全地区保持 `verified_professional_api/supplemental`；官方来源确认后才能标记
   `official_result`。
7. 阶段 A 仍不依赖外部来源；所有新 provider 均从 dry-run/shadow 开始，独立开关、独立授权。

## 7. 资料

- https://github.com/miyamamoto/jvlink-mcp-server
- https://github.com/miyamamoto/jrvltsql
- https://jra-van.jp/dlb/ddata.html
- https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf
- https://www.keiba.go.jp/terms.html
- https://api.theracingapi.com/documentation
- https://www.theracingapi.com/data-coverage
- https://www.theracingapi.com/terms-of-service
- https://www.equibase.com/products/whataredownloadablecharts.cfm
