# P0 马信息补全专项交接文档

更新日期：2026-07-20

## 1. 文档目的

本文供后续模型直接接手 P0 马信息补全专项使用，汇总项目背景、已确认需求、当前真实状态、
已完成工作、剩余任务、生产边界和关键入口。

接手后不要只根据本文判断生产状态。开始任何操作前，依次阅读：

1. `AGENTS.md`
2. `docs/current_state.md`
3. `docs/decisions.md`
4. `docs/deploy_runbook.md`
5. `docs/project_status.md`
6. `docs/p0_horse_career_history_policy.md`
7. `openspec/changes/complete-p0-horse-profile-data/`

`docs/current_state.md` 是状态主文档；本文是专项导航和交接摘要。两者冲突时，以
`docs/current_state.md` 和生产实时核验为准。

## 2. 项目整体背景

UmaNews 是面向中文用户的日本及全球赛马资讯平台，主要技术栈为 Django、PostgreSQL、
Celery、Redis、Docker Compose 和 Nginx。项目已经具备新闻采集、翻译、术语保护、
后台审核、网页发布、赛事总账、赛事详情和马匹详情等能力。

P0 马专项的目标不是只做一份静态马匹名单，而是建设可持续维护的高优先级马匹资料层：

- 从术语库和重点赛事中识别 P0 马。
- 为每匹 P0 马建立稳定身份和多语种名称。
- 补齐基础资料、二代血统、完整生涯履历、主胜鞍和来源证据。
- 在后台完成人工审核后写入主表，并独立决定是否公开。
- 已发布马以后可以自动增量更新；未发布马暂不自动首次公开。
- 公开页面只读本地数据库，不能在用户访问页面时实时请求第三方。

生产环境：

- 服务器：`root@47.239.167.86`
- 项目目录：`/opt/umanewsbot`
- Compose：`docker-compose.prod.lowcost.yml`
- 公开健康检查：`http://umafans.run/healthz/`
- 当前 P0 运行 revision：`7ad6adebb366444aa03e6e766d66fe9a49a3e2f8`
- 当前 P0 镜像：
  `sha256:af880cd208198c1e2ab960d8f39bd60539bdafa422cfb98890d0befbd90ff862`

不要把其他项目服务器、其他 worktree 的候选代码或本地主工作区的未提交文件当成当前 P0
生产基线。

## 3. 当前工作树与分支

专项生产交接工作树：

```text
/Users/mentianlu/Code/umanews/.worktrees/p0-horse-production-release
```

分支：

```text
codex/p0-horse-production-release
```

本交接文档创建前，该分支最新提交为：

```text
0880e429 docs: record P0 production scope sync
```

主工作区 `/Users/mentianlu/Code/umanews` 当前混有赛事历史回填、新闻门禁等多个专项的未提交
改动。后续模型必须先核对 worktree 和分支，不得在主工作区覆盖其他会话文件。需要吸收最新
`origin/main` 时，应在独立 worktree 中先比较和集成，再执行测试与生产发布门禁。

## 4. 已确认的 P0 定义

P0 马包含两部分的并集：

1. 当前 active 且已有中文译名的 horse `TermEntry`。
2. 日本、中国香港、英国、法国、美国五大地区，历史及未来所有重点赛事的参赛马。

重点赛事等级为：

```text
G1 / G2 / G3
J-G1 / J-G2 / J-G3
JpnⅠ / JpnⅡ / JpnⅢ
```

Listed、Open 和普通地方等级不因为赛事本身进入 P0 赛事范围，但一匹马一旦因其他依据成为
P0，它参加过的普通比赛仍必须进入该马的完整生涯履历。

新增 P0 马可以暂时没有中文译名。无中文译名马名仍需：

- 作为 horse term 进入术语识别。
- 在翻译时锁定为马名实体。
- 最终译文至少保留一次原始马名。
- 后台和前台使用原名展示“中文名待补”。

## 5. 本需求要补齐的完整马匹信息

### 5.1 身份和 P0 来源

- 稳定 `HorseProfile`
- P0 来源类型、赛事、等级、地区、来源 URL 和证据
- 来源内 external horse ID
- 多语种原名、中文名和 alias
- 同名马身份冲突与人工解决记录

马匹地区不属于唯一身份键。身份匹配规则为：

- 同一来源优先使用 provider namespace + external horse ID。
- 跨来源合并数据库已有马，必须唯一匹配经术语库归一的
  “马名 + 父名 + 母名 + 出生年份”。
