# A-006 / H01 纯planner与有界容量读取实现（待独立代码审核）

实现已形成本线四路径：horse_target_inventory.py/test_horse_target_inventory.py、scripts/h01_readonly_count.py与scripts/tests/test_h01_readonly_count.py。另回写冻结决定、测试设计、接口边界和映射提案；未改F01、模型/迁移、writer或其他线。JG1 unresolved保留，完整历史/complete snapshot不可冻结；源权限与真实数量unknown。原R仅批准方案非未决部分，当前代码还未审，不宣称H01整体完成/main交付。

六轮真实RED/GREEN证据位于私有runtime `/Users/mentianlu/.codex/runtime/a006-h01-evidence/`：planner骨架正常导入，4行为NotImplementedError失败→4通过；扩展窗口/版本/缺口/优先/strict schema失败→9通过；身份撤销/参赛冲突/赛季证据/delta失败→13通过；未知日期候选/新闻SQLexclusive失败→25合并通过；未完成模块优先与错误revision回显失败→27通过；custom对象copy风险失败→28通过。reader正常导入骨架的只读/rollback/schema与wall-time行为RED→GREEN也单列。日志保留真实失败与green，不把import/env错误或生产数量当RED。

28个本地开发测试通过。workflow contract PASS、diff检查通过；这些尚不是正式test-impact主线收据。固定Linux纯Python专项结果另回写证据（不启动PG或full）。SQL仅connection fake，生产schema/索引/实际事务与语法未在本轮真实PG执行。新增path/domain/test/python profile proposal交root，未改共享映射；正式PR影响计划由root集成后生成。

功能：固定初始近期实际出赛、历史全一级名单及pending JG1；强身份去重/未解与冲突保留；可信版本引用优先/legacy无有效版本补充，date/start/名单缺证partial；未来/赛季/新闻与模块优先；缓存/staging/profile/public分层及不可变输入SHA/delta。容量工具默认无连接，执行入口绑定脚本摘要、固定SQL/字段/窗口、RR READ ONLY及预算，异常/截断立即停止rollback，错误不回显敏感输入；输出都是容量聚合，不声称真正档案公开。

仍待原R：固定代码与producer边界、SQL/预算控制审核，必要真实短PG语法/事务验证排队；JG1用户答复、root/F06生产只读与输入完整冻结。未运行生产查询、网络/付费、旧采集恢复或写入/发布。F03后续源/样本/35文件缺口原样保留。

固定Linux开发专项验证：代码提交 `3780b662b19327ea2c40419f900053d6213ad0a7`，tree `ffa87d3807de54a94d1b9175b78290f795effab1`，既有镜像 `sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905`。以只读git archive挂载、network none、非root既有镜像、1 CPU/1 GiB、read-only rootfs执行上述两个unittest模块，28例PASS、exit 0，未启动PG。证据目录 `/Users/mentianlu/.codex/runtime/a006-h01-linux-3780b662`；`result.json`记录命令/绑定/时间/退出码，日志SHA256 `f2a9ae0f23e9f3b0c2a2f6d8da27018fde3ca41840df299de30a2e1cf5f3f690`。这是手工开发诊断，尚非正式test-impact计划或主线收据；SQL fake与实际PG边界不变。
