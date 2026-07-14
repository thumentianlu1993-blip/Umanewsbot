## 0. Pre-declared hypotheses

- [x] 0.1 (application) PASS：默认 batch006 对每个仍有目标的地区可选择最多 250 场、显式 50 仍可复跑、251 必须在 artifact 写入前失败；BLOCKER：任一层仍使用不同上限或静默截断。
- [x] 0.2 (integration) PASS：在 PostgreSQL 中并发 20 次锁获取始终只有一个 owner，30 秒心跳下 lease age 不超过设计值 180 秒，恢复运行不会重复执行已完成 step；BLOCKER：双 owner、过期误接管或重复 step。
- [ ] 0.3 (operations) PASS：crawl 的业务表写入与 apply 的公网请求在真实 PostgreSQL/Docker smoke 中均失败，普通部署前后 runner container ID 不变且 DB/Redis/network 未被操作；BLOCKER：任一越权成功或基础设施被普通部署处理。
- [x] 0.4 (operations) PASS：runner 容器硬限制不超过 2 CPU、2 GiB、256 PIDs，数据库每 step 日志摘要不超过 8 KiB 且无敏感值；BLOCKER：缺少任一限制、完整日志进入数据库或凭据泄漏。

## 1. 测试契约先行

- [x] 1.1 (application) 按 `test_cases.md` 新增 batch006 地区 250 上限、显式小批、超限拒绝、artifact 上限一致性、100 场领先和排除 snapshot 回归测试，并先确认旧实现按预期失败。
- [x] 1.2 (application) 新增 runner 模型、双锁、心跳租约、暂停、恢复、checkpoint 分叉、owner token 哈希、子进程组清理、stale takeover 和 draft 不变测试，并先确认缺失实现导致失败。
- [x] 1.3 (integration) 新增结构化 plan、allowlist、路径边界、shell 拒绝、输入输出 SHA 和敏感值脱敏测试，并先确认缺失实现导致失败。
- [x] 1.4 (operations) 新增 runner 启动/预检脚本的静态契约测试，覆盖固定镜像、资源限制、独立网络、phase 凭据、普通部署隔离和迁移暂停门禁。
- [x] 1.5 (integration) 新增 crawl 子进程预算覆盖、共享账本/cache 路径、容器内磁盘不足 fail-closed 测试，并先确认现实现按预期失败。
- [x] 1.6 (operations) 新增宿主脚本数值边界与启动前实时磁盘门禁测试，覆盖请求 `1..250`、cache `<=2 GiB`、磁盘底线 `>=5 GiB`。
- [x] 1.7 (integration) 新增请求账本/cache manifest 的 checkpoint 存在状态与 SHA 漂移测试，先确认删除、创建或修改仍会被旧实现放行。
- [x] 1.8 (integration) 新增资源账本 symlink/非普通文件和旧版非终态 checkpoint 测试，先确认现实现会跟随或继续执行。
- [x] 1.9 (integration) 新增生产工具根显式赛事工具白名单测试，确认术语联网脚本即使 SHA 匹配仍被旧实现放行。
- [x] 1.10 (integration) 新增 AdapterRunner 父级固定路径与更严格数值继承测试，先确认嵌套编排会重置账本和间隔。
- [x] 1.11 (integration) 新增首个 crawl step 消耗请求后失败的恢复测试，先确认失败前没有资源 checkpoint 时可删除账本并重置额度。
- [x] 1.12 (integration) 新增生产 artifact plan 不得把 `tool_root` 指向 artifact 内自带脚本的回归测试，并先确认旧校验会错误放行。
- [x] 1.13 (integration) 新增正式 stage 命令在工具根与 settings 不一致时不得创建 run 的回归测试，并先确认旧流程会留下无效控制记录。

## 2. 批次上限与 artifact 一致性

- [x] 2.1 (integration) 将标准地区最大值提升到 250，让管理命令默认值引用服务常量，并保留 1-249 显式小批与旧 50 场重放能力。
- [x] 2.2 (integration) 让 selection、`write_band_batch_artifact` 和 `validate_standard_batch` 接收同一 `approved_region_limit`，在不一致或超限时 fail closed。
- [x] 2.3 (integration) 将 `approved_region_limit` 写入 summary、manifest 和命令结果，同时保留地区领先、已耗尽地区和不可变排除 snapshot 语义。

## 3. Runner 控制账本与执行服务

