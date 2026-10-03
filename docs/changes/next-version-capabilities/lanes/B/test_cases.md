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

## B002-P2 返修专用案例

- P2-01：URL reason、控制字、129字符转unknown，合法selected/region_window_limit/空码保留；receipt记录实际替换数，防止重新开放URL。
- P2-02：实际来源包manifest/file摘要、receipt/schema/release/observation、固定28天cohort与每个ID/hash/updated_at绑定；错误manifest、错observation/release/schema、缺receipt、篡改cohort、越范围ID/hash/updated_at均在连接前拒绝；匹配案例content收据保留来源摘要。所有包是离线synthetic。
- P2-03：proposal必须为该测试模块登记python profile；不修改共享配置或runner。

## B-003 转存与宿主验证测试设计

依据原R对15b293ce的APPROVED transfer方案，在本地实现；接口仅注入copy/probe动作，CLI只核本地包，无DB/docker/SSH调用。完整方案的验收映射如下；模型/人类事实核验仍保持原状态。保留已审exporter字节。无Django/Celery/迁移/服务改动。

| 用例 | 验收 | mutation |
|---|---|---|
| T01 | metadata/content manifest、精确文件清单、SHA、receipt、来源selection/schema/release、全部数量/地区/时间/输入/脱敏hash一致；正文不输出 | 跳过任一身份/hash/来源或数量校验 |
| T02 | 路径绝对且无..，目录0700/文件0600，无symlink/hardlink/FIFO/额外文件，文件与总量边界等号接受/超限拒绝 | resolve吞链接、无限读取、忽略权限/extra |
| T03 | copy前后固定container/image/release/script/manifest核验；漂移拒绝，无DB重采 | 省略post probe或改包后仍final |
| T04 | 中断、timeout、回传丢失保留attempt/source commitment；先inspect/恢复同attempt，不新开复制；部分包不complete | unknown后再次copy、partial当成功 |
| T05 | final同包幂等不再copy；不同包/损坏冲突，不覆盖；并发lock自动释放 | 覆盖final或裸永久lock |
| T06 | 空间不足在copy前停止；预算≥包上限加staging副本；phase超时不交付 | copy后才检查空间、超时继续rename |
| T07 | source_lost且无完整stage标丢失；有完整stage及已绑定pre承诺可独立验收，无承诺保持unknown | 原容器消失伪造成功或盲重采 |
| T08 | 同FS rename、file/dir fsync；final或receipt写失败保持unknown，恢复先查final；不能以rename成功猜receipt完成 | 忽略fsync/receipt错误、自删未核产物 |
| T09 | host_verified后仍R未收；只有独立R回执精确绑定capsule/manifest/obs才delivered_to_R | producer自签R交付、错hash回执 |
| T10 | CLI错误只输出固定code；所有fake异常含合成PRIVATE也不泄露；影响proposal含新模块/测试、既有export测试读取的fixture与python profile | traceback/正文输出、fixture映射docs-only |

测试使用合成producer包、注入FakeAdapter、fake disk/time/故障；不会以callback合同声称真实传输超时已证明。真实命令adapter/capsule仍待精确技术核对，Linux正式收据另行由协调者安排。

### B003-P2-01返修

T10增加metadata/content counts精确键集与严格整数预算测试；extra string/nested字段必须CLI固定错误码/nonzero且无注入文本，transfer不得生成host_verified/transfer.complete。
覆盖缺键、非dict、bool/float/string/null/nested/负数/超限；有效包白名单整数摘要保留。可捕获mutation为去掉set(counts)精确匹配、放宽type is int或重新原样输出receipt.counts。

## B005 CI-v2 补充测试设计（原 R 已审 v2 方案范围）

- 保留 PGGuardTests 1 项、PostgreSQLContracts P01-P12 全部原 ID；正式 collect 零连接、无 skip，默认 Django profile 实际执行。
- InternalCIGuardTests 12 项：监听端点/inode owner、PID 重用、四类 namespace、私有 tmpfs、owner/mode、symlink、嵌套 mount、propagation、device、未知字段及 collect。每个拒绝分支通过 connect spy 证明零连接；mutation 为删除对应 preconnect check。
- 正常路径：实核固定 PG PID/start/socket/namespace/tmpfs 后 bootstrap 专用 DB/角色/nonce，再运行原 PG12（SQLSTATE、RR、timeout、budget/UTF8/hash）。本地模拟证明不替代真 PG。
- 权限/异常：admin 非 superuser/createdb/createrole，reader SELECT only；后端归属或 SQL 目标错连接后零写入；创建途中失败只清理本次已核 ownership 的对象，未知保留并由自有容器生命周期回收。
- 外部 manifest 模式保留原严格 schema/源码/hash/目标保护；internal-CI 显式独立，拒绝继承环境、未知模式、伪造 image。无 Django migrations / Celery / 生产网络。
- 单容器480秒含清理，最后20秒预留；原13项分母不减少，新增守卫 IDs 报 coordinator；formal worker PG GREEN 与 Linux隔离 proof 尚待窗口。
