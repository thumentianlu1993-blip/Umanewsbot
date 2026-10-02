# U01 实施测试设计

受审依据：U01-plan@2919dd35、协调者C-003派单与U01-offline-cases.json；承接总规格TC-U01。当前只读查询，无模型约束/迁移/Celery投递行为变更，不引入额外生产动作。既有未知/冲突数据保留待核实，GET不持久写等级字段。

| 用例 | 验收与mutation |
|---|---|
| U01-RED-01 | 同一德国2025G1原文/空规范字段在未筛选与G1筛选均可见且卡片g1颜色；两展示开关覆盖。捕获仅修模板、继续normalized_grade__in、取页后过滤 |
| U01-PARITY | 全部33合成场景及Unicode/空白/已核验JRA源上下文扩展；SQL代码与Python event_grade_field.code相等，未知/冲突排除分级查询。捕获宽松substring、忽略存储冲突、未证LocalG1升级、错误移除赛事名后缀 |
| U01-VISIBILITY | published/canonical exclusion/地区年份交集保持；隐藏/duplicate事件不因等级别名被公开。捕获OR优先级扩大集合 |
| U01-PAGING | 混合等级跨页、默认日期窗口、year/q游标；筛选在LIMIT前，游标不混筛选条件。捕获全表Python过滤/先分页再过滤 |
| U01-FOCUS | 历史重点G1/G2集合及weekly focus传入events/独立query分支；当前priority规则保持。捕获遗留normalized-only消费者 |
| U01-NO-WRITE | GET前后原始等级/normalized/source_refs一致；使用querycount确认无逐行DB查证。捕获隐式补字段及N+1 |
| U01-COMPAT | flag两状态等级一致，既有距离/单位legacy开关保持；卡片文字/颜色/详情等级相同。捕获为修等级开启全局单位规范化 |
| U01-PG | 固定Git树/Linux无外网容器/PostgreSQL16 native expression语义与SQLite诊断分开；数据库表达式不兼容即失败并报告，不新增schema或扩大运行环境 |

正常外部恢复、超时、Celery重投等不在U01新增行为范围；生产取数不用于自动测试。保存版本保护仍由既有路径保证，U01只消费读字段。未知后端/SQL失败不能回退全表后过滤。返回旧代码SHA即可回滚代码，数据字段不需要反向迁移。

首个RED最小测试在现有 `test_race_information_display_pages.PublicGradeFilterParityTests`；从真实断言漏对象开始，再同例GREEN与受影响计划回归。宿主SQLite结果只作诊断，不作为固定Linux交付证据。测试模块沿既有catalog，修改后执行影响计划；每批最多200项，共享VM总最多2批。
