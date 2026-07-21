# P0 马完整资料补全收尾发布边界

## 当前状态

- 工作分支：`codex/p0-horse-info-completion`
- 用户已确认首批 50 匹全部纳入。
- 生产候选提取只读完成；本地已完成五地区 50 匹研究解析、人工证据补证和审核工作簿。
- 当前严格完整资料为 `40/50`：日本、法国、中国香港、英国 `40/40` 达标；美国 10 匹的
  Equibase 官方总数已和去重、补证后的 `198` 次备用逐场记录数量对齐，但逐场官方性仍待
  授权数据或人工 Full Charts/Lifetime PP 核验。
- 50 匹研究产物共有 `1439` 条履历记录，其中 `1432` 次实际出赛、`7` 次未出赛；缺少实际
  出赛与多采待去重均为 `0`。Fort George 已补齐为 `13/13` 次实际出赛。
- 审核工作簿包含 `2050` 条逐字段证据、`1439` 条逐场履历和 `2679` 条逐场字段三层证据。
- 研究 JSON/Excel 是只读审核证据，不是 `complete_horse_profiles --commit` 可直接应用的
  模块审核 artifact。当前未创建 P0 来源、未写生产 `HorseRaceRecord`、未发布马匹。
- 美国 HRN 的正式请求、缓存复放与研究解析现均需四字段身份完整命中；旧 `complete` 履历在
  新权威字段默认未知时由迁移降为 `needs_review`，原聚合完整状态也同步撤销，不得沿用旧
  完整结论。
- source cache 已升级为 `v2`，必须用缓存自身马名/alias 绑定请求马并保留来源总数的来源名、
  URL、带时区核验时间。受控网络只允许五个已登记 HTTPS 主机，关闭自动重定向并逐跳校验。
- 跨 provider 必须完整匹配四字段身份；数据库和研究/工作簿生成器都独立 fail closed，只有
  `source_records_verified` 可进入完整。官方零场允许空记录快照。
- 日本 10 匹授权离线 replay 已真实重建；严格 URL、同源 ID 大小写旁路和 ignore 保留既有
  APPLIED 完整状态均有回归。
- 第 4 名及以后统一归一为 `unplaced` 并通过真实审核 apply 落库；年份精度履历保留但在
  adapter 和数据库两层均保持 partial。人工主 URL、佐证 URL 和血统证据 URL 均使用严格
  HTTP(S) 校验。
- 自动补充来源必须通过同 provider 一致 external ID 或双方完整四字段身份锁。总数证据按
  “数量 + 来源名 + 严格 URL + 带时区核验时间”原子组更新；cache 硬字段验证类型与日期格式，
  研究摘要优先按官方总数对账。
- 父母实体唯一同名结果不再自动采用，external ID 按不透明原值比较。当前 v2 JSON/Excel
  通过 `116` 行 manifest 固化此前已审核父系和母系字段，并归并为 `55` 个唯一父母来源身份；
  全部 `source_identity` 已包含马名、父名、母名和出生年。出生年另由
  `reviewed_by=codex_manual_source_review` 的 approved artifact 提供，不记为项目负责人逐字段
  审核 `55` 个出生年；旧产物保留。
- 最终冻结 SHA-256 为：v1 JSON
  `55d80abed2b76a2d7fcf0cb97aadff800c3130c3815e84d8e6eb5b1c16b4befd`、v1 workbook
  `4b68b87a076793eab0acc2357762afbd0c0fcaf2282fcf4122e3a2a855c2b696`、v2 JSON
  `a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7`、birth-year evidence
  `ed9f6419dccd41485b96884410ea9ab5976d8ab5ba2acfb97e03837a7a3deb54`、parent identity
  manifest `b211d9040814b0b56ec30e8ef8930fdc10f4140a3a660cf491fcae12d0b6ab2b`、v2 workbook
  `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`。
- Kentucky Wood 的父系 Balko 已从错误的 Netkeiba `000a02bd3f`（1925 年同名马）纠正为
  Racing Post `595446`（2001，Pistolet Bleu / Ella Royale）；v1 不改，纠错只进入 v2 审计。
- 本轮只获实现授权，未获 commit、push、merge、部署或生产写入授权。

## 实施边界

1. 所有网络路径默认关闭，测试使用 fixture/cache。
2. 首批真实 dry-run 只允许本地或生产备份副本；生产网络抓取另需运行态门禁。
3. 任何 adapter blocker 不得通过降低完整资料标准解决。
4. 普通赛事履历不创建低质量 `RaceEvent`。
5. 主线集成必须解决实时赛果分支与 P0 分支的迁移/模型冲突，并在集成后重新审核。
6. 当前专项组合回归为 `282/282`，包含既有 P0 完整档案测试整类；该结果不改变美国逐场
   权威性阻断和生产 `NO-GO`。

## 第十四轮：父母来源身份与 v2 产物最终冻结

- 本轮在第十三轮 `277/277` 基础上增加 5 项回归，最终 Python 组合回归为 `282/282`。
  Node summary/path 测试、Django check、迁移漂移、Python `compileall`、OpenSpec change
  strict 通过、all strict `30/30`、公式错误扫描和 `9` 张工作簿预览均通过。
