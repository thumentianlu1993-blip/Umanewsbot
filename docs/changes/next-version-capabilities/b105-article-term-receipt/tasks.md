# B105 顺序与责任

- (application) 原R先审本design/test_cases：版本隔离、SQL上界与resolver完整语义、词典捕获区间/权限差别；此提交仅方案。
- (application) 原两测试模块新增真实v2链目标RED，固定源码/IDs/输入/预期；ROOT分现有隔离PG，业务FAIL须真实，不计版本缺失/环境错误为RED。
- (application) 实施仅steps/consumer/窄codec/terms有界加载器与生成器共用；新v3登记，旧v1/v2不升级；SQL projection/LIMIT、数据类型/bytes严格拒绝。仅对新版本consumer使用持久resolution。
- (application) 新v3目标GREEN＋六组直接受影响场景；SQLite材料helper先行，完整业务/PG锁组由ROOT按资源安排；不新建通用runner/proof服务或Docker/VM。
- (integration) 原R代码/真实结果审、ROOT/C现行影响计划/原35、terms/budget/版本直接回归、正式CI；新增codec路径必要high-risk登记，不改skip/质量线。失败返原上下文修复。
- (operations) 本片不开放真实provider/生产调度、迁移、抓取、身份认证或发布；这类动作仍归ROOT原授权合同。

后续实施从ROOT指定包含固定047e产品对象的主线隔离分支开始，不能覆盖本B树/其他改动。本次责任只本目录design/test_cases/tasks与B104文档及B105 runtime，无业务代码/测试执行。

- (application) R01/R02窄复审前不混入RED源码/实现；新runtime只保存三文档diff、固定源SHA与审核绑定。复审后下一卡接续真实RED准备。
- (operations) 本design/tasks已承载小片spec/rollout。停止/回滚v2代码时已登记v3未知版本拒绝，不升降级、不fallback、不删账/自动重发；无新增生产发布流程。
