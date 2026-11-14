# 磁盘容量修复与自然采集验收：2026-11-14

## 结果

用户明确“执行”后，同一批准包已完成：原有采集最低磁盘余量从 4 GiB 降为 **3 GiB**；六份旧发布整库备份先离机归档，校验后删除服务器副本，共回收 **5,529,329,563 字节（5.15 GiB）**。最终复核可用空间约 **8.75 GiB**。当前四应用仍为候选 `24de56e2cb321b102390409a6a57fb528b5dc333` / 镜像 `sha256:4fc0201d32d0751f092c848e0fbbb766a43544662acf75439ff2efb99e1f62d1`，无迁移、schema0084 不变、QQ 关闭。

14:34:51 北京时间配置重试通过，Web 健康、双 worker 就绪、Beat 恢复，发布锁释放。14:38:54 的自然观察确认 13 条来源检查点发生真实采集尝试，其中 11 条成功更新时间；24 个新快照完成，无新增 `artifact_min_free_disk`。另有 2 个 `snapshot_fetch_failed` 和 1 个仍在采集的快照；它们与本次磁盘修复分开记录，未宣称所有来源均成功。

## 清理范围和恢复面

- 清单仅为 `ab5775f6-authorization-20261104`、`df2f376a-oci-20261105`、`661a0859-census-20261105` 三个旧发布目录中的六份 11 月 4 日 `.dump`，每目录两份。
- 六份是不同备份时点，不是字节级重复副本。离机目录 `disk-capacity-20261114/archived-dumps/` 保留原绝对路径结构，文件 0600；每份字节数、SHA256、`pg_restore --list` 校验通过后才删除服务器原件。未把 TOC 校验称为完整数据库恢复演练。
- 14:21:50 清理完成，实际空余升至 8.75 GiB。原发布目录、索引、收据和代码保留；当前备份、数据库卷、媒体、持久化来源证据、Nginx 仍引用的旧目录及其他项目均未清理；没有执行 Docker prune。
- 若需恢复文件，按清单从离机副本恢复原路径、SHA 和属主权限，先核对空间，不能覆盖不同内容的现存文件。此次没有导入或回滚数据库。

## 配置、验证和执行记录

新增唯一 Compose override：`/opt/umanews-external-staging/disk-capacity-20261114/capacity-override.json`，在此前实际完整 Compose 链末尾追加。四应用 `RACE_DATA_RAW_MIN_FREE_DISK_BYTES=3221225472`，其余环境、镜像、来源范围、请求预算、功能开关及队列不变。后续发布应从当前容器标签继承完整链，保留这一容量覆盖。

- 原固定候选容量函数的边界检查通过：不足 3 GiB 时仍拒绝，达到余量要求时允许。完整 Compose 渲染确认只有四应用这一个环境值发生变化。
- 发布持 OS flock 与兼容部署锁，记录 owner、PID、资源域和心跳。暂停 Beat 后等待在途任务自然完成，未强杀任务、清队列或批量重试来源。Docker 客户端超时不被杀死，协调器持锁等待原操作结束。
- 首次配置执行的验证脚本误把地区 URL 正常 301 当失败，Web 恢复 4 GiB 后同检查再次误拒；工作进程与 Beat 一度仍停。14:27:43 已按原批准回滚步骤完成原四应用及调度恢复。清理结果和离机备份保留。
- 纯技术修正仅允许 HTTPS 双域、相同路径及原 `year`/`region`，允许移除规范化的 `month`；补充正反用例并经原独立 reviewer 复审。重试复用六文件已完成清理收据，无重复删除，原批准计划与清单 SHA 不变。
- 重试后 14 项服务器侧 HTTP 检查通过（双域健康、赛事入口、各五地区页面）；本机另外两项健康检查通过。双 worker 的 ping、注册任务和队列就绪；四应用实际环境阈值均为 3 GiB，数据库 schema 不变。
- 自然观察使用只读 Beat 调度快照、任务结果收据及发布后来源检查点/快照。不能只凭 selector 空转成功作为采集证明；本次有真实尝试、成功检查点和已完成快照。没有手动派发第三方采集任务或重置失败状态。

## 绑定与证据

- 原批准计划 SHA256：`22ea144946f9c3531094709300c5edba55c4ee4d82f8bd6fee57be1fadb10c36`。
- 六文件清单 SHA256：`aa8e1448cd3bb5c3bc502a6bddc908984a3bba3ab7019d859ca55a9e70051104`。
- 配置 override SHA256：`1a6bcf93c42aaea5fa52735a5612ea718774406ad39bd5665ffdf6804e783426`。
- 本机证据目录：`/Users/mentianlu/.codex/runtime/disk-capacity-20261114/`。`archive-proof.json`、`production-deleted.json`、`production-retry-result.json`、`production-retry-http.json`、`natural-scheduler-receipts.json`、`natural-observation.json`、`completion.json` 保留归档、清理、配置及自然观察各自证据。
- 生产证据位于当前 France 宿主发布目录下 `runtime/disk-capacity-20261114/`：原失败收据、`restore-scheduling/` 恢复收据、`retry-1/` 成功配置收据分别保留；根目录 `completion.json` 和 `natural-observation.json` 记录最终验证。
- 原发布执行文件绑定与后置只读观察文件绑定分别保留。当前完成状态以最终 `completion.json` 为准，不把首次失败收据或配置完成后的 pending 状态当作最终结论。

原[线上复验](online_acceptance.md)中的 NAR 解析、来源策略/身份及历史字段缺口仍保持独立边界。本次仅解除磁盘容量阻断，未宣称所有地区的全部异常已修复。人工确认统一引用仓库根 [AGENTS.md](../../../AGENTS.md)。