- 同名、同地区仍可能是不同马；证据不足时进入 `HorseIdentityConflict`，禁止猜测合并。

### 5.2 基础资料

- 国家或产地
- 性别
- 毛色
- 出生日期；只有年份时保留日期精度，不能虚构月日
- 马主
- 练马师
- 生产牧场或育马者
- 字段级来源、URL、核验时间、原始值和归一化值

### 5.3 二代血统

- 父
- 母
- 父父
- 父母
- 母父
- 母母

来源没有祖父母时，可以查询父马和母马各自的父母再回填，但必须锁定父母实体身份。父母同名
或身份不能唯一确认时，不得自动采用。

### 5.4 完整生涯履历

完整生涯必须按马抓取，不能从重点赛事总账反推。新马赛、未胜利赛、普通条件赛、让磅赛、
表列赛、G2/G3 和 G1 均应进入 `HorseRaceRecord`。

每条履历至少需要：

- 日期和日期精度
- 原始比赛名及规范化比赛名
- 马场、地区、场次或来源赛事 ID
- 距离原文、单位和可验证的规范化值
- 跑道或比赛类型
- 名次或正式异常结果
- 实际出赛状态
- 可得的骑师、马号、闸位、负磅、完成时间和奖金
- 来源名、URL、外部马匹 ID、外部赛事/结果 ID、抓取或核验时间
- 直接原始值、权威标准原始值、内部归一化值三层字段证据

没有正式 `RaceEvent` 的普通比赛仍保存未关联 `HorseRaceRecord`，不得为了马匹履历强行创建
低质量 `RaceEvent`。以后确认赛事身份后再安全关联。

需要分别统计：

- `official_or_source_start_count`
- `collected_start_count`
- `linked_race_event_count`
- `unlinked_race_record_count`
- `overseas_start_count`
- `deduplicated_source_record_count`
- `career_history_gap_count`
- `career_history_status`
- `career_record_authority_status`

`F`、`UR`、`BD`、`PU` 等未完赛状态属于实际出赛；`WV`、scratched、withdrawn 属于未实际
出赛。不能把所有非数字结果折叠为 `unknown`。

### 5.5 主胜鞍、审核和发布

- 主胜鞍从完整履历中派生，并允许人工 `is_major_win` 覆盖。
- 基础资料、血统、履历、主胜鞍四个模块分别审核和留痕。
- 人工锁定字段不得被自动覆盖。
- 只有全部必需模块具备有效 APPLIED 审核和来源证据，才能标记
  `complete_profile_full`。
- 资料完整不等于自动发布。首发仍需独立发布动作；本阶段没有启用自动首次发布。

## 6. 已完成的能力建设

### 6.1 模型与迁移

生产已应用至 `stable.0052_horse_career_source_authority`。关键能力包括：

- `HorseProfile` 的资料完整度和生涯完整度拆分。
- `HorseP0Source`
- `HorseProfileCompletionRun`
- `HorseIdentityConflict`
- `HorseProfileDataCandidate`
- 支持未关联普通比赛的 `HorseRaceRecord`
- 生涯总数、采集数、缺口、海外、去重和逐场权威性字段
- 字段级三层来源证据和生涯来源快照
- 完整履历分页，不再固定截断 20 条

首次迁移曾因 PostgreSQL `pending trigger events` 回滚，之后已拆分为原子
`0049` 字段、`0050` 回填、`0051` 索引约束和 `0052` authority 字段，生产已成功应用。

### 6.2 身份、术语和翻译保护

- P0 同场参与项按马号、来源 external ID、赛事内唯一马名分组。
- 跨来源采用完整四字段身份锁。
- 同名不同马可建立不同 profile。
- 无中文译名 horse term 可识别、锁定并要求译文保留原文。
- 待处理身份冲突支持 Django Admin 筛选和每日管理员通知。

### 6.3 五地区来源和真实回归

首批五地区各 10 匹已经完成真实研究、字段证据、完整履历和生产提交。已处理的关键来源问题：

- 日本：JBIS 为主要完整资料/履历来源，netkeiba 和 JRA/NAR 用于补充核验。
- 香港：HKJC；真实 `Overseas` 行已支持，主表和海外表重复记录会去重。
- 英国：Sporting Life Full Form；`casualty.reason` 已支持
  Fell、Unseated Rider、Brought Down 等正式状态。
- 法国：Sporting Life 的 `N/A` 不再直接当作缺失；法国字段优先由 France Galop /
  IFCE SIRE 核验，禁止把英式 Class 或舍入英制距离猜成 Groupe/官方米制。