- 父母实体来源身份现在全局执行 provider namespace + opaque external ID 一致性；自动
  Netkeiba 候选 URL 只接受精确 `https://en.netkeiba.com/db/horse/<id>/`，凭据、端口、
  query、fragment 均拒绝。
- 工作簿 builder 默认读取 v2 JSON、输出 `-v2.xlsx` 与 `previews-v2`，环境变量覆盖配置；
  frozen v1 workbook / previews 目标会被拒绝。v1 JSON 与工作簿字节保持不变。
- reviewer 最后一条意见对应的硬编码结论已改为 `careerConclusionRows(horses)` 动态统计；
  法国、中国香港、英国和美国数字来自当前 horses 输入，具名马不存在时不制造结论。summary
  test 先以缺少导出取得 exit `1`，修复后 summary/path tests 均 exit `0`，builder/summary
  Node `--check` 通过；重建统计保持 `50 / 2050 / 1439 / 2679 / 9 previews / 0 formula
  errors`，首页预览人工检查无溢出或遮挡。
- 本轮只完成离线证据和文档/OpenSpec 收口，没有生产写入、部署、发布或网络 career crawl。

## 第十五轮：来源调研与批次文案动态化（2026-07-20）

- `buildSourceResearchRows(horses)` 使法国、英国、美国、Fort George 及日本/香港无缺口结论
  均来自当前 horses 输入；无对应地区或具名马样本时不制造结论。
- `workbookBatchMetadata(horses)` 使标题、范围、总表 sheet 名及美国字段字典中的批次数字
  来自当前 horses 输入；默认输出文件名继续绑定冻结 50 匹 artifact。
- 两轮 RED 均因缺少新 helper 导出使 summary test `exit 1`；GREEN 后 summary/path tests
  均 `exit 0`，builder/summary Node `--check` 通过。
- v2 workbook 重建为 50 horses / 2050 field evidence / 1439 career records /
  2679 record evidence / 9 previews / formula errors 0，SHA-256 为
  `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`。首页与来源调研页
  人工检查无溢出或遮挡；生产仍保持 **NO-GO**。

## 第十六轮：地区汇总与字段矩阵动态化（2026-07-20）

- `regionSummaryConclusion` 对非空地区按硬字段、血统、missing/excess/unknown 与 career
  completeness 动态生成结论，美国追加逐场官方性说明；无样本明确显示“当前输入无样本”。
  `japanBatchConclusion` 空样本不再产生 `0/0` 成功结论。
- `regionSourcePolicy` 与 `regionNextRoute` 改为通用来源能力和入口；字段矩阵不再固定
  Fort George/JBIS 本批覆盖说明或样本 URL，无样本也不再因 `0=0` 显示可正常获取。
- RED 阶段 summary test 因缺少 `regionNextRoute` 导出失败；GREEN 后 summary/path tests
  和 builder/summary Node `--check` 通过。
- 动态长文本视觉检查后仅调整 summary `A5:M9` 行高 `42 -> 72` 与 matrix data rows
  `34 -> 56`；重建保持 50 / 2050 / 1439 / 2679 / 9 previews / formula errors 0，SHA-256
  为 `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`。首页与字段矩阵
  复查无裁切或遮挡；生产仍保持 **NO-GO**。

## 第十七轮：血统结论空样本保护（2026-07-20）

- RED 证明 `pedigreeCompletionStatement([])` 会把 0 匹误判为全部补齐；GREEN 后该函数与
  `regionPedigreeStatement([])` 均返回“当前输入无样本”，非空输入行为不变。summary/path
  tests、Node `--check` 与 `git diff --check` 通过。
- 当前 50 匹输出最后重建一次，仍为 50 / 2050 / 1439 / 2679 / 9 previews /
  formula errors 0，可见内容与前次一致。二进制生成元数据使 SHA-256 更新为
  `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`；此后不再重建，
  生产保持 **NO-GO**。

## 当前生产结论

- `NO-GO`：既定要求是每批 50 匹全部达到完整资料，当前 `40/50`，不得申请生产 commit 或
  每地区公开样本授权。
- 当前基础字段、三代血统和已知履历数量差异均已清零；下一轮只针对美国逐场权威性，按授权
  Equibase/Equineline/TrackMaster 数据或人工 Full Charts/Lifetime PP 路径复核。
- 达到 `50/50` 后，必须重新生成带模块 diff、来源 evidence manifest、人工审核状态和冻结
  SHA-256 的正式 dry-run artifact；研究工作簿的人工通过不能替代模块审核。
- 正式 dry-run 通过后仍需为准确集成版本重新取得用户授权，并执行生产 HEAD/容器/锁/备份/
  `/healthz/` 门禁，才可进入 `6.5` 和 `6.6`。

## 恢复点

- 实现期间只产生 worktree 文件和本地 artifact。
- 未取得发布授权前不提交、不推送、不部署、不写生产。
- dry-run 失败时保留原 artifact、请求统计和缓存，不覆盖后重跑。
