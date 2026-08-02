# Celery race-live P0 部分部署报告

## 结论

状态为：**部分部署停在安全检查点，修复待复审/重新授权**。

初始实现已经进入生产并完成 `prepare`，但 `start-beat` 在真正启动 Beat 前 fail closed。
Beat 仍为 exited，五轮生产后验没有开始，不能写成发布成功。本地 stdout final fix 尚未
review、提交、合并或部署。

## 版本与范围

- 初始实现 commit：`611c6aab`；
- PR：`#46`；
- 合并版本：`main@7cd144ab`；
- 生产仓库：`/opt/umanewsbot`，从 `4221affa` fast-forward 到 `7cd144ab`；
- 生产既有 dirty：仅 `12` 个 deploy 脚本 mode-only 差异，发布过程中原样保留；
- 当前本地修复分支：`codex/fix-p0-queue-snapshot-output`；
- 本 change 无模型、migration 或业务数据变更，没有清理、迁移或消费历史队列。

## 生产只读预检

- Docker Compose：`5.1.2`；
- `RACE_LIVE_SCHEDULER_ENABLED=false`；
- `RACE_LIVE_MONITOR_ENABLED=false`；
- `RACE_LIVE_RUNNER_MODE=disabled`；
- `race_live_worker=Created`；
- 首次 active/reserved/scheduled：`0/0/0`；
- `celery=0`；
- `race_live`：首次 `6055`，prepare 前 `6574`；
- 上述 `race_live` 消息均为 `monitor_race_live_sla_task`。

队列增长发生在初始关闭态生产者修复进入生产前。该积压没有被删除、迁移、消费或重放。

## 资源门禁与额外授权维护

首次资源门禁为：

- `MemAvailable=867284 KiB`；
- `SwapFree=0 KiB`；
- 结论：NO-GO。

经用户针对该资源维护动作另行授权：

- 创建并启用 `/swapfile-umanews-p0-20260730`；
- 大小 `2 GiB`；
- mode `0600`；
- 未写入 `/etc/fstab`；
- 普通 worker 在确认空闲后优雅重启；
- 为释放资源临时停止 OneBot，操作完成后已恢复为 running。

该 swapfile 是临时生产资源，不是仓库配置。后续停用和删除必须单独授权：避开构建、重启和
任务负载，先确认内存足以承受 `swapoff`；只有
`swapoff /swapfile-umanews-p0-20260730` 成功并确认 `swapon` 已无该条目后，才可删除文件。
未写 fstab 只表示重启后不会自动启用，不表示文件自动删除。

## `prepare` 结果

`prepare` 成功到达 `CANDIDATE_READY`：

- drain 期间 active 从 `2` 自然降至 `0`，没有 revoke；
- rollback tag：
  `umanewsbot:rollback-race-live-p0-20260730T030255Z`；
- rollback old image：`sha256:7d730634...8774`；
- 初始候选 image：`sha256:17562c52...acea7`；
- 两次 migration plan：`0 / 0`；
- 候选 settings：scheduler=false、monitor=false、runner=disabled；
- web/worker/nginx 正常；
- 内外 healthz：`200 / 200`；
- Beat：exited；
- `race_live_worker`：`Created`。

这证明关闭态候选已经完成 prepare，不证明 `start-beat` 或五轮后验成功。

## `start-beat` 失败与安全状态

`start-beat` 在执行 `up beat` 前读取 machine queue snapshot。Django shell 在 stdout
前置输出：

```text
105 objects imported automatically (use -v 2 for details).
```

严格 parser 没有把该输出猜测为成功，而是 fail closed。结果：

- 没有执行 `up beat`；
- Beat 仍为 exited；
- 五轮后验未开始；
- OneBot 已恢复 running；
- `race_live` 后验为 `6574`；
- 没有清队列、启动 race-live worker、启用 flag、执行 migration 或业务写入。

## 本地 stdout final fix

已取得真实 RED，并做最小 GREEN：

- machine snapshot 从 `manage.py shell -c` 改为
  `manage.py shell --no-imports -c`；
- parser 不放宽；
- banner、多余行或畸形输出仍必须在 `up beat` 前 fail closed。

本地验证：

- 部署合同：`33/33 / 56.236s / exit 0`；
- 四组聚焦：`64/64 / 57.693s / exit 0`；
- Django check：exit `0`；
- `makemigrations --check --dry-run`：`No changes detected`；
- `sh -n deploy/deploy_race_live_p0_closed.sh`：exit `0`；
- `git diff --check`：exit `0`。

这些证据不等于代码 review 通过，也不构成新的发布授权。

## 下一步门禁

