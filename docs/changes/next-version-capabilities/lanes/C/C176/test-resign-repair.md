# C176：L03 导航测试重新签发令牌 P2 修复

状态：TEST_SOURCE_REPAIR_ONLY / ALL_RUNTIME_NOT_RUN，待原R_C同上下文复审。精确parent为C175 `139c846368332a83edc8b0157e3725c0bbbc680d`，正常PR main base仍为 `1dd5e0a508957672bcddd1c33e454fbbef1b75c1`。不amend旧提交，旧报告/封存保留。

原R_C报告SHA256 `64555d360f1f5b6968ad24dc607904e2f96cdd07d760b40daf71d6da01c5f78b` 的F1指出：最终新闻列表再次渲染的文章href是新签名，不必与起点令牌字节相同。

固定源码链已只读确认：`public_news_feed`在4149行将返回令牌恢复成有效GET，4190–4194行以当前page调用`_public_attach_nav`；3112–3115行调用`_public_nav_token`，3065–3070行重新`signing.dumps`。本测试仅冻结timezone.now，没有冻结TimestampSigner的墙钟，跨签名秒边界属于合法路径。不能通过改产品时间合同来稳定这个测试。

唯一测试修改：`_assert_round_trip`最终重新提取的目标文章href，改为断言查询字段仅return_nav、恰1值，且 `_public_read_nav(newtoken, {'news'}) == ('news', {'page':'2'})`。既有最终目标文章路径、唯一目标锚点、feed对象PK及page_obj.number=2全部保留。赛事入口href和赛事返回href仍必须携带原实际列表token，两个主方法的真正业务RED断言未改。过期负例的独立签名时钟控制完全不变；8唯一测试方法、原fixture、catalog/控制/生产文件均与C175保持。

仅源码AST(feature_version3.12)/compile-source、原新函数文本/JSON元数据及Git diff核验；没有import/planner/collection/tests/Django/DB/Redis/Docker/服务/网络/CI或宿主/demo替跑。新增本报告，不改C175报告。runtime保存原测试副本、原R报告、固定链行摘录、准确head/tree/diff、保护快照及新ci-packet/receipt/index/seal。

CI包沿用C175唯一Draft PR/标准pull_request路径，更新候选head/tree；仍需ROOT在原R_C源码复审后明确派push/PR/CI，核policy active、真实test-merge/run/attempt及8方法完整收集。当前未push或建PR，无有效RED，不写GREEN、不合并部署；旧C172及他线修改保持原状。
