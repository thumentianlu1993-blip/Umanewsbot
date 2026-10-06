# C043 第四批局部能力离线集成准备

任务 C043-FOURTH-SLICE-INTEGRATION-PREP-001，2026-10-06。ROOT授权从已审C036固定 `558df2a3bf83d590ccbdb010d3f73dc70d528041` 装配三个获审增量、必要测试映射与本报告。实际fetch origin/main与远端ls-remote均为 `6e6aded22764ebee3d6a97f2834f47d4b4baa7bb`；PR242/C036仍未合并，不改共享main。独立树 /Users/mentianlu/.codex/worktrees/c043-fourth-slice-integration/umanews，branch codex/c043-fourth-slice-integration。ROOT已覆盖当前G1静态范围，G2/G3无动作；人工门禁只引用根AGENTS.md。

## 固定获审来源

| 来源 | 增量base → final | 文件/提交 | ROOT绑定原R与局部证据 |
| --- | --- | --- | --- |
| A036 | 72f82102409bd9d7c6e200fb57a565ed9d23059b → 8c8a1a5367ed5614eadc1b18d0554f58f789ec23 | 6 / 3 | afba3558；prepare-only命令六例及旧精确回归；本片只导入3A文档/fixture/command/test，不导入A035方案祖先 |
| B041 | 558df2a3bf83d590ccbdb010d3f73dc70d528041 → 41650afb55b6a53d005a3371989d20f368d2af30 | 6 / 4 | 152c14b7；原117曾1fixture失败，受影响5修复后GREEN+未受影响112继承；不冒称同SHA重跑117 |
| C041 | 558df2a3bf83d590ccbdb010d3f73dc70d528041 → fbf30e34a774cef01f6bbce5e1a930cff7e44730 | 4 / 3 | 740a9432；五方法2目标RED/3保护PASS→十方法GREEN；C042独立合成可见验收由ROOT另核，不混为生产证明 |

完整10个source commit以cherry-pick -x追踪，三个来源16个文件互不重叠，无冲突、无业务技术返修。所有最终源blob/bytes逐文件相等，精确source→assembled commit和16路径/hash在runtime source-mapping.json。本C仅负责catalog/rules与C043报告；models及唯一0080严格为B041现有字节，A/C没有schema。A037/C042只runtime演示不入应用；B042尚在方案返修，不包含。源报告中的审核前历史字段保留，不改写获审源文档。

## 测试映射及真实依赖

1. 新horse_basic_profile_prepare_command域，准确label stable.test_horse_basic_profile_from_cache_command、django profile；command/单份合成fixture精确路径登记。依赖实际调用的horse_cache_reuse以及P0 canonical adapter与review workbook所在的既有adapter/batch测试域。既有horse_cache_reuse与horse_source_cache_reuse_adapter两条精确路径在保留旧域后追加新prepare域，保证这些实际被调用的服务变化也覆盖新命令，不引入环或宽泛邻域通配。
2. stable.test_translation_retry_budget准确登记news_translation/domain/tests/django profile，保留原translation claim-fence/checkpoint/recovery及其他旧标签。事务预算helper精确路径登记news_translation；helper和新prepare命令保守列高风险full。models.py、migrations/**与feed.html原高风险规则保留，0080自然覆盖，未改原规则意义。
3. C041五新方法由原tests_legacy模块/原core PublicHomeInfoFeedTests标签及django profile完整覆盖，AST准确新增五；不创建重复方法别名、不改旧方法或core。新模块静态方法数A6+B39，加C5共50，只是AST声明，尚未正式collect，不能推算实际新总数或声称已测。
4. 所有旧catalog domains/标签/依赖/test/profile/owner条目保留；allowed_skips、dedicated_batch_modules、全部旧high-risk/symbol/module_initialization规则及12受信controls保持。两处旧路径只扩大实际consumer覆盖，未知相邻command/helper/fixture仍unmapped fail closed。

## 已完成静态验证

- 原scripts.tests.test_test_impact和test_impact_evolution共34项离线工具合同PASS（5.938s），不导入Django应用、不用DB/PG/Redis/容器或真实服务；workflow contract PASS、git diff --check PASS。
- 16来源blob/bytes一致、10来源提交无重复；301个既有登记测试文件逐字节等于底座，唯一tests_legacy移除新增五方法后的整个旧module AST完全相同。新准确50 canonical IDs与class/method行号/profile记录在new-declared-ids.json。
- C038固定底座实际collect的6703 unique IDs逐个仍由候选full标签覆盖；此为旧要求不缩的静态证明，不是C043执行结果。旧318 full标签保留，新增两个模块后320标签/264域。真实方法/子例/分片数量仍待官方collector。
- 每条来源路径的选测、原cache planner/adapter到新command的闭包、三条未知邻近路径拒绝、模型/迁移/template高风险与12controls保护均通过。原C036及源A/B/C树不改；旧C027/C042证据不改，不复跑演示。

固定最终Git后在runtime生成正式模式的full静态计划，来源Git/完整head/tree及file/semantic digest封存；计划不是已收集的execution-plan，count/batches不预填。新增映射需同时保留old/full与new/full覆盖，不缩正式分母。源码与映射统一交ROOT→原R集成review，获准后才另排正式收集。

runtime /Users/mentianlu/.codex/runtime/c043-fourth-slice-integration-prep-001。本任务无PG/Docker/正式collector/full执行/build/pull/push/新PR/merge/main/生产迁移/功能启用/真实抓取/付费或外发，A037唯一容器窗口未占用。候选是静态ready，未宣称integration业务GREEN、正式CI/full通过或交付可发布。

## 来源说明入口

[A036 GREEN](../../A/A-036-h03-prepare-command-green-prep.md)、[A036测试设计](../../A/A-036-h03-prepare-command-test_cases.md)、[B041记录](../../B/B-041-m02-offline-budget-schema-red-prep.md)、[B041测试设计](../../B/B041-m02/test_cases.md)、[C041结果](../C041/report.md)、[C036底座集成](../C036/report.md)。
