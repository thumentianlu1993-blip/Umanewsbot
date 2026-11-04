# 精确发布包

本包尚未执行；人工确认统一引用根AGENTS.md。主线PR仅交付本优化和验证资料。生产使用窄候选`cf8f5cf3451fb55f39969b80596b0088fc7fbe33`，tree `b556cff12f42702b3a34ab5c878c4e24e8928bff`；它在当前生产`9def4a7be906a5e91d47ab5dd7ba888496f62b00`上只增加解析器及专项测试，不部署整个main。机器绑定见release-manifest.json。

## 范围

无迁移、无索引、无配置或功能开关变化、无生产数据动作、无新增外部调用。现有发布合同需要重建应用镜像并更新web、worker、beat、race_sync_v2_worker；后台先排空，保留队列、QQ关闭状态及OneBot停止状态。服务间共用同一镜像，不能把本次描述为只重启web。

## 执行顺序

1. 取得生产release lock，核对当前commit/image/config、四服务、schema0079、迁移空计划、队列与active/reserved任务、冲突任务/锁。2026-11-04只读核验四服务均running、restart0且身份与manifest一致；执行前重新核对，漂移即停止。
2. 连续三次资源采样，间隔20秒：1分钟load≤2、MemAvailable≥2GiB、SwapFree≥1GiB，磁盘足够新备份和构建。失败不停止服务。
3. 固定候选在独立发布目录复制现有私有配置；保留旧镜像身份与配置。通过`COMPOSE_FILE=docker-compose.prod.lowcost.yml ./deploy/deploy_0079.sh deploy`执行受保护发布：精确schema检查、新备份/摘要/TOC、排空、同schema发布、静态资源、按原运行意图恢复服务。不得跳过guard或手工覆盖恢复标记。TOC通过不冒充完整恢复验证。
4. 核对四服务镜像revision/健康/restart、worker broker ready与Beat、schema未变化。公网health、首页、赛历、至少一赛事详情及马匹页正常；抽查中文名与冲突原名显示。观察至少10分钟无新增错误及QQ发送；记录有界同页面耗时样本与负载，流量不同不能宣称严格线上A/B。

## 回滚与失败恢复

首次stop前失败保留运行服务并停止本包。部分发布失败沿本次原intent路径/SHA、固定候选镜像执行`deploy/deploy_0079.sh resume`，不重新生成意图或备份。已完成发布后发现问题，使用审查过的前向修复；现有策略禁止普通旧镜像rollback，不直接retag或启动旧容器。数据库恢复不属于本包自动动作；如需恢复，另绑定精确备份与数据影响。所有路径保持QQ关闭。

## 验证和交付

主线完整CI、独立review、目录外收据以及窄候选专项测试须齐备后才提交G2选择。发布前用户可选只合并或合并并执行本精确包；当前仅准备材料。
