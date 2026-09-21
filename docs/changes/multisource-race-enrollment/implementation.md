# 实施记录（2026-09-20）

用户批准实现后，在 `codex/multisource-race-enrollment` 隔离工作树实施。未操作原 horse_data 脏工作区，未写生产、启用新来源或调用真实付费接口。生产症状是否已消失不能由这些离线结果推断。

## 已落地

- 新增 `RaceEventIdentityKey`、`RaceDataSyncSourceBinding`，Enrollment 增加四个兼容默认字段；`0079_multisource_race_enrollment` 为追加迁移，旧记录默认 authority_version=1。
- policy schema=3 与旧 roster/registry 分离；route 内独立摘要。来源 ID、经核验的比赛实例键、受审 series/year 或旧候选 A0 收据一致时原子登记；名称仅召回最多五个候选。唯一约束和 PostgreSQL 排序 advisory lock/行锁保证一场一登记、一个写入 owner。
- binding 按资料能力选择；identity-only 不创建无效轮询。一个 claim 仅授权一个具体来源，并绑定源集合 generation、合同和 proof。后到来源不抢写；403/连续超时允许有期限备用，成功后保持备用来源；source-set 更新使旧 claim 失效。
- 同一 Beat/Celery 入口接入独立多源发现，旧 v1 流程保留。覆盖盘点从公开 canonical event 出发，包含未来 30 天和过去 7 天；每批最多 20 场、每场最多两个来源尝试，地区轮转及持久 due/lease 防止重复请求。与旧 selector 共享总批次额度。
- JRA 真实出马表链接→真实结果链接→登记→领取→13匹完整名单/结果→一次正式 publication 的离线链路通过。赛果名单必须与独立已核验参赛集合核对；HTML 结构完整不等于名单完整。首次 bootstrap、参与者、revision 和结果同事务提交。
- JRA/NAR/HKJC、Sporting Life、ZEturf、HRN 适配及 TRA binding 入口已接入；详情取数可从旧已核验候选、已绑定 source、受审策略中的精确发现列表或旧 URL 提示开始。URL/列表标题本身不授予身份，详情仍经强匹配。NAR/SL 只跟随同日期/场次或同 race ID 的真实结果链接，不拼造地址。
- 结果/赛时/名单 writer 共用 binding 准入；保留 v1 registry 摘要。写锁取得后重验授权截止、取消/延期、人工锁、owner 和 source-set。来源替换后相同内容使用新的授权摘要记录 observation，避免旧不可变 observation 永久阻塞重试。
- 公开读使用发布时授权快照。当前网络/写开关关闭或自然到期不删除已发布结果；显式撤销来源/身份会隐藏。赛后最后有效候选名单保留，赔率仍走既有新鲜度规则，正式名单接管后不重复展示。
- 覆盖缺口写入既有后台 incident，不发送外部通知；重复盘点去重，进入窗口外的未解决 incident 不自动消失。
- `manage_multisource_enrollment` 提供固定清单 prepare/dry-run/apply/verify。仅转换无已发布历史的 v1 登记；保留原 owner generation/source 摘要，逐 event 原子执行，30分钟期限，锁后复验关闭态和有效期，对照实际镜像提交标识或本地 Git HEAD。独立 verify 校验 binding、源集合、身份键、checkpoints、lifecycle 与收据。

## 准入收紧与保留边界

跨语种赛事身份与跨语种马匹身份分开处理。同场强锚点可跨语种去重；马号属于位置标识，`number:` 不能冒充稳定马匹 ID。跨名 runner 对齐只接受来源上已核验的 event-local crosswalk（event ID、证据 SHA、source runner ID→该 event runner ID），不创建全球马匹合并。

A0 自动冷启动目前从具有有效 baseline、原始摘要和完整名单的受审旧候选重建收据。仅有旧日历 `source_refs.primary` 的记录可触发受限详情读取，但缺少导入证据时仍进待核验，不将裸 URL 补造为 A0。已发布的 v1 历史继续走 v1；本工具不自动转换它们。v2 policy 整体变更仍须受控采用，不能把新增 route 偷换成已有登记的新政策。

