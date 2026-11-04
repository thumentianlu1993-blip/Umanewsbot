# 设计

生命周期 registry v1 保留生成后 35 天规则；显式 --runtime-valid-until 生成 v2，要求 aware 且晚于 generated_at。两版仍要求 24 小时 apply 窗口，过期或未来生成时间拒绝；promotion、predecessor、membership 与 activation 规则不变。

TRA v1/v2 保留 31 天证据新鲜度；v3 采用用户明确许可，新增 permission_valid_until 和 authorization_reference，要求 user_confirmed_automation_permission。registry 不得超出许可期限；verified_at 保留真实确认时间，不能写未来时间绕过校验。所有版本保留相同 source/host/route/region/预算校验。

实际 TRA 文件更新 SHA 后须重渲 standing policy，并在交付时检查已有登记的 route digest 影响；只读 dry-run 确定目标，不以 policy 可加载替代同步闭环。无模型或迁移变化。

worker 诊断只读采样 CPU、任务、队列、数据库活动。单个负载快照不作为根因。采样产物存专用 runtime，仓库仅存脱敏摘要。

生产唯一成员 956 已完赛，因此新增只读 prepare_race_event_lifecycle_renewal 命令。v2 successor 必须继承当前 active predecessor 的完整成员集合、selector scope、generation 链和身份字段；允许已完赛等正常生命周期进展，但拒绝撤销、人工暂停、退出 enforce、schedule/enrollment/region/timezone/US allowlist 漂移。activation 对这种原范围续期使用精确 predecessor 成员合同，避免用面向新增赛事的 census 排除已完赛成员。原 promotion/activation 的排他锁、false/off、CAS 和证据写入保留。
