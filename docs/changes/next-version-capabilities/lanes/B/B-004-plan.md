# B-004 / F02 真SQL与可执行转存适配方案

日期：2026-10-03，Asia/Shanghai。阶段：方案待root/原R审核，未实现、未运行。
输入：原R已APPROVED B003-P2-01返修4eafb17f，报告4c9ec84b3e1373a95b7d19b2db8f05804343b820；46 fake和四CLI反例独立通过。协调者已纳入集成3f07708a；本线未自行核该集成的运行状态。
人工门禁唯一来源仍为根AGENTS.md；本方案不代替正式执行绑定或交付授权。F02新真实样本仍0，M01依赖未解锁。

## 目标、范围与责任

补齐B003本地fake不能证明的两部分：固定exporter在隔离PG16的真实SQL/事务语义，以及既有SSH主机内可执行的argv型probe/copy runner。补全不可变工具包和已有root/R托管流程的可信接收来源。

- 拟由B拥有：scripts/tests/test_f02_export_postgres.py、scripts/f02_docker_adapter.py、scripts/f02_container_probe.py、scripts/tests/test_f02_docker_adapter.py、必要B文档。必要fixture及tool包构建代码另在实施前列出精确路径。
- B003 verifier/exporter以4eafb17f固定字节为基准；默认不修改。适配若要求变更其接口，在单独增量中列出与原R复审，不覆写已审证据。
- 不改业务模型/迁移、Compose、挂载、服务、权限、root/R角色或共享rules/catalog；共享映射提案交root统一集成。INT001-P2-01已由root实测selector优先catalog.tests；本次同步B proposal里test_f02_readonly_export.py的catalog domains为export+transfer，不仅补rules，避免漏实际import fixture的transfer测试。root共享配置未改。全部技术验证使用合成内容；不抓取、不付费调用、不触发M01。
- 本次仅文档，可用结构/引用/摘要/工作树检查验证；没有运行时行为变化，不制造文档RED。实施采用后文完整测试矩阵的真实RED→GREEN，再原R代码review。

## A. 隔离PG16短验证

### 环境与资源绑定

使用协调者核定的本机Linux执行面与专属DOCKER_CONFIG；不设置DOCKER_HOST/DOCKER_CONTEXT环境覆盖，不改变全局context。
当前C占一个短PG窗口，B不启动；提交本方案后由root安排独立短窗口，不盲跑full。

建议单批、无并发：PG容器1 CPU/384MiB，Python驱动1 CPU/512MiB，总≤2 CPU/896MiB，短批总预算8分钟；超预算停自身测试并留failure收据，不追加批次掩盖失败。资源是否足够仍由实际短验证证明。
固定PG major16镜像digest、Python3.12镜像digest、psycopg[binary]3.2.6依赖包digest与测试Git SHA；tag/旧截图不作运行证明。所有digest在root允许短窗口时只读核本机缓存，当前未绑定，不拉取新镜像/包。

- 唯一命名与labels包含B004/run-id/fixed SHA/synthetic，网络为专属Docker internal bridge，无宿主端口、无生产network/volume/socket/凭据挂入测试容器。
- 使用临时合成PG数据库与角色；admin只做fixture DDL/seed，exporter角色只给六表+django_migrations SELECT及连接权限。辅助事务语义案例使用另一合成测试角色，其DML资格用于证明READ ONLY本身拒写，不能用角色无DML权限冒充事务拒写。
- reader只从字面合成env获得五项POSTGRES配置，禁止继承宿主环境或加载.env/settings。连接目标host只准本次PG service名，DB名带run-id；启动先核server_version_num=16xxxx/current_database/session_user/本次container+network labels。摘要不输出密码或DSN。
- 驱动源码从固定Git对象导出到专属runtime archive，readonly挂载；产物落本次专属runtime，0600/0700。不依赖main变化的工作树。

### 合成schema与数据

