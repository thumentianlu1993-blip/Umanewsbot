# 独立审核与操作边界

2026-09-18：race_code_reviewer 首轮 REVISE（无冠军/错误竞争名次、旧source_refs语义残留）；主线程补失败测试和门禁，PostgreSQL 17项通过，含并发接管、字段锁、结果变更及非完赛实际公开页。

第二轮 APPROVED 仅日本20场256行。manifest `761155c77db87b599d361fb04a78f28ccf771114bfec2f30290b976228ffaa42`；脚本 `ae54937f83c42109aa0eb8d8cd5b7f635685bed461a896f9fb5b8ad61adf2b2a`。Reviewer独立提取20份HTML核对所有行。原82行保留ID和丰富字段；2条中止完整保留。japan-v1是未执行探索包，禁止应用。

执行：固定提交脚本 + 精确manifest SHA + 生产资源锁 + 原生产镜像，先dry-run，逐赛事事务再验完整after与审计；任何漂移停该场，不改基线绕过。此次用户“完成补齐和回填”的指令覆盖该批资料操作。无迁移、无其他通知、无owner/runner/赛时/路径变更。最近已校验全库备份见 服务器内发布证据；每场完整before留在不可变包，恢复采用审核后的前向补偿，不整库还原。

后续批次单独冻结和审核，不扩改已批准包。


## 后续批次与赛前展示

102场865行 reference-v3、829七行 ZT（含明确落马）、948–953六场81行 retired-v2 均经独立原文审核并生产预检、回填及完整重放通过。合计129场1209行。退役范围只读保留原控制/注册根，写前shared registry barrier，21项历史回填PG测试通过。

未来参考卡直接写 canonical 会导致TRA不同ID重复建马，复用现有候选展示只加入人工核验参考卡入口；完整卡接管或handoff后整份隐藏，不增加表或自动来源。代码review发现退赛状态DTO缺少显示方法、时间测试依赖真实时钟，两项均先复现后修复。61项相关PG测试通过，包含真实页面与事务回滚。


## 最终增量审核

Parx两场9/11名单单场原文、原始JSON-LD及所有profile ID独立核对通过；191 NAR原始HTML与12条马号/枠/姓名/原简称/负重/horseID全部一致。NAR新增测试先RED2失败再GREEN，review唯一执行metadata提交号finding修复为a115bb56，writer字节固定一致。

主线程收尾发现通用apply只拦JRA、未拦新reviewed候选；先新增真实失败用例，再按source_name或raw_payload任一标记在所有写入前拒绝。原reviewer终审APPROVED；70项断言首次通过但共享测试库清理冲突，切换独立测试库后70项完整运行并清理成功、退出0。最终应用提交7e111914；该审核时点尚未发布，随后发布结果见下节。


## 发布与交接审核

用户确认精确包后，由主线程执行普通expected-head合并与固定7e111914发布。验收脚本经同一race_code_reviewer复核，三处可能误报的健康/时间检查已修正并APPROVED。最终同run失败集合及与生产参考的比较，race_code_reviewer、race_plan_reviewer均独立重算为新增0；两者批准准确保留GitHub日志汇总pending、以原始工件完整比较满足原合同，未改变产品范围或绕过必需检查。

发布后运行态、备份、锁、四应用版本、9场预览及JRA/入口收据经race_code_reviewer审核APPROVED；129历史页完成后，race_plan_reviewer进一步独立核对129页1209行、9场双域名154显示行、公开证据安全和顶层文档一致性，交接APPROVED。保留历史3/未来10缺口和45个旧失败，不声称全部资料补齐或全量测试全绿。
