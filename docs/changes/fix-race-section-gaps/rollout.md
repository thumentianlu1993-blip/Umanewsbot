# 交付与发布包

## 代码范围

- 同日结果缺正式标记时，在原有预算内精确请求该 race ID 的详情；404、超时、限额或无明确终态均保留暂定结果。移除缺值时伪造 complete/official 的行为。
- 举办地 D−4（含）开始赛前检查，正常节奏 3h / 1h / 10min；未纳管身份发现也保存 due/lease。十分钟唤醒，小时资格盘点保留。
- 限定 JRA 官方赛前表，名单只作 PENDING 候选展示，不写 canonical runner/participant。默认关闭新开关；BASIC 仅在 UNMANAGED、无人工锁且字段空白或可证明由本来源写入时补赛时。TRA 正式赛卡接管后停止 JRA 回退。
- 过期 scheduled/running 显示“赛期已过，资料待补”；finished 无合法公开赛果显示“赛果待确认”。首页、列表与详情沿用同一正式结果门禁，筛选清除伪即将开赛/伪完赛。已有授权的暂定结果明细继续可见，但不显示正式冠军、不计入 finished 筛选；关闭公开权限后明细仍隐藏。显示北京与当地时间，不猜官网尚未公布。
- 无模型变化、无新增迁移、无新队列。扩展现有只读 audit 输出。

## 容量与有限启用范围

2026-09-17 只读复核：每 provider/region 每日 192 请求、1 GiB 预留响应量。9 月 10–12 日英国 TRA 已达到 192 上限；本次不提高配额。详细现场值见 evidence/capacity_snapshot.json。

JRA 的目录共享、成功 URL 持久复用和接管停止查询是必需条件。以当前 103/104/105 分别 9/19、9/20、9/21 的三场中央赛事计算，按完整自然日保守上界：D0 144 + D−1 24 + D−2 8 = 176 次详情；首次目录最多 1 次，正常上界 177，余量 15 次。已知 15:45 开赛及 TRA 提前接管会降低实际请求。故障采用退避且仍受硬额度约束；多场同日或未取得绑定时可能不能满足全部正常频率，必须在 audit 报告中保留延期原因，不能把受限查询宣称为达标。NAR 191/192 不进入 JRA。

首次代码发布保持 `RACE_DATA_SYNC_JRA_PRE_RACE_ENABLED=false`。启用前还需核对当时 D−4 窗口、最新预算和具体官方身份，不把上述三场测算推广成所有周末的保证。

## 精确交付选择

