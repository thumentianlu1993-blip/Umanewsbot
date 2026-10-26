# B028 首样本第一次执行与恢复记录

2026-10-06 00:14，Asia/Shanghai。结论：**PR238 已合并；003 首样本执行失败，样本仍为 0；本次自有暂存、进程与共享锁已清理。** 业务镜像、服务、配置、业务数据与功能开关未改变。

## 授权与固定输入

用户于 2026-10-05 23:50:58 在一次 A/B 选择及通俗解释后选择 B，按[完整交付材料](B028-first-sample-delivery-003.md)执行。范围仅固定 PR238 合并及固定首样本包，不扩大其他待决项。人工确认依据根 [AGENTS.md](../../../AGENTS.md)。

PR238 正常远端合并为 `ec0a12506cf2131eb6f6d774d9941f764f15c845`，parents 为 `22e130adf4464fd3c5dd63ccd3f508c4a853d464`、`78c65869166d3f56b0f8fc8469e8415dd78be121`；tree `605e94c51c557edff19e0c348c80f881fb0ad411` 与正式受验树一致。必需检查成功、strict 与 enforce_admins 生效，没有管理员绕过。合并收据 SHA `2f03558f78c3864ab6bddf0b11b42217b3d3c7d8de5ee2e089008114377d2088`。

首样本 operation 为 `b028-first001`，完整 manifest `d93094c293d5742ad20ac9da426223947116b99f00c5ac9e0c0e350628055b9b`，源码 `ff5344b4cd02606f3353a375b2bcaa1501f3db1a`，原 R 整包复审 `d3f80196`。执行前后 73 项封存输入 bytes/SHA 不变。

## 已实际执行

- 复核现场固定 CID、image、release、host/container Python、UID/GID、boot、时间 namespace、暂存路径、既有 helper SHA、默认锁与已知发布入口进程。ROOT 为该操作唯一生产协调者。
- 23:59:58 取得既有共享锁；owner PID `4069291`、start ticks `311943951`，记录来源、操作、摘要与真实心跳。
- 在批准的新专用目录暂存固定工具与输入。Mac 新空 H 继承 gid 0，ROOT 暂存检查阻断；确认只创建该空目录且 inode 未变后，完成批准的 gid 20 初始设置，继续尚未执行的本机暂存步骤。该 ROOT 暂存错误保留，不改写为首次全通过，不重复生产复制或采集。
- host/container/Mac 同工具 verify 通过，host 7 模块和 container 纯导入通过。现场 CPython 3.10.12 原 Runner 3 项计划和实际 ID 一致，3 PASS、0 failure/error/skip；真实 timer 触发、handler 恢复、outer 未延长均为 true。它们是前置资格证据，不是采样完成。
- 00:04:10 单次启动 driver PID `4072341`、start ticks `311969181`。metadata 入口拒绝，host 结果为 `capture_unknown / operation_failed`，未生成 metadata-ready；content、R 选样和 R 内容交付均未发生。

## 失败原因和证据边界

固定 binding 文件为紧凑 JSON：832 字节、SHA `2cf201f30e3f3cc17cd1a0d8faf99ed687d891dfe4eadc1fc3e1d502625f4adb`。StageRunner 使用既有 `export.encoded(binding)` 重编码：865 字节、SHA `bc2c999c34d8de32f0359a2f088d874b6b59e10656bd059f5d459c264f813c75`，随后把后者传给容器入口；metadata.pending 与该值一致。

容器入口在原始文件 SHA 检查处拒绝，位置先于 binding 解析、container_capture、parent journal、run_stage 及采样 DB connector；capture-status 也复用该错误摘要。现场 driver-control、probe-control、output 目录为空，限定操作的进程扫描为空。原 R 独立只读复算并确认该边界，报告 `fe61f308`；上一轮漏查编码一致性已明确保留。

因此此次操作未进入采样 DB 阶段，没有业务查询、内容读取、PG 取消或业务数据写入。此结论来自固定源码可达性、实际输入摘要及现场空控制目录/进程证据；**没有另做全生产 PG 会话探测，也不把 `capture_unknown` 改报为成功 `stage_closed`。**

## 清理与共享锁恢复

owner 最终 `driver_reaped=true`、`identity_unknown=false`，IO/handler 收尾完成。由于 ROOT 未在 cleanup 120 秒内完成真实目录清理确认，owner 按设计保留锁并退出；`root_cleanup_confirmed=false`、`PG_closed_proven=false` 与 `lock_released=false` 原样保留。

ROOT 后续核精确 owner/driver PID 已不存在、已知 session 成员为 0；保存现场原件和全树 inode、UID/GID、mode、bytes/SHA 后，逐项只清理本次自有目录：container 22 项、host 53 项、Mac 16 项。host 新增 `/private/tmp`、`/private` 确认为本次创建、同 inode 且为空后逐级 rmdir；既有祖先保持不变。

依原批准包的 manual stale-lock 恢复面，重新核同一操作的 owner/thread/source/config/manifest、7 个自有锁文件指纹、owner/driver/成员为 0，以及已知发布入口活进程为 0；仅逐个 unlink 这 7 个自有文件并 rmdir 本次锁。此为**有现场证据的自有遗留锁恢复**，不是正常 token release，不按 age 自动解锁，不删除未知或其他 owner 的锁。

独立末次核验：容器专用 BASE 不存在，host H 与本次新父目录不存在，共享锁不存在；原 CID/image 不变且 healthy。46 个有界 client 全部回收；唯一非零 client 是上述 Mac 空目录组权限检查。无服务重建/重启、镜像替换、迁移、配置/开关改动、新真实抓取、付费调用或对外消息。

## 产物与后续

实际证据保存在 `/Users/mentianlu/.codex/runtime/b028-root-approved-first001/`。总收据 `receipt.json` SHA `e00c5150134899e7798df0534f58f5dcf01fbf8d9ed5d29882ab63bd32e36e49`，`evidence-index.json` 索引 128 个当时文件；46 份步骤回执及输出 bytes/SHA 已逐项复核。原 003 完整包与失败历史不修改。

B 负责原卡最小本地 RED/GREEN 修复，原 R 保持独立复审。新候选和新 manifest 未完成审核，未获生产重试授权。当前 fresh=0；这次失败不缩 28 天范围、不重置原观察窗口、不代表 F02/F03 或整版验收完成。
