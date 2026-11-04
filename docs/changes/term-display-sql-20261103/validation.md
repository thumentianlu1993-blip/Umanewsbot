# 验证记录

2026-11-04：实现提交835d4f644c5a5e8489433f2b6b33614af6fb842f。旧实现真实RED，本地22项通过；固定源码、non-root、network-none、只读root/source/control、1 CPU/2 GiB/128 PID的PostgreSQL隔离容器中111项通过，失败/错误/skip均0，exit0、无OOM，容器已清理。证据见pg-receipt.json，完整runtime在/private/tmp/umanews-term-sql-20261103。

## 性能实测

合成58211主名/39926别名，1/20/200输入，包含命中与未命中；旧新结果集合摘要一致。1轮预热+3轮交错测量，EXPLAIN ANALYZE BUFFERS，关闭并行扫描。完整数值见benchmark.json。

|名称数|主名旧→新中位ms|别名旧→新中位ms|
|---|---|---|
|20|27.006→2.449|97.115→8.481|
|200|264.959→2.645|268.273→9.961|

单名称基本持平；大批收益来自去除长OR重复比较及无用排序，别名200名称shared hit blocks从33717降至1012。结果仅证明该合成分布下SQL成本降低，不能等同生产耗时、整页提速或整体CPU下降。

初次启动器依赖.git导致未执行；第二轮111测试通过但SHOW lc_ctype不受支持，性能阶段中断。第三轮改用pg_database.datctype后完整成功。这些是验证脚本问题，无应用代码变更。

## 完整CI和审查

最终提交的独立review、CI与目录外交付收据在PR交付记录补齐，未取得前不称完成。用户明确授权本次继续豁免既有10项环境测试；仅这10个精确ID的原profile/reason，review_by到2026-11-04。不新增skip，不自动续期；专项111项没有豁免。