1. 复用本 change 的同一代码 reviewer session，只限定复审 stdout final fix 和直接触及路径；
2. findings 清零并冻结精确 fingerprint；
3. 针对该已审版本重新取得发布授权；
4. 提交、推送并合并 final fix；
5. 生产只读复核 HEAD、flags、Beat/worker/OneBot、队列、资源和 rollback tag；
6. 拉取已审 final fix，重新运行 `prepare`，构建并记录精确最终 image；
7. 新 prepare 成功后才运行 `start-beat`；
8. 五轮状态、镜像、health、queue/task 计数和 Beat 日志后验全部通过后，才能写发布成功。

禁止直接修改生产脚本、复用
`sha256:17562c52...acea7` 冒充最终 image，或手工启动 Beat。

## 应用回滚

若在 final fix 发布前决定恢复旧应用：

1. 保持并确认 Beat stopped；
2. 保持三个 race-live flag 关闭，`race_live_worker` 不启动；
3. 使用 `umanewsbot:rollback-race-live-p0-20260730T030255Z`
   恢复 web/普通 worker；
4. 验证普通 worker 只消费 `celery`，内外 healthz 为 `200`；
5. 不清理 `race_live=6574`，不回滚数据库。

临时 swapfile 的停用/删除是独立资源维护动作，不与应用回滚捆绑，仍需单独授权和验证。

## 最终发布收口

上述“部分部署”记录按当时事实原样保留。本节追加最终发布证据，不回写或覆盖前述安全检查点。

- 同一 reviewer 对 stdout final fix 的限定复审结果为 `APPROVED`，inner session
  `019fb110-7ef5-7270-8bfc-28b1c93ab5bb`；冻结 fingerprint
  `4c785e742630e1d628d13ce419fce3f61995cac4e58e4f9144709b7e4ea8a000` 与 content
  manifest `a17ac407620a3c56b6e740c7c1671dbab5b4c82bf441fb9e74523958acd3f416`。
- 用户针对该版本明确授权后，暂存转换返回 `INDEX_TRANSITION_OK`；final fix commit
  `24a49c2a` 经 PR `#47` 合并为 `main@be1c89bf`，生产仓库随后 fast-forward 到该版本。
- 生产重新执行完整 `prepare`：普通 worker 在
  `active=0 / reserved=0` 后才停止；historical runner preflight 为 `migration_safe`，
  Django check 通过，两次 migration plan 为 `0/0`，关闭态 settings/schedule 通过。
  rollback tag
  `umanewsbot:rollback-race-live-p0-20260730T043615Z` 指向上一候选
  `sha256:17562c52...acea7`；最终候选为
  `sha256:c319750374c9ec197b4f6e230ad70b8fc5a8a144daef5a2ad5c4657916ecb5f5`。
  脚本返回 `CANDIDATE_READY`，此时 Beat 与 `race_live_worker` 均保持停止。
- `start-beat` 基线为
  `celery=0 / race_live=6574 / selector=0 / monitor=6574`。五轮 `celery` 依次为
  `36/35/30/28/30`；`race_live=6574 / selector=0 / monitor=6574` 每轮不变。
  每轮 Beat/web/worker running 且 image 一致，普通 worker 只监听 `celery` 并可 ping，
  `race_live_worker` 未运行，healthz 正常，Beat 日志不含两个关闭态目标。
- 脚本外终验：生产 HEAD=`be1c89bf`，web/worker/beat 均使用
  `sha256:c3197503...b5f5`；Beat running，`race_live_worker=Created`；
  `.env` 与容器 settings 均为 `false/false/disabled`，两个目标 schedule entry 不存在；
  队列为 `celery=23 / race_live=6574 / selector=0 / monitor=6574`，最近十分钟目标 Beat
  日志计数 `0`。容器内、本机 Nginx、`umafans.run` 与 `www.umafans.run` 的 HTTP
  healthz 均为 `200`；OneBot running，最近 15 分钟无 OOM。
- 临时 `/swapfile-umanews-p0-20260730` 仍启用，总量/空闲量均为
  `2097148 KiB`，未写 fstab；终验 `MemAvailable=1576148 KiB`，只略高于
  `1536 MiB` 硬门。停用/删除 swap 仍须单独授权，不能在当前负载下顺带执行。
- 生产进入窗口前已有的 `12` 个 deploy 脚本 mode-only 差异原样保留；全程没有清理、
  迁移、消费或重放历史 `race_live=6574` 积压。

当前回滚优先使用
`umanewsbot:rollback-race-live-p0-20260730T043615Z` 恢复到上一候选；该候选不含 stdout
final fix，恢复后 Beat 必须保持停止。若需继续退回更早版本，才使用
`umanewsbot:rollback-race-live-p0-20260730T030255Z`。任一回滚都不得改写历史队列或顺带
移除临时 swap。
