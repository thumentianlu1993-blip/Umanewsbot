# C026 局部读取边界测试设计

沿用 C024 原 R 已审方案；仅单 canonical event、anonymous/result/detail。无 schema/view/template/adapter 修改，无生产、网络或真实 proof。

| 编号 | 正反例与验收 | 捕获 mutation |
|---|---|---|
| T01 | 合法 provisional 发布 fixture 先经真实 gate，loader 独立冻结 rows，真实 Client URL/context/content 对账；保留非 confirmed 表格、无 marker/unverified proof | 空 loader、从 response 生成 expected、强制所有行 confirmed、泄露 raw/ORM |
| T02 | bool/非正 ID、naive 时间、错误 audience、绝对 URL/query/编码分隔符/失配 canonical path 拒绝 | 弱类型或任意输入扩 scope |
| T03 | unknown/hidden/draft、不属于 canonical 的 legacy；Client 404/301；历史无 control 页面仍200而 loader unverified | 缺 published/canonical 筛选、关闭历史页面 |
| T04 | source/policy/allowlist/current/publication/observation 缺失或漂移 fail closed；失效结果区和历史 winner 不泄露 | gate 被替代为 published=True、忽略既有拒绝 |
| T05 | multisource 已发表仅 fetch 到期仍允许，publication_revoked 拒绝 | 通用 source expiry 错误撤销已有发布 |
| T06 | 同名 participant 按 source identity 唯一绑定；缺/重复 source refs 或 projection 字段不匹配 unverified | 名字/名次/index 猜身份、projection 未对账 |
| T07 | 顶层只读 REPEATABLE READ；外层事务拒绝；异常恢复 autocommit；200行/256KiB上限拒绝 | 普通 atomic 冒充 RR、外层 savepoint、吞异常/截断称完整 |
| T08 | 独立 writer 在快照期间提交，可读到同一旧快照，退出后新事务复核返回 input_changed；policy/visibility/owner/projection 改变均检出 | 同一 RR 复查、跳过围栏、用缓存实例 |
| T09 | 缺 F01/source time/execution 保持 unverified；as_of/区间/复核时点分开；无 write/provider调用 | 默认0补版本、签 public_verified/SLA |

先运行 fixture+合法发布最小行为 RED；导入/setup 错误不计 RED。再实现同例 GREEN、完整新模块必要PG/Client回归。使用 TransactionTestCase 和独立线程 writer（finally connections.close_all），不触真实数据库。只在 ROOT 标准窗口运行容器；新测试 mapping 由 ROOT 集成。不启动 formal full。新模块使用独立 helper，不走 stable.tests 重导出。
