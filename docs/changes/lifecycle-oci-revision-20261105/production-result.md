# PR277 新版恢复包执行结果

## 已完成与边界

用户明确选择“选2，合并 PR #277 并执行新版恢复包”。PR277 固定 head `bb059abec358f6b6ec34f90ad2657edf02ab74dd`
已合并为 `c47e03d5c1eba3d03eccf9b30685fcde0d1e2316`。生产只发布获准窄候选
`df2f376a6718f39c3f31694f6b320bdda6e161dd`，镜像
`sha256:3fcf9090af794f98fffa0f33f110e02126b491fd0caab5df6b9dd1be69bc20f9`。
完整CI、10项实际补跑、独立review与两份wrapper复审见PR277原交付记录；本次没有重跑或扩大测试豁免。

北京时间2026-11-05 03:35:35，协调器返回 `verified_complete`；03:36:02最终只读审计通过。
四应用均运行同一候选与镜像，Web健康，普通worker和race_sync_v2_worker响应，Beat最后重建启动。
数据库仍为0079，迁移计划为空，无新增迁移。Nginx已平滑reload。

- generation3/root `8fb7b6447affbfa1dfcb7b77376bdb1d4be06928bf64c2a2e80970d1b1d5d410` 已active，
  成员仅956；membership `f500e2fac984d03df92cc7fa83762425fb2b6bf70a4e540a168bae0ac2ce4a90`。
- 旧generation2已retired；control、artifact receipt、membership及activation绑定只读核验通过。
  activation ID `a63fa003dcd146140b05800f7dd28ecb136cb0b2040111c7cea2355e33730850`。
- lifecycle为true/enforce，生命周期与TRA许可均到北京时间2028-01-01 00:00:00，覆盖2027/12/31全天。
  TRA摘要 `53962c4220c35523ea77ca27e674970bfb555e48e7b6bf86b0472e05cfed1735` 保持。
- 956仍finished，完整事实行摘要 `ce035a7fd156cb9fed11b3383796436e5cc6626c711e668d91dc193a81986588` 未变。
- QQ三开关false、无QQ周期、OneBot stopped/restart=no；旧sent记录不变，发布以来新增发送为0。
  未操作wechat-summary，未扩大抓取、成员或对外发送。

## 实际观察

北京时间03:24:50.912至03:35:35.522，共644.610225秒。19次连续采样：
两域名首页、healthz、956详情共六入口均200，四应用零重启/OOM/健康失败；
负载峰值1.4654，可用内存最低5,573,992,448字节，SwapFree为1,342,173,184字节，均在原门槛内。
终点四应用错误日志计数全0；QQ新增发送、通知、delivery行与重试日志均0，在途QQ任务为0。

终审导入锁0；普通worker消费celery，专用worker消费race_sync_v2。
队列快照celery=80、race_sync_v2=0、race_live=7543、unacked=1，未purge或重新投递。
本窗口INFO日志没有可提取的自然任务成功记录，不能把本次服务/授权恢复验收扩展为新赛事端到端或长期SLA验收。

## 备份、凭据与恢复面

生产release目录 `/opt/umanews-release-df2f376a-oci-20261105/umanewsbot`；
证据目录 `/opt/umanews-oci-recovery-20261105`。旧失败证据保留，旧锁按精确摘要归档。
部署锁不存在，coordinator flock已实测可获取并立即释放；没有遗留运行中的恢复协调者。
两份独立custom-format备份的SHA重新校验，TOC均1401行；没有执行整库恢复，因此不声称实际整库恢复验收。

1. `/opt/umanews-release-df2f376a-oci-20261105/umanewsbot/runtime/migration_history_repair/release-0079-recovery/6dc6606c57d12c0b7c8f940d547c5a59e6f50319c7f9cd1a99cd9f305c0f423b/backup/rds_horse_news_20261104T191112Z_223201.dump`
   大小 `921556775`，SHA `fc93bbaff661d71ea6c6fd5643e8c2ec1ce01dcfe612f6ae6010c35376c2c9a4`。

2. `/opt/umanews-release-df2f376a-oci-20261105/umanewsbot/backups/db/rds_horse_news_20261104T191805Z_229323.dump`
   大小 `921556775`，SHA `099a1ece1f786fdf9a121f7e6e1602b514652fb7d2783fe70b80cfb2740c2205`。

发布凭据：

- intent.json: `6788ffade281afda7c8242e85622de6f3d3923a45a52465fdd3a6039f380cd86`
- manifest.json: `7f1d3fb49e7717a468b0c969e2fc646291a02459c5538e88fd5e22f35f86f1fc`
- complete.json: `b95a3ce752e47e8f24c343bf58027c99b884fab6c7933c9fab8df2b85e58b4b6`

脱敏结果文件摘要（文件位于上述生产证据目录；本地同名副本已逐字对账）：

- execution-status.json: `ee1fc877244582dfceabdc9223534d32bf11a922500e561f97af6e172b532c9a`
- observation-start-summary.json: `e2095854ee77a054ea8a250f80063fb9b03ecfb267a7858b778551b82af8d244`
- observation-end-summary.json: `4e5738302136ea3bbff90c28fbae08ef021b06b4c499877174efb80536cdd464`
- continuous-observation.json: `a59eff5bb1bdefb6a8f08c009161cd0f1517943fe01818aba40f41fbb006c9c2`
- final-readonly-audit.json: `610b77d545e880db79ee851a51e363ca3233098be9b8c806a22ab6fd49f47646`

失败恢复边界沿原[发布包](rollout.md)：同候选受保护关闭态、必要时停消费者并保留锁/证据；不回退旧镜像或数据库。本次未触发失败恢复。人工门禁统一引用根AGENTS.md。
