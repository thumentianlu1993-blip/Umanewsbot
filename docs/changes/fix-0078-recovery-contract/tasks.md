# 0078 修复任务清单

方案审核已完成，用户已授权实施并要求独立测试。下列勾选只表示对应阶段实际完成，生产状态另记。

## 0. 规划

- [x] (operations) 固定main基线，定位回滚、发布、handoff、completion、resume和fixture差异。
- [x] (operations) 区分普通代码回滚禁用策略与0078合同缺口。
- [x] (application) 写出spec/design/test_cases/rollout与证据边界。
- [x] (operations) 完成只读方案审核，修订finding并回同一reviewer复审。
- [x] (operations) 将最终审核结论和文件指纹保存在本change。

## 1. 实现前

- [x] (operations) 获取完整仓库，从最新主线建立独立codex分支/worktree，核对与固定基线的相关差异。
- [x] (operations) 配置不含生产.env的Linux/PG16隔离环境；明确测试端口、库、卷和网络边界。
- [x] (operations) 重现相关基线失败，记录名称/原因；不声称本地源码节选能够跑全套。

## 2. 目标测试（RED 与故障注入）

- [x] (application) T02–T11：完成本次直接路径的graph、纯catalog校验、正向PG模板、不可逆与锁原子性开发验证；旧历史PG场景仍被既有setup错误阻断，见validation。
- [x] (integration) T12–T22/T28/T35–T42：完成开发测试与逐项覆盖核对；专项及三类入口/真实wrapper的最终回归通过，系统验收边界见validation。
- [x] (operations) T23–T27：真实禁用策略、模拟允许与显式代际fixture完成验证；防回归负例保留。
- [x] (operations) T29–T32：隔离备份恢复通过，已核对并记录恢复矩阵与队列测试边界；真实镜像/队列/连接切换验收留在发布阶段。

首批 7 项测试取得 RED 后转为 GREEN；其余用例补充故障注入与隔离集成证据，未声称每项都有独立 RED 记录。实际结果与测试替身边界见 `validation.md`。

## 3. 最小实现

- [x] (application) 新0078目标与窄catalog验证；既有迁移不变。
- [x] (integration) v5 handoff及upgrade/same-schema backup manifest贯穿标准/低成本/manual和全部producer/consumer。
- [x] (integration) 停服前prepared发布意图、active pointer与既有DDL marker/completion分层绑定；扩展resume_migration_history_repair.sh覆盖无DDL marker和schema完成但服务未恢复的断点。
- [x] (operations) 0078 allowlist和显式tail；保持真实生产普通rollback禁用。
- [x] (operations) 重建测试Harness代际输入，保留旧协议fixture与拒绝回归。
- [x] (operations) 更新部署/恢复文档，明确旧世代恢复边界和备份数据损失窗口。

## 4. 验证与交付准备

- [x] (application) 0078专项与修订的shell/夹具回归通过；未通过的历史基线场景单独记录，不声称完整stable或旧历史PG套件全绿。
- [x] (integration) 真实PG16迁移、锁竞争、备份恢复与管理命令链通过；真实host入口的故障重放也通过，Docker/DDL边界使用明示替身。
- [x] (operations) T33完成检查与全量stable同环境基线对比：4925对4886，无新增失败；工作流合同的既有失败与基线相同。
- [x] (operations) 独立代码review及同上下文五轮审核/复审；所有 actionable findings 解决。
- [x] (operations) 整理实现、测试与恢复路径的交付记录，更新必要状态文档；交付为Draft PR #181。

## 5. 后续发布

- [ ] (operations) 按rollout绑定待发布提交、环境、镜像和配置，准备精确发布包与停止/恢复路径。
- [ ] (operations) 按根AGENTS.md取得精确G2/G3交付确认。
- [ ] (operations) 发布前实时只读核对0078、旧意图/锁、队列、镜像与备份。
- [ ] (operations) 获准后执行关闭态无DDL发布、验收与原服务意图恢复。
- [ ] (operations) T34通过并回写生产结果；不执行生产restore演练。
