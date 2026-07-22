# 2026 赛历赛事中文展示名补齐发布报告（2026-07-23）

## 结果摘要

根据发布时保存的执行证据，573 场 2026 年已发布赛事的中文展示名已完成生产写入：
**573/573 单事务写入、0 否决**，写后校验通过。发布时全量复扫记录为：全部 9,820 场
已发布赛事（1984–2026）均有中文展示名，五地区赛历卡片标题 0 原文回退。

上述数字是发布时的已保留核验证据，不是本轮重新执行的全量验收。详情页抽查只保留
4 场记录，低于 spec 要求的至少 5 场，因此发布验收的该数量项未满足。

## 历史审核记录与治理缺口

1. 方案审核（plan-eng-review 等价）：首轮 REVISE（1 high + 3 medium + 7 low）后全部修订，
   同一 reviewer 限定复审 **APPROVED**。
2. 历史记录称代码由独立 reviewer 做了四轮 Claude Code「等价复审」：
   - R1 REVISE：工作簿 5 行含让赛标记，转 manual；decision 列否决契约补一致性校验；
   - R2 APPROVED；
   - R3 REVISE：用户定稿触发未括号让赛指标例外与 Excel BOM（`utf-8-sig`）边界，
     并发现 `verify_applied` 未同步例外；
   - R4 的历史结论记为 **APPROVED**，并记录 build/commit/verify 三层例外一致。
3. 用户审核：工作簿 573 行逐行定稿，209 行改名、6 行人工裁决、8 行重名处理、
   0 否决、0 重名残留。
4. 用户发布授权：2026-07-23 对定稿 SHA `47ba2e32…` 和功能发布提交
   `bd03b100` 回复「发布吧」。
5. 上述 Claude Code「等价复审」不等于现行 `docs/codex_workflow.md` 要求的 Codex 原生
   只读 review；现存证据中没有合格原生 review 的命令、内层 read-only 启动头、前后一致指纹
   和完成结果，因此不能追认为现行规则下的成功 review。
6. 历史交接仍列有 4 项 P3：裸 `H` 正则可能将人名首字母误放行、
   `APPROVE_DECISIONS` 未引用常量、畸形输入使用原生异常、OperationLog 幂等没有 DB 唯一约束。
   没有证据证明这 4 项已清零，也没有根据把它们改称为 non-actionable；按现行规则，它们不能支持
   「成功 review」结论。
7. `bd03b100` 与最终部署的集成版本 `6167b6c0` 不同。现存证据没有证明
   `6167b6c0` 获得合格原生复审，也没有证明在该复审之后取得新授权。生产写入和运行结果
   成功是事实，但不能反向补证这一治理门禁。

## 发布版本

| 项 | 值 |
|---|---|
| 功能发布提交 | `bd03b100`（历史记录为 approved parent `559cec7a`、INDEX_TRANSITION_OK；这不是最终部署版本） |
| 最终部署集成版本 | `6167b6c0`（由 `cc88da3a` 再合入 P0 分支；缺少合格集成复审及其后新授权证据） |
| 定稿工作簿 | `runtime/artifacts/translate-2026-race-display-names/20260721T200746Z/review_573条赛事中文名_复核完成.csv`，SHA-256 `47ba2e32fb96675ffe77888466dfb93f47c34e2489f5888d32fafe140b1d5d7d` |
| 生产 manifest | SHA-256 `b9f1e8b73e84da9df141a78081a1da2ba29d727539f12ce2fb708a95df4375c8`（生产实时 before 构建，与定稿零漂移） |
| batchId（OperationLog） | `d2e2b203d9c3e67f683650c397ed6af038c17123d9c54cf71bdb302b784ce673` |

## 生产执行记录（2026-07-23）

- 部署：生产切换 main 并快进到 `6167b6c0`，执行 `deploy_lowcost.sh`；无迁移，
  HTTP `/healthz/` 返回 200。
- 写前备份：`backups/db/pre-translate-2026-race-names-20260723_012307.dump`，
  232,399,205 bytes，SHA-256
  `cdcc751ed852019830721ddea0894afe04c0fcf7f7c5223921ca947c66edd04c`，
  `pg_restore -l` 得到 1018 项。
- 写入：`--commit` 单事务 `written=573`，OperationLog 绑定 artifact、备份和授权身份。
- 校验：`--verify` 返回 `{"ok": true, "written": 573, "veto": 0}`。
- 发布时已保留核验：DB 全量复扫 published 非 CJK 0、空名 0；美、英、法、日、港五视图卡片
  标题非 CJK 0；巴亚科亚锦标、卓定咸金杯、新手让赛跨栏锦标、凯旋门大赛四场详情页均为
  200 并渲染中文名。但 4 场少于 spec 要求的至少 5 场，该数量验收项未满足。
- 清理：web 容器内的定稿和 manifest 临时文件已删除。本地
  `/tmp/translate2026-manifest-production.json` 当前也不存在；现存证据是上述
  manifest SHA、执行结果、OperationLog batchId 和本报告，不包含临时 manifest 文件本体。

## 本轮当前抽检（2026-07-23）

- 公网 HTTP `/healthz/` 返回 `{"status":"ok"}`。
- 2026 赛历页可访问，抽样卡片标题为中文。
- HTTPS 在本地代理链路握手失败，本轮未将 HTTPS 记为已验证。
- 本轮没有重做 DB 全量复扫或五地区全量页面验收；本节不替代上节的发布时证据。

## 用户锁定的本批命名裁决

- 六条人工定名为：巴亚科亚锦标、大都会锦标、金米勒新手障碍锦标、**新手让赛跨栏锦标**、
  银杯障碍锦标、苏格兰冠军跨栏锦标。
- 赛事 id 666 「新手让赛跨栏锦标」是本批唯一保留「让赛」的人工定名：原文中未括号的
  `H'Cap` 属名称组成，若再删除会与另一「新手跨栏锦标」撞名。
- 重名按本批定稿用地区括注或区别译名处理；美国两条独立 Bayakoa Stakes 系列允许同名
  「巴亚科亚锦标」，底层依赛场与 RaceSeries 区分。

## 遗留（不在本 change）

- 2026 赛历系列与历史系列双卡片的系列级中文化。
- 1,300 条系列术语同步与历史文章回填。
- 未来新增赛事的原文回退会重新累积；本批是一次性批次，没有新增自动通道。
