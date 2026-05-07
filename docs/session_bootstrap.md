# 新 Session 启动模板

## 使用方式

未来每次新开工时，Codex 必须先阅读以下文件：

1. [AGENTS.md](E:/Codex/AGENTS.md)
2. [docs/current_state.md](E:/Codex/docs/current_state.md)
3. [docs/decisions.md](E:/Codex/docs/decisions.md)
4. [docs/deploy_runbook.md](E:/Codex/docs/deploy_runbook.md)

如任务涉及部署、回滚、运维，再继续阅读：

5. [docs/deploy_production.md](E:/Codex/docs/deploy_production.md)
6. [docs/alicloud_hongkong_step_by_step.md](E:/Codex/docs/alicloud_hongkong_step_by_step.md)
7. [docs/rollback_guide.md](E:/Codex/docs/rollback_guide.md)
8. [docs/backup_recovery.md](E:/Codex/docs/backup_recovery.md)

## 启动要求

开始干活前，Codex 必须先用自己的话总结：

- 当前项目是什么
- 当前阶段是什么
- 当前线上真实状态是什么
- 当前任务目标是什么
- 当前已知阻塞点是什么

在完成这一步之前，不要直接进入实现或部署动作。

## 推荐启动提示词

可直接复用下面这段作为未来新 session 的开场提示：

```text
请先阅读 AGENTS.md、docs/current_state.md、docs/decisions.md、docs/deploy_runbook.md。
阅读后请先用你自己的话总结：
1. 这个项目当前的产品定位
2. 当前线上真实状态
3. 当前阶段目标
4. 本次任务的阻塞点或注意事项

在没有完成这段总结之前，不要直接开始修改代码、部署或给结论。
```

