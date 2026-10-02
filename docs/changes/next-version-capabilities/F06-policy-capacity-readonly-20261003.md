# F06 来源政策与资源时点证据

观测：2026-10-03 03:46:16，Asia/Shanghai。协调者通过既有 SSH 仅查询 web 容器指定环境键、三个既有政策文件和宿主资源；未导入 Django、查询数据库、调用第三方、修改配置或恢复采集。

## 当前证据

固定 web ID 为 `9f03d1faa0ccf681d50dd2a9db6018af55a33937bf94517b0d447f453ac2190c`，镜像 `sha256:73ee1dcf7edb5b7c7bda49f5d6baedffe030d639fcc5bf191b831ece6e9f5930`，revision `ad50abdb74b89669ab8ada2958b040877c1a1849`。以下三个文件实际摘要均等于容器环境钉扎值：

| 对象 | 实际摘要 | 时点结论 |
|---|---|---|
| TRA registry | `0e1cdff89052b7b5f482b4761f1e39e3f38eefdf30405ae6a5d45b64e737b322` | 法/港/爱/日/英/美六地区映射；路由为 racecards_free、result_by_id、results_today_free；条款证据时间 2026-09-26 17:15 UTC，硬期限 2026-12-31 23:59:59 UTC |
| Standing policy | `e73a4e3b556cf1670caed6ca0cae46e5c01dbe711c74712a8fbe9c3fc527d679` | 14 条路线，包含旧 other 桶爱尔兰兼容项；有效至 2027-08-28 00:00 UTC。路线数不代表独立来源数或可用地区数 |
| JRA 多来源政策 | `738403e397016e2c4fcf04a4d44b9353a4f1bfd54c1f535ea80090bb32ef035d` | `/run/race-data-sync/multisource/20260927-jra-all-venues-policy.json`；schema 3，provider=jra、identity_namespace=jra-race-v1，仅 result 能力；有效至 2026-10-26 18:00 UTC，即北京时间 10/27 02:00 |

多来源 discovery/apply 与 coverage alerts 三个环境键均为 true；这只证明容器配置，不能代替逐事件准入、实际执行与公开结果。此次摘要未导出完整 route/proof，也未运行准入函数，不能据此确认每个场地 proof 当前都有效。

TRA registry 的 `max_requests=3` 是 proof 请求上限，`race_live_source_proof.py` 对该值执行 1–3 校验；不是套餐 QPS、日额度或剩余用量。`HISTORICAL_RACE_BACKFILL_REQUEST_BUDGET=250` 是本系统配置，不等于平台许可或累计预算。真实账号套餐、收费端点权限、速率与余额仍未知。

当时宿主 `/opt` 可用磁盘 27.59 GiB、MemAvailable 4,754,140 KiB、SwapFree 1,310,716 KiB；这是一帧资源读数，不是持续容量或部署空闲证明。未核 DB 租约、worker active/reserved、intent 或自定义锁。

## 时序风险与安排

JRA 现政策将在 10/28 全量观察开始前到期。另据固定主线 `907f8de6` 的 `race_live_source_proof.py:222`，TRA 证据超过 31 天即 stale；当前证据对应北京时间 10/27 01:15 后触发该门槛，不能只看 12/31 硬期限。运行镜像的这一函数未在本次逐字节比对，续期实施包仍需核对实际代码与全部派生摘要。

协调者将两者的 proof/条款/范围核验及续期包准备安排在 **10/19 18:00 前**，在 O05 的 10/20 12:00 观察前完成获准动作和校验，目标覆盖 10/30 20:00 交接。不得只改日期；须核真实许可、proof、新摘要及存量登记换绑影响，按根 AGENTS.md 组织精确发布包。这里仅登记工作顺序，未续期或获得生产变更授权。

F06 的 10/06 容量结论仍需要：F02 真实分母/样本、F03 地区缺口、H01 冻结数量、账号真实权限/速率及费用上限。已向用户请求每日及本版总预算和币种；未答前金额保持 unknown，不视为无限预算，不影响离线实现和审核。Codex 套餐剩余额度与产品 API 预算分开管理。

机器快照留在协调者私有 runtime：`/Users/mentianlu/.codex/runtime/f06-policy-readonly-20261003.json`，只含白名单字段；没有凭据或正文。
