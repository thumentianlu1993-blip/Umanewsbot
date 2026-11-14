# 交付包与验证记录

当前尚未合并或写入生产。前台与历史修复范围见 [spec.md](spec.md)、[audit.md](audit.md)。人工门禁仅引用根 `AGENTS.md`。

## 固定身份

- 开发基线：main `ca8abc736427a47c450721cc42e0b0b98c6521d8`。
- 生产基线：`282ae4f9ca1a624fc1e965faf50df8f993cebd07`，schema0084。2026-11-13 20:23 UTC 四应用正常、QQ 关闭。
- 窄发布候选：`24de56e2cb321b102390409a6a57fb528b5dc333`，直接以生产基线为 parent，仅叠加本次 17 个代码/测试文件；不将主线其他未发布能力带入生产。
- 候选镜像：`umanews-five-region:24de56e2`，OCI manifest `sha256:4fc0201d32d0751f092c848e0fbbb766a43544662acf75439ff2efb99e1f62d1`。
- 无迁移；唯一配置变化为固定镜像与 `UMANEWS_RELEASE_COMMIT` 身份。QQ 保持关闭，自动化开关及采集/付费范围不变。

生产分支与 main 的首页日期范围、等级查询存在既有差异。移植冲突只叠加公开地区过滤，保留生产既有日期/等级语义；没有拷贝 main 的整段函数。对应生产分支不存在的等级回归类未引入。生产旧版独有的详情年份切换器也已过滤非五地区，真实失败用例修正后通过。五地区新测试使用合法的 RaceGrade.G1 固定值，适用于两个基线。

## 数据清单

| 包 | manifest SHA256 | 作用 |
|---|---|---|
| `jra-jockey-manifest.json` | `affbd8eb5ee1d90d7a932bd8d00d9b205d5df8da720ff07bdadc7402af7e6f0d` | 1,180 场，35,319 个空骑手 |
| `jra-fields-manifest.json` | `005d77a593e75378a5d9cf202b04d527d691ff6a5529fa21c3fef5ce130001ed` | 日本 11 场，149 行 1,054 个空字段，补 2 条非完赛/取消 |
| `empty-race-manifest.json` | `e64e728c4fadbfaf3c637997f8df21237092937f201743886867baad0e4fef31` | 英国 7 场取消，法国 1 场 17 匹完整名单并公开 |

三包共 1,199 场；不覆盖 [盘点报告](audit.md) 的 94 场未补齐项。数据包包含原件、事实摘录、清单与隔离演练收据，逐文件 SHA 已冻结。

## 发布动作

取得生产发布锁并验证基线与 CAS；校验上传包并备份受影响记录、目录目标、原 Compose 身份。暂停 Beat、优雅排空两个 worker；全部清单 dry-run 通过后按骑手、日本字段、空表包顺序执行。同包原子事务，任一失败停止后续并恢复已成功包。

只重建 web、worker、race_sync_v2_worker、beat 四应用，数据库/Redis/浏览器服务保持原配置，不执行 migrate。web 重建后对既有 Nginx 执行配置检查与平滑 reload，验证 root/www 公网首页、healthz 及赛事页，防止静态 upstream 指向旧 Web IP。验证三个 manifest 全量后值、1199 场作用域与新增行，核对五地区公开入口、隐藏地区直链 404、日历/站点地图、法国 17 匹与日本非完赛显示；确认调度恢复、服务健康、QQ 关闭，释放发布锁。

回滚使用同一候选命令逆序恢复空表、日本字段、骑手包，再恢复四应用旧镜像与原 Compose 身份，重复 Nginx 配置检查、reload 与公网验证。后续来源/生涯关联或字段漂移时条件恢复会拒绝覆盖，保留备份并按实际状态处理，不假定回滚成功。

最终 `release-plan.json` 将绑定 PR/head、候选、OCI 摘要、包摘要、服务和操作。只能按该精确包交付。

## 已验证及待验证

- 前台变更原基线 215 项范围回归通过；原 reviewer 已只读通过。
- 修复单测及真实三个 manifest 的 dry-run/apply/replay/restore/replay 已通过；v1 在 v2 扩展后重放 1,180 场整包再次通过。
- 独立 review 的后续 P0 关联恢复风险、JRA“中止”语义两项 finding 已修复并获原 reviewer 复审通过。
- 固定生产候选 **264 项范围测试通过，零跳过**。其中唯一初次失败是 fixture 使用小写非枚举等级值，已改用 RaceGrade.G1 后重验。
- 最终整包复审包含生产年份切换器、镜像逐层/文件核对及 Nginx 发布/回滚 reload。正式范围 CI、最终整包审核与生产验收另附后续收据；当前不将隔离演练称为生产完成。
