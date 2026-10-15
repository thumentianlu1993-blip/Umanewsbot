# B148 PR252 S1 finalizer PG RED 测试最小登记整合

2026-10-15。仅准备准确已审测试blob和标准CI登记，等待原R整合审；没有push/CI、候选导入、应用tests/collect/DB/PG/容器或应用实现修改。新增39方法全部NOT_RUN，预期20RED/19既有PASS不是真实结果；完整S1、G159-01/02及Q03/I2仍未完成。

## 固定来源与范围

独立worktree/branch从原PR252准确基线 `a24ac25bce77f5784de0ce8a60154d8143aafd37` / tree `d3c5d3b5307eb03a696a53f18344aeeff106ccff` 建立，原PR branch和他线不动。最终本地head/tree及各blob SHA以独立runtime receipt/seal固定，不追加到原PRhead。

只提取C160 commit `d3b2d20bc909180d2a5840103f11b19692ae53a7` / tree `60ee823cd13243f63a0e1a31a6e29177628ca0b9` / parent `d07f13fe8268e1641be17619bde755ebd93dba6d` 的 `server/stable/test_news_feed_translation_finalize_postgres.py`，blob `611828b8ccd507ad988ff9f79a03e8e404df05ad`，SHA256 `628e026554391462dd106bbd83f820be2a2bbd06e066bccf6d58abe0db10111c`。不cherry-pick整分支，不带入C159/C160私有矩阵/说明。原类NewsFeedTranslationFinalizePostgresTests的39个AST方法/行号逐项同封存矩阵，全actual NOT_RUN。

原R窄复审 `7a968cf7ac6d0b1fc176dc536c0ae4ccad640207`，报告 `docs/changes/next-version-capabilities/reviews/R-C160-s1-pg-test-sqlstate23514-narrow-rereview-001.md` SHA256 `5053cbfdbaa5c40c91ae0ae2b5ad3c1b4c158733c057475fb80ed6ce17058198`，仅认可静态入口。R receipt `de5e3a38b955a987ac3aae53ac9f5e8c4fb3be763e4c495a3dd11a29dda6d9b5`，6 sealed成员已核。C160 prepare-receipt `18eaaf12134e226827bd6bcfd9e7065c92eb25e39f47d253c6ad818da7d4c002`，seal `34517b8cd5e22c29c12ff78883d6602b186627df8e1b47cd344ed2086c751695`的11成员已核；原三处23514分类修正保持，未知SQL/连接/清理ERROR不得计业务RED。

## 最小catalog登记

现有rules已将translation_recovery/translation/tasks/translation_retry_budget列high-risk/full，feed helper exactpath映射q03_news_feed。因此rules逐字不改，仅catalog：

- 现有q03_news_feed与news_translation两域各追加唯一新模块label `stable.test_news_feed_translation_finalize_postgres`。
- 新测试path登记到上述两域，profile明确django。
- 原dedicated_batch_modules四项原样，末尾追加该模块，保证39方法同一TransactionTestCase class独立批次，不能混入python或邻接class。

标签集合去重后由333增到334，domain数不变。测试单path选targeted36 labels，包含原feed/翻译、managed/预算及core，和q03既有legacy/API auth/CSRF/OperationLog/headline/exposure/public projection依赖；feed helper单path targeted20；四个翻译/任务高风险入口full334。原catalog中精确减去上述新增量后parsed JSON整体等于基线；所有旧tests/domains/依赖/profile/owner/allowed_skips/dedicated原项不变。rules/high-risk/module初始化策略没有放宽。

## 有界验证与方法分母

三个现有纯mapping模块共39 tests PASS、0failures/errors/skips，4.967s，parent audit guard attempts=0，未加载django/stable/server/DB模块，只允许本地Git fixture子进程。guard不冒子进程或正式容器独立网络隔离证明。日志的validation-only/missing release evidence来自既有单元fixture，不是此候选计划。

新增永久mapping测试方法为0；新增39仅为准确PG测试源码声明，不将pure39回归次数计入native分母。本卡正负检查为原纯mapping函数与静态数据断言，不伪造PG运行。

原B147真实6937 IDs/profiles来自其已封存execution-plan/方法结果。静态对照：原6937全部保留，新增AST39不与旧集合交集、无重复，profile全django。原shard_tests对旧集合还原原51批完全一致；加入新39后静态预测6976方法/52批，新增独立django batch023，移除新批并重编号后原51组完全相同（后续key顺移，不冒原批key仍不变）。静态预测profile6153django/774python/49release-postgres，仍待后续原生collection验证，实际新native/批次数/RED均UNKNOWN。新39的20预期RED/19预期既有PASS不是实际FAIL/PASS。

正负检查覆盖原域和旧依赖选中、unknown单独及与models high-risk共存均unmapped拒绝、duplicate label/ID拒绝、移除dedicated后原sharder会混邻接class而失败。固定commit的未改原planner、catalog drift负例和完整旧新覆盖计划收据单独封存在runtime。workflow contract静态PASS；没有导入/执行新模块或mock PG runtime。

## 保留与下一步

原B147已接受的PG14/完整6937通过仅属于旧固定运行，不冒本候选通过。原PG14 bytes、C156 helper、应用实现、schema、所有workflow/runner/容器/阈值/时限/pool/旧profile均冻结。原10skip ID/reason/profile/review_by2026-10-16准确保留，0关闭/不延期。

G159-01 foreign token、G159-02取消rollback失败/连接关闭或替换仍缺方法，未来实际seam固定后补，不在本卡新增hook或测试方法。20RED/19PASS预期只有健康fixture后的真实业务断言结果才可接受；import/setup/未知SQL/cleanup错误如实ERROR。原R先审此固定整合包，ROOT再另派唯一标准CI真实RED；本卡没有push、PR改动/CI触发、应用实现、DB/容器/付费/真实抓取/QQ、merge/main/deploy/enable。功能默认关闭、完整S1及Q03/I2仍开放。

本地证据在 `/Users/mentianlu/.codex/runtime/b148-pr252-s1-finalizer-pg-red-mapping-integration-001`：source/matrix副本、39AST IDs、原6937静态并集、正负检查、mapping39日志、固定planner和最终receipt/seal；source副本/私有矩阵仅在runtime，没有加入PR候选。
