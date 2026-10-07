# B059 checkpoint gate 夹具 ERROR 修复准备

固定 baseline `f1ba1a00e063f482f50776ec1ad74012655e0948`。ROOT在原R `2082ae412e5af23e64e9918dc7db81e0ad90e095` 批准的 host 包 `b3f133a096acdfff1493bbc502552674b983813ada9d1c9077ecd133690c2d99` 上完成一次 fresh exact7 窗口。原report SHA `b2269bafd3fec9b807ac54bcc257e06e028c2f599f2e2554c9fad847191af329`；batch log SHA `c0199d857466fbe1431cd11d472edbd9f9ce04234d956a272b4cfec5ac21e806`；cleanup SHA `1e127b6e819309fa8341d9229a99abf3d44aa7b01547cba6e5d505628457ab31`。实际七方法/76观察子场景：6方法PASS，E08 ERROR，0FAIL/5ERROR/0SKIP；71观察子场景PASS，5ERROR。worker报告105.864秒，unittest报告62.750秒，完整host收尾138.008秒，勿混用计时口径。ROOT复验资源FREE；本轮只读原cleanup记录，不重复访问资源。

五错误均 `phase=checkpoint_committed` 的 `claim_uuid/schema_bool/revision_float/unknown_namespace/null_plan`。完整原report/log指向主线程 `mutate_fence`→`TranslationRun.update(raw_response)`→夹具patched update→`transaction.on_commit`同步回调→`release.wait(8)`超时。原夹具只按raw.progress.state匹配；五次控制字段写入保留了checkpoint_saved状态，因此误注册了第二个主线程gate。worker已在真正提交后的回调暂停；主线程必须完成fence和snapshot后才release，误拦主线程导致自己无法release。这是夹具ERROR，不能当业务RED。

本修只改测试helper、E08必要精确断言及本记录。helper在gate创建时记录controller thread和目标run ID；E08显式worker_only=True，真实QuerySet.update仍先执行原ORM，再只对其他线程、实际atomic、changed=1、TranslationRun、目标run的真实checkpoint结果与checkpoint_saved progress注册原on_commit。回调记录实际writer thread。主线程fence仍写真实DB，所有五fence原样保留，不被skip、吞错或绕过。E08在fence写入后增断言hits==1、writer_thread!=observer_thread；既有实际checkpoint已提交/计数/read/SDK/快照/不应用断言全部保留，唯一call适配是明确worker_only。

同步E10默认worker_only=False，只观察创建gate的线程，exit_after=True仍在真实事务提交后原样抛CommittedFixtureExit，免费checkpoint恢复原断言不变。8秒等待、12秒/thread join、600/570/30、max3PG/2worker不放宽；不改业务services/tasks/schema/codec、官方controls、原三、其他六方法及旧25回归文件，不增加/缩减35测试分母。不以metadata校准代替真实PG执行。

独立 `codex/b059-checkpoint-fixture-error` worktree 从精确f1ba1a00创建；原worktree及旧准备/actual/错误report/log/cleanup完整保留，其他线程改动不回退。新runtime只封存固定源码、精确diff、全源archive/seal、原始输入指纹及新纯AST谓词校准；未业务/测试import/collect、PG/Docker/sharedFD/socket/network、旧suite/原图/旧metadata或续窗。历史6PASS仅本次baseline，不自动转为修订候选验收；修订七结果仍未知，full35/formal/full/M02及公开生产验收未完成。下一步同原R源码审核，再ROOT安排后续精确窗口。
