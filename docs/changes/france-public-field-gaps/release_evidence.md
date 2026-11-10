# 法国字段补缺发布证据

北京时间 **2026-11-11 01:15:38**，用户批准的精确发布包已完成合并、生产发布和本轮线上验收。后续正式卡、赛后自然节点仍待实际发生，不计作本轮通过。

## 固定身份

- [PR #296](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/296)，源提交 `286148aa03ef4f125ce0bc71543bf4976fbbb996`；合并 `ce1aa916536e3eaf2865231e610f20657d70ed42`，与 CI 受测合并树一致。
- 生产窄候选 `d9d97ab6c772e560e90822b896a218420f443387`；应用 OCI `sha256:400d8e716cd10cfbf99c3852626e88d86b9809aaab637befaff7d32bb63c41fb`。宿主固定 checkout 仍为 `0d05fa9b`，应用源码由镜像提供。
- 发布包 SHA256 `058b9afc66086c349622f5ebc124839e683735a1df8345ad1ff56a6eb41582eb`。
- 数据 manifest SHA256 `288924e2d28c4d263fde2c466a26bff3a6f94b58651cdab79454c8136c91c3f4`；法国 2026 年 9—12 月固定 80 场。实现通用于后续法国赛事。
- 生产 root `/opt/umanews-release-0d05fa9b-france-handoff-20261110/umanewsbot`；stage `/opt/umanews-external-staging/france-fields-d9d97ab6`；收据 `runtime/france-fields-d9d97ab6/release-complete.json`。

## 已完成动作与证据层级

1. 实现与独立复审完成；最终 [范围 CI 42849955113](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/42849955113) 649 项通过、零跳过。候选目录外的受信验证器重新取得本次测试镜像、收集清单并核对结果、代码树及主线保护，收据为 verified。并非全量 CI。
2. 固定窄候选另有 62 项 PostgreSQL 测试、80 个实际 view 的隔离回放、apply/replay/restore/replay，及精确 schema、六表真实备份恢复隔离演练。
3. 生产停止 beat、等待两个 worker 的 active/reserved/active_confirm 全零，再停止 worker。六表一致性 custom-format 备份为 17,386,196 字节，SHA256 `cbe17434bb4198e508dd52fd67f9d68afb0f86cbe44f5a8a5f9dd93cb6e489a8`；TOC 六表核对通过，原全库备份保留。本次不是全库灾备验收。
4. 生产迁移仅 0079→`0082_france_basic_fields`，新增奖金金额/币种并将条件扩为 text；未部署 0080/0081/0083。source/target catalog、数据库身份检查通过。
5. 固定数据包 dry-run 全部通过并回滚，随后原子 apply 80 场；生产收据恰好一条。逐字段值与 manifest 的 expected_values 一致，511 行赛果摘要与 80 场状态不变。47 场历史时间补缺；12 个历史已有时间和空中锦标原时间共 13 个非空时刻全部保留，其中 4 个历史值与源计划钟点差异不覆盖。
6. Web、通用 worker、race_sync_v2_worker、beat 已重建；四应用的镜像、环境、Django 实际 release 一致。配置只增加七个 France basic 字段准入并更新 release；QQ false，其它开关不变。Nginx 校验/reload、双 worker pong 通过；Web healthy，四应用零重启、无 OOM。France 浏览器镜像、环境及原会话容器保持。
7. 公网 80/80 详情 HTTP 200，距离、奖金、赛种、条件及有来源的方向/场况/材质展示通过；59 个冠军计时通过。10 场 80 行旧卡逐行核对练马师、公斤负重、十进制赔率、Genybet 平台及采集时刻通过。历史日历样例的距离/条件、空中锦标日历的距离/条件/23:25 北京时间通过；主域及 www health 均 200。
8. 启动后日志无 ERROR/CRITICAL/Traceback；实际 worker 统计已记录调度选择、生命周期推进和 SLO 监测各 4 次，以及覆盖监测执行。此证据证明调度恢复，不替代后续真实正式卡/赛后验收。收尾空闲 5,092,360,192 字节，满足 4GiB 加 512MiB 余量。两类发布锁均已释放。

## 保留的来源缺口

距离/赛种/奖金/完整条件各 80 场，方向 65、场况 59、材质 62 场已有证据并入库。18 场材质和 15 场方向无明确来源时继续未知；天气、热门排名及尚未公布条目不推测。历史原值、来源、审计及恢复快照保留。

## 运行与恢复入口

完整 Compose 链见 [运维记录](../../deploy_runbook.md) 最新条目；必须在原六份文件之后追加本包 `release-identity.json`。普通全量 migrate、旧镜像回退和全库覆盖不属于本次恢复方式。字段恢复沿同一 manifest，只在当前值及相关证据仍等于本批 after-image 时先 dry-run 再原子 restore；保留新增列及 text 扩容。人工门禁统一引用根 AGENTS.md。

本机证据目录：`/Users/mentianlu/.codex/runtime/france-public-field-gaps-20261110/`。`production-evidence/release-complete.json` 绑定每项生产证据 SHA；`delivery-296.json`、`merge-proof.json`、`public-live-verification.json`、`public-card-verification.json`、`calendar-live-verification.json` 分别保存交付核验、合并树与公网验收。
