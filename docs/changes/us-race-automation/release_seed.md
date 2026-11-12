# 美国历史名单背景修复：精确发布包

本包接续 PR #301 已合并但事务未提交的发布；根因与演练缺口见[修复说明](archive_seed_fix.md)。源 PR、源提交及发布计划 SHA 由最终交付收据绑定；交付按根 `AGENTS.md`。

## 固定内容

- 窄候选 `cba398750fc7e5cb2ecfc17d1ecfe348e8781524`；OCI `sha256:961cf9c411c1e2560c5815f1bc241ccfe2ff0fd09de53822d213df4536cc84bd`。
- 原 manifest `7895f3f0b44cceefcdd44465cc1ee441bd1c74bb05098ba5206c841e01f44ff5` 不变：153 目标、111 场 1071 行赛果/退赛、101 个来源时刻、109 条旧地区登记换绑。
- 当前基线 `332fc540`、schema0084；无新增迁移。30 条旧 TRA 检查点保留，不重新启用。
- 原策略 `5bea3e8dd017da241a3a0348c90290618c82d52d2dd10b9a45336d2ce6b5763a` 不变，美国五时区 route 有效至 2027-01-10，日港法 route 不变。
- 配置同原范围：开启美国赛前流程，provider 增加 `us_racing`，fields 增加 `us_basic.prize/distance/eligibility/race_metadata`，固定策略及只读挂载 `/run/race-data-sync/us-346`。QQ 关闭，Equibase 及子域仍禁用。

## 执行和恢复

1. 取得生产独占锁，复核四应用、配置、schema0084、251 条基线及至少 4.4 GiB 可用磁盘。复用专用 stage 和原件包，保留上次执行资料；仅替换绑定后的计划、脚本及镜像 overlay。
2. 固定镜像流入 Docker，验证候选只读启动，暂停 Beat，排空两个 worker 后停止 worker。确认没有待执行迁移。
3. 校验 manifest、archive 和全部原件 SHA，在同一事务执行完整数据包及 109 条换绑。回放摘要仅排除数据库派生的 seed 收据，来源内容和既有身份检查均继续执行；不改写采集时间。
4. 重建 web，健康检查后验证并 reload Nginx。恢复调度前核对 153 个 Django 页面、1071 行、101 个时刻、分场/停办展示及旧地区数据；随后启动两个 worker、确认 ready、启动 Beat，核对四应用版本与 QQ。法国、日本浏览器不重建。
5. 解除锁后核对 153 个公网页面、代表性浏览器、分场日历/历年冠军及自然调度。只在成功提交且本机原包摘要匹配后清理本包清单内远端 raw 文件，保留 manifest/baseline/policy/archive 和本机完整包；不全域清理镜像。
6. 整库备份继续不作发布前置。提交前失败则整包回滚；若命令输出中断，先探测数据库收据并等待事务锁，确认未提交才跳过数据恢复。已提交且调度未恢复时，按同 manifest 的 after-image CAS 精确恢复，再恢复 `332fc540` 四应用和 Nginx，保留0084。新 worker 启动后若有写入，先停止相关调度并核对差异，不盲目覆盖。

未来正式卡、赛后自然节点、完整七天观察及 Gallant Bob 实时补源限制仍需分别说明；冻结原件回放不代表来源网站已恢复。
