# 公开赛事时间查询性能

用户已要求完成实现流程。基线 633f80ce（生产诊断版本 f19c7f2d）。目标是消除同一公开查询反复执行 PostgreSQL 时区目录函数，保留全部结果语义。

只修改 race_public_time 的查询构造和相关测试。不改变时间合同、权限、身份、筛选、排序、分页、数据库、采集、字体、Nginx 或 robots。只缓存单条语句内的时区名称，不缓存赛事或 offset/DST。

验收：PostgreSQL 真实执行计划每个公开查询编译作用域仅一次目录 Function Scan，Actual Loops=1；时间边界、公开筛选与分页回归通过；同一 fixture 的旧/新结果全列一致。独立只读 review 后准备精确交付包，交付按根 AGENTS.md。