- [x] 3.1 (application) 新增 `HistoricalBatchRun`、`HistoricalBatchLock`、append-only `HistoricalBatchRunEvent`、状态枚举、约束、索引和 Django migration，不修改现有历史 target 或公开状态。
- [x] 3.2 (integration) 实现数据库租约获取/续租/释放、runtime `fcntl` 文件锁、30 秒心跳、180 秒租约、暂停请求和审计化 stale takeover。
- [x] 3.3 (integration) 实现版本化 runner plan 校验、phase 权限组合、结构化 argv、管理命令/工具 allowlist、真实路径边界和敏感值脱敏。
- [x] 3.4 (integration) 实现 shell-free step 执行、子进程组清理、8 KiB 脱敏摘要、完整日志归档、输入输出身份、fsync+rename runtime state、数据库双 checkpoint、resume 校验和分叉阻断。
- [x] 3.5 (application) 新增 `run_historical_batch_stage` 与 runner status/pause/resume/takeover 管理命令，提供稳定 JSON 输出和正确退出码。
- [x] 3.6 (application) 在 runner 完成和失败路径核对历史常驻开关及目标 visibility，禁止任何隐式发布。
- [x] 3.7 (integration) 为 crawl step 构造受控子进程环境，强制覆盖请求预算、请求间隔、请求账本、cache 上限、磁盘底线、cache 根目录和 manifest，并在租约前重复检查 artifact 文件系统实时可用空间。
- [x] 3.8 (integration) 将 crawl 请求账本与 cache manifest 的最新存在状态、大小和 SHA 写入顶层 checkpoint，并在 completed/resume/下一 step 前验证，漂移时 fail closed。
- [x] 3.9 (integration) 启动与 checkpoint 校验先拒绝资源账本 symlink/非普通文件；旧版缺少资源身份的非终态 crawl blocked，仅保留 completed 幂等兼容。
- [x] 3.10 (integration) 对生产不可变工具根实施显式赛事 Python 工具白名单；保持测试临时工具根可注入，生产新增工具需代码 review。
- [x] 3.11 (integration) AdapterRunner 检测父级 `RACE_EVENT_CRAWL_*` 约束，路径原样继承，数值按更严格者合并，普通非 runner 编排保持原路径。
- [x] 3.12 (integration) crawl 取得双锁后先保存资源基线；任何已启动 step 的失败收尾在释放锁前刷新资源身份，强杀后恢复则由基线漂移 fail closed。
- [x] 3.13 (integration) 生产 `/app/historical-runtime` plan 在遍历 step 前强制使用 `/app/runtime/tools`；正式管理命令还会在创建 run 前比对 settings 工具根，不再依赖执行阶段才阻止 artifact 工具旁路。

## 4. 生产隔离与生命周期脚本

- [x] 4.1 (operations) 新增幂等 provisioning 脚本，只创建 runner egress/internal DB 网络、连接既有 DB alias 并校验三张控制表的最小权限 control role；不得重建 DB、Redis 或共享网络。
- [x] 4.2 (operations) 新增原生 Docker runner 启动/停止/状态脚本，拒绝可变镜像和 `/app/runtime` 宿主挂载，强制 2 CPU、2 GiB、256 PID、日志轮转、`/app/historical-runtime` artifact 挂载、独立 `0600` owner secret 和 phase 环境 allowlist。
- [x] 4.3 (operations) 为 crawl 组合 egress 与 control-role DB 网络，为 apply 只连接 internal DB 网络，并增加实际越权 smoke 检查。
- [x] 4.4 (operations) 将普通 deploy/rollback 改为 `--no-deps` 只更新应用容器并增加 runner 迁移前暂停 preflight，包含首次建表 host-only 门禁，确保不 pull/start/stop/recreate runner、DB、Redis 或 networks，超时直接停止部署。
- [x] 4.5 (operations) 新增必须单独确认的 infrastructure bootstrap，承接初次 DB/Redis/shared network 建立；普通 deploy 缺少基础设施时只报错，不自动调用 bootstrap。
- [x] 4.6 (operations) 更新 `.env.example` 的非敏感 runner 配置说明，并补充凭据文件权限、固定镜像和网络命名约定。
- [x] 4.7 (operations) 在原生 runner 启动脚本校验三项历史资源配置的数值边界，并在 crawl `docker create` 前按 artifact 文件系统实时可用空间执行 fail-closed 门禁。

## 5. 文档与静态验证

- [x] 5.1 (operations) 更新 `docs/current_state.md`、`docs/decisions.md`、`docs/project_status.md` 和 `docs/deploy_runbook.md`，记录实现边界、部署/暂停/恢复/接管/回滚步骤和生产禁止项。
- [x] 5.2 (operations) 运行 shell 语法检查、脚本契约测试、Docker 命令静态检查和 `git diff --check`，确认无 Compose 重建 DB/Redis 路径。
- [x] 5.3 (application) 运行 runner 与历史批次聚焦测试、完整 `stable` 回归、Django check 和 `makemigrations --check --dry-run`。
- [x] 5.4 (operations) 运行本 change strict 校验及全量 OpenSpec 校验，逐项核对 proposal/design/spec/tasks/test cases 一致性。
- [x] 5.5 (application) 执行反复 `/review -> 修复 -> 重新 review`，直到第五轮没有任何 actionable finding；前四轮共修复 7 项问题。
- [x] 5.6 (application) 完成资源预算补丁的聚焦/完整回归、OpenSpec/shell/diff 校验与反复 `/review -> 修复 -> 重新 review`，第七轮没有 actionable finding。
- [x] 5.7 (integration) 完成生产工具根旁路补丁的测试优先实现；两轮复审修复生产子目录放行与拒绝前残留 run，最终 review 无 actionable finding，组合 `250/250`、完整 `stable 1425/1425` 通过。

## 6. 部署与 batch006 前验收

- [ ] 6.1 (operations) 从最新 main 的干净 tree 构建可复现 AMD64 镜像，记录 image ID、revision、tree 和源码 SHA，并在不启动 runner 的情况下应用迁移。
- [ ] 6.2 (operations) 执行 runner 网络/control role provisioning 和只读 smoke run，验收双锁、心跳、状态、暂停、恢复、资源与日志轮转。
- [ ] 6.3 (operations) 证明 crawl 无业务表写权限、apply 无公网出口、普通 web/worker/beat 部署不影响 runner、迁移 preflight 能阻断未安全暂停状态。
- [ ] 6.4 (operations) 保持历史公开及常驻网络/写入开关关闭，生成并审核 batch006 每地区最多 250 场 selection artifact 后再恢复正式历史抓取。
