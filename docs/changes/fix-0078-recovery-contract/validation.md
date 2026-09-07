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
| 真实 PostgreSQL 16 | 首轮的 3 项通过：0077→0078、锁超时原子性与重试、不可逆边界、custom dump 在新空库恢复 JSON/FK/recorder |
| 实际恢复 shell、私有文件和故障断点 | 首轮夹具已返修，待下一轮 Linux 结果 |
| 真实 v5 管理命令与迁移衔接 | 已补测试，待下一轮 PG16 结果 |
| 完整 stable 固定基线对照 | 首轮仍在运行，不能沿用历史 235 项失败数量作为本次结果 |
| 仓库工作流合同检查 | 本地 checker 报 5 处既有历史文档引用；4 项合同测试中 1 error、3 pass。待同环境固定基线对照，不在本任务中扩大治理清理 |
| 独立原生代码审核 | 首轮 1 项 P1、1 项 P2；修复与原 reviewer 复审尚未全部完成 |

首轮 [CI run 34103904943](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34103904943)
实际测试 GitHub merge ref `30435ca18f623fb1d8918ab4a0d21b0349a9011d`，其 PR head 为上述首轮实现。
后续 CI 固定 PR head，并在 Linux 保存测试前后的原生 review fingerprint，避免把 merge ref 与候选混称。

## 独立测试与审核返修

独立测试 agent 只修改测试与 CI，生产实现由主 agent 修复；测试不使用生产配置。
已识别并修复、仍需 Linux 复验的实现问题：

- 旧 optional worker 恢复意图必须阻止新 0078 入口，不能把中断时的停止状态记为原始状态。
- 服务恢复要核验实际容器镜像，不能只验证当前镜像标签。
- 原 admission 与备份证明必须绑定同一个 source leaf。
- 恢复前必须比对实际生效的 writer flags 和 Compose project，不能仅比对 `.env` 字节。

原生 `codex review` 在固定只读 worktree 审核首轮提交，session 为
`01a07b1d-7de0-7d10-a1a2-505f62a51bc2`。审核前后 worktree clean、HEAD/tree 不变。
Windows 上仓库 fingerprint 脚本因缺少 `O_NOFOLLOW` 拒绝执行，没有放松该安全检查；
后续由 Linux CI 执行原脚本并保存相同 scope 的前后结果。

原生审核发现 P1 为实际环境开关漂移；P2 为旧测试仍要求静态文件处理晚于完成标记。
P2 必须按新的完成边界修改测试，不能删除该断言或把新增失败归入历史基线。

## 测试边界

恢复入口测试运行真实 coordinator、resume shell、deployment lock 和 POSIX 私有产物，
Docker/Compose、备份命令与部分下游命令使用替身。PG16 测试补充真实迁移、数据库语义、
备份恢复和管理命令衔接。二者不等于已经在生产容器编排中演练。
