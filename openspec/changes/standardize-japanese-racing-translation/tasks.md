## 0. Pre-declared hypotheses

- [x] 0.1 (integration) PASS：普通词正样本最终残留指定片假名数量为 `0`，未知马名逐字保留率为 `100%`；BLOCKER：任一普通词残留或未知马名被翻译/拆分
- [x] 0.2 (integration) PASS：产驹、追切、访谈和骑手未定四类固定格式在全部变体中精确一致，格式占位符遗漏时重试并最终失败；BLOCKER：任一格式依赖模型自由发挥或静默丢失占位符
- [x] 0.3 (application) PASS：术语迁移首次执行后每个概念唯一，重复执行语义不增行，冲突数据明确失败且不覆盖；BLOCKER：重复概念/别名或人工数据被静默改写
- [ ] 0.4 (operations) PASS：11 篇目标文章和随机新样本正文正确，目标文章 ID/状态/发布时间/`manually_edited_fields` 标记/QQ delivery 完全不变；BLOCKER：任一公开、人工标记或分发副作用

## 1. 完整测试用例与失败回归

- [x] 1.1 (application) 已建立 `test_cases.md`，逐条映射 11 篇文章、所有术语、格式变体、负例、迁移、翻译失败和生产副作用验收
- [x] 1.2 (integration) 已从 `8304/8298/8290/8288/8283` 编写产驹回归，覆盖已知/未知母马、无括号、括号在引号内外、父马有无 `父` 前缀、多 lot 同段、内部短术语不得跨位置拆分，以及整段消费后不再触发旧未知马名缺失检查
- [x] 1.3 (integration) 已从 `8291/8219/8212` 编写追切、赛后访谈和出马表回归，覆盖相似非目标秒数、说明句 `○○` 及未知完整马名保护
- [x] 1.4 (integration) 已从 `8304/8287/8276` 编写普通词与 prompt 回归，证明普通片假名进入中文术语且不成为马名，同时真实/未知马名仍按文章级实体结果处理
- [x] 1.5 (application) 已编写 `0030` 数据迁移回归，覆盖首次创建、日英同概念、最长词优先、大小写不敏感幂等重跑语义、不同中文/不同概念冲突和保留式反向迁移
- [x] 1.6 (integration) 已编写格式与种子术语占位符按标题/正文字段成功恢复、元数据审计、首次遗漏后重试、最终遗漏/重复/跨字段失败以及既有马名/人物占位符组合顺序回归
- [x] 1.7 (application) 已编写同步强制重译副作用与返回值回归，证明已发布文章状态、发布时间、`manually_edited_fields` 标记、发布配额和 QQ delivery 不变，目标中文字段按显式 `--force` 更新，任务跳过时不得报告 commit 成功

## 2. 术语数据与普通词语义

- [x] 2.1 (application) 新增无 schema 变化的 `0030` 数据迁移，幂等创建普通词、社台和北方马公园概念及日英 `TermAlias`，冲突即失败且反向不删除运营术语
- [x] 2.2 (integration) 让新增普通词以 `non_horse_common_word` 进入文章级实体索引，并验证 `セレクトセール` 对 `セール` 的最长跨度优先
- [x] 2.3 (integration) 扩充日文翻译 prompt，并用字段级 `__UMA_SEED_n__` 对已接受种子术语执行精确恢复；普通片假名不残留，模型同义改写不能偏离指定中文，且不影响强马名语境和未知马名原文保护

## 3. 日文固定格式计划

- [x] 3.1 (integration) 新增纯函数式日文格式计划类型，确定性生成受保护文本、`__UMA_FORMAT_n__` 映射、来源字段、已消费源 span/实体和可序列化审计元数据
- [x] 3.2 (integration) 实现拍卖 lot 解析与恢复，按字段绝对 span 精确读取母马/父马实体，支持性别括号内外、父马有无前缀、已知实体中文目标和未知马名原文回退，禁止组件全局术语替换
- [x] 3.3 (integration) 实现追切计时与赛后访谈窄上下文规则，并为相似普通文本保持无修改
- [x] 3.4 (integration) 实现出马表行末 `○○` 的骑手未定规则，保持说明句符号与完整未知马名
- [x] 3.5 (integration) 将格式计划接入现有马名/人物占位符之前和恢复链路之后，排除已消费未知实体，并按标题/正文字段检查缺失占位符、复用重试并最终显式失败
- [x] 3.6 (integration) 将格式规则、源片段、目标片段和占位符写入 `TranslationRun.raw_response`，并保持 `terms_used` 与文章级接受术语一致

## 4. 本地验证与零问题 review

- [x] 4.1 (application) 运行日文格式、术语、实体、翻译任务和同步重译目标测试，并核对预声明 PASS/BLOCKER
- [x] 4.2 (application) 运行完整 `stable`、Django check、`makemigrations --check --dry-run`、SQLite 迁移往返、OpenSpec strict/all 和 diff check
- [x] 4.3 (application) 执行 `/review -> 修复` 循环；产品能力选择向用户确认，技术问题直接修复，直到某轮 review 零问题

## 5. 生产部署与文章修复

- [ ] 5.1 (operations) 协调空闲生产写入窗口，核对精确 commit、容器/Celery/one-off/历史写入门禁和健康状态，备份 `.env` 与 PostgreSQL 并验证恢复清单
- [ ] 5.2 (operations) 从最终零问题提交构建可复现 AMD64 镜像，在候选 PostgreSQL 上执行迁移、Django check、迁移漂移和目标测试，再依次部署 web/worker/beat
- [ ] 5.3 (operations) 核对 `社台/Shadai`、`ノーザンホースパーク/Northern Horse Park`、`セレクトセール` 及普通词在生产术语库中概念唯一、目标正确且别名完整
- [ ] 5.4 (operations) 对 `8304/8299/8298/8291/8290/8288/8287/8283/8276/8219/8212` 记录公开身份、`manually_edited_fields` 标记和 QQ 快照后分批同步强制重译并逐篇重新校验
- [ ] 5.5 (operations) 逐篇验收普通词、产驹、追切、访谈、出马表与未知马名，保持公开状态/时间/人工标记/QQ 幂等；随机抽取近期新日文文章确认不再出现同类问题
- [ ] 5.6 (operations) 验收 HTTP healthz、首页、后台、目标详情、web/worker/beat 同镜像、空队列、错误日志及历史赛事安全开关后交还生产写入窗口

## 6. 文档、规格与归档

- [ ] 6.1 (operations) 更新 `docs/current_state.md`、`docs/project_status.md`、`docs/decisions.md` 和 `docs/deploy_runbook.md`，记录格式契约、术语迁移、镜像、备份、目标文章与随机回归证据
- [ ] 6.2 (operations) 同步 delta spec、严格校验全部完成任务并归档 `standardize-japanese-racing-translation`
