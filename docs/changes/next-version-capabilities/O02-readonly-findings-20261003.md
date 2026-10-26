# O02 备份恢复缺陷只读取证

2026-10-03，Asia/Shanghai。对应 C010 诊断设计 `b955f45432ca37f9397887de4c20a9769cccb7b0` 的 Q1–Q6；由协调者通过既有 SSH 与现有应用环境执行。本文记录当前观测，不是修复方案或生产写入授权。

## 运行身份和预算

19:52:18 与19:53:32 两批均先核唯一 web 容器，实际 ID `9f03d1faa0ccf681d50dd2a9db6018af55a33937bf94517b0d447f453ac2190c`；image `73ee1dcf7edb5b7c7bda49f5d6baedffe030d639fcc5bf191b831ece6e9f5930`，label 与 `/app/.umanews-release-commit` 都为 `ad50abdb74b89669ab8ada2958b040877c1a1849`。未从历史环境变量推断版本。

使用专用 PostgreSQL READ ONLY / REPEATABLE READ 连接，statement 3秒、lock 250毫秒、idle 5秒、work_mem 4MB、temp_file_limit 16MB、parallel=0。每批远程 Python 25秒、Docker调用35秒、外层SSH45秒硬期限；成功与异常路径均关闭连接，两批实际 rollback/close 均完成。元数据查询四条合计约0.11秒；重复汇总阶段另设总9秒剩余预算。未执行 DDL/DML、ANALYZE、REINDEX、抓取、消息或服务操作。

## 当前元数据

- 数据库为 PostgreSQL 16.14 / UTF8，两个目标表都在 public。数据库使用 libc `en_US.utf8`；记录版本与 actual version 均为 null，不能解释成版本一致或无漂移。
- 新闻唯一约束为 `(source_site, source_article_id)`，术语候选为 `(term_type, source_language, normalized_key)`；两者均普通 UNIQUE btree，无表达式或条件。convalidated、indisunique、indisvalid、indisready、indislive 均 true。
- 五个键列都 NOT NULL；索引使用 collation OID100，与列的 default deterministic collation 一致。现有索引标志没有证明 heap 数据唯一。
- 实际全 schema 入站外键共21条，新闻19、术语候选2，与 C 的静态声明数量一致。完整定义已私有保存；它们不覆盖 JSON、审计、公开URL等非外键关系，也未证明重指无唯一冲突。
- 新闻表估计19,392行、heap 36,388,864字节、total 555,499,520字节；术语表估计12,014行、heap 2,646,016字节、total 11,051,008字节。reltuples是估计，不作为真实总分母。

## 强制 heap 的同字节重复汇总

先执行 EXPLAIN FORMAT JSON（未 ANALYZE），确认每个目标使用 Seq Scan、没有 Index 或 Parallel 节点。禁止 index/index-only/bitmap scan 与 hash aggregate；键转 UTF8 bytea 后在 MATERIALIZED CTE 之外分组，不依赖已知唯一索引或其优化假设。

| 目标 | 重复键组 | 组内总行数 | 超出每组一行的行数 | 最大组行数 | 实际查询耗时 |
|---|---:|---:|---:|---:|---:|
| stable_newsarticle | 8 | 47 | 39 | 13 | 0.0604秒 |
| stable_termcandidate | 226 | 558 | 332 | 19 | 0.0527秒 |

这是当前同字节键重复的观测。没有输出原始键、对象ID列表、正文或用户信息。未执行 Q7 私有报错键查询，也未按本结果保留/合并/删除任何一行。

同字节重复证明问题不止是“两个不同字节字符串被某种排序规则视为相同”的情形，但不能凭此断言损坏来源、发生时间或单一根因。恢复仍未修复，未重跑完整恢复。下一步由 C 按真实21条外键设计受限的引用计数、重指唯一冲突与内容差异布尔；非FK/URL/人工修改必须一并保全，不能默认最小ID为保留对象。

## 私有证据与下一步

