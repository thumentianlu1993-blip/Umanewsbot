# A028：H02 首个离线缓存复用切片

任务 A028-H02-CACHE-REUSE-FIRST-SLICE-001，基线 `6e6aded22764ebee3d6a97f2834f47d4b4baa7bb`（实际远端main/PR239），独立worktree `/Users/mentianlu/.codex/worktrees/a028-h02-cache-reuse/umanews`、分支 `codex/a028-h02-cache-reuse`。最初本地origin/main陈旧，已只读核远端并fetch准确对象，在尚未修改的新worktree校准；原5482冻结树、其他线不改。按ROOT用户范围调整保留公开页/资料/新闻和可靠性核心，不推进QQ下线/后台交互。明确授权覆盖本地实现/窄测/演示/commit；没有生产、合并、抓取/付费/外发或4GiB隔离授权。

## 已实现接口与边界

新增 `stable.services.horse_cache_reuse.plan_cache_reuse(snapshot, cache_records, entity_versions, *, as_of, max_age_seconds)`。完全纯函数，无Django/DB、Celery、网络、目录读取或公开写入。H01 `plan_inventory`及其验证、规范摘要、时间/身份字段校验复用原代码；H01目标顺序/未知身份分母不丢。旧 `horse_identity_html_parse`/离线reparse能定位外部ID，但没有hash/来源时间，更不能把赛果页中的多条马链接当某一匹马档案身份；本切片不凭这些不完整证据补造强身份。现有completion的source/external_horse_id/fetched_at可供未来producer适配，但本轮不改共享服务入口或持久化。

cache_records显式带ref、horse_key、profile_id（可空）、source_ref、来源时间（可空）、UTF-8原始内容、SHA256（可空）、parse_status；后者是可信producer的解析事实，不是此函数完成了HTML/档案解析。内容必须逐件hash一致；mtime、名字和“cache present”均不当身份或时间依据。实体版本和新鲜度为强制注入值，没有默认业务阈值。示例3600秒仅测试参数，不是用户标准。输入结构按H01严格验证；缓存最多10000件、单内容128KiB、累计内容2MiB，是首切片技术处理边界，超界拒绝，不扫描全历史目录。

| 条件 | 输出 | H03候选 |
| --- | --- | --- |
| 强身份一致、最新原件hash有效、完整、年龄≤注入阈值 | reusable | 内容及来源/身份证据 |
| 缺缓存、过期、解析不完整或hash不符 | refresh_required | content=null及原因，不能拿旧内容当新事实 |
| 同外部ID冲突档案、缓存档案声明与强身份不符 | identity_conflict | 不生成 |
| 同时最新原件内容hash冲突 | cache_conflict | 不生成 |
| 未核/撤销身份、缺实体版本/来源时间/hash、未来时间 | insufficient | 不生成 |

最新记录部分失败不回退较老成功记录；时间按带时区实际瞬间比较。跨来源ID必须都经H01验证绑定同profile，才合为一实体；同名/相同payload的异马不合并。每(entity_key, entity_version)最多一个候选及稳定idempotency_key，带target_refs/identity_evidence/cache_evidence；总体摘要绑定H01摘要、缓存输入、注入时间/阈值和分类。H03消费者须维护实体版本，事实/版本变化不能复用旧幂等键；这里不是数据库并发唯一约束或已入队执行。缓存和公开状态分别输出，始终published=false/complete=false，不冒称资料补齐或公开。

## 首批可读实例

全部是明确合成合同fixture，日期为2026-10-03，未读取真实历史或敏感数据；没有“真实数据已复用”结论。

| 输入 | 结果 | 公开状态 |
| --- | --- | --- |
| 已核jra:1→profile:1，缓存恰好1小时 | 可复用，候选1个 | unknown |
| 同身份，缓存1天前 | 需刷新，候选不携带旧内容 | unknown |
| jra:1同时绑定profile:1和2 | 身份冲突，无候选 | unknown |
| 只有缓存自称profile:1、H01无验证身份 | 身份不足，无候选 | unknown |
| 强身份及新缓存有效，但只有staging/未建公开档案 | 可复用，仍未公开 | unpublished |

完整输入→输出在runtime `examples.json`，可离线交H03；不触发任何采集或暂停旧任务恢复。

## 测试与变异覆盖

使用仓库tdd skill，沿已审版本矩阵TC-H01（旧缓存/staging-only/未知身份/重复增量）与HG-02/HG-05，独立新增16个unittest方法。RED：先仅有空决策入口，运行同组退出1；fresh边界与去重断言失败，明确目标行为缺失，非导入或环境故障。GREEN初轮发现未核身份误标冲突，已修为insufficient；最终H02 16＋H01 21共37项通过，零跳过。命令 `PYTHONPATH=server python3 -m unittest stable.test_horse_cache_reuse stable.test_horse_target_inventory -v`，真实输出red.log/green.log。git diff --check通过。

变异对应：取消hash校验会误复用损坏内容；`>`改`>=`破坏阈值边界；仅看profile自称会绕过强身份/撤销；名称或payload去重会合异马；删entity_version会无法幂等区分新版本；按遍历顺序取缓存会丢冲突/时区等价与确定性；旧成功兜底会掩盖最新失败；把staging当public破坏未公开断言；漏深拷贝会污染后续结果。包括空缓存、非法结构/时区/bool阈值、重复ref、未来时间、超界内容、输入/输出所有权等边界。纯函数不涉及迁移、DB事务或worker并发，未跑PG/全量/生产测试，无这些资格声明。

## 交付状态

只服务、独立测试、本A报告三文件；未改models/views/settings/migration、旧整组/runtime。可供H03消费的离线切片已实现，但producer真实缓存适配、来源授权/可信producer校验、H01真实分母、F03完整矩阵、真实历史抽样和公开自动链均仍待；不勾选H02全卡完成。独立原R审查由ROOT转交，本A不自授APPROVED。额度起6、实现后7；按≤1暂停/≤3逐批。无子代理/模型CLI/新构建资源/抓取/积分/reset/push/PR/merge/deploy。commit hooks禁用避免非本范围自动脚本，显式窄测已执行。
