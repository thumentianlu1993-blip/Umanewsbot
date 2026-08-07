# 未来七天重点赛事官方数据测试用例

## RED 计划


1. `Asia/Shanghai` aware `[start, end)` 与半开边界；恰等于 start 纳入、恰等于 end 排除。
2. 英国/法国/美国 DST 换算；禁止使用固定 offset，处理不存在/歧义 local time 时 fail closed。
3. 重点赛事仅按 `P0/P1 或 featured` 枚举，使用真实
   `visibility_status/status`；featured P2 必须纳入，draft/cancelled 排除。
4. 无 series 或 series 未批准仍进入 inventory，但只能形成 apply blocker。
5. 本地日期超集只有在取得官方 aware post time 后才能决定最终窗口归属。
6. 未审核 provider/region/field/phase/contract version 在 transport 前拒绝，网络调用数为 0。
7. 官方 event ID 缺失或不唯一、仅名称/日期可匹配时整场 blocker，业务写入为 0。
8. runner ID 缺失/重复、马号冲突或跨修订换号时整场 blocker。
9. 不同 official source 的相同 runner ID 不碰撞；相同名称、马号或 ID 字符串不得跨 source
   自动合并，出现多 source current identity 时整场零写。
10. official source 切换必须进入人工身份 review blocker；同 source 内退赛后恢复、换号及
    现有 revision 都保留 canonical participant。
11. 空出马表、局部来源、时间冲突、身份冲突、不可信来源均不能产出可 apply record。
12. raw → normalized → 中文展示三层值与时区证据同时保留。
13. 退赛/取消修订保留原 runner 与 revision evidence，不删除历史审计。
14. 新候选空值不能覆盖既有可信非空字段；field authority/manual lock 冲突必须拒绝。
15. prepare 只写不可覆盖 artifact，不写任何 canonical 或 legacy 业务表。
16. source body、receipt、candidate 和 manifest SHA 任一漂移时 dry-run/apply 拒绝。
17. manifest 自改、payload 替换、symlink、路径逃逸、重复规范路径必须拒绝。
18. 伪造/未批准/非 active staff approval receipt 或 receipt SHA 不符时零写。
19. 手工 receipt 填写有效他人 staff ID、缺 immutable DB approval row 时必须零写；Admin
    actor 只能来自认证 request.user，UPDATE/DELETE approval 被应用层和 PostgreSQL trigger 拒绝。
20. `LIVE/HISTORICAL/MANUAL_PAUSED` owner、owner generation 漂移和没有安全 baseline 时拒绝。
21. 已有 official/supplemental racecard revision、manual lock、lifecycle generation 变化并发测试。
22. 所有 writer owner 都必须锁 projection control；绕过 owner 的回归使新 apply 保持关闭。
23. 批次事务中最后一场故障时，canonical revision、projection、field authority 全部回滚。
24. 相同批准 SHA 重复 apply 为幂等 noop；不同 SHA 必须重新 review。
25. 独立 verifier 能发现额外行、漏写行、字段/owner/coverage 漂移。
26. 无网络测试使用 fixture/fake transport，并断言 DNS/HTTP 从未触发。

## 地区 fixture

- 英国：BST 日期与 `Europe/London` 换算、官方时间修订。
- 法国：CEST 日期与 `Europe/Paris` 换算、登录/缺 route blocker。
- 美国：
  - `America/Los_Angeles` 与 `America/New_York` 同一项目窗口；
  - scratched/MTO/withdrawn 状态；
  - 尚未公布页面、404 和部分 racecard。
- 日本/香港：本窗口无应到赛事仍输出零覆盖；既有 JRA/HKJC/NAR parser 回归不得破坏。

## 验证矩阵

- 聚焦 Django 单元/命令测试；
- PostgreSQL advisory lock、并发与事务回滚测试；
- `manage.py check`；
- `makemigrations --check --dry-run`；
- 所有相关 migration plan；
- parser fixture 离线测试；
- `git diff --check`；
- 现存 racecard/realtime/lifecycle/historical candidate 回归；
- 旧规格流程 仅做既有兼容目录的 strict validation（若仓库 CLI 可用），不把它作为新 change

## 当前测试状态

尚未创建或修改自动化测试。原因不是 RED 豁免，而是 AGENTS 工作流要求方案审核通过并获得用户
针对本版方案的“G1 范围确认”后才进入 TDD。当前只允许文档结构、链接、diff 和计划审核检查。
