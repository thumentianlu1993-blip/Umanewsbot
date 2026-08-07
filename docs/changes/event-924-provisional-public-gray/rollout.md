# event 924 暂定赛果单赛事公开灰度发布与回滚

## 当前门禁

方案审核和本地 RED/GREEN 已完成，当前停在阶段 C 的首次代码 review 前。以下动作在最新

- 改 production policy；
- 晋级 revision `2`；
- 创建 public projection/publication/incident；
- 重新轮询 TRA；
- 打开 scheduler；
- 增加 event；
- 部署候选版本。

## 阶段 A：方案审核

验收：

- 方案以 `origin/main@353464c7` 和 2026-07-18 生产只读事实为基线；
- 明确现有复用面和两个实现缺口；
- promotion 不依赖 today endpoint；
- BHA manual route 不被误称自动 official；
- reviewer 关闭 P0/P1。

失败：仅修改方案文档并复审，不进入 RED。

## 阶段 B：本地 RED/GREEN

环境：

- 本地 SQLite 用于 parser、命令、页面和大部分业务行为；
- 临时 PostgreSQL 16 用于真实行锁、嵌套 transaction、并发和 rollback；
- 不访问真实网络；
- 不读取历史 runtime。

验收：

- 首批核心行为和实现中发现的新增失败关闭缺口取得真实 RED；已有基线已覆盖的行为直接作为
  回归，不伪造历史 RED；
- GREEN 后聚焦与相邻准实时回归通过；
- no migration drift；
- manifest/命令输出无 secret/raw；
- operator admission 任意子步骤注入失败时 policy、allowlist、publication、incident 和
  tracking 全回滚；
- runner/operator PostgreSQL 竞争无死锁，provider claim/timing 字段不被 operator 改写；
- BHA manual receipt 的 match/conflict/unavailable 三条路径均有真实 RED/GREEN。

## 阶段 C：代码审核与冻结

1. 未参与实现的 reviewer 执行：

   ```bash
   codex review -c 'sandbox_mode="read-only"' --uncommitted
   ```

2. 修复 finding 后复用同一 reviewer 会话限定复审。
3. 成功后记录：
   - reviewed scope；
   - full fingerprint；
   - approved parent；
   - `content_manifest_sha256`。

任何受审内容变化都使 review/授权失效。

## 阶段 D：部署但保持 shadow

前置：

- 生产历史 runner/receipt/lease/checkpoint 处于已记录安全状态；
- 普通新闻 worker/Beat 可安全维护；
- event 924 facts 与 manifest 预期无漂移；
- tracking/allowlist universe 精确 `[924]`；
- scheduler false；
- live queue/active/reserved/one-off 为空。

步骤：

1. 创建 custom-format PostgreSQL 备份；
2. 核对 owner/mode/权限和 `pg_restore -l`；
3. 部署受审 image；
4. 运行 migration `0046`，确认只增加 nullable/default-empty 治理字段且不回填、不晋级；
5. system check、healthz、worker/queue/resource；
6. 确认部署后仍是 shadow、publication 0、legacy result 0、incident 0。

此阶段不执行 promotion。

## 阶段 E：event 924 promotion

### 官方 route 人工 preflight

release operator 使用正常浏览器人工打开受审 BHA Results URL，确认
`bha-manual-v1` registry 和 terms evidence 未过期、manual route 当前可执行。不得调用
页面后端 API、脚本抓取或批量下载。官方 event 结果尚未出现不阻止暂定首发；入口完全不可
人工使用或 route contract 过期则停止 promotion。

### 生成 transition bundle

只在生产宿主安全 runtime 目录生成：

- 目录 `root:root 0700`；
- promotion/disable/restore/report/SHA ledger 均为 `root:root 0600`；
- 输出 root/ancestor 不得是 symlink，run ID 独占，已存在路径绝不覆盖；
- 唯一 event `924`；
- 唯一 observation `1`；
- 唯一 result revision `2`；
- expected policy `shadow v1` 四条；
- expected allowlist v1；
- expected owner manifest `ee9d0d43…1432`；
- expected digest `4d2fa8c…ccc2`；
- approved commit 等于部署 OCI revision。
- BHA route contract digest、terms evidence digest、version、validity、责任角色和 15 分钟
  SLA 与受审 registry 完全一致。

### dry-run

必须输出：

- `ok=true`；
- `mode=dry_run`；
- `event_ids=[924]`；
- `would_promote_revision_id=2`；
- `network_request_count=0`；
- 精确 policy pre/post versions；
- allowlist v1->v2 和 route digest pre/post；
- public facts pre-count 全为 0。