public中仅建stable_newsarticle、stable_newssource、stable_crawljob、stable_productionwindow、stable_windowcandidatedecision、stable_racenewsexposure及django_migrations，覆盖export.REQUIRED_SCHEMA所有列。
DDL逐列静态声明并对照当前server/stable/models.py类型：bigint主键/引用id、timestamptz日期、nullable published_at_verified boolean、各bool、smallint分数/rank、integer计数、varchar/text内容；正文列NOT NULL DEFAULT ''，可空引用/日期保留NULL。不把所有列简化为text。
newsarticle包含CONTENT_FIELDS全部字段和source_url；django_migrations至少app/name并保留id/applied。事件等外部引用仅是bigint合成标识，不补业务表或宣称已验证Django FK/迁移约束。
固定DDL/seed SHA、列名+类型+nullable清单留收据。fixture对照仅证明此输入契约；不能声称等于完整生产schema或production schema SHA。

基线约12条新闻覆盖五地区、失败/未发布、空正文/无HTML、曾发布后撤回、duplicate、窗口外与非目标地区；3来源含停用/未批准/NULL字段；NULL source crawl与publish/crawl windows；decision仅publish window纳入；homepage与非homepage exposure分开。所有标题/正文显式synthetic。
SQL生成器不从真实metadata或保留集取数据，扩界案例用generate_series生成至对应预算+1，逐场景重建合成库，不共用上次损坏schema。

### 真SQL执行与分层证据

1. 未修改exporter CLI metadata实跑：固定script/release synthetic marker，真实psycopg连接，核counts、region、derived sha256/convert_to/octets、聚合、未知抓取/失败保留与完整manifest。
2. 从该真实metadata由fixture custodian产生≤150明确ID/hash/updated_at selection，再未修改CLI content实跑；核先实际来源包验证、再真实DB/schema/大小/漂移、脱敏输出与host verifier独立验收。
3. exporter.readonly回调配真实连接检查current_setting、backend PID、UTC、statement/lock/idle timeout；有DML资格的合成角色在READ ONLY中INSERT必须SQLSTATE25006，rollback后新事务可读且无写入。
4. 用两条真实PG连接及事件同步：reader在observation/count查询建立快照，writer提交新增/修改，reader随后cohort保持同一snapshot且counts=details；新事务才见新增。用薄cursor observer触发writer，底层仍真实execute/fetch，不替换SQL结果或READ ONLY实现。
5. CLI自然28日窗口用距边界≥1秒的fixture，核实际事务clock；精确>=start/<cutoff另对录得的实际SQL模板用固定参数与边界fixture执行。两证据分别标识，不把固定参数case称自然CLI捕捉了精确同一微秒cutoff。
6. 锁冲突、pg_sleep、idle timeout在exporter.readonly真实会话里制造；驱动留SQLSTATE/耗时/rollback outcome，不输出DB异常正文。statement/lock CLI失败预期database_read_failed；idle断连可能在cleanup映射local_operation_failed，二者仅允许固定码且无complete，实际结果如实保存，不据fake预判。180秒wall alarm仍原值，不为测试改生产脚本或默认timeout。
7. schema drift：缺列在metadata schema校验拒绝；metadata后给synthetic表增加列改变实际schema摘要，再content拒绝source_schema_drift；输入hash/updated_at变化由publish_content拒绝stale_input。每案新observation不覆盖旧成功目录。

这些PG证据不证明生产连接、权限、锁负载、样本真实性或gold；正式运行仍会检查实际schema/release与bounded cohort。

## B. 既有SSH主机内argv transport runner

### 工具包与配置

主机执行Python选定3.12，作为首版最低支持版本（与Dockerfile一致，未声称更旧解释器兼容）。需POSIX flock、SIGALRM/setitimer、setsid、killpg、selector与目录fsync能力；不满足则停止，不安装/升级主机运行时。真实主机Python版本尚未核。

固定工具包包含私有tools/scripts/空__init__.py（打包生成、SHA明确）及已审exporter/verifier、新adapter/container_probe；隔离模式Python入口显式插入此私有tools根，拒绝被当前目录/用户site/PYTHONPATH的同名scripts包覆盖。模块不得导入Django或.env。
package.manifest精确清单+每文件SHA+Git SHA+Python版本约束；从Git对象提取，打包后重算每文件SHA，部署前后各核一次。缺/额外/链接文件或权限错误拒绝；最低版本与固定版本分开记。

