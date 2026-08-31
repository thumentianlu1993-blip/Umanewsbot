# Ireland 历史赛果与外部冠军锚点方案（2026-08-30）

## 结论

Ireland 的历史 occurrence 不能宣称已闭环。reviewed COMPLETE target 中有 `1,957` 条 Ireland target，当前
局部 occurrence ledger 的 Ireland gap 仍为 `1,957`。现阶段可执行的最小方案分成三层：

1. HRI 继续作为 Ireland 首选官方 authority，但没有可验证的本地 HTML fixture/parser，也没有公开许可足以
   支撑商业系统化抓取；因此只保留人工发现与后续许可路线。
2. 既有 IrishRacing parser 增加 `ireland_irishracing / irishracing_ireland` 地区专用离线入口，只消费已冻结、
   经 source map/admission 的页面，authority 保持 `third_party_high_access`。
3. 对能从受控外部页面确认唯一冠军的 target，先生成不可执行 winner-anchor proposal；独立审核后才发布为
   TRA targeted-horse seed，再由 TRA full horse results 唯一反查目标赛事和完整 runners。

## HRI 能力与限制

HRI 的官方结果产品页面可见 date/course/race/grade/distance、ran、runner、sire/dam、jockey/trainer/owner
和名次等字段，例如 [HRI Results](https://www.hri.ie/results?meeting=2025-079) 与
[HRI Race Result](https://www.hri.ie/results/race-result?meeting-num=2025-288&race=1325)。搜索索引也能发现
历史统计入口，但这不证明 2000–当前的逐场完整 coverage，也不构成批量复用许可。

当前自动化直接打开 HRI 结果页返回 403；没有冻结真实响应 fixture，因此没有实现或声称通过 HRI HTML
parser。公开搜索也没有找到足够明确的系统化商业复用授权。后续只有在取得书面许可或 HRI 提供正式数据
接口/导出后，才能把 HRI 路线升级为 executable official source。

## Ireland-specific IrishRacing 离线入口

本轮扩展以下现有组件：

- `prepare_irishracing_race_detail_candidates.py`：Ireland -> `ireland_irishracing`；
- `package_historical_race_detail_candidates.py`：`irishracing_ireland` source mapping；
- `historical_race_detail_adapters.py`：Ireland adapter 与 parser provider；
- `historical_race_detail_sources.py`：Ireland provider/authority/region admission。

这只证明冻结页面可被现有 parser 离线处理，不证明 IrishRacing 的历史覆盖或系统化抓取许可。runner v2
现已加入 Ireland 六地区 recipe，但显式区分 authority 与 execution：HRI 保留 official source 且列入
`blocked_sources`，IrishRacing 是唯一 `executable_sources`。descriptor/request policy 只接受
IrishRacing HTTPS `/raceresults/`；HRI provider、HRI URL、伪标 provider 或将 HRI 改为 executable 都在
cache/network 前拒绝。因此 official chain 的位置已建模，official route 本身仍未完成。

target-complete readiness 审计进一步把该差异固化为机器可读 artifact：

- root：`/Users/mentianlu/.codex/umanews-ireland-runner-readiness-v1-20260830.qQWH0n`
- recipe SHA-256：`8dd2a6934fe627ae6b672622878710f47e0a2362d04f97fe9f25a966624e74ca`
- manifest SHA-256：`d6f71a65653f41ff67a3426688e24a3b474a70d187c8952baca5225b51d3205f`
- ledger SHA-256：`0810e6622b0242a009f2a56402e997adc613b5c1d5d3902d5d1dc100a4a8c27e`
- counts：Ireland targets/HRI blocked/approved direct URL missing 为 `1,957/1,957/1,957`；present/approved
  为 `0/0`；状态 `PREPARED_NOT_EXECUTABLE`。

第二个空目录重放得到相同 manifest 与 ledger SHA。审计器只有在 exact COMPLETE target、exact recipe 和可选
source fragment SHA 全部匹配时才运行；即使存在 direct URL，也只标 descriptor candidate，不授予执行。

## 外部冠军批量提案

输入索引：

- 文件：`ireland_2024_external_winner_anchor_index.v1.jsonl`
- SHA-256：`802275a02fead67082f0f630429a03e6e531354706fd415bb43a98dba4c49b71`
- 行：`1`；target：`ireland:2024:ireland-irish-champion:flat`
- 冻结来源：Netkeiba 英文单场结果；冠军 `Economics`，2024-09-14，G1。

proposal artifact：

- root：`/Users/mentianlu/.codex/umanews-ireland-external-winner-anchor-proposal-v2-final-20260830.OfLBzd`
- manifest SHA-256：`694f6c0eb5b5fe49b93471ccbf90cebf0d9bc5bd800d924786ece98de732adca`
- seed ledger SHA-256：`7ad16746f7fa6454852f6e105407f01c74fa2ecdad5d775a1007b16e47a5ea36`
- evidence SHA-256：`35881c880c48fef2ecdee9d6c0b6fd7f6a1cd3dd9c6d29ef9dac3b8db70c1eb1`
- generator SHA-256：`a87b60cdec06d16c02b58ab200a3e4040f8f3622b1982ae62185f9264dcf1eaa`
- 状态：`PREPARED_NOT_EXECUTABLE / approval=false / network_requests=0 / database_writes=0`。

第二个空目录重放得到完全相同的三项输出 SHA。该提案只证明“一条冻结单页证据可以生成一条待审冠军
anchor”，不批准该 anchor、TRA 请求、Netkeiba 批量抓取或数据库写入。

## 独立审核合同

`publish_external_winner_anchor_approval.py` 只接受 regular decision file 与 exact decision SHA。decision
必须绑定 proposal manifest、seed/evidence 两份输出、非实现者声明、带时区时间、审核人、不可变审核记录
引用和理由。publisher 重新验证 COMPLETE target、anchor index、capture manifest、request ledger、原始页面、
winner reference、seed/evidence 双向守恒后，才逐字节发布现有 batch planner 可读的
`targeted-horse-seed-ledger.v1 / COMPLETE`。

当前没有真实 decision 或 APPROVED artifact。测试内的独立批准 fixture 能继续生成 batch plan，但该 plan
仍为 `PROPOSED_NOT_APPROVED`，从而保证事实审核不会隐式授权网络。

## 验证

- proposal/publisher 专项：`6/6`；
- `runtime/research` 完整：`342/342`；
- Ireland runner/detail/source/direct URL：`90/90`，`1 skipped`；
- py_compile：通过；
- 首次 Django 重跑误传不存在的 `config.settings.test`，在 settings import 阶段失败且未创建测试数据库；
  改用仓库真实 `app.settings` 后通过。该误调用没有网络或业务数据库副作用。
