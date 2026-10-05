# C023 最小测试接线验证用例

范围依据原 R C022 `5f5c7fb8a8ffdc9e5f65facef0ff022b0b8b2d79`：固定 main 装配23文件，独立 testing_public_probe 包、全名导入与 adapter 类内 override_settings；不改 adapter/templates/schema/fixture 业务字节、legacy 测试入口、共享 mapping 或生产。

本卡按明确派单只编写/静态核验，不运行测试、collector、Django setup、hostcompile 或容器。以下 RED/GREEN/正式结果均 NOT_RUN；不把导入失败或静态AST扫描冒充行为RED。仓库 TDD 技能作为测试设计兜底；本卡明确“先不运行”的任务指令决定执行安排。实际测试须固定新SHA、独立审核后由ROOT安排。

| 用例 | 验证层 | 行为与可捕获 mutation | 当前状态 |
| --- | --- | --- | --- |
| G01 标准collector收集 | 正式collector为主；专用label自动化回归为辅 | Django setup后仅标准sys.path加载 adapter/glue labels，canonical方法归属正确、无FailedTest、legacy额外收集/重复/unowned；捕获裸support import、stable.tests重导出或漏profile | NOT_RUN |
| G02 固定render环境、SQL禁用、成功恢复 | 新glue自动化 | 在与本片不同的外层URL/模板/cache/语言/时区/flag设置中，通过unittest正常class生命周期运行继承adapter设置的单一探针；三个reverse及实际模板加载成功，default cursor因databases=set禁用；INSTALLED_APPS/DATABASES不变，结束后所有覆盖键与cursor包装恢复 | NOT_RUN |
| G03 失败恢复、不污染相邻测试 | 新glue自动化 | 同一类探针核完环境后制造受控assert失败，内层Result仅记录该失败；class cleanups后外层设置/DB限制包装仍恢复。捕获缺tearDownClass/addClassCleanup、异常路径泄漏；该内层控制失败不是业务RED | NOT_RUN |
| G04 旧离线业务语义 | 正式full中新adapter/parser组 | 既有原方法及fixture输入完整保留；正例/负例/预算/算术/HTML反例仍受原断言约束，不预填旧114/625为新树通过 | NOT_RUN |
| G05 全套相邻环境 | 正式full/可信执行收据 | adapter批前后其他django测试仍保有正式PG16/UTF8、合法DB测试可执行；不用全局SQL/network guards。真实network-none/nonroot由runner核，不用mock代替 | NOT_RUN |
| G06 交付身份与完整分母 | formal plan/collection/execution/verifier | 全量canonical IDs/profile/≤200整类batch/有界并发，原10允许skip逐ID/reason；绑定实际base/test-tree/image/run/job/attempt，不用旧fixture身份替代新Git树 | NOT_RUN |

静态先核：23装配原始SHA、21main依赖、7v6入Git；14裸import全部改同一包；空init、无stable.tests/legacy/global sys.path；support fixture根；原3URL name/path；class databases=set与override范围；业务文件原SHA不变；辅助模块迁移逐路径/字节差分。静态通过只证明装配和接线结构。

纯parser依赖链沿python，adapter和新增glue沿现有django；ROOT持有domain/catalog/profile修订。共享模板/测试基础设施触发formal full，unmapped先fail closed。

不涉及新增模型/迁移、生产权限规则或Celery投递，实现片不增加这些测试或宣称其覆盖。真实loader/匿名views/ORM权限、浏览器CSS、来源→执行→公开SLA/失活、队列外/workerBeat/probe自身故障属于后续范围。
