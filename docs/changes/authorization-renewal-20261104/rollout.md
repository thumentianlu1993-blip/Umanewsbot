# 精确发布包（尚未执行）

候选 `ab5775f62619ec196aed7bd7f87f65236b53dfa8` 从当前生产 `cf8f5cf3451fb55f39969b80596b0088fc7fbe33` 构建；只增加本次续期代码、配置和测试。主线 PR 不作为生产整树发布目标。门禁统一见根 AGENTS.md。

## 绑定

- lifecycle 原 root：`28c327c0897f3c1559dfa99fc9fed76532dc1b1bee6f2ed994db4e680e5bb1a9`。
- 续期 artifact SHA：`d9aa21ab6007e0508f64cd96ca5eb3808f5aa11443e623dbbe01c2c5569d75cf`；generation=3，成员恰为 `[956]`。
- membership SHA：`f500e2fac984d03df92cc7fa83762425fb2b6bf70a4e540a168bae0ac2ce4a90`。
- artifact 生成时间：`2026-11-04T13:03:10.754797+00:00`；apply 必须早于 `2026-11-05T13:03:10.754797+00:00`。
- 两项授权截止：`2028-01-01T00:00:00+08:00`，即覆盖北京时间 2027/12/31 全天。
- TRA registry SHA：`53962c4220c35523ea77ca27e674970bfb555e48e7b6bf86b0472e05cfed1735`。
- standing policy SHA：`4d00fdef5b515b5777f1a5d306c86911ffa2afe15a6ba1eafebcd25180ea04ab`；14 条路线只轮换 digest，地区、接口、预算及原有效期不变。

## 发布动作

1. 核对生产仍为绑定版本、schema0079、原 registry/member/activation；核对 release lock、服务、队列、active/reserved 任务、资源和持久化路径。异常则不停止服务。
2. 独立发布目录固定候选；备份私有配置和当前 registry 证据；通过受保护 `deploy/deploy_0079.sh deploy` 完成新备份/摘要/TOC、排空、同 schema 镜像发布。无迁移。更新 `.env` 中 TRA 和 standing policy 两枚 SHA；核对四服务实际加载的文件副本与 SHA。
3. 重建 `web / worker / beat / race_sync_v2_worker`；db、redis、nginx、OneBot 不变。随后通过 `deploy/promote_lifecycle_enforce_registry.sh` 以同一 artifact 执行 successor promotion：备份、停 Beat/排空普通 worker、暂置 lifecycle false/off、创建 generation3 root 和 1 条 membership、换绑 956 control 的授权证据。
4. 通过 `deploy/switch_lifecycle_mode.sh` 恢复原 true/enforce 模式，绑定新 root/membership/count，并由脚本生成 activation ID、原子激活新 root、退休旧 root、清除旧 claim，再恢复原服务。期间 web/worker/beat 会按受保护切换流程再次重建；scope 不扩大，不启用其他自动化。
5. 数据写入限上述授权记录、操作日志及既有脚本的 claim 轮换。956 的状态、赛时、赛果不改。TRA 不做批量历史登记修复；只读核验现存 44 个 enrolled 均已完赛且日期最晚为 2026-10-25。自然调度保持原范围和频率，不人工触发网络 proof、抓取、QQ 或邮件。
6. 验证新期限、SHA、active root/member/activation/identity 一致；在只读事务确认956仍finished；公网health、首页、赛历/详情；至少10分钟观察新错误、队列、服务重启和既有调度。自然任务完成与单纯合同加载分别报告；没有实际符合条件的同步任务时，不声称真实请求恢复验收。

## 恢复

首次 stop 前技术检查失败，保留旧服务。同 schema 发布中断，按原 intent/候选/备份走 `deploy_0079.sh resume`；不重新造意图、不直接切旧镜像。授权 promotion/activation 失败时沿受保护脚本保留 false/off 与恢复证据，排查后在同一 manifest 有效期内继续；web 服务保持可验证。完成发布后发现缺陷，先按受保护 switch 关闭 lifecycle，再准备前向修复；不直接改回旧 registry 数据或使用已过期证据冒充续期成功。数据库整库恢复不在本包中。

## 已知独立边界

本次只移除用户指定的35/31天期限阻断。standing policy 自身 `2027-08-28` 的到期、JRA 等其他来源许可、单赛事身份和公开证据仍独立校验；不把TRA来源许可续期等同于所有赛事/来源到2027年底均可自动运行。
