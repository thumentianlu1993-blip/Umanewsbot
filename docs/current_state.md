# 2026-10-28 P01 来源问题修复与复验完成（候选，未部署）

候选代码 `741334cc` 修复SCMP正文取错、国际来源首发时间遗漏、Sporting Life发现链空转和TDN地区直接继承来源的问题。当前文章时间采用身份或专用文章容器绑定；推荐/更新时间及付费预览不能冒充完整输入。逐稿地区保留证据，既有off/shadow、历史稿和人工锁策略保持有效。

22份国际真实缓存正文结构与时间复验通过，Sporting Life单页发现14条候选；日本两页重新取证缓存重放通过，原8份旧缓存缺HTML结果保持。独立复核R1–R3全部关闭；固定SHA本地离线完整回归7696项/57批全通过，0失败、0错误、0跳过，执行集合、owned生命周期和自有资源清理核验通过。详见[修复报告](changes/p01-source-verification-20261027/repair.md)与[机器证据](changes/p01-source-verification-20261027/repair-evidence.json)。

本轮未合并或部署，没有生产回填、开关/频率变更、模型调用或外发。尚无人工gold；真实模型评估、五区覆盖和发布后168小时验收仍未完成，不能把本地修复当成生产数据已更新。

# 2026-10-27 P01 来源验证完成，输入质量问题待修复

已对当前生产作只读盘点：15条启用/批准配置、9个新闻提供方，7日7049次任务中115次failed。用户明确确认已有所有来源授权，本轮据此记录，未审阅文件。取30份真实缓存样本离线重放P01，20份通过正文结构检查，8份缺原始HTML、2份缺正文边界；没有把诊断样本当gold。

已复现日本生产旧缓存缺HTML（候选已修复，本轮各一页新样本验证通过）、SCMP推荐卡片混作正文、HKJC/Sky/Sporting Life源时间不可靠、Sporting Life发现链空转及TDN跨地区归类问题。详细配置、样本ID、来源URL、限度及修复建议见[来源验证报告](changes/p01-source-verification-20261027/report.md)与[机器证据](changes/p01-source-verification-20261027/evidence.json)。本轮另做两次指定日本页面GET及离线回放，没有改运行代码、生产数据/配置或启动生产采集；实际模型评估和168小时P01业务观察仍未执行。

# 2026-10-27 P01 扩围修复完成，本地全仓验证通过

用户授权的P01实现及验证扩围位于独立分支 `codex/p01-news-quality-design-20261027`，未合并或部署。业务实现包含新流水线、独立不可变稿件、五区feed、后台和报告；迁移0083–0085只在隔离PG执行。

验证扩围候选为 `e16a0cb2e7a21c6ac1a3565d4e841a820153b9ce`：已修正巨型SQL测试输入，增加8项冻结真实缓存、1项指定root和1项历史镜像的隔离执行条件，移除原10项skip豁免。未提高日志限额、放宽原断言或修改缓存字节。同一独立reviewer已关闭C1–C9，结论APPROVED。固定SHA完整串行回归7681项、57批全部通过，0失败、0错误、0skip；正式计划及owned生命周期核验通过，59个自有容器和临时镜像均已清理并只读复查。原7662个测试ID全部保留、新增19个。详见[验收记录](changes/p01-validation-closure-20261027/validation.md)。旧全量失败与本轮首次并发超时记录均保留，不拼接旧回执。

实现阶段仅盘点7份DOM fixture、0份已核来源样本；本轮来源诊断另取30份真实缓存，尚未人工标注为gold。20篇模型评估、100篇gold含25篇holdout、来源许可/频率、生产形状验证、启用和168小时观察未执行。原卡百分比未改，旧8线未恢复。生产开关默认关闭，没有付费模型、新抓取、生产回填或外发。以下保留方案及交接历史。

# 2026-10-27 P01 新闻方案设计与独立评审

用户已完成10题产品澄清，并明确授权本线程设计开发方案和派出子Agent评审。当前只进行文档设计与评审，不恢复旧8线或生产任务，不代表开始实现。

方案分支 `codex/p01-news-quality-design-20261027`，基于交接 `e4df6bda`，见[产品规格](changes/p01-news-quality-20261027/spec.md)、[设计](changes/p01-news-quality-20261027/design.md)、[测试](changes/p01-news-quality-20261027/test_cases.md)、[任务](changes/p01-news-quality-20261027/tasks.md)、[交付与评审状态](changes/p01-news-quality-20261027/rollout.md)。原卡百分比保持不变；用户已明确“单独发一篇新稿件，不修改旧文章”；同一独立reviewer共4轮关闭8项问题（首轮7项及追加决策后的关联隔离1项），最终APPROVED，无剩余finding或待用户决策项。业务测试、CI、真实模型评估和生产操作均未执行。G1范围来自当前指令；后续交付依根AGENTS处理。

# 当前工作状态：2026-10-26 业务项目交接

用户已停止旧多线协调，要求把全部任务、进度和源码整合后交其重新规划。本次仅做本地源码保存、需求映射、优先级建议和完整spec交接；未恢复开发、定时任务、生产采集或通知。

统一worktree：`/Users/mentianlu/.codex/worktrees/business-handoff-20261026/umanews`；分支：`codex/business-project-handoff-20261026`。

- [业务项目总入口与完整spec](changes/business-project-handoff-20261026/README.md)
- [原100卡内容/进度/动态台账](changes/business-project-handoff-20261026/cards/all-cards.json)
- [整合校验及未验证事项](changes/business-project-handoff-20261026/validation.json)
- [原current_state逐字快照](changes/business-project-handoff-20261026/original/docs/current_state.md)

四线最新保存HEAD均为本分支祖先，原分支及其工作区保留。整合未运行DB/业务测试/CI或独立review，不能继承旧单线PASS；没有合并共享main、部署、启用或生产验收。C265源码准入、C266取消后UNKNOWN、B285stop4>3与B286待审未跑事实均保留。原10/30排期未重新承诺，用户重定日期与实施项目。

后续新会话按用户所选spec实施；不得自行唤醒旧8线或恢复自动任务。人工确认唯一来源为根AGENTS.md。
