# C051 第五批隔离集成静态准备

基底固定为 PR243 获审候选 `8b9e1b9d7de2d265c9671dab761b8b86b5fd778f`。
原 PR243 已有正式6755唯一ID/48批原生CI成功及ROOT外部trusted VERIFIED证据，仍冻结待G2。
本线只在独立分支组合A/B获审实现；不改变原PR、共享main或生产。

## 获审来源与依赖

A最终 `0120468d7e16747a2d7d3417c3e9d0d15f37b688`，原R
`723c36f929696beb7a976fe526387656aed4151c`，报告
`R-A042-A043-reviewed-input-fullcode-review.md`，结论
APPROVED_LOCAL_REVIEWED_INPUT_SLICE。独立决策record、dry-run及预冻结已审输入消费入口，
继续使用原H02/H03 writer、事务、七字段baseline、锁和合法重放规则。
A039原消费合同测试及合成夹具是新command测试的显式依赖，基底尚无该模块；随获审最终blob引入。
已有cache writer、career writer及旧fixture/test与来源完全相同，沿用基底，不重复引入。
合成审批时间2026-10-03仅为测试样本，不代表当前可消费业务输入。

B最终 `15ea92f278800451acee675186b2ebe28e44fef3`，原R
`6c7f8f7e0b358be3f7133f8edab3bd6723b9960e`，报告
`R-B046-dispatch-claim-fence-R01-rereview.md` 与原完整B043/B044审阅组合生效。
完整4业务模块、12方法离线消费者与3方法派发claim fence回归均取最终Git blob。
其private offline_test封闭fake及前置seam属于已审依赖；旧无scope路径继续由原合同保持。
原0080、models及旧预算测试与基底完全相同；没有新增schema、迁移或生产activation。
不把离线fake消费者当作真实SDK重试、费用/token/金额账本或M02生产保护。

所有需要替换的现存文件，集成基底bytes与相应获审preimage完全相等，未发生语义或机械冲突。
逐文件source commit/blob/SHA、基底blob、集成bytes和已包含祖先记录在本线runtime。
未引入A/B历史规划文档或候选范围外文件。

## 静态测试登记与待执行面

四个新增测试模块静态声明22 unique方法：A reviewed-input command4、A原consumer3、
B offline consumer12、B dispatch fence3。登记django profile，A新领域依赖既有prepare与cache，
B复用news_translation；原所有tests/profiles、skip、dedicated_batch_modules保持。
A原prepare path映射保留并增加新领域，提取helper及review入口进入既有high-risk/full规则。
仅catalog/rules发生必要登记变化，原12受信controls保持字节不变。

旧正式6755分母的全部方法/模块保留，静态预计6755+22=6777；这不是原生collect结果。
导入的既有TestCase别名须在未来原生收集时去重与核profile，不能把别名当新增ID。
正式计划草案按现有catalog演进full规则保留旧/新覆盖，原普通600、release2100、max4、
200普通分片与专属分批不修改。实际collection/报告、整合后的业务回归和独立review均待后续窗口。
A/B旧GREEN分别有跨SHA继承边界，本集成SHA尚未执行业务测试，不能继承为同SHA全过。

(application) 静态方法/依赖解析与原分母保留检查；(integration) 精确获审blob组合及catalog映射；
(operations) 0080/models/12controls保护、diff-check与原计划合同验证。
本线静态准备完成后交原R集成审核，后续由ROOT安排窗口；人工门禁仅引用根AGENTS.md。
