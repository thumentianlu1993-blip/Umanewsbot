# A046 私有单行已审赛绩 consumer：本地 GREEN 候选（未运行）

ROOT A046-CAREER-CONSUMER-GREEN-001 已确认固定 `043152cc6aeed2592833a2c836f5204fe1267bc2` 在原 runner003 一次真实 PG 得到两指定业务 FAIL、0 ERROR、0 SKIP：旧 writer eligibility 空值对3yo+，no-op 正式记录0对1。原 wrapper 的 cleanup大小写误判 exit2 原件保留；ROOT独立资源清理补证完成，没有重跑测试。本卡沿已审 A044/R01 合同实现，本地静态检查不等于 full GREEN 通过，PG窗口仍待 ROOT 核定。

独立 `codex/a046-career-consumer-green` worktree 从固定043152cc起步，原A045 checkout/测试字节与旧RED证据保留；原始主线基线仍是 main90f73d8093df00827a7ec78cc41dc3d3b91730c0。只改本线 command/service/test、原 writer条件字段及本线说明，不改models/migration/UI/task/生产入口、原legal-link、来源权限或其他线。

## 最终实现行为

冻结原 packet/source/review bytes 通过严格JSON/大小/SHA、profile/entity/version/H01/H02、唯一原行SHA和独立单行scope重建。原 guard 和完整 cache validator保留；不调用 basic-profile专用 review/bundle，也不另建审批。来源行的provider/region/namespace/operator/timezone/external horse identity精确校验，原finish证据和声明start/result都必须actual started、日期exact。保留原row dict做record.raw_payload，审阅绑定放candidate.raw_payload。独立review依然是调用方给出的冻结synthetic sidecar，不宣称生产审阅签名认证。

数据库仅PG；outer atomic里设置有界lock_timeout15秒，强制 User NO_KEY_UPDATE→profile UPDATE→candidate/record。读取锁内current actor active/staff/username，同一锁持至commit/rollback，保持User FK KEY SHARE兼容。profile须private、强身份不冲突、Hong Kong且race_record手工锁未开；获每个等待锁后及提交前用实际UTC重新核TTL/未来审批。权限/门禁/锁超时返回blocked，持久层/保存/日志系统异常向上传播并整体rollback，没有自动重试/取源。

首次 baseline匹配后先用原 resolver拒绝既存非本角色记录，再调用真实upsert且只接受created；DB refresh核raw/source/managed facts/idempotency/canonical/归一化issues为空，profile只允许原derived字段变化，官方数/authority/private/basic等值保护。实际records/started/unlinked各+1，linked不变。原APPLIED candidate/confidence0/actor、完整独立review binding、原行SHA/H02/source/版本/record_after/前后计数/receipt与operationlog同事务；再DB核candidate/log/record/profile实际值，写后TTL或审计失败整体rollback。

消费凭据按profile/module/新role/H02 key/row scope查询，多条或绑定改变拒绝。原完整输入重放重新做current权限/TTL/私有/身份门禁，读取record与receipt并比较全事实；不调用upsert/normalize/refresh completeness、不写audit或时间戳。若已有合法后续event补连，要求原link role的同PK/row/H02/event receipt并核canonical key，仅容许原link允许字段变化；不撤销event关联，不把receipt当原link实时权限检查的替代。

ignore零写不消费；dry-run实际writer/审计/readback路径后回滚，不返回临时持久PK。序列化验证在atomic内，stdout在commit后；BrokenPipe传播但保留实际已提交事实。命令仍从安全FD读0700/0600输入，用真实git HEAD核code声明；ROOT窗口需正确只读Git metadata与git可用，不能mock执行SHA或把Git前置ERROR算业务结果。

原 `horse_race_records._race_record_values` 只加两行：payload包含eligibility_text才写值；缺key保持原值，不默认空串。原models已有字段，不增schema。

## 唯一确定性测试 fixture 修订

原043测试的撤权方法两种子例，第二个新profile仍声明第一匹马hkjc:hk-001，原 `_identity_reason` 会正确拒绝跨profile强身份冲突。仅修第二个synthetic profile/source/selected row为HK-002，并让request H01 horse_key来自实际source external_horse_id；原身份guard不放宽，也不删除第一子例的成功record/audit。原strong URL一起绑定HorseId=HK-002，没有名字匹配或伪造权限。

10方法名与全部assert调用AST保持；两个指定RED方法完整AST不变。仅request和撤权方法的fixture语句改动。原043测试字节另封存为原件，fixture patch独立封存；这是执行前静态识别的确定性fixture冲突，尚无PG通过证据。

## 拟议 ROOT 窗口

10个新方法完整执行，原career-link 5方法回归（事实保护/重放/身份权限期限/写后rollback/PG锁），P0现有未关联记录补连/异常start/unknown start、未关联快照展示四方法，合计19个精确AST入口。原pure grade/eligibility代码未改，实际OP/L/NEWCOMER和eligibility写入/缺key保留已在新方法覆盖；不把未执行旧suite算本实现通过。

沿ROOT已适配runner和固定环境；源码/testmanifest/control/env均按候选SHA重新封存。必须把 A045_TEST_CODE_SHA绑定本次候选，不能被旧runner清除。PG业务两连接+只读观察control连接至少3，lock_timeout15秒；真实TTL方法停止历史clock后实际跨6秒并封存blocking PID/UTC，线程和屏障均有界。建议CPU2/4GiB/全窗口600秒，其中570秒执行+30秒清理，无外网；资源实际许可由ROOT决定。

本线未启动PG/Docker/网络/生产任务，无full GREEN、merge、部署或发布结论。ROOT核定窗口后实际失败须封存并修复，不因准备或静态检查提前报通过。
