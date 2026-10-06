# C027 首批公开页真实本地演示

任务：C027-PUBLIC-FIRST-RESULT-DEMO-001。2026-10-06 完成本地验证，尚未独立复审、合并或发布。

## 结果与范围

固定已合并主线 `6e6aded22764ebee3d6a97f2834f47d4b4baa7bb`；开始时远端 main 同 SHA。独立 worktree `/Users/mentianlu/.codex/worktrees/c027-public-demo/umanews`，分支 `codex/c027-public-first-result-demo`。保留 U01/U02 及主线 QQ 代码，不重写已通过能力；F04/E 后台交互和 Q01/Q02 QQ 下线继续暂缓。

真实 Django 模板、ORM、静态资源与 Chromium 已展示：

- 首页今天起七天最多四场，第五场与七天外重点场不回填；未知时刻无虚构钟点，已知时刻显示北京时间 14:30。
- G1 筛选四卡，徽章为 G1/Jpn1/G1/G1；没有可信地方体系 profile 的 Local G1 保持待核实，不进入国际 G1 集合。
- 德国 G1 筛选一场，点击真实详情再返回，页面选中 grade=g1、region=germany、year=2026，集合仍为一场。返回使用签名 `return_nav`，不要求 URL 明文展开筛选。
- 桌面 1440×1000、手机 390×844；手机无横向溢出。六张真实截图已逐项生成，首页、日历、详情和返回截图已人工查看。

仅发现并修复一行生产代码：`server/stable/services/race_public_time.py` 的 SQLite UDF 注册前增加 `connection.ensure_connection()`。原来新 HTTP 线程第一次编译日历 SQL，尚未打开连接，真实 GET 返回 500 / `NoneType.create_function`。PostgreSQL 分支、业务筛选、view、template、model、QQ 与配置文件均未修改。本任务没有新增迁移。

授权覆盖本地演示与技术修复（G1）；没有 G2/G3 发布、生产写入或 QQ 外发授权。通用门禁仅引用根 `AGENTS.md`。

## RED / GREEN 与证据

RED 提交 `1c105f4b1213af5fc5c82e1e6f03aa5adc492809`；一行修复提交 `438609798d10cbd6ffd377d530f3d628333c0f5b`。浏览器证据的 candidate_sha 绑定后者；最终交付附加的改动只修正截图断言并补本文，不改变服务器产品代码。

新增唯一窄回归：

`stable.test_c027_public_time_sqlite.PublicTimeFreshSqliteConnectionTests.test_cold_connection_compiles_and_preserves_known_and_unknown_clock`

独立 `:memory:` SQLite DatabaseWrapper，初始 connection=None，编译并执行真实公开时间 SQL；date-only 得到日期/空时刻/空 UTC，已知上海时刻得到日期/14:30/06:30 UTC。原实现实际 RED，增加一行后 1 test GREEN（0.008s），不触及项目测试数据库。删除该行恢复相同冷连接错误。没有跑旧整组、Docker、PostgreSQL 或正式 CI；不得将本结果描述为正式 CI 验收。

证据目录 `/Users/mentianlu/.codex/runtime/c027-public-first-result-demo-001`：

| 文件 | 内容 |
| --- | --- |
| `sqlite-regression-red.log` / `sqlite-regression-green.log` | 窄回归实际 RED / GREEN |
| `calendar-http.html` | 修复前真实 HTTP 500 调试页，仅含合成数据 |
| `server-green.log` | 修复后相同日历 URL 及真实导航链路 HTTP 200 |
| `verification.json` | Django Client 集合、时间与签名返回验证 |
| `browser-verification.json` | 真实浏览器六页验证；page_errors 与 blocked_external_requests 均为空 |
| `home-desktop.png` / `.html` | 桌面首页 |
| `g1-calendar-desktop.png` / `.html` | G1 四卡日历 |
| `germany-g1-desktop.png` / `.html` | 德国 G1 单卡 |
| `detail-with-return.png` / `.html` | 真实详情 |
| `return-preserves-filters.png` / `.html` | 返回后筛选和集合 |
| `home-mobile.png` / `.html` | 手机首页 |

演示夹具初次误将缺可信 profile 的 Local G1 算入 G1、并误用小写 canonical code，已按现有 parser 修正；浏览器初次误将签名返回当明文参数，改为核对实际控件。两者均属于演示断言修正，没有修改产品语义。

## 本地入口、隔离与复现

入口 `http://127.0.0.1:8767/`，演示日期 2026-10-06。记录时自有服务 PID 49107，启动日志如上；入口只在该 Mac 进程存活期间可用。数据库仅为专用 runtime 的 `synthetic.sqlite3`，所有赛事名称标记 `【合成演示】`，新闻正文明确声明非真实赛事。原文、头像或图片均未从外部抓取。