- 目录：`/Users/mentianlu/.codex/runtime/o02-readonly-20261003/`，本地私有权限；脚本只通过stdin执行，没有在生产写入采样文件。
- `metadata-receipt.json` SHA256 `0b60dc3ffe0092e714e65a894a9d9b56fb72e747b0e0231bcf877b5123f8e14d`；固定查询与完整FK元数据。
- `duplicates-receipt.json` SHA256 `5b0f57e98b0d1481ff56a4ae436a8be1c134acedaf74c070395b6688c9694fc3`；包含完整EXPLAIN、聚合结果与连接收尾。
- 只读方案与更早的失败dump证据相互补充；旧dump和旧恢复日志保持原样。隔离复现、关联守恒、完整备份后整库恢复、RTO/RPO和精确生产包仍未完成。人工确认统一引用根 [AGENTS.md](../../../AGENTS.md)。

## 20:14 第一完整组 pilot

协调者核验固定 manifest `413c0681980ecc24773c04870340a3f91af09b27b8c3f93562ba7414ad7dda73` 后执行，生产 web/image/revision 与上文相同。两条专用只读事务分别执行4与3条 SELECT（包含两次非 ANALYZE EXPLAIN），均 rollback/close；查询阶段0.2509秒、服务器包装1.5946秒。保留3秒statement、250毫秒lock、5秒idle、4MB/16MB/parallel0限制。

完整新闻8组含47个ID；术语仅取前20个完整组、40个ID，当前总数仍226组558行。每组完整，未拆组或截断；此结果不代表术语全量关联分析。实际补充35个唯一索引定义、54条出站外键定义、133个所需列元数据，均未触及输出上限。最小ID只用于稳定枚举顺序，未选择保留对象。

本轮为私有证据保存创建专用服务器临时目录和600文件，属于诊断产物写入；没有数据库写入或服务操作。容器内临时文件已清理，服务器私有副本保留；本地私有副本已通过SSH取回并校验SHA。原文/键值/ID未写入仓库。

摘要位于 `/Users/mentianlu/.codex/runtime/c010-o02-pilot/pilot-summary.json`，SHA256 `72a9361aeadd2e610709b4d3fb02e82ee56fcb1152474db8b9888d608f6674f5`；私有完整收据 SHA256 `509033d22c6fec32faec63005bb9232f4650c1d6e40dca8e841e33376eb7e949`。C据此准备仅覆盖这28组选定记录的有限入站引用计数及语义摘要包，由协调者审包后执行。修复策略、非FK保全、完整恢复与RTO/RPO仍待。

## 20:34–20:37 已选28组的引用与语义诊断

固定 followup manifest `ecee18ee55b2b73044dc2849a7ac046de358a0ff2dcc4f937b1807469b61a0d9`，逐批选择执行原 news8组47行和 term20组40行，没有扩到全部术语组。每批先核相同 web9f03/image73ee/ad50，沿既定只读/超时/内存限制。8批的rollback、close与容器临时证据清理均完成；各批使用独立snapshot，不是全图一致性守恒证明。

18/21条外键计数完成，输出无截断。非零关系如下；“被引用父行数”仅该条外键范围，不可跨行相加当唯一对象总数。其余13条已完成关系计数为0。

| 外键/子表 | 引用行数 | 被引用父行数 |
|---|---:|---:|
| FK03 automationlog.article_id | 34 | 28 |
| FK18 termcandidateevidence.candidate_id | 1088 | 40 |
| FK19 translationrun.article_id | 47 | 45 |
| FK20 windowcandidatedecision.article_id | 252 | 25 |
| FK21 windowtargetdecision.article_id | 11 | 1 |

references-4 的 FK10 newssnapshot 在3秒statement_timeout下被取消（SQLSTATE57014）；完整回滚及关闭，无重试或加时。已保存非ANALYZE EXPLAIN的SeqScan估计3,406,175行，这不是实测总行数。该批FK11 pushlog和FK12 qqpushdelivery尚未执行，三者明确未知；失败隔离后其余独立批次继续完成。

