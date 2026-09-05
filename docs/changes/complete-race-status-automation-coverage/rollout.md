# 补齐赛事状态自动更新完整链路：上线与回退方案

## 1. 当前起点

方案制定时的生产只读证据：

- release：PR #137，revision `1312c8de131bba6e5a6a3ee1b52a6a2d2fc14a03`；
- image：`sha256:85b94626e302036598cf67194d4c3bf7cb8f9f2ddda2e8de288df42fce4af253`；
- migration leaf：0077；
- Web、普通 worker、Beat、`race_sync_v2_worker` 均 running，restart=0、OOM=false；
- 10 个赛事开关均 true；
- `celery=0 / race_sync_v2=0 / race_live=7543`；
- event 956 已 finished、10 条 confirmed result、1 条 publication；
- 755/756/757 有 official revision，但仍 scheduled、0 result、0 publication、0 transition；
- lifecycle active registry 只有 event 956；
- future census 为 128 blocked，其中 route ambiguous 127、manual lock 1；
- 内存和 Swap 充足；磁盘约 8.18 GiB，只比 8 GiB 硬门槛高约 189 MiB。

以上是方案基线，不得作为以后发布时的当前证明。真正上线前必须全部重新读取。

## 2. 发布前必须通过

### 2.1 代码与身份

- PR 已通过测试和独立 review；
- commit、tree、source archive、image ID 和 OCI revision 一致；
- policy v2 文件 SHA、canonical digest、provider registry SHA 全部冻结；
- `makemigrations --check --dry-run` 无漂移；如出现 migration，停止并重新审核。

### 2.2 生产状态

- shared deployment lock absent；
- exact revision/image、四服务 restart/OOM、migration leaf 可读；
- active/reserved/scheduled task 和三队列可读；
- 旧 `race_live` 数量精确记录且不得变化；
- external import、历史 runner 和其他 release owner 不在冲突窗口。

### 2.3 磁盘和备份

当前磁盘余量不足以安全容纳新镜像和新备份。执行发布前必须计算：

```text
最低发布前可用空间
= 新 custom-format 备份预计大小
+ 新镜像解压后预计增量
+ 发布临时文件预计增量
+ 1 GiB 操作缓冲
+ 8 GiB 发布后硬保底
```

任何一项 unknown 或最终不足都停止。不得删除当前唯一可恢复备份、运行证据或正在使用的 image 来凑门槛。

备份必须为 PostgreSQL custom format、0600、非空、有 SHA，并通过 `pg_restore --list`。

## 3. 关闭态部署

获得用户批准的精确发布包后：

1. 取得自己的随机 token deployment lock；
2. 停 Beat，等待 ordinary `celery` 和 `race_sync_v2` 自然排空；
3. 将 10 个 `RACE_DATA_SYNC_*` 开关全部设为 false；
4. 停止专用 worker；
5. 使用 exact image 重建 Web、普通 worker、Beat；
6. 执行 Django check、migration leaf、policy/registry 文件和关闭态审计；
7. 验证 root/www/healthz、普通新闻任务、队列和资源；
8. `race_live` 必须保持精确原值。

关闭态任何检查失败都保持关闭，不继续启用。

## 4. 分阶段启用

### 阶段 A：只读 policy v2 和 census

- 所有写开关继续关闭；
- 运行只读审计；
- 要求未来 30 天清单与最近 7 天恢复清单分别守恒；
- `standing_policy_route_ambiguous=0`；
- far-future 合理进入 `awaiting_source_window`；
- manual lock 保持阻断；
- 无 provider 请求和业务写入。

### 阶段 B：future discovery 和 enrollment

- 开启总开关、scheduler、future discovery 和受限 network；
- 先保持 schedule/racecard/lifecycle/result/public/correction apply 关闭；
- 验证今天/明天赛事的 identity create/adopt/replay；
- 单轮请求数、容量账本和 outcome 守恒；
- 已有 v1 enrollment 只通过合法 successor manifest 轮换；
- 755/756/757 只能由最近 7 天未闭环清单选中进入审计修复流程，不能靠扩大未来窗口或扫描全部历史赛事。

