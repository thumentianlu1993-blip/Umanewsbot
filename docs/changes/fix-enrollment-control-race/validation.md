# 纳管 control 并发创建冲突修复

## 问题与最小修改

生产候选 `69955960` 的既有全量结果、组合候选 `9ebdf657` 的
[Linux/PG16 CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34349427487)
均复现原回归 `test_two_concurrent_applies_create_one_complete_control_set`：
第二个并发请求报 `stable_raceeventlifecyclecontrol_event_id_key` 唯一键冲突。

`preflight_enrollment(lock=True)` 先读取并锁住已有 control，再锁 event。
如果两次请求最初都未读到 control，第二次等待 event 锁后仍沿用空快照，便会重复创建。
现有规范要求 lifecycle control → event，直接反转会破坏其他写路径的锁顺序。

本修复在 event 加锁后，对原快照缺少 control 的 ID 做一次无行锁存在性检查。
发现并发新增就抛原有受控 `EnrollmentError`，外层事务整批回退；重新预检仍走原有 replay/CAS。
不在 event 之后补锁 control，不吞掉任意数据库异常，不增加自动重试或全局锁。
原 lifecycle false/off、资格、manifest、预测状态、来源证据和整批事务检查均保留。
本问题属于受控旧纳管入口，不能据此认定当前两场 M2 自然赛事链路故障。

## 回归及验证边界

- 保留原 PostgreSQL 并发测试，新增一项真实连接交错回归：主事务持有 event 锁，
  等待者完成空 control 查询，主事务通过正式 apply 创建并提交。等待者须受控拒绝，
  同一 manifest 重试返回 replay，全部 control 字段保持不变。线程/数据库等待均有界。
- 本机执行纳管命令模块与 PG 模块共 45 项：8 通过、6 failures、27 errors、4 skipped。
  错误和失败发生于 Windows 不支持的 O_DIRECTORY/O_NOFOLLOW、原子目录操作及符号链接路径；
  4 项跳过为 2 项临时目录别名条件与 2 项 PostgreSQL 并发测试。未弱化文件安全检查，
  本机结果不能证明并发修复通过。真实 PG GREEN 须由本候选 CI 核验。
- Django system check 通过。基线文档合同的五处旧引用和一条契约错误由独立 PR #186
  修复，本分支不改变检查器。验证记录不代表合并或发布许可。

原始失败、命令输出及后续固定版本证据保存在本机 `runtime/fix-enrollment-control-race/`
和 `runtime/closeout-m2-test-ops/next-enrollment-concurrency-diagnosis.json`。
本次没有迁移、配置、功能开关、生产数据或服务操作；M2 赛时显示 #194 仍优先交付。