- 美国：当前冻结 50 匹批次获批采用组合来源。HRN 提供主要逐场记录，Equibase 提供官方
  Career Starts 和身份/颜色核验；Fort George 另由 Sporting Life 与 Racing Post 补充。
  该批准只适用于冻结批次，不代表 HRN 全局自动成为官方逐场来源，也不允许绕过 Equibase
  访问限制或许可条款。

最终专项 Python 组合回归为 `282/282`；生产发布前后还执行过 P0/五地区组合、
PostgreSQL 迁移、Django check、migration drift、OpenSpec 和幂等复跑验证。精确测试分母与
SHA 以 `docs/current_state.md` 顶部记录为准。

## 7. 已完成的生产数据

### 7.1 首批五地区 50 匹

首批严格完整资料已写入生产：

- `50/50` 匹 `complete_profile_full`
- `1439` 条履历
- `1432` 次实际出赛
- `7` 次未出赛
- `4` 次海外出赛
- 实际出赛但结果为 unknown：`0`
- 普通比赛新增 `RaceEvent`：`0`
- `200` 条模块审核
- `published=0`，没有自动首次发布

生产 release artifact：

```text
runtime/horse_profile_completion/p0-production-release-20260720/
```

关键文件：

- `reviewed_p0_horse_completion_artifact.json`
- `p0_horse_production_release_manifest.v1.json`
- `production_commit_report.v1.json`
- `post_repair_idempotent_dry_run.v1.json`
- `approved_profile_mapping_decisions.json`

精确 artifact、manifest 和报告 SHA 见 `docs/current_state.md` 顶部。

### 7.2 全部 P0 范围来源

2026-07-20 已把当前可确定的 P0 范围写入生产：

- 有效 P0 来源：`56745`
- 唯一 P0 profile：`46318`
- 重点赛事参赛来源：`35097`
- active 且有中文译名术语来源：`21598`
- 人工来源：`50`
- 已翻译 horse term 未进入 P0 的数量：`0`

地区来源计数：

| 地区 | 有效来源数 |
| --- | ---: |
| 法国 | 5145 |
| 中国香港 | 4974 |
| 日本 | 11651 |
| 英国 | 19549 |
| 美国 | 9125 |
| other | 6301 |

当前详情完整度：

| 状态 | 数量 |
| --- | ---: |
| `complete_profile_full` | 50 |
| `complete_pedigree_2gen` | 2 |
| `empty` | 46266 |

当前生涯状态：

| 状态 | 数量 |
| --- | ---: |
| `complete` | 50 |
| `partial` | 2 |
| `not_started` | 46266 |

当前有 `65042` 条 pending `HorseIdentityConflict`。这是按赛事参与项记录的冲突证据数量，
不是唯一马匹数量。不能把它直接当成还缺 `65042` 匹马，也不能批量猜测解决。

## 8. 本次全范围写入的生产事故与经验

首次执行无地区：

```bash
python manage.py p0_horse_profiles --sync-sources --commit --json
```

在当前 `2 vCPU / 4 GiB / no swap` 主机触发 OOM，Linux 杀死约 `1.4 GiB` RSS 的 Python
进程。因为同步处于一个 `transaction.atomic()` 中，数据库完整回滚；重启后核对仍为原来的
`50` 条来源、`21621` 匹资料、`0` 个待处理冲突。

后续成功路径：

1. 验证数据库备份和 restore list。
2. 临时启用 `1 GiB` swap。
3. 停止空闲 beat、worker 和 race-live worker。
4. 按法国、香港、英国、美国、日本分别执行地区 commit。
5. 对 `other` 和空地区的 `7670` 条术语来源按 `500` 条事务补齐。
6. 恢复 worker，删除临时 swap。
7. 复核 Django check、migration、内外 health、来源分类和 term 缺口。

写入前备份：

```text
/opt/umanewsbot/backups/p0-horse-full-scope-precommit-20260720T063831Z
```

数据库 dump SHA-256：

```text
f773f5ec0a98974cc402b202cfe2f0eed91fc4f022e58a621f2c7b2b63b96378
```

禁止在这台主机再次直接运行无地区全量 P0 来源单事务。需要全量 reconcile 时，先实现并测试
正式的分页/检查点能力，不能依赖临时 shell 脚本作为长期运行方案。

## 9. 当前没有完成的事项

### 9.1 全量详细资料尚未采集