### apply

只执行一次：

```bash
python manage.py transition_race_live_publication \
  --manifest <manifest> \
  --expected-manifest-sha256 <sha> \
  --expected-approved-commit <commit> \
  --apply --confirm-apply
```

apply 必须是一个数据库外层 transaction。不得在 apply 前单独手改 policy，也不得另行 claim、
dispatch Celery 或请求 TRA。

### verify

独立进程执行 `--verify`，检查：

- policy 四条 provisional public，version `2`；
- allowlist version `2`，route contract/terms digest 与 registry 一致；
- revision `2` published；
- publication `1`；
- legacy result `7`；
- incident `1 / open / overdue`，且保存相同 route digest，
  `manual_verification_due_at=promotion commit+15m`；
- event status finished；
- `result_confirmed_at=null`；
- active claim 空；
- claim generation 和 provider attempt/success/hash/failure/stale 字段与 pre-state 逐字段
  相同；
- tracking disabled、next poll 为空；
- public read allowed；
- scheduler false；
- tracking/allowlist universe `[924]`。

## 阶段 F：页面与运行态验收

详情页：

- HTTP 200；
- “暂定赛果”“尚待官方来源复核”“补充来源”；
- 1–7 顺序完全匹配受审 revision；
- 有 racecard 证据的闸位/骑师显示；
- 只有闸位/骑师允许 fallback 且有字段级 provenance；trainer/time/margin/weight 即使
  racecard 有值也不从 fallback 带入，未取得时显示 `-`；
- hero 显示“冠军 · 暂定”，不显示“赛果已确认”；
- 不含第三方评级、评论或“官方已确认”措辞。

日历：

- HTTP 200；
- 与详情页 read gate 结论一致；
- 只显示 event 924 的结果。

运行态：

- healthz 200；
- scheduler false；
- live/news queue、active/reserved/one-off 为空；
- history runner 状态未变；
- host budget 未因 promotion 改变；
- web/worker 资源无异常。

## 阶段 G：BHA 首次人工复核

promotion commit 后 15 分钟内：

1. release operator 在正常浏览器查看 BHA Results；
2. 用 offline prepare 命令生成 `0600` manual receipt，记录 source URL、observed_at、
   私有截图/打印件 SHA、marker 与客观 participant/position；不保存页面 raw 或专有内容；
3. 用 expected receipt SHA/approved commit 执行独立 dry-run；
4. apply 服务自行比较 published provisional revision：
   - match：写 official observation/marker evidence，incident resolved，页面仍 provisional；
   - conflict：同一 transaction 写 evidence、incident escalated 并应用预生成 disable；
   - unavailable/尚无结果：不写伪 observation，记录一次 probe/alert/next probe，incident
     保持 open，明确 provisional 继续公开。
5. 独立 verify 复核 incident、policy、页面标签与审计数量。

## 阶段 H：kill switch 演练

使用 promotion 前同一安全 bundle 预生成、且以 promotion 确定 post-state 为 pre-state 的
event 924 精确 disable manifest：

1. dry-run；
2. apply；
3. verify；
4. 详情和日历立即隐藏 live result；
5. revision/publication/legacy result/incident 数量不减少；
6. scheduler/queue/其他 event 不变。

隐藏并向用户报告。

## 回滚矩阵

| 故障 | 第一动作 | 审计事实 |
|---|---|---|
| 页面文案/字段错误 | event 924 disable manifest | 保留 |
| policy 漂移 | 停止，不 apply；核对操作者 | 不变 |
| promotion 内部失败 | 外层事务自动回滚 | pre-state |
| apply 成功但 verify 失败 | 立即 event 924 disable；保存证据 | 保留 |
| web/worker 资源异常 | disable + 回滚 image | 保留 |
| 数据库结构/事务异常 | 停服务，按验证备份恢复 | 以备份为准 |
| 官方来源迟到/暂不可用 | 保持清晰 provisional；incident open + 一次告警 | 保留 |
| 官方结果冲突 | manual apply 同事务 disable；另立 official 修订 | 保留 |

## 灰度结束条件

本变更只在以下事实齐全时完成：

- event 924 promotion 和 public page 实证；
- BHA 首次人工 probe 已按 match/conflict/unavailable 路径留下可审计证据；
- kill switch 实证；
- 零其他 event 扩张；
- overdue official incident 被明确报告；
- evidence-only closure review 通过并提交。

它不等于准实时赛果“正式全量上线”。扩大到第二场、开启 scheduler、接入英国 official 或
进入其他地区，都必须使用后续独立 reviewed change。
