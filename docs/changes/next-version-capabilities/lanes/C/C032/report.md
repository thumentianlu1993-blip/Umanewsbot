# C032：马匹搜索空态最小实现

已审方案 `46d564a06257797e144960a3fd29e9f2f60272ac`；RED 准备提交 `0828a23885a50fbec4f66cc08cdbd5d35a2525fa`。本阶段已取得有效 RED 并按原方案实现模板，GREEN、最终独立代码 review 和交付仍待进行，不能宣称 U04 整卡完成。根 AGENTS.md 是唯一门禁来源。

## 真实 RED

ROOT 分配 C032-FIVE-RED-PG-WINDOW-001，一次单容器，官方受信 django worker 实际加载固定五个完整 IDs，无 collector/build/pull/host DB。2026-10-06 约 51.985 秒完成：5 executed、3 failures、0 errors、0 skip、lifecycle complete、runner exit 1。

- `test_u04_unmatched_search_describes_public_search_scope`：新“没有找到符合搜索条件的已发布马匹资料。”文案缺失。
- `test_u04_clear_search_restores_cards_and_preserves_anonymous_follow`：清除链接数量 0 != 1。
- `test_u04_hidden_only_search_remains_no_match_without_disclosure`：新搜索范围文案缺失。
- 无 q/空白空库与匹配卡片/signed return_nav 两个保护项通过。清除后的 cookie/关注行保护在 RED 时尚未执行到，须由同例 GREEN 验证，不能提前称通过。

环境 Django 5.2.1 / PostgreSQL 16.15；仅本地隔离测试库，真实数据或第三方调用为零。指定 fcf8 镜像、non-root、network none、4 GiB / 2 CPU、pids 256、只读 root/source/control、capdrop ALL、NNP、3 GiB tmpfs 均实测，600 秒总窗含 30 秒清理、570 cutoff。FD flock owner 92613 / runner 92621 已退出；自有容器删除，实时 daemon 无运行容器、flock 可再取得，资源已回报 ROOT 释放。

原始结果、日志和十份 evidence hash：`/Users/mentianlu/.codex/runtime/c032-u04-empty-search-001/red-window-001/`。`results/c032-red-five.json` 是官方原结果；`red-receipt.json` 提取准确 AssertionError 行，不把导入/基础设施错误当 RED。原证据未因摘要调整而修改。

## 最小模板变化

仅 `horse_index.html` empty 分支按既有 `filters.q`：非空搜索显示固定搜索范围文案和真实 `/horses/` 清除链接；无搜索保持原文案。将文案和链接放同一个 grid item 内，不新增 CSS 或组件。点击后清除 q/page/return_nav，正常公开范围和匿名关注 cookie 保持既有行为。

view/query/pagination、共享 `_empty_state.html`、模型/settings/schema/migration/catalog 均不变。测试仅既有 HorseProfilePageMvpTests 的五项；不改他线或 PR240 候选。模板离线 parse / git diff --check 通过，这不是 GREEN 或真实渲染证据。

## 下一窗口

固定实现 SHA 后在新自有 green-window-001 绑定同五 IDs、同受信 controls/image/django profile。仅申请一次同预算诊断容器，原五项全部执行，不缩选、不复跑 RED，不修改官方 full/collector/验证器。等 ROOT 分配后才启动。GREEN 后最近相关范围与实际演示按 ROOT 排程，原 C027 树/数据库/进程/端口继续保持；不伪造已有 published 的 C027 样本。

H07/R03 的全局新鲜度、读取失败统一状态、L05 聚合、QQ 停用文案及后台改造均延期；不增加字段或吞掉异常成空集。本片没有 push/PR/merge/发布、生产写入、真实网络、QQ 外发或付费调用。