`46266` 匹 P0 马仍为 `empty/not_started`。当前完成的是 P0 范围和身份队列写入，不是所有
详细资料已经完成。

### 9.2 通用五地区批量 adapter 仍未完全产品化

OpenSpec `tasks.md` 中 `4.2` 仍未完成。首批 50 匹已经通过受控来源 client、缓存、人工补证和
冻结 artifact 跑通，但还缺可面向整个 4.6 万匹队列长期运行的通用批处理能力，包括：

- 可恢复分页和检查点
- 每地区独立请求预算、限速、缓存和失败重试
- 动态批次，不再只接受固定五地区各 10 匹审核 CSV
- 来源条款与自动化许可状态
- 字段缺口和身份冲突的可持续回流
- 完成批次的自动幂等验收，但不能伪造人工审核

生产仍保持：

```text
HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false
HORSE_PROFILE_COMPLETION_BATCH_LIMIT=10
```

### 9.3 身份冲突尚未治理

需要先对 `65042` 条参与项冲突做分组和原因统计，区分：

- 同一匹马跨赛事重复出现的同类冲突
- 同名不同马
- 缺父、母或出生年份
- 缺稳定 external horse ID
- runner/result 配对冲突
- 已有 profile 但来源身份不完整

后续应按“唯一马候选 + 冲突原因”形成管理员队列，不能逐条盲目处理赛事行。

### 9.4 公开验收尚未完成

OpenSpec `6.7` 仍未完成：尚未每地区人工发布 1-2 匹，验收公开索引、详情页、移动端、
完整履历、主胜鞍、关注入口、新闻 tag 和 no-network 边界。

### 9.5 OpenSpec 尚未归档

`complete-p0-horse-profile-data` 仍有 `4.2` 和 `6.7` 未完成，不得为了清单好看而勾选或归档。

## 10. 下一步建议执行顺序

### 第一步：建立可恢复的详情补全批处理

在独立 worktree 中实现 OpenSpec `4.2` 的长期版本：

1. 支持任意审核批次，而不是固定 5×10 CSV。
2. 按地区和 profile ID 分片，单批默认不超过 `10`。
3. 每批独立 artifact、manifest、请求预算、缓存和 checkpoint。
4. dry-run 与 commit 分离；commit 只消费冻结且通过门禁的 artifact。
5. 单批失败只回滚该批，不拖垮整机或破坏已完成批次。
6. 可幂等重跑，第二次 planned write 必须为 `0`。

用户已经要求后续批量推进时不要逐批重复询问授权，但这不代表允许跳过来源、身份或字段审核。
可以连续执行已经满足门禁的批次；不能把 AI 生成结果伪装成“人工已审核”，也不能猜值。

### 第二步：先治理身份冲突，再扩大抓取

先做只读统计和去重视图：

- 按规范化马名、赛事参与键、候选 profile 和原因聚合。
- 优先处理拥有父、母、出生年份或 external horse ID 的高确定性冲突。
- 仍有歧义的记录定期通知管理员。
- 解决后重跑地区来源同步，确认 active/revoked 和 profile 绑定幂等。

### 第三步：按地区滚动补齐详细资料

推荐顺序：

1. 日本：JBIS 链路最成熟。
2. 中国香港：HKJC 本地履历较强，但必须补海外记录。
3. 英国：Sporting Life 批量能力较强，异常结果需保留 casualty 原码。
4. 法国：必须补 France Galop/IFCE SIRE 权威层，不能仅用英式转换值。
5. 美国：当前冻结批次来源获批不等于全量许可；批量前先明确授权来源或继续采用可审计的人工
   Career Starts 核验方案。

每批都要求补足完整内容，不能只写基础资料或重点赛事履历后称为完成。

### 第四步：生产批次验收

每批至少核对：

- profile 身份唯一，跨来源四字段锁通过
- P0 来源有效且有 URL/证据
- 基础字段和二代血统完整
- 官方或可靠来源总出赛数存在
- 实际出赛数、未出赛数、海外数和去重数可解释
- actual start 的 unknown 结果为 `0`
- 生涯缺口为 `0`，或有明确不可补原因且不标完整
- 四个模块均有有效审核记录
- `complete_profile_full` 与模块结论一致
- 重复 commit 不新增履历或审核记录
- 不创建低质量普通 `RaceEvent`
- 公开请求路径不触网

### 第五步：完成首批公开验收

从已完成的 50 匹中每地区选择 1-2 匹人工发布，执行 OpenSpec `6.7`，然后再决定是否启用
更大范围的人工首次发布或未来自动首次发布。不要把详情写入和公开发布合并成一个授权。

