# C010 / O02 测试与验收设计（未执行）

承接TC-O02与O02-plan.md；当前只提交文档。运行资源与私有真实副本由root安排，自动测试使用合成数据，外网/provider/生产DB/Redis/QQ/邮件不参与。未取得根因事实前不编写apply脚本，也不假造RED。

| 用例 | 输入与断言 |
|---|---|
| O02-REPRO | 私有原dump绑定SHA/大小、PG镜像/客户端/schema/collation；实际完整恢复复现原两约束错误；退出非0且留错误收据。SHA/TOC可读不能转PASS |
| O02-EQUALITY | 合成byte相同、byte不同但collation等价、不等价、源目标collation版本不同组；分别保存heap/index读取与相等规则，不能用valid flags或换C规则消灭反证 |
| O02-REFERENCES | 从实际catalog所有schema和代码契约枚举FK/self/非FK引用；遗漏一条引用或未知字段即阻断；避免CASCADE删证据、SET_NULL丢出处 |
| O02-KEEP | 相同内容/不同人工稿/公开与未公开/术语accepted不同目标；未经明确规则不得按最小ID或最新时间挑保留者。冲突有证据与阻塞状态 |
| O02-CHILD-COLLISION | 重指触发race/horse link、地区、term evidence、delivery、window decision同键碰撞；未声明逐子表策略整批不写；发送历史保留且发送调用为0 |
| O02-CONSERVATION | 精确行数delta、引用逻辑多重集、人工字段/公开依据/媒体/来源digest、术语上下文及审计历史均符合manifest。合并计数按去重定义，不简单叠加distinct article计数 |
| O02-IDEMPOTENCY | 固定manifest重复apply不再改数据；中断/失败可回退；missing ID/schema/collation/digest漂移、并发在线更改立即fail closed；未知结果先检查状态再决定重试 |
| O02-FULL-RESTORE | 修复副本生成全新完整dump，第二个新空目标完整恢复退出0；所有约束/索引/触发器及migration catalog完整，heap两唯一键无重复、FK无孤儿；禁止排除失败项 |
| O02-REPEAT | 第二次恢复用新空目标得到相同对象/行数/关系；旧schema到新schema不能因clean留下新增对象而声称exact旧状态 |
| O02-APP-COMPAT | 固定当前/拟回退镜像在约定schema只读启动及关键页面读取成功，无队列/provider/通知；forward-only schema不执行逆向migration |
| O02-RTO-RPO | 记录snapshot点、dump与恢复/索引验证/可读时间、模拟切换停写与恢复点；RTO/RPO实际计算，不把演练总耗时等同RPO或宣称零损失 |
| O02-RESOURCE | root给定CPU/内存/磁盘/temp/锁与硬期限；SQL超时或资源不足只记unknown/blocked，不自动放大预算；B独占窗不冲突；私有数据不输出 |
| O02-ROLLBACK | 新旧备份真实恢复有效；逐对象回退或新库切换在副本验证；恢复点后在线变化与可能损失窗口显式记录，不以代码rollback替代数据恢复 |

首个真实RED随根因选择：若现有恢复路径/合同有可复现错误，合成数据用实际dump/restore与失败断言；若只是生产异常数据，保留原副本约束建立失败作为运维反证，再对固定数据方案验证，不制造修改脚本测试的假RED。deploy/tests现有fake CLI合同仅证明参数/文件收尾；不能替代native PG整库验收。

验证产物需绑定commit、manifest/dump SHA、镜像/PG/schema/collation、运行窗、完整日志摘要及私有收据路径、行数/关系报告、RTO/RPO和清理收据。root负责正式验收/交付，本线不写共享TC/mapping与状态文档。当前所有运行用例未执行，O02未通过。