候选为 [PR #203](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/203)，代码与测试绑定 `d0bb40fb8defe3e9de1029aa255edd2e06e1e0c6`，完整 Linux 5,012 项无新增失败，45 项发布合同通过，原有 45 项失败明确保留。后续交接提交仅包含 docs，不替换该已验证 SHA；交付前核对所有应用、测试与配置 blob 无差异。遵守根 AGENTS.md 的 G2：必要测试、独立审核与 CI 完成后，用户选择只合并，或合并并发布该固定代码 SHA。

代码发布包：

1. 用现有 release coordinator 复核当前实际镜像、生产 release lock、活跃马匹采集的固定版本/锁/worker 依赖。不得占用活跃采集的运行窗口。
2. 现有 0078 发布合同备份及 intent；迁移计划必须为空。重建 Web、普通 worker、Beat、race_sync_v2_worker，Nginx 沿既有发布流程处理；DB/Redis/OneBot 不升级，旧 race_live 队列不消费。
3. 增加并显式传递唯一新配置 `RACE_DATA_SYNC_JRA_PRE_RACE_ENABLED=false`。现有来源、字段、配额不扩大。十分钟发现与同日精确结果补查随代码生效。
4. 核验 Django check、版本一致、服务/队列健康、audit 无新冲突；原始 828/830/829、104/105 及历史样本公开页与 DB 分别验收。正式证据仍缺失则明确保留待确认。
5. 数据动作仅包含 829/104 两条精确身份修复，使用下文 SHA 绑定 manifest；先 dry-run，通过才显式 --apply。不存在正式赛果批量写入、JRA 开关开启或付费历史补抓。其他历史清单只是审计输入。

## 两条身份修复包

`repair_race_section_identities` 是本次专用入口，只接受 829 与 104 的已核定名称/别名。默认 dry-run；在事务内核对 year/slug/名称/地区/马场/日期/时区，拒绝人工锁、lifecycle owner、已纳管或其他 projection owner。只更正名字/添加别名，不改路径、时间、状态、runner 或赛果；TaskExecutionLog 保存完整前后值及 manifest SHA，重复执行验证现状后幂等返回。任一对象漂移整批回滚。已有有效别名保留其全部元数据，仅新增缺少的 fr/ja 别名；已有停用同名别名则整批拒绝，不隐式恢复。

Manifest：`docs/changes/fix-race-section-gaps/evidence/identity_repairs.json`，SHA256 `31dbf9f1d8400f0ef33a7f7b8dd18931488bfb562fa0437c26e29febf2f5827b`。该包已在隔离数据库按真实基线 dry-run 验证，未在生产应用。获准精确发布包后，使用同一个文件和 SHA 运行：

```sh
python server/manage.py repair_race_section_identities --manifest docs/changes/fix-race-section-gaps/evidence/identity_repairs.json --sha256 31dbf9f1d8400f0ef33a7f7b8dd18931488bfb562fa0437c26e29febf2f5827b
# 前置 dry-run 无 drift/owner/lock 冲突后，在已批准的发布包内添加 --apply。
```

如实际运行路径是 `/app/server/manage.py`，相应调整文件挂载路径，不修改文件内容或 SHA。生产 apply 前先保存目标基线/备份；apply 后核对 slug/public_path、原始名与别名及 TaskExecutionLog。仅 alias/name 可被此包更正，不将其当作结果恢复。

## 数据修复输入与仍缺证据

- evidence/target_baselines.json：现场 828/829/830/104/105 原值、来源引用、人工锁与当前版本。829 需将 `PRIX DE CHAMBL Y` 精确更正为 `PRIX DE CHAMBLY` 并保留旧别名；不能全局删除空格，slug 不变。既有缓存精确 ID 为 `rac_32298273488`、Auteuil、当地 2026-09-17；赛时/七行名单可回放，但正式性仍须独立验证。
- 104 官方名为 `産経賞オールカマー`，站内为 `オールカマー`，需要经过目标基线核对添加精确别名；105 使用 `神戸新聞杯`。官方 URL 在原始 upstream.json；不得用通用 apply 将 JRA RUNNERS 候选应用为 canonical。
- evidence/historical_inventory.json：复用现有 recovery inventory 在生产 READ ONLY transaction 下冻结实际 79 场，范围 2026-08-16～09-13；美国40、法国16、日本14、英国9，均 missing_result。没有可据此直接应用的正式结果，禁止批量 scheduled→finished。后续 apply/verifier 仍需要逐目标来源证据和 SHA 绑定的 manifest。
- 这批历史记录的过期赛前展示由代码修复；“历史结果补齐数量”当前为 0。不将清单冻结、展示修正或 dry-run 误称为数据恢复。
- JRA 的真实自然 D−4 持续调度、最终编号更新与线上 TRA 接管必须在单独绑定的启用范围验证；离线两场样本和手工补齐不能替代自然调度验收。

## 停用与恢复

JRA 配置由进程加载。先停相关派发，等待有界在途任务退出或终止对应 worker，再以 false 重建相关 worker/Web，确认所有进程载入 false 后才视为停用；只改 .env 不生效。关闭不删除已核验赛时或正常 TRA 赛卡。

生产普通代码 rollback 继续禁用：发布中断用同一 exact intent 恢复；发布完成后问题前向修复。数据误写按目标级证据纠正，不整库覆盖。授权与包内容漂移规则只引用根 AGENTS.md。
