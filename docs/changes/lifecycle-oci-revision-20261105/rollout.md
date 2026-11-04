# OCI revision 归属误判：续期恢复包

## 已执行事实与当前边界

PR #276 已合并为 `c34f3c3d105b81f20452a0813949469a38e2e071`。
用户批准的固定候选 `661a0859242f001853957365fcb8dd7c5ad0ddab` 已完成0079同schema发布，
镜像 `sha256:f8bc53f0a5045bfbb5bd87a7aa0a7d47fd5c70790167d2e2e52ab663a960be2b`。
本次专属 intent `d92a4ea28f94439edeab8aebff3b66a82f381d964c129334a5699435aa357d00`，
manifest `46a94849e985d044610cb0d7a9bcfeabd6f1cbf262c2a61051a3588f2c33d483`，
complete `bcd9acd1df7e83b9abe90c4c6636c8339dc50a50567a61ed94c636f030a278ce`；
备份921,556,775字节，SHA `27603bc68e10bfa31a1c93a0fd2b5b5d60b04323eb0f948cf683ee151d856bb7`。
备份SHA/TOC与同schema发布成功，不代表整库恢复验收。

2026-11-04T17:53:31Z，promotion因外项目通用OCI revision标签被误判而停止，未创建generation3。
同机wechat-summary-worker在17:10:50Z重建，revision为`fa123af836f9990291cddc5ffd0bf2d7750418fc`。
保留全宿主扫描后发现该真实状态变化；本轮未修改该项目。
Web健康、race_sync_v2_worker运行；普通worker与Beat停止，实际Web为false/off。
停止的Beat仍是旧ab5775镜像，不能称四应用发布和授权恢复全部完成。
旧generation2/root `28c327c0897f3c1559dfa99fc9fed76532dc1b1bee6f2ed994db4e680e5bb1a9`仍active且过期。
赛事956行与新鲜只读单成员快照完全不变；TRA已续期且摘要不变。
双域名首页、healthz、956赛事页各返回200；恢复后的10分钟验收尚未开始。

## 修正与自动验证

仅修正通用OCI revision和本项目身份的区分，完整镜像/环境/资源隔离证明仍必需。
本项目镜像级revision（含停止容器，按固定Image ID绑定并缓存）同样受到保护。
测试包含三个同名外服务真实RED、review发现的旧镜像标签绕过RED、标记/资源/权限攻击、
元数据漂移和读取失败。Linux测试使用独立/tmp tmpfs，避免占用已满的共享Docker磁盘；不清理其他线程资源。
真实宿主只读证明使用原始docker ps/inspect/image inspect，不替换Docker输出，不修改发布checkout。

## 待交付的精确对象

- 新固定生产候选：`df2f376a6718f39c3f31694f6b320bdda6e161dd`，基于当前生产661a0859，
  仅修改 `deploy/verify_unrelated_lifecycle_service.py`；不发布主线的其他代码/迁移。
- 新artifact SHA：`8fb7b6447affbfa1dfcb7b77376bdb1d4be06928bf64c2a2e80970d1b1d5d410`。
  approved_commit严格绑定上述候选，只覆盖956，generation3，前驱仍为28c327…。
  membership `f500e2fac984d03df92cc7fa83762425fb2b6bf70a4e540a168bae0ac2ce4a90`。
  apply期限为北京时间2026-11-06 02:03:45；runtime期限2027-12-31T16:00:00Z，覆盖北京时间2027/12/31全天。
- 本地隔离快照已完成dry-run、promotion、activation和active验证，赛事行不变；`production_shape=false`。
- 完整CI、独立复审、候选外核验和组合证据完成后才提供G2选择，结果另记PR与固定摘要；本文件不表示已获新G2。

## 下一次生产执行顺序

1. 实时核对新PR/候选/脚本逐字一致、artifact期限/前驱/单成员和事件快照、现有关闭态与资源。
   **在归档旧锁、构建或停服前，对所有外项目同名常驻容器执行新候选的只读归属证明；**
   在promotion/activation原检查点继续全宿主扫描，不能用预检替代后续检查。
2. 原失败证据目录 `/opt/umanews-census-recovery-20261105` 保留。
   在排他coordinator flock下确认原coordinator191890、promotion200343及锁PID200352均已退出且无复用，
   核对blocked-preconditions.json内锁内容哈希，原子归档 `/tmp/umanews-deployment.lock`。
   如只读lease203762仍存活，先写其stop文件并确认退出、flock释放；已自然退出则证明锁可获取。
   新协调者持续记录owner/thread/operation/SHA/资源域与心跳。
3. 新独立release目录从当前active 661a0859 `.env`复制，分别备份active与canonical；
   两者摘要分别a4dff851…和c1f7dd3a…，canonical含旧QQ漂移，不用作复制来源。
   保持QQ关闭、OneBot停止、TRA及standing policy不变，不操作wechat-summary。
4. 原 `deploy/deploy_0079.sh deploy` 完成新专属备份、SHA/TOC、空迁移、静态及完成收据；
   无新增迁移、不反迁移、不恢复全库。按进入清单恢复Web及race_sync_v2_worker。
5. 在同一coordinator及共享部署锁下，按新镜像与false/off重建启动普通worker，Beat保持停止。
   等待新worker响应，再使用原受保护promotion；每次Web地址变化均nginx -t后平滑reload。
6. 精确新artifact promotion/verify，再运行原switch脚本激活数据库、写true/enforce、重建Web/worker，
   Beat最后重建启动。仅恢复原956范围；不修改赛事事实、不人工触发抓取、不对外发送消息。
7. 四应用镜像/commit、关闭QQ、TRA合同、单成员/root/control/旧root退休、956未变、schema0079和迁移空计划，
   队列/导入锁、worker/Beat健康与双域名首页/healthz/956页均核验。
   恢复后资源达标再开始至少10分钟连续观察；无新OOM/restart、健康错误、资源越线或授权漂移。
8. 归档新intent/manifest/complete、两份备份SHA/TOC、artifact与验证结果，确认共享锁释放后释放coordinator。

失败继续按原受保护关闭态恢复，无法证明则停止普通worker/Beat并保留证据与锁；不回退旧镜像或数据库，
不关闭外项目服务、不绕过census。人工确认统一引用根 `AGENTS.md`；候选和artifact已变化，原G2不覆盖新生产执行。
