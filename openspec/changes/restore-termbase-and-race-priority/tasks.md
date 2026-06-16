## 1. TDD 测试先行

- [x] 1.1 (application) 先增加术语导入测试，覆盖 dry-run 不落库、新增模式重复保护、upsert 更新、旧 CSV 兼容和非法比赛等级校验，并确认在当前实现下失败。
- [x] 1.2 (application) 先增加候选池字段测试，覆盖候选的日文原词、中文译词、类型、日文别名、中文别名展示、编辑和接受为正式术语，并确认在当前实现下失败。
- [x] 1.3 (application) 先增加未知马名和比赛名入池测试，覆盖未命中正式术语库时创建或合并候选证据，并确认在当前实现下失败。
- [x] 1.4 (application) 先增加翻译术语测试，覆盖标题中的 `キタサンブラック → 北部玄驹` 命中、元数据记录和未知马名列表排除，并确认在当前实现下失败。
- [x] 1.5 (application) 先增加赛事等级归一化和自动评分测试，覆盖 `G1/GI/GⅠ`、`G2/GII/GⅡ`、`G3/GIII/GⅢ`、`L/Listed/リステッド`、`OP/オープン`、`新馬`、`未勝利`，并确认在当前实现下失败。
- [x] 1.6 (application) 先增加文章 `3961` 形态的端到端回归测试，确认评分达到自动候选阈值且不再出现“赛事 P2、无重点马命中”的错误组合，并确认在当前实现下失败。
- [x] 1.7 (application) 先增加执行日 0:00 后候选新闻池批量验收测试或管理命令测试，覆盖多篇候选新闻的术语命中、候选发现、赛事等级和自动评分输出，并确认在当前实现下失败。

## 2. 正式术语模型与导入链路

- [x] 2.1 (application) 为 `TermEntry` 增加可为空的 `race_grade` 字段，限制为系统支持的比赛等级枚举，并生成 Django 迁移。
- [x] 2.2 (application) 扩展术语后台表单、列表、详情、复制、新建、编辑、API payload，使比赛等级可查看、可编辑、可保存。
- [x] 2.3 (integration) 扩展 `term_admin` CSV 解析、校验、预览、提交、导出逻辑，兼容旧 CSV 缺少 `race_grade` 的情况。
- [x] 2.4 (application) 新增 `import_terms` 管理命令，支持指定文件、`--dry-run`、`--mode create|upsert`，并复用后台导入服务。
- [x] 2.5 (application) 新增版本化术语数据文件，包含历史 PRD 已确认的核心马名术语和本次修复所需的 `宝塚記念` 比赛等级初始项。

## 3. 候选池字段与入池链路

- [x] 3.1 (application) 为 `TermCandidate` 补齐 `target_zh`、`aliases_ja`、`aliases_zh` 等基础术语内容字段，并生成迁移。
- [x] 3.2 (application) 扩展候选池列表、详情、审核表单和接受逻辑，使候选基础内容字段可展示、可编辑、可写入正式术语。
- [x] 3.3 (integration) 调整术语发现逻辑，确保马名和比赛名未命中正式术语库时创建或更新候选，并聚合文章证据。
- [x] 3.4 (integration) 确保已命中正式术语库的马名和比赛名不进入候选池，避免重复候选污染。

## 4. 翻译术语命中修复

- [x] 4.1 (integration) 调整翻译术语解析输入，使用标题、正文和规范化原文的组合文本生成 `metadata["terms"]`。
- [x] 4.2 (integration) 确保 `extract_unknown_horse_names` 在正式马名存在时跳过日文原词和别名，避免 `キタサンブラック` 被作为未知马名保护。
- [x] 4.3 (integration) 确保最终标题、正文和推送摘要继续执行正式术语映射，并覆盖标题中出现的正式术语。

## 5. 自动评分赛事等级修复

- [x] 5.1 (integration) 新增赛事等级归一化函数，覆盖 G1/G2/G3、Jpn、障害、Listed、Open、新马、未胜利和胜利条件赛常见写法。
- [x] 5.2 (integration) 调整 `race_priority()`，优先读取命中的比赛类 `TermEntry.race_grade`，没有结构化等级时再使用文本归一化回退。
- [x] 5.3 (integration) 建立 `race_grade` 到自动评分优先级的映射，确保 G1/Jpn1 等进入 P0，G2/Jpn2 等进入 P1，G3/L/OP 等进入 P2，新马/未胜利等进入低价值层级。
- [x] 5.4 (integration) 保留障害赛降级或特殊处理逻辑，避免普通平地赛事规则误升障害赛文章。
- [x] 5.5 (integration) 确保自动决策原因写入术语库比赛等级、等级来源、最终 `race_priority`、价值分和重点马命中信息，便于后台排查。

## 6. 本地验证与浏览器验收

- [x] 6.1 (application) 执行 `DB_ENGINE=sqlite python manage.py check`。
- [x] 6.2 (application) 执行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`。
- [x] 6.3 (application) 本地部署测试环境，使用浏览器登录后台并验收文章 `3961` 形态页面。
- [x] 6.4 (application) 使用浏览器或验收命令检查执行日 0:00 后所有进入候选新闻池的新闻，逐篇确认术语命中、候选入池、赛事等级和自动评分结果。

## 7. 生产修复准备

- [x] 7.1 (operations) 更新部署运行手册或当前状态文档，记录生产备份、迁移、术语 dry-run、正式导入、执行日候选新闻批量重跑、后台核验的步骤。
- [x] 7.2 (operations) 准备生产只读核验命令，确认 `TermEntry` 数量、`キタサンブラック`、`宝塚記念`、候选池新增项、文章 `3961` 翻译元数据和自动评分状态。