### 阶段 C：时间和出马表

- 开启 schedule/racecard apply；
- 核对 race_datetime、时区、runner、退赛和 immutable revision；
- 缺行、身份多解或人工锁保持零 canonical 写入；
- 公网页不泄露内部字段。

### 阶段 D：lifecycle

- 开启 lifecycle apply；
- reconciliation 每批最多 20 场；
- 验证 data-sync admission 和 legacy registry 不冲突；
- 等待自然 T/T+30，或验证一场较晚纳管的精确 direct-finish；
- 不手工修改状态。

### 阶段 E：正式赛果和公开

- 开启 result apply，再开启 result public；
- 755/756/757 通过一次性审计修复包完成状态/赛果/公开（证据复核、SHA 候选、dry-run、备份、批准、apply、verifier）；
- 核对 terminal marker、roster、revision、result、publication、transition 和 root/www；
- task SUCCESS 或 HTTP 200 均不能单独算通过。

### 阶段 F：更正

- 开启 correction apply；
- 至少观察一轮自然无变化检查，证明 checkpoint 推进且无重复写入；
- 不在生产造一条假更正；
- 真实更正首次出现时继续按同一验收表记录。

## 5. 每阶段共同门禁

- lock owner 唯一；
- 四服务 exact revision/image，restart=0、OOM=false；
- migration leaf 精确；
- MemAvailable、SwapFree、磁盘均通过；
- `celery` 和 `race_sync_v2` 的短暂消息都能解释并自然排空；
- `race_live` 精确不变；
- claim/token 正常释放或有明确下一次 due；
- 无跨 event、manual lock 覆盖、部分赛果公开和双 authority；
- root/www 同时验收；
- 新闻、QQ 和 External staging side effect=0。

## 6. 自动止损

任一下列情况立即停止：

- policy/route/registry/contract 漂移；
- 一个地区没有任何可竞争纳管的可信来源（`trusted_route_missing`）；
- discovery 分类不守恒；
- lifecycle writer、result writer 与 public reader 的 admission 结论不同；
- 错误或部分赛果公开；
- 同一赛事出现双 lifecycle authority；
- claim 过期后仍写入；
- worker OOM/restart、队列失控、磁盘或内存门禁失败；
- `race_live` 数量变化；
- shared lock 出现其他 owner。

止损顺序：correction -> result public/apply -> lifecycle -> racecard/schedule -> network -> future discovery/scheduler -> 专用 worker。必要时执行既有 10 false fail-closed 恢复，不 purge 任何 Redis 队列。

## 7. 回滚

- 行为错误优先关开关，不删除 observation/revision/transition；
- policy v2 错误时恢复 v1 只能与旧 image、旧 SHA 和关闭态一起执行，不能混搭；
- 已经合法发布的赛果只通过新 correction/reverse manifest 修复，不静默覆盖；
- 代码回滚前停 Beat、自然 drain、停专用 worker、10 false，然后恢复精确旧 image；
- additive schema 默认保留；本方案预计无 migration；
- 只有数据库损坏才使用 custom-format 恢复，该动作不属于普通回滚。

## 8. 发布完成定义

只有以下全部满足才称为“赛事状态自动更新完整链路已上线”：

- 新赛事能从等待来源开放自然进入 identity/enrollment；
- route ambiguity 不再由多来源竞争造成（先到先得授予）；
- 时间和出马表有真实自然更新；
- 至少一场新赛事自然经过 lifecycle；
- 755/756/757 通过一次性审计修复包完成正式赛果公开并验收；
- correction 无变化轮询幂等，变化分支已通过隔离 PostgreSQL；
- 审计分类和请求结果完全守恒；
- kill switch 实测有效；
- root/www、服务、资源、队列和 `race_live` 全部通过；
- 最终事实已写回仓库文档。