使用已有 Python 3.12.13 / Django 5.2.1 与 bundled Node/Playwright/Chromium，无安装或下载。演示进程不加载 dotenv，显式覆盖专用 SQLite、locmem cache/email、内存 broker/result；关闭 QQ、抓取与其他网络开关，禁出站 socket；没有 worker、Beat、Redis、生产数据库或第三方服务连接。原项目配置文件和凭据未修改，凭据未输出。

在上述 worktree 复现（当前服务运行时不要重复启动同一端口）：

```sh
/Users/mentianlu/Code/umanews/.venv/bin/python scripts/demos/c027_public_pages.py --runtime /Users/mentianlu/.codex/runtime/c027-public-first-result-demo-001 --port 8767
```

仅验证夹具、不启动服务时追加 `--verify-only`。跨日复现应指定新的专用 runtime，脚本拒绝复用过期演示日；同样拒绝接管无合成标记的既有数据库。

```sh
NODE_PATH=/Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/demos/c027_capture_pages.cjs /Users/mentianlu/.codex/runtime/c027-public-first-result-demo-001 http://127.0.0.1:8767
```

停止时先核对 `ps -p 49107 -o command=` 仍为本演示启动命令，再 `kill -INT 49107`；PID 会随重启变化，勿盲用历史 PID。保留专属运行数据和截图即可复查。本地关 QQ 只用于隔离，不代表生产下线。

## QQ 已合并代码盘点与后续发布边界

本节仅对固定 main 只读盘点，没有查询或改变当前生产 QQ 状态。

| 已合并变更 | 效果与风险 |
| --- | --- |
| `5b30966f`（Q01）及 `f606ef7d` 领取 CAS 修复 | settings 增加 `QQ_CHANNEL_ENABLED=False` 默认值，`QQ_PUSH_ENABLED` 默认 False；OneBot online/send、领取、入队、发送和 sweep 多入口 guard |
| `cc5eb8e7`、`370c2093`、整合 `aaed18ac` | QQ UI 条件隐藏、legacy admin action 防护及历史状态展示调整 |
| `qq_auto_push.py` disable 路径 | 可能把投递写成终态 SKIPPED / qq_channel_disabled；重新打开 flag 不自动恢复这些记录 |
| `e70724c9`（Q02） | 删除 settings 的 `qq-production-regions-window` 五分钟 Beat 项；两份 production Compose 删除 optional onebot / with-onebot 服务块 |

`.env.example` 虽有 QQ_PUSH_ENABLED=false，但没有显式 QQ_CHANNEL_ENABLED；新主开关缺失时将默认关闭。因此不能直接部署整个 6e6 主线后声称 QQ 行为保持。仅打开主开关也无法恢复被删除的 Beat 和 Compose 声明。

后续 ROOT 精确发布包需要先只读固定生产实际 QQ 基线（开关、OneBot 服务/登录卷/endpoint、Beat 与数据库 schedule、队列和投递状态、UI），再选择明确的兼容发布方案：

1. 若使用包含 Q01/Q02 的主线，保持已批准生产行为需要在新 worker 加载前显式配置 QQ_CHANNEL_ENABLED=True，并保留现有 QQ_PUSH_ENABLED 与地区窗口值；不要自动开启原来关闭的推送，也不要经过临时 False 导致终态 skip。
2. 按基线在独立、经过 review 的部署兼容层保留所需 QQ schedule 与 OneBot 实例、登录卷和 profile。Compose orphan 清理或移除 profile 不能隐式关闭原网关；单改 flag 不足以证明兼容。UI 历史语义也需要按生产基线评估。
3. 若要求整个 Q01/Q02 行为完全延后，ROOT 可另行构建基于实际生产基线、仅含 U01/U02 与本 SQLite 修复的发布候选；主线 QQ 已合并代码继续保留。本任务没有构建该候选、回退主线或授权发布。
4. 发布验证、回滚、迁移和配置清单须绑定实际候选及生产基线，不能把本任务“无新增迁移”扩写为整个主线发布无迁移。QQ 真正外发应由精确 G2/G3 范围覆盖；演示不发送测试消息。若真实生产已有 disabled 终态数据，恢复另行绑定 manifest 与数据范围，不能盲目 requeue。

## 交接剩余项

由 ROOT 将最终代码/截图提交给原 R 独立复审，并统一登记新增窄测试的 impact mapping（C 不修改共享 mapping）。本地页面演示已完成；正式 CI、独立 review、生产 QQ 兼容发布方案、精确发布包批准及实际生产页面/数据验证仍未完成。C 不启动额外测试资源或竞争 release coordinator。
