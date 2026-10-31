# 顺序任务

1. (application) 产品spec与技术design，独立只读方案审查至通过。
2. (integration) 方案通过后编写test_cases，补上下文/预算/路由/修复/缓存/发布契约RED。
3. (integration) 实现确定性实体与审校引用定位、预算和模型模式、硬检查/局部修复、证据复用。
4. (application) 集成状态机及发布二次核验，完成GREEN和受影响回归。
5. (operations) 固定SHA隔离验证、独立代码review至通过，冻结3篇小测manifest。
6. (integration) 执行最多3篇、增量0.50美元小测，核对收据与费用，人工抽查并记录局限。
7. (operations) 回写实测和当前状态，交付候选；不合并/部署/外发。

当前：1–4完成，5的代码review已通过，正在固定提交与小测包。6–7待执行。按用户补充要求只运行定向测试，不运行7000多项全量CI。