### 第六步：更新状态并归档

完成 `4.2` 和 `6.7` 后：

1. 更新 `docs/current_state.md`
2. 更新 `docs/project_status.md`
3. 如有新决策，更新 `docs/decisions.md`
4. 如涉及生产，更新 `docs/deploy_runbook.md`
5. 运行完整验证和独立 code review
6. 同步 OpenSpec 主规格并归档 change

## 11. 关键代码入口

| 能力 | 文件 |
| --- | --- |
| P0 范围、身份、队列和完整度 | `server/stable/services/p0_horse_profiles.py` |
| P0 范围管理命令 | `server/stable/management/commands/p0_horse_profiles.py` |
| 五地区补全 adapter | `server/stable/services/p0_horse_completion_adapters.py` |
| 来源 client 与解析 | `server/stable/services/p0_horse_completion_source_clients.py` |
| 通用补全规划/应用 | `server/stable/services/horse_profile_completion.py` |
| 补全管理命令 | `server/stable/management/commands/complete_horse_profiles.py` |
| 已审核 artifact 生产链 | `server/stable/management/commands/apply_reviewed_p0_horse_completion.py` |
| 履历幂等写入 | `server/stable/services/horse_race_records.py` |
| 模型 | `server/stable/models.py` |
| 马匹后台/公开页面 | `server/stable/views.py` |
| 专项主测试 | `server/stable/test_p0_horse_completion_adapters.py` |
| P0 基础测试 | `server/stable/tests.py` |
| OpenSpec 任务 | `openspec/changes/complete-p0-horse-profile-data/tasks.md` |

## 12. 关键产物

### 审核与研究

```text
runtime/p0_horse_candidates/production-reviewed-20260718-all-50-approved/
runtime/horse_profile_completion/research-50-parsed-20260718/
runtime/horse_profile_completion/pedigree-research-20260719/
runtime/horse_profile_completion/manual-source-evidence-20260719/
```

最终审核工作簿：

```text
/Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/
outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/
P0马五地区50匹完整解析与字段可用性审核-v2.xlsx
```

该工作簿当前保存在原 P0 实现 worktree，不在 production-release worktree 中；冻结 SHA-256
为 `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`。移动、重建或复制
前必须重新核对 SHA，不能用同名文件替代冻结审核产物。

### 生产提交

```text
runtime/horse_profile_completion/p0-production-release-20260720/
```

生产服务器地区同步日志：

```text
/opt/umanewsbot/runtime/p0-horse-source-sync-*-20260720.json
```

## 13. 常用只读检查

生产健康：

```bash
ssh root@47.239.167.86 \
  'cd /opt/umanewsbot && docker compose -f docker-compose.prod.lowcost.yml ps'

curl -fsS http://umafans.run/healthz/
```

代码和迁移：

```bash
docker exec umanewsbot-web-1 python manage.py check
docker exec umanewsbot-web-1 python manage.py showmigrations stable
```

P0 dry-run：

```bash
docker exec umanewsbot-web-1 \
  python manage.py p0_horse_profiles --sync-sources --json
```

注意：上面的命令只能查看候选分母，不代表详情补全，也不要在当前主机去掉 dry-run 后执行无地区
全量 commit。

## 14. 禁止事项

- 不得把 `56745` 条来源说成 `56745` 匹完整马。
- 不得把 `46318` 匹 P0 profile 说成全部资料已补完。
- 不得从重点赛事列表反推完整生涯。
- 不得为了普通比赛强行创建 `RaceEvent`。
- 不得用地区或马名作为唯一身份。
- 不得猜测父母、出生年份、异常赛果、法国 Groupe 或官方米制距离。
- 不得把来源行数直接等同实际出赛数。
- 不得绕过 Equibase 防护做生产爬虫。
- 不得把未经审核的 artifact 标成已审核。
- 不得自动首次发布未发布马。
- 不得在 4 GiB 生产主机再次执行无地区单事务 P0 来源 commit。
- 不得覆盖主工作区或其他 worktree 的未提交改动。

## 15. 一句话当前状态

当前已经完成 P0 能力底座、五地区 50 匹严格完整资料生产提交，以及全部可确定 P0 范围的生产
入队；尚未完成 4.6 万匹详细资料的通用批量采集、身份冲突治理和每地区公开验收。后续应先把
五地区 adapter 产品化为可恢复小批次，再按严格身份、来源、完整生涯和审核门禁持续写入。
