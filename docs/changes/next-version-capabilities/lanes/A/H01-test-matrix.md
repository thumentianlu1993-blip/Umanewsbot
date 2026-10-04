# H01 最小测试矩阵（方案，未执行）

纯planner先取得真实RED；生产/第三方不作为测试依赖。下表是具体失败断言，不是既有测试收据。

| ID | 固定输入/反例 | 必须结果 |
|---|---|---|
| H01-T01 | 出生年2010且2026参赛；出生年2025但无参赛 | 前者纳入、后者不凭马龄纳入；按最近实际参赛排序 |
| H01-T02 | 2023-10-02/03、2026-10-03/04精确当地赛日 | 两端含，外侧排除；UTC跨日不改变local_date |
| H01-T03 | 2020-01-01 G1全名单12行，含9完赛、DNF、退赛、未知 | 历史名称目标12项，非胜马1项；近期实际出赛按各自证据分类 |
| H01-T04 | JPN1、港本土G1受审等级证据、其他地区Local G1、仅名称相似 | 前两明确纳入，其他Local G1排除；证据不足留等级待核；JG1配置分支待冻结 |
| H01-T05 | 跨地区两个verified namespace ID映同profile | raw两项、唯一已解析马一匹，双地区/集合归属保留 |
| H01-T06 | 同名异马、一个源键映两profile、observed/rejected/retired ID | 不自动合并；保留独立target与冲突/撤销理由 |
| H01-T07 | 全部事件参与项中的未建档对象及无horse ID对象 | 不从HorseProfile过滤消失；有源键形成未解source target，无源键保留参与项引用 |
| H01-T08 | 一场无来源名单、人数unknown；另一场已知12行缺3行 | 前者unknown人数事件；后者明确缺口，不伪造0或猜3匹身份，不宣称精确真马总数 |
| H01-T09 | 同事件legacy runner/result及current revision、superseded更正、缺pointer | 不重复计马；取当前生效证据；无pointer/不一致留冲突，不max revision猜测 |
| H01-T10 | finished/DNF/DQ/fell/PU、scratched/non_runner、declared、refused歧义 | 实际出赛有证据纳近期；未出赛不纳近期但保留历史名单；其余待核 |
| H01-T11 | month/year-only日期、missing time、空列表、0次与null次 | date-only可按真实日归属；月/年跨窗不补日期；空未知与确证0不同 |
| H01-T12 | 当前赛季跨年、未来第1/30/31天、当日计划名单、新闻第90/91天 | 使用固定season/version，未来30天与近期90天边界；未来/新闻不灌历史actual-start分母 |
| H01-T13 | 同马近期+历史+未来+新闻，多源表示顺序打乱 | membership全保留，执行队列一次，canonical摘要与优先排序不受输入顺序影响 |
| H01-T14 | cache存在、staging双候选、profile unpublished/hidden/locked、eligible但未公开 | 各层分别计数，ambiguity/hidden/blocked保留，eligible不等于公开 |
| H01-T15 | snapshot期间新增参赛项；冻结后更正删/改身份；重放旧输入 | 旧snapshot输出相同；新增/更正入新delta含原因，不回写旧分母 |
| H01-T16 | 任一页超过行数/时间/字节预算，最后页缺失或SHA不一致 | partial + cutoff理由，禁止complete freeze；复算不悄悄当缺数据成功 |
| H01-T17 | 仅用旧P0五地区/major集合、只读取published profile | 与九地区全部参与输入预期不符的真实RED，证明分母不复用旧选集 |
| H01-T18 | 原输入引用含URL query token、账户或内部正文 | 公开摘要只含脱敏计数/摘要；敏感值不写repo/日志；artifact摘要固定 |

关联既有测试：test_horse_profile_publish 的BASIC门槛/hidden/锁；test_p0_horse_profiles 的身份与参与项冲突；horse_race_records相关歧义/幂等测试。实施时按实际影响映射，不能把它们历史通过当新H01验收。
