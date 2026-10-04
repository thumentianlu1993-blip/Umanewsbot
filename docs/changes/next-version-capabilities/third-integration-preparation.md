# 第三批本地集成准备

日期：2026-10-04，Asia/Shanghai。此候选从已固定第二批 `06b01aea9041eacb3deae9f46968eb06fd459cb6` 派生；独立分支 `codex/next-version-third-integration-20261004`。PR #236 的提交和交付材料保持原样；本候选仍处准备阶段，没有新 PR、合并、发布或生产动作。人工确认统一引用根 AGENTS.md。

## 已纳入的时效纯核心

A013 固定修订 `2a7ccbfe159a1878e3d9ee03258110757bdc259b`，原 R `f8b1f33fc3132dce3baac6ab57eacfcd7c4ee0a5` 关闭迟到违约归窗及跨窗严重错误阻断两项 finding，并批准纯核心修订。两个新增 Python 文件及 A 的交付文档按 Git blob 原字节导入，未引入 A 线其他提交。

共享映射新增 `race_timeliness_contracts` 领域、测试条目和 `python` profile；新服务/测试选中本核心和 F01，F01 服务/样例变化通过反向依赖选中时效核心。既有领域、测试、profile、skip 许可及执行策略全部保留。两个映射用例先复现未登记路径/漏下游，再登记后通过。

本地最小验证：映射用例所在模块 26 PASS；实际组合后的纯核心 44 项与 F01 17 项共 61 PASS，均零 skip/failure/error。记录位于 `/Users/mentianlu/.codex/runtime/third-integration-evidence/` 的 `a013-mapping-RED.log`、`a013-mapping-GREEN.log`、`a013-integrated-pure-GREEN.log` 及 `a013-integration-precommit-receipt.json`。纯 Python 不加载 Django，不接数据库/网络。

## 尚待组合与交付证据

C013 公开探针纯核心 `baa6345e87203e35fde6cb2c7e913fae28826ecd` 已由原 R `c924ec6d84b6b99f3f461e274328d60cd2c968a5` APPROVED，独立49项通过；两个新增Python文件及C交付文档按原Git字节纳入。新增 `public_probe_contracts` 领域、测试条目、python profile，以及F01到公开探针的反向依赖；两个映射反例先RED再GREEN。实际组合纯测试93 PASS（A44+C32+F01 17），映射模块28 PASS，均零skip/failure/error。原字节清单及真实日志见同runtime的 `c013-integration-precommit-receipt.json`、`c013-mapping-RED.log`、`combined-mapping-GREEN.log`、`combined-pure-GREEN.log`。

B012 的受控 fake 监管器仍在开发，未纳入本候选。下一步审核实际组合映射与控制文件，再按现有策略运行最终固定候选的一套 Linux CI；映射变更仍要求 full，不以本地28/93项代替正式交付，不重复运行原候选full。

R01 数据库账本/写入 hook/真实 scope 与 F03，O03 公开版本/执行 origin/独立宿主/真实请求预算，F02 现场权限与凭据传递/故障验收仍待对应证据。这里没有迁移、真实采集、自动化启用或外发，不代表 R01/O03/F02 整卡完成。