语义查询仅在数据库内计算分层SHA256，再返回组内差异布尔，没有取回原文、URL、注释或原键。所选父行无缺失：新闻8组中identity层5组有差异、content层6组、manual层0组、public_basis层8组、references层8组；术语20组中identity/content/references均0组差异，review层1组、evidence_counters和times各20组。identity层同时包含来源模式、语言、URL，这些布尔不能单独解释成实体不同；相同唯一键也不能直接解释成记录可删除。

8份私有收据已逐SHA取回本地600文件，索引 `/Users/mentianlu/.codex/runtime/c010-o02-pilot-followup/followup-index.json` SHA256 `c9dfc48b72380773daa020095cd7626dc0630014ae88b82a9be54fc54181cf87`。服务器私有诊断副本保留；没有DML/DDL或服务动作。

下一步补FK11/12、以元数据与有界heap分段设计补FK10，并核新闻重复键是否为空/占位的布尔事实，避免错误合并不同文章。碰撞、非FK、全部术语范围、保留策略、隔离恢复和精确生产包仍未完成。U02主要开发不因该只读超时全线暂停。


## 22:36–22:38 固定 tail 补证与收尾核验

固定 `package-manifest.json` SHA256 `e627b6ef77f715206ce14403a800469da7ec555b4d7dee4c1f42a3ecfe145b55`。现场再核 web9f03/image73ee/ad50、原 seed509033d2、无部署锁或匹配的冲突进程；上传7个固定代码/设计文件至专用私有临时目录，随后逐个显式执行三个 batch。代码、查询与原输入 hash 不变；不重新执行已完成18条或超时的FK10。

| 批次 | 实际 SELECT（含非 ANALYZE EXPLAIN） | 数据库阶段 | 结果 |
|---|---:|---:|---|
| metadata | 1 | 0.0383秒 | newssnapshot heap950927360字节、block8192；pushlog0字节；qqpushdelivery1245184字节 |
| references-tail | 4 | 0.0396秒 | 原8新闻组：FK11引用0行/父0行；FK12引用1行/父1行，无cap |
| key-class | 2 | 0.1008秒 | 原47父行全部仍在，来源站点/来源ID/URL的空串或ASCII btrim后空均0；非空URL同字节等于ID为0；每组内非空URL均相同 |

引用计数累计完成所选组20/21条外键，FK10快照仍未知；快照表约907MiB（116080个8KiB块），不能放宽原3秒整表限制或把估计当真实行数。新闻键分类不证明值是真实合法来源ID，也不抹去此前6组内容差异；术语仍仅先前20组，不推断全部226组。各批独立snapshot，仍不是完整引用图或守恒证明。没有选择保留对象、301、去重、数据库写入、服务操作或生产CTID扫描。

三批均原限制READ ONLY/RR，rollback、close、容器私有证据清理成功；服务器私有文件owner/0600/hash实际复核并复制至本地600文件。独立只读观察在22:38确认本次tail application_name的后端数量0，observer连接也已关闭。该观察只证明当时已无该名后端，不追认未执行的超时/异常清理路径。

证据目录 `/Users/mentianlu/.codex/runtime/c010-o02-tail-prepare/`：metadata、references-tail、key-class 的 safe summary SHA依次为 `dbd51f4dc6520de90569192506d6f4413467f6897e8cee8fbc66d1dd2bd9e2a4`、`8be1a18f88252c0395b06e80ff4dfcb3c5816b4496ae1f0f950bff3dac636cc9`、`267c81b769ec20d6f5280b27a63df309ab33218fe6fe17e5e3ba247217c82e79`；`root-final-verification.json` SHA `833d0c6c46f740f97f62ee5572d12b0191ff767a58b988e88c454779a9c1542a`。完整计划/组别摘要保留在该目录的私有 `root-private-receipts/`，不入仓。原R `fb8a1807` 已批准本次三批实际收据与覆盖陈述；未重新审查此前18条外键。下一步先验证隔离PG16中的有界快照分段方案，再判断是否形成新的生产只读精确包；完整恢复仍阻塞。
