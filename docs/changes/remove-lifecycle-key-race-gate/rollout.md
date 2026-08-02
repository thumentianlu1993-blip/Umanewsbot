# 移除 lifecycle 重点赛事资格门禁发布方案

## R0：关闭态代码发布（独立授权）

- 从最新 main 构建包含 strict v2 enrollment 的一致镜像；
- web/worker/beat 保持 `false/off`；
- 不启动 race-live，不执行 lifecycle control 写入；
- 验证命令存在、migration plan 为零、服务和 HTTP healthz 正常。

完成后停止。不得沿用 R0 授权生成生产 artifact、创建 control 或打开 shadow。

## R1：16 场只读 prepare/dry-run（独立授权）

- 精确范围：event `84/85/86/430/431/432/433/434/435/436/437/740/940/941/942/943`；
- 全部重新核对 published、scheduled、地区、时区、datetime、manual lock 和 control absence；
- 美国赛事使用逐场真实 zone allowlist；
- 输出逐场 priority、featured、`is_key_race`、local/UTC datetime、next refresh、predicted
  decision 和 expected proposal；至少一场必须为 `is_key_race=false`；
- prepare strict v2 manifest 并 dry-run，证明数据库零写。

完成后停止，提交精确 manifest SHA、16 IDs、部署 revision、逐场审核表和建议观察窗口，等待
R2 新授权。

## R2：`false/off` control apply/verify（精确 manifest 独立授权）

- 核对共享部署锁、备份、web/worker/beat 严格 `false/off`、lifecycle active/reserved/claim=0；
- 只 apply 获准的 exact-SHA manifest，并在单事务内创建精确 16 个 shadow control；
- 验证 control 集合、generation、manifest SHA、next refresh；公开状态、赛果、新闻、QQ 和
  applied transition 均零变化。

完成后继续保持 `false/off` 并停止，等待 R3 新授权。

## R3：打开 shadow（精确范围独立授权）

- 显式设置 `RACE_EVENT_LIFECYCLE_ENABLED=true`、`RACE_EVENT_LIFECYCLE_MODE=shadow`；
- 只重建 web、普通 worker 和 beat，不启动 race-live；
- 首轮核对只产生 proposal/audit，16 场公开状态保持不变；
- 授权必须绑定 16 IDs、manifest SHA、部署 revision 和 24–48 小时决策窗口；
- 逐场记录实际跨过的 T/T+30 边界、expected/actual proposal、重复和错误；
- 未在窗口内到期的赛事仅验证未提前推进，标为“尚未生产观察”，不得宣称其时序已通过；
- 窗口结束只形成 enforce 的 GO/NO-GO 建议，不自动开启 enforce。

## 4. 失败处理

- 任一异常立即恢复 `false/off` 并重建必要服务；
- 已排队任务在事务内复查开关并零写退出；
- 保留 control、proposal、manifest 和日志，不删除审计、不反向改赛事状态；
- enforce 仍需在观察证据和独立授权后另行开启。
- 若回滚到旧校验代码，非重点 control 不会自动失效；全局必须保持 `false/off`，直到这些
  control 已按受审方案暂停或置 off。在此之前禁止重新开启 shadow/enforce。
