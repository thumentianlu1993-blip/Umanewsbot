## 0. Pre-declared hypotheses

- [x] 0.1 (application) PASS：问题文章最小样本中人物/普通词误识别为马的数量为 `0`，真实马名 `多爵` 仍命中；BLOCKER：任一负样本仍生成 horse entity/tag/link，或真实马名被全部压制
- [x] 0.2 (integration) PASS：`ノリヤンモーニン`、`マドモアゼルアスク`、`プティフォリー`、`ルアーヴル` 及含 `ユーロ` 的完整实体逐字保留，内部短术语替换数量为 `0`；BLOCKER：任一完整实体被拆分或遗漏
- [x] 0.3 (integration) PASS：20 篇批量实体解析的术语与外部别名查询合计 `<=8` 且从 10 篇增至 20 篇不增加；BLOCKER：出现逐篇术语/alias 查询或英文全 alias 无条件加载
- [x] 0.4 (application) PASS：显式修复前后人工标签、`MANUAL/REMOVED` 关联、公开 ID/状态/时间和 QQ delivery 完全不变，过时 `AUTO/CANDIDATE` 关联清除；BLOCKER：任一人工或公开副作用

## 1. 回归测试代码

- [x] 1.1 (application) 从文章 `8317`、`8309`、`8086`、`8330`、`8318` 提炼英文人物、姓氏回指、普通词误识别和真实马名保留的最小测试文本
- [x] 1.2 (application) 从文章 `8291`、`8290`、`8283`、`8288`、`8221`、`8212` 提炼完整日文马名、内部短术语和赛前出马表未知马名原文保留的最小测试文本
- [x] 1.3 (integration) 编写文章级实体解析失败回归，覆盖完整跨度最长优先、人物职业语境、唯一姓氏回指、同姓歧义和英文强马名上下文
- [x] 1.4 (integration) 编写翻译术语/占位符失败回归，证明人物或普通词不进 horse terms，未知完整日文马名先占位、只映射接受术语并在最后恢复，且 `TranslationRun.terms_used` 与 metadata 一致
- [x] 1.5 (application) 编写标签与自动马匹关联失败回归，覆盖机器标签 provenance、legacy 目标清理、来源默认标签保留、内容 force 不覆盖人工标签，以及过时 `AUTO/CANDIDATE` 删除和 `MANUAL/REMOVED` 保护
- [x] 1.6 (application) 编写显式文章实体修复命令 dry-run/commit、逐篇事务回滚、操作日志、公开状态/发布时间和 QQ 零副作用的失败回归

## 2. 文章级实体解析实现

- [x] 2.1 (integration) 在术语服务中实现带跨度、实体类型、证据、冲突标记和确定性排序的文章级解析结果及序列化
- [x] 2.2 (integration) 实现英文人物全名识别与篇内唯一姓氏回指，明确人物跨度压制内部马名候选
- [x] 2.3 (integration) 实现英文普通词/高歧义马名强上下文门禁，复用既有普通词和英文上下文规则并保留真实马名例外
- [x] 2.4 (integration) 实现日文连续完整马名 token 仲裁，确保完整外部/正式/强语境未知马名压制内部父马名、冠名或短术语
- [x] 2.5 (integration) 为单篇与批量解析增加按原文候选 key 的术语/外部别名预加载接口，英文不得无条件加载全 alias；让 `ValidationBatchContext` 携带预计算实体与接受术语 ID，并满足预声明查询上限

## 3. 翻译、标签、校验与关联接入

- [x] 3.1 (integration) 修改翻译 prompt、`TranslationRun.terms_used`、翻译元数据和确定性术语映射，只消费同一文章级接受实体；完整未知马名先占位、接受术语映射后再恢复，禁止恢复后全库扫描替换
- [x] 3.2 (integration) 修改马名标签提取及非人工标签写回，在既有 metadata 记录机器标签 provenance；只移除上轮机器标签或显式目标 legacy 候选，保留非马/来源默认标签，内容 force 也保护人工标签
- [x] 3.3 (integration) 修改发布校验，记录人物/普通词被误作马名及正文、标签、自动关联类型不一致，同时保留其他 blocker
- [x] 3.4 (integration) 修改自动马匹关联按接受实体身份预筛 Profile，删除不再命中的旧 `AUTO/CANDIDATE`，并保护 `MANUAL` 与 `REMOVED` 关联决定
- [x] 3.5 (application) 实现按显式文章 ID 的实体/标签/自动关联重处理管理命令，默认 dry-run，每篇 commit 独立事务并记录前后差异与 `OperationLog`

## 4. 本地验证与复核

- [x] 4.1 (application) 运行全部问题文章目标测试、术语/翻译/标签/校验/马匹关联相关测试，并验收 20 篇批量解析 `<=8` 查询且 10/20 篇查询数相同
- [x] 4.2 (application) 运行完整 `stable` 测试、Django check、`makemigrations --check --dry-run`、OpenSpec strict 和 diff check
- [x] 4.3 (application) 完成 17 轮代码与生产回归 review；直接修复 PostgreSQL 锁语义、实体上下文、同步重译 provenance、旧标签清理、人名边界、跨位置校验及随机样本日文普通词保护问题，并继续复核至零问题

## 5. 生产部署与问题文章修复

- [ ] 5.1 (operations) 协调并取得空闲生产写入窗口，核对精确 commit、容器、Celery、外部导入/历史写入锁和健康状态，备份 `.env` 与 PostgreSQL 并验证可读
- [ ] 5.2 (operations) 从经 review 的精确提交构建可复现 AMD64 镜像，运行候选 check、迁移漂移和目标测试后部署 web/worker/beat
- [ ] 5.3 (operations) 对文章 `8317`、`8309`、`8086`、`8330`、`8318` 执行实体/标签 dry-run、commit、显式重译和重新校验
- [ ] 5.4 (operations) 对文章 `8291`、`8290`、`8283`、`8288`、`8221`、`8212` 执行完整马名保护 dry-run、commit、显式重译和重新校验
- [ ] 5.5 (operations) 逐篇验收正文、标签和自动马匹关联，保持公开 ID、状态、原发布时间及 QQ 幂等；随机抽取英文/日文新文章确认不再出现同类误识别

## 6. 文档、规格与归档

- [ ] 6.1 (operations) 更新 `docs/current_state.md`、`docs/project_status.md`、`docs/decisions.md` 和 `docs/deploy_runbook.md`，记录实体判定、生产镜像、备份、逐篇修复和随机回归证据
- [ ] 6.2 (operations) 同步 delta spec、严格校验全部完成任务并归档 `contextualize-news-entity-resolution`
