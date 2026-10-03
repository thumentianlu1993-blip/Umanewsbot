# C-005 / Q01 原R两项P2返修

2026-10-03，Asia/Shanghai。原审核 `d19e4996db1932a37171f9f2df465349d2a26a8a` / R-C005-CODE-001，输入 `a940f95aa5c78c89aa9611028999071c48f3c9cf`。本次仅纯技术返修，既有G1覆盖；不执行G2/G3动作，未改生产或共享映射。

## 修复与范围

- C005-P2-01：`DeliveryClaim` 为冻结对象，保存本人 attempt/time。claim UPDATE 和读取凭证置于同一事务，UPDATE行锁保持到凭证读取后提交。refresh不改凭证；发现已易主时只读退出。typed停用异常的CAS仅匹配本人不可变凭证，退还本人一次attempt；其他worker、SENT及fresh SENDING保留。
- 真正两连接/屏障用例：A真实领取后暂停，B独立连接把lease时间改为过期，再真实领取fresh attempt；A恢复后许可关闭，要求B的status/attempt/time/payload不变且零URL探测/发送。只有合成fixture改时间，无生产数据。
- C005-P2-02：仅 `WindowQQAtomicityTests.test_quota_rejection_leaves_no_orphan_exposure` 显式 `QQ_CHANNEL_ENABLED=True`，保留原quota原因与无orphan exposure/delivery断言，不改业务迎合测试。
- 修改仅qq_auto_push、tests_legacy、test_race_news_exposure及本线报告。无迁移/Q02/真实外发，root负责共享rules精确映射与formal/full。

## RED → GREEN

初始测试快照bc30在claim屏障超时（fixture原默认high_value_only），不计竞态RED。修正fixture目标all_public后固定RED `07ae0ee6bad2c57f88d272402b7fe2dee0bd31a2`：2项均为行为FAIL、0error/skip。旧worker实际返回SKIPPED而非B的SENDING；原配额测试原因qq_channel_disabled而非group_hour_quota_exhausted。

固定实现GREEN `f606ef7d1c83854ef484cc3ed3fc82a87e107799`：Linux隔离PG16.15/Python3.12.3/Django5.2.1，76项全部PASS，0failure/error/skip，含原74项、claim易主及配额原子性。两连接3项均实际运行，保留本人typed停用退还attempt、fresh/SENT保护、启用态与邮件回归。宿主另53项PASS，不用SQLite冒充PG竞争。

| 收据目录 | executed | failure | error | skip | lifecycle | exit | 秒 | receipt SHA256 |
|---|---:|---:|---:|---:|---|---:|---:|---|
| revision-red2 | 2 | 2 | 0 | 0 | complete | 1 | 7.140706651000073 | b2d797a8ddedfea9ada7dcfc067fd062d8bc890734cac5b9c1167ce32fb12e96 |
| revision-green | 76 | 0 | 0 | 0 | complete | 0 | 7.958794830000443 | 6601313227b89bd0abf3e65f29b7efd6c160fb87a90ba16398e0e747822cb252 |

产物根 `/Users/mentianlu/.codex/runtime/q01/`；目录含 execution-plan.json、batch-000.json/log。计划固定Git SHA/tree/digest并标diagnostic_only。沿用已核实本地Docker context、Git archive只读/nonroot/network-none，镜像 `sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905`；仅lo，外部Python/curl及nestedDocker均blocked。每批<=200，单批顺序执行，没有自动full。

## 当前边界

待原R限定findings复审，未自标APPROVED。formal/full及真实交付/生产验收仍由协调者完成，短PG不是formal策略收据。F04固定907运行包留在树外；36个fixture已准备但UI计时完成0，8894服务已停止，中断不算成功。