execution-manifest独立于B003精确键capsule，绑定tool package SHA、transfer capsule SHA、absolute Docker/Python binary与本机Unix socket、host/container工具根、observation/source path、runner budgets、owner/root/R thread与operation-id。不能把新runner键偷偷塞进既有capsule或省略capsule原绑定。
container只放exporter及轻量probe需要的固定文件到独占/tmp目录，仍不增加mount/Compose或借horse。probe数据读取限该stage及resident marker，不连接DB；自身PID/退出marker只写独占control子目录，不改producer observation文件清单。

### 精确argv合同（全部槽位未绑定）

所有调用shell=False，禁止任意命令文本与自动ssh重连；adapter运行于既有SSH主机，使用该主机本地Docker CLI，SSH仅为既有受控调度通道。Docker executable/Unix socket/连接身份由root只读实核，禁TCP远端endpoint；不从环境猜context。

```json
["<ABS_DOCKER>","--host=unix://<BOUND_HOST_SOCKET>","inspect","--type","container","--format","{{.Id}} {{.Image}} {{.State.Running}}","<FULL_WEB_ID>"]
```

image revision用固定image ID的独立image inspect allowlist值核对，不打印完整inspect/env/labels；marker由容器probe核对，三者必须一致。

```json
["<ABS_DOCKER>","--host=unix://<BOUND_HOST_SOCKET>","exec","<FULL_WEB_ID>","<BOUND_CONTAINER_PYTHON>","-I","<ABS_CONTAINER_PROBE>","--binding","<PRIVATE_PROBE_BINDING_JSON>","--operation-id","<OP_ID>"]
```

probe binding只含固定script/marker/输出root/obs/manifest与自身摘要、uid/budget，不能是任意path/命令读取器。输出固定小schema≤8KiB：state与B003 IDENTITY/uid；由host inspect提供container/image身份证据，probe提供marker/script/manifest/file type/path/uid，再合并返回adapter。两套证据都实核，不能原样回显capsule值冒充probe结果。
probe须lstat检查每级容器路径、script/probe/hash/owner、manifest≤64KiB/no links；完整manifest吻合才complete，无manifest但活跃capture标capture_unknown。容器不存在与Docker不可用/通信超时分开：前者source_lost，后者unknown。固定source_root+obs的规范路径由adapter检查，不因capsule存在就接受任意目录。

```json
["<ABS_DOCKER>","--host=unix://<BOUND_HOST_SOCKET>","cp","<FULL_WEB_ID>:<BOUND_CONTAINER_OUTPUT_ROOT>/<OBS>/.","<NEW_PRIVATE_HOST_STAGE>/"]
```

路径不得以option形式注入、..、symlink或越过固定临时/host artifact根；源只读、destination由B003独占创建。同一copy前后重新probe/inspect，漂移保持invalid。

### 限时进程回收与未知结果

runner用Popen(argv, shell=False, start_new_session=True, stdin=DEVNULL)建立自有PGID；最小受控env，stdout/stderr有界流式读取，超输出上限立即终止自有进程组。不会把原始stderr或任何正文返回模型/日志。
每次预算≤60秒，其中主命令最多56秒，保留2秒TERM与2秒KILL/wait回收；用monotonic deadline/select≤100ms间隔，不靠无限communicate等待。非零/timeout/output overflow只返回固定码、耗时和拥有进程的退出证据。
PGID/PID绑定创建时间与本次op-id，不能按名字pkill/killall或终止服务。测试需证实孙进程被回收，不只Popen父进程退出。

- kill Docker CLI不等于docker exec内probe停止：probe自身有≤10秒wall timer，独占op-id/PID收据及退出marker。若CLI中断，另一次≤60秒受控探针检查该精确PID+cmdline/op-id和退出marker；PID被复用或身份不足不发kill，保持unknown。
- 只有匹配自有probe进程才允许定点回收；不能杀exporter/其他thread/service。退出无法证实就阻止再次copy，不凭sleep推断已结束。
- docker cp只读取容器目录，取消client后仍核本次PGID与host stage/receipt实际结果；Docker daemon内部无法独立证实的状态保留unknown。不把kill返回0视为copy取消/数据完整证明，也不通过重启容器解决。
- 本地runner测试用纯Python子进程（包括孙进程/忽略TERM/输出洪泛/模拟daemon探针），不连真实docker/SSH。未来本机Docker合成容器烟测只在root安排短窗口、固定digest与合成目录后进行；这与生产验证分开记录。

