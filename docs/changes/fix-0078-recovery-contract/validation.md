# 0078 实现验证记录

本文件仅记录本地与隔离 CI。没有连接生产数据库、启用业务开关、执行真实抓取或发送消息。

## 固定输入

- 基线：`a88bcbf669bd609e30f97c8a07f009881d2da705`。
- 首轮实现：`e79fe4ba1c1a8e1bb424bcb4e3f37ed0094e11f0`，Draft PR [#181](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/181)。
- 首轮 Git tree：`e62a66017be50e573ccef83d2e5214f48b248733`。提交前逐项核对 41 个变更文件的 Git blob 与本地字节一致。
- 最终代码与测试：`966e3455afc66a1476a8dc8e020ee81592237bbb`，tree `6928c2a6fa2cb0c54348c75a1a9b9a5cdafe9ece`。后续提交仅回写文档与记录，不改变受测代码/测试文件。
- 已发布 0077/0078 迁移未修改；完整迁移文件合同 SHA-256 为 `50c421f3167a8c2c8f1613a0597ad7ee196c249fc18bf7eed0de7b9cd2f80906`。

## 最终开发验证结果

| 检查 | 当前结果 |
| --- | --- |
| 最初 7 项纯逻辑 RED | 4 failures、2 errors、1 pass；来自缺少 0078 状态/列校验与旧迁移上限 |
| 同批 GREEN | 7/7 通过；独立 agent 后续补充后，Windows 可执行纯逻辑 9 项通过 |
| Python 编译、shell 语法、全变更 `git diff --check` | 15 个变更 Python 文件在内存编译通过；shell 语法由 Linux 专项检查；最终以固定基线到整个工作树检查 whitespace，通过 |
| 首轮 Linux/PG16 专项 | 29 tests / 190.199s，29 个失败子例；失败处是 preflight 夹具父目录权限与 inode 重用假设，未视为通过 |
| Linux/PG16 专项 | 最终代码 `966e3455`：39 tests / 216.528s / OK / 0 skipped；测试前后原生 review fingerprint 一致 |
| 真实 PostgreSQL 16 | 0077→0078、锁超时原子性与重试、不可逆边界、custom dump 在新空库恢复 JSON/FK/recorder 均通过 |
| 实际恢复 shell、私有文件和故障断点 | 修正夹具后通过，覆盖两种 source leaf 的中断与续跑、身份/备份/配置篡改拒绝 |
| 真实 v5 管理命令与迁移衔接 | 真实 create→verify→ensure(v3)→0078 migration→complete receipt 通过；`manage.py check` 正常，`makemigrations --check --dry-run` 无漂移 |
| 完整 stable 固定基线对照 | baseline 4886 tests / 69 failures / 258 errors / 15 skipped；最终 candidate 4925 / 31 failures / 257 errors / 19 skipped；0 新增失败，39 个既有失败 ID 消失 |
| 仓库工作流合同检查 | 正常模式两侧 checker/test 均退出 1/1：5 处既有历史文档引用，4 项合同测试中 1 error、3 pass；没有新增，不在本任务中扩大治理清理 |
| 独立原生代码审核 | 同一 reviewer 完成五轮；生产 P1/P2 与测试差量两个 P2 均已复审解决，最终 `966e3455` 无新增 finding |

首轮 [CI run 34103904943](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34103904943)
实际测试 GitHub merge ref `30435ca18f623fb1d8918ab4a0d21b0349a9011d`，其 PR head 为上述首轮实现。
后续 CI 固定 PR head，并在 Linux 保存测试前后的原生 review fingerprint，避免把 merge ref 与候选混称。

首轮完整套件通过 `python -` 启动，触发了仓库既有 `RUNNING_TESTS` 判断差异，使用了
RedisCache 而非正常测试的 LocMemCache。因此这些数量只是首轮原始证据，不能作为最终
正常测试基线；已把两侧启动参数统一为 `manage.py test stable` 的测试模式。
第二轮 [CI run 34105926335](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34105926335)
取得上表的正常基线，新增失败为 `test_single_migration_owner` 55 个、
`test_migration_history_repair` 11 个、`test_historical_calendar_release_b` 4 个。
新 0078 模块没有新增失败，不能因此忽略旧入口的合同回归。
第四轮重新执行相同基线为 4886 tests / 916.935s，仍为 69 failures、258 errors、15 skipped；
两次基线失败 ID 集双向差集均为空。同名失败原因也已逐项比较，最终结果见下文。
第四轮候选 `2e11e7ef` 为 4925 tests / 1260.070s、42 failures、257 errors、19 skipped；
新增失败由 70 降至 8：5 个 wrapper 缺 lock action、1 个 absent 配置夹具、
1 个错误期待忽略 conflicting attempt mode、1 个 manual 夹具错误依赖 expected DB 环境变量。
前 6 个已在 `17089d36` 修复；后两项按真实早拒绝和独立 DB 事实修正。
同名失败栈另暴露 machine-readable leaf 和两种 rollback 的精确 `git show` 清单过期，
这些也列为必须修正，不能用旧失败名称遮住。
对 277 个共同失败 ID 逐一核对并保留重复 teardown 栈：263 个规范化栈相同；
14 个差异中上述 3 个过期期望已修，其余为 set 展示顺序（5）、页面 CSRF 随机值（4）、
同样超过阈值的性能耗时（1）及同样缺少四个路径的旧 inventory 检查行号/参数差异（1）。
未将上述三项期望漂移并入“历史问题无需处理”。
第二轮专项在测试前因证据目录造成脏 worktree 而退出，没有执行用例；证据现移至
`RUNNER_TEMP`，未放松 clean 检查或 fingerprint 脚本。

专项通过证据为 [CI run 34106340975](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34106340975)，
job `101692128078`，固定 head `dfb20ca820ed5631f7506811879a7beedf1a8d31`。
artifact `10012713276` 的 ZIP SHA-256 为
`f74462d2e8ae31711cfccc7db378ad76c162e9ae36239e6a53bdda9de7f68e3e`。
该阶段的专项通过不等于当时完整 stable 无新增失败；以下记录后续返修和最终结果。

补充三个边界用例后，[CI run 34107943935](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34107943935)
在固定 `2e11e7efe35efd86abcfe7db5d0b58e41139dfcb` 的专项为 39 项全部通过，
覆盖合法含空格路径、stop 后 DB identity 漂移和真实 resume 对损坏 v3 receipt 的拒绝。
ZIP SHA-256：`4500d089a6cb27e4375f236877aba9d61795aa257f0cc337a99eb250b5eb5b58`。
旧夹具随后又修正 lock action、无容器但有 Compose 服务配置、正确签名的旧 source 拒绝用例；
最终候选 `17089d36d19ca293590b22293c94339471225c1d` 在
[CI run 34108845892](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34108845892)
的专项 job `101700084892` 再次 39/39 通过、0 skipped（312.195s）。
`check`、migration dry-run、原生指纹前后比较均通过。artifact `10013697781` 的 ZIP SHA-256 为
`abd242eaf19dc79ad1d6462d2656aa1b88c3f5c643e5a8be5d518dbd789f3523`。
最后一批夹具更正后，[CI run 34110369092](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34110369092)
在固定 `966e3455afc66a1476a8dc8e020ee81592237bbb` 的专项 job `101704942546` 为
39 tests / 216.528s / OK / 0 skipped；`check`、migration dry-run 和 clean/fingerprint 均通过。
artifact `10014234198` 的 ZIP SHA-256 为
`539561cd8f0480ddf967eb7a0cc5ba8d27808355c58de6f2a2924b7194eb46a0`。
环境为 Python 3.12.14 / PostgreSQL 16.15；前后原生 fingerprint 字节一致，SHA-256 为
`f4c1a49587e5efc6c3171485e336b1e2a0c0415f113cf3120d66a4cbc9ef80cb`，
tracked/untracked/conflict 均为 0。

### 最终完整 stable 对照

同一 run `34110369092` 的四个 job 均完成，新增失败检查成功：

- 基线 `a88bcbf6`：4886 tests / 932.821s，69 failures、258 errors、15 skipped。
- 候选 `966e3455`：4925 tests / 1266.122s，31 failures、257 errors、19 skipped。
- 去重失败 ID：313→274，新增为 0、消失为 39；完整 suite 仍有 288 条既有 failure/error，不能称全仓全绿。
- 多出的 4 个 skip 是新 PG 专项在 full stable 中明确关闭；相同四项已在独立 PG16 job 实际通过，专项为 0 skipped。
- 最终 274 个共同 ID 连同重复 teardown 栈全部比较：261 个规范化栈相同；其余 13 个只有 set 顺序（5）、CSRF 值（4）、页面时间（2）、同样超阈值的性能耗时（1）和旧 inventory 同缺四路径（1）差异，无同名掩盖的新回归。
- `test_single_migration_owner`、`test_historical_calendar_release_b` 与新 0078 模块无剩余失败；旧 repair LeafSet 和历史 PG 的基线失败单独保留。

候选 artifact `10014827005` 的 ZIP SHA-256：
`b9871f1d2d4c8674170bd760e6a83de8d18b7619b74f35eff030785f604cefd1`；
基线 artifact `10014643494`：
`b80b91192594587abefd9bc2a2f3c5fe445946607f12bd0c4cc18a379fb7ea1b`；
comparison artifact `10014832687`：
`0033e4fcc3bc172b0ace607e404741efd8bfbc78096c47e143a64120a043dfb9`。
独立测试 agent 已下载并逐项校验 ZIP 与上述 digest。

## 独立测试与审核返修

独立测试 agent 只修改测试与 CI，生产实现由主 agent 修复；测试不使用生产配置。
已识别、修复并经上述 Linux 专项复验的实现问题：

- 旧 optional worker 恢复意图必须阻止新 0078 入口，不能把中断时的停止状态记为原始状态。
- 服务恢复要核验实际容器镜像，不能只验证当前镜像标签。
- 原 admission 与备份证明必须绑定同一个 source leaf。
- 恢复前必须比对实际生效的 writer flags 和 Compose project，不能仅比对 `.env` 字节。

原生 `codex review` 在固定只读 worktree 审核首轮提交，session 为
`01a07b1d-7de0-7d10-a1a2-505f62a51bc2`。审核前后 worktree clean、HEAD/tree 不变。
Windows 上仓库 fingerprint 脚本因缺少 `O_NOFOLLOW` 拒绝执行，没有放松该安全检查；
后续由 Linux CI 执行原脚本并保存相同 scope 的前后结果。

原生审核发现 P1 为实际环境开关漂移；P2 为旧测试仍要求静态文件处理晚于完成标记。
两项已在固定 `3c051364` 上复审解决，独立验证 80 个配置场景、6 个 shell 成败场景及原排序断言通过。
P2 保留并修正了断言，没有删除测试或将新增失败归入历史基线。
最终测试差量还修复缺失容器/Compose 服务定义混淆、旧 source 拒绝用例的签名及锁 action 参数。
第四轮在固定 `17089d36` 通过 5 个不落盘定向场景，确认两个测试 P2 解决，无新增 finding。
范围、固定 tree 和历史发现见 `review.md`。
最后三个测试差量于 `966e3455` 完成第五轮审核，6 个定向场景通过，无新增 finding。
完整候选 CI `34110369092` 已按上述实际结果确认无新增失败。
收尾只把历史 `input_fingerprints.json` 的 CRLF 行尾规范为 LF；解析后的 JSON 完全相同，
其中历史输入的 SHA/字节数未改，也没有把旧方案指纹改称当前实现指纹。

## 测试边界

恢复入口测试运行真实 coordinator、resume shell、deployment lock 和 POSIX 私有产物，
Docker/Compose、备份命令与部分下游命令使用替身。PG16 测试补充真实迁移、数据库语义、
备份恢复和管理命令衔接。二者不等于已经在生产容器编排中演练。

旧 `test_migration_history_repair_postgres` 仍有 12 个共同失败 ID（含重复 setup/teardown
错误共 23 条）与基线规范化栈相同：主要因从已应用不可逆 0078 的默认测试库尝试倒退
到旧 leaf，在历史场景断言之前失败。这些旧场景未获验证，不能写成历史 PG 套件全绿。
新专项通过独立 0077 模板正向迁移、真实恢复与管理命令链验证本次 0078 路径。

## 验收矩阵的实际覆盖

下表按独立测试 agent 的用例核对记录；计划中的完整系统验收与开发验证分开标记。
39 项专项与修订的旧夹具已在最终代码 `966e3455` 通过；同提交完整 stable 的历史失败见上文。

| 计划项 | 已有证据与边界 |
| --- | --- |
| T01 | 固定 Git SHA、迁移合同和 Linux 前后指纹 |
| T02–T03、T09–T11 | 真实 PG16 的 preflight、0077→0078 与空计划、JSON/NOT NULL/default、锁超时原子重试、不可逆 |
| T04–T05 | 全文件 hash、未知 0079、异名 0078、低序号插入和嵌套路径负例；重复路径枚举没有单独用例 |
| T06–T08 | catalog 变异的纯校验器测试与本次正向模板的真实 PG 正确结构验证通过；旧历史 PG 场景仍受既有不可逆 setup 错误阻断，未到其场景断言 |
| T12–T15、T28 | coordinator 两 Compose 的备份失败/绑定拒绝；共享校验和真实 PG 管理命令闭环；私有文件权限/父目录/symlink；admission-only 拒绝；合法含空格路径、三类顶层入口和真实 wrapper 正例均通过。未对每个坏证明在每个入口穷举组合 |
| T16 | 静态 DB/source/plan 漂移负例、stop web 后 closed preflight 改变 DB identity 的真实 coordinator 拒绝均通过。未逐项动态改变所有 catalog 属性 |
| T17–T20、T35–T42 | 两种 source 的 20 个故障重放子例经真实 resume shell 通过；Docker/Git/DDL 边界用替身，真实 DDL 由独立 PG 用例验证 |
| T21 | 备份 inode、intent/pointer 绑定、替换 v3 receipt 内容及 inode 后真实 resume 拒绝均通过，不承诺相同内容跨重试换 inode 必须拒绝 |
| T22–T27 | 默认两种 rollback 零变更拒绝、旧 stopped resume 门禁、控制镜像模拟、模拟允许与显式代际夹具通过；未把真实禁用策略改成模拟允许策略 |
| T29–T30 | 真实 0077/0078 custom dump 均恢复到新空库，核对 snapshot、关联、计数、recorder 和列状态；未构建目标应用镜像读取恢复库 |
| T31 | 截断 dump 恢复失败且已恢复数据不变；未做进程中断、连接切换与服务组切换的系统演练 |
| T32 | 实际 host shell 与替身 Docker/drain，覆盖有效开关和原服务意图；没有真实 Celery/Redis 消费或 purge 验证 |
| T33 | check、migration drift、shell 语法、diff 和 Linux 指纹通过；工作流检查与固定基线相同，完整 stable 无新增失败 |
| T34 | 未来生产实时只读验收，未执行 |

这些未执行项不通过增建一套部署平台补齐。候选真实镜像/Compose、队列和连接切换验收仍属于精确发布包的验证范围。
