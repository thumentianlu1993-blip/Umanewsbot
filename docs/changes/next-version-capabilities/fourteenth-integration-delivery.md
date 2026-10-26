# 第十四批交付：PR248 来源证据收据

状态：用户已批准只合并，PR248已完成远端合并并核验；未发布。正式CI、可信交付与ROOT独立资源收尾均通过，原R实际最终审核已接受，无finding。2026-10-10（Asia/Shanghai）。人工确认仅引用根 [AGENTS.md](../../../AGENTS.md)。

## 固定对象

- PR：[248](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/248)。
- HEAD：`047e3305cd287f6630eac546e156d831e94b0941`。
- BASE：`275e98592f968e1586b76727e9a93927c8a87f6f`。
- 测试 merge：`c43f328701da692749995a70de9332798c45141d`；tree：`67e755d385725fa7404cba822bf65d74f50403cf`。
- 正式 pull_request CI：run `37958222301`，attempt 1；49 批全部完成，6863 唯一测试，6853 PASS、10 原允许 SKIP，零失败或错误。
- 原R正式CI验收：`b5d4f02c10754ec6cc562068f442168dc870f4a0`，无 finding；此时只接受原生产物，不代表可信交付验证完成。
- 可信监督器包：`9069344730fa5d86644b3bc890ea2a5d723884c10aade114d5ee76428065589b`；原R host审核：`5cddb83a7095596d9fcb73ca0a30408b5ea6fa09`。

## 行为与限制

显式 receipt_version=2 的离线入口，将同条 ORM publication 投影与严格 codec 纳入 step UUID、result SHA、checkpoint/final 证据链。保留 v1 默认、字段计划和预算；v2 权限检查可延迟读取完整证据，头条 on_commit 保留资格、锁序、失效与审计约束。修复并发测试线程的连接清理并登记对应完整测试影响。

差异共15文件，无新增 migration、模型schema、依赖或配置变化，无新skip豁免，无付费调用或抓取扩张。十项原允许SKIP不算PASS。完整M02/M03、v2跨进程恢复与生产验证仍开放。

## 候选交付动作

推荐“只合并，不发布”，精确对象为本页PR248及固定HEAD。获准后将固定PR248转ready，合并前实时核HEAD/BASE/测试树、required checks及strict/admin保护，再以精确HEAD约束远端合并；合并后核真实commit、parents、tree。

此候选包无生产迁移、配置或功能开关变化，无生产镜像构建发布、服务重建重启、数据写入、外部发送。撤回需保留审计历史的revert；没有生产数据库恢复动作。若选择合并并发布，需先补齐生产当前SHA/镜像、已有0080/0081迁移状态、备份恢复、配置、服务动作和验收合同，形成另一精确发布包。

## 最终独立验收

原R实际最终审核commit `01a7d376eef3be4bc4cc846e7c47aa6da5211a16`，报告SHA `dd410459cc14e9d33134e4f81a6d80dc7982f424bbd713c7425a88102a51944c`，回执SHA `63ceab5e02aa053783908e764fcbee45e9f182ceba3cb026180625edbd77dd3c`。ROOT全文核对及Git/回执/三项实际证据哈希均通过。接受固定对象技术交付与独立FREE，仍不代表G2授权。

## 可信验证实际结果

实际exit0，342.725秒；receipt `7269d381189e31d1b5819ed2b4417d834424952d81dc0081bca5525f35aea50b`，status verified，6863测试及计划摘要一致。ROOT独立closeout `f658ddf5e2e60f77160ed80a746c0ce6493956e7e94dfa224eef8299a2b0521d` 确认资源FREE：PID/PGID与owned容器消失、旧停止容器六字段保留、双锁原dev/inode可重新取放、20项封存未变。原R实际最终审核 `R-B098-TRUSTED-ACTUAL-FINAL-001` 已接受。

## G2请求时当前状态

2026-10-10实时读取PR248为OPEN/DRAFT/CLEAN，HEAD与BASE均保持本包固定值，tests和test-plan-gate均SUCCESS。获准前保持Draft，不执行合并。合并执行前仍复读精确身份和分支保护。

## 获准执行结果（2026-10-10）

用户明确批准第1项只合并包。固定HEAD `047e3305cd287f6630eac546e156d831e94b0941` 已合并为 `1dd5e0a508957672bcddd1c33e454fbbef1b75c1`；ROOT核真实parents为本页BASE/HEAD，tree保持 `67e755d385725fa7404cba822bf65d74f50403cf`，远端main与PR merged状态一致。合并前两次复核strict/admin保护与required checks。独立核owner PID消失及原dev/inode锁可重取释放，资源FREE。原始审计位于 `/Users/mentianlu/.codex/runtime/pr248-merge-only-001/`。生产动作0；没有部署、迁移、重启或功能开关变化。