## C. 现有root/R调用面的可信接收

R直接取得完整immutable metadata/content包，B只接收计数/摘要；root核producer→host verified后才将同一包交原R。R在自己的现有runtime路径独立重算manifest/每文件SHA/source链，回执精确绑定package/capsule/manifest/obs与时间。
可信身份依据是现有Codex聊天来源：root固定原R的thread ID、review任务/turn、原R独立回执消息及实际artifact路径/SHA，不能从包内issuer='R'或相同Unix uid/0600推断R身份。R审核代码通过也不等于收包。

本方案保留B003 HMAC API作为调用校验，使用root已核R来源的短时桥接：

1. 原R先独立收包/验证并在原R线程回执；root通过既有read_thread/收到的可靠来源记录核精确绑定，把非secret来源承诺存trusted-ack.source.json。
2. root受信调用面在宿主独占控制目录提交同一unsigned ack+来源承诺（正文不含样本行）；该控制目录不挂入producer容器、producer无生成/提交接收回执入口。
3. 受信host控制入口在同一进程内生成短时32-byte材料、签已核ack并调用record_delivery，然后销毁内存材料；不经argv/env/stdout传递，不写仓库/业务artifact，不建长期密钥/账号/付费服务。
4. HMAC证明受信桥接调用一致性，R身份仍来自步骤1的既有来源核验。若来源记录缺失/错线程/错SHA/未实际取得包，根本不调用该入口；不是producer读本包后自签issuer=R。
5. R.received完成后仍保存独立R来源承诺、host收据与R所核包SHA；回传丢失先核实际R.received及来源记录，再回同一摘要，不重复制造新接收事实。

此桥接尚未实现，也不声称当前已有真实认证材料。root/R需审核来源核验及入口职责；若现有调用面无法保持producer/host接收控制分离，就停在host_verified，不自行新增权限或认证体系。
R事实标签仍是model/machine/human分列，收包/代码review不把human=not_reviewed改成verified。

## 交付顺序与剩余输入

测试矩阵见[B-004测试设计](B-004-test-cases.md)。拟任务按native流程：

1. (integration) 先方案root/原R review，锁定所有责任文件和输入契约。
2. (integration) 写PG/runner/R来源反例，取得真实RED；实现真实runner与最小PG驱动，局部GREEN。
3. (operations) 构建不可变工具包及literal execution-manifest，补source/UID/路径/进程回收fake与本机合成烟测；不做生产staging。
4. (integration) root安排PG16独立短窗口，记录真实SQL/事务/失败收据；不足则明确阻塞，不用fake替代。
5. (integration) 固定SHA、proposal新路径/profile/fixture依赖，交原R独立代码review；root统一mapping/PR/full政策，不由B盲跑full。
6. (operations) 正式目标、binary/socket/Python/digest/路径/owner/空间、工具包/执行manifest/R来源绑定及适用根AGENTS门禁由root整体安排；本方案不执行生产。

每层留Git/image/dependency/schema/fixture/tool/capsule/manifest SHA、case与耗时/exit/fixed code、清理的自有资源清单。失败和unknown保留源obs不重采、不覆盖；清理只限本次标签/专属目录且先核无存活进程与持久receipt，不删除他人数据。
当前剩余输入：PG/Python缓存image digest、实际短窗口、真实host/container Python与Docker/socket路径、root/R thread/receipt来源绑定。均UNBOUND。当前周剩余4%，无子代理/长进程/模型CLI；≤1停工规则继承既有任务约束。

## 本轮文档验证（未执行上述验证矩阵）

workflow contract PASS、4契约tests PASS、B004文档引用与diff check PASS；两项已有mapping fixture tests PASS。INT001-P2-01 proposal静态契约改前明确失败（catalog缺transfer域）、同步后PASS，与root已取得的selector真RED/30例分开记录。
已核exporter/verifier及两test文件均与4eafb17f字节一致；本轮没有实现代码变动，没有PG/Docker/SSH/网络/生产操作或后台进程。首次targeted unittest用了不存在的CLITests类名，修正为CommandTests后通过，该命令错误不计行为RED。
