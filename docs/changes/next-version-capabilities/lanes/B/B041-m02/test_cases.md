# B041 离线核心测试设计（GREEN 准备）

固定 RED 输入703e1620，官方receipt278e19bf：12实际运行，6schema通过/6业务失败/0errors。ROOT现派离线GREEN准备，运行窗口另派；本文件先于状态实现。已审B040保守身份/期限/unknown/删除兼容合同不变；无生产caller、SDK、真实fee/token总额或outbox。

| 条目 | 输入/验收 | 捕获的 mutation |
|---|---|---|
| 核心六RED | 既有12方法原样保留：持久计数/attempt、unknown reason、同源删建旧根、PK复用拒绝、最后槽单胜者、首次并发单根 | 只返回allowed/内存计数/按PK或新UUID充值/漏数据库unique |
| 请求幂等/计数 | 同claim/index不可新领；同claim下一index经有效离线对账后才能领；新claim不能退前槽 | 去掉request unique/unknown门槛、超limit、退槽 |
| 身份/历史 | 来源精确大小写/空格不归一；旧UUID换来源拒绝；同源不同UUID解析旧根并拒绝直接预留；仅retired历史不建根，旧UUID不可领；legacy无baseline缺证不初建 | UUID自动rotation/只看digest/active为空跳历史/旧PK权威 |
| 版本 | source SHA/provider/model/policy变化拒绝；unknown优先于版本变化，不释放消耗 | 内容变动清unknown/换模型续期 |
| 期限 | actual clock锁后复核，now参数不能替代锁后时钟；等锁跨deadline0slot；claimed_at非法或deadline到点拒绝 | 只在入场看时间/续deadline |
| 用量 | reserved/unknown无slot退款；合法整数非bool/非负/total=input+output；缺usage保持unknown；有usage无离线收据仍unreconciled；只受控synthetic receipt可对账，不接受真实fee | {}当0、bool当int、非法total、price缺失当0、自动解除unknown |
| 部分失败 | counter与attempt建同事务；attempt INSERT故障回滚；usage写故障回滚；外层atomic拒绝授权 | 先计数后独立保存/未commit便授权 |
| 迟到/审计 | usage只改旧attempt，拒绝预算/attempt错配及原UUID/source快照漂移；报告幂等，冲突不能覆盖首份；不改原文章/run | 用run pk污染新claim/覆盖原报告/费用退款 |
| 并发 | 两worker独立PG backend；最后槽及record/reserve序列实际预算行锁等待；只有一slot胜者；首次unique冲突受控同root | 不加预算锁/锁不存在root/重复授权 |
| ORM/DDL | 已有schema6；额外identity save/update/bulk_update/get_or_create冲突不可覆写，普通counter更新拒绝 | identity可编辑、创建覆盖/删除账 |
| 删除兼容 | 带两账的原Model/delete_queryset/admin单删批删；原headline selection失效/推荐失效，账/unknown/期限/快照保留 | 新原对象FK/collector关系/删除账退款 |
| migration | 0080向前实库constraints与无原FK；另独立空测试库0080→0079→0080验证两表移除重建、旧表保留；不含生产数据 | migration leaf错/旧表修改/无逆向/将drop当生产可用回滚 |
| 回归/静态 | B03930+B03725+recovery22共77，旧headlines删除1；生产12指纹/旧modelAST/migration0079均保持 | ledger牵连既有claim/checkpoint/生产调用 |

运行设计：单批<=200；official django PG16固定SHA、network none、最多主+2worker三连接。迁移往返测试另列精确类，最后恢复0080，finally确保state恢复；未授权前不运行。性能界限：每次根行短事务，不跨网络；并发最多两worker、等待超时/线程及连接清理；JSON报告/receipt字节与嵌套上界固定，拒绝非builtin/非finite，不造金额字段。完整M02不在本组分母，缺费用证据不得称生产enforce。
