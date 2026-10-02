# B-002 导出器离线测试设计

依据 R 已 APPROVED 的 `a2704b2d` 采样/有界导出方案；以下将其审核过的正常、失败、预算、只读和隔离验收映射为可执行案例，不扩大生产范围。
所有输入为标记 synthetic 的本地 fixture/FakeConnection；不导入 Django、不连接生产/网络，不执行模型。
责任文件为 `scripts/f02_readonly_export.py`、`scripts/tests/test_f02_readonly_export.py`、本线命令包和报告。
无业务模型/迁移/Celery改动；数据库行为由 fake 验证 SQL/事务合同，真实PG语义需后续隔离PG或受审只读运行证据，不能称 fake 已证明。

| 用例 | 行为与验收 | 必须捕获的 mutation |
|---|---|---|
| X01 | 正常元数据包：显式allowlist、五地区cohort分母、未知地区抓取、空正文/失败/无decision保留；0600文件/0700目录与SHA manifest | 去掉字段过滤、隐藏失败/unknown、缺摘要 |
| X02 | 只读会话顺序与schema：READ ONLY/REPEATABLE READ、15s语句/1s锁、事务clock，缺列停止 | 去掉只读、改时间边界/缺列继续 |
| X03 | cohort>10000、source>100、crawl/window>20000、decision>100000/exposure>20000拒绝完整包，边界等号通过 | 移除上限或错误使用>= |
| X04 | 明细与精确计数/地区数、重复ID对账失败拒绝complete receipt | 直接信任截断/重复明细 |
| X05 | 超时/数据库异常/部分成功：清理未完成输出，不发布成功manifest；错误stdout不含原文/DSN | 把错误堆栈/partial包标完成 |
| X06 | 原文包≤150、单篇≤512KiB、总包≤30MiB；输入hash/updated_at与selection一致，否则stale停止 | 截断正文、忽略漂移/超限 |
| X07 | 内容先直落R受控runtime，stdout只计数/摘要；默认不开内容模式，无selection或非R归属拒绝 | 默认输出全文/跳过明确ID绑定 |
| X08 | 脱敏：HTML脚本/样式/表单/账号区块、URL凭据/query/fragment移除；原始和脱敏SHA分列；保留正文顺序 | 只去tag保留token、哈希混用、删除正常段落 |
| X09 | 输出路径绝对固定runtime后缀、拒绝symlink/已存在目录/非法observationID；失败不覆盖旧包 | resolve后误接受symlink、exist_ok覆盖 |
| X10 | 固定script SHA/resident release SHA/schema核对失败不连DB、不建输出；凭据仅env显式提供 | 无绑定先查询/打印连接异常 |
| X11 | CLI offline准备不访问网络；live需显式mode/绑定/env；stdout receipt只含方法/计数/摘要不含行数据 | import即连接、默认live、明文print |
| X12 | 保留集回传只承诺与计数；标签初始化model/machine/human三栏，human=not_reviewed；来源/输出异常留unknown | 模型草标写human verified |

恢复：瞬时查询/传输错误由协调者核对实际receipt后最多3次（2秒、5秒）恢复；导出器本身不自动重连，事务与snapshot失败则新observation，未知写文件结果先查manifest。
已有成功目录不得重跑覆盖；失败不续用半份快照。计数/摘要一致的成功包可只读复核，无重复发布/生产写入。
持续/子代理/review前额度检查继承用户≤1%停工及未知有界重试规则；脚本不管理账户额度或充值。

RED记录必须来自已可导入接口的行为缺失，不以ImportError/依赖缺失为RED；先X01/X08等例，再最小GREEN与边界回归。
候选影响计划需登记新scripts/test路径；不得因未映射而当docs-only或偷偷全量。当前shared rules/catalog尚未改，交协调者按测试政策组织登记/回归。
