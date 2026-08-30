# 关键决策

## 2026-08-30 普通 worker 的 OOMKilled 标记即使未重启也必须 fail-closed

- `OOMKilled=true` 是冻结的容器完整性硬门禁；不能因容器仍 running、restart=0、主机
  `MemAvailable` 尚高于 1536 MiB 或公网仍为 200 而忽略。20:00 赛前检查命中该条件后，已立即关闭全部
  10 个赛事开关并移除专用 worker。
- 本次关闭不等于扩大赛事链容量或修改业务语义。普通新闻任务在此前窗口出现 DeepSeek 402、OSS 404 与
  持续 backlog，但这些只能作为后续归因线索，不能在缺少旧 cgroup/task 证据时直接宣告单一根因。
- 在关闭态根因修复和新热身通过前，不因真实赛果时点临近而恢复 result/public；下一次启用必须从 future
  discovery 全量重走。扩容仍是优化证据证明现有资源不可满足硬门槛之后的独立决策。

## 2026-08-30 Web 保持 1 worker × 4 threads，当前不扩容并暂停相邻 proof

- 生产 Web 从 2×2 调整为 1×4 后仍保留 4 个请求线程，关闭态 10 分钟热身最低内存约 1.83 GiB；完整
  激活后的 120 样本最低 `1767740 kB`，比 1536 MiB 硬门槛高约 190 MiB，公网、队列、restart/OOM
  同时通过。该配置作为 event 956 真实赛果窗口的当前基线，不恢复第二个 Gunicorn worker，也不扩 RAM。
- 后续 Beat 周期最低 `1663796 kB`，把已观测最小余量进一步收窄到约 89 MiB；在
  result/public/correction 实证完成前，UK/USA TRA proof 继续暂停，法国/爱尔兰
  `PROPOSED_NOT_APPROVED` proposals 不进入 canonical registry。若后续活跃窗口低于硬门槛，仍立即
  10 false、移除专用 worker并恢复普通服务，不能用扩容追溯改写失败窗口。
- 摘要语义必须分开：TRA source registry SHA 是 `3bac3b64…a6da`，standing policy SHA 是
  `07013655…1888`，reference registry SHA 是 `740a9377…cff2`，配置生成的 provider roster SHA 是
  `26e0625d…32d4`。审计的 `roster.registry_digest` 只能与最后一项比较，不能误与 TRA SHA 比较。

## 2026-08-30 普通 Celery 必须有任务后回收与 512 MiB host 保护

- 生产普通 worker 在 concurrency=1 下仍从约 129–292 MiB 增长到 1.344 GiB，并把 host
  `MemAvailable` 压到 751020 kB；重启后立即恢复到 2.05 GB，证明扩容不是首选，问题是长寿命 Celery
  子进程的任务后内存滞留/异常峰值。
- 在赛事写入重新开启前，普通 worker 启动合同增加 `prefetch-multiplier=1`、可配置
  `max-tasks-per-child` 与 `max-memory-per-child`，并在三份 Compose 给普通 worker 设置默认 512 MiB
  cgroup 上限。子进程超过软阈值在任务完成后回收；单任务失控则由 cgroup 阻止拖垮整机。
- 该保护必须先在隔离测试覆盖参数/Compose 合同，再以 10 false 发布，观察普通调度峰值、OOM/restart、
  redelivery/重复副作用与 1536 MiB host 门槛。只有新窗口稳定才从 future discovery 全量重走；当前不扩 RAM、
  不降低门槛、不用 swap/drop cache 制造通过读数。

## 2026-08-30 generation 2 只继承仍可执行成员，赛果与更正分开放行

- lifecycle successor registry 只包含创建时仍符合 selector 条件的赛事；已结束 predecessor 不为维持成员数而
  复制。本轮 generation 1 的 6 个已结束成员自然退出，generation 2 只纳管 event 956，属于预期 cohort
  收敛，不是成员丢失。
- result apply/public 可以在真实赛时前保持开启，以便 checkpoint 按 T+3 自然到期；禁止直接修改 due time、
  claim 或手工补写结果来提前验收。必须分别证明 provider 终态、数据库 apply/publication 和真实公网结果页，
  Celery `SUCCESS` 只证明任务终止状态。
- correction 是 result/public 通过后的独立门禁。只有 event 956 的真实赛果和公开页全部通过，才在新的发布锁
  内单独开启并观察一个完整周期；否则保持 false。任一资源、队列、锁、路由、worker 或业务门禁失败均立即
  关闭 10 个 data-sync 开关、移除专用 worker并恢复普通 worker/Beat；旧 `race_live=7543` 始终不动。

## 2026-08-30 exclusive proof 允许不可执行的 legacy backlog，但拒绝任何消费能力

- 决定：旧 `race_live=7543` 已被项目冻结为不得清理、迁移或消费的历史 backlog，不能为了生成 Racing API
  exclusive proof 将它归零。队列非空本身不等于存在 caller；是否可执行由 scheduler/network flags、worker
  容器、Celery worker 集合和订阅队列共同证明。
- 决定：proof 仍要求 `celery=0`、`race_sync_v2=0`；允许 `race_live>=0` 的前提是 host evidence 中不存在
  `race_live_worker` 或 `race_sync_v2_worker` 容器，Celery inspector 只返回精确预期的普通 worker，且其
  active queue 精确为 `celery`。任何 extra worker、非默认订阅、活动/保留/调度任务或开关开启均失败关闭。
- 该修正只使只读 proof 与既有生产边界相容，不批准消费旧队列、清理 Redis、调用 TRA 或写数据库。

## 2026-08-30 worker readiness 以协议响应判定，不依赖日志固定文案

- 容器 running、restart=0、OOM=false 仍不足以证明 Celery ready，但日志出现固定 `ready.` 字符串也不是稳定
  协议；本次普通/专用 worker 均未输出该行，脚本 240 秒超时后，普通 worker 实际已能返回 `pong` 并消费
  队列。后续 readiness 必须冻结目标容器 hostname，以 Celery `ping` 加 active/reserved 完整 worker 集合
  判定，同时保留容器、Redis/DNS、资源和队列门禁。
- readiness wrapper 误判仍属于本轮门禁失败：立即 10 false、停专用 worker、恢复普通 worker/Beat；不得
  因事后 pong 自动重试 selector。修正验收入口后另开新窗口，从停 Beat/drain 重新开始。
- dangling layer 清理只删除逐轮验证为零 tag、零容器引用的完整 ID；本次在用户授权删除 legacy Created
  容器后共清理 82 个 image manifest/layer、最终 dangling=0，当前/即时回滚 image 与 `race_live=7543`
  保持。Docker 首次 reclaimable 估算不能替代逐轮实际 `df`。

## 2026-08-30 dangling image 清理仍以容器引用为硬边界

- `RepoTags=[]` 只说明 image 无 tag，不等于无引用。删除前必须对每个完整 image ID 检查所有运行和停止
  容器；只删除 tag 为空且 `docker ps -a --filter ancestor=<id>` 为 0 的精确集合，不用全局 prune。
- 旧 `race_live_worker` 即使处于 Created/未运行，也属于生产 legacy 边界；之前的“清理零引用镜像”授权
  不自动包含删除该容器。共享层导致 4 个真正零引用 image 只释放 60 KiB，不能据 Docker 预估值猜测成功。
- 磁盘低于 8 GiB 时保持 10 false 并停止 Phase 2。删除 Created legacy 容器及其 image、清理 release/备份
  或扩磁盘都是新的明确选择；未确认前不得执行。

## 2026-08-30 排空门禁失败后不因任务稍后成功而自动重试

- Phase 2 的开关变更必须发生在停 Beat、普通 worker `active=0 / reserved=0` 之后。本次普通新闻采集在
  180 秒排空窗口内始终 active，因此门禁已经失败；它稍后返回 SUCCESS 只说明业务任务完成，不能把失败
  窗口改写为通过，也不能沿用原发布锁继续开启 network/apply。
- fail-closed 后保持 10 个 data-sync 开关全 false、专用 worker absent，恢复普通 worker/Beat；旧
  `race_live=7543` 只读保留。Phase 2、lifecycle、result public 与 correction 都等待新的发布窗口和完整
  前置门禁，不从失败步骤中间续跑。
- 中断产生的已过期 data-sync claim 不直接 SQL 清除。旧任务在全关状态消费后返回
  `disabled/claim_expired`，checkpoint 未计失败；控制面已明确允许 selector 对过期 token 做原子换代，
  手工清 token 会绕过 generation/plan CAS 证据。
- 现有 2+1 内存配置仍通过 1536 MiB 门槛，不扩 RAM；当前实际约束是磁盘仅比 8 GiB 冻结底线多约
  16.0 MiB。不得为继续灰度降低磁盘底线、删备份或盲目 prune；恢复足够余量须走精确可恢复清理授权，
  无合适对象时再扩磁盘。

## 2026-08-29 manifest 路由列表保持 roster 声明顺序，只禁止重复

- `allowed_hosts` / `allowed_path_prefixes` 的安全合同是非空字符串、无重复，并与当前 resolved route 的列表
  逐项相等；前缀匹配不要求字典序。builder 既然从已审 roster 原样生成 manifest，apply 不得再施加 builder
  没有保证且 transport 不需要的排序条件。
- 不重排 TRA roster 常量，也不对 manifest 静默排序：两者都会改变 route/registry digest 或破坏与冻结
  standing policy 的精确绑定。修复只把 `values == sorted(set(values))` 收窄为唯一性校验，后续 route-drift
  精确比较保持不变，重复值仍在任何事件写入前失败。
- Phase 2 的 3 次 provider 请求及新增 identity/ledger 是失败证据，保留而不清理；它们不是 enrollment 或
  发布成功。hotfix 必须在 10 false 下发布，随后 Phase 1/Phase 2 全部重走，不能从已经失败的 task 续跑。

## 2026-08-29 Meta/Facebook 入口防护采用赛事路径级 429

- 用户已确认采用 Nginx 入口规则，不使用扩内存制造公网门禁通过。UA 只匹配大小写不敏感的
  `meta-externalagent` / `facebookexternalhit`；URI 只匹配精确 `/races/` 和 `/static/` 下字体后缀
  `woff/woff2/ttf/otf`，返回 `429`。
- 不做全站 UA 封禁，也不按来源 IP 封禁：Meta 来源 IP 分散且会变化；全站封禁会扩大社交预览影响。
  规则同时覆盖 HTTP/HTTPS，其他 UA/URI 必须走原 location/proxy/alias。
- 入口规则已通过 PR #119 上线；五阶段启用仍逐门禁推进。任一公网、资源、队列、业务终态或
  zero-write/write-delta 门禁失败，立即恢复 10 false、停止专用 worker且不消费旧 `race_live`。

## 2026-08-29 应用 canonical redirect 不能替代分布式 crawler 入口防护

- PR #117 已证明畸形 query 可在数据库前快速 301，且正常赛事页本身可约 0.036 秒返回；但 Meta crawler
  使用大量 `57.141.2.*` 来源继续跟随清洁 URL并抓取字体，5 分钟仍有 464 个 crawler 请求。应用层修复
  降低了单次成本，不能单独保证公网 20 秒可用性门禁。
- 入口重验必须使用冻结的总时长 `curl --max-time 20`；额外 3 秒 connect 限制只能作为诊断，不能替代原
  门禁。按原门槛仍出现首个请求 20.001 秒、0 bytes/HTTP 000，故激活保持停止。
- 主机 load、可用内存和 swap 正常时不得因公网超时直接扩内存。下一步优先级是有界入口控制：可选精确
  Meta/Facebook crawler UA 的 `/races/`/字体拒绝或 429，或在 CDN/WAF 做同等规则；是否牺牲社交预览、
  返回码和作用路径是新的产品/运维决策，当前授权不自动选择。
- 未取得该入口策略确认并重新通过完整公网窗口前，10 个 data-sync 开关保持 false、专用 worker不运行，
  不从 Phase 1 或 discovery 续跑。旧 `race_live=7543` 继续只读保留。

## 2026-08-29 公网可用性是激活硬门禁，畸形赛事查询必须在数据库前规范化

- 专用 worker 内存通过不代表 Phase 2 通过；同一窗口的 root/www 任一请求超时仍立即关闭全部新写入、
  停专用 worker并恢复普通 worker/Beat。事后恢复 200 不能替代失败窗口证据，也不能自动续跑 discovery。
- Meta/Facebook crawler 把筛选分隔符带成 `®ion=`/`Â®ion=` 后，赛事日历不得复制未知或未规范化 query
  到所有筛选链接。检测到未知 key 或上述污染片段时必须在执行日历 queryset 前永久跳转到清洁 URL；正常
  链接只保留 `tab/region/grade/when/year/q` 的规范化值，cursor/direction 仍由当前页面重新生成。
- 当前瓶颈是 4 个 Gunicorn 请求槽被慢 `/races/` 抓取占满，不是主机内存不足。先消除请求放大并以生产
  公网延迟/5xx 重验，不为通过门禁临时增加 Web worker、降低 1536 MiB 内存阈值、动用 swap 或直接扩容。
- 此修复不修改 migration、自动化容量、provider 网络或旧 `race_live`；必须在 10 个 data-sync 开关全 false
  的关闭态发布。发布后先验证畸形 URL 快速 301、正常 `/races/`/root/www 200 和 0 新写入，再从 Phase 1
  重新建立一套新鲜门禁证据。

## 2026-08-29 provider transport 授权必须绑定用途名与规范 URL 二元组

- future discovery 的 identity 请求与已纳管 racecard sync 可访问同一固定 path，但二者是不同用途；transport
  allowlist 必须显式接受 `racecards_identity_<region>_<day>` 与该 region/day 规范 URL 的精确二元组，不能
  仅按 URL 放行，也不能把 identity 调用伪装成 `racecards_sync_<day>`。
- identity region 只允许冻结 registry 的 6 个规范名称，day 只允许 today/tomorrow；endpoint 名、region code、
  query 顺序或 day 任一错配都必须在 DNS 解析前拒绝。该补丁不改变 proof request budget、registry digest、
  credential、redirect、host 或 path 边界。
- provider 结果中的 `request_count` 只统计成功解析的响应，不能代表 transport 完全未尝试。生产审计还必须
  对照 capacity ledger 与 host budget；本次 `provider_response_invalid` 的业务 request_count 为 0，但 ledger
  已保守预留 1 次且 host outcome 已记录失败，因此按一次失败尝试处理，不立即重试。

## 2026-08-29 同一 provider host 的共享预算只可单调收紧

- `RaceLiveHostBudget.host` 是跨 legacy race-live 与 data-sync 的共享唯一行，不能同时满足
  “精确 1050ms”与“精确 2000ms”两个互斥条件。持久值改为该 host 已纳管消费者中的
  最严格下限，各消费者只要它不低于自身安全下限即可使用。
- 新消费者要求更严时，必须在 `select_for_update` 事务内单调提高 `min_interval_ms`；
  若 `next_allowed_at` 已存在，还要增加新旧下限差值，不得让已预留的下一次请求沿用旧短间隔。
  任何路径不得自动降低共享下限。
- 该修复不变更 migration，不通过生产 SQL 热改绕过代码门禁。修复发布必须先保持所有
  data-sync 开关 false，验证 legacy 初始化/racecard 对 2000ms 兼容后，再从 Phase 1 重放。

## 2026-08-29 低成本生产 sizing 使用显式 2+1，扩容只作为专用 worker 复验后的后备

- 当前 2 vCPU / 3.4 GiB 生产实例的 resident profile 显式设置 `GUNICORN_WORKERS=2`、
  `GUNICORN_THREADS=2`、`CELERY_WORKER_CONCURRENCY=1`。仓库通用默认值暂不修改；该值是基于当前生产
  约 1.9 req/s、8 req/s 峰值和真实任务窗口验证的 host-specific 配置。
- 内存优化优先减少常驻 Python 进程，不调整 PostgreSQL 已较小的 128 MiB shared buffers，不限制 Redis，
  不用 drop cache、降低 1536 MiB 门槛或提高 swap 使用来制造通过读数。OneBot 保持原运行态，旧
  `race_live` 不消费。
- concurrency=1 的保留条件是每轮普通调度峰值在 5 分钟内自然归零、active/reserved/scheduled 可清空、
  worker pong、失败数不增加且公网稳定；任一不满足先停 Beat、drain，再把普通 worker 恢复为 2。
  本次峰值 22 且最大约 4 分 17 秒归零，因此暂时保留 1。
- 单个 Web 容器的 force-recreate 会产生真实切换损失；本次记录到 14 次短暂 5xx。健康恢复后零新增 5xx
  只能证明稳态可用，不能把这 14 次抹掉。后续 sizing/release 应增加滚动 Web 切换能力或选择维护窗口。
- 2+1 只证明现有 resident stack 暂不需扩容。`race_sync_v2_worker` 仍有 384 MiB cgroup 上限，启动并热身后
  必须重新执行内存、SwapFree、队列、延迟和 5xx 门禁；若失败，优先扩容至 8 GiB，而不是继续削减核心 Web
  或让普通任务长期积压。

## 2026-08-29 关闭态代码与 schema 可保留在线，容量失败不得开启任何自动写入

- PR `#110` 的精确候选已证明普通 `0073 -> 0074/0075` migration、持久 runtime/TLS mount、服务身份和公网
  都通过；因此容量失败的最小止损是保留新代码及 additive schema，同时保持全部 data-sync 开关关闭并不启动
  `race_sync_v2_worker`，而不是把已经验证成功的 migration 反向回滚。
- 1536 MiB `MemAvailable` 与 8 GiB free disk 是启动专用 worker、注入冻结容量和开始五阶段启用前的硬门禁。
  临时停 OneBot、只删除零容器引用旧镜像属于本次获准的有界恢复尝试；即使读数只差少量，只要未稳定通过就
  不得以清缓存、临场降低阈值、扩大 swap 或直接启动 worker 绕过。
- 资源尝试失败后必须先恢复原 OneBot，再把同步面收窄到总开关、scheduler、network 及所有 apply/public
  开关均关闭，确认 `race_sync_v2=0` 和旧 `race_live` 计数不变。下一次资源扩容后从 capacity admission 和
  future discovery 第一阶段重新开始，不继承本次未执行的阶段状态。
- 本次 1280 MiB swap 是 0600、非 fstab 的临时生产措施；它与镜像清理均不得被描述为自动化已启用。
  停用/删除 swap 或清理其他备份、镜像、runtime 仍是独立运维动作。

## 2026-08-29 普通发布起点绑定 artifact，隔离 release 同时保留旧 Compose 回滚挂载

- no-intent 的迁移前门禁不再比较候选最终 leaf，而是要求 fresh live leaf 与已验签 handoff artifact
  内的 `preflight.migration_leaf_set` 精确相等，并且该 leaf 属于代码审查过的普通发布集合；这同时阻断
  handoff 后 TOCTOU 漂移和未知分支。迁移后 completion 仍精确要求 `0075`。
- release 外持久目录是运行数据与 TLS 的 canonical host root；新 Compose 只从这两个绝对根挂载。
  同一 isolated checkout 还必须建立 release-local rollback compatibility path，使回滚到仍使用
  `./runtime/*` / `./deploy/certs` 的 PR `#108` Compose 时不会静默挂载空目录。未跟踪 runtime 和 TLS
  使用整目录 symlink；Git tracked 的 `horse_profile_completion` parent 保持普通目录，只把
  `cache/batches/review/budget` 四个运行态子目录链接到稳定根，避免污染 worktree 或阻断 checkout。
- compatibility symlink 不是信任根：发布脚本逐项比较 `realpath`，TLS key/cert 目标必须留在稳定证书根
  内，候选 Nginx 必须在 build 和服务停止前通过 `nginx -t`。任一不一致均零停服、零 migration。

## 2026-08-29 普通 migration 的 no-intent 校验必须区分 pre-migrate 与 post-migrate leaf

- `recovery_intent_mode=not-required` 只表示当前 schema 不属于受限 migration-history repair，不表示
  数据库在运行 `migrate` 前已经位于候选最终 leaf。普通 forward deploy 的 intent 阶段必须接受 handoff
  artifact 绑定且 catalog 校验通过的受审起始 leaf；完成阶段仍必须精确要求候选最终 leaf。
- 本次 `0073 -> 0075` 在 migration 前被“必须已是最终 leaf”的条件阻断，禁止通过手工伪造 marker、修改
  preflight artifact、直接调用 `migrate` 或跳过 wrapper 继续发布。必须用独立修复 PR 补齐状态机和真实
  PostgreSQL 端到端回归后，重新走完整发布门禁。
- release 隔离不能把 TLS 私钥/证书当作 Git checkout 内容。Nginx 的证书 mount 必须指向 release 外稳定
  runtime，或在新 release 中以不暴露内容的受审复制/绑定步骤建立；切换前必须验证
  `fullchain.pem`/`privkey.pem` 可读和 `nginx -t`。仅恢复应用 health 不等于公网恢复。
- 任一发布门禁失败后，先证明 migration 边界和镜像身份，再恢复精确旧服务。旧 `race_live` 队列和新
  data-sync 开关继续保持原值；故障恢复不构成绕过失败门禁继续启用的授权。

## 2026-08-29 0075 为本发布最终 leaf，门禁重放与公开读取必须保持证据语义

- 普通 Release-B deploy/rollback 的最终 leaf 固定为
  `stable.0075_race_data_source_priority_and_reported_position`；pre-0075 目标不得使用通用
  rollback。`0075` 的 `reported_finish_position` 只可回填已存在的 official value，
  `finish_position` 只是内部稳定排序，未知名次必须保持 `NULL`。
- `data_sync` owner 的赛果不借用 legacy race-live policy/authority 决策。读取时独立重验
  result apply/public/correction 开关、exact enrollment/source/route、owner/enrollment generation、standing
  policy、registry/contract/provenance 与 publication audit；任一漂移即 fail closed。
- 因开关关闭而保存的 shadow/rejected 证据不是永久处理完成。同一 observation 只在相应
  apply/public 门禁真正打开后才可 promotion/重处理；门禁仍关闭时重放必须零新 audit
  写入。manual lock、身份冲突、证据不完整和真实 contract rejection 不得自动重试覆盖。
- provider 执行器的赛事身份唯一来自当前 `RaceDataSyncEnrollment.source_identity`；即使同事件
  存在多 provider/region/namespace identity，也不得通过 `.first()` 选择另一条“看似可用”的来源。
- `RACE_DATA_SYNC_ENABLED` 是 future discovery 和 artifact cleanup 的共同总开关；子开关、Beat route
  或 cleanup schedule 不能绕过它产生数据库、网络或删除副作用。snapshot waiter 的有界轮询必须在
  最小 jitter 下仍覆盖完整 lease TTL，不能在合法 owner 即将发布前提前宣告 timeout。
- shared snapshot 保留 8 天，以覆盖确认赛果的 T+7 更正窗口；清理有批量上限、校验
  manifest/cache key/SHA 和文件 inode，且只投递到拥有 `/run/race-data-sync` mount 的
  `race_sync_v2`。不消费旧 `race_live`，也不让普通 worker 处理 artifact 清理。
- cancelled/finished 为 lifecycle 终态；cancelled 停止所有 checkpoint，postponed 丢弃旧
  result datetime 并等待新 schedule。T+30 告警只针对未确认且非 cancelled/postponed 的 enrolled
  event；已有 open incident 不得占用后续 batch，赛果确认后 incident 自动 resolved。
- 历史 claim 关闭态收口只处理 exact preview 中的过期空证据行，不把既有 lifecycle 或 race-live 当作
  本发布附带清理项。生产原有 `enabled/enforce` lifecycle controls 保持原授权状态；新 data-sync
  lifecycle 继续由独立 false 开关隔离，旧 `race_live` 队列只读计数、不得消费或迁移。

## 2026-08-28 自动赛事数据以一次最终生产确认为授权边界，canonical 写入必须重验 exact claim

- 本 change 的产品目标明确覆盖早期文档中的固定 7 天 shadow、多 PR、逐地区或逐赛事人工批准：未来赛事
  时间、出马表、状态、赛果和更正均按 standing policy 自动运行，三类获准来源均作为正式数据使用，公开页
  不显示来源等级或内部阶段。PR 完成后只申请一次绑定精确 revision/image 的最终生产合并与部署确认。
- 启用时按 future discovery、time/racecard、lifecycle、result public/correction 依次开关并逐步自动验收；这是
  同一发布内的可观测性和 kill-switch，不产生新的人工批准门槛。任何门禁失败立即停止后续步骤并保持相应
  写开关关闭，不得以“已有最终确认”为由绕过备份、容量、身份、来源合同或回滚边界。
- provider transport 在数据库事务外执行。网络返回后，任何 schedule、racecard 或 result canonical 写入必须
  在该写事务最先按统一锁序锁定 event、projection control、tracking、enrollment 与 checkpoints，并重新核对
  owner/enrollment/claim generation、attempt token、claim expiry、entry/route/plan SHA、checkpoint lock
  version 及 required data kind。任一不符即整个投影零写回滚。
- claim 过期或被接管的旧 worker 可以保留已经取得的 immutable transport 证据，但不能写 canonical、完成
  checkpoint，或通过 fail/release 改动新 owner 的 claim。complete/fail 同样要求 `lease_expires_at > now`；
  不能把外层 task 成功返回、HTTP 200 或 receipt 存在误报成业务投影成功。

## 2026-08-20 赛事数据自动同步 R0 使用独立持久 owner、限时 manifest 与隔离 worker

- 新 writer 只能使用 `RaceEventProjectionWriteOwner.DATA_SYNC`；旧 `LIVE` 不由 migration 或普通 enrollment
  自动转移。唯一允许的 legacy transfer 必须证明 legacy runtime 关闭、legacy/new 两条队列完整 drain、无
  active claim，并绑定 current/LKG/revision/tracking 的精确 baseline 后单事务执行 owner generation CAS。
- enrollment 是赛事数据同步选择边界，不替代 lifecycle membership。普通纳管必须绑定 exact commit、standing
  policy、census/event/source/route/owner snapshot、entry SHA、限时不超过 24 小时的 manifest；过期、歧义、
  identity/route/owner 漂移均逐场零写拒绝。
- provider roster 仍以既有 Slice A 为唯一 facade。adapter 为 implemented 仍不等于可联网；缺任一 audited
  proof、host allowlist、path prefix、正 request budget 或最小间隔时，route resolution 必须返回不可用。
- `race_sync_v2_worker` 只消费 `race_sync_v2`，使用独立 concurrency/prefetch/time limits、max-tasks-per-child、
  max-memory-per-child 和 Compose CPU/memory 上限；不得消费或清理遗留 `race_live` backlog。
- reverse disenrollment 必须绑定当前 event/source/route/owner/enrollment snapshot，逐场释放 tracking、checkpoint
  与 `data_sync` owner；来源、observation、revision 和 audit 永久保留。任一 baseline 漂移即该场零写拒绝。
- future discovery 当前只允许读取 raw SHA 绑定的 standing policy 并生成限时小批 proposal，不得由 Beat 直接
  apply。proposal artifact persistence、route admission 复核和独立 live-apply 开关完成前，自动纳管保持关闭。
- `RACE_DATA_RAW_*` 容量值默认全部为 `0`，含义是配置无效而不是无限制。只有基于生产磁盘、备份占用、
  provider/region 成本与 cleanup/hold 故障的 sizing proof 冻结正值后，network admission 才可能通过。
- release freeze/resume/rollback 必须把新 worker 当作独立状态机成员。目标旧镜像 service catalog 不含新 worker
  时不得恢复它；普通 rollback 只接受包含 `0074` 合同的目标，pre-0074 为另行审核的跨 schema 恢复。
- 所有 R0 事件写路径遵循 `RaceEvent -> projection control -> live tracking -> enrollment -> checkpoint -> source`
  的统一锁序；optional control/tracking 不存在时也必须在 source 前创建并锁定，后续拒绝通过 savepoint 零残留；
  会停用旧 checkpoint 的 rotate/transfer/manifest 外层必须先按稳定顺序锁全量目标行。snapshot `COMPLETE` 只
  允许复用 150 秒，publish/fail 也必须 CAS `lease_expires_at > now`，失败态必须有显式 retry boundary。
- legacy owner transfer 的信任根是配置 raw SHA 绑定的独立 approval 文件，不是 API 调用者传入的布尔状态或
  自签 manifest。approval 必须在 canonical manifest 生成后产生，并绑定 manifest/receipt 原始字节 SHA、commit、
  时间窗和 event；apply 还须复核当前 runtime、两条队列 drain、entry digest 与 projection baseline。
- `0074` 发布 guard 必须拒绝列 type/nullability/default 或 CHECK 语义漂移；只比较列名、约束名或出现
  `data_sync` 字符串不构成 schema compatibility。rollback 在 image switch 前后必须持久 phase，`switching`
  歧义态禁止自动恢复猜测；race-live/data-sync 任一可信 sibling marker 为 `switching` 或两者 action/phase
  不一致时都必须全局拒绝恢复。
- 本决定只固定 R0 关闭态控制面，不批准联网、赛事字段写入、公开赛果、生产 migration 或部署。首次生产启用
  仍需 PostgreSQL/Celery/Compose、容量故障与独立代码 review 门禁，以及单独 G2/G3 授权。

## 2026-08-17 未来赛事时间只写官方明确值，备份可恢复性先于磁盘清理

- 首批未来时间只使用 York Racecourse 官方 Order of Runnings；其他地区没有明确、当前、可核对的开赛
  时间时保持缺失，不按日期、往年时间或服务器时区猜测。
- 赛事时间写入必须同时记录 authority、source URL、confidence、逐字段 before/after 与 operation log；
  写入不等于 lifecycle enrollment 或 enforce 授权。
- OSS 配置存在不等于远端恢复点成立。只有 endpoint 可解析、上传返回成功且 `head_object` 大小与本地归档
  一致，才可记为远端备份；当前 bucket 为空，因此本地备份不得清理。
- 标准备份格式统一为 PostgreSQL custom `.dump`，低成本部署在 Compose db 内生成/RDS 用隔离 client，
  必须非空、TOC 有效、0600、SHA 可核对后才原子发布。Nginx 仓库配置以当前生产已验证文件为准，未来
  发布不得再用 HTTP placeholder 覆盖正式 TLS。
- 数据库运维脚本不得根据 checkout basename 或缺省值猜部署栈；必须显式声明 allowlisted
  `COMPOSE_FILE` 与实际 `EXPECTED_COMPOSE_PROJECT`。low-cost 操作经受审 wrapper 精确绑定 resident
  project；RDS 不得调用其 Compose 中不存在的 `db` service。

## 2026-08-17 legacy direct-finish 只作为关闭态 disarm 的历史兼容证据

- 早期 canary 可在任务首次执行已经到达 T+30 时，把赛事从 `scheduled` 直接推进为 `finished`，并留下
  `time_t_plus_30` applied transition；不得为此伪造缺失的 `running` transition 或改写历史状态。
- 只有显式 `--phase inactive --disarm` 且 runtime 为严格 `false/off` 时，才允许完整 provenance、精确
  canary metadata、相同 generation 且 effective time 不早于 T+30 的 `scheduled -> finished` 单边作为
  历史证据。首次收口还必须把 transition activation ID 与当前 active evidence 精确绑定；成功写成
  canonical inactive evidence 后，同一 artifact 的重复 disarm 必须以零写 `replay` 返回。普通 verify、
  activate/reactivate 与运行时 enforce 仍要求标准两段链。
- full-cohort prepare 的空集合是正常终态：写出 canonical census/enrollment plan 后返回
  `status=no_candidates`，不得创建空 registry，也不得把零候选误报为发布失败。

## 2026-08-16 过期 canary 只能在严格关闭态执行精确 disarm

- runtime 过期必须继续阻断普通 verify、activate 和任何 enforce 使用；不能延长、重签或忽略旧 artifact 的
  `runtime_valid_until`。
- 但关闭态撤销是安全收敛动作：只有 verify 命令显式 `--disarm --phase inactive` 时可加载过期 manifest，
  后续仍必须由 mutation 层验证 lifecycle `false/off`、完整 event/control cohort、原始 SHA、approved commit、
  frozen schedule/enrollment/evidence 和无范围外 enforce 漂移，任一不符即零写失败。
- 该例外不改变 control mode、公开赛事状态或历史 transition，只把匹配的 legacy canary active evidence 原子
  降为 inactive；后续 registry promotion/activation 仍按独立 G3 授权执行。

## 2026-08-16 新 migration 必须原子推进 forward、completion、rollback 与 catalog 合同

- 任何新的生产 migration leaf 不能只新增 migration 文件；同一发布必须同步 ordinary forward plan、
  initial-install/resume 的单调前缀、restricted completion 最终边界、generic B-to-B rollback 目标校验和
  allowlist，以及该 migration 新增表/约束/索引的 PostgreSQL catalog 语义。
- recorder 显示 migration 已应用不等于 schema 合同成立。完成校验必须同时验证新对象的存在、FK 删除
  语义、唯一性和关键索引；否则必须 fail closed，不能启动长期服务或宣称发布成功。
- generic rollback 保留已应用的 additive `0073`，只允许目标提交携带精确受审的 0071/0072/0073
  migration 内容与依赖；更早目标仍需单独的跨 schema recovery，不在普通 rollback 中反向迁移数据库。

## 2026-08-11 全量 lifecycle 使用 registry，不放大双赛事 canary

- 双赛事 canary 的完整 cohort 校验与锁模型不能直接扩为数百场；否则每个单场 task 都读取或锁完整 ID
  列表，形成 O(N^2) 读取和全局串行。通用路径改为唯一 active registry + 逐场 membership，单场 task 只
  锁自身 membership/control/event；PostgreSQL per-event task 使用 shared advisory transaction lock，
  promotion/activation 使用同键独占锁，既阻止 rotation 竞态又允许不同赛事并行。
- “全量”本 change 只指一个冻结 census cutoff 下的当前全部合格赛事 E1，不宣称未来新赛事永久自动
  admission。缺 control 的合格赛事必须保留在 census 并显式进入 strict-v2 enrollment；enrollment 仍每批
  最多 20，registry promotion 每次最多 100，全部 membership 完整且摘要一致后才能 activation。
- selector 以 `(race_datetime,event_id)` 选择和截断，但 artifact membership 统一按 event ID 数值升序
  canonical；successor 必须绑定 predecessor。激活 successor 时同事务 retire predecessor、清理旧 claim，
  范围外 enforce control 降为 shadow 且停止刷新，历史 canary/registry evidence 保留不改写。
- registry runtime trust root 固定为 raw SHA、membership SHA、member count、activation ID 四元组，与 legacy
  canary root 互斥。激活后 env 切换失败时，false/off 重试只能通过完整 artifact/DB 校验复用原 activation
  ID；不得生成不同 ID 或凭 caller 参数覆盖数据库事实。
- 本 change 不启用 race-live、不接新 provider、不发布新闻或 QQ，也不自动 admission 新赛事。代码审核、
  合并、关闭态部署、census/enrollment/promotion 和 true/enforce 分别受独立门禁约束。

## 2026-08-10 新 candidate 必须取得独立 release approval，旧 G3 不可迁移

- resolver 语义变化后生成的 candidate `d95b580b…a418a` 与 artifact `f74c116f…6ce0c` 是唯一可进入下一
  G3 的对象；旧 `fc7962c3…e16e` candidate、`46b7951d…cd33` release manifest、release approval 和旧
  G3 均不得复制、解释或重放到新对象。
- 新 G3 必须显式覆盖：创建绑定新 candidate 的 release approval/manifest、fresh 写前备份、maintenance/
  drain、manifest-bound dry-run 精确重现 `32 profile update / 180 race create / 230 race update / 12
  existing / 32 source / 128 audit`、apply 和完整 verifier。动作或 snapshot 任一漂移立即停止。
- 独立静态复审已通过；额外自定义 230-row DB 重放未完成，不能作为证据引用。正式 dry-run 是写前必须
  通过的权威动态门禁，不得因静态 `APPROVED` 而跳过。首次发布只允许 `8307/45666/45738`，16 blocker
  继续冻结，`full_network` 另行授权。

## 2026-08-10 日本场地届次与场地前缀距离只做严格语法归一化

- Netkeiba 的 `3中京8` 表示届次/日次包裹的 `中京`，`芝2000` 表示 2000 米；它们可分别与 JBIS
  `中京`、`2000m` 比较，但不能由删除任意数字或任意前缀实现。
- 场地归一化只对 Netkeiba 来源接受完整字符串命中“可选数字 + 仓库已知 JRA/NAR 场名 + 可选数字”；
  其他来源与未知场地保留完整规范化文本。若双方都有数字包装且值冲突，也不得合并。距离只接受显式
  metric unit，或 `芝/ダ/障` 后 3-5 位数字及可选 metric unit；双方都有场地类型且冲突时不得合并；
  mile、furlong、近似换算和带多余文本的值不进入同场 fallback。
- 该表示归一化只替换跨来源同场合同中的场地/公制距离比较，不改变不同来源、精确日期、actual start、
  名次、result status、race number/event 冲突和多解 fail-closed 门禁。任何扩大场地表或距离语法的变更
  都需新增真实正反例并重新生成 release candidate。

## 2026-08-10 跨来源同场重复不得用放宽完整性门禁处理

- profile 已有 Netkeiba 完整履历、candidate 携带 JBIS 同场履历时，source-aware idempotency 和包含赛名
  变体的 canonical key 可能把同场视为两条；写后 official start count 守恒会正确拒绝。
- 不允许删除既有记录、忽略 `start_count_mismatch`、把 career 强制改为 complete、只特判
  `インターポーザー`，也不允许重放当前 release。最小修复必须建立可审查的跨来源同场等价合同，并证明
  不会合并不同赛事；dry-run 还须在写前报告逐 profile 的合并后出赛数守恒。
- release approval 已生成但 DB transaction 全回滚。任何代码/等价语义变化都要求重新部署、重新生成
  production snapshot/artifact/candidate、独立审查和新 G3；旧 candidate `fc7962c3…e16e` 禁止重试。

## 2026-08-10 batch-0001 r2 模块批准不等于生产写入批准

- 用户批准只覆盖 `32` 个 identity 的四模块并继续冻结 `16` 个 blocker；它允许生成只读 mapping bundle
  和 immutable release candidate，不自动授权 `--commit`、自动首次发布或 `full_network`。
- 精确 G3 必须绑定 candidate `fc7962c3…e16e`、artifact `9d2a1e32…9c16`、production snapshot
  `1bb55ec9…fbe4` 及完整 action/publish scope。执行前仍需 fresh 写前备份、writer/lock/queue 复核与
  maintenance；写后 verifier 通过前不得推进 execution ledger 或 ordinal 2。
- 三个 draft profile `8307/45666/45738` 的首次发布属于候选显式动作范围，不能隐含在“资料更新”中；
  G3 必须明确包含或排除。其余 `29` 个已发布 profile 只更新受审资料，不改变发布状态。

## 2026-08-10 production draft 保留权威 evidence root 的路径身份

- participant bridge 的 source binding 会记录实际输入路径；生产生成时不复制 PR90 r2 到新 release，
  而是由 PR93 精确 image 在 `--network none`、只读根文件系统下绑定权威 evidence root。
- 因绝对路径参与 manifest 内容，生产 batch/source-binding SHA 与本地 `/tmp` 回放 SHA 不应相同；验收
  以相同上游四份文件 SHA、combined candidates SHA、32/16/2 守恒和生产绝对路径语义 verifier 为准。
- 失败的容器初始化或权限探针只有在 output 目录仍不存在时才允许按原参数重试；成功发布 ready marker
  后禁止覆盖。当前 draft 只继承 batch inclusion approval，仍不能推断 module 或 release approval。

## 2026-08-10 participant occurrence 不直接进入 production apply

- participant census 的记账单位是一次参赛 occurrence，HorseProfile production apply 的记账单位是
  唯一马匹身份；两者不能通过放宽“duplicate identity”校验拼接。
- 唯一允许的转换键为 `source_name + external_horse_id`。重复行还必须拥有相同马名、父、母、出生年，
  且除 candidate key、抓取/官方核验时间、该次参赛入口 evidence 外的完整补全内容逐字节语义相等；
  否则保持阻断。跨 provider 的相同四字段身份也不自动合并。
- canonical 选择固定为最新 `official_start_count_verified_at`，再以 candidate key 破同值；桥接 artifact
  必须绑定全部 occurrence、blocker、batch index、execution ledger、completion manifest 和 candidates
  SHA。去重不允许丢失参赛证据。
- participant batch inclusion approval 与四模块资料审核是两个门禁。桥接只记录前者并生成 pending
  draft；不得把命令执行者、历史工作簿或聊天推断成 module reviewer，也不得自动生成 release/G3。

## 2026-08-09 受审 official-results 包必须仓库内可寻址且 CLI 可直接执行

- `full_network=true` 只接受仓库相对三文件包，因此独立审核通过的包必须以精确 summary SHA 登记到
  `runtime/research/reviewed_packages/`，包目录内不得混入 receipt 或说明文件。
- GitHub Actions 使用 `python runtime/research/<script>.py` 直接运行验证器与 bundle builder；两个入口
  必须自行把仓库根加入 import path，不能依赖开发机的隐式 `PYTHONPATH`。
- checked-in package 的 CLI 测试必须验证 `433 = 87 + 346` 守恒。审核 receipt 明确记录所有生产、
  澳洲采集、official-results 与 `full_network` 权限均为 false，避免把证据提交误解成运行授权。
- 澳洲 346 场的外部许可门禁不能由用户普通运行授权或技术审核替代；未取得许可时只能保持可审计 gap，
  或由用户明确把本轮写入范围缩为非澳洲 87 场。

## 2026-08-09 澳洲年度目录按自然年拼接官方相邻赛季

- TJCIS 澳洲章节明确采用 `8 月 1 日至次年 7 月 31 日` 赛季口径，不能直接代表单一自然年。
- 2025 正式目录改为 Racing Australia 官方 `2024-2025` 与 `2025-2026` 两份 Group/Listed 日历中
  `local_date.year == 2025` 的 G1/G2/G3 并集；每届身份包含官方 group ID 与实际日期，允许同一赛事
  因年内改期出现两届，不按名称去重。
- 澳洲官方结果以 meeting page 发布。同一页面的多场赛事必须以来源赛名、途程与级别共同选表；只有
  澳洲可共享结果 URL，完全相同选择器仍视为重复并 fail closed。URL 不能访问或选表不唯一时保留
  evidence gap，不回退到 Wikipedia、模糊名称或第一页结果。
- QREC 结果使用其官方前端公开配置引导的官方 API；认证材料仅驻留当前进程，不写日志、代码或工件。
  任何 bootstrap、host、年份或响应合同漂移都确定性停止。

## 2026-08-09 新 migration 必须同步推进受审 preflight 最终叶

- `0072` 虽然只改变 Django choices、数据库 SQL 为 no-op，仍会写入 migration recorder；因此发布
  合同不能继续把 `0071` 当作永久最终叶。
- 最小修复把 schema compatibility target、restricted-recovery final leaf、completion 命令和 host
  preflight allowlist 原子推进到 `0072`，同时保留 `0071` 作为单向合法中间态。
- 禁止通过删除 recorder、伪造 handoff、忽略 `migration.state` 或直接跳过 completion 恢复发布。
  首次失败后的生产只允许同一候选镜像恢复服务；正式完成仍须发布修复后的代码并重新生成 fresh
  preflight artifact。
- 普通 B→B rollback 也必须同时绑定受审 `0071` 依赖与精确 `0072` migration 内容/依赖；不含
  `0072` 的旧 image 不再是 code-only rollback 目标。回到 pre-0072 版本必须使用另行审批的数据库
  恢复/跨 schema 合同。

## 2026-08-09 新地区赛果必须绑定官方页面与同域数据端点

- 澳洲、德国、中东补全不使用 Wikipedia/Wikidata，也不以媒体报道代替全体参赛结果。
- 服务端页面直接含结果时保存页面证据；ERA/JCSA 等加载型页面必须同时保存页面声明和同域
  AJAX/API 响应，两者共同绑定 race identity、内容 SHA 和 parser version。
- 只接受 allowlist HTTPS host；普通 403、空壳 Loading/Error 或缺失 catalog 均按证据缺口停止，
  不绕过反爬、不猜测参赛马。
- 生产地区使用 `australia`、`germany`、`middle_east` 一等枚举，中东具体国家继续写入 country，
  不把它们降级为 `other`。

## 2026-08-09 canonical path 轮转必须先解除条件唯一身份

Release B apply 的临时阶段不能只替换 path 的 `year/slug`。当 reviewed topology 把另一条 path
轮转为同一 event 的新 canonical 时，旧 canonical 尚在会触发 `uq_race_public_path_event_canonical`。
最小修复固定为：锁定完整 path scope 后，在同一事务内先把全部受控 path 临时设为 `legacy` 并
写临时 key，再逐行写最终 owner/key/kind。该修复不放宽最终唯一约束，也不改变 reviewed artifact
的业务决策；必须由回归测试证明失败事务零写、修复后最终每个 published event 恰有一个 canonical。

## 2026-08-09 数据回填继续绑定人工 survivor 与跨年届次审核

- 官方身份相等只证明 duplicate boundary 是同一实际赛事，不自动决定哪条生产记录成为 survivor。
- 12 对香港重复边界推荐保留自然年/届次均正确的原记录，墓碑化错位记录，并把后续错位链的
  public year、edition、target 与 path 按 ledger 顺移；不得仅建立 canonical link 后保留重复公开记录。
- `series-5963` 的 2020 届赛事实际日期为 2019-12-29，`series-6501` 的 2015 届赛事实际日期为
  2016-01-09；推荐保留 edition，public year 使用实际自然年。
- 上述 14 actions 必须作为同一 reviewed manifest 完整审核并取得 G3 精确授权；代码发布、只读 census
  或旧 manifest 的授权均不等于生产数据 apply 或联网运行授权。

## 2026-08-09 duplicate equivalence 以受审官方结果身份为最小锚点

- 完整 `source_refs` 是 provenance 与漂移证据，不再整体决定“是否同一场赛事”。
- 只有 HTTPS official result、非空 provider、唯一匹配的 approved detail source 和内容 SHA 全部
  成立时，等价摘要才使用 `provider + URL + content SHA`，并继续要求客观字段、runner/result 一致。
- 该官方身份存在时，赞助商展示名和 TJCIS season catalog 差异不阻断同赛；任一官方证据条件
  缺失时回退赛事名 + 完整 `source_refs` SHA，保持 fail-closed。
- 完整 `source_refs` SHA 继续进入 event snapshot 和 series precondition；旧 census/overlay 不可复用。
  本修复不新增 schema 或 migration。

## 2026-08-08 production audit 只允许由运行时 collector 生成

receipt repair baseline 不再接受独立手写 SQL 的 positional row 编码。唯一口径固定为
`named-object-scalar-fk/v1`：行是带字段名的 object，FK 是按 receipt 主键排序的 scalar ID list；
生产 baseline 生成命令必须在 PostgreSQL `REPEATABLE READ READ ONLY` 事务内直接调用 preflight
使用的同一 collector。baseline 同时绑定 receipt IDs、operation IDs/FK IDs 和 created/updated
time bounds，loader 对完整字段集与版本 fail closed。这样修正生成口径而不改变任何 migration graph、
catalog、handoff、TOCTOU 或 restricted-recovery 决策。

## 2026-08-08 为什么人工确认门禁只保留在根 AGENTS.md

此前范围确认、实现确认、Git 操作、review、发布和生产动作授权散落在工作流文档、session
模板、skills、agents、任务交接和历史规格中，同一任务换线程后容易重复询问。现在根
`AGENTS.md` 是唯一权威，统一为 G1 范围、G2 交付、G3 高影响动作；其他文件只可引用，
不能新增或改写。初始明确实现指令可以满足 G1，机械 Git 步骤不再单独停顿；自动技术检查
只在范围、指纹、环境漂移或新增高影响动作时触发重新确认。

## 2026-08-08 为什么项目只保留 Codex 原生工作流

旧规格流程虽然早已不再是主流程，但仓库仍保存兼容目录、skills、契约分支和路径引用，导致
新线程继续尝试旧入口。为消除双重权威，本次删除旧流程目录、兼容 skill、workflow 路由与
专用历史治理 change；后续较大任务只在 `docs/changes/<slug>/` 按风险维护原生
spec/design/test/tasks/rollout 产物。历史业务事实可保留，但不再保留旧工具名或可执行入口。

## 2026-08-08 为什么 main 只作为受保护远端引用

长脚本与 PR 合并争抢同一个 checkout，会让运行中任务读取变化后的代码，也让脏工作区阻塞
集成。现在每个线程使用独立 `codex/<slug>` worktree，长任务固定到 commit SHA/镜像，PR
优先远端合并；只有影响相同数据库、服务、队列、配置或输入契约的生产发布才互斥。短时
integration lock 与 production release lock 分离，并由单一 release coordinator 操作生产面。

## 2026-08-01 Release B 以系列级链路治理取代逐 event duplicate 推断

- v1 `canonicalize_duplicate` 只表示 Release A 无法安全处理唯一约束冲突，不能作为 81 条生产
  数据都是独立重复赛事的事实结论。
- Release B 的最小 schema 范围是 event series/edition 与 active target series/year 两组约束
  切换；数据 action 改为一个 series 一个原子 ledger，禁止逐 event 部分提交。
- 同日重复 boundary 只有在来源与 runner/result 核心身份等价并经人工选择 survivor 后才可
  tombstone；后续错位链的 event 必须保留并重挂正确 target/path。
- duplicate 等价摘要必须包含 `source_refs` SHA；被判定 equivalent 的 duplicate 只有在审核终态
  为 `draft`、`race_series=NULL`、slug 精确为 `release-b-tombstone-<event_id>` 时才可建立 active
  canonical link，避免不同上游身份或仍公开记录被错误合并。
- duplicate 的既有依赖默认留在 tombstone，复用 `RaceEventProductCanonicalLink` 隐藏产品重复；
  无逐行 mapping/SHA 时禁止删除、repoint 或 dedupe。
- canonical product link 必须作为独立 managed ledger，不得同时计入 immutable reverse dependency
  SHA；inactive canonical link 是不可删除的审计记录。target supersession 必须同
  series/edition、指向 active survivor、仅一层且无链环。
- Release B 候选镜像构建后，必须由绑定 commit/image、`0070` leaf 与 DB identity 的 candidate
  one-shot 在旧服务仍运行时完成 forward schema preflight；运行时还必须显式绑定预先核对的生产
  DB identity。失败不得进入 release orchestration。通用 rollback 只允许 B→B，必须用 checkout
  后的目标 image 做 forward preflight；reverse preflight 仅属于另行审批的 pre-0071 跨 schema
  恢复，不能混入合法 B-only 数据的普通回滚。
- migration leaf 必须来自目标库实际 applied migration；review overlay 不得把不同身份摘要的
  同日记录判为等价，不得修改赛历修复范围外 target 字段，artifact 目录必须原子 no-replace
  发布；published event 缺少唯一 canonical path 时 verifier 必须失败。
- recorder 中任一候选 graph 未知的 `stable.*` applied migration 都是 schema identity 不明，必须
  明确列出并 fail closed，禁止静默过滤。reviewed supersession 的时间身份按 UTC 微秒规范值比较；
  series/edition 链式交换只允许在同一事务内使用完整 manifest SHA 绑定的临时身份解除即时唯一键，
  最终状态、ledger、verifier 与 exact rollback 合同不变。
- superseded target 的 manifest 字段在 overlay 使用固定 sentinel，apply 时写入当前已审核 manifest
  SHA；canonical links 必须与 equivalent boundary 的 pair/identity 精确相等，并允许多个 duplicate
  共享同一 survivor。既有 inventory 只处理非 superseded active target。
- 通用 rollback 不承担跨 schema 反向迁移：目标必须同时满足受审 `0071` 依赖合同与精确 `0072`
  终态；pre-0072 target 必须在任何 checkout/停服前拒绝，另走独立审批的停服恢复。所有 imported
  target 必须有关联 event；series identity collision 使用 edition-year identity。
- review template 与 reviewed overlay 使用同一字段形状；模板中的 census manifest SHA 在完整
  census 生成后由审核者填写。target 若已有 `superseded_targets`，自身不得再被 supersede，模型
  校验与 v2 overlay 共同阻断多层链。
- 替代 read-only reviewer session `019fb946-ae91-7a21-b455-29ce02766fd7` 已关闭首轮 4 个 P1 和
  1 个 P2，最终 `VERDICT: APPROVED`。Release B 实现、部署、v2 census、人工 overlay、生产 apply
  和 Release C 继续是独立门禁。用户已明确确认本地实现，但该确认不授权 commit、PR、部署或
  生产数据操作；实现完成后仍须完整验证和独立代码 review。

## 2026-07-31 历史赛事赛历完整性当前只闭合 Release A 本地范围

- 当前候选只允许包含 nullable `RaceEvent.edition_year`、统一
  `RaceEventPublicPath` registry、target supersession、
  `HistoricalRaceCalendarRepairReceipt`、兼容读写代码、前台修复、collector 修复及离线
  census/repair 工具；对应唯一 migration 为 `0067_historical_calendar_release_a.py`。
- Release B 的 series/edition 唯一约束切换和 Release C 的 `edition_year` non-null/自然年
  check 必须分别等待生产全地区 census、数据 verifier、独立 review 和新授权后再创建。B/C
  migration 提前出现在 Release A 图中即为阻塞。
- public year 固定为自然年，edition year 固定为届次身份；历史“重点”以 G1/G2 等级族表达，
  不批量篡改运营 `priority/is_featured`；公共旧路径只保留 registry 301，不复制第二张 event。
- 全地区 `prepare/apply/verifier/rollback` 是本地可执行工具，不是生产执行回执。生产 census
  即使只读也需独立授权；任何 apply 还需冻结 manifest/approval/action scope/actor、
  maintenance 和已验证备份，不随代码部署自动触发。
- 本轮完整 `stable` 的 `3989 / 25 failure / 54 error / 72 skip` 只能作为失败边界证据。
  其中已识别环境/既有失败不等于本 scope 回归，也不能据此声称完整 suite 全绿；当前发布判断
  只能引用聚焦 `61/61`、collector `101/101`、Django check、migration drift/graph 和
  diff check，并继续把真实 PostgreSQL、并发、性能与独立代码 review 作为未完成门禁。
- 实现授权不等于发布或生产数据授权；当前没有 commit、push、PR、部署、生产只读或生产写入
  权限。
- 跨届次 `authority_url` 只允许由 `race_event_years.validate_authority_url()` 定义一份中央
  合同；年份写入和 repair classifier 禁止各自实现 URL 判断。当前合同为有效 HTTPS、hostname
  存在、无 credentials/fragment/whitespace，允许合法 path/query；任何不通过者在 classifier
  中保持 manual/block，不得形成 action。该修复通过聚焦 `76/76`，但仍须重新独立 review。

## 2026-07-31 年度参赛马研究暂以生产 HTTP origin 为唯一正式来源入口

- 当前生产对外验收入口仍是 `http://umafans.run/`；研究 workflow 必须显式使用该 origin，
  不得因 Compose 映射了 443 或目录中存在证书文件就推断 HTTPS 可用。
- collector 可以校验并保留 HTTP/HTTPS scheme，但 host 仍只允许 UmaFans 两个精确域名，
  并继续禁止凭据、显式端口、越界 query/fragment、非规范 path 与 offsite race/profile
  URL；这不是通用明文 HTTP 放行。每次 run 选定 scheme 后，全部 sitemap、race、profile、
  redirect、run manifest 和 region manifest URL 必须保持同一 scheme。
- base URL 是 checkpoint identity 的一部分。HTTPS 失败 checkpoint 不得原地改写或以
  HTTP 参数续跑；协议修复后的第一轮必须 fresh，以免请求账本与 queue 身份失真。
- 年度 `other` 地区清单仍按完整 canonical race URL 精确匹配；scheme 是 key 的一部分。
  当前 HTTP run 只能使用 HTTP manifest URL，不能把 HTTPS 清单自动降级归一化后复用。
- 为域名取得可信证书、启用 Nginx 443 server、验证 TLS 后，是否切回 HTTPS 作为独立运维
  change 处理；不得把本次研究脚本修复扩大为未经设计和验收的证书上线。

## 2026-07-29 race-live P0 采用条件注册、保持告警队列并实施两阶段关闭态发布

- P0 在 Beat 生产者侧按
  `RACE_LIVE_SCHEDULER_ENABLED`、`RACE_LIVE_MONITOR_ENABLED` 独立构造周期 entry；
  关闭即不注册，对应 task body 的 `disabled` 防御继续保留。分钟 entry 开启时附带
  `expires=55`，该值只表示 Celery 最佳努力过期元数据，不承诺 broker 立即物理删除或已预取
  消息绝不执行。
- P0 不把 monitor 或 alert delivery 迁移到普通 `celery`。selector 继续投递
  `celery`，monitor、delivery 和 poll 继续使用 `race_live`；在完成 incident 级 durable
  dispatch admission、并发领取和 broker 失败恢复之前，不通过换队列把重复告警风险扩散到
  普通 worker。
- 首次关闭态发布固定使用
  `deploy/deploy_race_live_p0_closed.sh prepare` 与
  `deploy/deploy_race_live_p0_closed.sh start-beat` 两个阶段。`prepare` 在构建前先停止并
  验证 Beat、drain/停止普通 worker，通过两次零 migration plan 和候选关闭态 schedule 后只
  准备 web/普通 worker/nginx；`start-beat` 复核候选状态后才单独启动 Beat。原样
  `deploy_lowcost.sh` 不具备这一候选检查点，不作为本 P0 的发布入口。
- 本决策不新增告警队列、模型、migration 或业务数据动作，也不授权清理历史积压、启动
  `race_live_worker`、启用 race-live flags 或执行生产发布。当前只完成本地实现，下一步为
  独立代码 review。

## 2026-07-27 明确非完赛状态计入完整性，但不得成为名次

- 官方 `SCR/DNF/DSQ/中止` 等受控状态表示该参赛者已被官方交代，但没有数值完赛名次；
  adapter 必须同时保留来源原文与规范化状态，不得把表格行号或后续顺序写成名次。
- JRA `中止` 采用现有模型语义 `pulled_up`。恢复聚合只允许明确列入受控集合的退赛/非完赛
  状态退出数值名次分母；`unknown`、`declared`、`Also Ran`、`N/A` 等不确定或无顺序状态
  继续产生 `incomplete_result_order` blocker。
- 完整名次是所有实际完赛马的连续、唯一数值顺序；“非完赛状态已交代”和“完整排名”是两个
  并存事实。该决定不放宽官方 evidence、participant identity、receipt 或生产 apply 门禁。

## 2026-07-27 recovery adapter 不得以成功空跑替代 scheduled 目标处理

- inventory 中 `scheduled + result_due=true` 是本次历史赛果恢复的合法冻结状态；显式
  recovery mode 必须贯穿 JRA、NAR、Sporting Life 和 ZEturf 等存在状态过滤的详情 adapter，
  普通模式继续只接受 `finished`；TOBA discovery 继续按精确 target scope 执行。
- adapter 对精确输入产生 `events=0` 时，即使命令 return code 为 0，也必须按未覆盖 target
  形成 blocker；不得把空 candidate/review CSV 解释为 prepare 完成。
- source-scoped CSV 必须携带冻结生产 `event_id` 并由 candidate 回传。聚合层对所有来源独立
  校验完整参赛名单、所有非 `withdrawn/scratched` 马的结果覆盖、连续唯一内部名次及
  discovery-only 标记；缺一项即 `incomplete_result_order`，`Also Ran` 页面顺序不得成为名次。
- 同一 run 内不同地区 adapter 的 `standard_name` 必须唯一；UK/US Sporting Life 即使复用
  parser，也必须分别保存 candidate/review/summary，禁止后执行来源覆盖先执行来源。
- recovery coverage 只接受当前 run `state.json` 绑定的标准
  `candidates/combined_candidates.jsonl`，并复核其 SHA-256/size；CLI 显式外部 JSONL、
  identity 漂移或缺 state 一律拒绝。逐场 candidate 的 `source_provider/racing_region`
  还必须与 plan target 完全一致，不能靠自报 `result_order_complete=true` 跨 shard 放行。
- 本轮不通过手改 CSV status、直接运行 adapter 或手工拼接 combined candidate 绕过 runner。
  非 JRA adapter 的恢复状态过滤需按测试、独立 review、release、关闭态部署后再重新联网；
  已取得的网页赛果只能作为人工审核线索，未进入 receipt 前不得授权生产 apply。

## 2026-07-27 recovery adapter 输入按来源分片，JRA 同时服从两层请求账本

- `race_result_recovery` plan 必须同时绑定 inventory 文件路径、文件 SHA-256 与内部
  manifest SHA-256，并强制携带当前批准的 `source_map_version`；缺失或版本不符直接拒绝，
  精确 40 场 source map 不允许降级为任意子集。expected target 创建和既有 snapshot 恢复都先运行 inventory verifier
  重算当前数据库 identity，再按冻结 event ID 顺序绑定；event、状态、赛果、地区或其他
  inventory 字段漂移直接拒绝，不生成可人工补写的伪 snapshot。
- adapter 输入不能只按地区分组。同一地区允许多个批准来源时必须以 `region + source` 分片，
  runner 只向 manifest 的精确来源交付对应 CSV，避免 JRA/NAR 或 TOBA/Sporting Life 交叉扩张
  网络范围。
- JRA 年度列表与详情页复用同一 source cache。显式 recovery mode 可读取已审批 CSV 中仍为
  `scheduled` 的恢复目标，普通模式继续只接受 `finished`。每个初始请求和每次 redirect 都先
  通过 runner v2 的 JRA-only HTTPS host/path，再分别占用全批次共享预算；任一层拒绝都不得
  发起 transport。该决定不放宽 BHA、France Galop、Equibase 等 manual-only 路由。

## 2026-07-27 赛果候选联网在 expected-target 构造缺口处保持零请求阻断

- `race_result_recovery` 的 40 个 event ID source map 校验通过，不代表运行时 expected-target
  snapshot 已可生成。生产只读调用实证 `expected_targets_from_plan()` 返回
  `expected_target_empty`；此时不得手工伪造 snapshot、改用普通三模块 plan、直接运行 adapter
  或跳过 historical runner。
- 本次联网权限没有被解释为绕过编排权限：自动请求、manual-only 请求、candidate 和 source
  cache 均为 0。修复必须先为 recovery event ID 构造并绑定精确 `RaceEvent` identity，
  同时补齐 JRA list/source 与受控请求上下文，再按测试、独立 review、精确 release、部署和
  新联网授权顺序推进。
- 关闭态部署允许修改控制面开关，但不授权正式赛果投影。既有 race-live publication policies
  和 allowlist 已关闭；event 924 暂定结果保留，正式结果、canonical link 和新闻/QQ 均不改。

## 2026-07-27 赛果恢复必须服从 projection owner 并以 blocker=0 才算完成

- 指定窗口的赛果恢复不得直接按名称/日期复制数据，也不得直接写 `RaceEventResult`。所有正式结果先形成
  official revision/evidence，再按 `RaceEventProjectionControl` 的 `live / historical /
  unmanaged / manual_paused` owner 分流；event `924` 保持 live owner。
- 跨 `RaceSeries` 的重复实体只生成身份候选；人工批准后以
  `RaceEventProductCanonicalLink` 持久化非 canonical → canonical 展示关系。底层赛事、系列、
  revision 和 evidence 不删除，旧详情 URL 保留。
- inventory 的到期判定复用 `decide_race_lifecycle()`：有时间用 T+30m，无时间用当地次日零时；
  非法时区/日期 fail closed。
- `confirmed/cancelled/postponed/blocked` 只用于 accounted 守恒；只要仍有一个
  `blocked_with_evidence`，恢复 run 就不能标记 completed，也不能对外宣称“全部收集并确认完成”。
- 实现、部署、网络候选收集和生产写入是四个独立授权面；后一阶段必须绑定其精确 artifact/commit SHA。
## 2026-07-26 赛事新闻质量治理实现完成（代码就位，待审核与发布）

- 按已审方案实现赛事新闻曝光治理和多语言术语统一两组变更，使用单一协调实现分支
  `codex/impl-race-news-quality-20260726`。
- 曝光：新增 `RaceNewsExposure` 模型、两席状态机、主赛事身份解析、硬重复分类、角度分类；
  首页/头条/热门榜/QQ 统一读取同一 exposure 预算。
- 术语：新增 `TermMappingEvidence` 模型、共享 occurrence resolver、公开字段 canonical 门禁、
  published CAS repair。旧中文译名只进入 `aliases_zh`，`TermAlias.source_language` 不接受中文。
- 两组变更默认关闭（ENABLED=false, SHADOW=true），代码回滚仅关闭 enforce，保留审计表和 migration。
- 实现采用测试先行：RED → 子代理实现 → GREEN，所有新增和回归测试通过。
- 具体实现见 `docs/changes/govern-race-news-exposure/` 和 `docs/changes/unify-public-racing-terms/`。
- 未实际发布，不授权部署、生产术语写入、历史文章修复或生产 exposure 写入。
## 2026-07-25 日本重赏 P0 一期采用 Netkeiba + JRA/NAR 身份共识

- JAIRS 完全退出自动化与人工主链。JRA 中央马档案和 NAR 地方马档案分别作为正式 provider；
  有直接官方马匹 ID/URL 时优先使用，没有锚点时只允许带赛事日期、马号和官方来源的有界上下文
  检索，只有 Netkeiba 的对象继续阻断。
- 一期范围包含 G1/G2/G3、J-G1/J-G2/J-G3、JpnⅠ/JpnⅡ/JpnⅢ及证据完整的日本训练马
  海外 G1/G2/G3。等级只决定 `G1 → G2 → G3` 的批次顺序；G3 的完整双源证据可以通过，
  G1 的单一 Netkeiba 证据仍必须阻断。
- 自动候选只接受马名、父、母和完整出生日期一致：Netkeiba+JRA 或 Netkeiba+NAR 为 A，
  三源一致为 A+；任何冲突、年份级日期、字段缺失或候选不唯一均不提交。
- “日本训练”使用独立证据门禁：JRA 的美浦/栗东等所属、NAR 地方所属，或绑定来源与赛事日期的
  已审核等价证据；比赛地点、日文名、日本产地和 profile 地区均不能单独证明。
- 项目所有者确认网站是个人非商用学习项目，不另设商业授权申请前置。访问合同仍保持最小化、
  低频、缓存、请求预算、拒绝即停且不公开复制源页面；用途改变时重新评估来源合同。
- JRA-VAN DataLab 只定义 Windows 清单导出与 Linux 离线校验接口：交换包必须绑定 UM record
  type、血统登记编号、数据规格版本、带时区 snapshot、逐记录 SHA、输入清单与输出清单 SHA；
  校验器拒绝夹带原始 UM record。普通 DataLab 原始记录不直接复制到公开产品，本期网页 PoC
  不依赖 Windows 节点，也不实现常驻采集服务。
- 2026-07-25 只读盘点确认直接官方马匹锚点为 0 后，首个 PoC 固定从第二层开始：只消费冻结的
  官方赛事 URL、日期、场地、马号和精确马名；索引页最多跟随一个唯一详情链接，参赛行和同源
  马匹链接都必须唯一，禁止站内开放式马名搜索。外国出生/转籍线索只决定抽样覆盖，不证明
  日本训练身份。单匹总计最多 6 个不同 URL/18 次传输，JRA/NAR 上下文链最多 3 URL/6 次传输。
- 审核批准与正式写入继续分离：approve 生成包含 reviewer、获批 profile 集合、时间、prepare
  artifact SHA 的不可变审核事件；commit/verify 除精确批准 SHA 外还必须显式确认该 artifact。
  approve 还必须从冻结的 Netkeiba 与 JRA/NAR 原始身份字段重新计算共识，不能信任候选中的
  `fields` 自述或只靠伴随文件 SHA；真实 prepare 候选必须携带 commit 复验所需的完整冻结选择
  字段，approve 必须要求内嵌 candidate/blocker 与已哈希 JSONL sidecar 规范字节一致。
  所有来源 URL 与重定向逐跳限定为 allowlist HTTPS，
  JRA/NAR 直连锚点必须携带非空来源 ID，每次传输使用显式连接/读取超时。
  首次事务以唯一批准 SHA 写入 receipt 与 OperationLog；重复执行只有在 before/after、资格、
  官方来源证据摘要、结果 payload 和审计日志全部与 receipt 一致时才返回零写 replay，不能仅凭
  当前字段值相同推断历史写入成功。

## 2026-07-24 首页人工头条实现完成（代码就位，待审核与发布）

- 已按审核通过的方案实现 HomepageHeadlineSelection / HomepageHeadlineRecommendation
  模型、服务层、signals 协调、admin 修复、路由、视图和模板。
- 具体实现与 `docs/changes/add-editorial-headline-control/design.md` 的通过版本一致。
- 未实际发布，不授权部署或生产写入。

## 2026-07-24 首页人工头条采用唯一控制行，AI 推荐保持独立记录

- 规划中的首页人工头条不在 `NewsArticle` 增加 `is_headline` 布尔字段。全站唯一头条是跨文章不变量，
  用多文章布尔字段会把替换、并发和残余状态分散到多行，也容易让 Django Admin 绕过资格与审计。
- 方案采用固定 `homepage_primary` slot 的 `HomepageHeadlineSelection` 单例控制行；所有设置、替换、
  取消、接受推荐和失效协调锁同一行，并用 `version` 拒绝陈旧页面。数据库以固定 slot
  CheckConstraint 和 `UNIQUE(slot)` 保证当前版本全库只有一个合法控制位。
- AI 编辑推荐使用独立 `HomepageHeadlineRecommendation` 快照和 active 条件唯一约束。推荐生成只读取
  已保存的赛事优先级、自动分数、封面和发布时间信号，不新增第二套 LLM 调用；生成推荐永不写 selection，
  只有有权限用户明确接受后才可切换人工头条。
- 头条统一资格要求文章当前已发布、网页公开时间不在未来、有效标题/摘要/正文非空；不强制封面。
  人工选择、AI 推荐和算法 fallback 共用该资格；选择失效时清除人工状态并记录审计，保留原有三级时间
  窗口、48 篇合格候选和排序元组，避免无效文章被算法立即选回。
- 首页当前没有页面级或 headline cache，本变更不为头条新增缓存；实时性通过数据库读取和连续请求验证。
  若后续需要 cache，必须另行补 key、TTL、事务提交后失效和故障回退设计。
- 本决策已由同一独立方案 reviewer 三轮收敛并获得 `VERDICT: APPROVED`；最终字段和文件范围以
  `docs/changes/add-editorial-headline-control/` 的通过版本为准。当前只完成规划，尚未授权实现或发布。

## 2026-07-24 已审核空胜绩采用显式证据语义并版本化发布候选

- “没有胜绩记录”不再等同于“胜绩资料缺失”。有实际胜绩沿用原判定；没有实际胜绩时，只有最新
  非 ignored 的 `major_wins` 候选为 `applied`、审核结论为 `approved`、payload 精确为空列表，
  且记录执行人、执行时间，才表示“已审核确认无胜绩”。未审核、非空 payload、pending、
  conflict、rejected 均继续阻断，不伪造胜场、不绕过严格完整度。
- 完整度语义会改变同一审核输入能否提交，因此属于发布候选的安全属性。新 artifact 和 candidate
  统一绑定 `p0-horse-full-profile-completeness.v2`，所有 candidate/v2 release 加载与重算路径
  必须精确校验；历史 v1 artifact 继续可信 v1 dry-run 验证兼容，任何 v1 commit 明确拒绝。
- 手工 ready 复审无胜绩马时，新的 `major_wins` 审计必须继续保存空列表，不能写入较新的非空
  手工标记而使档案立即重新不完整。
- 旧 candidate 即使已有正式批准，只要尚未完整落库，就不能跨策略版本恢复。保留旧
  candidate/release/ledger 作为审计证据；部署新受审版本后从冻结 bundle 重做 prepare-release。
  发布授权必须在最新成功 review 后取得，review 前的持续授权或预授权不替代该门禁；对象、动作
  或公开范围漂移必须 fail closed。

## 2026-07-23 P0 正式提交拆分为无批准候选与独立批准

- 人工 xlsx 内容复审不等于生产写入批准。bundle 之后先执行 `prepare-release`，冻结完整子集、
  commit artifact、预计数据库动作与自动首发范围到精确 candidate SHA；candidate 不含
  `approved_by`，不写 `release_approved`，不写业务表或公开状态。
- 新 rolling release 只生成 `p0_horse_production_release_manifest.v2`，并反向绑定真实 candidate
  SHA；v1 仅用于历史证据的只读复验，不再允许 builder 新建 v1 批准。正式 commit 和 standalone
  apply 都必须验证 candidate 普通文件、完整 SHA、batch/state、准备事件与有序批准账本；
  superseded 或 abandoned candidate 永久 fail closed。
- 自动首发授权集合来自已复审 artifact，而不是地区 batch manifest。只有冻结 disposition 为
  `attempt_publish_after_commit` 的对象可进入 live gate；hidden、manual lock、already published
  以及未进 artifact 的 blocker 只进入排除审计，后续状态放宽不能扩大原批准。
- 文件证据采用按 SHA 命名的不可变快照；账本严格解析 malformed/partial 行并在 append 后
  flush/fsync。候选替换顺序固定为“写新 manifest（未批准）→ supersede 旧批准 → approve 新
  manifest”，防止崩溃时新旧同时 active。
- batch state lock 保护产物与 checkpoint 的短事务，execution lock 串行化正式批准、DB apply、
  publish/retry 与 abandon。abandon 只允许尚未落库批次；已 committed 的数据库事实不能通过改
  state 伪装撤回。execution lock 必须按同线程同 batch 可重入实现，锁顺序固定为
  execution -> state；standalone v2 同样从 validation 持锁到数据库事务退出。artifact 尚未
  committed 时必须复验 current batch manifest/combined SHA；只有精确 artifact path+SHA 的
  committed completion run 可改用不可变 snapshot 恢复。
- publish completed 是一次性终态证据，不是“可重新计算”的当前 gate。相同 candidate 的普通
  重复 commit 必须返回冻结 publish checkpoint/report，不得因人工降级、解除 manual lock 或其他
  gate 放宽再次调用发布。publish 未完成或失败只允许显式 `--retry-publish`；普通 commit 不兼任
  发布恢复入口。
- `prepare` 也属于同 batch execution window；锁顺序固定为 `execution -> state`，不得让 commit
  在 prepare 的 artifact、workbook 或 checkpoint 更新中途读取证据。
- prepare-release 的锁合同必须位于 public service，而不能只依赖 management command。所有 direct
  caller 先取得同 batch execution lock，再进入 state serial lock；等待后必须复读 manifest/state。
  committed 或 abandoned 终态只允许零写拒绝，不得生成新 candidate 或补写 state/ledger。
- completed 重放不是仅凭 state checkpoint 的快捷返回。它必须在任何 dry-run/DB apply/publish 前
  复验冻结 candidate、artifact/release、commit/publish checkpoint、committed completion run，
  并要求唯一精确匹配的 v2 `auto_first_publish` 成功账本事件。证据缺失、重复或报告计数/ID/
  frozen exclusions 不匹配时只允许人工审计，禁止自动补账本、重算 checkpoint 或写数据库。

## 2026-07-23 task 5.2 分叉生产线执行决定

- 本次已批准 task 提交与生产 HEAD 从共同父提交分叉：切换会回退并行已上线功能，合并会产生
  未获本次精确授权的新 SHA。为同时保住生产运行态和授权对象，本次只把目标 Git tree 构建为带
  完整 revision label 的一次性任务镜像，未替换在线 web/worker/beat/race_live_worker。
- 本次网络权限缩到一次性 prepare 容器：生产 `.env` 和在线应用保持 false，仅该容器覆盖 true。
  容器退出后确认其已不存在、四应用 false，生产 HEAD、马匹计数和 healthz 均未变化。
- 本次一次性执行仅完成 task 5.2 的 prepare/xlsx，不是公网应用版本切换，也没有扩大数据写入
  授权；未执行 bundle、commit 或自动首发。后续动作仍受既有精确 artifact/hash 授权边界约束。
## 2026-07-23 Codex 原生流程增加“用户确认实现”，HRN 正文按来源可信容器修复

- 项目主流程更新为“探索 -> spec/design -> 方案审核 -> 用户确认实现 -> 测试先行 -> 子代理实现 ->
  独立 reviewer 会话 `/review` -> 用户授权后发布”。方案审核通过后必须汇报根因、范围、测试/RED、
  历史数据边界、风险/回滚和 reviewer 结论；用户明确确认实现前不得写测试、改应用代码/配置/迁移、
  启动实现 subagent 或重处理历史数据。
- HRN 正文边界问题按来源 DOM 结构解决：真实正文容器 `.article-body` 是主边界，选择器缺失时 fail-closed；
  不使用文章 ID、公开中文词黑名单、翻译 prompt 或模板/CSS 隐藏替代抓取修复。
- 新采集修复、历史候选识别、历史文章重处理和生产部署是独立门禁。历史识别只读、分批并输出哈希；
  部署前已存在的 HRN 文章一律留在历史 scope。历史写入必须绑定精确批准 manifest 及 file SHA，在事务锁行后
  复核全集与逐篇输入/输出哈希，任一漂移整批零写入；备份和另一次明确授权仍是前置条件，人工正文默认不自动覆盖。
## 2026-07-23 netkeiba 解析版本、旧批处置与生产授权拆分

- 会改变 canonical payload 的 netkeiba 解析规则必须递增显式 parser version；版本同时
  绑定批次输入 fingerprint 与日本 netkeiba canonical cache。只失效 checkpoint 而继续
  命中旧 cache 仍会绕过新解析器，因此不接受。
- stale netkeiba cache 在网络刷新成功后必须通过独立 sidecar 文件锁与 `os.replace` 原子
  替换；竞争调用若已发布当前版本则复用该 payload。普通 cache 首写仍使用 no-clobber，
  JBIS 和其他地区不进入替换路径。
- prepared 批次中的 blocker payload 也按候选成功落 checkpoint。解析器变化后不手改
  state、不直接 resume 旧 approved manifest；旧批保留证据并 abandon，重新 select/approve。
- 页面事实不足时继续阻断：Haru Aube 的空着顺水沢行不因存在马号/骑师就推断为实际出赛
  或取消；部分 expected identity 继续要求完整四字段，不因来源页面本身完整而放宽候选锁。
- 生产授权按不可变对象拆分：受审代码版本绑定部署/触网授权；prepare 与人工 xlsx 复审后
  再冻结 bundle/hash；生产 commit 与自动首发必须取得绑定精确 bundle/hash、完整子集和
  公开范围的新授权。触网窗口在 prepare 成功或异常后立即恢复 false，不跨人工审核。

## 2026-07-22 日本滚动补全来源：netkeiba ID 直取优先，JBIS 检索兜底

- 日本候选持有 netkeiba key 时，select 阶段 `source_namespace` 直接取 netkeiba 并走
  `_NetkeibaClient`（马匹页 + 战绩页 + 血统页 3 页直取，provider-bound 身份）；无 key
  候选保持 `_JBISClient` 名称检索。其余多 key 场景保持 identity_keys 顺序扫描（不用
  frozenset 迭代，保证跨进程确定性）。
- netkeiba 与 JBIS 身份空间不同源：netkeiba key 不代表 JBIS ID；不做 netkeiba 失败
  中途回退 JBIS（预算与身份语义都不允许）。日本每候选请求预算 3→4（3 页 + 1 次
  redirect 余量）。
- netkeiba 页面解析不猜值：结构不识别、年份生日、未白名单毛色、未知单字产地一律
  fail closed 阻断候选；生涯总数取马匹页「通算成績」并与逐场对账（不一致由既有
  adapter gap 逻辑处理）；异常状态 `取消/除外` 不计出赛、`中止/失格` 计出赛。
- ExternalHorse 存量空四字段（12,405 条）不在本 change 批量修复，仅随批次自然覆盖；
  批量修复如需进行另立专项。

## 2026-07-22 发布资格时间、积压时效和历史恢复

- `first_seen_at` 表示“系统何时看见新闻”，不能代表“新闻何时通过全部发布门禁”。新增
  `publish_ready_at` 作为唯一发布资格时钟；只在非 ready→ready 时设置，重复任务不得续期。
  历史值不猜测、不回填，避免旧稿被伪装成新稿。
- 自动消费时效固定为 `0–24h`；`24–72h` 只人工复核，`>72h` 只显式处置。实时候选和积压候选
  各自有查询上限，积压默认关闭并按地区灰度。任何通道都不改变原有每窗口、每地区或全站配额，
  不放宽来源、门禁、去重、评分或 QQ 规则。
- 当前历史候选一律先生成 SHA manifest，默认 `keep_manual`。逐篇恢复必须由独立 decisions
  文件、reviewer、封印后的精确 SHA 和 apply 确认共同授权；内容、状态、门禁或更新时间漂移即
  跳过。恢复只刷新通过完整重校验文章的 `publish_ready_at`，不直接公开也不创建 QQ delivery。
- 用户已确认 2026-07-22 manifest 中的精确 21 篇全部舍弃。舍弃使用新增
  `discard_ignored` 审核动作，沿用后台“忽略候选新闻”语义，将 workflow/review/automation
  三层状态统一改为 `ignored` 并记录 `ignored_at`；不物理删除文章。该动作仍受 reviewer、原始
  快照、新 manifest SHA、逐行锁和漂移拒绝约束，并记录在
  `decision_reason.publish_ready_recovery`；重复 apply 必须幂等，公开和 QQ 账本不得变化。
- 生产灰度顺序仍是“部署且开关关闭 → 只读预览 → 单地区 4 个窗口 → 五地区 → 24 小时观察”；
  这不是 shadow，但开关和地区 allowlist 仍是即时止损面。

## 2026-07-22 遗留 CrawlJob 使用 SHA manifest 和条件终态

- `CrawlJob(status=started)` 超过 60 分钟不等于执行已死亡。dry-run 必须记录 Celery active/reserved 和有效生产窗口租约；Celery 无回应、任务无法映射来源或租约未过期时 fail closed。
- apply 必须绑定不可覆盖的 manifest 和 SHA-256，逐行加锁复核 status/started_at/source 未漂移，并使用有界批次。历史审计数 `32` 只作基线，不是直接写入清单。
- 抓取执行只能以 started→success/failed 条件更新抢占终态。未抢到终态的迟到任务只记录 `terminal_state_already_claimed`，不得覆盖 CrawlJob 或 `NewsSource.last_crawl_*`。

## 2026-07-22 P0 BASIC 层公开发布门禁与自动首发

- 公开展示最低门槛为 BASIC 层：名称 + 五地区地区 +（`horse_identity_verified_keys`
  含 netkeiba/nar/hkjc/sporting_life 认可 namespace 的 key，或父/母/出生日期三字段
  齐全）。verified 身份只由 fail-closed 身份回填 commit 或人工批准批次 commit 写入；
  sync 按名称归属写入的扁平 `horse_identity_keys` 不产生公开信任。
- 滚动批次地区 commit 通过幂等复验后自动首次发布本地区马（含批次 create_new 新建马，
  经 completion run 反查）；`published_by` = 批次 commit 审核人，不设系统用户；
  `auto_first_publish_enabled` 死字段保持预留不启用，opt-out 用
  `manual_lock_flags.auto_publish_blocked`。
- hidden 或曾 hidden（`hidden_at` 非空）的马任何自动/批量通道都不得发布，必须人工
  重新发布；这是隔离 `mark_profile_completion_ready` 把 hidden 复活为 ready 的既有行为。
- 发布失败不得进入批次 committed 终态；同 artifact 全量重 commit 会被快照漂移检查
  fail closed（既有行为），发布失败恢复走 `--retry-publish` 专用阶段，且 retry 必须核验
  commit artifact 的 `idempotent_verification.passed`。
- 主规格 `horse-profile-pages`"只有管理员审核发布后才进入前台"按三种发布路径（人工 /
  批次审核后自动首发 / 批准的存量批量发布）修订，全部经同一 `transition_review_status`
  审计通道；首批验收（2026-07-21 已完成）前仍只允许人工发布。
- 未完整公开马统一显示「资料补全中」徽章；`空壳/仅基础资料/部分血统` 等内部措辞不出现在
  公开页，`completeness_status` 仍是唯一事实源。

## 2026-07-22：去让赛混合标记对象一律进 review；最终复审沿用 Claude Code 等价复审

- 代码复审 P1：term 5087（`THE KWANGTUNG HANDICAP CUP (HANDICAP)` / `广东让赛杯(让赛)`）原文同时含未括号 handicap（赛事名组成部分）与括号 (HANDICAP)（补充说明），既有兜底删除会错改为「广东杯」。决策：凡原文去除括号标记后仍含 handicap 完整词或四种中文让赛标记的对象，一律进 review 桶保持原值，不写入；京成杯锁定例外（`京成杯秋季让赛`→`京成杯秋季赛`）显式豁免该守卫。term 5087 与 5570 留待人工决定展示名，另走受控流程。
- 本任务最终复审沿用 2026-07-21 先例：codex CLI 不可用、原 codex reviewer 会话无法恢复，由 Claude Code 对精确候选做等价完整只读复审（首轮 REVISE → 修复 → 同一 reviewer 限定复审 APPROVED，P0/P1/P2 清零，审前/审后 fingerprint `2889f4b2…` 一致）；不以测试通过或普通 diff 替代复审。
- 发布授权：用户 2026-07-22 针对精确版本（提交 `5b491561` + artifact SHA `30d85d1a…`，168/1550/2/0）回复「发布吧」；发布报告见 `docs/changes/remove-handicap-markers-from-race-names/release_report.md`。

## 2026-07-22 P0 身份回填写入门禁加固

- 离线冲突 fingerprint 为裸 SHA-256 hexdigest（64 字符），"offline" 作用域编进被哈希
  内容而不是字符串前缀；任何指纹格式必须满足 `HorseIdentityConflict.fingerprint`
  `max_length=64`，禁止再以 SQLite 不校验长度为由放行超长值。
- 批准后的 manifest 在 commit 时必须重算哈希并与存储值、操作者提供值双重比对；只比
  存储值等于把批准后的 manifest 篡改视为可信。artifact 文件 SHA 另独立校验。
- commit 是第二道 fail-closed 防线：dry-run 之后 profile 发生漂移（同 namespace 出现
  其他 key、四字段与证据矛盾）时整个候选丢弃并记冲突，不写部分身份；identity key
  一律 casefold 写入（含 HKJC 字母数字 ID），原始大小写只留在 `identity_evidence`。
- 证据判级按行来源 namespace 核验：可识别为其他 provider 的 `horse_id` 不得贴上本
  地区预期 provider 的标签（如 UK 行上的 racing_post ID 不得写成 sporting_life key）；
  无法识别来源的行保持既有行为并留待后续治理。

## 2026-07-21：赛事展示名让赛处理以原文括号形式为准，京成杯为例外

- 用户明确修订让赛清理规则：原文名（RaceEvent.original_name / RaceSeries.canonical_name_original / TermEntry.source_ja）中 handicap/让赛 被括号圈住时，视为赛事补充说明，中文展示名删除该标记；未被括号圈住时，视为赛事名组成部分，保留。所有案例按此规则判定，不再设"条件描述型豁免"的独立逻辑。
- 京成杯是唯一例外：凡展示名为"京成杯秋季让赛"的对象（日本 RaceSeries 285、术语 1972/15215）一律改为用户此前逐字锁定的"京成杯秋季赛"，与 2026-07-21 已写入生产的系列 6125、Event 96 和 2010–2025 共 16 场历史赛事保持一致；该例外不与"Keisei Hai Autumn H 原文 H 无括号"的新规则冲突处理，而是显式锁定值。
- 删除机制沿用"只删不补"：仅删除四种中文让赛标记及直接包裹该标记的中英文括号，不补写"锦标""大赛"等新词；删除后无中文字符、同地区重名等校验失败的对象只报告、不写入。
- 本规则取代 2026-07-20"让赛不展示一律删除"的口径；范围仍限定赛事日历对象与 race 术语 target_zh，不回填历史文章、不新增术语。

## 2026-07-20 P0 来源地区与幂等修复边界

- `HorseProfile.racing_region` 是既有档案属性，不因本批样本归属自动覆盖；
  `HorseP0Source.racing_region` 必须记录已审核候选的 `sample_region`。候选地区与研究顶层
  地区冲突时，artifact 生成直接失败，不允许以旧档案地区替代本批审核事实。
- 旧 artifact 的幂等重跑只允许修复仍属于同一 artifact、同一 completion run 且状态为
  active 的确定性来源地区。来源已撤销、已转属新 run 或 evidence artifact SHA 不同，
  均 fail closed；不得借幂等重跑覆盖后续人工决定、证据、状态或审计归属。
- 首次成功 run 的 summary 固定保存首次写入结果；后续幂等核验写入独立
  `last_idempotent_verification`，不得把首次 `database_write_count` 覆盖为 `0` 或修复数量。
- P0 完整资料落库与首次公开继续分离。无中文译名马可以完整、待发布并在翻译中保护原文，
  但本批不自动发布；每地区首批公开样本仍需单独人工动作和公开面验收。

## 2026-07-20 P0 PostgreSQL 迁移事务边界

- 对会更新已有 `HorseRaceRecord` 的字段回填，不在同一原子迁移的后续 operation 创建该表
  的索引或约束。迁移按 schema fields、data backfill、indexes/constraints、authority
  顺序拆为 `0049-0052`，让前一事务的 trigger events 在后续 DDL 前结束。
- 每个迁移继续使用 Django 默认原子事务；禁止用 `atomic=False` 留下可见的半 schema。
  生产首次失败已完整回滚，二次 Phase A 必须从确认的 `0048` 状态重新开始。

## 2026-07-20 P0 美国组合来源批准与生产提交边界

- 用户/项目负责人确认当前冻结批次采用以下美国组合来源可满足项目严格完整标准：HRN 为逐场
  主记录；Fort George 由 Sporting Life 与 Racing Post 补齐；Equibase 只承担官方总出赛数、
  身份和颜色对账。该批准是批次限定、经独立批准的组合来源完整，不得表述为 Equibase 官方
  逐场履历，不得全局放宽 HRN 或 `count_aligned_records_unverified`。
- 冻结 v1/v2 JSON 字节保持不变：v1 SHA-256
  `55d80abed2b76a2d7fcf0cb97aadff800c3130c3815e84d8e6eb5b1c16b4befd`；v2 SHA-256
  `a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7`，并继续保留原口径
  `40/50`。独立批准 manifest SHA-256 为
  `29091d69573bab907cda2e9a081ae4684838b92d1f9b052a7601b6109a541077`；由此生成的 v3
  研究派生物 SHA-256 为
  `98a7019a400f10a4bf961d869f38f770e9e98afab76b557a3c784d4eff6e470e`，只在研究层达到
  `50/50`，不能反向改写冻结 v2。
- prepare 只能生成 pending 准备稿；当前 pending SHA-256 为
  `8aba561b856ffbdcd03c2a59228b166315174b539f20aef4ae6412bfe03b1b61`。apply 必须同时绑定
  固定 v2 SHA、可信 manifest SHA、调用方显式 SHA 和实际文件 SHA；记录、身份、来源、计数
  漂移或重复记录必须 fail closed。
- research module review SHA-256
  `1440550a3e4d203b604b9dba74b89b2f49ee7075bc168f35e756e54830f31db1` 的独立 reviewer
  第三轮结论为 `APPROVED`，只批准研究模块及该批次来源组合，不替代生产 artifact、formal
  dry-run 或准确集成版本的生产授权。
- production readiness report SHA-256
  `8cc36106091708827852401927a791a5575f2d6d490d1a306297e450612ed2c5` 仅为
  `static_schema_compatibility_check`，明确
  `safe_simulation_performed=false`、`commit_artifact_compatible=false`、
  `decision=blocked`、`database_write_count=0`。用户本次“继续推进”不构成生产写入授权；
  正式 commit artifact 与 formal production dry-run 完成后仍须重新申请精确授权。

## 2026-07-19 P0 父母出生年、全局来源身份与 v2 冻结规则

- `116` 条已审核血统证据必须解析为 `55` 个唯一父母来源身份；每条 v2 `source_identity`
  必须同时含 `horse_name`、`sire_name`、`dam_name`、`birth_year`，不得保留 name-only 或
  name + known sire legacy method。
- 父母出生年使用独立 approved artifact
  `runtime/horse_profile_completion/pedigree-research-20260719/reviewed_parent_birth_year_evidence.json`，
  SHA-256 为 `ed9f6419dccd41485b96884410ea9ab5976d8ab5ba2acfb97e03837a7a3deb54`，
  `reviewed_by=codex_manual_source_review`。这 `55` 个出生年不记为项目负责人逐字段提供或审核；
  parent identity manifest 只绑定该独立证据及既有审核上下文。
- provider namespace 可以规范化，external horse ID 必须在搜索候选、出生年证据、逐行 manifest、
  v2 JSON 和工作簿全链路按不透明原值精确一致；同 provider 不允许大小写、标点删除或其它
  近似匹配改变 ID。
- 自动 Netkeiba 父母候选只接受精确
  `https://en.netkeiba.com/db/horse/<id>/`。URL 含凭据、显式端口、query 或 fragment 时必须
  fail closed，即使主机名和路径前缀看似正确也不能进入 v2。
- Kentucky Wood 的父系 Balko 必须保留显式纠错审计：Netkeiba `000a02bd3f` 是 1925 年同名马，
  只留在冻结 v1；v2 使用 Racing Post `595446`、出生年 2001、父 Pistolet Bleu、母
  Ella Royale。纠错不得回写或重造 v1。
- 冻结 v1 JSON / workbook SHA-256 分别为
  `55d80abed2b76a2d7fcf0cb97aadff800c3130c3815e84d8e6eb5b1c16b4befd` /
  `4b68b87a076793eab0acc2357762afbd0c0fcaf2282fcf4122e3a2a855c2b696`；最终 v2 JSON /
  parent identity manifest / workbook SHA-256 分别为
  `a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7` /
  `b211d9040814b0b56ec30e8ef8930fdc10f4140a3a660cf491fcae12d0b6ab2b` /
  `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`。
- 工作簿 builder 默认读取 v2 JSON、输出 `-v2.xlsx` 和 `previews-v2`，环境变量优先于配置；
  冻结 v1 workbook 与 previews 目录是拒绝写入目标。本决定只固定只读审核产物和生成边界，
  不授权生产写入、部署、发布或网络 career crawl。

## 2026-07-19 P0 来源缓存必须自证身份、计数证据和安全出站目标

- `p0-horse-source-cache.v2` 不得用当前请求的马名补齐缓存身份。所有地区复放前必须由缓存
  `identity.horse_name` 或缓存 alias 命中请求马名；美国或提供了预期血统的候选还必须完整命中
  父名、母名和出生年份。
- 来源总出赛数只有在同时保存非空来源名、HTTP(S) 来源 URL 和带时区核验时间后才可参与
  `complete` 判定。数量相等但三项证据任一缺失时保留 `partial`，不虚增数量缺口。
- 受控来源 client 采用登记 HTTPS 主机白名单、禁止凭据 URL 和非 443 端口、关闭 transport
  自动重定向并逐跳校验 `Location`；重定向请求继续消耗同一单马预算。当前登记主机仅为
  JBIS、HKJC、Sporting Life、Geny 和 HRN 的实现目标。
- 引入逐场权威状态时，旧的未核验 `complete` 不仅降级生涯状态；若聚合状态为
  `complete_profile_full`，也必须降为 `complete_pedigree_2gen`。跨来源正式赛果覆盖旧
  `unknown` 时保留旧直接展示值，标准原始值和归一化值改用正式来源证据。
- 候选来源与资料 payload 来源不同时，来源内 external ID 不能互证；候选必须提供完整四字段
  身份并与 payload 一致，或以后使用显式人工审核的跨来源绑定。只有同名/alias 时 fail closed。
  同 provider 也只有在候选和 payload 都携带一致 external ID 时可直接绑定；显式来源 namespace
  与 `external:<provider>:...` key 冲突时必须拒绝。
- 总数证据门禁必须同时存在于 cache validator、履历 normalizer、数据库生涯 evaluator 和
  整匹马聚合 evaluator，不能假设所有调用都经过同一入口。研究 JSON 与工作簿只有
  `source_records_verified` 可显示完整，其它或非法 authority 均保持受阻/待审。
- `source_start_count=0` 是合法官方事实；此时空逐场列表可通过数量对齐校验。总数大于零时，
  空列表仍是完整履历缺口。
- 同 provider 比较对 provider namespace 做 NFKC/大小写归一，但 external horse ID 按来源
  原值精确比较；名称大小写不能绕过 ID 冲突。总数 URL 使用 Django `URLValidator`，不以
  scheme/netloc 粗判替代合法 URL。
- `IGNORED` 表达“本次建议不采用”，不是撤销既有已应用证据。模块完整度读取最近一条非
  ignored 审核状态；若不存在此前 APPLIED，或最近非 ignored 状态为 conflict/pending，仍阻断。
- 一次性研究转换必须在函数内部从实际逐场记录复算数量，真实离线 replay 样本纳入测试；不能
  依赖调用环境残留变量或仅测试冻结最终 JSON。
- 逐场结果状态必须使用 `HorseRaceResultStatus` 的正式枚举；第 4 名及以后和来源 `finished` /
  `unplaced` 统一归一为 `unplaced`。只有 `race_date_precision=exact` 的记录可满足逐场核心
  证据门禁；年份精度记录照常保存，但不能在 dry-run 中先宣称完整。
- 所有人工字段证据 URL，包括主来源、佐证来源、血统证据、逐场结果和官方总数，都必须通过
  Django `URLValidator` 的 HTTP(S) 严格校验；仅检查 scheme/netloc 或 `https://` 前缀不足以
  进入冻结审核产物。
- 自动补充来源与主来源的合并也必须做强身份检查。同 provider 只有双方 external ID 完整且
  精确一致时可直接补空；其它情况要求双方各自完整匹配马名、父名、母名、出生年份，不能因
  地区相同或马名相同放行。
- 来源总数、来源名、来源 URL 和带时区核验时间按一个原子证据组更新。新审核候选缺任一项时
  整组清空，禁止与数据库旧字段拼接。研究摘要有官方总数时优先采用官方总数，否则才采用
  备用来源总数。
- source cache 的“非空”不等于“有效”：硬字段必须是预期类型，出生年份在合理范围，精确日期
  必须为合法 ISO 日期。审核行、模块、逐场记录与数据库 `source_refs` 均执行相同 HTTP(S)
  URL 门禁。
- 父母实体反查不能把“搜索只有一个同名结果”当作强身份。自动采用只允许预期 external ID
  精确一致，或已知父名与候选完整来源身份共同命中；provider 名可规范化，external ID 是
  opaque string，只去首尾空格并精确比较。
- 已审核的历史 name-only 血统字段不直接改写旧产物。必须用 manifest 逐行绑定旧输入 SHA、
  目标马强身份、父母实体 external ID、字段值、既有审核上下文和独立出生年证据，再生成
  新版本；任一漂移即拒绝。独立出生年证据的 `reviewed_by` 不得被改写为项目负责人逐字段
  审核。历史 APPLIED profile/pedigree 模块的 URL 由最终 evaluator 再次严格校验。

## 2026-07-19 P0 马人工字段补证与美国履历数量对齐口径

- 人工字段证据保留地区元数据，但身份匹配优先使用“来源 namespace + 来源马 ID”；来源身份
  不可用时才回退到“马名 + 父名 + 母名 + 出生年份”。出生年份缺失必须拒绝，同一字段重复、
  身份不匹配或与既有非空值冲突时整项拒绝。马名归一化须跨地区生效，地区不得进入唯一身份键。
- 基础字段人工补证必须保留直接原始值、归一化值、转换规则、来源 URL、核验时间和证据说明。
  应用前缺口快照是冻结审核输入，重复执行不得覆盖或把补后状态伪装成补前状态。
- Fort George 缺失的 7 条逐场履历可由 Sporting Life/Racing Post 结果页补齐数量，但
  Equibase 只核验了 Career Starts 总数。因此美国样本在 `13/13` 或其它数量对齐后仍必须保持
  `count_aligned_records_unverified` / `count_aligned_per_record_officiality_pending`，不得升级为
  官方逐场完整。
- HRN 备用逐场履历只能在 HRN 页面与已核验候选的马名、父名、母名、出生年份四项全部存在且
  一致时接收；直接 slug、搜索结果和缓存复放遵守同一门禁。任何缺项、同名不同年份或父母冲突
  均阻断。来源证据没有 external horse ID 时，去重键必须携带完整四字段身份，不能只按赛事 ID
  跨马去重。
- 新增逐场权威性字段时，既有 `complete` 履历不能沿用旧结论；迁移必须把权威状态非
  `source_records_verified` 的旧完整记录降为 `needs_review`。同场的 `unknown` 可由正式结果
  补齐，但两个互相矛盾的正式结果不得自动合并。
- 本决定只适用于只读研究产物、审核工作簿和后续安全应用能力，不授权生产批量写入、网络抓取、
  自动发布、部署或为普通比赛强建 `RaceEvent`。

## 2026-07-18 P0 马网络批次必须绑定冻结审核 manifest

- `--allow-network` 不能只信任审核 CSV 内自报的 `reviewed/decision`，也不能只依赖 CSV 与
  manifest 彼此自洽；必须同时显式提供冻结的 `review_manifest.json` 和预先批准的 SHA-256。
  CLI expected SHA、服务端 `HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256` 与实际 manifest
  字节 SHA 必须三方一致，随后再核对 artifact 类型、确认决定、CSV basename、SHA-256、大小和
  50 行分母。所有校验在解析 manifest 和创建任何 source client 前完成。
- transport 调用一旦开始，无论返回 HTTP 响应还是在连接、TLS、读取阶段抛异常，都计为一次
  请求尝试并更新跨候选限速时间；manifest 不得把已尝试的失败请求记为 0。
- reviewed batch 的业务文件和两层 manifest 必须先在同父目录 staging 中完整生成、逐文件
  校验并 `fsync`，再原子发布最终目录；失败清理 staging，不允许留下无法安全重跑的半批 artifact。
- 该加固只提高审核输入、请求审计和 artifact 发布可靠性，不授权新的网络地区、生产写入、
  自动发布、Git 合并或部署，也不改变 P0 范围和五地区资料完整门槛。

## 2026-07-18 P0 马首批 50 匹全部纳入

- 项目负责人确认生产只读样本中的法国、中国香港、日本、英国、美国各 10 匹全部纳入首批 P0 马资料补全。
- “确认纳入”只决定批次成员，不代表身份已确认或资料已完整；`needs_identity_enrichment`、同名歧义、完整生涯和硬字段门禁继续生效。
- 真实资料写入前继续采用离线 artifact、模块人工审核和显式 commit 门禁；本决定不授权自动首次发布或生产写入。

## 2026-07-18 P0 参赛马必须先只读提取，马名本身不构成跨赛事唯一身份
## 2026-07-18：P0 参赛马先只读提取，马名不构成跨赛事唯一身份

- 赛事详情完成后，先生成只读观察、候选和五地区人工样本，再决定是否同步 P0 来源。
- 来源内 external horse ID 可跨赛事归并；跨来源归并必须完整命中马名、父名、母名和出生年份。只有马名时不得自动视为同一匹马。
- 同一观察可携带多个强身份键并按连通关系聚合；连通后指向多个 profile 或出现血统冲突时必须转人工审核。
- 预样本只验证来源和 adapter；只有人工确认并完成全部硬字段后，才能计入每地区 10 匹完整资料验收。

## 2026-07-19：coupled runner 身份与 rollback Gate D 修复边界

- 来源中的参赛号码是客观展示字段，不是 live runner 唯一身份。合法 coupled entries
  可以由不同非空 external runner ID 共享号码；系统不得改写为猜测的 `1A/1B`、合并
  马匹或因页内无关 coupled race 拒绝整页。重复 external ID 仍必须 fail-closed。
- legacy `RaceEventRunner` 的 live 身份改为 `event + nonempty external_runner_id`；
  历史空身份行不做大表猜测回填。只有 external ID 唯一命中，或在无 external ID 时
  号码/名称形成唯一匹配，才允许更新动态字段；歧义必须零写入并计数。
- P0 身份按来源 `source_key + external_runner_id` 统一关联 runner/result；相同号码不
  参与强身份归并，不同来源的相同外部 ID 也不得自动合并。legacy 新列与 source refs
  同时非空却不一致时，在任何 racecard refresh/replay 写入前 fail-closed。
- 后续准实时代码发布在切换镜像前必须生成受审、不可变、绑定完整候选 image ID 和
  filtered env SHA 的 rollback manifest。四层 policy 先以单事务进入 maintenance，
  再按 coarse restore、重新验证、event restore 的固定阶段恢复；缺 manifest、状态混合、
  tracking/claim/settings 漂移或阶段乱序时不得切换镜像或扩大公开范围。
- rollback manifest 同时冻结 current revision pointer；validator 和 policy restore
  都要求 scheduler/monitor=false、enabled regions 为空，并在行锁内、任何恢复写入前
  对 current pointer 做 CAS。pointer 漂移时保持当前恢复阶段不变，禁止重新开放 event。

## 2026-07-19：event 924 的 15 分钟 SLA 不追溯补证，下一场重新验收

- event `924` 唯一 BHA 截图观察时间早于 promotion，receipt 的后续应用时间不能替代
  promotion 后的新浏览器 probe；该场 15 分钟 SLA 继续明确记为未通过，不以数据库
  incident 已 resolved 覆盖证据缺口。
- 用户决定不为 event `924` 追溯补证，改由下一场获准公开灰度赛事在 promotion 后
  15 分钟内重新执行官方来源 probe。该决定不豁免下一场 SLA，也不授权开启 scheduler、
  扩大 allowlist 或增加其他公开赛事。
- 用户同时明确授权 event `924` 实际 disable、公开隐藏验证和 restore；演练完成后恢复
  该赛事的暂定赛果公开，客观赛果、publication、observation 和 incident 事实均保留。

## 2026-07-19：event 924 使用已存 shadow 的无网络 operator promotion

- event `924` 的首个公开灰度不重新请求 TRA，也不伪造 runner claim/checkpoint。受审
  prepare 从数据库一致快照生成 promotion、disable、restore 三份独立 CAS manifest；
  operator 路径按 `control -> tracking -> event -> source/observation/revision/items ->
  policy/allowlist` 锁序，在同一事务内复用 runner 的唯一 admission core。
- promotion 只修改 manifest 精确列出的四层 policy 和 event allowlist，物化既有
  provisional revision，创建唯一 publication/incident，并停止该 event 的后续 tracking。
  `claim_generation`、provider attempt/success/hash/failure 和 host budget 均保持不变；
  scheduler 继续 false，tracking/allowlist universe 必须仍精确为 `[924]`。
- shared global/region/source policy 可作为版本化 public cap 保留；每个 event policy
  仍是强制层。resolver 的单条和批量读取在 event policy 缺失时都 fail closed；
  initializer 可复用合法 shared v2+ cap，但新 event 只允许建立精确 `event:ID shadow
  v1`，不能因 shared cap 或 allowlist 自动公开。

## 2026-07-19：暂定公开与 BHA 人工官方复核解耦

- TRA 继续固定为 supplemental authority；完整 TRA 结果可先以明确
  `provisional_public` 展示。赛事粗状态随成功物化变为 finished，但
  `result_confirmed_at` 保持空，页面只显示“冠军 · 暂定”“尚待官方来源复核”和“补充
  来源”，绝不误标正式。
- BHA 当前路线固定为版本化 `manual_browser_only` registry，禁止自动抓取、页面后端 API
  或批量下载。registry 中的 terms evidence digest 是受审条款证据记录的摘要，不是
  BHA HTTP response body 的摘要；发布前仍须 release operator 用普通浏览器确认入口、
  条款和 route 有效。
- 人工 receipt 只持久化客观 marker、participant/position 和私有截图/打印件 SHA，不保存
  第三方页面 raw、评论、评级、赔率或逐马版权描述。服务自行比较 provisional 顺序：
  match 只关闭 incident、不把页面升级为 official；conflict 同事务执行预生成 event
  disable；unavailable 保持明确 provisional/open，记录一次告警和后续人工探针时间。
- public admission/read 必须同时验证 route contract digest 和 terms evidence digest。
  allowlist/incident 保存同一版本化摘要，manual due 为 promotion commit + 15 分钟；
  event off + 2h 后仍 open 时 verify 明确报告 overdue。

## 2026-07-18：英国 Group 级别装饰只从审核级别派生精确名称变体

- TRA 英国 G1-G3 racecard 赛事名可在基础名末尾携带 `(Group 1/2/3)`。首版只在英国且
  `RaceEvent.normalized_grade` 明确为 G1、G2、G3 时，用固定映射生成规范化
  `group 1/2/3` token；不从自由文本 `grade_text` 或来源字符串推断级别。
- 派生输入继续限于原有获准 event、active 非中文 alias、series canonical、当年有效
  series name 和 active 同年度 MajorRaceEvent 名称。名称中零 Group token 时才保留基础
  名并增加唯一同级 suffix；恰好一个、位于末尾且同级的 token 只保留一次；异级、非末尾
  或多个 token 时整条排除。非 G1-G3 与非英国赛事完全保留原有名称集合。
- 来源候选仍须通过地区、Europe/London 日期、赛场和归一化赛事名 exact membership，并且
  唯一命中。不得扩为 substring、编辑距离、任意括号删除、sponsor 删除、Roman numeral、
  `G3` 文本解析或自动数据库 alias 写入；未观察到的新格式继续 fail closed。

## 2026-07-18：赛前开赛时间只通过受控 racecard manifest 初始化

- 首期只处理调用方显式列出的英国 event ID，并只请求 TRA Free 的
  `today/tomorrow + region_codes=gb` 两条固定路由。绑定必须同时精确满足英国地区、
  `Europe/London` 当地日期、赛场名和已审核赛事名/有效别名；不使用 substring、编辑
  距离、邻近时间或人工猜测自动绑定。
- prepare 对赛事业务事实只读，但允许创建/更新共享 `RaceLiveHostBudget` 控制面以保证
  1 RPS。真实网络不持有数据库锁；最多等待并重试一次，单次等待不超过 2 秒。产物只含
  客观 racecard 字段、响应摘要和审计元数据，不保存 raw、赔率、form、评级、奖金、血统
  或评论。
- schema v2 manifest 必须与同目录 `requests.jsonl/report.json` 的 SHA 绑定。initializer
  在锁内分类 fresh/replay，以 status、local date、timezone、旧时间、`updated_at` 和
  owner manifest 做 CAS；fresh 在单事务补齐时间并建立 shadow 行，相同 manifest 精确
  replay，任何不同 manifest 或 partial 状态拒绝。schema v1 继续兼容。
- 赛前有效 claim 不调用 results API，也不把等待记为成功/失败 observation；它以专用
  `pre_off_wait` checkpoint 清 claim、保持 failure counter、推进 next poll。只有到达
  off time 才原子晋级 `awaiting_result` 后发请求，stale claim/owner mismatch 零写入。
- secret 和 artifact 只永久挂载给独立 `race_live_worker`：secret 为 ro、artifact 为
  rw。initializer 的 one-off web 只临时只读挂载获准的完整 run 目录，不读取 secret；
  web、普通 worker 和 Beat 不得永久获得 secret 或 artifact root。

## 2026-07-18 历史公开状态与抓取权限门分离

- 历史赛事是否对外展示，以逐赛事持久字段 `visibility_status=published` 且 `data_quality_status=complete` 为准；不新增一个会让未完成赛事误公开的全局展示布尔值。
- 批量公开必须使用固定 target ID 和逐目标 artifact SHA 的不可变 scope，并依次执行最新备份、dry-run、整批原子 apply、事务内逐目标校验和独立 verifier。manifest 只读取一次，同一字节同时用于 SHA 校验和 JSON 解析，避免校验与执行之间的文件漂移。
- `HISTORICAL_RACE_BACKFILL_ENABLED` 只允许在受控 apply 进程中临时为 true；网络门始终为 false。apply 完成后常驻写门、网络门和准实时 scheduler/runner 都保持关闭，已公开数据不受这些运行权限门影响。
- 纯数字历史距离只在展示层补单位：日本、中国香港、法国为米，美国及英国平地为弗隆，英国障碍为英里；已带单位的字符串保持原样。原始数据库值、来源证据、导入和验收口径不做推断性重写。
- `8,867` 个 imported 目标全部公开，只代表已完整导入层；`30,917` 条正式总账中仍有 pending、来源不可得、身份待审和 ready 目标，必须在进度报告中分开统计。

## 2026-07-18 PostgreSQL 身份写入只锁业务基表

- 身份批次需要同时读取 `RaceEvent.race_series`，但该外键可空，PostgreSQL 不允许对 `select_related` 生成的 nullable `LEFT OUTER JOIN` 整体执行 `FOR UPDATE`。
- 正式锁顺序保持为：先按主键锁定全部相关 `RaceSeries`，再按主键锁定 `HistoricalRaceEventTarget` 和 `RaceEvent` 基表；后两者使用 `select_for_update(of=("self",))`，系列仍可预取但不通过外连接重复加锁。
- 该调整不降低并发保护，也不改变审核动作、manifest 或数据语义。任何未来增加的 nullable 预取都必须保持“基表显式锁 + 关联对象独立锁”的 PostgreSQL 回归。

## 2026-07-17 AI 赛事身份初审的正式执行语义

- 接受工作簿中的 `228` 条“同意合并并关联”、`21` 条“保持独立”和 `18` 条“非同赛／忽略”作为本轮正式产品输入，但生产执行仍受精确 manifest、独立 approval、备份、dry-run 和 verifier 门禁约束。
- “合并并关联”不是删除重复系列：把审核指定的年度 `RaceEvent` 从来源系列改挂到主系列，关联正式目标，并保留来源系列及一条审核通过的 `MERGED_INTO` 沿革。这样可保留历史来源和回滚证据，避免级联破坏 slug、别名和历届赛事。
- “保持独立”和“非同赛／忽略”都写入对称的禁止自动合并标记，并保留决定类别、依据和证据。误命中允许跨地区，也允许候选赛事已经正确归属于第三个系列；执行器不得为完成拒绝决定而改动该赛事或现有目标。
- 身份决定与字段校正分离。John C. Harris Stakes 的 `surface=turf` 只作为带 before/after 和事件身份的显式 repair 应用；以后迁址、距离、场地或年份修正也不得隐含在系列合并中。
- 同一事件、同一序列或正负决定发生冲突时整批拒绝；生产基线在 prepare 与 apply 之间漂移时整批拒绝。成功 apply 后必须逐动作证明目标关联、系列归属、关系、负向锁和字段修复均与 artifact 一致。

## 2026-07-17 未来赛程与历史正式目标采用关联而非复制

- `not_due` 只表示尚未进入赛果验收期，可以关联既有公开赛程，但不得变为 `imported`；历史物化器不得为 `not_due` 创建赛事。
- 自动关联只认同一 `race_series + official year` 的唯一既有赛事，并核对年份、地区和状态。名称只用于发现同名异线或一对多冲突，不作为自动合并依据。
- 历史、当前和赛果使用三个独立分母：历史截至 2024，当前从 2025 开始，赛果只统计超过宽限期且实际举办的正式目标。展示扩展赛事不进入正式分母。
- 完整赛果必须同时满足 `finished + imported + module_statuses.results=complete + result_confirmed_at + 全部结果 is_confirmed`；只有冠军或部分赛果不得计为完整。
- 生产修复只建立已批准关联，不创建、删除或合并 `RaceEvent`，不改变可见性和详情；artifact、approval、apply、rollback 和 verifier 全部使用不可变身份与整批原子事务。
## 2026-07-16：准实时赛果采用不可变修订、持久来源权限和独立 worker

- 产品状态固定为 `scheduled -> racecard_ready -> awaiting_result -> provisional_result -> official_result -> corrected_result`，只允许审核设计中的显式边；当前不做比赛进行中的逐秒位置或沿途排名。
- `RaceEventRunner` / `RaceEventResult` 继续作为当前投影，来源事实先写 append-only observation，再形成 immutable revision/items/evidence；current 与 last-known-good pointer 受 event/kind、owner generation 和 claim CAS 约束。shadow 不物化公开赛果，晋级公开必须留下唯一 publication audit。
- official authority 只能来自持久、已审核的 source identity，调用方参数不能提权。The Racing API 只能作为 provisional/交叉验证来源，不能单独推进 official；公开只保留客观赛事事实，不复制评级、评论或第三方版权正文。
- 用户在 `2026-07-17` 明确确认相信 The Racing API 商业接口的赛果准确性。对已完成覆盖 proof、赛事/参赛马身份绑定和完整性校验的目标赛事，TRA 改为暂定赛果公开主链：`provisional_public` 开启后可在官方二次复核前直接推到前台。JRA/NAR/HKJC/BHA/France Galop/Equibase 等官方来源仍必须异步复核并决定 official/corrected；这项决定不授予 TRA official authority，也不放宽空结果、缺马、身份冲突、人工锁或条款门禁。
- 调度采用 Beat 轻量 due-selector + 独立 `race_live` queue/worker；普通 worker 固定只消费 `celery`。数据库 HostBudget 是正确性层，所有真实网络仍须通过 source permission、host 预算、有限轮询窗口和短 claim/checkpoint。
- 历史一期收口只解除“先完成历史任务”顺序门禁，不自动移交任何赛事写入权。来源 proof 必须业务 DB 零写入；进入 shadow 前仍要用精确 event allowlist/owner generation 和 SHA handoff 明确无 active historical lease/checkpoint，并经最新代码 review 和用户发布授权。
- 日本和香港正式范围按用户确认推进：香港 G1/G2/G3；日本 G1/G2/G3、JpnI/JpnII/JpnIII、JG1/JG2/JG3。JG1-3 只有在 90 天、必要时延长至 180 天的独立 proof 仍无法达标后，才可凭带 SHA、等级/赛事明细和复核日期的用户批准 artifact 暂时 deferred。

## 2026-07-16：历史覆盖分层与详情导入 receipt 成为正式门禁

- 历史期定义为截至 2024 年；2025 年及以后属于新赛事正式范围。日本、中国香港继续沿用既有官方来源和正式总账 hard 标准；英国、法国、美国历史 G1 为 hard，历史 G2/G3 为 best-effort，已有数据继续保留和补充，显式 gap 单独报告但不阻断历史 hard 验收；2025 年及以后英法美 G1-G3 属于正式展示范围。
- 已完成的 batch 和详情 package 一律复用，不因政策分层倒退或重跑。零星身份歧义、缺页和普通 G2/G3 缺口进入统一 gap/review ledger；hard 缺口只有权威取消、未举行或永久不可得证据才可记账通过。
- 正式详情导入按 source bundle/chunk 执行。bundle 必须精确覆盖冻结 package scope，并把 source bytes、cache identity、request evidence、target identity、layer、cutoff、chunk 与 approval SHA 全部写入 manifest；只保存 identity 而不带来源对象字节的 bundle 不得进入生产。
- 每个 chunk 使用独立 `HistoricalRaceDetailImportReceipt`。receipt 的 STARTED/COMPLETED/ABANDONED 三态及 supersedes 链不可覆写；业务写入和 COMPLETED 必须同事务，STARTED 只有证明零业务写后才能显式 abandon。runner owner token、全局数据库锁和 artifact/current-step/plan binding 共同构成 fencing，不能只凭 run ID 执行。
- verifier 只核 receipt 固定的本次 APPLIED candidate，不以“event 下存在某个候选”代替精确写入证明。2026 当前到期 descriptor 必须按 target 身份 materialize，强制保持草稿和不完整状态，并在任何失败时整批回滚。
- 历史公开继续关闭。代码通过最新零问题复审并生成正式不可变 artifact 后，仍须取得用户对当前固定发布内容的明确授权，才能执行生产备份、迁移、镜像切换和写入；授权后不得再改变发布内容。

## 2026-07-15：项目协作切换为 Codex 原生规划、测试先行与独立子代理审核

- 项目主流程固定为“探索 -> spec/design -> 方案审核 -> 测试先行 -> 子代理实现 -> reviewer 会话 `/review` -> 用户授权后发布”。新任务在 `docs/changes/<slug>/` 保留 `spec.md`、`design.md`、`test_cases.md`、`tasks.md` 和 `rollout.md` 五份 durable artifacts，不把聊天记录作为唯一项目记忆。
- 探索使用 Codex 原生只读调研/规划；需求不清或高风险时可使用 `grill-me-codex`。进入方案审核阶段且缺少合适原生能力时自动使用 `plan-eng-review`，无需用户再次点名。
- 自动化测试必须先于实现，并实际产生由缺失目标行为导致的 RED，再进入 GREEN/REFACTOR。仅不改变运行时行为的纯文档或纯配置整理可豁免；flags、队列/路由、权限、依赖、容器/部署顺序和数据行为配置必须测试先行。
- 任何 subagent（实现、测试、审核、调研或其他用途）运行期间，直到全部 active subagent 结束，主代理只能继续派新 subagent 或等待/接收结果；不得读/改/测/调研、向其他任务发消息或处理无关工作。写密集任务默认串行，并行任务必须没有文件边界重叠。实现代理不提交、不发布，只返回摘要、路径、测试证据和风险。
- 同一需求首次方案审核与首次代码审核各建立 reviewer 会话；首次代码 reviewer 必须未参与实现并实际调用内层只读 Codex 原生 review。后续方案复审和代码复审分别复用各自原 reviewer 的同一会话与上下文；只有会话不可恢复时才新建，并记录原因、上轮 findings 与已知问题交接。
- 复审严格限于上轮具体漏洞、对应修复及直接触及路径。只有该漏洞的直接 P0/P1 回归可新增阻塞；其他新发现记录为后续建议后结束，禁止扩展为无关 P2/P3 加固或通用发布协议。completed/exit 0 仅表示原生 review 执行成功。
- 发布授权只对当前任务有效，必须在最新成功 review 后由用户明确给出。成功 review 记录完整 fingerprint、approved parent 与 `content_manifest_sha256`；授权后 staging 前完整 fingerprint 必须不变。显式 stage 全部受审改动后允许 status/index 表示变化，但 HEAD 必须仍为 approved parent、无 unstaged/untracked/conflict，且 index content hash 必须等于受审值；漏 stage、夹带或内容变化均停止。不另引入 receipt 或 CAS 发布协议。
- 部署后 evidence-only closure 的精确文件 allowlist 只有 current state、project status、deploy runbook、必要发布 decisions 和本任务 release report；仅追加已发生证据并复用同一需求既有代码 reviewer 会话审核。代码、测试、配置、迁移、spec、tasks、skills、agents 均禁入；超出集合或改变行为/治理时返回完整 review + 新授权。
- 活跃 `grill-me-codex` 仅是一问一答的 Codex 原生只读探索 skill：先查仓库、每题给推荐答案与理由、用户可随时停止；不写 PLAN/spec/design，不启动其他模型或 nested review。原 Claude 双阶段版本完整归档，仅作恢复依据。
- `旧规格流程-explore`、`旧规格流程-propose`、`旧规格流程-apply-change`、`旧规格流程-archive-change`、`旧规格流程-sync-specs` 及 旧规格流程 workflow-spine 停用。既有 旧规格流程 artifacts 原地保留为历史/在途上下文，旧规格流程 CLI、phase 和 journal 不再是新流程门禁。
- `2026-07-15` 已在途任务先完成当前原子操作并停在安全检查点，再按“读取现存规格 -> 补齐/更新 test_cases -> 对尚未实现行为取得真实 RED -> subagent 实现 -> 复用同一需求既有 reviewer 会话（没有时首次建立）”迁移。不得伪造已经错过的历史 RED，也不得重做已完成生产动作；旧文档里的 旧规格流程 “下一步”自此仅为历史记录，不再是现行指令。
- 本迁移由用户直接要求立即建立规则；最早一批编辑发生时新流程及 `docs/changes/codex-native-workflow-migration/` 尚不存在，因此不追溯伪称前置 artifacts 已完成。目录建立后的 helper 强化必须保留真实 RED/GREEN 证据。
- `codex-native-workflow-migration` 当前尚未发布；其他现有 worktree 不批量改写 tracked
  治理文件，以免破坏在途工作，只在安全检查点通过 handoff/rebase/main 同步。base/commit
  审核只接受 clean tree；未提交发布前改动统一走 `--uncommitted`。

## 2026-07-15：重型历史解析留在本地，详情匹配必须先消除距离歧义

- France Galop 年度 PDF、逐场详情扫描及其他高内存解析只在本地固定镜像执行；生产 runner 只接收已缓存、已校验的轻量 artifact 做 verifier/apply。生产主机发生资源异常或 SSH 不可达时，不在未知状态下重启、重建或继续写入。
- `m` 必须结合地区和值域解释：法港日以及 `>=100m` 为 metres；英美短值如 `3m` 为 miles。不能把英国 `3m` 当 3 metres，也不能把美国 `1600m` 当 1600 miles。详情匹配在名称评分前优先使用兼容距离缩小候选，并继续保留 URL 一对一和复用拒绝门禁。
- 年度目录标题可能包含赞助名、注册名或历史胜马文本。详情解析应同时使用审核后的系列 alias、年度目录名和总账原始名，但只有日期、场地、距离及唯一来源 URL 共同通过时才接受；名称相似不能覆盖距离冲突。
- 地区内并发分片可以使用共享 host interval artifact：请求次数仍按 shard 独立记账，所有 worker 通过同一 `fcntl` 锁共享上次启动时间。共享文件必须位于共同受控挂载根；正式 runner 在尚未支持父级共享挂载前必须清除该环境变量，不能从宿主继承任意路径。

## 2026-07-15：正式历史批次按冻结输入、证据 gap 和只读验收推进

- batch006 及后续正式抓取必须由 tracked plan builder 生成结构化 runner plan；selection、approval、batch manifest、descriptor、image revision 和 tool SHA 均为不可变身份，typed recipe 必须从实际 CSV/JSONL 内容证明与 shard scope 精确一致，禁止手写任意 argv 或使用 `tmp/` 工具。
- complete 与 gap 共同构成 selection 的精确分母。来源冲突、无效或暂不可得可以进入带证据的 gap 并继续其他目标；人工补证的 target SHA 或旧值漂移只把该目标转为 conflict gap。无证据遗漏、complete/gap 重叠、来源缓存漂移和结构不合法的补证仍整体 fail closed。零星歧义累计到最终统一审核，不中断整批正式总账收集。
- 数据库 verifier 检查冻结候选身份对写后 target/event 状态的结果，不把写前 target hash 与合法写后的当前 target hash 机械比较。PostgreSQL verifier 必须在事务第一阶段设置 READ ONLY，任何完整或 gap target 的赛事均不得为 published；同模块历史 APPLIED candidate 允许保留，但必须按 `applied_at/id` 核验最新一条。
- 地区距离单位保留来源原文及 provenance；英美 `m/f/y`、法港日公制等不在合并层强制换算。只有来源明确给出单位时才补单位，不能凭地区猜测。

## 2026-07-15：新闻重跑发布与未知马名门禁

1. 7 月 13 日起新闻按创建时间冻结清单重跑；重复稿不重复处理，可处理稿必须有明确成功、人工复核或忽略终态，不能以“命令执行过”代替逐篇对账。
2. 来源框架、编辑注、与正文无关的导航链接和博彩推广必须在翻译前清除；赔率以及作为赛事标题、马主等专名组成部分的博彩公司名称允许保留。
3. 完整未知马名必须原样保护，不能按术语子串拆译；普通词、人物和机构只有在上下文支持时才能作为马匹实体。未知马名占位出现多次继续阻断发布，省略主语由有界重试改写成“该马/其”，不得降低 `validate_rewrite()` 门槛。
4. 日文普通词必须正常翻译；产驹、追切时间、赛后访谈和出马表采用确定性格式。术语库补充社台与北方马公园的日英中别名。
5. 存量重新发布不主动补发 QQ。冻结清单中 `8337/8413/8424/8425/8450` 在早期中断窗口产生 5 条 delivery；最终排空已在队列中的自然任务时，`8429` 又产生 1 条合规 delivery，六条均保留审计。本次受控发布的 47 篇 Sponichi 稿新增 QQ delivery 仍为 0。
6. 新闻上线不解除 historical runner 的独立资源门禁。生产磁盘低于 5 GiB 时 batch006 保持关闭，即使新闻健康检查和队列均已恢复正常。

## 2026-07-14：Gold 合格不能覆盖生产差异人工复核失败

- Gold 的 `qualified=true` 只证明冻结样本达到覆盖和指标门槛，不等于当前 72 小时生产文章可安全上线。只要全部主地区变化或 `needs_review` 中存在明确错标，本轮仍为 no-go，必须修规则、补回归并重新生成完整 run。
- 主地区遵循 precision 优先：赛事或赛场的明确证据高于参赛马来源；ASCII 单词实体、嵌套在机构全名内的赛事词和正文历史背景不得轻易夺取主地区。无法可靠裁决时允许漏标或进入 `needs_review`，不得为提高 recall 制造错标。
- 日本来源报道当前日本成就、仅把海外赛事作为未来梦想时，主地区保持日本，海外目标进入相关地区。正文首段赛事只在标题没有可靠赛事、且首段仅出现一个非歧义赛事地区时补充主地区证据。
- 每次规则修复后必须重跑完整 72 小时 `all_articles`，人工检查全部主地区变化和全部 `needs_review`；不能复用修复前的 Gold 指标或审核结论批准 Shadow。

## 2026-07-14：全量归属审计不再隐式执行发布门禁，Gold 漂移采用保守续签

- `--scope all_articles` 用于验证归属差异，不用于恢复术语门禁；默认不得逐篇调用 `validate_rewrite()`。确需同时复核门禁时必须显式传 `--include-gate-validation`，默认 `gate_candidates` 仍保持原门禁补跑语义。
- 持久 dry-run 是审计真相。报告进程中断后应使用同一 run ID 与 manifest 导出，不重复推断；导出必须验证 manifest 和 candidate fingerprint，原子写新文件并拒绝覆盖既有证据。文章缺失/漂移必须进入必审清单，不能拿旧归属结果校验已变化正文。
- Gold 输入 SHA 只可在原审核身份、来源 URL、规范化标题、正文长度/语义以及当前推断与人工结论均稳定时自动刷新。重复 key/article、正文异常缩短、标题变化或推断变化均保持漂移，不以“凑足 150 条”为由放宽。
- 相关地区质量门槛只评估五个实际运营频道；`other` 可保存为证据，但不计入五频道 precision/recall。低置信度主地区变化只有在同时违背人工期望时才算无依据变化，避免把 Gold 明确认可的变化反向计为错误。

## 2026-07-14：historical runner 资源门禁必须由宿主与应用双层强制

- crawl phase 的 `RACE_EVENT_CRAWL_*` 不能直接继承 plan 或宿主环境。runner 父进程必须用批准 settings 覆盖子进程，并让同一 run 的所有 step 共用 artifact 根目录下的请求账本和 source-cache manifest。
- 请求预算必须为 `1..250`，source cache 必须为 `1..2147483648` bytes，请求间隔至少 1 秒，磁盘底线不得低于 `5368709120` bytes。`0` 不得解释为无限；直接调用 Django 管理命令也必须执行同一边界校验。
- 宿主脚本在 `docker create` 前检查 phase env 数值和 artifact 文件系统实时可用空间；Django 服务在取得数据库租约前重复检查容器内文件系统。任一层失败都不得创建 runner、取得租约或执行网络 step。
- 每个 crawl step 后将请求账本与 cache manifest 的存在状态、大小和 SHA 保存为 checkpoint 顶层身份；下一 step、resume 和 completed 幂等检查都必须重新核验。资源账本漂移一律 blocked，不能把删除后的空账本视作新额度。
- crawl 取得双锁后必须在首个 step 前保存资源基线；任何已启动 step 的失败收尾必须在释放锁前刷新资源身份，无法收尾的强杀恢复由基线漂移 fail closed。
- 生产 `/app/runtime/tools` 不再接受“镜像内任意 SHA 匹配脚本”，只允许显式赛事发现、缓存、详情解析、打包、导出和 smoke 工具。新增历史工具必须更新白名单、测试和固定镜像；术语或其他直接联网脚本不得借 crawl egress 绕过赛事预算。
- `orchestrate_race_event_crawl` 内部的 AdapterRunner 不得重新生成自己的请求账本/cache 路径覆盖 runner 父级。父级路径原样继承；请求数/cache bytes 使用父子较小值，请求间隔/磁盘底线使用父子较大值。
- 生产磁盘不足时只能清理可再生构建上下文/镜像或扩容，不能临时降低 5 GiB 底线。第一版 runner smoke 后发现这一旁路时，batch006 仍未发出真实网络请求，因此按本决策先修补、重新 review/部署/smoke，再开始正式抓取。

## 2026-07-14：batch006 起扩大标准批次并使用独立 historical runner

- batch005 继续完整遵守旧标准，即单地区最多 50 场；只有 batch005 全部写入和验收结束后，batch006 及后续标准批次才把单地区上限提高到 250 场。
- 扩容不能只修改一个命令行默认值。选择器、地区进度护栏、artifact 摘要、测试和运行手册必须使用同一口径；既有排除 snapshot、100 场地区领先护栏和待审 gap 记账规则继续有效，除非后续产品审核另行修改。
- 后续历史批次使用独立 runner 容器，固定到已验收镜像 revision，显式挂载 runtime artifact，并设置资源限制。普通 web/worker/beat 部署不得重建、停止或接管 runner，也不得借此重建 DB、Redis 或共享网络。
- runner 必须具有数据库级与应用级互斥锁、心跳、可恢复 checkpoint 和失联接管门禁；迁移前必须安全暂停。抓取阶段只允许 `network=true / write=false`，落库阶段只允许 `network=false / write=true`，任何阶段都不能同时获得两种权限。
- 该能力在当时必须走 旧规格流程、工程评审、完整测试、实现和反复代码 review，并在部署验收通过后才允许启动 batch006；其中技术验收事实继续有效，但流程入口已由本文件顶部 `2026-07-15` 新流程取代。历史公开展示继续保持关闭。
- 实现采用三张独立控制表、PostgreSQL 租约与 `fcntl` 双锁；过期租约不能被普通启动覆盖。接管必须同时证明旧容器不存在、`pg_stat_activity` 无对应 `application_name`、runtime/DB checkpoint 一致，并写入操作者与原因。
- owner token 原文只能位于 artifact 外的 0600 文件；resume/takeover 也不得通过命令行传 token。crawl control role 对 event 表只允许 append，不能删除审计事件，更不能读取或写入赛事、新闻、术语等业务表。
- 普通部署首次引入 `0031` 时只能显式设置一次 initial-install 门禁；后续迁移必须让 active runner 安全暂停。数据库、Redis 和共享网络只允许由独立 bootstrap 首次创建，普通 deploy/rollback 永远不隐式补建。
- 子进程 stdout/stderr 不通过无界内存 pipe 累积，也不把未脱敏原文写入 artifact；先写入 runner 容器受限 `/tmp` tmpfs，结束后统一脱敏并原子写正式日志。stale takeover 只能核对 artifact 根目录固定 `runner-state.json`，不接受任意替代文件。
- crawl runner 不写旧的业务 `TaskExecutionLog`，网络步骤审计统一进入 append-only `HistoricalBatchRunEvent`；普通非 runner 管理命令仍保留原任务日志。这样 control role 无需获得任何业务表权限。
- stale takeover 必须从宿主执行 `historical_runner.sh takeover`：脚本先通过 Docker 实际确认固定名称旧容器不存在，再用同 revision、同 phase 数据库凭据、internal-only 网络和只读 artifact 挂载执行接管探针。不得直接把管理命令的 `--container-absent` 当成人工声明使用。
## 2026-07-14：归属生产验收必须显式使用全量近期文章范围

- `reprocess_multiregion_attribution_gates` 的默认 `gate_candidates` 范围继续只用于术语门禁候选恢复，保持现有运维兼容；它不能作为多地区归属生产资格证据。
- 生产 72 小时验收必须显式使用 `--scope all_articles` 且不传 `--limit`。范围包含已发布文章，排除 duplicate/rejected/withdrawn/archived/ignored；任何 `scope_complete=false` 的输出均不得用于 go/no-go。
- 人工清单必须覆盖全部主地区变化、全部 `needs_review` 和全部人工锁定跳过，再从其余文章按五个运营地区做内容指纹确定性抽样。人工锁定文章在 dry-run manifest 中必须保留原主地区与相关地区。
- `all_articles` run 的 commit 只应用已审核的主/相关地区与归属审计字段，不重写门禁状态、不设置 `ranked_revived_at`、不改变 published 身份或 QQ 交付；默认 `gate_candidates` commit 才保留原来的门禁恢复语义。
- `all_articles` run 若因显式 `--limit` 产生 `scope_complete=false`，即使 Gold 指标合格也必须拒绝 commit；人工清单行保留标题、来源 URL、来源站点和发布时间，避免脱离原文只审核数字 ID。
- `scope/scope_complete/commit_policy` 必须作为 `_run_contract` 写入 manifest 已绑定的 metrics；commit 不得信任可独立修改的 selectors 来决定是否重跑门禁。旧 run 仅为兼容读取 selectors，新全量 run 即使 selectors 后续漂移也仍按锁定契约执行。

## 2026-07-14：单审 Gold Set 可在完整门槛和 Shadow 验收后支持 Enforce

- `provisional_single_review` 继续作为审核来源和审计事实保留，但不再无条件判定 no-go，也不得伪造 reviewer B 或裁决状态。
- 单审与双审使用同一首发覆盖和质量门槛：有效样本至少 150 条、五个运营地区各至少 10 条、跨地区至少 20 条；总体/分地区准确率、相关地区 precision、无依据变化、过度扩散、锁定覆盖和 PostgreSQL 性能门槛不降低。相关地区 recall 首发门槛从 90% 调整为 50%，因为漏标通常不可感知，而错标不可接受；多人审核存在冲突时仍必须裁决。
- Gold Set 达标只允许进入 shadow，不能直接 enforce。shadow 必须至少观察 24 小时，并人工检查全部主地区变化和全部 `needs_review`；通过后仅对新文章 enforce，相关地区查询仍独立关闭。
- Gold Set 是持续增长的数据产品，不是一次性验收文件。新增来源、规则改版、shadow 误判和运营争议样本均应进入新版本并保留版本间指标变化。
- 当前 159 条单审集合的最少运营地区样本为法国 11 条、跨地区 24 条；主地区准确率 98.11%、相关 precision 100%、recall 54.84%、过度扩散 0%，覆盖与质量门槛均通过，因此允许进入 shadow。该结论不等于允许直接 enforce。
- recall 线上下降只告警并暂停扩大灰度，不自动关闭当前功能；precision 跌破 95%、明显错标或过度扩散超过 1% 时，才按相关地区查询 -> 归属 enforce 的顺序回退。
- 250 篇真实规模 PostgreSQL 测试必须绑定实际 `NewsSource`。本次先发现 `254 SQL` 的来源懒加载 N+1，修复后五轮稳定为 `5 SQL / 1.66–2.14s / 约49 MiB`；以后不得使用无来源空 fixture 掩盖批处理查询问题。

## 2026-07-14：生产只读检查不得使用 `docker compose run`

- 生产环境查看管理命令帮助、Django 状态或只读数据时，只允许使用已存在容器的 `docker exec`；不得使用 `docker compose run`，因为 Compose 仍可能按依赖图重建 DB/Redis，即使目标命令本身只读。
- 如果确实需要一次性容器，必须先检查 Compose 依赖、使用显式 `--no-deps`，并在单一生产协调线程批准后执行；默认仍优先使用现有 `web` 容器。
- 当同一表出现两个不同索引的结构/唯一性异常时，不按单索引修复结束：应暂停 beat、停止 worker 消费、排空 active、生成并校验完整备份、顺序扫描确认真实重复、合并重复记录及外键审计，再对整表执行并发重建和 `VACUUM ANALYZE`。
- 生产身份重复合并必须保留事故前最早的权威文章，迁移快照、翻译运行、自动化日志和窗口决策，写入操作日志后才删除冗余行；不得只删除“看起来较新”的文章而丢失审计关系。
## 2026-07-14：日文固定译词必须以字段级占位符守恒并在边界恢复

- 日文普通赛马词不依赖模型自由选同义词；已接受的种子术语在标题/正文按绝对 span 转为字段级占位符，模型必须逐出现次原样返回，最终由系统恢复术语库目标。遗漏、重复、跨字段、新造或畸形占位符一律重试并最终显式失败。
- 完整未知马名和结构化格式优先于内部短术语。拍卖产驹、追切、赛后访谈和出马表采用窄上下文格式计划；未知母马、父马和出马表马名保留完整原文，不做全局组件替换。
- 模型可能在占位符旁自行补写同一中文词。恢复阶段只移除两个及以上字符的明确后缀/前缀重叠，以及 `公开级 + 级别` 的受控单字重叠；其他单字重叠保留，避免把“拍卖会会场”错误缩成“拍卖会场”。
- 已发布文章重译若连续被完整性或占位符门禁拒绝，不得放宽门禁或保存失败稿。若同一原文已有通过全部门禁的成功 run，可在精确计数、公开身份与 QQ 断言下只修复确定性后处理重复，并写入 `OperationLog`；失败 run 保留审计但不得覆盖公开稿。

## 2026-07-14：国际新闻正文清理必须按可信容器与语义噪声 fail closed

- 国际来源正文选择器未命中时必须返回显式失败，不得回退页面 `body`；站点 DOM 漂移应在后台暴露，而不是把导航、推荐、社交和页脚误当新闻发布。
- 与新闻事实无关的独立 URL、`click here` 行动句、编辑注、完整赛果/活动跳转、责任博彩和博彩推广必须清理。博彩公司名称只有出现在赛事标题、马主等专名或赔率事实中才保留，不能用公司名本身作为整段删除条件。
- 历史公开文的修复必须使用已保存 HTML 离线重解析、显式文章 ID、默认 dry-run、事务 commit 和操作日志；强制重译只能更新译文，必须保持公开状态、原发布时间和 QQ 幂等状态。
- 翻译完整性不能只按英中字符数和标点数判断。日期表、出马表等结构化内容可用非空行覆盖证明完整，但阈值必须向上取整，且尾句完整性和显式列表标记门禁继续生效。

## 2026-07-14：官方来源不提供马号时允许留空，但必须显式记账

- `horse_number` 的完整性以来源实际提供字段为准，不能为了满足统一格式而按结果顺序伪造号码。官方结果文件没有马号时，可保留空值，但马名、骑手、名次和来源缓存身份仍必须完整。
- batch004 的 NSA `target_id=74171` 属于此例：官方 PDF 提供 8 匹出马和 7 条正式赛果，但不提供马号。导入器允许多个空马号，同时继续禁止同一赛事的非空马号重复。
- 这类来源格式差异不阻断其他正式总账数据收集；统一进入最终产品审核清单，后续若取得权威号码来源，再通过独立候选补充，不能回写推测值。

## 2026-07-13：原定场次弃赛不等于年度赛事取消

- 年度赛事身份判断必须继续追踪改期、移师和补赛。原定日期或场地页面标记 `ABANDONED`，只能证明该场次未按原计划举行；同届赛事在其他日期或场地正式跑完时，target 仍为 `held`。
- 2025 Hampton Novices' Chase 以 `2025-01-19 / Windsor / 3m53y` 的正式结果为准，Warwick 原定场次只保留为变更证据。以后遇到相同情形，必须先排查改期和移师，不能直接改成 `cancelled`。

## 2026-07-13：逐届距离必须保留批准来源的原单位

- 不同地区和年代使用公制、mile/furlong/yard 等不同单位；总账裸数字不能作为最终展示值，也不能按地区猜测单位。
- 日期 apply 后必须核对逐届来源距离并通过权威字段门禁写回原文。字段变化会改变 target SHA，后续详情来源和最终候选必须依次重新导出、重新打包。

## 2026-07-14：地区进度护栏只比较仍有可抓目标的地区

- 同一年代带的 100 场领先上限用于同步仍在抓取的地区，不是要求五地区拥有相同赛事总量；正式总账容量较小的地区抓空后必须退出比较，否则较大地区永远无法完成。
- “仍未完成”以本批选择后是否还有未排除、可选的 pending held/cancelled due 目标判断。任一未完成地区即使本批未被手工选中，也仍参与比较；只剩一个未完成地区时没有比较对象，不因护栏拒绝。
- selection snapshot 显式排除的歧义或缺口仍是 pending，继续计入总账分母、remaining pending 和最终统一审核清单；但它们不属于当前可抓集合，不能单独冻结其他地区。
- 批次选择和 artifact 写入前各自重算可抓分母并执行护栏，summary 保存可抓地区集合。该变更不修改 expectation/resolution、不自动解决歧义、不开放历史展示。

## 2026-07-13：年度日历的竞赛类型不得覆盖赛道表面

- `flat / jumps` 是竞赛类型证据，不等同于 `turf / dirt / synthetic` 赛道表面；年度日历未明确给出表面时，保留总帐已经审核的 `surface`。
- Newcastle 的 Hoppings Stakes 不得因为进入英国平地赛日历就被改为 turf；障碍赛也不得仅因实际在草地举行就把模型中的 `jumps` 类型改写为 turf。
- 日期发现 artifact 只处理日期、直接来源和带单位距离；surface 或场地的实质修订继续走独立字段候选、证据 SHA、dry-run 和审核门禁。

## 2026-07-13：新增详情来源必须在三层白名单保持一致

- 一个新来源只有同时登记到直接 URL 的 host/authority/region 校验、补充详情来源 artifact 服务和最终详情 packager 后，才算可用于生产；任一层缺失都应 fail closed。
- NAR `keiba.go.jp` 定义为日本官方来源；Zone-Turf 定义为法国第三方数据库来源。来源缓存必须逐文件绑定原始 URL、大小和 SHA-256，不能把缓存内容配给后来合成的 URL。
- ZEturf 发现器必须保存实际下载并缓存的 URL。即使页面内容匹配另一目标，也不得按命中目标重新合成 URL，否则来源 manifest 与候选身份会分离。

## 2026-07-13：已交代 gap 用历史选样证据排除，不改产品状态

- 上一批已经进入 gap ledger、但仍应保持 pending 的目标，不得反复占用后续标准批次的地区配额；生成新批次时显式传入既有不可变 selection snapshot，在地区 limit 前按 target ID 排除。
- 排除 snapshot 必须自证 schema、inventory SHA、内部 snapshot SHA、target 数量和唯一性，并与当前总账的稳定 series/year/region/inventory 身份一致；当前 target SHA 可因成功导入或权威字段更新而变化，不作为历史排除证据失效条件。
- 新 artifact 必须复制输入 snapshot 原字节，以固定单文件 artifact 键绑定路径、大小和 SHA-256。多份 snapshot 可重复输入，target ID 去重；最终 selection 与排除集合相交时 fail closed。
- 该入口只改变选样，不修改 expectation、resolution、event 或来源证据。被排除的 pending gap 继续留在 available/remaining 分母，直到另行完成产品审核、补源或永久不可得审批。

## 2026-07-13：详情来源审批与最终数据导入必须使用不同形态的候选

- `manage_historical_race_detail_sources` 必须读取仍带 `year / slug` 的原始解析候选，用于按年度赛事建立来源审批 artifact；不得把只含 target 绑定信息的最终导入包反向当作来源发现输入。
- 来源 artifact apply 会把批准证据写入 target 与 RaceEvent，并改变 target SHA。因此来源 apply 后必须重新导出 event input，再运行 `package_historical_race_detail_candidates.py` 生成新的最终导入包。
- `import_historical_race_event_candidates` 只接受这个写后重打包文件，并同时锁定文件 SHA-256、target SHA、inventory artifact SHA、来源 URL 和 source-cache identity。任何来源审批后的旧包都应因 target SHA 漂移而拒绝。
- 该分层只改变技术证据链，不改变产品语义：`ABANDONED`、`not run`、`cancelled`、`not_held` 仍按各自审核规则处理，不能因详情来源存在就自动修改总账。

## 2026-07-13：年度来源的 `not run` 只能生成审核证据，不自动改总账

- TOBA 等权威年度表若将某赛事明确标为 `not run`，来源发现工具应输出结构化 `source_reports_not_run`，保留来源赛事名、场地和状态。
- 该证据说明当前 `held` 预期可能有误，但来源发现阶段不得自行把 target 改为 `not_held`，也不得生成伪结果 URL、RaceEvent 或永久不可得结论。
- expectation 状态变化属于产品总账决策，需经审核后通过受控 artifact 更新；未批准前目标保持 pending，其他无关目标可继续抓取。
- TOBA 单场结果 URL 必须一对一绑定 target；同一 URL 若匹配多个系列，所有冲突候选均 fail closed。名称消歧中的 `Fillies`、`Turf`、`Sprint` 按完整单词判断，避免短名称包含或赞助词子串导致串场。

## 2026-07-13：法国新鲜度与多地区归属工程评审决策

- 归属采用 `MULTIREGION_ATTRIBUTION_MODE=off|shadow|enforce` 单一模式；旧布尔变量只作兼容映射，相关地区查询仍使用独立开关。
- 新增结构化文章状态字段与 `MultiregionAttributionRun/Lock`；不得复用外键指向术语门禁 run 的 `TermGateReprocessLock`。
- shadow 审计与 applied 审计分命名空间保存；归属 commit 必须绑定成功 dry-run 和 manifest，支持逐篇事务、断点续跑和重复提交幂等。
- gold set 使用真实生产输入快照；本段原双审及 `250/40/50` 硬门槛已由 2026-07-14 决策修订为“单审允许、多人冲突须裁决、首发覆盖 `150/10/20`”，任一地区样本或准确率不足仍为 no-go。
- 批量归属必须预加载术语、别名和赛事证据；250 篇 PostgreSQL 验收目标为 SQL `<=30`、耗时 `<=30s`、RSS 增量 `<=256 MiB`。
- 部署后默认不启用：先 off 部署，再 shadow 验证，再仅新文章 enforce，观察至少 24 小时后才可逐步开放相关地区查询、近期回填和正式群。
- 本地实现完成不等于生产资格通过。测试 fixture 和 CSV 模板不能替代真实生产输入的有效审核；现有 159 条已达到首发覆盖与质量门槛，但未完成生产 dry-run 和 shadow 验收时，change 仍保持 `implementing`，不得直接 enforce。
- 法国时间修复、翻译失败重试和历史归属回填均采用“先 dry-run 生成持久 run/manifest，再人工审核并锁定 commit”的路径；不得通过启动服务或迁移隐式修改旧文章、公开状态或 QQ 交付。
- manifest 必须同时绑定候选结果、规则版本、术语/配置/gold 快照和质量指标；commit 直接应用审核结果，不重新推断，并将归属写入、门禁重校验和 cursor 更新纳入逐篇原子流程。
- `new_articles` 及后续阶段的自然流只对新入库文章 enforce，旧文章重复抓取仅 shadow；历史修改必须走 manifest。`web_test_groups/recent_backfill` 阶段只有显式标记 `multiregion_test_enabled` 的 QQ 群读取相关地区，`formal_groups` 后才扩大到正式群。
- 翻译终态失败邮件默认启用并发送至用户确认的 `754652181@qq.com`；自动 selector 先原子 claim 再入队，避免 worker 积压时重复塞入同一篇文章。

## 2026-07-12：门禁补跑不得复活来源日期可信度不足的历史库存

- 英文术语门禁重处理只负责重新判断术语上下文，不改变来源新鲜度标准；候选仍必须满足其抓取时适用的来源日期和新鲜度要求。
- `NewsSource#21 / CrawlJob#9408` 创建于 TDN France 真实日期修复上线前，批内 `published_at` 为错误兜底时间，因此整批 `20` 篇视为不可信库存并进入 `withdrawn` 终态，不再参与后续自动补跑。
- 本次先发布后发现的 5 篇旧文立即撤回；QQ 未产生交付。其余地区 19 篇保留公开。
- 常驻生产仍使用 `shadow`；只有 manifest 锁定的单次 commit 可临时以 `enforce` 重校验，不能据此提前切换全局模式。

## 为什么英文术语上下文门禁先进入 shadow 而不直接 enforce

术语库中保留 `Exactly / Brilliant / Title` 这类合法单词型马名是正确的，问题应在文章命中级上下文中解决，而不是删除术语。新分类器按每次实际出现区分 `proper_noun / common_word / uncertain`，真实赛事、骑师、练马师和强实体证据继续保守保护；标题、导语 uncertain 仍阻断，背景 uncertain 只 warning。

生产固定 100 篇基准已证明重处理性能达标，但真实四地区小批中仍存在大量 uncertain，且本批 `common_word` 直接命中样本不足以单独证明零误放。因此当前只启用 `shadow`：计算和记录新旧差异，旧门禁仍决定文章状态。至少观察 24 小时并抽检普通词、真实单词型马名和 uncertain 后，才允许切 `enforce`；历史文章只能引用已审核 run ID 与 manifest commit，commit 只恢复发布候选，不直接公开或创建 QQ delivery。

性能门槛不通过时不得通过提高 60 秒或 256 MiB 上限掩盖问题。本次生产基准曾暴露全地区 26,713 条术语、37 万英文 alias n-gram key 和完整重复语料/文章字段加载，最终通过地区预筛、相关快照、字段投影和英文 alias 一次预取消除无效 CPU/内存，保留既定正确性边界。

## 为什么 P0 基础代码上线后不立即执行全量来源同步

生产 dry-run 显示当前范围包含 `21596` 条有译名马术语、`992` 场重点赛事，赛事证据已有 runner `5096` 条、result `4572` 条。直接执行 `p0_horse_profiles --sync-sources --commit` 会一次写入全量术语来源并分析数千条参赛身份，超出已经确认的“日本、中国香港、英国、法国、美国各先抽 10 匹人工跑通”范围。

因此 P0 基础代码和迁移可以先上线，但来源同步 commit 必须继续服从样本优先：先完成五地区 adapter、统一 artifact、每地区 10 匹 dry-run 和人工审核，再选择受控写入方式。上线本身不得隐式启用网络补全、全量来源写入或自动首次发布；当前生产保持 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`，`HorseP0Source` 为空属于有意状态，不是部署失败。
## 为什么美国历史平地赛优先使用Equibase单场standard PDF

Equibase旧 `eqbPDFChartPlus.cfm` 和整日PDF索引可能返回防护HTML或失效链接，但同一官方体系的单场standard PDF仍可稳定提供完整实际出走、马号、闸位、骑手、练马师、负磅和官方赛果。因此美国历史平地赛继续以Equibase为主源，日期发现阶段直接绑定可验证的单场PDF，不把HTTP 200防护页或404整日索引视为成功证据。

详情生成必须使用target在日期apply时记录的唯一source-cache manifest，并逐文件匹配批准URL、大小和SHA-256；随后再复核PDF页眉日期、赛场和场次。每次只允许一个已批准manifest，禁止把批准manifest与其他manifest中的PDF混用。`1a`等联合投注编号独立保留，runners按马号排序，results按官方完赛顺序保存。

## 为什么 materialize 后发现的详情页使用独立补充来源 artifact

日期发现 artifact 已经批准并把目标 materialize 后，后续可能找到更完整的专业数据库详情页。此时重做原日期 artifact 会破坏既有审批身份，也会让日期证据与详情正文混在一起。因此补充详情页使用独立 detail-source artifact：绑定当前 target SHA、inventory SHA、provider/authority、直接 URL，并复制批准的 source-cache 字节；apply 只向 target 与 RaceEvent 的 `detail_discovery.approved_detail_sources` 追加证据，不改变赛事身份、ready 状态或 draft 可见性。

详情打包必须同时匹配批准 capture 的 `source_url / size / SHA-256`。即使 URL 相同，只要缓存正文不同也必须拒绝，避免网站后来更新的页面无声替代人工批准版本。提交时同时锁定 target 与 RaceEvent，防止并发来源维护互相覆盖。

## 为什么赛事详情来源必须按地区分层，并区分赛前声明与实际出走

不同地区的历史赛果权威入口和保存深度不同，不能使用一个第三方站点覆盖所有地区。日本采用 JRA 主源、netkeiba 历史补源和 JBIS 血统/沿革补源；中国香港采用 HKJC 官方 Race Card / Results；英国采用 Racing Post Full Result 作为历史实际出走与赛果主源，Sky Sports Racecard 补赛前页面，BHA 只承担 2014 年后官方校验；法国采用 France Galop 主源、PMU 补源；美国采用 Equibase historical charts 主源，BRISnet、DRF、BloodHorse 交叉校验，美国障碍赛事补用 NSA。

数据层必须分别保存 `declared_runners_source`、`actual_runners_source`、`non_runner_source` 和 `result_source`。Full Result 或 chart 中的 runners 只证明实际出走，不能冒充赛前声明出马表；找不到历史 racecard 时应明确标记赛前表缺失，而不是从赛果反推。所有来源还需保留原始 URL、抓取时间、来源权威级别和解析版本。

## 为什么同名赛事审核结论要生成新总账而不覆盖原始目录

TJCIS 的简写、赞助名和场地/距离字段会把同名不同赛、迁场沿革及年度改场混在一起。`2026-07-13` 的人工审核把 `102` 个临时 Key 归入 `58` 条正式赛事线，并修正京都雌马、Bristol届次、Louisville 2008、Keeneland First Lady年度名和NYRA Matron 2018等已确认异常。为保留可追溯性，原始 v10 总账保持不变，审核结果写入独立 v11；每个年度目标保留 `provisional_series_key`、正式 `series_key`、身份决策来源和别名。

赛事身份判断以沿革、场地、距离原单位、竞赛类型、年龄性别条件和同年并存情况共同决定，不能仅按裸赛事名或裸距离自动合并。实际年份与届次年份必须分开，例如 Bristol Novices' Hurdle 的 2001 届实际于 `2002-01-11` 举办。Ascot约3m金杯线中文主名确认为 `阿斯科特秋季金杯让磅障碍追逐赛`。高相似名称最终采用“15对名称变体合并、Prince of Wales's与Princess of Wales's保持独立”的审核结论，原始写法继续作为别名留存。

## 为什么历史赛事身份审核必须提供逐届参赛证据并保留距离原单位

同名赛事只比较名称、赛场和裸距离，容易把不同赛事错误合并，也可能把真实举办年份误判为 `not_held`。因此身份审核表必须把系列展开为逐年届次：能取得正式赛果时展示冠军马，能取得出马表或赛果明细时展示1号马；两者都不能可靠取得时保留该年度官方目录链接，不用模糊匹配填充空白。目录状态与官方赛果冲突时只标记待审，不自动修改总账。

不同地区和竞赛类型的距离单位不同，任何身份规则都不得直接比较 `distance_text` 裸数字。审核产物先保留 TJCIS 原始距离文本和竞赛类型；后续标准化模型必须分别保存原始数值、原始单位、统一换算值及换算规则来源，只有单位明确后才允许参与距离一致性判断。

## 为什么技术审查问题默认直接修复，产品能力与交互仍需用户审核

后续 code review 发现的纯技术问题，例如正确性、安全门禁、并发、性能、测试缺口、状态一致性和可维护性问题，默认由 Codex 直接修复、补测试并完成验证，不再逐项等待用户确认。这样可以减少已经明确方向后的重复审批，让技术返修持续推进到全绿。

涉及产品能力、数据范围、运营规则、用户流程、页面交互、公开可见性或文案体验的变更，仍必须先说明影响并交由用户审核。技术修复如果会实质改变上述产品行为，也按产品问题处理，不得借“技术优化”名义直接改变既定能力边界。

## 为什么马匹详情页使用 ID URL、草稿默认不可见并由后台审核发布

马匹名称存在多语言、重名、改译、别名和后续术语合并风险。若把公开 URL 绑定到马名或 slug，后续改名会带来重定向、重复页面和 SEO/缓存一致性问题。

因此马匹详情页 MVP 使用稳定唯一 ID：

- 公开索引：`/horses/`
- 公开详情：`/horses/<HorseProfile.id>/`
- 关注管理：`/horses/follows/`

P0 马匹页可以从 active horse `TermEntry` 默认生成，但生成后状态为 `draft`，前台返回 404；只有后台 `/admin/horse-profiles/` 人工审核、补充资料并手动发布后才公开展示。为了支持运营抢先建入口，管理员即使在资料完全空壳时也可以强制发布，但该动作会记录发布人、发布时间和备注。

## 为什么马匹关注对普通用户开放且只保存 token hash

关注功能的产品目标是让用户在新闻首页看到“关注马及其子孙代”的相关新闻，而不是后台运营专属标记。因此普通未登录用户也可以关注马匹。

实现采用匿名签名 cookie：

- cookie 保存签名后的随机 token，`HttpOnly`、`SameSite=Lax`，HTTPS 配置下启用 `Secure`。
- 数据库 `HorseFollow` 只保存 `token_hash`，不保存明文 token。
- 关注 POST 保持 CSRF 保护。
- 子孙代新闻只通过 `sire_horse_profile` / `dam_horse_profile` 的直接 profile 关系递归查询，纯文本血统不参与后代查询。

## 为什么用 HorseRaceRecord 承载完整参赛履历

马匹页第一版需要展示主胜鞍，但后续目标是每匹马的完整参赛履历。如果只建“主胜鞍表”，未来会重复建模参赛事实，也难以表达参加但未获胜、退赛、未上名等结果。

因此本轮新增 `HorseRaceRecord` 作为马-比赛事实表：

- 可选关联 `RaceEvent` / `RaceEventResult`，同时保存比赛快照字段。
- 覆盖参加过的比赛，不限于赢过的比赛。
- 主胜鞍由最高等级胜利和人工 `is_major_win` 标记共同决定。
- 无胜利、新马/未胜利、无重赏和人工指定场景都可以保守展示。

## 为什么外部血统补全走 dry-run artifact 而不是直接写公开数据

马匹资料需要尝试从外部数据补完整二代血统，但来源覆盖率、命名歧义、地区差异和反爬/限流都会影响准确性。直接从公开页或审核页实时请求第三方，会放大延迟、稳定性和来源合规风险。

因此补全策略是：

- 公开 `/horses/`、`/horses/<id>/`、首页关注模块和新闻详情 tag 只读本地数据库，不访问外部网络。
- `complete_horse_profiles --dry-run` 基于本地 `ExternalHorse` / `ExternalHorseAlias` 缓存生成 artifact、CSV 和 summary。
- summary 必须包含全局/按地区完整二代成功率、未补全占比、逐马失败原因、source URL 和候选 diff。
- `--commit` 必须读取已审核 artifact，并显式提供 `--confirm-reviewed-artifact`，不允许边抓边写。
- `new-village/KeibaScraper` 只作为受控 netkeiba 导入链路的可信数据源参考；项目当前采用本地缓存和低频导入，避免公开请求路径触网。

## 为什么马名和术语匹配一律大小写不敏感

外部赛马数据和新闻源对英文马名、赛事名、骑师名等术语的大小写并不稳定：HKJC 可能使用全大写，新闻标题可能使用标题式大小写，人工术语库也可能保留来源原始写法。如果按大小写精确匹配，会导致同一匹马在补全、新闻关联、术语替换和翻译保护链路中被误判为未命中。

因此所有含拉丁字母的术语匹配采用大小写不敏感规则：

- 术语解析、术语替换和单条术语应用对拉丁字母忽略大小写，并保留英文词边界保护。
- 外部马名 alias 和 `HorseProfile` 补全匹配使用大小写不敏感的规范化 key。
- 前台展示仍保留数据库中的原始写法；大小写不敏感只影响匹配与替换，不自动改写术语主数据。
## 为什么赛事信息编排工具第一版只服务 RaceEvent 产品层

赛事历史回填有两套容易混淆的数据层：

- `RaceEvent*`：产品层赛事，服务 `/races/`、赛事详情页、后台赛事工作台、出走表、赛果、历届冠军和相关新闻组织。
- `ExternalRace*`：外部来源缓存层，服务真实赛马数据库导入、外部马名索引和原始来源证据。

本轮 旧规格流程 change `orchestrate-race-event-data-crawls` 的第一版目标是补齐赛事页可展示和可运营的结构化赛事信息，因此只服务 `RaceEvent*`，不写 `ExternalRace*` / `ExternalHorse*`。这样可以避免把“产品层赛事历史回填”和“底层外部数据库导入”混成一个过大的系统，也能让 apply 门禁聚焦在 `RaceEventRunner`、`RaceEventResult`、`RaceEventHistoryWinner` 和 `RaceEventDataCandidate` 的完整性与覆盖风险上。

对应边界：

- 五个目标地区为日本、香港、英国、法国、美国。
- 第一版同时覆盖 `runners`、`results`、`history_winners`，且同一目标范围内三模块历史深度一致。
- 第一阶段只追核心 Group / Grade / Jpn / 交流分级 / 障碍分级等重点赛事，不包含 Listed，也不追所有普通比赛。
- 历史赛事系列必须显式 `series_key` / mapping；名称模糊匹配只能进入待审候选，不得直接写正式赛事详情数据。
- 长周期抓取默认手动分批或一次性容器执行，不加入 Celery Beat，不做无人值守自动 apply。

## 为什么赛事信息编排工具需要 adapter manifest 和目标赛事行预检

现有 `runtime/tools` 详情脚本已经能生成不少候选数据，但它们不是统一命令行接口：有的依赖 `--review-csv`，有的需要 `--source-html`、`--runner-jsonl` 或 `--pdf-dir`，部分产物还使用固定年份或来源特有文件名。因此第一版编排工具不假设所有脚本都有统一 `events_csv/output_dir` 契约，而是通过 adapter manifest 逐个声明脚本路径、参数映射、依赖产物、必需输出、source authority 和输出归一化规则。

深历史详情导入还受现有 importer 约束：`import_race_event_detail_candidates` 在 dry-run 阶段也会按 `year + slug` 查找 `RaceEvent`。如果某个历史年份的目标 `RaceEvent` 行尚不存在，详情候选即使抓到了也不能直接 dry-run 或 apply。因此编排工具必须先做目标赛事行预检；缺失时输出 draft seed review artifact 和 `missing_race_event` blocker，经人工确认或导入目标赛事行后，才能进入详情候选 dry-run 与 apply-check。这个规则避免把“抓到详情候选”误判为“已经可以安全写入公开赛事页”。

## 为什么 coverage、dry-run 和 apply-check 必须绑定候选文件哈希

赛事详情批量 apply 会按模块替换已有正式行，仅凭文件路径或“某个 dry-run 文件存在”不足以证明最终导入的就是已经审计的数据。候选文件可能在 coverage 后被修改，也可能在 apply-check 时通过另一个路径替换；旧日志、空文件或其他批次结果也不能证明当前候选 dry-run 通过。

因此编排工具把候选 JSONL 的绝对路径、大小和 SHA-256 作为批次证据身份：coverage audit、结构化 `dry_run.json` 和最终 apply 文件三者哈希必须一致。adapter manifest 同时作为 provenance 权威声明，标准候选由编排层注入 `adapter_key`、`source_provider`、`racing_region` 和 `source_authority`；缺失、非法或与 manifest 冲突的来源信息直接阻断。若同一赛事的模块使用不同来源或权威等级，coverage 生成稳定策略哈希，apply-check 只有在人工确认显式包含这些哈希时才放行。

同一原则也用于 resume：跳过 adapter 不只依赖输入未变化，还必须确认上次所有必需输出仍存在且哈希一致。这样可以避免运行目录被清理或产物被修改后，state 仍错误地声称该 adapter 可以复用。

## 为什么法国 TDN broad 上线时同时允许 `tdn_france:access` 和 `tdn:access`

`tdn_france_broad` 是法国新闻补充来源，但为了和既有 TDN 去重共用同一篇原文，入库时会使用 canonical source site `tdn`，同时通过 `source_config` 保留“这是法国来源发现的文章”。

生产发布白名单判断会先看文章主来源 `article.source_site:article.source_mode`，不匹配时再看 `source_config_id`。如果只允许 `tdn_france:access`，抓取可以成功，但自动发布策略可能看到文章主来源 `tdn:access` 后判定为 `source_not_allowed`。

因此 `2026-07-07` 上线法国 TDN broad 时，生产 `.env` 同时加入：

- `tdn_france:access`：表达运营意图，即法国补充来源被允许。
- `tdn:access`：匹配 canonical 入库后的文章主来源，避免发布策略误挡。

这不会放开所有 TDN 普通新闻；它只匹配 access 模式，并且文章仍需满足地区、评分、术语门禁、发布窗口配额和 QQ 限流。

## 为什么使用香港 ECS

当前阶段选择香港 ECS，主要基于以下考虑：

- 面向中文用户，访问延迟相对可接受
- 与大陆相比，部署与公网访问流程更直接
- 不需要先被大陆备案流程阻塞
- 适合项目早期先验证真实可用性

## 为什么当前阶段不做大陆备案路线

当前目标是先把产品链路跑通，而不是先投入备案周期。

不优先走大陆备案路线的原因：

- 备案流程会显著拉长首个可用版本上线时间
- 当前更需要先验证抓取、翻译、后台、前台、域名接入是否闭环
- 项目仍处于迭代和修正阶段，先以可运行、可验证为主

后续如果产品稳定、需要大陆更优访问体验，再评估备案与境内部署。

## 为什么继续使用 Django 单体 + Docker Compose 主干

当前继续保留 `Django 单体 + Docker Compose` 主干，而不做大分离或复杂服务化，原因是：

- 后台、前台、任务调度、模型管理都可在 Django 内保持高协同
- 当前团队规模与项目阶段更适合低复杂度架构
- Docker Compose 足以支撑单机阶段的生产部署与维护
- 当前瓶颈主要是上线稳定性与运维闭环，而不是架构扩展性

## 为什么项目记忆要写入仓库文档，而不是只依赖聊天上下文

这是本项目的重要协作原则。

原因包括：

- 聊天上下文天然易丢失，不适合承载长期项目状态
- 新 session 或新协作者需要能从仓库直接恢复上下文
- 生产问题、运行态差异、关键决策必须可追溯
- 文档化后的项目记忆更容易和代码、配置、部署资产一起演进

## 为什么术语合并后保留 inactive 历史主术语

`TermEntry.is_active=false` 不只表示“废弃错误词条”，也可以表示某个历史主术语已经被更完整的正式概念吸收。

HKJC 日语 alias 合并采用这个语义：

- 英文 HKJC 官方概念作为主概念保留 active
- 同一中文译名、同一类型的日语主术语被转换为该主概念的 active alias
- 原日语主术语设为 inactive，并在 notes 中记录 `hkjc_ja_alias_merged_into_term_id=<target>`

这样做可以避免同一马名在后台搜索、翻译替换和文章回填中形成两个 active 概念，同时保留来源可追溯性。后续排查 inactive 术语时，优先看 notes 是否存在合并标记；有标记的记录应视为“已合并历史概念”，不是需要恢复的漏导入。

## 为什么当前先做 HTTP，再补 HTTPS

正式域名接入阶段先做 HTTP，再补 HTTPS，是为了降低并发排障维度。

原因是：

- 如果 DNS、Nginx、Django Host、反代、证书同时变化，定位问题会更困难
- 先完成 HTTP 域名打通，可以确认：
  - DNS 正常
  - 域名已到服务器
  - `nginx` 反代链路正常
  - Django 域名配置正确
- 在 HTTP 稳定后，再接入 HTTPS / Certbot / 强制跳转，排障范围更清晰

## 为什么自动化运营采用“规则优先 + AI 改写 + 校验”

自动发布会直接影响前台内容质量，因此不能把“是否发布”完全交给黑盒模型。

当前实现选择：

- 规则先判断硬性忽略项和必须人工审核项
- 再按来源、内容价值、P0 马、赛事优先级、时效性和结构完整度评分
- AI 负责把基准翻译稿改写成中文资讯稿
- 改写后再做术语、数字、未收录马名、引语等一致性校验

这样可以做到自动化可解释、可回看、可人工接管。

## 为什么自动化默认通过 `.env` 开关灰度启用

自动发布属于生产风险较高的能力，代码完成不等于应立即在线上全量打开。

因此新增 `AUTOMATION_ENABLED` 开关：

- 生产可以先部署迁移但保持关闭
- 后台确认字段、日志和任务正常后再开启
- 如果自动化效果不稳定，可以不回滚代码，只关闭开关

## 为什么通知 MVP 只真实发送邮件

PRD 提到邮件、短信、微信或 QQ 通知，但首版只接入邮件，其他渠道先写 `NotificationLog` 并标记为 `skipped`。

原因是：

- 邮件成本低、接入稳定、适合异常告警 MVP
- 短信需要服务商、费用和模板审核
- QQ / 微信通知涉及账号、风控和协议稳定性
- 先把异常通知留痕和最小真实发送跑通，比一次性接入多个不稳定渠道更可靠

## 为什么 QQ 群自动推送使用独立交付记录

自动推送需要处理多群、重复触发、有限重试和部分失败。如果直接复用手动推送的 `PushLog`，同一篇文章对同一群可能因为 Celery 重试或重复发布触发而产生多条发送尝试，难以保证“只自动推一次”。

因此自动推送新增以“文章 x 群”为唯一粒度的交付记录：

- 成功后后续自动编排不会重复发送到同一群
- 多个群可以分别成功、失败或重试
- URL 检查失败和 OneBot 发送失败可以分开排查
- 手动推送保留原有日志语义，不受自动推送状态机影响

`sending` 只表示当前有任务正在领取并尝试交付，不作为永久锁。若 worker 异常退出或任务在外部 I/O 中断，记录超过 `QQ_PUSH_SENDING_STALE_SECONDS` 后允许后续任务重新领取；这样可以在有限重试内恢复，而不是长期卡在“发送中”。

OneBot HTTP API 的 HTTP 200 也不直接等于发送成功。应用会继续检查 OneBot JSON 中的 `status` / `retcode`，业务失败按 `send_failed` 记录，避免 QQ 群实际未收到消息但交付记录显示成功。

OneBot 网关离线或登录态失效时，自动推送会在真正调用 `/send_group_msg` 之前暂停本次交付，并记录 `send_failed` 错误摘要，但不会增加 `attempt_count`。这样做是因为 QQ 重新扫码登录后，原文章仍然可以继续发送；如果把离线状态当成一次真实发送尝试，短时间内的队列重试会把可恢复交付快速打到失败上限。

## 为什么 QQ 群自动推送默认关闭且默认只推高价值新闻

QQ 群是强打扰分发渠道，上线初期如果全量推送，容易刷屏，也更容易暴露 QQ 账号风控和 OneBot 网关稳定性问题。

因此生产默认：

- `QQ_PUSH_ENABLED=false`：先部署代码和迁移，再配置 Bot、测试群和灰度
- `QQ_PUSH_SCOPE=high_value_only`：首版只推 `score_total >= AUTO_REVIEW_THRESHOLD` 的新闻

如需验证链路或临时全量推送，可以显式切换为 `QQ_PUSH_SCOPE=all_public`。

## 为什么 QQ 重点推送要拆分范围配置和策略配置

QQ 自动推送后续会存在多种“重点”口径：本期按 netkeiba 访问量榜 / 注目数榜推送，后续可能扩展为“榜单 + 每场比赛当天高频推”或重新支持“按分数推”。

因此后续配置需要区分两层含义：

- `QQ_PUSH_SCOPE` 表示推送范围：例如 `high_value_only` 只推重点，`all_public` 临时推所有公开新闻。
- `QQ_PUSH_IMPORTANCE_STRATEGY` 表示“重点如何判定”：本期统一为 `ranked`，即 netkeiba 访问量榜和注目数榜。

这样可以避免把 `high_value_only` 永久绑定到某一个算法，也能让后续策略扩展只修改重点判定函数，而不破坏自动推送交付、去重、重试和多群配置。

无论采用哪种重点策略，QQ 推送都不得绕过自动发布门禁。阻断问题以 `NewsArticle.gate_blockers` 或 `gate_issues.severity=blocker` 为准，QQ 服务只消费现有结构化门禁结果，不重新实现一套独立 blocker 规则。

## 为什么 OneBot API 不公网裸露

OneBot HTTP API 可以直接发送群消息，一旦公网裸露且 token 泄露或配置不当，就可能被滥用。

因此生产部署约束为：

- 优先使用 Docker 内网 `http://onebot:3000`
- 临时宿主机映射只能绑定 `127.0.0.1`
- 必须配置 access token
- 应用日志不得输出 token

## 为什么保留 fallback 改写 provider

真实 AI 改写依赖模型 Key、余额、网络和供应商稳定性。

因此保留 `fallback` 改写 provider：

- 本地测试和 CI 不依赖外部 API
- 模型不可用时仍能保守生成改写稿快照
- 生产可通过 `REWRITE_PROVIDER` 切换到 SiliconFlow 或 OpenAI-compatible provider
- 自动化主流程可以先验证状态机、日志和发布闭环，再优化真实改写质量

## 为什么赛事日历新增“复合赛道”surface

2026 美国 TOBA Grade 批次中存在 `Sur=A` 的 all-weather / synthetic 赛事，例如 Turfway Park 的 Jeff Ruby Steaks。若把这些赛事硬映射为 `dirt`，前台会显示“泥地”，与官方赛道类型不一致。

因此 `RaceEventSurface` 新增 `synthetic=复合赛道`：

- 可以准确承载美国 all-weather / synthetic 赛事。
- 后续英国、法国或其他地区出现 Polytrack、PSF、Tapeta 等复合赛道时可复用同一字段值。
- 仍保留官方原始 surface code 到 `source_refs`，便于之后做更细的赛道材质标准化。
- 这是枚举与展示层补充，不改变 `RaceEvent` 主表结构或现有 turf/dirt/jumps 数据语义。

## 为什么赛果同着使用唯一排序位写库并保留官方名次

JRA 官方赛果会出现同着，例如两匹马同为第 `2` 名。当前 `RaceEventResult` 对 `(event, finish_position)` 有唯一约束，不能直接写入两条相同 `finish_position`。

因此 2026 JRA 详情导入采用两层口径：

- `RaceEventResult.finish_position` 保存唯一排序位，用于数据库约束、排序和稳定渲染。
- `source_refs.official_finish_position` 与 `source_refs.jra_finish_position_text` 保存官方名次。
- 前台赛事日历和赛事详情页优先展示官方名次；没有官方名次时才展示排序位。

这样既不破坏当前数据库约束，也不会在用户可见页面把同着第 `2` 名错误展示成第 `3` 名。后续若要彻底支持同着、DNF、取消和除外的完整赛果语义，可以再扩展 `RaceEventResult` 的展示名次字段或调整唯一约束。

## 为什么法国 2026 赛事详情暂用 ZEturf 作为公开结果源

France Galop 官方结果入口当前会重定向到认证页，不能稳定批量读取出走表和赛果；Geny 对本批 France Galop Groupe 赛事覆盖不足，不能作为唯一来源。ZEturf 的 race detail 页面当前可通过日期和 R/C 编号访问，并提供出走表、非出走标记和到达顺序，因此本轮法国 2026 详情先用 ZEturf 作为可访问公开来源。

## 为什么英文术语发布门禁先用地区过滤和配置化高歧义词清单

多地区英文新闻中，`CLASS`、`CONTENT`、`LINK`、`AGENT` 等既可能是正式术语，也常常只是普通英文词。如果把所有地区、所有英文正式术语都拿来做硬门禁，香港马名会阻断英国新闻，普通词也会把可发布文章打入人工审核。

因此 `fix-english-term-gate-region-filter` 第一版采用保守止血策略：

- 英文文章只校验同地区术语和 `racing_region=""` 全局术语。
- 需要跨地区通用的词条先治理为全局术语，不通过 notes 或 metadata 做隐式跨地区契约。
- 高歧义英文词先由 settings / 环境变量清单控制，降级为 warning/info 并保留审计 payload。
- 短词 / 全大写等自动派生歧义规则只用于非核心命中；未配置的同地区 / 全局高可信核心实体缺失仍然阻断。
- 不新增 `TermEntry` 字段，避免为止血引入迁移和后台维护成本；后续如运营需要可再设计 `publish_gate_level` 等字段。
- 真正同地区或全局高可信核心赛事、马名、骑师名、练马师名缺失仍然阻断自动发布。

为降低同日同场多场赛事误匹配风险，法国详情导入必须用页面 title 的日期、场地和赛事名共同确认；赛事名 token 匹配排除赞助词和场地词，并对短赛事名使用更严格匹配。若后续 France Galop 官方结果页恢复可访问，应优先切回官方源或用官方源复核 ZEturf 数据。

## 为什么已确认非术语进入发布门禁忽略清单

候选池 raw 抽取会保留所有可能触发术语识别的原文片段，其中一部分已经由运营确认不是术语，例如源站导航、产品名、HTML/布局片段、普通赛马词、马名/人名片段或广告文本。这些词如果被误建成 active `TermEntry`，或者被后续规则误识别为核心术语，就会让国际新闻源因为“假术语缺失”进入人工审核。

因此 `2026-07-10` 本地新增 `MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS`：

- 命中该清单的 source term 在发布校验中记录为 `non_term_gate_ignored` / `info`。
- 它不产生 `core_term_missing` 或 `background_term_missing`，不阻断自动发布，也不触发高价值 warning 邮件。
- 该机制独立于英文高歧义词清单；高歧义英文词仍用于“可能是术语但风险高”的降级，非术语清单用于“运营已确认不是术语”的忽略。
- 清单通过 settings / 环境变量可调整，便于后续把误加入的项移除，或继续从 raw no 类样本补充。
- 真正同地区或全局高可信核心赛事、马名、骑师名、练马师名缺失仍然阻断自动发布。

## 为什么历史冠军先写当前年度冠军作为第一层

`RaceEventHistoryWinner` 当前用于前台“近年冠军”模块。完整过去年份历届冠军需要按地区继续接入不同官方历史源，范围远大于 2026 当年赛事详情填充。

因此本轮先从已确认 `RaceEventResult` 中抽取每场 `2026` 年冠军写入 `RaceEventHistoryWinner`：已有赛果的已完赛赛事不会再显示“暂无历史冠军资料”，也不会猜测缺赛果赛事。这个数据层只代表当前年度冠军，不等同于完整历届冠军；后续补齐过去年份时，应以地区官方历史源生成完整 `history_winners.items` 后覆盖同一赛事的历史冠军列表。

## 为什么引入 旧规格流程 + Codex 领域代理

项目已经进入自动化运营、HTTPS、部署稳定化和运维完善并行推进阶段，跨模块与生产高风险改动会逐渐增加。

因此仓库引入 旧规格流程 作为较大改动的规格驱动工作流：

- 在实现前先形成可版本化的 proposal、spec、design 和 tasks
- 通过 `tasks.md` 保留进度，使新 session 可以从仓库恢复上下文
- 使用 `application / integration / operations` 三个真实仓库领域拆分任务
- 子代理只在明确要求时启用，避免无控制的并行修改
- 小型修复不强制创建 旧规格流程 change，但仍遵守现有阅读、验证与文档回写要求

旧规格流程 项目上下文与任务规则以 `旧规格流程/config.yaml` 为准；项目全局状态仍以 `docs/current_state.md` 为准。

## 为什么仓库协作文档默认使用中文

项目面向中文用户，当前主要协作者也以中文进行需求、运营和生产排障沟通。为了降低新 session 恢复上下文、人工审阅规格和运维执行时的理解成本，仓库内由 Codex 新增或维护的协作文档默认使用中文。

具体约定：

- 旧规格流程 proposal、spec、design、tasks 的说明性内容使用中文
- Codex 代理描述、项目上下文和面向协作者的说明使用中文
- 命令、代码标识符、协议字段、第三方工具强制要求的机器语法可以保留英文
- 旧规格流程 规格校验依赖的 `ADDED Requirements / Requirement / Scenario / WHEN / THEN` 等结构关键字保留英文，具体标题和内容使用中文
- 上游工具自动生成且约定不手工修改的文件维持原样

## 为什么术语发现结果必须先进入候选池

专有术语会直接影响翻译、改写、自动分流和重点赛事识别。自动识别仍可能存在误报、实体类型混淆和同名冲突，因此首版采用“发现与确认分离”：

- 规则发现器只创建或更新 `TermCandidate`，不能直接创建 `TermEntry`。
- 与正式术语同类型命中时不创建候选，跨类型命中时保留冲突信息供管理员判断。
- 接受、修改后接受和合并必须由工作人员在后台逐条完成。
- 合并到正式术语时，只有管理员明确勾选后才把候选文本加入日文别名。
- 拒绝和忽略状态在后续重复发现时保持稳定，避免候选池反复污染。

该设计优先保证正式术语库可信，并为后续接入模型识别或更多信息源保留可审计证据。

## 为什么国际化术语库采用“正式术语概念 + 多语言原文别名”

接入日本、中国香港、英国、法国和美国新闻后，同一匹马、同一场赛事或同一个人物可能同时出现日文名、英文名和繁体中文名。如果把每种语言都建成一条独立 `TermEntry`，后台会出现多个“同一实体”，自动评分、标签、翻译校验和候选合并也会越来越难解释。

因此本轮国际化返修采用两层模型：

- `TermEntry` 表示正式术语概念和标准简体中文译名，例如一匹马“春秋分”。
- `TermAlias` 表示该概念在不同原文语言下的名称或别名，例如 `イクイノックス / Equinox / 春秋分`。

文章匹配时只使用与文章 `source_language` 一致的原文别名，避免英文文章误命中日文别名；命中后仍回到同一个 `TermEntry`，用于统一的中文译名、标签和评分。

本轮保留 `TermEntry.source_ja / aliases_ja` 作为兼容字段，迁移会把旧数据回填为 `ja` 别名。后续如果要彻底重命名旧字段，应另起清理 change。

## 为什么 HKJC 日语 alias 合并会停用冗余日语主术语

HKJC 官方英文概念和既有日语主术语如果拥有同一术语类型和同一中文目标，继续保留两个 active `TermEntry` 会让后台搜索、文章术语替换和后续审计出现“同一实体多概念”的歧义。

因此 `hkjc-ja-alias-article-backfill` 采用保守合并策略：

- HKJC 英文 `TermEntry` 作为正式概念承载标准中文译名。
- 日语 source text 写入该概念的 `TermAlias(source_language=ja)`。
- 原独立日语主术语停用，并在 notes 记录合并目标 term id。

这样做不会删除历史记录，也解释了术语库中少量 inactive 术语的来源：它们可能是已经被更完整概念吸收的历史主术语，而不是应继续参与匹配的正式概念。若中文目标、术语类型或 active owner 存在冲突，系统只输出人工复核记录，不自动合并。

## 为什么已发布文章术语回填不重新翻译整篇文章

术语补齐后，历史已发布文章中可能仍保留日文或英文 source text。这个问题的修复目标是“精确替换术语”，不是重做内容生产。

因此文章回填采用字段级 diff/apply：

- dry-run 输出完整 before/after 字段值和人工复核 CSV。
- apply 只替换明确命中的 source text。
- 默认跳过人工编辑过的发布字段。
- 不重新抓取、不重新翻译、不调用 AI 改写、不改变发布、审核、workflow 或 QQ 推送状态。

这能把生产写入范围限制在可审计、可恢复的最小改动内；大范围内容重译或风格重写应另起 change。

## 为什么公开首页升级先做主 旧规格流程 change

公开首页从 MVP 页面升级为 Web + 移动 H5 成熟资讯流，虽然主要发生在模板、样式和视图层，但它会影响前台信息架构、后续子能力边界和用户内容消费路径，因此先创建主 旧规格流程 change `upgrade-public-home-info-feed` 作为指导规范。

这样做的原因：

- 首页不再只是“已发布文章列表”，而是要定义头条、普通流、热门代理、详情页和响应式布局的长期基础。
- 后续手工置顶、搜索频道、专题、赛事日历、站内热度等能力都可能接入首页，如果没有主规范，容易把不同问题混在一次实现里。
- 当前前台模板直接引用后台 `console.css`，需要先确立公开站点样式解耦方向，避免后台和前台继续互相牵连。
- 旧规格流程 主 change 可以明确本轮只做公开资讯消费体验，不改抓取、翻译、自动发布和部署主链路。

## 为什么第一版首页不新增手工置顶或赛事日历模型

第一版首页升级选择复用现有 `NewsArticle`、`NewsSnapshot`、自动评分和赛事优先级字段，先完成算法化头条、普通新闻流和热门代理展示，不新增首页运营控制或赛事日历数据模型。

## 为什么赛事日历 MVP 使用年度 RaceEvent 产品层

赛事日历第一版采用“每年一个赛事页”的 `RaceEvent` 产品对象，而不是直接公开 `ExternalRace` 或把现有 `MajorRaceEvent` 扩成前台赛事页。

原因是：

- 前台赛事页需要可见性、资料完整度、候选确认、人工锁定和新闻纠偏，这些属于产品运营语义。
- `ExternalRace` 继续表示外部原始数据，不能直接承担“已确认可公开”的状态。
- `MajorRaceEvent` 继续服务抓取 / 发布窗口升频，不写入公开可见性、候选资料或赛果。
- 年度粒度符合赛前资料、出马表、闸位、赛果和相关新闻都随年份变化的产品形态。

第一版保留 `series_key`，只作为未来跨年系列聚合的内部伏笔，不提供系列页。

## 为什么赛事候选资料必须人工确认后再公开

赛事信息整体稳定，但指定网站抓取仍可能出现字段缺失、格式差异或来源冲突。第一版因此采用“公开字段”和“候选资料”分离：

- CSV 或后台创建的赛事满足名称、日期、马场、等级等最小条件后可展示。
- 指定网站抓取结果只写入 `RaceEventDataCandidate`，不自动覆盖公开结构化字段。
- 后台按模块应用候选，应用行为写入操作日志或任务日志。
- 已人工编辑或锁定的字段不被普通候选覆盖。

这让自动化能减轻录入工作，但最终可公开资料仍由运营人员拍板。

## 为什么赛事动态字段只对白名单自动刷新

赔率、热门度、出走状态和退赛状态变化快，适合在详情页出马表中作为动态字段刷新；赛事名称、日期、马场、等级、surface、距离、参赛条件等基础资料相对稳定，自动覆盖会增加误伤风险。

因此第一版动态刷新只允许：

- `odds_value`
- `popularity`
- `running_status`
- 退赛 / 取消出走类状态

刷新失败时保留最后一次成功值和更新时间，只在后台记录错误。

## 为什么赔率只放在赛事详情页而不进赛事日历

赛事日历的目标是按时间快速扫描赛事，不承担投注或赔率导向。赔率信息敏感且变化快，放进列表会放大合规和误读风险。

因此第一版约束为：

- 赛事日历移动卡片和 PC 表格不展示赔率。
- 赔率只在赛事详情页概览的出马表中作为普通动态字段展示。
- 赔率不进入详情页 Header，也不建设独立赔率模块。

## 为什么马匹数据库延期

赛事日历 MVP 只需要展示年度赛事、出马表、前几名赛果、历史冠军和相关新闻。完整马匹数据库、马匹详情页、血统、历史战绩会显著扩大数据建模和导入复杂度。

因此第一版只在 `RaceEventRunner`、`RaceEventResult` 和 `RaceEventHistoryWinner` 中保存展示所需的马名文本，不建立独立马匹产品页。未来如要抽出马匹数据库，应另起 change 处理。

原因是：

- 现有字段已经足够支撑“重点内容突出 + 普通内容高密度”的第一版体验。
- 手工置顶会引入推荐位模型、后台表单、排序冲突、开始/结束时间和运营权限规则，更适合作为后续独立 change。
- 赛事日历需要结构化赛事、场地、开跑时间和数据源，不应伪装成已有新闻标签或术语数据。
- 热门榜当前只能使用 netkeiba 上游访问/注目快照或自动评分回退，不能包装为本站浏览量或本站评论。

因此后续规划拆为：

- `upgrade-public-home-info-feed`：主首页与详情页信息流升级。
- `add-homepage-editorial-placement`：手工头条、推荐位和置顶。
- `add-public-topic-search-navigation`：搜索、标签页、频道页和专题页。
- `add-race-calendar-sidebar`：结构化赛事日历和今日重要赛事模块。

## 为什么 QQ 群空地区配置按旧日本行为处理

国际赛马资讯扩展后，QQ 群级配置需要区分“系统能不能推”和“这个群想看什么”。如果把旧群的空 `allowed_regions` 解释为所有地区，部署后既有群会在没有明确订阅的情况下突然收到中国香港、英国、法国和美国新闻。

因此本轮约定：

- `QQ_PUSH_ENABLED` 仍是总开关，只决定是否运行自动推送。
- `PushTarget.allowed_regions` 决定该群允许接收哪些地区。
- 迁移会把既有群回填为 `["japan"]`。
- 运行时如果仍遇到空 `allowed_regions`，也按旧行为仅允许日本新闻，而不是默认允许全球新闻。

这样能让国际新闻源上线后按群灰度启用，不打扰只想继续看日本新闻的旧群。

## 为什么公开首页资讯流升级要求严格 TDD

公开首页升级虽然主要是前台视图、模板和样式改动，但它会改变已发布文章在用户侧的呈现规则，包括发布过滤、头条选择、普通流排序、热门代理和详情页有效稿件字段展示。为了避免实现过程中只凭视觉调试而破坏已有发布链路，`upgrade-public-home-info-feed` 后续实施要求严格 TDD。

执行原则：

- 每个可测试行为单独执行 RED -> GREEN -> REFACTOR：先在 `server/stable/tests.py` 中新增一个失败测试并确认红，再实现该行为的最小代码并确认变绿，最后做局部重构。
- 禁止一次性批量写完全部测试后再实现；发布过滤、普通流排序、头条选择、热门代理、详情页字段和公开静态资源都必须按行为分轮推进。
- 热门代理实现必须在有限已发布候选集内批量读取 `NewsSnapshot` 或使用等价预取方式，避免无上限扫描或逐篇文章查询最近快照。
- 所有 TDD 循环通过后，再跑完整 `stable` 测试。
- CSS 和响应式体验不适合全部单元测试化，因此用桌面/移动浏览器视口验收作为补充验证。

该决策只约束本 change 的实施顺序，不要求为纯视觉像素差异编写脆弱测试。

## 为什么外部赛马数据采用离线低频导入

未知马名识别需要更可靠的马名来源，但不能把新闻抓取、翻译或自动发布链路绑定到实时访问 netkeiba。

因此外部赛马数据采用离线低频导入与本地索引方案：

- 使用 `keibascraper` 作为可替换适配层的数据来源，不让业务代码直接依赖第三方库返回结构。
- 先按近两年比赛、出走、赛果、马匹和履历建立本地缓存，保存结构化字段与原始 payload。
- 从出走表、赛果和可信单马参数派生本地马名索引，后续再让未知马名识别消费该索引。
- 生产默认关闭网络导入，必须人工显式触发，并且强制限速、抖动、批量上限和同一来源互斥。
- 导入失败只写入导入错误记录，不影响新闻抓取、翻译、AI 改写、自动发布和公开前台。

这个方案优先保证生产主链路稳定，也为后续替换为 JBIS、JRA-VAN 或本地公开数据库保留边界。

## 为什么外部马名索引不等同于正式术语库

外部赛马数据导入得到的 `ExternalHorseAlias` 只证明某个日文文本是外部数据源确认过的马名，不证明系统已经有可信中文译名。因此后续接入文章准备、翻译和校验时，必须把“确认是马名”和“有中文译名可替换”拆开。

设计边界如下：

- `TermEntry` 继续作为正式术语库，保存有中文译名、固定译法或人工确认别名的词条。
- `ExternalHorseAlias` 作为本地马名索引，只用于识别、保护、校验和候选发现，不批量写入 `TermEntry`。
- 如果同一马名同时命中 `TermEntry` 和 `ExternalHorseAlias`，以 `TermEntry` 为准，进入中文术语提示和译后替换。
- 如果只命中 `ExternalHorseAlias`，翻译阶段应保护原始日文马名，不能擅自生成或替换中文译名。
- 术语候选池应把新闻中出现、外部索引命中但缺少正式中文译名的马名均作为高置信候选，包括正文背景段落中的马名，让工作人员决定是否补入正式术语库。
- 普通词与外部马名同名时不能无条件信任数据库，必须结合强马名上下文消歧；缺少强马名上下文时不得把普通词当马名。
- 同一日文马名可能对应多个外部 horse ID，识别结果必须保留全部匹配 ID，并只把主 ID 作为展示辅助，避免静默丢弃同名歧义。

## 为什么国际赛马资讯扩展先做多地区承载和 HKJC 导入

项目下一阶段需要从日本赛马资讯扩展到日本、中国香港、英国、法国和美国，但不同地区的新闻语言、数据库开放度、审核可读性和 QQ 群偏好差异很大。因此国际化第一期不直接追求全地区全量抓取，而是先建立可承载多地区、多原文语言和多群推送偏好的主干能力。

具体决策：

- 前台先提供 `综合 / 日本 / 中国香港 / 英国 / 法国 / 美国` 地区 tab，综合流第一期使用已发布文章倒序，不先做复杂推荐或地区打散。
- 新闻正文第一期只支持日文、英文和繁体中文；法国新闻只接英文来源，法语正文不进入人工审核和自动发布主链路。
- 术语库先从 UI 和服务语义上改为“原文术语 -> 简体中文译名”，并增加原文语言；现有 `source_ja / aliases_ja` 物理字段暂时保留兼容，避免在同一阶段做高风险重命名。
- QQ 自动推送从全局范围配置扩展为群级配置，因为不同 QQ 群可能只想看不同地区或不同范围的新闻。
- 外部数据库第一期正式实现 HKJC，因为香港官方数据集中、字段完整、中文用户价值高；美国 `Equibase`、英国 `Sporting Life + BHA`、法国 `France Galop` 先做小样本 spike，确认字段、入口和反爬/语言风险后再进入正式导入。

该决策最初只对应 旧规格流程 change `expand-international-racing-coverage` 的规划边界；`2026-06-25` 已在独立 worktree 开始本地实现。当时后续部署要求完整测试、旧规格流程 校验和生产窗口确认；这是历史门禁记录，`2026-07-15` 后新变更以当前 Codex 工作流和任务专属发布授权为准。

review 返修后补充实现边界：HKJC 外部数据导入必须参考 netkeiba 的单来源互斥锁语义，已有运行中导入时拒绝并发写入；在真实网络抓取实现前，`--commit` 不允许写入占位 payload，必须通过 `--payload-file` 提供真实小样本；payload 超过 `max_races / max_horses` 时直接失败，不静默截断或部分写入；`max_horses` 的统计口径必须覆盖顶层 `horses`、赛事 `entries` 和 `results` 中实际会写入缓存或别名的唯一马匹，避免 entries/results 绕过批量上限；多语言术语后处理和自动化评分必须按文章 `source_language` 隔离，避免英语、繁中、日语术语在翻译、改写、重点马和赛事优先级判断中串用。

公开文章 ID 和来源去重键必须分离：公开详情页继续使用本地全局自增 `NewsArticle.id`，减少标题 slug 或上游 ID 变化带来的公开 URL 问题；但抓取入库仍需要稳定的 `source_article_id` 识别同一上游文章，否则重复抓取无法幂等更新。国际新闻源的 `source_article_id` 因此使用完整 URL 派生的低碰撞键，而不是只取 URL 最后一段 slug。

原始 HTML 和轻量 metadata 必须分离：整页 HTML 只保存到 `original_content_html`，`translation_metadata` 只保存来源语言、作者、抓取 URL、模型和 warning 等轻量元信息，避免同一份 HTML 在文本字段和 JSON 字段中重复保存。

排序型入口采用逐源确认策略：类似 netkeiba 访问量榜/注目榜的来源，只有公开 HTML 或公开 API 能稳定慢速抓取并能拿到真实文章时，才作为独立榜单源接入并记录原站排名。本轮只确认 `Sponichi 新闻ランキング` 可稳定抓取，因此先作为 `source_mode=access` 榜单源加入，默认关闭；该页面混有ボート等非赛马内容，适配器必须过滤非赛马文章并保留原站排名，不按过滤后的列表重新编号。`HKJC Racing News`、`SCMP Racing`、`BHA` 暂未发现等价公开热门新闻榜单；`Sporting Life` 有 `MOST READ RACING` 骨架容器但未确认稳定公开 API；`At The Races`、`Paulick Report` 当前 403，`BloodHorse` 有反机器人/空样本风险，均不作为生产自动榜单源启用。

上线前最终新闻源清单以真实 dry-run 可抓到两篇正文为准。第一版生产候选为：日本 `Sponichi latest/access`；中国香港 `HKJC Racing News`、`SCMP Racing`；英国 `Sporting Life Racing`、`Sky Sports Racing latest/access`，官方补充 `BHA official`；法国仅英文来源 `France Galop English News official`、`TDN France keyword`；美国 `TDN`、`Horse Racing Nation latest/access`。其中 `Sky Sports Racing Top Stories` 和 `Horse Racing Nation Trending` 作为弱热门/编辑排序信号，按页面顺序写入 rank；`At The Races`、`Paulick Report`、`BloodHorse` 保留为可单独探测候选，但不进入第一版默认清单或生产启用计划。

`TDN France keyword` 本质上仍来自 `thoroughbreddailynews.com`，与美国 `TDN` 普通源可能发现同一篇 URL。为避免同 URL 在两个 `source_site` 下重复入库，本轮采用简单 canonical 去重：文章主键使用 `TDN + source_article_id`，快照仍记录实际发现来源 `TDN France keyword`，且法国关键词来源会优先保留法国地区归类。这样既减少重复文章，也不丢失“这篇是法国相关稿”的审核和推送信号。

这样可以利用本地马名数据库降低普通词误报和真实马名漏报，同时避免把没有中文译名的外部数据污染正式术语库。

## 为什么自动发布门禁要区分 blocker / warning / info

自动化评分已经能识别高价值新闻，但近期候选池样本显示，很多高分文章不是因为内容不可发布而进入人工审核，而是被低确定性校验误伤：片假名普通词被识别成未收录马名，背景术语在摘要化稿件中被省略，数字一致性校验要求过严，长采访或引语较多也被当成硬失败。

因此后续自动发布门禁采用三层严重级别：

- `blocker`：明确不可自动发布的问题，例如缺标题、缺正文、正文过短、乱码、广告导航页、翻译失败或高度重复内容。
- `warning`：需要人工关注但初期不阻断自动发布的问题，例如疑似未收录马名、背景术语缺失、数字省略或引语较多。
- `info`：仅用于诊断和回看的问题，不影响发布分流，也不触发告警。

初期策略是 warning 不阻断自动发布，但高价值文章出现 warning 时必须邮件告警给工作人员。这样可以让自动化发布先跑起来，同时保留人工接管入口和质量抽检线索。

高价值来源只影响评分阶段放行，不绕过 blocker。首批高价值来源规划为 `netkeiba` 访问量榜和 `netkeiba` 注目数榜；如果这类文章缺正文、乱码或与已发布内容高度重复，仍然不得自动进入前台。

重复内容属于发布安全门禁：高度重复内容使用独立重复状态阻断自动发布，中等相似内容转人工审核，不归入初期不阻断的 warning。

短期默认发布内容源采用基准翻译稿，`AUTO_REWRITE_ENABLED=false` 且 `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`。AI 改写字段和任务不删除，后续质量稳定后可通过配置恢复为 `rewrite` 内容源。

## 为什么原文选区快速加入术语库首版不自动重翻译

后台工作人员在候选详情页或编辑台发现新马名、赛事名、固定译法时，需要一个低摩擦入口把原文片段加入正式术语库，但“保存术语”和“让当前稿件重新应用术语”是两个风险不同的动作。

因此 `add-selection-term-quick-add` 首版只做文章上下文快速创建正式术语：

- 术语类型默认 `horse`，因为当前最常见问题是未知马名漏识别；但后台表单必须允许改类型，避免把普通词误写成马名。
- 快速入口复用正式术语校验，不绕过重复、类型、比赛等级和启用状态规则。
- 创建成功只写入 `TermEntry` 和操作日志，并记录来源文章 ID/标题；不改当前文章中文稿、基准翻译稿或改写稿。
- 不自动触发 `translate_article_task`，避免管理员只是补库时意外覆盖正在编辑的稿件。
- 编辑台页面已有外层文章编辑表单，快速术语按钮必须绑定到独立表单，避免浏览器把“加入术语库”误提交成“保存文章”。

后续如果要“新增术语后自动重新应用术语/重翻译”，应作为独立 change 处理，并显式设计覆盖字段、人工确认、失败提示和可回退路径。

## 为什么新增术语后的当前稿联动采用显式动作

`reapply-terms-after-quick-add` 继续沿用“保存术语”和“改当前稿件”分离的原则。新增术语成功后，工作人员可以通过一次性浮层选择“应用该术语到当前稿”；重新翻译保留为页面级能力，不属于术语成功浮层。系统不在保存术语后自动覆盖稿件。

这样设计的原因：

- 创建 `TermEntry` 是低风险补库动作；修改 `NewsArticle` 中文稿是内容编辑动作，应由工作人员明确触发。
- 编辑台里可能已有人工修改，默认覆盖会破坏工作人员刚完成的校对。
- 用户心智是“刚建一个新术语，就把这个术语应用到本文”，因此轻量动作只应用刚创建的指定术语，不重扫整个正式术语库。
- 指定术语应用会替换当前文章相关字段中的所有匹配位置，不限于创建术语时选中的原文片段，因为同一术语可能在文章中出现多次。
- 轻量术语应用不能等同于模型重新理解日文原文，因此需要和页面级“重新翻译”能力保持区分。
- 人工编辑字段由 `manually_edited_fields` 保护；默认指定术语应用只更新机器翻译字段、基准翻译稿和未标记人工编辑的发布稿字段。
- 快速创建成功后的应用入口只出现一次；刷新、离开页面或错过成功反馈后不补常驻入口，避免后台长期暴露容易误点的稿件修改按钮。
- 重翻译继续复用现有 `translate_article_task`，避免新增任务类型，也让最新正式术语库自然进入现有翻译提示和译文纠偏链路；若页面已有重新翻译按钮，不为术语成功浮层新增重翻译入口。

首版不做全站批量重翻译，不自动重新跑自动发布门禁，也不因指定术语应用或重翻译自动发布文章。后续如需要字段级 diff、强制覆盖人工字段或自动重跑门禁，应继续拆独立 change。

## 为什么英法美数据库源本轮仍保持 needs_more_spike

`start-hkjc-data-import-and-global-spikes` 对 `Equibase`、`Sporting Life + BHA`、`France Galop` 做了 2026-06-26 read-only spike。三地公开页面均能返回 `200`，且没有观察到明显访问阻断，但本轮只确认了浅层 HTML 入口和字段信号，没有确认稳定的结构化 API、完整单赛日/单马 URL 参数、分页/历史范围、PDF chart 解析成本或官方补字段路径。

因此本轮准入判断统一保持 `needs_more_spike`：

- 美国 `Equibase`：entries/results 有信号，但 horse profile 与 chart/PDF 仍需更具体小样本验证。
- 英国 `Sporting Life + BHA`：Sporting Life racecards/results/profile 信号较好，优先级最高；BHA 官方搜索、监管和补字段入口仍需单独复验。
- 法国 `France Galop`：英文站浅层页面可访问，但结构化赛程、报名、出马、赛果和马匹资料的稳定查询入口仍未确认；法语新闻正文仍不进入新闻审核、翻译、自动发布或 QQ 推送主链路。

该决策当时要求正式导入英法美数据库源前另起 旧规格流程 change，先把每个地区的具体 URL 参数、字段映射、限速、失败恢复、正式表写入边界和回滚口径设计清楚；`2026-07-15` 起等价工作改为新建 `docs/changes/<slug>/` spec/design，不再调用旧 旧规格流程 skills。

2026-06-26 `connect-real-global-racing-databases` 追加只读复核后，英法美仍不进入正式写库，但职责边界更清晰：

- 英国优先以 `Sporting Life` 作为正式导入主候选，因为 `racecards`、`fast-results` 和 horse profile 均可访问，且 results 页面暴露具体 racecard/profile 链接；`BHA` 作为官方补字段候选，负责复核 horses、fixtures、feed/search 等权威入口。
- 美国 `Equibase` 可继续作为唯一主候选推进 fixture spike；entries、chart/PDF index 和 horse profile 均可访问，但正式导入前必须先证明 chart/PDF 或 HTML chart 解析成本可控。
- 法国 `France Galop` 仍停留在官方页面浅层信号阶段；在定位稳定结构化查询参数前，不进入正式 parser/importer TDD。

## 为什么本轮全球赛马数据库目标关闭在“能力可用”

`2026-06-27` 用户将本轮目标从“完成最近 2 个月完整大量爬取”调整为“先保证所有地区的数据爬取能力真实可用”。因此本轮完成口径不再要求香港、英国、法国、美国都完成最近 60 天全量赛事与所有涉及马匹 profile 的真实爬取，也不要求生产 `--commit`。

本轮关闭目标的依据是：

- HKJC 已有生产真实 dry-run 批次证据，证明官方 HTML 入口、race batch、马匹详情补抓、低频请求和 dry-run 安全边界可用。
- UK / France / US 已有少量真实 proof，证明 Sporting Life、Geny、Horse Racing Nation 的赛事、赛果和马匹详情入口可访问并可解析。
- 四地 importer 均保留默认 dry-run、显式 `--allow-network`、请求上限、限速、精确批次和严格 `--commit` 门禁。
- proof-only 离线审计可以证明“能力可用”，同时完整 commit 候选审计会继续阻断缺少 plan、混合来源或马匹详情未补齐的输出。

后续若重新追求最近 60 天完整大量抓取，应作为新的执行窗口处理，并从最新 plan-only、逐批 dry-run、离线审计、备份、锁检查和用户显式确认重新开始。

## 为什么多地区新闻常态生产第一期使用配置化策略

日本以外的香港、英国、法国、美国新闻源已经接入，但真实运营仍需要先解决常态调度、人工审核边界、地区观测和 QQ 灰度，而不是马上新增一套地区策略后台模型。

因此第一期选择：

- 使用 `NEWS_SOURCE_POLL_*` 配置驱动通用 enabled 来源轮询，生产默认关闭。
- 继续保留 netkeiba / JRA 固定 Celery Beat，通用轮询默认排除这些固定调度来源，避免重复高频抓取。
- 使用 `MULTIREGION_AUTO_PUBLISH_*` settings 表达地区 / 来源 allowlist、每轮上限、每日上限和术语候选积压阈值，不新增 `RegionPublishPolicy` 模型。
- 非日本新闻默认转人工审核；只有显式配置允许的地区和来源才可能进入自动发布。
- QQ 推送继续以 `PushTarget.allowed_regions` 为群级边界；旧群空地区或非法地区配置仍只按日本兼容，不自动扩展到全球新闻。
- 外部赛马数据库 importer 继续只作为受控数据导入和马名识别底座，不进入新闻 Beat，不自动生成公开新闻、赛果页或 QQ 推送。

这样能先把“可常态运行但默认安全关闭”的闭环落地，后续若运营确实需要后台维护地区策略，再另起 change 设计模型、迁移和 UI。

## 为什么地区生产概览区分今日产能和当前积压

`operate-multiregion-news-production` 代码审查后明确：后台地区生产概览不能把历史累计发布数当成今日生产状态，否则工作人员会误判某地区今天是否真的在持续产出。

因此地区生产概览采用两类口径：

- `今日新增`、`自动发布`、`人工发布`、`公开` 表示服务器当前日期窗口内发生的生产结果。
- `待翻译`、`翻译失败`、`待审核` 表示当前仍需处理的积压队列。

这个口径能同时回答“今天有没有生产”和“现在还堵在哪里”，也避免页面默认依赖全量历史发布计数。

## 为什么正式术语地区字段为空表示全局通用

多地区新闻常态生产需要知道香港、英国、法国、美国各自的术语库准备程度，但现有正式术语长期作为全站词库使用，不能在迁移时强行归属到单一地区。

因此 `TermEntry.racing_region` 采用可选字段：

- 空值表示全局通用术语，适用于所有地区的审计统计。
- 设置地区值时，表示该术语主要用于对应地区，可在术语列表、表单、API、CSV 导入和多地区审计中按地区筛选。
- 本轮先不改变翻译/术语替换的匹配范围，避免因为加地区字段而破坏既有术语应用链路；如果后续要让翻译提示严格按地区匹配，应另起 change 设计回退和兼容规则。

## 为什么多地区新闻增量使用窗口账本而不是直接提高旧任务频率

`increase-multiregion-news-volume` 的核心目标不是单纯“多跑几次爬虫”，而是让抓取、发布和 QQ 推送都能回答同一类运营问题：这个 15 分钟或 5 分钟窗口有没有执行、为什么 0 篇、是否触发上限、能否安全重跑。

因此本轮采用 `ProductionWindow + WindowCandidateDecision + WindowTargetDecision + QuotaLedger`：

- 抓取窗口按来源建账，只有已启用、生产批准、未暂停且未 backoff 的来源进入 15 分钟调度。
- 发布窗口按地区建账，硬门禁、去重、评分、保底和配额都写入候选决策，0 发布不再只能从日志猜。
- QQ 窗口按地区建账，目标群跳过原因、群小时上限和全站小时上限都有持久化记录。
- 重要赛事只改变频率，不叠加单窗口上限；同地区重叠赛事合并为同一个 5 分钟模式。
- 新窗口 Beat 可以常驻，但生产总开关默认关闭；部署、迁移和重启不会自动切入高频生产。

旧 `auto_publish_batch_task` 在新发布窗口开启时直接跳过，避免旧任务和新窗口同时抢发文章。

抓取和 QQ 推送恢复时只执行最近一个缺失窗口，较早缺失窗口只写 `SKIPPED` 账本并标记合并到最新窗口。这样做是因为停机或 worker 堵塞后，连续补跑多个历史窗口会在真实时间内集中请求新闻源或集中发送 QQ 消息，容易触发来源站和 QQ 风控；运营仍能从窗口账本看到哪些窗口被合并跳过，而不会误以为它们正常生产。

已有 `SKIPPED` 或仍可重试的 `FAILED` QQ delivery 再次被窗口选中时，也要重新占用群小时和全站小时配额。原因是这类记录代表“又要尝试一次真实发送”，对 QQ 和用户群的打扰成本与新建 delivery 相同；只有 `PENDING / RETRYING / SENDING / SENT` 这类已经排队、正在处理或已成功的记录，才可以跳过配额，避免重复记账。

抓取窗口不能把“Celery 任务已投递”当成“抓取成功”。投递成功只说明任务进入队列，真实抓取可能仍在排队、运行或最终失败；如果此时窗口已记为成功，而来源 `last_crawl_at` 尚未更新，下一轮调度可能继续派发同一来源，反而提高抓取频率和封禁风险。因此抓取窗口由真实抓取任务完成后回写结果，来源存在 lease 未过期的运行中抓取窗口时直接跳过。

QQ 窗口同样不能把“delivery 已入队”当成“QQ 已成功发送”。OneBot 离线或登录态失效时，真实发送任务会失败，若窗口仍显示成功，运营会误判本轮 QQ 正常。因此 QQ 窗口在占用配额和创建发送任务前先做 OneBot 在线预检；离线时窗口直接记录失败原因，不消耗发送尝试，也不制造新的群消息任务。

## 为什么 ops 摘要通知先接入 UmaFans 测试群

`increase-multiregion-news-volume` 上线后，运营需要能感知窗口失败、0 发布原因和恢复情况；但生产暂时没有单独的内部运营邮箱或专用 QQ 群配置。

因此本次上线先将 `MULTIREGION_OPS_NOTIFICATION_QQ_GROUP_ID` 配置为现有 `UmaFans测试群(1026525240)`：

- 该群已经用于生产 QQ 推送验证，且已显式允许五地区新闻。
- ops 通知服务有独立开关和 30 分钟冷却，不占用用户新闻 QQ 推送配额。
- 本次只验证一次 `production_summary_task`，确认 `NotificationLog #13051` 发送成功，避免上线时额外刷屏。

后续如有正式运营群或邮件地址，应只调整 ops 通知目标，不需要改窗口调度代码。

## 为什么榜单二次命中只唤醒未发布文章而不直接发布

新闻从普通来源进入访问量榜、注目榜或国际榜单，说明它的价值可能被首次评分低估，但榜单本身不等于内容已经适合公开发布。

因此 `revive-ranked-news-for-publish` 的产品语义是“榜单唤醒”，而不是“榜单直发”：

- 榜单命中可以复活低分忽略、价值不足转人工、待翻译或翻译失败的未发布文章。
- 翻译失败或待翻译文章进入榜单后，应自动重试翻译。
- 已翻译文章进入榜单后，应重新评分，并让高价值来源信号参与自动发布判断。
- 发布仍必须经过翻译成功、自动评分、发布校验、发布窗口候选选择、配额和 QQ 限流。
- 人工拒绝、撤回、已发布、高度重复、正文缺失、核心术语缺失等硬门禁不被榜单绕过。

这样可以把榜单价值信号用在“重新认真处理”上，同时保留现有自动发布体系的可解释性和安全边界。

## 为什么榜单唤醒时间使用 `ranked_revived_at` 字段而不是只写 JSON

发布窗口需要稳定查询“最近 3 小时首次入库或最近 3 小时被榜单唤醒”的候选。如果只把唤醒时间写在 `decision_reason` JSON 里，SQLite 测试和 PostgreSQL 生产在 JSON 时间比较、索引和查询性能上都更容易分叉。

因此 `revive-ranked-news-for-publish` 采用双轨记录：

- `NewsArticle.ranked_revived_at` 是候选窗口查询和排序使用的 nullable/indexed 时间字段，历史文章默认 `NULL`，不做回填。
- `decision_reason.ranked_revival` 保存可读审计信息，包括唤醒时间、来源站点、来源模式、原 workflow/automation/translation 状态和执行动作。

这样既保证发布窗口查询简单可靠，也保留后台和窗口账本排查所需的上下文。
## 为什么术语种子数据准备先用 HKJC 体系和 WP Stud 且先审核不入库

当前多地区新闻源已经上线，但正式术语库和术语候选池仍主要是日文内容。为了补齐香港和国际赛马新闻的中文译名基础，第一批术语种子数据准备选择 HKJC 体系和 WP Stud：

- HKJC 体系包含较权威的中英文、繁中/英文对照，适合作为香港和国际赛马译名的主来源。
- WP Stud 属于高质量民间整理，适合作为别名、补充候选和译名冲突佐证，但不直接等同官方译名。
- 当 HKJC 和 WP Stud 都有译名时，以 HKJC 作为主译名，WP Stud 进入别名或备注；只有 WP Stud 时，作为需要人工审核的主译名候选。

第一版只输出 `seed_candidates.csv` 和 `seed_conflicts.csv`，不直接写入 `TermEntry`，原因是：

- 术语会影响翻译、自动评分、标签和发布校验，必须保持正式库可信。
- 种子候选需要人工审核冲突、繁简转换、地区归属和术语类型。
- `seed_candidates.csv` 严格兼容现有 `import_terms` 字段，便于复用已验证的 dry-run 与幂等导入流程。
- 所有中文目标译名统一输出简体中文；来源为繁体中文时，先做繁简转换并保留原始繁体证据。

`2026-07-03` plan-eng-review 后补充锁定：

- 第一版 HKJC 只做稳定 HTML/文本入口，`racecards` PDF、排位表 PDF 或网页排位表全量抽取延后。
- 实现前必须先做 HKJC 与 WP Stud source discovery，固定 URL、字段、fixture 和不可用入口。
- 默认输出目录为 `runtime/termbase_seed/<timestamp>/`，不得覆盖正式 `server/stable/data/terms_seed.csv`。
- 若新增繁简转换依赖，必须同步 `requirements.txt` 并测试；触网执行必须记录 timeout、非 2xx、解析失败和 incomplete 来源。

`2026-07-04` `prepare-hkjc-overseas-termbase-seeds` plan-eng-review 后补充锁定：

- HKJC overseas 精确 Race Card 输入使用可重复的 `--hkjc-overseas-race RaceDate=YYYY-MM-DD,Racecourse=<code>,RaceNo=<number>`，参数格式错误时必须拒绝执行，不能静默回退到自动发现。
- 渲染 fallback 只作为人工审核种子准备的可选能力；本变更默认不把 Playwright、浏览器二进制或图形系统依赖加入生产镜像。
- 若直接请求无法得到 Race Card 内容且没有可用渲染器或渲染后缓存，命令必须记录 `render_fallback_unavailable` 或等价原因，并把结果标记为 `incomplete=true`，不能把缺失当作空数据成功。

## 为什么术语最终导入不强行合并既有日文 alias 占用

HKJC 官方来源适合作为国际和香港赛马术语主译名，但生产库中已经存在大量日本日文主词和自动维护的日文 `TermAlias`。当 HKJC 日本马英文词条需要补日文 alias 时，如果对应日文名已被既有词条或 alias 占用，直接把 alias 迁移或复制到英文词条会产生两个风险：

- 中文目标一致时，强行合并会破坏既有日文词条的历史引用和审核痕迹。
- 中文目标不一致时，例如 `Raijin / ライジン` 或 `Scintillation / シンチレーション`，强行合并会把不同概念或地区译名折叠到同一个词条，影响翻译保护和术语应用。

因此 `2026-07-06/07` 最终术语导入采用保守策略：

- HKJC 英文词条保留官方主译名和地区。
- 只在无冲突时补充日文 alias。
- 已被既有日文主词或 alias 占用的日文名记录为 skipped，不自动迁移、不停用官方英文主词。
- 后续如果要合并个别概念，必须通过人工审核确认是同一匹马、同一中文目标和同一适用地区后，再单条处理。

## 为什么文章地区采用“主地区 + 关联地区”而不是覆盖原字段

`NewsArticle.racing_region` 已被发布窗口、配额、QQ、公开筛选和历史数据大量使用。直接把它改成多值字段会让配额归属和旧查询同时变复杂，也会影响已经发布文章的兼容性。

因此 `2026-07-10` 的多地区归属实现采用：

- `NewsArticle.racing_region` 继续代表主地区，决定发布窗口配额由哪个地区消耗。
- `NewsArticleRelatedRegion` 记录关联地区，用于地区 tab 可见性、QQ 群订阅匹配和运营汇总。
- 自动归属把赛事/赛场信号和国家、对象、机构上下文分开：只有明确赛事或赛场证据可进入“赛事地优先”，一般国家形容词只作为对象/上下文地区；来源 URL 和来源备注不参与内容归属，避免来源路径污染判断。
- 默认开启关联地区查询，但保留 `MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false` 作为回退开关，可以临时让首页地区查询、公开卡片/详情地区展示、发布窗口、QQ 即时推送/窗口和地区审计全部退回只看主地区；关联地区数据不删除。
- 发布窗口可以看见关联地区候选，但未发布文章只由主地区窗口真正发布，避免同一文章被多个地区窗口重复发布。
- 后台归属锁定使用显式开关：勾选后后续自动归属和补跑不得覆盖运营最终判断；取消勾选后允许后续自动识别，普通正文编辑不会强制把开关重新打开。
- 文章编辑页把“新版字段存在但没有选择任何关联地区”解释为明确清空；只有完全没有新版字段哨兵的旧请求才保留已有关联地区，避免兼容逻辑阻止运营纠错。
- 对外展示必须以主地区为第一语义：列表使用“主地区 · 相关：…”紧凑格式，详情页和 QQ 分开显示主地区与关联地区；固定地区排序只用于关联地区内部排序。
- `2026-07-10` 审查决定：本轮不禁止后台将 `other` 保存为关联地区，保持现有兼容行为；服务层仍不把 `other` 当作有效地区集合成员。
- 重处理命令的 `--limit` 表示最多处理多少篇有效门禁候选，而不是最多扫描多少篇人工审核文章；审计输出必须说明扫描数和是否仍有更多候选。

这个设计让法国来源报道英国赛事、法国育马/拍卖相关海外赛事、爱尔兰内容暂归英国等场景可以进入多个地区池，同时保持配额和发布责任单一。

## 为什么 QQ 推送默认不放行所有内容类别

多地区新闻池扩大后，如果 QQ 按“地区命中即可推送”，普通 tips、营销投注建议、一般官方公告、拍卖/育马机构新闻会显著增加群消息量，且比网页发布更容易触发用户疲劳和平台限流。

因此本期 QQ 自动推送采用配置白名单：

- 默认允许 `news / preview / result_brief / feature` 和必要的旧兼容分类。
- 默认不允许 `tips / sales_breeding / official_notice / racecard_update` 自动群推。
- 无法可靠分类的 `other` 默认也不自动群推，必须由生产配置显式放行。
- QQ 群订阅匹配按“群允许地区”和“文章主地区 + 关联地区”求交集；同一文章对同一群仍由 `QQPushDelivery(article, target)` 唯一约束保证只发一次。

如后续运营确认某类内容适合群推，只需调整 `MULTIREGION_QQ_ALLOWED_CONTENT_CATEGORIES`，不需要改代码。

## 为什么人工审新闻补术语先写 pending 文件

逐篇检查已发布新闻时，单篇文章可能同时包含新增词条、既有词条缺跨语言 alias、以及其实已入库但已发布稿未回填的情况。如果每篇都立即写线上术语库，会增加频繁备份、dry-run、导入和回填的操作成本，也更容易把待确认译名与已确认译名混在同一次生产变更里。

因此 `2026-07-07` 起，人工审新闻补术语采用“审阅与生产写库分离”：

- 审新闻时先把待入库记录写入 `runtime/termbase_seed/manual-pending-terms.csv`，记录来源文章、参考源、动作类型、术语类型、原文语言、目标译名、待补 alias 和既有词条 ID。
- `action=create_term` 表示新增正式词条候选；`action=add_alias` 表示只给既有正式词条补跨语言 alias，不能重复建概念。
- 攒够一批后再统一执行生产备份、dry-run、正式导入和验收。
- 成功写入线上库的记录必须从 pending 文件清理或改状态，避免下一批重复导入。
- 已发布文章展示是否更新是另一件事：术语入库后仍需显式回填或重应用术语，不假设历史稿会自动变化。

## 为什么美国 2026 赛事详情先用 TOBA + HRN，而不强抓 Equibase chart

2026 美国分级赛基础范围以 TOBA 官方 American Graded Stakes 表为准；TOBA 表提供赛事、日期、赛场、等级、字段和部分 Equibase chart URL，适合定义“哪些比赛应进入赛事日历”。

赛后详情方面，Equibase chart HTML/PDF 入口当前返回 `Pardon Our Interruption` 防护页，不应尝试绕过风控或把防护页当作可解析来源。因此本轮详情导入采用：

- TOBA 官方表确定 2026 已完赛 Grade 1/2/3 范围，并优先使用 TOBA `chart_url` 中的 RaceNo 辅助匹配。
- Horse Racing Nation track-day 页面作为可访问公开来源，提供出走表和可见结果顺序。
- HRN 马名展示字段剥离 `(IRE)/(GB)/(SAF)` 等国籍后缀，原始写法保存在 `source_refs.horse_name_raw`。
- HRN 未公开 payout / also-rans 结果块的赛事，只导入出走表，不从 TOBA `winner` 字段猜完整名次。

这样能先让前台展示美国已完赛分级赛的出走表和可确认赛果，同时保留来源边界；后续若 Equibase 或赛场官方 chart 有稳定可访问入口，再用更权威来源覆盖对应 `results` 模块。

## 为什么 2026 赛事详情补齐允许显式映射和取消状态修正

2026 年五地区重赏赛事详情补齐时，部分基础赛程表与赛后结果页存在真实世界差异：赛事可能取消、延期、改场地，或者赞助名 / 标题发生变化。如果继续只靠日期、场地和标题模糊匹配，会有两类风险：

- 真正取消或废止的比赛被错误标记为“已完赛但缺赛果”，导致前台长期显示不完整。
- 法国、英国这类标题变化较多的赛事被漏配，或者在同一天多场同级赛之间误配。

因此本轮采用以下规则：

- 源站明确 `ABANDONED` 或 meeting abandoned 的赛事，改为 `cancelled`，不再追赛果；前台显示“取消”，且不显示赛果表。
- 改期 / 改场地赛事，以结果页实际出走日期和场地修正 `RaceEvent.local_date / racecourse`，同时在 `source_refs.manual_detail_import_audit` 留下证据摘要。
- 法国 ZEturf 对漏配的 8 场使用显式 R/C 映射，不再扩大模糊扫描；显式映射只用于已经通过页面标题核对的缺口场次。
- 美国 Equibase chart PDF 后续恢复可访问后，用于补齐 HRN 未公开完整名次的四场赛果；马名仍通过既有 HRN 出走表按马号对齐，避免 PDF 抽取中的缩写或排版误读。
- `RaceEventHistoryWinner` 本轮只从已确认赛果第一名补 2026 当前年度冠军，用于避免前台“近年冠军”空白；这不代表完整历届冠军已经完成。完整历届冠军仍需后续使用地区官方历史源补齐。

## 为什么 2026 历史冠军按地区分层导入

`RaceEventHistoryWinner` 会直接影响赛事详情页的“近年冠军”展示，因此历史冠军不能只靠模糊搜索或二手页面批量填充。本轮采用按地区可信源分层的方式：

- 日本 JRA：JRA 官方年度重赏一覧历史页覆盖 `2002-2026`，可稳定按赛事名和历史别名映射，因此导入完整年度范围。
- 日本 NAR：`keiba.go.jp` ダートグレード特设页只稳定公开“過去5年の競走成績”，因此导入近 5 年，并为已完赛 2026 场次补当前年度冠军。
- 香港：HKJC 官方 `getSeasonRaces` 接口和繁中单场赛果页能稳定覆盖当前 2025/26 马季对应赛事的 `2023-2026` 结果，因此导入 4 年近年冠军，并统一繁简转换。
- 美国：TOBA 官方年度分级赛表能稳定提供 `2023-2026` 的 Grade 1/2/3 winner 字段，因此导入近 4 年；赛事名变体只处理可解释的赞助前缀、`Invitational`、`S.` 尾缀和 `formerly` 前身，不使用模糊匹配直接写库。
- 英国、法国：官方结构化历史源仍未找到；`2026-07-07` 后续先用 Sporting Life previous-winners 链和 Wikipedia winners table 作为可追溯补充源扩展近年冠军，并保留 `source_refs`，未来找到 BHA / France Galop 官方结构化源时优先覆盖。

美国 `INDIAN SUMMER S.` 在 TOBA `2023-2026` 分级表中没有可靠历史前身，本轮保留为空，后续交由人工或新增官方来源确认后再补。

## 为什么英国 / 法国近年冠军先使用可追溯补充源

`2026-07-07` 继续补齐 2026 年重赏赛事近年冠军时，英国和法国没有找到能批量、稳定映射到现有 2026 底表的官方结构化历史冠军源：

- 英国 BHA 当前官方资料主要适合定义赛程、等级和基础赛事范围；未提供可直接批量解析并映射到 2026 每个赛事 series 的 previous winners 表。
- 法国 France Galop 官方结果入口当前重定向到认证页；官网 `Historique` 页面多为叙述文章，适合人工佐证，不适合作为统一结构化导入源。

为了让赛事详情页先具备可用的“近年冠军”展示，本轮采用以下补充策略：

- 英国使用 Sporting Life 结果页里的 `last_years_winners / previousWinners` 链。该来源已经用于英国出走表 / 赛果补齐，页面可缓存、可追溯；Flat 页面部分可回溯至 `2020`，Jump 页面多数只稳定提供当前年度冠军。
- 法国使用英文 Wikipedia race page 的 winners table，并合并已确认 2026 当前冠军。该来源明确标记为 `wikipedia_winners_table`，不视为 France Galop 官方数据。
- 所有补充来源都写入 `source_refs`；后续若找到 BHA / France Galop 官方结构化历史冠军源，应优先覆盖同一 `RaceEventHistoryWinner` 模块。
- 对无可靠匹配或无结构化表的赛事保留为空，不使用模糊搜索结果强行写库。

## 为什么赛事编排必须使用独立应到清单和运行级请求预算

实际候选不能作为覆盖率分母：抓取器整体失效时，候选文件可能为空；若审计只遍历候选，反而会把“什么都没抓到”误判为没有缺口。因此 `orchestrate-race-event-data-crawls` 在真实网络请求前只根据已校验 plan 与正式 `RaceEvent` 生成不可静默缩减的应到快照，并绑定 plan SHA-256。coverage 必须逐项对照应到清单，空候选、缺失目标、计划外候选和 series 不一致都阻止后续流程。

应到清单本身仍可能因为运营计划漏项而不完整，因此第一批真实抓取增加人工复核层：review CSV 展示赛事中英文名、年份、地区、slug 与预检状态，由用户确认范围；没有确认就不启动首批网络抓取。程序负责发现结构错误和底表缺失，人工负责判断产品范围是否少了或多了赛事，两层彼此独立。

限流必须按整个 run 计算，而不是给每个 adapter 各发一份额度。否则 adapter 越多，总请求量越可能按倍数放大。所有默认网络 adapter 因此共享持久化 `request_budget.json`，失败请求也占额度，resume 继续累计；预算证据损坏时 fail closed。prepare 另行生成 run 级 combined candidate，避免人工拼文件时漏掉某个地区或模块，并让 coverage、dry-run 与 apply-check 始终绑定同一候选身份。

同时，前台模板已调整为只有存在 `history_winners` 时才展示“近年冠军”区块，避免无数据赛事出现空标题。

## 为什么马匹详情页先走受审核的产品层，而不是直接暴露术语或外部表

`2026-07-07` 马匹详情页 MVP 提案已锁定为独立 `HorseProfile` 产品层，不能把 `TermEntry` 或 `ExternalHorse` 直接当成公开详情页。原因是术语库负责翻译保护和概念识别，外部表负责来源抓取证据；公开马匹页需要审核状态、展示名快照、简介、重点新闻、血统、参赛履历、关注关系和人工覆盖痕迹，这些都属于产品层能力。

因此第一版采用以下规则：

- P0 马默认由 active `TermEntry(term_type=horse, target_zh nonempty)` 生成 `HorseProfile` 草稿，但前台不可见；后台审核补充后手动发布，状态为 `draft -> ready -> published -> hidden`。
- 管理员允许强制发布空壳页；未发布或隐藏的马匹详情页在前台返回 `404`。
- 公开 URL 只使用唯一 ID：`/horses/<id>/`，不使用 slug，避免马名、多语言和改名带来的长期兼容问题。
- 展示字段优先使用 `HorseProfile` 快照，再回退到绑定的 `TermEntry`；术语变化不应自动改写已人工确认的马匹页展示。
- 文章马匹关系使用 `ArticleHorseLink`，前台和关注流只消费 `auto/manual`，不重新扫描正文；人工移除写入 `removed` 并保护不被自动重建。
- 关注功能对匿名普通用户开放，使用 `follower_token + cookie`；首页新增“我的关注”模块，展示关注马匹及可选子孙代的相关新闻。
- 马匹与比赛关系使用 `HorseRaceRecord` 记录参加过的比赛，并从获胜记录派生重点胜利；第一版前台先展示重点胜利和关联赛事，不做完整履历表。
- 血统展示必须尽力补齐完整二代，六个文本字段齐全才算补全成功；文本足够用于展示，只有能高可信绑定时才链接 `TermEntry` / `HorseProfile`。
- 外部资料补全覆盖所有地区 P0 马，必须先 dry-run，输出补全成功/失败占比和具体失败原因；高置信唯一匹配才写草稿字段，歧义或冲突进入 `HorseProfileDataCandidate` 供后台审核。
- 日本来源优先参考 `netkeiba` / `JBIS`，并把 GitHub `new-village/KeibaScraper` 作为可信参考来源或可选依赖候选；香港、英国、法国、美国分别以 HKJC、Sporting Life / Racing Post、Geny / France Galop、Horse Racing Nation / Equibase 为第一批候选来源。

## 为什么马匹关注 token 只在 cookie 明文存在，数据库只存 hash

马匹关注第一版不引入注册账号，但匿名 `follower_token` 仍然代表当前浏览器的关注身份。如果把明文 token 写进数据库、日志或 artifact，一旦后台导出、错误日志或调试文件泄露，别人就可能复用该 token 查看或修改关注列表。

因此 `horse-profile-page-mvp` 工程审查后锁定：

- 浏览器 cookie 保存签名随机 `follower_token`。
- cookie 使用 `HttpOnly`、`SameSite=Lax`，并随 HTTPS 安全 cookie 配置启用 `Secure`。
- 数据库 `HorseFollow` 只保存不可反推的 `token_hash`，不保存明文 token。
- 关注 POST 继续使用 Django CSRF；服务端从 cookie 解析 token，前端脚本不读取 token。
- 页面 HTML、URL、日志、补全 artifact 和运行报告都不得输出明文 token。

这样可以保留匿名关注的低门槛，同时降低数据库或运营 artifact 泄露后的横向风险。

## 为什么马匹外部补全 commit 必须读取已审核 artifact

马匹资料补全会写入 `HorseProfile`、`HorseProfileDataCandidate` 和 `HorseRaceRecord`，一旦把错误血统、错误马匹匹配或错误参赛记录写入产品层，会影响公开详情页、关注流和后续人工审核。外部来源又存在限流、同名马、地区差异和字段缺失，不能让 `--commit` 一边实时抓取一边直接写库。

因此本变更要求：

- dry-run 先输出 source evidence、before/after diff、补全状态、失败原因和未补全占比。
- commit 必须读取同一批次已审核 dry-run artifact，并要求显式确认参数。
- commit 只能写入 artifact 覆盖的马匹和字段，不得重新抓取外部来源后绕过审核直接写库。
- artifact 缺少 batch id、生成时间、source 摘要、diff 或审核确认标记时，命令必须拒绝写入。
- 回滚优先使用 commit artifact 中保存的 before 值；大范围异常再使用生产数据库备份。

这个约束和现有术语合并、文章术语回填的“先生成可审 diff，再 apply 已审核 artifact”保持一致。

## 为什么赛事历史抓取必须从已审批应到清单生成输入

赛事抓取器原先可以读取工作区共享 `events.csv`。即使 coverage 最后能发现多抓或漏抓，让真实网络请求先访问计划外赛事仍会浪费请求额度并增加被来源限流的风险。因此 `orchestrate-race-event-data-crawls` 锁定以下门禁：

- run 创建时从 plan 与正式 `RaceEvent` 生成不可静默缩减的 `expected_targets.json`。
- 运营审批固定的 `review/expected_targets_approval.json`；批准状态、批准人、批准时间和应到文件 SHA-256 缺一不可。
- 网络 prepare 从已审批应到清单按地区生成 `input/events_<region>.csv`，adapter 不再以共享旧 CSV 决定范围。
- coverage 只接受显式 `approved` mapping；空模块、缺来源 URL 都视为 blocker。
- apply-check 再次对账应到 SHA-256，完整读取 gzip 备份，并要求每个实际写入范围都有完整批准元数据。

这样即使赛事抓取工具、应到清单或人工文件任一环节损坏，系统也会停止，而不是以不完整数据继续写库。

## Code review 的协作边界

- 纯技术问题，包括正确性、安全性、数据一致性、测试、性能和可维护性，由 Codex 在审查后自行判断并直接修复，不再逐条要求用户批准。
- 会改变产品能力、运营口径、用户交互、公开展示或业务规则的问题，仍需先向用户说明并确认。

## 2026-07-11 赛事抓取第六轮审查取舍

- 修复批量 importer 的部分提交风险：候选保存和正式 apply 必须整批事务化，任一后续模块失败时全部回滚。
- 修复审批后抓取输入漂移：完整 adapter 输入进入应到快照，当前 `RaceEvent` 与快照不一致时必须重新生成和审批。
- 修复混合来源批准拼接：策略 SHA 只认完整 `approved` confirmation。
- 暂不强制所有 importer apply 提供 `--expected-sha256`，保留当前单场人工修复兼容入口；规范流程仍使用 apply-check 生成的带哈希命令。
- 暂不增加请求预算文件锁或 run 并发锁，继续按当前手动、单进程分批方式运行。

## 为什么多地区新闻归属迁移上线后仍保持关闭

`2026-07-11` 生产五地区真实文章 dry-run 表明，当前实体信号可能把来源主地区文章改到另一地区，并可能一次生成三至四个关联地区。例如法国样本 `article_id=7031` 被推断为英国主地区，日本样本也出现改为中国香港主地区。该结果会改变公开地区 tab、发布窗口配额和 QQ 群匹配，属于产品归属口径问题，不能作为纯技术修复自动启用。

因此决定：

- 迁移 `stable.0023_multiregion_news_attribution` 和代码保留在线，避免重复部署与迁移风险。
- `MULTIREGION_ATTRIBUTION_ENABLED=false`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false`，旧行为继续生效。
- 不执行 `reprocess_multiregion_attribution_gates --commit`，不向 `NewsArticleRelatedRegion` 写入本批结果。
- 先由产品侧确认主地区优先级、关联地区最大范围和弱实体信号是否允许改变主地区，再修改规则并重新执行五地区 dry-run。
- 赛事信息编排工具不依赖这两个开关，可独立上线和开始后续应到清单验收。
## 为什么赛事页保留原始人马名并在展示时关联术语库

赛事抓取数据需要保留来源原文，便于去重、追溯、重新匹配和处理术语库后续修订；若把中文译名直接覆盖进赛事明细，术语更新后会产生历史脏数据，也会丢失原始证据。因此赛事页采用展示时批量解析：马名和骑师名精确命中 active 正式术语主原文或别名时显示 `target_zh`，冲突时优先赛事同地区，其次全局，再次其他地区；未命中时原样展示，不自动编造译名。

出马表与赛果是两个不同视图。赛果继续按完赛名次排列；出马表当前五地区按马号自然升序排列，马号缺失时回退闸位，最后才使用来源行序。地区排序映射显式保留，后续若某地区以闸位为主，只调整该地区规则，不改写已抓取数据。
## 五地区分级赛事追溯至 1984 年的范围与完成口径

历史赛事目标采用以下锁定口径：

- 覆盖日本 JRA/NAR、中国香港、英国、法国和美国在 1984 年以来全部 graded/pattern 系列，包含历史停办和降级退出系列，不包含普通赛、让赛和未胜利赛。
- 入选系列从 `max(1984, 创办年)` 保存完整系列史，包含升格前和降级后连续届次，各年使用真实等级。
- 已排期后取消创建 cancelled 年度赛事；当年未举办只记 not-held 证据，不创建虚假 `RaceEvent`。
- 可信完整赛果可派生 runners 并标记来源；年度正式赛果是冠军主事实，缺完整赛果时才使用冠军补位，历届冠军按稳定系列动态汇总。
- 字段冲突按官方当年结果、官方档案/年鉴、高可信专业库、参考来源排序；低级来源只补空，同级或高级冲突人工审核。
- 完整目标可先按批准 scope 写入，暂时不可用和身份待审持续挂账；永久不可得必须双来源证据和人工批准。
- 最终同时报告 accounted rate 和 data complete rate；闭环要求全部年度目标有明确结论，不把永久缺档伪装成数据完整。
- 历史数据不自动创建 HorseProfile、不自动音译正式术语；前台不新增系列页，赛事日历增加年份和名称搜索。
- 达标 historical publication scope 可公开年度赛事并进入分片 sitemap；资料不足、冲突和 not-held 不进入索引。

工程实现使用稳定 `RaceSeries`、年度总账 `HistoricalRaceEventTarget` 和真实年度 `RaceEvent` 三层身份。年度总账拆分客观 expectation 与处理 resolution 状态；逐年分级目录发现入选系列，再通过 lineage/timeline 补足前分级、后降级、取消和缺届。生产网络和 commit 默认关闭，所有批量行为继续绑定 artifact、请求/磁盘预算、备份、原子写入和写后核验。

# 2026-07-12 历史赛事生产执行授权

- `backfill-race-events-to-1984` 准备任务全部完成、测试通过且最终 code review 无 actionable finding 后，Codex 可自主执行生产备份、部署、历史目录抓取、详情抓取、dry-run、分批落库和写后核验，无需逐批再次取得用户确认。
- 自主执行不取消既有安全门禁：总账和批次 artifact 必须锁定 SHA，网络和写入必须受请求/cache/磁盘预算、coverage、备份、原子 scope 和写后计数约束；失败批次停止扩大并保留 gap ledger。
- 生产抓取/写入期间可临时开启 `HISTORICAL_RACE_BACKFILL_ENABLED` 与 `HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK`，但本轮结束时必须恢复关闭。历史年度赛事默认保持 draft，最终线上展示开关暂不开放。

## 2026-07-12 现有年度重复赛事的主记录选择

- 同一年、同一地区的两条记录经官方名称、日期、场地和来源证据确认属于同一届赛事时，不得为了通过系列唯一约束而创建两个伪系列。
- 合并时优先保留已经长期公开、可读且被用户使用的主 slug；后导入记录的官方字段、出马表、赛果、历届冠军、候选和别名迁入主记录，重复子记录在事务断言和备份后删除。
- 本次英国 Gold Cup 保留 `/races/2026/gold-cup/`，BHA 自动 slug 作为搜索别名留存；该规则不授权批量模糊合并，名称相似但实际不同的赛事仍须显式区分。

## 2026-07-12 以 TJCIS 年鉴作为 1998–2026 跨地区目录骨架

- 1998–2026 五地区年度 graded/group 目录先以 TJCIS 官方 International Cataloguing Standards 当年整本年鉴建立共同骨架，再由地区主办方/监管机构正式结果和 timeline 证据补充日期、结果、改名、迁场与前后等级。
- 年鉴是目录权威来源，不凌驾于当年主办方正式赛果；同级冲突继续阻断。Listed/LR 不直接进入本目标 catalog，障碍赛按独立 discipline 解析。
- 该决定不缩短历史深度。1984–1997 必须使用相同产品完成口径继续补源；旧年代未补齐前不得批准完整总账或把部分账本描述为全量完成。
## 2026-07-12 先完成并上线 1998–当前独立年代 scope

- 用户最新执行顺序明确拆为两个完整年代 scope：先补齐并审核 `1998–当前` 总账，再按该总账抓取和写入全部赛事详情，验收后打开该 scope 的正式展示；随后继续调研 `1984–1997` 完整目录。
- 该决定覆盖此前“1984–1997 未齐前不得批准任何总账或详情批次”的门禁，但不降低最终历史深度。`1998–当前` 只有在自身逐年五地区分母完整、来源冲突和身份冲突审核完成、manifest 独立批准后才能写入或公开。
- `1984–1997` 仍是同一长期目标的必做 scope，不得因 1998–当前上线而标记 旧规格流程 change 全部完成或归档。
- 两个年代 scope 必须分别保存 source cache、manifest、approval、请求预算、备份和写后核验；公开开关只能在 1998–当前数据全部验收通过后开启。
## 为什么 P0 马范围扩展到五大地区重点赛事参赛马

`horse-profile-page-mvp` 第一版把 P0 马定义为 active 且有中文译名的 horse `TermEntry`，适合先批量生成后台草稿，但会漏掉没有稳定中文译名、却已经参加五大地区重点赛事并具备资料补全价值的马。P0 马资料补全专项的目标不是只补已有中文译名术语，而是为用户提供重点马匹资料入口。

因此 `complete-p0-horse-profile-data` 规划将 P0 马定义扩展为：

- 当前范围：active 且有中文译名的 horse `TermEntry`。
- 重点赛事参赛马：日本、中国香港、英国、法国、美国全部历史与未来已知 `G1/G2/G3/J-G1/J-G2/J-G3/JpnⅠ/JpnⅡ/JpnⅢ` 赛事参赛马。

重点赛事参赛马必须能追溯到结构化赛事、出赛表或赛果证据，不能仅因外部马名搜索命中就进入 P0。Listed、Open、`LOCAL_GRADE` 和其它等级暂不纳入本次 P0 扩容，后续如需扩大范围另起 change。

## 为什么暂无中文译名的马名术语仍可 active

新版 P0 范围会自然引入一批暂时没有合适中文译名的海外马。如果继续要求 horse `TermEntry.target_zh` 必填，系统会被迫在资料补全前先造一个不稳定中文译名，或者让这类马完全绕开术语体系。前者会污染翻译和前台展示，后者会削弱马名识别、翻译保护、文章关联和 P0 同步。

因此后续实现应升级术语库语义：

- `is_active=True` 表示可信实体可被识别，不再等同于“可中文替换”。
- 暂无中文译名的 horse term 可保持 active，但应有 `translation_status=pending` 或等价状态。
- 翻译、改写和发布校验命中这类马名时，必须保留原文，不得音译、意译或替换为空值。
- 只有 `target_zh` 非空或 `translation_status=translated` 的术语才参与中文替换和中文译名保留校验。

这样无译名马可以进入资料补全、ready 和人工发布流程，前台用外文原名展示并提示“中文名待补”；正式中文译名确认后，再自然升级为普通正式术语。

## 为什么马匹地区不属于身份唯一键

马匹会跨地区参加重点赛事，日本马可以参加美国、香港、英国或法国赛事。`HorseProfile.racing_region` 表达马匹自身归属，赛事地区表达一条参赛证据发生在哪里，两者不是同一个维度。因此 P0 同步不得使用“马名 + 地区”直接创建新身份，也不得因海外参赛覆盖马匹自身地区。

身份判定采用两层证据。第一层是来源命名空间内的 external horse ID，它只证明该来源中的身份；同一来源不同 ID 的同名马可以建立独立资料，不同来源的 ID 则不能仅因相同或不同就自动判断为同一匹或不同匹。第二层用于跨来源归并数据库已有马，必须完整且唯一命中“马名 + 父名 + 母名 + 出生年份”。马名和父母名通过正式术语主名、中文译名和多语言 `TermAlias` 归一，因此 `Forever Young` 与 `青春永驻` 可参与同一身份判断。

`racing_region` 不参与身份唯一性，只表达马匹自身地区；重点赛事地区只写入对应 `HorseP0Source.racing_region`。同一赛事参赛者先按马号、再按来源身份分组，不能在身份分析前按同名折叠。跨来源四元组字段不全、命中多匹或只有同名证据时，系统必须写入专用 `HorseIdentityConflict`、不写主表；该记录允许尚无 profile，保存多个候选术语/资料页、原始身份字段、来源证据和人工解决状态，并每天汇总 pending 冲突通知管理员。全量来源对账遇到仍存在但身份待处理或 URL 暂缺的输入时，不得把既有来源误撤销。暂无中文译名 horse term 的原文保护跨地区生效；同一原名命中多个 active horse term 时也必须保留原文，不能任选一个中文译名替换。

同场参赛身份必须持久化为 `HorseP0Source.participant_key`，不能在内存分组后退化回“赛事 + 马名”查询。该键表达某场赛事中的参赛者，不是马匹全局身份：优先使用规范化马号，其次使用来源身份集合摘要，只有赛事内马名唯一时才使用规范化马名。runner/result 采用马号、来源 identity、赛事内唯一马名的分阶段配对；无法唯一配对时保留独立证据并进入歧义处理。同一个 `participant_key` 最多有一条 active 重点赛事来源，身份纠正时撤销旧绑定并新增 active 绑定，以保留历史审计。

人工审核来源不属于某场赛事参赛身份，不能复用空 `race_event + participant_key` 查找。每匹马最多保留一条 active 人工 P0 来源，应用已审核 artifact 时按 `profile + source_type=manual` 独立 upsert，并由数据库条件唯一约束兜底；审核后一匹马不得撤销前一匹马的人工来源。

P0 补全队列的资料缺口优先级必须显式建模，不能直接按 `completeness_status` 字符串排序。顺序为：空资料、仅基础资料、部分血统、完整二代血统、完整资料但需刷新、完整且无需刷新；需刷新包含在役履历过期或缺同步日期、退役同步日期早于最新赛绩，以及生涯状态未知。同一缺口等级内再按人工标记、pending/conflict 候选、近 30 天公开新闻、重点赛事证据、非空外部身份和术语优先级排序。空 `horse_identity_keys` 不得算作外部匹配信号。

`participant_key` 允许随证据增强从 identity 键升级为 number 键，但升级不能新建第二条 active 来源。同步必须同时使用现有键、`race_runner`、`race_result` 和来源 identity 查找旧绑定：同一资料页原地迁移键，另一资料页则撤销旧绑定后新建。runner/result 两边都有马号且不同属于硬冲突，不能再降级按 external ID 或同名合并，必须写 `HorseIdentityConflict` 保存两边马号和原始记录。

马号硬冲突检查必须覆盖整个赛事 participant 集合，而不只覆盖 runner-result 配对。同一来源 identity 关联两条 runner、两条 result 或混合记录时，只要出现多个非空马号，就汇总成一条 pending `HorseIdentityConflict`，保存全部 runner/result ID 与马号，并阻止该冲突组写入 active P0 来源。

马号冲突不能仅凭 `resolved_profile` 恢复写入，还必须填写 `resolved_horse_number`，且该值必须属于 evidence 中的候选马号。共享任一来源身份键的参赛记录必须先形成完整连通组，再生成一条包含全部成员和马号的冲突，不能按身份键顺序覆盖证据。同步只采用最终马号对应的 runner/result；只有所选成员自身或赛事具备来源 URL 时才允许 resolved。若所选成员无法在本轮证据中定位、URL 后续消失或数据绕过后台校验，下一次同步统一恢复为 pending、清空无效解决选择并记录失败原因，使其继续进入管理员通知。冲突 evidence 保存所有成员和 URL，即使全部无 URL也必须落库；URL 等可补充证据不参与 fingerprint，避免证据完善后复制一条新冲突。

## 为什么 P0 commit 必须逐行逐模块审核

artifact 顶层“已审核”只能表示整份文件进入 commit 阶段，不能替代每匹马、每个模块的人工结论。正式写入必须同时满足：有效审核人、行级 `reviewed=true`、模块级 `approved`、最低置信度、无冲突/失败标记和来源 URL 规则。基础资料、血统、赛事履历、主胜鞍四个必需模块都留下 applied 审计后，系统才允许标记 `complete_profile_full`。

旧 `HorseRaceRecord` 在迁移时优先从 `raw_payload`、其次从 `source_refs` 读取 external race/result ID，并为唯一记录回填同一套幂等键；两处都没有外部身份时才使用自然键，已有重复组保持空键等待人工处理。来源命名空间从 `record.source_name` 或证据中的 `source/source_name/provider/adapter` 推导，用于身份键时统一去空格和 `casefold()`；external ID 统一字符串化并去首尾空格，避免来源大小写或证据空格变化生成不同键。运行期接管空键旧记录时也必须先扫描 `raw_payload/source_refs` external identity：唯一命中时接管并补齐来源名，多条命中时在 importer 与后台编辑路径都停止写入并报告歧义，完全无外部身份命中时才退回比赛名、日期、马场和 URL 等自然字段，避免事实字段修正后生成第三条重复记录。新增、修正、未变化必须分别统计，修正必须保留 before/after。P0 普通同步采用追加式更新，不执行撤销；只有操作者显式选择全地区完整对账时，本轮不再成立的受管来源才标记 `revoked`，并保留撤销时间和原因，不删除历史来源。

所有赛绩写入口必须复用共享的 `stable.services.horse_race_records.upsert_race_record()`，包括 P0 artifact、后台人工候选和后续批量导入；不得另行直接 `create()`。共享服务统一校验比赛名、来源名和来源 URL，生成幂等键，接管唯一旧记录，并在多个旧记录同时命中时停止写入。这样“人工审核”和“批量补全”不会因为走不同代码路径而生成重复赛绩。

后台手工新增和编辑也属于上述统一入口。编辑已有赛绩时需要指定原记录，按编辑后自然键重新生成幂等键；若新键或旧自然键已经属于另一记录，应拒绝保存而不是合并或覆盖。当前不额外实现并发请求争用时的自动重查，数据库唯一约束仍作为最终防重复边界。

人工编辑既有 importer 赛绩不得覆盖 `source_refs/raw_payload`；这些字段保存原始来源证据，不是表单当前值的镜像。手工修改的 before/after 应进入 `OperationLog`，只有从后台新建的赛绩才初始化 `entry_method=manual_console`。

若既有赛绩的 `raw_payload/source_refs` 含 external race/result ID，人工编辑普通事实字段时幂等键必须继续使用该 external ID 和原 source namespace，不得退化为比赛名/日期自然键。只有显式更正外部身份的专门操作才可改变外部身份键。

在役马履历新鲜度只使用一个公共截止日期函数，读取 `HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS`。完整度判断、后台待刷新筛选、后续队列和定时任务不得各自硬编码“早于今天”。

## 2026-07-13 法国新鲜度与归属能力采用先部署、后资格灰度

- 允许先将 `badc10e0` 和 `stable.0029` 部署到生产，但归属模式保持 `off`，相关地区查询、翻译自动重试和失败邮件保持关闭。
- 归属能力必须先完成达到 `150/10/20` 首发覆盖的有效 Gold Set，并通过既定准确率、扩散率、锁定覆盖与性能门槛；单审来源可以使用但不得伪造第二审核人，多人冲突必须裁决。不得以代码已部署替代生产资格。
- 失败邮件固定发往 `754652181@qq.com`，但只有在生产 SMTP 参数配置完成并通过测试发送后才允许开启；无 SMTP 时保持关闭并依赖现有后台/运行日志感知失败。
- 本次验收以 HTTP 运行态为准。HTTPS server 块仍未启用，证书接入继续作为独立运维事项，不与本 change 的代码部署混为一谈。
## 2026-07-13 历史第一批允许完整子 scope 独立写入

- 第一批 45 场不要求为了等待某一地区来源而冻结其他已完整目标；满足当前 target/inventory SHA、审核直链、source cache identity、完整 runners/results 和 production dry-run 的 27 场可作为完整子 scope 正式写入。
- 法国 9 场详情缺口、英国 2000 年 3 场日期缺口和美国 2000/2012 年 6 场日期缺口必须继续留在总账，分别保持 `ready` 或 `pending`，不得用空候选、仅冠军信息或推测日期标记完成。
- 本次写入只改变结构化数据状态，不构成 publication scope 批准。36 个已建赛事继续保持 draft，两个历史开关保持关闭；只有补齐五地区样本并完成前台、搜索、历届冠军、可见性和 sitemap 验收后，才讨论扩大公开范围。

## 2026-07-13 IrishRacing 作为英法历史详情备用源

- 当 Racing Post / France Galop / PMU 等主源只提供沿革证据或当前受反爬限制时，允许 IrishRacing 作为较低权威的正式详情备用源。主源链接与交叉核验证据仍保留，不将备用源提升为地区第一权威。
- IrishRacing 结果页只证明 actual runners 与 results，不冒充 declared runners/racecard。马号和闸位分字段保存，出马表按马号排序；并列官方名次保存在 `official_finish_position`。
- 工程上拆为 `uk_irishracing` 和 `france_irishracing`，即使 host 相同也不允许跨地区候选或 artifact apply。HTTP 200 但显示 `Information Not Available` 的页面必须视为抓取失败。

## 2026-07-13 近年日美来源与字段口径

- 2025 美国平地分级赛由 TOBA 年表定位，直接结果使用可缓存的 Equibase Yearbook 单场页；旧 `tvg` 静态整日 PDF 规则只用于已验证旧年份。
- TJCIS 裸距离按地区显式补单位：日本、香港、法国为米，美国平地为 furlong；美国障碍和英国保存来源中的 mile/furlong/yard 组合。
- Equibase 退赛程序号 `SCR` 内部保存为稳定 `SCR-n`；官方并列名次写入 `official_finish_position`，唯一 `finish_position` 仅作稳定存储顺序。
- 年度权威表赛事名唯一且有工程期移师证据时，允许以当年实际场地定位结果，不因此拆分稳定赛事系列。

## 为什么迁移前进后禁止部署旧应用底座

- 历史赛事能力可以在独立分支长期迭代，但每次生产构建前必须先合入最新 `origin/main`，检查当前生产已应用迁移及所有新增非空字段的创建路径，并运行历史链路与新闻主链路组合回归。
- 数据库已应用 `stable.0027–0029` 后，缺少对应模型/服务写入逻辑的旧镜像即使 healthz 正常，也可能让新文章在数据库约束处失败；因此 healthz 不能替代真实新增 smoke 或近期任务错误日志检查。
- 生产发生 schema/application 不兼容时，优先停止新的 one-off 写入、构建和重启，由单一生产协调线程选择短时回滚或兼容镜像替换。历史批次不得抢占新闻主链路恢复。
- 生产兼容镜像已由单一协调线程完成切换；历史回填线程后续只能在既有镜像上执行已批准的数据操作，不得自行重建、retag 或重启生产服务。任何后续代码部署必须先合入最新 main 并重新交付镜像 ID。
- 历史详情来源必须在整个批次内一对一绑定目标；同一详情 URL 即使仅 fragment 不同也视为同一来源页面，发现复用必须阻断，不得用同日同场相似赛事填充。
- 生产当前运行的组合镜像在历史源码完整进入 Git 前属于临时可运行状态；法港英 150 场日期 apply 完成后暂停详情写入，优先提交源码、推送分支、合入最新 main，并从可复现 Git tree 重建 AMD64 镜像。

## 2026-07-13 生产镜像必须同时绑定最新主线和构建上下文

- 服务器 Git HEAD 最新不代表运行容器最新。每次生产切换必须同时核对容器 image ID、镜像内最新迁移、Django settings 和关键管理命令；任一项不一致即停止切换。
- 多个 worktree 并行开发时，后部署任务必须先合入最新 `origin/main` 并跑组合回归。禁止使用旧分支构建后直接覆盖共享 `umanewsbot:prod`，即使该镜像只想修复另一个模块。
- 暂未全部提交的生产镜像必须至少记录内容 commit、构建上下文树 SHA、完整 image ID 和回滚 tag，并尽快将真实生产源码提交推送。它只能作为短期过渡，不能成为长期部署方式。
- 切换共享 worker 前先暂停 beat，等待 active/reserved/one-off 清空；切换完成后立即恢复 beat，并验证自然抓取、数据库非空约束、五地区页面和错误日志。

## 2026-07-14 新闻实体采用文章级统一仲裁与显式重处理

- 同一篇文章的翻译术语、马名标签、发布校验和自动马匹关联必须消费同一份带跨度、实体类型、证据与冲突结果的文章级解析，禁止各链路独立扫描全术语库后得到互相矛盾的实体。
- 英文人物全名及篇内唯一姓氏回指优先于内部马名候选；普通词和高歧义单词型马名只有在强马名语境中才接受。日文连续完整未知马名先整体占位，接受术语只在占位前应用，恢复后不得再次全库扫描而把父马、冠名或普通短词嵌入完整名。
- 历史误识别只通过显式文章 ID 的管理命令修复，默认 dry-run、逐篇事务和操作日志；提交时可清理本轮机器 provenance 与明确目标旧 `AUTO/CANDIDATE`，但必须保留人工标签、`MANUAL/REMOVED` 关联、公开状态/时间及 QQ 幂等。自然流入规则修复不授权全库批量回填。
## 为什么历史赛事基础字段校正必须独立于详情候选

年度清单和日期来源可能只提供裸数字或地区特有的距离写法，直接物化后不能假设数值单位相同。法国、香港的距离证据通常以米为单位，英国则可能使用 mile、furlong 和 yard；任何统一猜测都会把正确数字写成错误语义。

因此基础字段校正采用独立、哈希锁定的 JSONL artifact：每个目标绑定当前 target/inventory 身份和逐来源快照，dry-run 展示 before/after，apply 保护人工锁并整批原子写入。字段变化后 target SHA 必须改变，已有详情候选必须重新导出、重新打包和重新 dry-run，禁止直接复用旧审批结果。场地、surface、等级、日期和名称的权威修正也复用同一门禁，不允许生产 shell 手改。

## 2026-07-13 多地区归属 Gold Set 原始采样与双审口径（已部分修订）

- Gold Set 候选按五个当前文章地区各 `50` 篇分层抽样，并在来源内轮转，避免高产来源独占样本；抽样前按归属输入 SHA 全局去重，同一正文不能重复计入分母。
- 困难样本选择不得调用当前待测归属算法，避免考生参与出题造成选择偏差。只使用独立的宽地区关键词判断是否疑似同时涉及多个地区；正式跨地区数量只认人工确认标签，2026-07-14 起首发最低为 `20`，后续继续扩充。
- 原计划由 `reviewer_a` 与 `reviewer_b` 独立完成；2026-07-14 起允许只有 reviewer A 的单审集进入资格判断，但不得伪造 reviewer B。若后续存在多人审核，不一致项必须由裁决人给出最终主地区、相关地区和理由。
- 真实正文只保存在被 Git 忽略的审核包；仓库中的正式 Gold Labels 只保留 article ID、source URL、输入 SHA、期望主/相关地区、审核角色、理由和裁决状态。正文、URL、哈希或快照发生漂移时必须拒绝合并或从分母排除。
- 生成候选不等于完成 Gold Set。只有有效分母、五地区数量、跨地区数量和零多人未决冲突均达标，且评估器质量门槛通过后，才允许进入生产 shadow。

## 2026-07-13 单审部分样本原限制（已由 2026-07-14 决策取代）

- 当现实条件无法取得第二位审核人，或审核人明确只抽样部分地区时，允许使用显式 `provisional_single_review` 模式保留已完成工作：有主地区的行进入校准标签，明确 `exclude` 保留，全空行按未选中忽略。
- 该模式不得伪造第二审核角色、裁决状态或来源回退答案；`allow_source_fallback` 未填写时保持未知。输入中的别名和自由文本先保留 raw 值，再输出可审计的规范值。
- 当日“单审无条件 no-go”的限制已取消；`provisional_single_review` 现在只记录审核来源。单审集达到 `150/10/20` 覆盖和既定质量/性能门槛后可进入 shadow，多人审核冲突仍须裁决。
- 覆盖门槛的降低只用于允许首轮 Shadow，不降低主地区准确率、相关地区 precision、无依据变化、过度扩散、锁定覆盖和性能门槛，也不允许跳过 shadow 直接 enforce。

## 2026-07-14 多地区归属 V3 校准决策

- 现有 `159` 条单审标签是本轮固定首发 Gold Set；不伪造 reviewer B、不要求用户继续补标。2026-07-14 复评确认其达到 `150/10/20` 覆盖和全部质量门槛，可进入 shadow；Gold Set 后续仍按新增来源、规则变化、shadow 误判和运营争议持续增长。
- 主地区采用“标题叙事中心优先，但必须有强证据”的分层规则：明确队伍/从业者/核心对象行动或成果可高于赛事；否则明确赛事/赛场优先。普通词马名、单词型歧义赛事、正文历史履历和来源 URL 不得单独改变主地区。
- `other` 是合法的归属与审计值，可表达澳洲、爱尔兰、沙特、迪拜等非五地区证据；它不是新的生产地区，不产生独立发布窗口、配额或 QQ 路由。
- Gold 标签要求的相关地区若只来自对象多年历史参赛地，而文章标题/导语没有可靠证据，自动规则不补齐。此取舍优先保证 precision 和不误扩散，相关 recall 的剩余缺口记录为单审标签/数据证据边界。
- 批量术语匹配采用请求内候选索引，最终仍复用原边界匹配器；不引入跨 worker 常驻缓存。enforce 的 `needs_review` 只保存 `review_candidate`，不得写主地区或关联地区。
## 为什么英制距离必须接受来源紧凑写法但保留原文

英国来源会把 mile、furlong、yard 连写为 `2m4f`，也会把四又二分之一 furlong 写为 `41/2f`，组合后出现 `2m41/2f`。这些是带明确单位的来源格式，不应因为缺少空格而进入距离缺口，也不能先改写为裸小数再猜测单位。

正式解析先保留原始 `distance_text`，再把紧凑 token 和粘连分数拆成结构化 mile/furlong/yard 组件并按固定公式派生米值。香港赛季目标若届次年度与实际比赛自然年不同，必须显式保存 `actual_year` 和跨年原因；不得仅靠日期或 season label 隐式推断。

## 为什么生产备份必须验证恢复文件而不能相信脚本成功文案

低成本 Compose 的 PostgreSQL 主机名 `db` 只在容器网络内可解析，宿主机直接运行备份脚本可能在 `pg_dump` 阶段失败；脚本后续依赖或错误处理不完整时，仍可能打印看似成功的备份路径。部署门禁因此以命令退出码、文件非空、`gzip -t` 和 SHA-256 四项为准，缺一项都不能继续 retag 或重建生产容器。

在备份脚本修复前，允许使用数据库容器内 `pg_dump`、宿主机只负责压缩落盘的回退路径。该路径仍必须生成独立的 `pre-<change>-<timestamp>.sql.gz`，完成完整性校验并记录 SHA-256；失败文件不得覆盖或冒充有效恢复点。

# 2026-07-15：年度赛历按地区与届次年分片，汇总来源只作补充证据

- batch006 的年度赛历 request/cache/parse 不按五个地区粗分，而按 11 个“地区+届次年”scope 执行；每片 target 数不超过 250，parser 的 edition year 和地区边界因此可被 typed recipe 精确证明。
- 同一个年度目录 URL 可以服务多个届次年。网络 cache 对 URL 只请求一次，但 ledger 的 target references 必须精确等于 catalog 中所有引用该 URL 的来源 scope 并集；每个 parse shard 仍只输出本 scope targets。
- France Galop 固定列障碍分组汇总表使用 layout-aware PDF 解析，只补齐逐场详细赛程未覆盖的赛事；同等来源质量下详细赛程优先，汇总摘要不得覆盖详细记录。
- 完整 catalog/selection 与 scope 副本均可作为 stage 输入，但必须保留全量身份校验。少量匹配歧义、来源失败或确认事项进入 evidence-backed gap，并继续其他 scope；未知 parser、身份漂移或分母缺失仍 fail closed。

## 2026-07-18 P0 马真实来源字段统一 fail closed

- provider external horse ID 与完整 `horse_name + sire_name + dam_name + birth_year` 四元身份至少
  有一项，才允许统一 payload 通过身份 validator；候选来源 ID 不得借给另一 provider。
- Sporting Life 缺 breeder/完整二代血统、HKJC 缺明确赛事名或硬字段、HRN 缺明确出生/场数、
  JBIS 搜索与 profile 身份不一致、Geny 429/登录墙/部分履历时一律 blocker，不猜测或合成。
- `Race Index`、年龄、赛绩行数、`sire/dam/damsire` 和地区常识不能代替缺失的赛事名、出生年份、
  starts 或完整 pedigree。JBIS 日本区域只有在页面明确给出 `産地` 时才可把 country 设为日本。
- 并发网络结果只允许第一个完整临时文件通过 `os.link` 发布；所有竞争调用重读并严格校验同一
  canonical cache 后再返回，失败清理临时文件，不持锁跨网络。
## 2026-07-18 P0 马人工补录与多来源合并门禁

- 自动补充来源只允许补齐主来源的空字段，不得覆盖不同的非空值；发生冲突时整匹候选 fail closed，进入人工处理。
- 人工补录采用逐字段审核记录，只允许身份、基础资料和二代血统白名单字段。每条批准记录必须有直接 `http/https` 证据 URL、真实来源名、录入人、不同的复核人和 UTC 复核时间。
- 人工补录在 artifact 中必须标为 `entry_method=manual_review`、`evidence_role=manual_supplement`，adapter key 留空；不得把人工查证包装成自动抓取。
- canonical source cache 只能保存纯自动来源快照；读、写两侧都必须递归拒绝人工 outcome、人工 provenance、人工 supplemental source 和 raw manual rows。canonical payload 的容器只接受精确内置 `dict/list` 和字符串对象键，拒绝 tuple/set、自定义容器子类、非有限浮点值等会在序列化时变形或产生非标准 JSON 的值；迭代检查必须在任何复制之前检测当前活动容器中的循环并限制最大深度，随后用 JSON round-trip 生成纯内置类型副本，不调用不可信 `__deepcopy__`，并在规范化副本上再次检查人工标记，防止欺骗型字符串值或键在转换后变成真实标记。独立 canonical purity gate、完整 source validator 和 cache 写入边界都必须遵守该双检查。磁盘 JSON 解码阶段的深度异常也必须包装为来源错误，统一产生领域 blocker，不泄漏 `RecursionError` 或对象自定义复制异常。自动多来源与人工补录两个合并入口也必须先规范化主 payload 和全部补充行，再执行任何合并。历史污染 cache 或自定义 client 混合 payload 不得进入当前批次，人工补录只作用于本批内存工作副本。
- 原子发布 staging 前必须把冻结人工 CSV 的每个批准字段与唯一 outcome 按候选、字段和完整证据指纹一一对账。只允许 `applied/already_applied/blocked/ignored`；缺失、重复、未知状态、证据漂移或无批准输入的旧 outcome 一律整批阻断。
- 完整生涯不能通过人工字段补录通道写入，也不能由重点赛事列表推导。生涯记录仍必须来自可证明来源总出赛数和全部逐场核心证据的主来源。
- 某地区单马探测已知不完整时，不批量跑该地区 10 匹；先修来源或身份，再用同一匹复验。当前只有日本允许保持已完成结论。

## 2026-07-19 P0 马逐场证据与权威性决策

- 逐场字段证据固定分为 `direct_raw`、`canonical_raw`、`normalized` 三层，每层分别保留值、状态、
  来源、URL、时间和转换规则。Sporting Life 对法国赛事的英式展示只属于直接原始值；没有
  France Galop/IFCE SIRE 证据时，不得把 Class/Grade 映射为 Groupe，也不得由舍入英制距离反推
  官方米制。
- Sporting Life 的法国 `N/A` 不统一解释为缺失。只有法国权威来源能决定其是正式名次、未完赛、
  低名次/未映射结果或仍待补；直接 `N/A` 与权威标准结果必须同时保留。
- 生涯数量完整度与逐场权威性是两个独立维度。官方总数与备用来源行数相等时可记录 `gap=0`，
  但逐场状态仍为 `count_aligned_records_unverified`；只有逐场来源也通过权威核验后才能提升。
- HKJC 首列纯文本 `Overseas` 是有效海外履历，不要求 Race Index 包含数字；主表和页面下方重复
  海外表按稳定记录键去重并保留来源。`F/UR/BD` 等正式异常结果属于实际出赛，`WV/SCR/withdrawn`
  属于未出赛，两类计数不得混合。
- Equibase 受 Incapsula 和许可条款限制，禁止将浏览器绕过做成生产爬虫。短期仅允许人工核验
  `Career Starts` 并保存来源与时间；长期使用 Equibase/Equineline/TrackMaster 授权数据或人工
  Full Charts/Lifetime PP。

## 2026-07-19 P0 马祖父母字段的父母实体反查规则

- 当目标马来源只有父、母、母父而缺父父、父母、母母时，允许查询父马和母马各自的父母并回填
  目标马祖父母；每个字段必须保存来源 URL、核验时间、方法和证据等级。
- 父马反查只接受唯一精确同名候选；出现多个同名候选时不自动选择。母马反查除精确同名外，必须
  与目标马已有母父一致；不允许仅以马名、地区或搜索排序合并。
- 自动来源没有唯一安全候选时，允许人工查看目标马完整血统页、父母资料页、官方/拍卖目录或可靠
  血统页补证。人工补证只填空，不覆盖已有不同非空值；身份条件不符或值冲突时 fail closed。
- netkeiba、France-Sire、Tattersalls、媒体血统页和种公马资料页可作为本批字段级二级证据，但不
  自动提升为官方 Stud Book 值。法国长期以 IFCE SIRE/France Galop、英国及英爱马以 Weatherbys、
  香港进口马以原产地 Stud Book、美国以 Equineline/授权数据复核。
- 祖父母字段齐全只表示“本批血统字段已有可审计值”，不代表整匹马资料或生涯完成；基础字段缺口、
  结果状态待补、官方总出赛数未知和逐场权威性仍按独立维度判断。

## 2026-07-19 P0 马来源可见行与实际出赛必须分离

- 马匹来源页的一行不自动等于一次实际出赛。最终出赛名单未包含的早期报名行、取消赛事中的报名行
  可以保留为可审计履历证据，但 `start_status=did_not_start`，不得计入实际出赛总数或未知赛果数。
- `result_status` 与 `start_status` 独立：实际出赛的正式名次、`F/UR/BD/arr` 等必须有非
  `unknown` 结果；已证实未出赛但无法证明具体退赛原因时，结果可保持 `unknown`，不能猜成
  `scratched` 或 `withdrawn`。
- 人工赛果证据必须完整绑定原始马名、来源马 ID、父、母、出生年份、日期、外部赛事 ID、外部结果
  ID 和规范化赛事名，并且只能精确命中一条记录。身份或比赛不一致、重复命中、实际出赛仍为未知
  结果、来源 URL 或核验时间缺失时整条证据 fail closed。
- 来源可见行数、实际出赛数、未出赛数和权威/来源声明总数分别保存。只有人工最终出赛名单与公开
  生涯总数对账一致时，才可标记 `source_reconciled`；该状态不改变逐场来源本身的权威等级。
## 2026-07-19：五地区暂定赛果可先公开，正式赛果采用独立授权

- TRA 商业 API 的合资格结果可以在完整性、身份、来源权限、event allowlist 和
  provisional policy 通过后直接显示为“暂定赛果”，不等待官方二次复核。
- 官方页面只用于客观赛果事实的 manual receipt；用户于 2026-07-19 确认可以使用这些
  来源，但本期仍固定 `manual_browser_only`、`automation_allowed=false`。permission
  evidence、terms evidence 和 route contract 使用三个独立 digest，不以 contract digest
  冒充条款证据。
- official/corrected receipt 与公开授权分离：receipt 可先保存 staged revision；只有精确
  event authorization、global/region/event official coarse gate、TRA source
  provisional gate 和当前 allowlist/audit 全部成立时才发布。缺少授权时 provisional
  保持可见。
- emergency rollback 不倒删 additive schema 或审计；页面先在 maintenance off 隐藏，
  再以 dedicated provisional pointer 原子恢复投影，并按
  global/region/source -> revalidate -> event 的顺序恢复 policy。

## 2026-07-20 P0 范围批量写入与详细资料边界

- P0 来源同步允许按地区拆分事务，并把无五地区归属的既有中文马名术语另行按固定批量提交；
  该拆分只改变事务大小，不改变 P0 定义、身份规则或来源证据。
- 一次大事务因 OOM 被杀时必须先确认数据库完整回滚、恢复健康并核验备份，再继续较小批次；
  不得把进程中断前的内存进度当成已提交数据。
- “已进入 P0 生产范围”不等于“详细资料已经补完”。基础资料、二代血统、完整生涯和逐场权威性
  仍按独立完整度与字段证据门禁写入；身份冲突继续 fail closed，不因批量范围写入而放宽。
- 本次用户授权覆盖 P0 范围批量生产写入，但不授权猜值、跨身份合并、绕过来源许可或把未审核
  详情 artifact 标成已审核。

## 2026-07-23 netkeiba 标题省略状态与错误分类规则

- netkeiba `.horse_title .txt_01` 合法只含“性别年龄 + 毛色”时，允许状态字段为空；仅接受
  空值或既有明确枚举，出现未知非空状态仍以 `netkeiba_profile_structure: title_status`
  fail closed。英文名必须独立读取 `.eng_name`，不得再从整段标题位置推断。
- `partial_career:` 是已知的证据完整度 blocker，应保留原记录序号和错误文本并归类为
  `source_cache_or_adapter_error`；不得标成 `unexpected_adapter_error`，也不得据此猜测空着顺。
- 上述标题解析会改变 canonical payload，因此 parser version 从 v2 递增到 v3；所有 v2
  Netkeiba cache 与 checkpoint 必须按既有版本门禁失效，不能为节省请求绕过刷新。

## 2026-07-23 公开门户 P1–P3 采用一次性整合发布

- P1、P2、P3 作为同一公开门户版本发布，避免生产出现字体、组件、赛事上下文和关注页模板
  版本不一致；生产验收以提交 `bc7e2df047a20a997de1620688f1c7de4a5c52c4` 为准。
- 视觉改版不得弱化实时赛果公开门禁：暂定/正式状态、policy off 隐藏、冲突复核和 stale 标识
  继续沿用主线逻辑；门户模板只改变呈现，不改变发布授权。
- 未来赛事倒计时以“日”为最小精度；仅在已有发走时间时补充显示时间，不据缺失数据推算小时级
  倒计时。

## 2026-07-23 2026 赛事系列身份治理采用完整审核、单批原子写入

- 正式审核包完整覆盖 2026 target 的穷尽分类；探索快照中的 401 条未关联目标全部进入预期表或
  异常清单，但只有“唯一名称匹配”表允许产生本期动作。
- 名称相同只生成候选，不等于批准。所有非 defer 动作必须有人工作结论、非空说明、锁定的公开
  来源 URL，并通过既有身份引擎的依赖、CAS、人工锁和年度冲突检查。
- 原始 manifest 作为审核包独立信任根，绑定机器文件、原始工作簿和 canonical 行；定稿工作簿
  只允许修改 decision/review_note，不能通过同时修改机器列与哈希自证。
- 首批所有正负动作使用一个互斥 manifest 和一个数据库事务，不拆 shard；若容量或互斥性不满足，
  必须停止并重新设计、复审、授权，不能接受部分首批完成。

## 2026-07-25 HRN 同名机构采用来源级确定性译名，不改全局英国词条

- HRN `.article-body` 内的交互式视频 modal 以 `role="dialog"` DOM 语义在文本提取前删除；
  不使用 `Race Video`、乘号或中文污染词黑名单，普通正文中的同词和非 HRN dialog 不受影响。
- `The Jockey Club` 同时可指美国和英国机构。HRN 英文新闻采用来源级确定性映射“美国赛马会”，
  并与人物术语共用经过字段次数校验的 TERM 占位符；冲突英国 glossary 和生成后映射在该来源
  计划内排除。
- 生产中既有英国词条不修改，非 HRN 来源继续使用原术语解析。未来出现不同来源、缩写或新 DOM
  结构时必须用真实样本另行审核，不扩成全局字符串替换。

## 2026-07-26 本次部署后新发现的同结构污染使用独立 cohort

- 本次发布后使用新解析器重跑了完整权威 cohort，因此没有仅以冻结目标的 apply 数量推算
  `source_clean` 增量。
- 新解析器使 8 篇旧 `source_clean` 文章变为 `source_changed`。逐篇 diff 证明它们属于同一
  已审核 DOM 结构后，本次为其建立了独立 ID-set SHA、candidate、批准、receipt 和
  rollback；冻结 36 篇的 completion 保持不变。
- 本次新发现 8 篇均只移除 HRN dialog 的 `Race Video / ×`，独立 cohort SHA 为
  `f70b56c3aaa4d988c827f28aee076c43199312132be9774c1ccd010a4e51e137`。
- 其中已公开且已有 sent delivery 的文章 `9783` 仅按批准正文更新了数据库与网页，没有重发
  QQ；写前/写后逐篇比对确认 delivery 与公开状态未漂移。

## 2026-07-26 赛事生命周期设计决策（阶段 A 已实现）

- 状态推进与赛果权威分离；时间规则按 IANA 时区执行；cancelled/postponed/finished 为终态。
- 时区合同：日本→Asia/Tokyo、香港→Asia/Hong_Kong、英国→Europe/London、法国→Europe/Paris、
  美国→manifest 逐场审核 America/*；其他 region fail closed。
- 默认 mode=off，所有配置关闭；不接入 provider、不改新闻门禁、不 dispatch race-live。

## 2026-07-26 The Racing API schema v2 proof 路由必须显式绑定地区

- schema v2 proof 禁止隐式默认英国；调用者必须显式给出 registry 中已审核的 region。
- 单次 proof 固定顺序为该地区 `racecards today`、`racecards tomorrow`、无地区过滤的
  `results today skip=0`，最多 3 请求；所有 URL 均由 registry v2 route contract builder
  构建，并继续受 HTTPS host、请求参数、15 秒超时、2 MiB、无 redirect/retry 和 1.05 秒间隔约束。
- v2 artifact 只记录本次实际尝试的请求 path，不把未执行路由写成已执行证据；v1 proof
  行为保持兼容。
- runner 修复、独立 review 与真实联网 proof 是三个独立授权点。本地测试通过不构成联网许可，
  当前仍禁止读取生产 secret 或发出请求。

## 2026-07-27 赛前官方数据不得沿用赛果 route 或第三方 authority

- 重点赛事赛前清单以现有产品规则 `P0/P1 或 featured` 穷尽枚举，再用官方 aware post time
  判断七天半开窗口；禁止先挑有数据的赛事后宣称全量。
- `scheduled_post_time`、`actual_off_time`、场地 `local_start_time` 和数据库
  `race_datetime` 是不同语义。赛前计划时间使用现有 `RaceResultPhase.RACECARD`，并在
  field provenance 记录 `time_semantics=scheduled_post_time`；同时保留原始时区、UTC、
  地区时区和中文展示值。不得为这些语义另造数据库 phase。
- 现有 BHA、France Galop、Equibase official route 只覆盖赛果核验，不自动授权 entries；
  TRA 只能是 provisional 补充。provider/region/field/phase/contract version 或许可缺失时
  必须在抓取/写入前 fail closed。
- 当前跨地区每日官方赛前任务为 NO-GO；购买或取得授权来源、完成连续覆盖证据和新的 review
  之前，不创建或启用 beat/scheduler。

## 2026-07-27 P0 出马页 URL 发现与出马数据 apply 分离

- 允许把“官方出马页面 URL 发现”作为独立窄链路建设；该链路只保存 URL 和最小审计元数据，
  不保存页面正文/出马名单，不写赛事业务表，也不改变
  `fetch-upcoming-key-racecards` 当前结构化数据 apply 为 0 的结论。
- P0 范围严格等于 `RaceEvent.priority=P0`。draft/hidden、系列待审或时间证据不足的 P0 不得
  静默丢弃，应进入完整清单并显示 blocker；P1、P2 和 featured-only 不进入本任务。
- 上海时间每日 `06:30/18:30` 运行，冻结绝对 `[start, start+7d)`。同一赛事只保留一个当前
  URL；新 URL 替换旧 URL，瞬时错误或后续 404 不自动清空已确认 URL，较旧运行不得覆盖较新运行。
- 机器 JSON、人工 Markdown 和 manifest 组成不可变 generation，由单一原子 `current` 相对
  symlink 切换；人工固定读取 `current/latest.md`。SHA 计算必须无环，读取者只可见上一完整代
  或下一完整代。
- 模板构造 URL 只能标记 `candidate_unverified`，不得标为 found；found 必须有官方正向存在
  marker 或官方索引精确链接。普通 404 是 `path_unverified`，不能猜成“尚未发布”。
- 保留上轮确认 URL 时，URL 的 `provider/provider_event_id/provider_contract_version` 必须与
  原确认来源一起保留；本轮失败或改源检查使用独立
  `checked_provider/checked_provider_event_id/checked_provider_contract_version`。汇总按本轮
  checked provider 计数，禁止把旧 URL 错误归因到新失败来源。
- 网络在锁外执行，但 outcome 与当前文档的最终 merge 必须在发布锁内重读 `current` 后完成；
  stale CAS 只防旧运行覆盖，不能替代锁内 latest-state merge。
- URL-only 降低了内容复制风险，但用户授权不能替代第三方站点的 robots、条款或自动访问许可。
  每个 provider route 独立 fail closed；确定性构造 URL 可以不联网，索引发现/存在性检查仍须
  受审 contract。

## 2026-07-27 P0 URL route 的 HEAD 与正文抓取边界

- 用户明确纠正前述边界：按受审规则离线生成 URL，再以 `HEAD` 检查精确路径或应用入口，
  不属于本项目所称的网页正文抓取。该决定仅修订上一节最后一条对存在性检查的解释，不授权
  `GET` 正文、HTML 解析、出马字段提取或绕过认证。
- BHA 目标路径未被本轮获取的 `robots.txt` 禁止，并声明 `crawl-delay: 10`。Equibase 实际
  请求 origin `tvg.equibase.com` 的 `robots.txt` 返回 404 且不重定向；不得借用
  `www.equibase.com` 的 robots 规则冒充目标 origin 证据。项目仍主动采用 5 秒最小间隔。
  route 必须按 host 去重并满足最小间隔；无论响应状态如何，`HEAD` transport 都不得读取或
  保存 body。
- BHA 日期变量位于 fragment，服务器无法据此判断该日期数据是否已发布。因此 BHA 的 2xx
  只能标为 `listing_reachable/date_listing`，不能标为单场 `found`。同一批所有 BHA 日期 URL
  共享一次去重后的应用入口 HEAD。
- Equibase 的 `tvg.equibase.com/static/entry/RaceCardIndex{track}{MMDDYY}USA-EQB.html`
  对当前 DMR/CNL 返回 200、伪场地或错误日期返回 404；因此允许按官方
  `track_code + local_date` 发精确 HEAD，2xx 标为 `found`、404 标为 `not_published`。
- France Galop 有效与伪会议 URL 都跳转认证，无法由状态码区分，继续 fail closed；JRA、
  HKJC 保留未来 contract，NAR 继续遵守明确 robots 禁止。
- 该判断不把任何 provider 的历史赛果或正文访问许可扩展到 entries 内容；以后若 route 需要
  `GET` 或解析正文，必须另行形成证据、方案审核和授权。
## 2026-07-27 赛果缺口恢复采用地区化候选源与官方确认双层来源

- 日本缺口直接以 JRA/NAR 官方结果页作为采集和确认来源。
- 英国使用 Sporting Life 生成结构化候选、BHA Results 人工确认；法国使用 ZEturf
  生成候选、France Galop 人工确认。
- 美国优先从 TOBA 发现精确 Equibase chart；TOBA 尚未更新时允许 Sporting Life 生成候选，
  但完整赛果仍须 Equibase chart 人工确认。HRN 日期入口本次已验证失效，不作为该批主来源。
- 第三方候选不得单独写成 confirmed。官方站点的反爬、token 或登录限制不得通过 stealth、
  验证码绕过或未批准自动化规避。

## 2026-07-27 赛果恢复投影与实时公开门禁按 owner 分流

- `historical` owner 的缺口恢复使用 non-live official receipt 和逐场 CAS 投影，不复用
  race-live 的 provisional/publication 授权；`live`、既有 `unmanaged` 以及
  `manual_paused` 的 current result revision 仍经过原实时公开策略读取门禁。
- canonical 去重只隐藏已批准 active duplicate 的日历、首页、周焦点和 sitemap 入口；
  旧详情 URL 保留并指向 canonical 赛事。链接创建必须同地区、同年度、无自环、无链/环，
  且使用 PostgreSQL advisory lock 与 row lock。
- 本地实现、代码审核、部署、联网 candidate prepare、人工 official 审批和生产 apply
  是独立授权点；任一前置完成不授权后续动作。
## 2026-07-27 Sporting Life、ZEturf、HRN 固定为内部参考源

- 用户已与三方确认本站可保留现有解析器并低频使用；项目记录该确认作为当前使用边界，不在
  仓库保存敏感往来内容。
- 三源新增生命周期观察统一为 `internal_reference`：允许内部采集、匹配、版本比较和后台查看，
  不允许公开展示、字段 apply、赛果 authority、新闻引用自动发布或 QQ 分发。
- 内部参考链必须使用独立 run/payload/receipt 模型和只读后台；禁止直接复用
  `import_race_event_detail_candidates --apply`、`RaceEventDataCandidate`、race-live revision/
  projection。
- Sporting Life 不能产生英国 official，ZEturf 不能覆盖 France Galop，HRN 的 payout/
  also-rans 不能冒充完整正式结果。
- 本决定不追溯修改按既有历史赛事审核流程已经导入的数据。未来若要人工采纳内部观察，必须
  另立 change，不在阶段 B0.1 提供 promotion action。
- 阶段 B0.1 只处理现有 parser 的 `finished` 赛后入口，不注册 Celery/Beat；多日观察使用逐日
  manifest-bound one-shot。赛前 route 或无人值守调度属于后续独立范围。
- 阶段 B0.1 与 TRA/官方赛前同步分开 review、开关、联网和生产写入授权；连续观察成功也不会
  自动提高来源 authority。

## 2026-07-27 定时赛果工具新增逐审核包人工采纳 authority

- Sporting Life、ZEturf、HRN 等来源继续保持 `internal_reference`，自动采集成功和完整顺序都不把
  来源升级为 official，也不能复用 official receipt 冒充官方确认。
- 用户对精确 `bundle_sha256 + event_id + reviewed_row_digest` 的明确批准形成独立
  `human_reviewed_reference` authority，只允许当前 event 的当前字段集合进入平台正式赛果投影；
  它不是来源级白名单，也不授权未来 bundle。
- 该路径使用独立、不可变 approval ledger 和逐 event 原子 projection。平台确认时间与官方确认
  时间分开；公开语义为“已人工审核赛果”，不得显示为“官方赛果”。
- official receipt 路径保持原合同不变。任何未审核、digest 漂移、名次不完整或 Also ran 文本顺序
  继续 fail closed。

# 2026-07-27 赛果补缺 candidate source map 升级为 gap-v2

- 决定将美国 19 场恢复目标全部交给 Sporting Life 结果 adapter 生成完整数字顺序候选。
  TOBA 对前 12 场只保留 Equibase 精确 chart 入口、field 与 winner 的 discovery 证据，
  不再作为结果 candidate provider，也不能授权 official confirmation。
- 原因：生产一次性 prepare 中 TOBA 自动请求返回 403，且 TOBA 表只提供 winner/discovery，
  无法满足完整参赛名单与连续唯一名次门禁；同场 Sporting Life 已取得完整顺序，并与 TOBA
  field/winner 一致。
- NAR event 185 不改变 provider；recovery mode 允许在冻结的 `introduction.html` 尚无入口时
  受控检查同目录 `racecard.html`。该行为只在 recovery mode 生效，不改变普通历史详情流程。
- 法国 event `733..736` 在 recovery mode 使用首轮 prepare 已核验的四条精确 ZEturf route，
  下载后必须重验日期、赛场与赛事名，失败不回退宽范围探测。该选择把预计请求数从 35 降至
  4，使美国 19 场改走 Sporting Life 后全批仍可满足 75 请求硬上限。
- 新 candidate source map 版本为 `2026-07-27-gap-v2`。发布前的 40 场合并包仅供审阅，
  source map v2 未部署前不得作为正式 audit/apply 输入。

## 2026-07-28 数据库 migration 采用显式一次性 release task 作为唯一 owner

- 当前 `start-web.sh` 与四条 deploy/rollback 入口都能执行 migration，`up -d web` 后再
  `exec web migrate` 存在真实并发 DDL 风险。
- 设计决定不再把 migration/collectstatic 绑定到常驻 web 启动；两者由共享的 Compose
  one-shot release task 串行执行。标准/低成本 deploy 与 rollback 只调用这一入口。
- release task 前必须停 beat，冻结并完整排空普通/race-live worker，停普通 worker、原本
  running 的 race_live_worker 和 web；release 成功后先启动 web 并等待 `healthy`，再启动
  worker/beat/nginx，race_live_worker 只按原始状态恢复。任一失败均非零并禁止继续。
- deploy、rollback 和手工 release 共享 host-local fail-closed 部署锁与 owner token。内部
  wrapper 缺 token 拒绝，竞争失败者不能释放赢家锁；遗留锁不得自动过期删除。
- 通用 rollback 只接受含 `release_contract_v1` 的目标；首次发布回退到 pre-contract 版本时
  保留新控制面 checkout，只恢复冻结旧 image，由旧 web 作为唯一 migration owner。
- greenfield bootstrap 不在本 change 范围；historical runner initial-install 不等于站点初装。
- 代码 rollback 不等于数据库反向 migration。目标 schema 不兼容时必须显式反向迁移或恢复
  已校验备份，不能只 checkout 旧代码后继续启动。
- 本决定目前处于设计/审核阶段，不是实现或生产授权。

## 2026-07-31 历史年份“重点”按赛事等级展示 G1+G2

- 用户确认：选择历史年份时，“重点”应展示该筛选范围内的 G1 与 G2 赛事，不应依赖当期运营
  `priority` 或 `is_featured` 是否被人工赋值。
- `normalized_grade` 是历史赛事事实字段；`priority/is_featured` 是运营字段，两者不得通过批量
  把历史赛事改为 P1 来混用。
- 现有 旧规格流程 `backfill-race-events-to-1984` 对“重点”的旧定义曾是 P0/P1 或人工置顶，与本
  决定冲突；本地实现已同步旧规格，并保留未选择历史年份及当前年份的运营口径。
- 用户后续仅授权本地实现；本决定仍不授权历史数据写入、发布或部署。

## 2026-07-31 赛事公开自然年与届次年分离

- `RaceEvent.year` 作为公开自然年；已知 `local_date` 时必须等于 `local_date.year`。年份筛选、
  页面标题、canonical URL 和 sitemap 均使用公开自然年。
- 新增 `RaceEvent.edition_year` 表达真正的届次身份；
  `HistoricalRaceEventTarget.year` 与它关联。普通香港马季跨自然年不是延期，不得使用赛季结束年
  冒充届次年；真实延期仍须权威证据和人工批准。
- 公开路径使用统一 registry 承载 canonical/legacy，并在单表内唯一，旧错误 URL 只做 301，
  不保留第二张公开卡片。
- schema 必须拆成三个独立 release：A 为 nullable/兼容层，B 在全库 census 后切换届次唯一约束，
  C 在数据修复 verifier 后增加 non-null/自然年 check。后续 migration 不得提前存在于前一
  release 镜像。
- 全库最终约束意味着 census 不能只检查香港；香港是强制修复子集，其他地区 mismatch 也必须
  分类为合法跨届次、待修或 blocker。
- 用户后续仅授权 Release A 本地实现；本决定不授权生产 census、数据 apply 或发布，Release
  B/C 仍需各自重新 review 与授权。

## 2026-07-31 历史赛历 writer admission 与 canonical path 采用集中事务合同

- 不能把年份合同只放在 `full_clean()`：`RaceEvent.save/create/update_or_create` 对新行和身份
  变更统一调用 `validate_event_years`；已知 identity bulk/update 写拒绝并要求逐条 writer。
- 为兼容 Release A 存量坏行，非身份字段更新不重验旧错误；任何 year、edition_year、
  local_date 或 source_refs 变化仍须重新验证。
- canonical path reservation 是 event 写事务的一部分。event 新建或 year/slug 改动必须同步
  registry；legacy 已占用目标路径时整笔失败，不允许静默覆盖。
- maintenance evidence 仅是外部观测，不替代数据库实时 gate。`0067` 内加入有 enter/exit 审计的
  active gate；普通 writer 在事务内 admission，PostgreSQL 以 shared/exclusive advisory lock
  保证 gate 前 writer 排空、gate 后 writer 拒绝且等待者重新检查。
- repair 的 bypass 不是通用开关，只能在已核验 manifest/action scope 且 exact active gate 的
  apply/rollback 事务内使用。该决定仍处于本地代码复审前状态，不构成生产写入授权。

## 2026-07-31 lifecycle shadow 采用 prepare manifest 与启用分离

- 不直接用现有 `--auto-discover` 或人工 JSON 纳管生产赛事。先以明确 event IDs 生成
  strict schema v2 manifest，再由同一 loader/preflight 完成 dry-run 和 apply。
- 首次纳管入口固定 shadow-only、1–20 场；apply 在单事务内排序锁定全部 event/control，
  对资格、状态、地区、时区、日期/时间、event 更新时间和 existing control 做完整 CAS。
  任一漂移整批零写；相同 manifest 只允许精确 replay，不同 manifest 不更新既有 control。
- control apply 必须在全局 `false/off` 下完成并独立 verify。打开
  `true/shadow` 是针对精确 manifest、赛事范围和观察窗口的第二次用户授权；观察成功也不
  自动进入 enforce。
- `local_start_time` 只是展示 wall-clock，不用于推导 `race_datetime`。当前生产未来赛事
  `race_datetime=0`，所以首批只能验证无时间的当地次日 proposal，不能宣称有时间路径已
  完成线上验证。
- 方案已通过独立审核，用户已授权测试先行与本地实现；实现仍不构成生产 apply、开关、
  commit/push/PR 或部署授权。
- 首轮方案 review 后补充：v2 apply 的 `false/off` 必须是代码硬门禁，不能只依赖操作
  runbook；v1 只保留 dry-run compatibility，永久禁止 apply，避免绕过 v2 合同。
- 实现采用同一 strict loader/preflight 服务承载 v2 dry-run/apply；跨位数 event ID 的
  canonical 排序按整数处理，避免字符串 `10 < 9` 导致 producer 生成后被 loader 自拒绝。

## 2026-08-01 首批近期赛事时间采用“举办地 wall-clock + IANA + aware UTC”原子修正

- 本次写入将 `local_date/local_start_time/timezone_name` 核对为举办地当地时间，未把中文站
  展示时区投影回写为赛事当地字段；`race_datetime` 保存了同一时刻的 aware UTC。四个字段
  在本次 manifest 中保持一致，未只补 `race_datetime` 而留下冲突数据。
- 本次 Del Mar/NYRA 官方结构化页面采用 authority `500`；Racing Post 等已批准可信媒体采用
  authority `200`，未将可信媒体伪装为官方或专业 API。所有本次实际变化均同时写入当前
  `RaceEventFieldAuthority` 与 append-only `RaceEventFieldChange`。
- 本次 8 场修正只解决已人工核对的时间元数据，不自动创建 lifecycle control，不改变
  `RaceEvent.status`，也不构成打开 shadow/enforce、启用 provider 或 race-live worker 的授权。

## 2026-08-01 第二批时间补采继续采用“逐场明确证据，不推断缺失时间”

- 本次 8 月 1–8 日盘点只写入了可由 JRA、NYRA、The Jockey Club 官方页面或已批准 Racing
  Post 逐场核对的 8 场；未找到逐场明确时间的 12 场保持原值，未由赛事日期、首场时间或场次
  顺序推导。
- 本次官方页面字段采用 authority `500`，Glorious Stakes 的 Racing Post 字段采用 `200`；
  `local_start_time/timezone_name/race_datetime` 作为同一时间事实一起核对，未把上海展示时间
  继续保存为日本或英国赛事的举办地 wall-clock。
- 本次生产运行始终保持 lifecycle `false/off`，未创建 control/transition，未改变赛事状态，
  也未启用 provider、shadow、enforce 或 race-live worker。
# 2026-08-01 生命周期适用于所有已纳管赛事，重点属性不再作为资格门禁

- 用户明确决定：赛事生命周期是赛事基础能力，`priority`、`is_featured` 和
  `is_key_race` 不应决定赛事能否自动更新状态。strict manifest 明确选中的合法赛事即使为
  P2/非 featured，也允许进入 shadow；这些字段继续冻结为审计快照。
- 本决定不等同于自动给全部历史赛事创建 control。首次纳管继续使用 1–20 场 explicit-ID、
  strict v2、SHA/CAS、false/off apply 和 shadow-only 合同；全量自动纳管另行设计。
- 用户希望 shadow 不长期停留，决策窗口为 24–48 小时。该窗口用于形成 enforce GO/NO-GO，
  只统计真实跨过边界的赛事；未到期赛事不得记为已完成生产时序观察，enforce 仍需独立 change、
  review 和授权。
# 2026-08-02 生命周期 advance task 复用普通 celery 队列

- 决定将 `advance_race_event_lifecycle_task` 路由到生产普通 worker 已消费的 `celery`。
- 不扩大普通 worker 去消费 `default`：该队列的任务类型和既有消息未在本变更中完成审计。
- 生产 `default` 中既有 2 条旧 lifecycle 消息不清理；claim 过期不等于 stale。后续 R3
  启用前必须确认无人消费 `default`，并在 scanner 后确认新 claim generation 已增长，才可
  依赖陈旧任务防护隔离旧消息。
- 修复发布保持 lifecycle `false/off`；关闭态部署与 R3 重试分别重新授权。
# 2026-08-02 race-data-sync A 采用 provider-neutral ledger 与 schedule fail-closed

- roster 中 HKJC/JRA/NAR/France Galop/Equibase/HRI/TRA/Sporting Life/ZEturf/HRN 保留真实
  source class，但新 reconciliation 不再读取 legacy `authority_level` 决定覆盖；同源新版可修正，
  跨来源异值和 manual lock 进入 `needs_review`。
- 切片 A 可以自动写入非 schedule runner 字段，但 `race_datetime/local_start_time/timezone/status`
  只形成带 observation/contract/hash 的 candidate ledger；C 的 generation/claim/reschedule 未完成前
  任何入口都不得直接改赛事时间或状态。
- provider roster 与 flags 默认关闭。已有 TRA adapter 标记 implemented；其他来源在逐来源 proof 和
  parser fixture 完成前必须保持 `proof_required`，不能因来源可信就伪称采集实现已完成。
- 自动写入必须同时满足 source identity 已审批、automation allowed、adapter implemented、transport
  enabled、apply enabled，以及 global/provider/region/field 四维运行开关；预录 observation 不能绕过
  proof 或已撤销 contract。参赛马外部 ID 必须位于 provider/source identity 命名空间，跨来源只接受
  已审核 `RaceEventParticipantSourceIdentity` 的确定映射。
- `RaceEventFieldChange` 新 decision 受 enum/check 约束，PostgreSQL 通过可逆 trigger 禁止 update/delete；
  raw artifact 删除使用 directory FD/unlinkat 等价语义并在数据库锁内重验，不能依赖 Linux-only `/proc`。
- 空 `source_refs` 的 legacy runner 不代表任何 provider ownership；必须有本来源 ownership 或已批准的
  participant source identity mapping 才能更新。赔率/人气不享有隐式放行；所有字段服从同一 allowlist。
  runner 动态更新时间只随真正 applied 且严格更新的 freshness watermark 前进。raw cleanup 使用稳定
  keyset 分页越过任意数量 held rows，不能用固定扩大扫描窗口近似解决饥饿。
- field reconciliation 的准入结果同时约束 legacy runner 和 canonical racecard revision；关闭态不推进
  revision/pointer，部分字段准入只能把获准后的 canonical state 投影进 revision。单 observation 内发现
  needs-review 必须回滚本轮全部 applied 字段，并完成 tracking checkpoint/claim 收尾；同 observation 在
  后续扩大 allowlist 时按字段补处理，已决字段不重复写 ledger。
- `jockey_id` 等被 strict schema 明确识别的 provider metadata 可保留在 observation，但不自动成为
  writable field、runtime allowlist 或 field ledger。`RacingRegion.OTHER` 不等于 Ireland；只有 event
  source refs 或已批准 source identity 中精确 `race_data_region=ireland` 才允许反向路由，禁止根据场名猜测。
- event/source identity 的 Ireland markers 只要有一个存在的值不是精确字符串 `ireland` 即判冲突并
  fail closed；仅一方存在不冲突，两方存在必须一致，不能用 OR 掩盖相反地区证据。
# 2026-08-08 lifecycle shadow 观察加固采用运行配置握手与单向关闭收敛

- shadow proposal 与 proposal duplicate 均按成功处理，更新 `last_success_at` 并把
  `consecutive_failures` 归零；真实 decision error 的失败计数和退避不放宽。
- scanner 消息携带期望 enabled/mode；worker 配置不一致时零业务写、记录固定结构化错误，
  claim 依靠既有 TTL/CAS 恢复，旧消息保持向后兼容。
- 生产一致性验收采用宿主全量 running-container census，强制核对 expected Compose project、
  release directory、不可变 image ID、release commit 与 flags；只看当前 project 不足。
- lifecycle mode 只允许通过共享锁保护的专用入口在 `false/off` 与 `true/shadow` 间切换。
  任一失败的自动安全目标固定为双 env 和 web/worker `false/off`、Beat stopped；安全收敛自身
  失败时停止 worker/Beat、保留锁和证据人工接管。
- Compose wrapper one-off 采用 canonical grammar；`run` 必须精确以
  `run --rm --no-deps` 开头，子命令前未知/缺值/歧义 global option fail closed。直接原生 Docker
  绕过不属于受支持路径。
- 修复后自然 shadow 样本须重新冻结尚未到 T、至少覆盖日本和英国的 2–4 场；样本不足 NO-GO。
  既有 8 月 8 日 proposal 不自动替代修复后证据，enforce 仍为独立 change。

# 2026-08-09 新地区分级赛以 TJCIS 目录和 provider-bound 官方赛果分层

- TJCIS Blue Book 只作为年度 G1/G2/G3 目录与地区/国家 provenance，不直接证明参赛马；实际参赛必须
  来自对应官方 provider 的正式赛果，并排除 nonstarter/unknown。
- 官方赛果运行以 reviewed manifest 精确绑定 race key、provider、URL、地区、国家、等级与 catalog
  SHA；逐跳 HTTPS allowlist、provider request budget、原始 response SHA 和 parser/policy SHA 全部进入
  checkpoint identity。临时网络错误可精确续跑，确定性解析或身份错误立即停止。
- 年度候选映射只允许 provider identity 或完整四字段身份产生 `bind_existing/create_new`；冲突为
  `ambiguous`，只有马名或来源不足一律 `blocked`，不得因名称唯一就写入生产。

# 2026-08-08 Release B 生产动作只接受 PostgreSQL

- 所有 Release B handoff/preflight/deploy/manual/rollback/forward-resume/control-state retry 和
  historical initial-install 都以 Django live connection 的 `vendor=postgresql` 为硬合同。
- `DB_ENGINE` 名称、artifact 或 catalog 的既有摘要不能替代 live vendor；catalog 未执行也不得视为成功。
- 非生产数据库兼容只存在于 Python 内部测试参数，不提供 management option 或 shell 环境变量旁路。

# 2026-08-08 historical initial-install 使用 durable required intent

- pre-0070 的唯一批准起点是 exact `stable.0067_historical_calendar_release_a`，不是泛化的“任何旧库”。
- initial-install marker 固定 origin、candidate commit/image、DB identity、artifact/lock provenance、初始
  catalog SHA，唯一恢复动作是同候选 `forward-resume`；其他 action/candidate/DB 一律拒绝。
- 允许的中断状态按 Django 实际 plan 固定为 0067、0070、0068+0070、0069+0070、0071；不接受
  0068-only、0069-only 或任意已应用组合。

# 2026-08-08 completion audit 由可信 recovery origin 决定

- `recovery_origin_action` 只能来自 SHA 验证通过的 artifact，并必须与可信 marker origin 一致；不增加
  CLI/env origin 参数。
- initial-install completion 的数据不变量为原始 legacy counts 不变且新 receipt 表为空；repair
  completion 继续使用 reviewed-static production audit。两套审计不得按“receipt 恰好为空”互相降级。

# 2026-08-08 migration leaf 之前必须验证完整 recorder history

- leaf set 与 0068+ plan 不能替代 Django 对全部已记录 migration dependency 的一致性检查；任何早期
  dependency 缺行都以 `migration.history_consistency` 阻断。
- migration 0024 的 event legacy `UniqueConstraint(condition=...)` 在 PostgreSQL 中是 partial unique
  index，不是 table constraint；这是唯一明确例外。historical target 的无条件 UniqueConstraint 才是
  table constraint + backing index，二者分别按真实 catalog 精确合同验收。

# 2026-08-08 rollback control-state 前必须可恢复原控制面

- rollback 从 checkout 到 durable control-state 验签成功之间属于 provisional control window：失败必须
  恢复精确原 HEAD OID、原 branch/detached 语义和原 production image tag，并复核恢复结果；该窗口禁止停服。
- control-state 成功验签后不再回切原控制面，后续失败只允许按 exact target/image/artifact/state 的 pinned
  resume 继续，避免同一次尝试在“回原状态”和“续跑目标状态”之间产生双重解释。
- 通用 resume 不可信任 control-state 自述路径。必须由当前 reviewed host verifier 先完成 nofollow/fstat、
  canonical state SHA 和全 catalog SHA/mode/owner 验证，之后才可执行 state 指定的 pinned resume。

# 2026-08-08 旧镜像 smoke 的数据库认证必须独立前置

- 随机只读角色密码不得通过未引用 heredoc 拼成 SQL；使用 `psql \getenv` 读取受控环境值，并分别以
  identifier/literal quoting 绑定角色和密码，日志与命令参数不得输出密码。
- 权限创建完成后必须从 fixture PostgreSQL 的 TCP 认证入口，以该角色验证身份与
  `default_transaction_read_only`，通过后才允许启动任何旧镜像进程。认证失败属于 harness pre-start
  failure，不得归因于旧镜像兼容性。

# 2026-08-08 固定旧镜像双 partial-state 证据通过技术门禁

- 只有参数化 role auth 修复后，精确固定 image 在 `{0068,0070}` 与 `{0069,0070}` 两态完整通过
  auth/read-only/write-denied、check、health/ping/beat、日志和 digest 不变，才计为 compatibility GREEN。
- fixture env-string、`post_migrate` 或 role auth 阶段的失败属于 setup/pre-smoke failure；即使已安全
  清理，也不能计为兼容性正例或负例。
- 该 GREEN 只关闭发布技术证据缺口，不授权 commit/push/PR/merge、生产部署或 migration。

# 2026-08-08 recovery provenance 只能由 artifact-bound forward-resume 使用

- provenance SHA 表示既有 active marker 的原始 handoff，不是普通发布可继承的默认值。只有新 handoff
  明确且已验证为 `forward-resume` 时才能把它传入 ensure/completion。
- deploy、manual-release、rollback 与 initial-install 必须忽略进程环境中的旧 provenance，并始终以
  当前 preflight artifact SHA 创建和完成本次 intent；否则普通发布可能在 migrate 后才发现 marker
  绑定错误，破坏“迁移前 fail closed”。
- host wrapper 与容器 release task 都执行 action gate。受审 resume 入口从原 artifact/control-state
  恢复精确 provenance；仅凭外部环境变量不能把普通 action 升级为 restricted recovery。

# 2026-08-08 Release B partial unique index 必须绑定精确 owning relation

- 索引名称在 schema 内唯一，但名称、列和 predicate 相同仍不能证明它属于受审业务表。若原索引被删除，
  同名索引可在其他表上重建；只按名称映射会把错误 relation 误当成 Release B 合同。
- 两个 `0071` 索引必须同时匹配当前 schema 与固定 table name：
  `uq_race_event_series_edition → stable_raceevent`，
  `uq_hist_target_active_series_year → stable_historicalraceeventtarget`。
- collector 对受审名称进行补充收集，使错误表上的同名索引进入 validator 并产生对应 drift；对象位于
  其他 schema 时，受审 schema 中索引缺失同样 fail closed。

# 2026-08-08 duplicate equivalence 不得由完整 provenance blob 决定

- 生产 v2 census 证明 12 对香港事件具有相同 series、local date、official HKJC result URL、规范化
  runner/result，但来自相邻 TJCIS season catalog，因此完整 `source_refs` 不同。
- 当前 `_duplicate_identity_sha256()` 把整个 `source_refs` digest 纳入等价 identity，导致这些同赛无法
  标记 equivalent；把它们标记 distinct 又会制造两个产品事件，违反 duplicate contract。
- 决策是 fail closed：当前 census 只作为证据冻结，不制作 overlay/approval。后续 change 应以稳定官方
  赛事身份、核心字段、runner/result 判断同赛，并把 season-catalog provenance 差异保留在独立审计
  ledger；修复须重新测试、独立 review、部署和生成 census，不能复用本次 manifest SHA。
# 2026-08-09 官方赛果 actual-start 与 checkpoint 恢复合同

- 正式赛果中的并列名次合法；DNF/PU/F/UR 等保留为 `did_not_finish`，DQ/DSQ 保留为
  `disqualified`，只有明确 NR/SCR/WD 才排除。未知状态确定性停止，不得静默丢行。
- checkpoint 只允许 `retryable_error` 续跑；`deterministic_error` 必须沿用原错误停止，修改输入或
  parser 后以新 identity/fresh checkpoint 运行。缓存路径必须精确等于 race key 派生路径且位于 output root。
- 外部赛事身份采用规范化完整 URL 并保留排序 query；path basename 只可作为唯一时的生产 diff 显示别名，
  不得参与赛事计数或 participant/manifest 一致性门禁。
# 2026-08-09 Qatar 必须作为 TJCIS OTHER 页中的独立中东国家解析

- 2025 官方 Blue Book 同时在 Part I 与 Part II 列出 Qatar 三场 G1/G3；它们分别被夹在
  Bahrain/Scandinavia 和 Poland/Spain 段落之间，不能用“每页一个地区”或只看目录索引的方式跳过。
- 正确整本计数为 `1494`，新增地区为 `404 = Australia 312 + Germany 42 + Middle East 50`；
  Middle East 国家分布固定为 UAE 33、Saudi 12、Qatar 3、Bahrain 2。
- 官方赛果 URL 不按赛事名自动模糊绑定。先生成 404 行 review queue，再以 SHA 绑定 reviewed mapping
  编译 runner manifest；缺稳定结果页必须作为显式 evidence gap 保留。

# 2026-08-09 新地区 P0 资料阶段先采用 reviewed canonical cache-only

- AU/DE/Middle East 可以复用现有 `p0-horse-source-cache.v2` 完整度、身份、履历和主胜鞍重算合同，
  但未独立批准逐 provider live client 前，不把它们加入旧五地区 rolling network batch。
- 新地区 cache 必须声明匹配的 adapter/provider，并通过基础资料、二代血统、source start count 与完整
  records 守恒；cache 缺失时明确阻断，不回退成临时搜索或手工 placeholder。
- cache-only 是 adapter 入口的不变量，不只依赖默认 source-client factory；即使调用者设置
  `allow_network=true` 并注入 client，AU/DE/Middle East cache miss 也必须在零 client 调用处阻断。

# 2026-08-09 官方赛果 reviewed mapping 必须绑定 canonical URL、provider 与输出包

- 同一 provider/result URL 的 query 参数排序差异不构成两场赛事；duplicate 检查使用规范化
  scheme/host/path/query identity，不能比较原始字符串。
- `evidence_gap` 只能引用本场 provider allowlist 内且含目标年份的 HTTPS 证据，或含目标年份的 TJCIS
  官方目录；不能借用其他国家 provider 的可访问页面作为证据。
- runner manifest 自身绑定 reviewed mapping SHA；summary 再绑定 manifest、gap artifact 和 package SHA，
  避免只拿 runner 文件时丢失审核来源，或三个输出被跨批次拼接。

# 2026-08-09 2025 正式 workflow 必须同时收敛旧七文件与官方新地区分支

- `full_network=true` 不再允许缺少受审 official result 三文件包；否则只会重复产生已知
  `classification_incomplete` 七文件，不能推进八地区目标。
- official_results 与旧 UmaFans races/profiles 并行运行，各自使用独立 checkpoint；任一暂时错误返回
  `75` 并上传完整 stage。恢复来源 run 时 official checkpoint 总是恢复，旧分支仍按 `races|profiles`
  指定深度恢复，避免一条分支失败导致另一条重复触网。
- 只有两条分支都成功，才生成 `graded-race-completion-bundle.v1`；bundle 绑定旧七文件、官方三文件、
  受审三文件包及 package SHA，但保持来源分层，不把旧 partial artifact 单独改名冒充完整。
- workflow 输入目录只用于 literal file read；受审三文件必须先复制到固定 staging 目录并重新通过
  package validator，artifact uploader 只接受固定路径，避免自由目录名被二次解释为 glob 或 `!` 排除。
# 2026-08-09 五地区参赛马资料上线使用 source-bound participant batch

- 本轮明确排除澳洲、德国和中东资料写入；不把已完成的 87 场德国/中东 official-results 研究分支
  误当作 HorseProfile production package。
- 生产 RaceEvent 参赛行缺 provider horse ID 时，不允许按规范化马名直接跨赛事绑定或新建；这些行
  可以进入受审 provider identity probe，但搜索无结果、多解或马名、父、母、出生年不一致必须阻断。
- 旧首批 50 匹 CSV 继续严格要求五地区各 10 匹。年度全量改用单地区、有界、source census 与生产
  manifest SHA 双绑定的 v2 batch contract；每批还必须属于同一份全局无重叠 plan，并通过严格顺序
  execution ledger 的 `claimed -> prepared -> released -> applied -> verified` 状态链。下一 ordinal 只在
  上一批绑定 production release、G3 approval、apply receipt 且写后 verifier 零剩余后开放；由机器拒绝
  跳批、重复、不同 manifest 抢占、stale mapping 并行和最终漏跑，不能只靠 runbook 人工记忆。
- 写后零剩余必须复用生产合同的精确五字段：profile create/update、race record create/update 和 module
  audit；字段集合不得增减，每值必须是非布尔整数 `0`。最终独立只读复审已用 missing/extra/`None`/
  `False`/字符串反例确认这些形状不能进入 `verified`，结论 `APPROVED`、无 P0-P2。
- 同一弱身份马可能在多个保守 occurrence candidate 中出现；正式 production release 必须按批次顺序
  生成 mapping snapshot，并在前一批 verifier 后再生成后续写入候选，禁止一次性冻结多个 `create_new`
  决策后并行写入导致重复档案。

# 2026-08-10 Japan occurrence 身份 enrichment 使用受限 JBIS authority

- reviewed participant occurrence 只有在 `candidate_key` 属于 `observation:event:*`、JBIS 搜索唯一精确
  命中、profile horse name 匹配、search/profile 的父母与出生年一致且 source payload 身份字段完整时，
  才允许 JBIS 补足候选原本缺失的父母、出生年和 provider horse ID。该例外不适用于普通候选、其他地区、
  多解或姓名不一致结果。
- `candidate_source_name=netkeiba` 只表示赛事证据来源，不等于已有 netkeiba horse identity；只有同时存在
  数字 external horse ID 才走 netkeiba ID 直连，否则 Japan dispatcher 使用上述 JBIS 唯一精确路由。
- JBIS `finish=**` 只有 status cell 精确为 `除外/取消/中止/失格` 时才分别映射为
  `withdrawn/scratched/did_not_finish/disqualified`；包含词、空值或其他标记继续确定性阻断。
- 已登记为 `prepared` 的全阻断零写入 attempt 不得覆盖或删除。ledger retry 必须绑定原 completion SHA、
  相同 batch/review identity 和固定 repair reason，并把旧 SHA 追加到 `prepare_attempts` 后回到 `claimed`。

# 2026-08-10 跨来源同赛只能以完整出赛事实保守合并

- provider external identity 和赛名不能单独证明两条履历不同；Netkeiba/JBIS 对同场比赛可使用不同赛事名。
- fallback 等价只适用于不同来源的实际出赛，并同时要求精确日期、规范化场地、公制距离、完赛名次和
  actual result status 相同；双方都有 race number 或 event ID 时还必须一致。非出赛、日期不精确、事实
  不完整或任一冲突都不得合并。
- 多个旧记录同时命中，或 provider/canonical/fact identity 指向不同记录时必须确定性拒绝，不得任选。
- 正式 artifact 在任何写入前必须用与 upsert 相同的解析逻辑计算“现有记录 + 受审记录”合并后的 started
  count，并与受审 official/source start count 精确相等。首次 apply、dry-run 和幂等复核不得各自实现不同
  身份语义。
- 任何改变合并语义的代码都会使旧 production snapshot 与 expected actions 失效；必须闭锁部署后生成
  全新 candidate/artifact/release，并取得新的精确 G3，禁止复用失败批次的授权哈希。

# 2026-08-10 lifecycle enforce 首发只采用双赛事 manifest canary

- lifecycle 的全局 `enforce` 不是公开写入的充分条件；必须同时满足 canonical/active env 与三服务
  settings 的精确 manifest raw SHA/event IDs、control 冻结 evidence、两场共享 active activation ID。
- 首发生产 wrapper 精确限制为 event `186,187`。应用层不硬编码赛事，但生产启用授权和 host wrapper
  都必须绑定同一 raw SHA、release commit 和有序 ID `186,187`；范围外自洽 control 仍 fail closed。
- promotion 只允许在宿主三服务严格 false/off、shared deployment lock 和 PostgreSQL advisory xact
  lock 内写 inactive control；每次 enable 先 disarm，再按 web-only 验证、worker coherence、原子 activate、
  active verify、Beat-last 顺序执行。
- apply freshness 固定 24 小时；runtime validity 固定为最晚 race datetime +30 分钟 +24 小时。一级止损
  永远是无需 manifest 的 false/off；已合法推进的公开状态不自动反向修改。

# 2026-08-28 赛事数据自动化采用 standing policy、确定性来源仲裁和动态 cadence

- 用户本轮明确要求完整自动闭环并覆盖此前逐阶段/逐场确认约束；因此未来公开赛事由一年期冻结 standing
  policy 自动纳管，不再逐场确认。生产部署仍是独立的最终确认点，代码合并不自动扩大生产权限。
- 来源等级固定为 `licensed_api=300 > official_operator=200 > trusted_publisher=100`。更高等级覆盖低等级；
  同等级使用 observation 时间和 provider key 稳定决胜；manual lock 永不被自动化覆盖。
- The Racing API 是新增联网主链，单 task 最多 3 请求；官网层本轮只消费既有 HKJC/France Galop 导入，
  未经独立 proof 不新增官网网络抓取。API 未找到赛果时才依次尝试官方导入和地区可信第三方 receipt。
- 赛时和出马表远期最多间隔 12 小时，临赛加密；状态按 T/T+30 推进；赛果自 T+3 起抓取并在确认后继续
  7 天更正观察。所有 checkpoint 由 claim completion 原子生成后继，避免固定 Beat 与 worker 重复派发。
- 来源报告名次与内部唯一排序分离：`reported_finish_position` 保留 dead heat，`finish_position` 保持既有
  唯一约束。更正追加 immutable revision，不就地覆盖证据。
- 公开页面不显示来源等级、provisional/official 或人工复核标签；这些字段保留为内部仲裁、审计和回滚依据。
- The Racing API 身份发现每轮最多 3 请求，但 provider/日期桶按 UTC 小时轮转，不能固定从字典序头部开始；
  这样所有存在候选的地区在有限轮次内都有机会执行，不会因全局 budget 长期饥饿。
- network 前容量不是“正数配置即通过”：必须在 `RaceDataTransportCapacityLedger` 原子预留 provider/region/day
  请求和最大响应字节，并同时验证 artifact root、high-water、hold 与 free disk。失败只消耗零网络请求。

# 2026-08-28 过期赛果审核 claim 必须显式失败终态，发布门禁不忽略

- 用户已在发现 14 条阻塞后明确授权按本方案处理历史 claim 并修复防复发逻辑；该授权只覆盖备份、精确
  manifest 收口和验证，不覆盖修复后 PR 的最终合并、部署、migration 或自动化启用。
- `claimed` 表示仍有写入所有权，租约过期不等于业务终态；发布门禁继续统计全部 claimed，不增加
  “expired 即安全”的旁路。
- prepare 异常由仍持有原 token 的 worker 写 `failed/prepare_exception`；独立 sweeper 只处理租约过期且
  从未形成 selector、bundle、terminal 或 finished 证据的标准空 claim。其他形态保持 claimed 并告警。
- 历史修复采用 preview canonical manifest SHA + apply 事务锁/CAS，两阶段绑定全部 claimed 行；任一漂移
  整批零写。收口状态使用 `failed/stale_claim_reconciled`，不使用会误示“没有目标”的 `noop`。
- 自动收口只解决运行记录泄漏，不触发重跑。具体 slot 的 retry 是独立运维动作，沿用现有显式入口与门禁。

# 2026-08-28 PR #108 赛果、出马表与生命周期发布门禁收紧

- The Racing API 当日列表只有返回 registry 登记的 terminal marker 才能形成正式赛果；无 marker 的完整
  行只保存 provisional revision，不移动 current 或公开投影。赛后第 1 至 7 天只使用受审精确路由
  `/v1/results/{race_id}`，404 作为明确 not-found，禁止猜测其他历史 endpoint。
- 地区/日期批量 racecard 与 results 使用数据库 single-flight 和 150 秒 complete TTL 共享完整快照；必须
  完成全部分页后才发布 manifest，缺页或预算不足整份拒绝。容量由快照 owner 预留一次，event waiter
  只消费已完成 artifact，不能逐赛事重复扣减整批请求预算。
- 正式/更正赛果必须覆盖 canonical runner 全集且每行都是终态。优先要求已有来源 runner ID 精确相等；
  对仅提供赛果的 fallback，只有 runner 数量、马号与 NFKC 规范化马名构成无歧义全双射时，才在同一
  投影事务原子补充该来源 runner ID。缺行、多解、重复或非终态全部 fail closed。
- data-sync 纳管不再隐式把 lifecycle 切为 `enforce`，也不清除人工暂停；新 control 从 `off` 建立，已有
  mode、pause 和 refresh 原样保留。所有相关写路径统一使用 lifecycle control -> event 的锁顺序。
- T+30 未确认只创建 `data_sync_event` incident，监控任务走普通 `celery`，不派发邮件或旧
  `race_live` 消息。配置审计的 `ready` 只证明 allowlist、route、policy、registry 与容量完整，不要求
  运行开关已打开。
- schedule/racecard/result canonical apply 都必须在网络之后、事务内重新验证来源 review/terms、有效期、
  registry、contract、region/namespace 和 exact claim；观察创建成功不能替代写入时准入。

# 2026-08-30 赛事链生产启用采用业务不变量、冷启动有界等待与进程级内存保护

- future discovery census 的绝对 total/blocked 会随时间自然变化，发布门禁不再固定某个瞬时数字；必须
  验证唯一目标 event 已纳管、其余目标全部以可解释原因阻断、无越权 candidate/decision/provider request，
  并以数据库前后 SHA 证明零意外写入。
- 专用 worker 容器 running 不等于 Celery 节点 ready。启用门禁使用有界重试等待拓扑恰好包含普通
  `celery` 与专用 `race_sync_v2` 两个隔离节点；超时仍 fail-closed，不通过延长锁无限等待或跳过检查。
- 小站资源治理先约束进程而非扩容：普通 worker 单并发/单预取、20 task 回收、256 MiB child 上限、
  512 MiB cgroup；专用 worker 单并发/单预取、384 MiB cgroup；Web 为 2 workers/2 threads。硬资源门槛
  保持不变，任何采样越线仍关闭全部新写入。
- canonical/release env 的冻结容量、持久目录、TLS 根、exact revision 与 registry digest 属于同一发布合同；
  发现配置漂移必须修复并重新审计，不能只依赖容器 image 一致。

# 2026-08-30 小站 Web 采用单进程四线程，运行期越线必须重新开窗

- 激活态任一实时采样低于硬内存门槛，即使服务、Swap、磁盘和队列仍正常，也必须立即 10 false并移除
  专用 worker；关闭完成后资源恢复不能追溯性地把失败窗口改为通过，也不能由 heartbeat 自行重开。
- Web 两个 Gunicorn worker 的实测 PSS 各约 173 MiB；小站生产改为 1 worker × 4 threads，保持原 4 个
  请求线程并减少约 160 MiB 常驻匿名内存。该选择以资源稳定性换取进程级冗余，Gunicorn master 仍负责
  worker 重启；任何健康或吞吐回归都回退 2 × 2。
- PostgreSQL cgroup 的主要占用来自 file cache，`shared_buffers=128MB`；不通过 drop cache、压低正确的
  shared buffer 或扩容来掩盖应用进程常驻占用。继续优先使用 PSS/cgroup 证据和可逆进程配置。
- Web 优化的关闭态热身只证明新配置可运行；恢复赛事链仍需新的全量 preflight、配置审计、资源余量和
  冻结顺序启用，不复用内存失败窗口的激活结论。

# 2026-08-30 扩容后仍保留应用级资源约束与原始终态标记门禁

- 2C/8G 扩容不取消进程上限：Web 保持 1×4，普通 worker 单并发/单预取并提高至 1 GiB cgroup，专用
  worker 仍为 384 MiB；1280 MiB Swap 必须持久化，原 1.5 GiB/512 MiB/8 GiB 三项硬门槛继续执行。
- `race_sync_v2=0` 是阶段切换和关闭态门禁；Beat 开启后的正常运行期允许已批准 enrollment 的合法任务
  短暂排队。必须逐条解码 task/event/data_kinds、限制有界数量并验证自然排空、claim 释放和业务终态，
  不能因 LLEN 瞬时非零误判为积压，也不能 purge/重排来制造 0。
- provider 规范化 payload 中的默认 `race_status=complete` 不能替代原始响应 terminal marker。当天批量
  results 没有受审 marker 时只记录 provisional immutable revision，不创建 canonical results/publication；
  后续继续自然轮询，跨 provider local date 后只走受审 exact race-id 路由。
- Compose 重建 Web 会改变容器 IP；当前 Nginx upstream 在 reload 时解析服务名，因此每次 Web 重建后必须
  先 `nginx -t` 再平滑 reload，并同时验收 root/www，而不能把内部 health 或旧连接的 200 当公网恢复。
