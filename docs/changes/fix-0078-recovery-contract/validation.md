# 0078 实现验证记录

本文件仅记录本地与隔离 CI。没有连接生产数据库、启用业务开关、执行真实抓取或发送消息。

## 固定输入

- 基线：`a88bcbf669bd609e30f97c8a07f009881d2da705`。
- 首轮实现：`e79fe4ba1c1a8e1bb424bcb4e3f37ed0094e11f0`，Draft PR [#181](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/181)。
- 首轮 Git tree：`e62a66017be50e573ccef83d2e5214f48b248733`。提交前逐项核对 41 个变更文件的 Git blob 与本地字节一致。
- 已发布 0077/0078 迁移未修改；完整迁移文件合同 SHA-256 为 `50c421f3167a8c2c8f1613a0597ad7ee196c249fc18bf7eed0de7b9cd2f80906`。

## 已执行与尚待完成

| 检查 | 当前结果 |
| --- | --- |
| 最初 7 项纯逻辑 RED | 4 failures、2 errors、1 pass；来自缺少 0078 状态/列校验与旧迁移上限 |
| 同批 GREEN | 7/7 通过；独立 agent 后续补充后，Windows 可执行纯逻辑 9 项通过 |
| Python 编译、shell 语法、`git diff --check` | 已通过；随返修继续检查 |
| 首轮 Linux/PG16 专项 | 29 tests / 190.199s，29 个失败子例；失败处是 preflight 夹具父目录权限与 inode 重用假设，未视为通过 |
| 最终生产实现的 Linux/PG16 专项 | 固定 `dfb20ca8`：36 tests / 294.092s / OK / 0 skipped；测试前后原生 review fingerprint 一致 |
| 真实 PostgreSQL 16 | 0077→0078、锁超时原子性与重试、不可逆边界、custom dump 在新空库恢复 JSON/FK/recorder 均通过 |
| 实际恢复 shell、私有文件和故障断点 | 修正夹具后通过，覆盖两种 source leaf 的中断与续跑、身份/备份/配置篡改拒绝 |
| 真实 v5 管理命令与迁移衔接 | 真实 create→verify→ensure(v3)→0078 migration→complete receipt 通过；`manage.py check` 正常，`makemigrations --check --dry-run` 无漂移 |
| 完整 stable 固定基线对照 | 首轮 baseline 4886 tests / 71 failures / 259 errors / 15 skipped；candidate 4915 tests / 163 failures / 264 errors / 18 skipped；新增 101 个失败记录（含子例），尚未通过 |
| 仓库工作流合同检查 | 本地 checker 报 5 处既有历史文档引用；4 项合同测试中 1 error、3 pass。待同环境固定基线对照，不在本任务中扩大治理清理 |
| 独立原生代码审核 | 首轮 P1/P2 已在同一 reviewer 的第二轮复审中解决，无新增 finding；最终测试/CI 差量仍待审核 |

首轮 [CI run 34103904943](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34103904943)
实际测试 GitHub merge ref `30435ca18f623fb1d8918ab4a0d21b0349a9011d`，其 PR head 为上述首轮实现。
后续 CI 固定 PR head，并在 Linux 保存测试前后的原生 review fingerprint，避免把 merge ref 与候选混称。

首轮完整套件通过 `python -` 启动，触发了仓库既有 `RUNNING_TESTS` 判断差异，使用了
RedisCache 而非正常测试的 LocMemCache。因此这些数量只是首轮原始证据，不能作为最终
正常测试基线；已把两侧启动参数统一为 `manage.py test stable` 的测试模式，正在重跑。
第二轮专项在测试前因证据目录造成脏 worktree 而退出，没有执行用例；证据现移至
`RUNNER_TEMP`，未放松 clean 检查或 fingerprint 脚本。

专项通过证据为 [CI run 34106340975](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34106340975)，
job `101692128078`，固定 head `dfb20ca820ed5631f7506811879a7beedf1a8d31`。
artifact `10012713276` 的 ZIP SHA-256 为
`f74462d2e8ae31711cfccc7db378ad76c162e9ae36239e6a53bdda9de7f68e3e`。
后续旧测试夹具仍在收尾，专项通过不代表完整 stable 无新增失败。

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

## 测试边界

恢复入口测试运行真实 coordinator、resume shell、deployment lock 和 POSIX 私有产物，
Docker/Compose、备份命令与部分下游命令使用替身。PG16 测试补充真实迁移、数据库语义、
备份恢复和管理命令衔接。二者不等于已经在生产容器编排中演练。
