# 0078 修复测试与验收计划

## 1. 验证边界

本文件定义验收矩阵。实现阶段已取得纯逻辑 RED→GREEN；独立 Linux/PostgreSQL 16 专项 36 项已通过，旧合同全量对照仍在收尾。逐项覆盖与实际执行结果以 `validation.md` 为准，不能把下列计划要求直接当作全部完成。本次未操作生产。
权威环境为隔离 Linux + PostgreSQL 16；Windows 原生不等同生产 shell/权限语义，SQLite不替代PG catalog、锁与事务。
所有网络、Git远端、Docker生产项目、Celery/Redis和外部消息均使用 mock 或本次专用隔离资源；测试环境不得继承生产 .env。

## 2. 测试矩阵

| ID | 行为/反例 | 通过条件 / 能捕获的错误 |
| --- | --- | --- |
| T01 | main 固定 SHA 静态合同 | 记录 TARGET、FINAL、resume、allowlist 和 fixture 0077/0078 差异；静态证据不冒充 RED |
| T02 | 真实0078数据库+当前候选 | preflight 成功、空计划、catalog 完整；捕获仍钉0077 |
| T03 | 稳定0077→0078 | 仅0078出现在plan，唯一migration owner；捕获裸 migrate全树 |
| T04 | 未知0079/同号不同文件 | preflight拒绝；不能由max版本号自动放行 |
| T05 | blob/依赖/路径全集漂移 | SHA或依赖变化、低序号插入、嵌套路径、重复路径均拒绝 |
| T06 | 已记录0078但列缺失/错型/可空/持久default/generated | 结构化catalog_drift；不先ORM报缺列 |
| T07 | 列存在但0078未记录 | 拒绝；不fake recorder，不自动删列 |
| T08 | 0077既有表/约束/索引漂移 | 仍拒绝；snapshot检查不覆盖原校验 |
| T09 | real PG16 jsonb/default语义 | 空/非空JSON、NOT NULL与无DB default符合真实migration；fixture不是照抄validator |
| T10 | 0078锁超时 | 另一连接持锁；5秒左右超时，0078 recorder/列均未提交，业务行未变 |
| T11 | 反向0078及跨0077 | IrreversibleError；数据不被反向删除 |
| T12 | 0077升级无备份/坏SHA/不可读TOC | 经标准/低成本真实入口在任何服务stop前拒绝 |
| T13 | 0078绑定生产者与消费者 | host→env→命令→verifier各字段一致；缺任一consumer即失败 |
| T14 | 备份路径含空格、非法路径/symlink/权限 | 合法独立argv通过；不可信文件拒绝 |
| T15 | admission-only误入release | 迁移前拒绝；必须重新生成closed-state artifact |
| T16 | 停服之间DB identity/source/catalog变化 | 不生成可用bound handoff，不migrate |
| T17 | 0077升级在DDL前/中/后失败 | 停服前已有prepared发布意图；live只能是完整0077或完整0078，prepared本身不授权DDL |
| T18 | live0077+新候选/新deploy试图接管 | 拒绝；原candidate+manifest的forward-resume才通过 |
| T19 | live0078+static失败后重试 | 空计划、完成static再完成intent；不能提前启动worker |
| T20 | v4/0077与v5/0078 artifact混用 | 拒绝，不补默认值升级、不重写旧marker |
| T21 | 完成receipt重放/marker inode替换 | 原receipt幂等；替换文件、DB/commit/image/SHA漂移拒绝 |
| T22 | resume_stopped_release | exact0078/catalog通过才启动；0077部分态与0079均拒绝 |
| T23 | 仓库真实默认rollback策略，两种compose | 非零且checkout/build/retag/stop/migrate/restore调用数均0 |
| T24 | 显式模拟允许rollback fixture | exact0078路径+blob+OID+manifest一致才进入模拟允许分支；不改生产allowlist |
| T25 | REVIEWED_TAIL包含0076/77/78 | 漏0076、改0077、异名0078都被拒绝；捕获[-2:]回归 |
| T26 | 旧世代fixture | 固定旧清单/旧blob/旧目标自洽；不能glob当前迁移树冒充旧0077 |
| T27 | retained-schema隔离控制镜像回归 | pin文件完整、不可变OID、retag漂移、锁竞争、失败恢复、token一致 |
| T28 | 同版本0078标准/低成本/manual真实入口 | 缺失、替换、source=0077伪装same-schema、错误DB/candidate、另一release证明均在首个stop或release-task写前拒绝；原release绑定重试复用不误判过期 |
| T29 | 真正0078备份恢复 | 新空隔离库恢复后recorder、catalog、非空snapshot、关联和业务计数一致，目标镜像可读 |
| T30 | 0077备份恢复对比 | 新空库恢复才得到exact0077；禁止把向0078库--clean后留列当成功 |
| T31 | restore中断/错误备份/目标漂移 | 原服务不切换；隔离目标不启动writer；事务失败可识别 |
| T32 | worker/队列/开关 | 两种compose保持既有drain与恢复意图；race_live无消费/purge |
| T33 | 完整本地验证 | Django check、migration drift、shell语法、三compose、工作流文档检查、diff检查 |
| T34 | 最新生产只读验收（未来发布阶段） | exact commit/image/leaf/catalog/flags/locks/queues；无DDL、业务抽样一致 |
| T35 | backup proof已持久化，intent或active pointer发布失败 | 没有stop；通过同一resume入口原release_id补prepare，不生成新origin |
| T36 | 第1个stop/drain之后异常退出 | prepared意图已存在；原服务意图不被部分停止状态覆盖，新锁可继续关闭 |
| T37 | 全停后closed artifact创建失败 | 无DDL；同一resume入口从原prepared意图生成bound artifact，不要求尚不存在的DDL marker |
| T38 | closed已写，DDL marker创建失败 | 重试复验closed状态后创建marker；prepared/admission-only不能跳到migration |
| T39 | DDL已提交后进程崩溃 | exact0078/空计划；不重复应用0078或新建备份，沿原意图继续static |
| T40 | schema完成receipt已归档，服务尚未恢复 | 发布意图仍活动；同入口识别receipt继续服务，不因DDL marker不存在而拒绝或误开新发布 |
| T41 | 服务已健康，发布receipt/指针收尾中断 | 复核真实服务、同release_id幂等完成；不删别人的指针 |
| T42 | 不同release_id竞争、旧lease失效/新锁获取 | 新发布被active intent拒绝；合法原发布可在新锁下续跑，不能伪造原token/provenance |

