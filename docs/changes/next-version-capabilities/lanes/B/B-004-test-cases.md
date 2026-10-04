# B-004 完整测试设计（方案待审）

日期：2026-10-03，Asia/Shanghai。对应B-004-plan.md；仅测试设计，未执行。
无业务模型、Django/Celery、迁移或生产行为变化；合成DDL仅供真实SQL契约测试，不宣称迁移验收。

## PG16真实契约

| ID | 验收与层次 | mutation/故障 |
|---|---|---|
| P01 | 未修改CLI metadata/content真SQL走通，六dataset精确count/region/聚合/input sha/bytes；完整来源包复核 | SQL参数次序错、PG函数不兼容、漏字段/过滤 |
| P02 | 真PG READ ONLY/REPEATABLE READ/UTC及15s/1s/15s settings；DML有权限的角色仍SQLSTATE25006，rollback无写 | 只检查文本、用权限拒绝冒充READ ONLY |
| P03 | reader快照建立后writer提交insert/update；counts/details不变，新事务见变化 | READ COMMITTED或分两次事务 |
| P04 | CLI自然28日+精确参数边界分别标证据，>=start/<cutoff、五地区限制、NULL source crawl保留 | <=cutoff、去掉地区/未知来源 |
| P05 | statement pg_sleep>15s、锁冲突>1s、idle>15s；固定失败码/无complete、rollback和连接关闭 | 放宽timeout、异常正文输出、失败留完整包 |
| P06 | metadata缺列拒绝；metadata后额外列使content schema摘要漂移拒绝 | 缺列继续、content不检查实际schema |
| P07 | input hash/updated_at变化、ID丢失、source metadata篡改拒绝；未连DB反例与真DB漂移分别记录 | 只信selection文件名、略过更新 |
| P08 | 对六dataset预算等号与+1，超限count先拒绝，不截断明细；空cohort可完整metadata | fetch截断当成功、>=边界错误 |
| P09 | content=150/+1、单篇512KiB/+1、总30MiB/+1、UTF8多字节；先size查询后正文 | 按字符数计预算、绕过size、截断正文 |
| P10 | NULL可空日期/标志/引用、空非NULL正文、SQL derived函数与Python input SHA一致 | 用NULL正文简化模型、COALESCE路径错 |
| P11 | script/release/marker错在DB前失败；只接合成目标/env；schema drift每案新obs | 继承宿主POSTGRES、装载.env、错绑定先连 |
| P12 | CLI query failure/进程异常输出固定码，目录无complete；成功目录重跑不覆盖 | 错误堆栈/密码泄漏、obs覆盖 |

若真实PG证据受资源/镜像/权限阻塞，记未完成；fake不替代P01–P10。事务wall180秒不延长；外部测试驱动≤8分钟，超时回收仅自身进程/容器。schema最小集与生产全schema界限明确。

## argv runner / 本机合成烟测

| ID | 验收 | mutation/故障 |
|---|---|---|
| D01 | 精确argv/shell=False、absolute binaries、Unix socket、固定ID/image/marker/source root/obs；从实际probe信息合并 | 回显capsule、TCP或环境改target、shell注入 |
| D02 | 包SHA/每文件SHA/私有目录/无links、隔离Python imports及3.12最低约束 | 同名包劫持、缺/extra工具/老Python仍跑 |
| D03 | probe missing container=lost；daemon错误/timeout=unknown；capture未完成=capture_unknown | 不可达当丢失/完成、虚构marker |
| D04 | 自有Python child/grandchild超过56s内deadline，TERM→KILL→wait总≤60；不可回收保持unknown | 只杀父、killall、无限communicate |
| D05 | stdout/stderr洪泛有界并杀自有组，返回固定码无原文 | 管道deadlock、无限内存/落原文日志 |
| D06 | CLI取消后exec helper仍活跃；自timer退出与PID/op-id核验、PID复用不杀 | CLI退出当helper已停、杀其他capture |
| D07 | cp部分/完整回传丢失先查stage/receipt，不新copy；sourcehash/identity漂移保留invalid | 未知盲重试、复制后不probe |
| D08 | path option/..、symlink/hardlink/FIFO/错误uid/权限/extra文件拒绝 | resolve吞链接、越界读/写 |
| D09 | 真实本机合成容器read-only probe/cp可回收，输出包host独立核hash；无服务/生产挂载 | fake成功当Docker/SSH现场证据 |
| D10 | crash/fsync/rename/receipt失败及重复调用：final同包复用、异包不覆盖、flock释放 | 丢收据就重采、永久裸锁、覆写 |

D01–D08/D10先纯Python实际子进程+fake Docker响应，不连接网络；D09单独资源窗口。实际SSH调度未验证前不声称外部链路可用。

## R来源与接收

| ID | 验收 | mutation/故障 |
|---|---|---|
| R01 | 原R独立核同一包并来源thread/turn精确绑定；producer issuer字段不产生来源事实 | producer自签R、同uid/0600当身份 |
| R02 | root来源收据错线程/manifest/capsule/obs/无实际包均阻止record_delivery入口 | HMAC合法就忽略R来源 |
| R03 | host桥接短时材料仅内存、不进argv/env/stdout/仓库/样本artifact；producer没有控制目录映射 | 长期secret、把材料交B/producer |
| R04 | R.received与host producer收据分开；写失败/回传丢失核实际结果，不能靠host_verified转R已收到 | rename或review通过当收包 |
| R05 | 同一ACK幂等、错签名/错包拒绝；来源记录可审、secret无输出；model/machine/human原状态不变 | ack重放别包、machine→human verified |

这些用例验证托管与收据，不代替人类gold核验。root/R来源核验用受信调用面的fake记录反例，真实接收需实际原R独立收包证据；缺证据停host_verified。

## 执行与影响计划

- 每项先真实RED再最小GREEN；导入/环境错误单列，不计行为RED。
- PG按P01/02/03、P04/06/07/10/11/12、P05/08/09顺序单批执行；每类避免重复建全部业务schema，无Django migrations/full suite。
- runner与来源fake单独python profile；PG集成用专属隔离PG profile/受控驱动。新路径/fixture/工具manifest必须登记behavior domain，不能docs-only；共享catalog/profile由root统一处理。selector优先catalog.tests，因此原exporter测试被transfer当fixture import的依赖必须在该catalog条目声明双域；本轮仅同步proposal，原root最小selector RED/GREEN与30例证据保持独立。
- 本次只校验文档引用、固定script摘要/边界和workflow contract/diff，不运行测试矩阵或Docker/SSH/PG。
