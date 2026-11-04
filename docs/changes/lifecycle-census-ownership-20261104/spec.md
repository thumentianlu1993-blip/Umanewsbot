# 生命周期运行态 census 的应用归属边界

2026-11-04 用户批准原 PR275 精确发布包。应用候选 ab5775f6 已经上线，TRA v3 合同已在四服务核验；生命周期 promotion 在数据库写入前失败：旧 checker 把同机 wechat-summary 的 worker 当作 Umanews 额外 worker。保护流程将 lifecycle 设为 false/off、停止 Beat/普通 worker并保留恢复锁，网页及 race_sync_v2_worker 仍运行；没有 generation3 registry。

原设计明确阻断所有项目的同名服务。用户随后明确批准新的 G1 范围：保留全宿主扫描，只排除经应用标记及资源隔离证明无关的常驻容器。不得停止或修改其他应用来绕过校验。共享主线和生产交付统一遵循根 AGENTS.md。

目标：Umanews 的旧 checkout、跨项目副本、one-off、重复实例、镜像/开关/身份漂移继续失败；独立项目的同名服务不再误阻断。证据未知仍 fail closed。校验器只读 Docker 元数据，不连接业务数据库，不打印环境值，不自动修复容器。
