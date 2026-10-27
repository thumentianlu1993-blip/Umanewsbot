# 本地固定候选验收记录

## 当前状态

2026-10-27，本地固定候选完整回归及正式核验均为 **PASS**：57批、7681项全部通过，0失败、0错误、0跳过。代码独立复审APPROVED，原9项finding全部关闭。本轮扩围的本地验证目标完成，未合并或部署。

## 固定身份与运行边界

- 候选：`e16a0cb2e7a21c6ac1a3565d4e841a820153b9ce`。
- 测试镜像：`sha256:5fa59696f087c4ba2fdc0fde4e6c95d484e660334332a0256ba739a911766d42`。
- 本地Linux aarch64，Python3.12.3、Django5.2.1、PostgreSQL16.15；network none，独立测试PG，不连接生产DB、Redis或供应商。
- 完整计划7681项、57批：Django47批、三组缓存3批、指定root1批、Python5批、发布合同1批。
- 普通worker为10001:10001且cap-drop ALL；只有精确指定的root权限用例为0:0和SETUID/SETGID/KILL，PG始终10001:10001。
- 完整运行目录：`/Users/mentianlu/.codex/runtime/p01-validation-closure/full-serial-e16a0cb2/`。原始报告在本机保留，不作为仓库数据提交。

## 正式结果与资源核验

| 检查 | 结果 |
| --- | --- |
| 完整原生执行 | 7681项、57批全部通过；完整串行运行约2134秒 |
| 正式 `verify_test_plan.py` | 退出0，`status=passed`、`skipped_count=0` |
| 原测试集合 | 原7662个ID全部保留，新增19个；无遗漏或重复 |
| profile变更 | 恰好9个原ID：8项缓存及1项指定root；其余原ID映射保持 |
| collection与批次生命周期 | collection及全部57批均通过 `require_owned=True` 核验 |
| PG收尾 | 52个需PG的批次及collection，stop/postmaster均0；5个Python批次无需PG |
| 完整PG生命周期日志 | 最大28725字节，原总限额524288字节保持不变 |
| 自有容器 | 镜像reader、collection、57个批次共59个，退出码均0、清理收据均通过；最终daemon只读复查全部不存在 |
| 本次构建的历史合同镜像 | 原始源码/pins、真实image inspect及容器内audit核验通过；镜像已清理并经daemon只读复查确认不存在 |

固定test tree为 `f29addd00f0dfd7fa8471ab2055ad3b6957dda7b`；plan digest为 `e8128f8eb1b5667a0261773c6e4020c7e54c950589ee710b46322c08e0df2036`；run ID为 `p01-full-e16a0cb2-serial`，attempt为1。所有原生结果来自这一次完整运行，未拼接旧通过收据。普通collect-only保持无镜像准备副作用，此次完整收集显式执行prepare-images。

历史镜像合同仍绑定 `1dd5e0a508957672bcddd1c33e454fbbef1b75c1` 及原5项文件pin；本次临时image ID为 `sha256:1809df126bf44bb39b4b975a8511a8613209219f785ecedc0a8a69108b0e5317`。这项证明不代表P01候选生产镜像已经构建或验收。

运行目录中的 `official-summary.json` 为正式集合摘要，`audit-summary.json` 包含原ID保留、profile差异、逐批生命周期及版本，`owned-events.jsonl` 为资源事件账，`container-cleanup-postcheck.json` 和 `image-cleanup-postcheck.json` 为运行后只读复查。`execution-plan.json`、全部原生结果与日志、collection/逐批生命周期文件及 `migration-image-proof.json` 均保留。

完整测试绑定上述代码SHA；后续收尾提交仅更新文档，不把文档提交SHA写成已执行的源码SHA。

## 审核与历史记录

同一只读reviewer对候选结论APPROVED，C1–C9全部关闭，状态指纹 `da2b7fa2cd419bbcff4d55327b221f9d1a48829816ccd7b16a6fd779d46315e3`。定向RED/GREEN及首次并发完整运行的失败见[扩围记录](rollout.md)，旧P01全量失败见[历史记录](../p01-news-quality-20261027/rollout.md#8-实现候选与本地验证2026-10-27)。

## 验收范围

这是本地固定SHA的离线回归，不是GitHub CI交付收据或生产验收。真实输入仍为7份DOM fixture、0份已核来源样本；20篇真实模型评估、100篇gold（其中25篇holdout）、来源许可/真实频率、生产形状验证、发布及启用后168小时观察仍待完成。原卡进度不改；生产开关保持原默认关闭，本轮没有合并、部署、付费调用、新抓取、生产数据操作或QQ外发。

## 收尾文档检查

仓库workflow contract通过，4项契约测试通过；9份收尾文档的18个相对链接及 `git diff --check` 通过。收尾文档复审发现的旧阻断状态表述已修正，真实输入、模型评估和生产观察的未完成项保持不变。