## 七地区能力证据

| 地区 | 实现与离线证据 | 尚未证明的启用项 |
| --- | --- | --- |
| Japan JRA | 当场真实卡/结果缩减 fixture，13匹闭环；正反、回滚、公开读取 | 新鲜生产 policy/proof、部署与自然任务验收 |
| Japan NAR | 既有真实12匹卡结构；补充标题为明确标注的合成合同变体；同场链接筛选 | 完整原页标题/结果终态的地区 proof |
| Hong Kong | 既有 HKJC 结果样本与日期标记合同变体；明确 RaceDate/course/no | 真实完整页面与中英跨页 proof、赛前卡能力 |
| UK | 真实缩减 Sporting Life 卡；既有参考结果 parser | 新鲜列表发现、完整结果/终态的独立 proof |
| Ireland | 独立 region/operator/timezone policy；SL合成地区变体不借用UK准入 | 爱尔兰真实 fixture 和访问/条款 proof |
| France | 既有真实 ZEturf 名单；无 canonical 的缩减页拒绝身份，补标记合同变体测试；trot拒绝 | 完整原页 R/C、gallop 与正式结果 proof |
| US | 真实 SL美国卡；HRN沿用明确 partial 合同，不能冒充完整赛果 | HRN明确身份/完整终态、跨来源参赛集合 proof |

七桶都有“两来源两种到达顺序、跨语种强键、单 owner/单 enrollment”合成合同测试。这证明通用登记机制，不等于七桶实网全链已验收。缺 proof 的来源保持关闭，不更换访问方式绕过403/406。

## 验证与独立审查

实施过程中保存了实际失败再修复的场景：初始缺模块、JRA标题缺失、unsaved runner写入、缺末行仍完整、取消赛事重新投影、同号换马、名单写入后claim失效、转换锁后过期和verify漏报。固定 reviewer 多轮只读复核，核心和转换/权限新增范围均给出 APPROVED；审核不代替来源实网或生产验收。

- 本地最终聚焦测试数、PostgreSQL、Linux CI 及提交信息见 `validation.json`。
- PostgreSQL 16 使用独立 localhost:55439 临时实例，不连接生产；验证了迁移、两个来源竞争首次登记、重复请求、两个 worker 竞争单 claim、结果整批回滚和转换。
- 0078历史发布测试使用隔离、固定SHA的原迁移集合；只排除本次根目录已知0079，未知嵌套文件仍拒绝。PG历史测试同时使用可正常重复加载的独立历史迁移模块并清理。当前代码包含0079必须被旧生产文件与迁移图guard拒绝，有独立测试证明；生产准入未放宽。
- macOS 默认临时路径 `/var` 为符号链接，0078路径安全测试会按合同拒绝；另用真实 `/private/tmp` 目录复验，不改安全实现迁就环境。Linux发布合同以CI结果为准。
- fixture 原始来源/裁剪说明/SHA见 `server/stable/fixtures/jra_pre_race/all_comers_provenance.json`。测试中添加的地区/date/title变体明确标记 synthetic，不当生产证据。

## 发布状态

三新开关全部默认关闭，policy 文件路径和 SHA 默认空。尚未合并/发布，未修写生产103/104，未执行T32自然周期。0079的精确迁移、镜像、关闭态、来源scope与恢复包需要独立发布准备；不能宣称原固定0078目标的发布工具已自动支持0079。仓库全量CI、逐地区proof和后续发布验收的未完成项在 tasks.md保留。

## 2026-09-21 独立代码审核返修

全新reviewer发现的赛卡同号换马、明确更正标记丢失、赛前结果窗口三项问题已修复并复审通过。历史schema/rollback测试新增隔离，并修正CI过旧基线；最新结果与初审失败证据见REVIEW.md和validation.json，旧测试数保留历史意义。
