# A-006 / H01 实施前冻结决定

协调者已采纳：初始2023-10-03..2026-10-03窗口含边界不漂移；有证据/版本才赋当前赛季优先；排序当日/未来30天→已证赛季→新闻90天→最近真实出赛→未完成模块/key；重叠一个执行target保留全部reason；有效指针/明确supersedes，不max revision，legacy无有效版本才补充，冲突留账；容量初测120秒/SQL5秒/lock250ms/24SELECT/500聚合行/2MiB，超时partial/rollback，不做streaming。

原R6a07acd5批准971a08a2非未决部分及上述边界。JG1历史归属仍unresolved，候选单列，不并入/排除最终冻结分母，并阻断完整历史/complete snapshot；近期actual-start各赛种保留。未解决schema、索引、输入全集、身份、许可仍partial。当前进入纯planner与有界读取工具实现，不执行生产查询，不恢复旧采集；F01业务代码不回改。
