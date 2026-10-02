# A-006 真实 PostgreSQL 专项验证准备（未执行）

代码绑定 `3780b662b19327ea2c40419f900053d6213ad0a7`，文档基线 f21058c；当前28例均为纯Python/fake连接，不证明SQL在PG执行。此文仅向协调者申请B005后的短窗口，不启动容器、生产SQL或新主要实现；独立R finding优先，代码变更后重新绑定。测试标签/共享映射仍由root统一登记。

## 窗口与隔离申请

申请单PG、单Python执行器，无并发测试；预计正常10分钟，硬截止15分钟（包括初始化/清理），PG 1 CPU/1 GiB、执行器1 CPU/1 GiB。只复用既有本地镜像，无pull/build/网络访问。临时专属Docker内部网络只连接两个容器，不映射宿主端口，不挂载生产配置/凭据，不接Redis/Celery/第三方。镜像实际SHA、PG版本、代码tree、fixture/harness SHA与全部退出码写私有runtime；结束清理两个容器/网络/临时卷。共享资源未获协调者排程前不启动。

fixture优先使用固定源码的真实迁移建立19表，随后由本地fixture管理员种最小synthetic数据；reader另用非superuser、无写/DDL权限的SELECT专用角色。所有setup/故障注入只作用临时测试DB。迁移预算不够则停止报告pending，不能用手写19表通过来冒充真实迁移契约。必要时手写最小表仅作为另列SQL诊断，明确其不证明Django模型/迁移一致。

## 最小必要用例（建议7组，不是已通过测试）

| 用例 | 本地fixture/注入 | 必要断言 |
|---|---|---|
| PG01 真实schema与12固定SQL | 真实迁移、19表白名单、九地区少量synthetic赛事/档案/身份/版本指针及legacy行 | schema19行全部true，12模板实际成功，status capacity_preflight_finished，inventory_complete=false；逐模板摘要/参数hash/行数可审计 |
| PG02 边界聚合 | 固定2020、近期2023-10-03/2026-10-03、未来2026-11-02与外侧日期；exact/非exact、started/非出赛、缺日期/缺profile；一个profile同时关联事件和record | 事件/目标CTE及UNION去重符合SQL范围；raw参与行不当真马数；staging同source/id仅候选；不把news-only profile缺席误称完整目标 |
| PG03 新闻与公开分层 | 发布时间07-05 00:00+08、10-03末端、10-04 00:00+08；撤稿；published/hidden四组合 | lower inclusive/upper exclusive，撤稿剔除；公开计数按现有SQL字段而非完整可见性合同；候选link状态保留分组 |
| PG04 只读与RR快照 | reader真实连接记录SET LOCAL值；取得snapshot后另一fixture管理员连接插入并commit，再执行后续聚合 | reader read_only=on/isolation repeatable read，三个timeout精确值；当前事务看不到后插入数据，新事务能见；本地独立连接验证写语句42501且不改变fixture（失败事务不混入正常reader调用） |
| PG05 schema fail-closed | 独立测试DB fixture管理员移除一个必需列/表 | schema_mismatch后停止，不执行snapshot/业务SELECT、不重试；返回脱敏partial；恢复仅fixture管理员进行 |
| PG06 服务端timeout/lock | 独立fixture管理员持目标表ACCESS EXCLUSIVE锁，reader触发250ms lock_timeout；另列诊断调用pg_sleep验证statement_timeout=5s | driver错误返回generic partial，后续模板未执行；rollback/close并释放锁，无后台重试。pg_sleep仅测试连接故障注入，不增加生产模板/扩大生产SQL |
| PG07 cleanup与最小权限 | 记录reader backend_pid；正常及PG05/06返回后管理员查pg_stat_activity及fixture校验 | reader会话消失/无idle in transaction，数据摘要不变；临时SELECT角色无创建/插入/更新/删除权限；错误不含DSN/秘密/原SQL异常 |

fixture控制数量：最多30赛事、40参与项、12profile、24identity、20record、12article/link、12staging；都是标注synthetic的本地数据，无真实payload。分别保留期望值表；schema与真实类型依据固定迁移，不猜原生产表。PG01–03复用一份最小fixture，PG05独立DB避免污染正常用例。行/字节/clock上限已有fake测试，真实PG只补SQL/driver/服务端事务证据，不以重复28例替代新增断言。

每次run_counts仍执行120秒、5秒statement/250ms lock/5秒idle、24SELECT/500行/2MiB既有上限。故障用例不扩大预算，不盲重试。输出仅测试编号、synthetic期望/实测聚合、PG错误码的测试断言、连接生命周期与hash，不输出连接串或个人数据。新harness需原R审核/root登记路径与标签后才形成正式test-impact收据；手工专项结果单独命名，不宣称生产计数、许可、H01整体完成或主线交付。