## 3. 测试夹具重建

Harness改为显式代际输入，不默认把仓库glob结果塞进0077模拟目标：

- 当前生产策略fixture：复制真实allowlist，不开启模拟批准，用于T23。
- 当前0078模拟批准fixture：以独立明确清单提供0071–0078 blob、已固定目标OID、迁移manifest和同代fake preflight响应。只有声明需要模拟允许分支的测试能使用。
- 历史0077 fixture：冻结旧文件清单和真实旧blob，不吸入0078；用于兼容拒绝和历史协议测试。
- 预期值与被测实现分离：路径/hash可取固定源码，但期望动作、状态迁移和异常必须由case明确写出，不能导入生产常量后assert等于自己。

不把全部0077替换为0078，不批量删除负例，不跳过相关失败，不用expectedFailure粉饰通过。

## 4. 执行顺序和证据

1. 完整checkout建隔离worktree，固定基线；先重跑涉及的test_single_migration_owner及schema/handoff套件，按case名称记录失败，不能只比较计数。
2. 新写T02/T06/T20/T23/T28等有效RED，失败必须命中目标缺口；对已有可通过保护测试保留GREEN。
3. 最小实现，单元及shell模拟套件GREEN。
4. PG16从真实0077迁到0078，做锁竞争、失败重试和恢复演练。
5. 全相关套件全绿；一次全量stable与同环境基线比较，无新增失败。历史债务以本轮同环境基线为准，不在本修复内扩大清理。
6. 独立代码review及同上下文复审；发布后另做T34。

T35–T42必须分别经真实resume_migration_history_repair.sh新分支重放，不能仅直接调用Python helper。对upgrade和same-schema都覆盖相应断点，两个Compose模式与manual首次进入都验证T28。每例断言不需要新的deploy、手改marker或解除原backup绑定，且首次stop前已验证prepared意图、closed验证前0 DDL、schema/static证明前0提前启动writer。

验证记录保留环境/依赖版本、基线与候选SHA、命令、退出码、测试总数、失败名称及原因、artifact SHA。没有执行的项目明确标“未执行”，不勾完成。
