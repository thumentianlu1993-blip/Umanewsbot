# A021 固定候选独立审核交接

2026-10-05，Asia/Shanghai。任务 `R-A021-CODE-REVIEW-001` 已于02:23权限恢复后首次成功送达原 R，并取得 active 确认；原 R 先独立审核 A021，再按顺序审核 C021 静态包。此前发送返回 `MCP tool call requires approval, but approval policy is never`，该次确实未送达。下面保留固定派单内容，未取得审核结论。人工确认仍只按根 [AGENTS.md](../../../AGENTS.md)，本单不授权合并、发布或新增生产动作。

## 固定范围与已核证据

- 候选 `898cfe0244abed9b07ff481159dc37c6fd9f96cc`，parent `4982b4a2935f0680b5b1456998e81d2707578ffe`；A 工作树 `/Users/mentianlu/.codex/worktrees/5482/umanews` 已核干净。
- 仅三个新增文件：`server/stable/services/race_page_compat.py`、`server/stable/test_race_page_compat.py`、`docs/changes/next-version-capabilities/lanes/A/A-021-R03-full-page-compat-pure.md`。
- root 已读完整报告，核对 3 个 Git 文件摘要、808 个证据索引工件、36 阶段的 444 个源码条目和 11 个固定 Git 依赖。
- 最终同源码两批 160 + 113，共 273 个唯一方法：旧 204、新 69；实际逐方法日志均通过，0 failure/error/skip。938 次参数化子例单列；新方法 AST 与执行 ID 一致。
- 十组 RED/GREEN 的完整测试文件摘要相同，RED 日志含实际断言失败；fixture/setup 错误单列。root 未执行候选源码，该核验不替代独立代码审核。
- 证据目录 `/Users/mentianlu/.codex/runtime/a021-page-compat/`；index SHA `e8c17b4e6b127f0b070f8647907ac4e5eeaf95f239ca12e049752b5658cffc5d`；receipt SHA `8df1f7a10ec2e498df1a656343d2ed2c1edbe351d1bc3ea54dd71dfe12a102ed`。
- root 核验文件 `/private/tmp/umanews-root-a021-verification-898c/verification.json`，SHA `8936f19d7c71f70509b53a77ca56380913e21822a90514d9d6f643cc50806fa1`。

这只是 macOS Python 3.14.6 固定纯函数开发证据，不代表 Linux CI、真实来源/权限、DOM、公开时效或生产验收。F03 完整格仍为 0/45，R03 全量目标及 10/09 18:00 检查点不变。

## 已发给原 R 的任务

目标会话 `01a0fdc6-2d8d-7d10-9662-a7b042e56ef0`，模型沿用 `gpt-6.1-sol` / `medium`。

> 执行 R-A021-CODE-REVIEW-001，在原审核上下文只读检查固定候选 898cfe0244abed9b07ff481159dc37c6fd9f96cc。你已批准其 A020 最终方案，原结论为 24d4c524c2171d78c8d333cdc2a382a86bf65424。只在自己的 R 工作树保存报告及私有证据，不修改受审实现、root 共享文件或其他线程改动。
>
> 重点核最终 A020 §6.1–6.7/§7：五键完整证据、来源原件、单位/null 引用、current/retained 完整代数、独立 page permission 及无环关系；资源超限拒绝而非截短。已有 detail 字段不可通过 extension 绕过；原 winner 三层扫描、原顺序、top5、podium、全表同着和旧文案保持。现代冠军不一致只失去 bound，不得改写旧页面。
>
> 特别核 preview 遮罩与过期价格必须服从固定 A019 原公开投影，page source/display/tag 不能恢复隐藏的私有值；合法 null 仍保留完整行。纯代码不得读取文件、环境、时钟、网络、Django 或数据库。预算保持 depth32、nodes65536、1MiB、每 kind 512 行、每组 2048 证据、每 display 32 原始引用。
>
> 在不可变、隔离的纯函数快照独立复验 273 方法，每批不超过 200；可补必要最小边界反例，不启动 Linux/native、真实网络或生产资源。固定依赖：F01 06b01aea9041eacb3deae9f46968eb06fd459cb6；A013 2a7ccbfe159a1878e3d9ee03258110757bdc259b；A015 76d19af3515041391e6fe7effc7d9833371842a9；A017 29f7793a48e5b93a54fbc53fe8cfd8db397bbb44；A019 7148ee66a398759190e9ad15e26a0f94ebf7a944。C018 cdeb757f9c8e70938ac8ea40a64096f8a0ffa2cd 只作语义参考，不 import。
>
> 输出 APPROVED 或具体 actionable finding，以及固定报告 commit、来源和证据摘要；review 不构成合并或发布授权。先实时核每周额度，活跃每 5 分钟复核，剩余 ≤3% 每批复核，≤1% 执行既有停止流程。不使用积分、重置券或更换模型绕过。

实际发送前已检查原 R 空闲且本任务未收到，没有创建替代 reviewer 或重复副作用。C 新执行包已在同一消息中明确排在 A 后面；B 引用规范增量仍待完整固定交付。
