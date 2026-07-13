# 完整测试用例

## 1. 命中实例

| ID | 场景 | 预期 |
|---|---|---|
| HIT-01 | 同一术语在标题和正文各出现一次 | 返回两个独立命中，字段、跨度和上下文正确 |
| HIT-02 | `Brilliant was brilliant at Sha Tin` | 两个命中顺序稳定，实际文本分别保留 |
| HIT-03 | 大小写不同的 alias 命中 | 关联同一概念，但保存文章实际写法 |
| HIT-04 | 子串位于更长单词内部 | 不产生错误单词边界命中 |
| HIT-05 | 同概念多个 alias，文章只命中一个 | 只对实际 alias 分类，其他 alias 不污染 |
| HIT-06 | 标题/摘要/首段/背景正文 | 核心位置标记准确 |

## 2. 高置信马名上下文

| ID | 场景 | 预期 |
|---|---|---|
| HORSE-01 | `Brilliant won at Sha Tin` | `proper_noun` |
| HORSE-02 | `Brilliant finished second` | `proper_noun` |
| HORSE-03 | `Brilliant, ridden by Zac Purton` | `proper_noun` |
| HORSE-04 | `Brilliant is trained by ...` | `proper_noun` |
| HORSE-05 | `Brilliant (IRE)` | `proper_noun`，记录国别后缀证据 |
| HORSE-06 | 候选出现在结构化参赛名单 | `proper_noun`，记录参赛证据 |
| HORSE-07 | 候选出现在结构化赛果 | `proper_noun`，记录赛果证据 |
| HORSE-08 | 同名马存在但当前没有任何实体关系 | 不得仅凭 `term_type=horse` 高置信判专名 |

## 3. 高置信普通词上下文

| ID | 场景 | 预期 |
|---|---|---|
| COMMON-01 | `a brilliant winner` | `common_word`，无 blocker |
| COMMON-02 | `an incredible performance` | `common_word`，无 blocker |
| COMMON-03 | `something went wrong` | `common_word`，无 blocker |
| COMMON-04 | `something around his head` | `common_word`，无 blocker |
| COMMON-05 | `an unbelievably versatile filly` | `common_word`，无 blocker |
| COMMON-06 | `came with a huge reputation` | `common_word`，无 blocker |
| COMMON-07 | `posed a threat` | `common_word`，无 blocker |
| COMMON-08 | HTML `title=` 属性、脚本或推荐卡片中的 `title` | 不进入命中集合，不作为马名 blocker |
| COMMON-09 | `too soon to decide` | `common_word`，无 blocker |
| COMMON-10 | `yet to win` / `yet again` | `common_word`，无 blocker |
| COMMON-11 | `Contact / Number / Live / Were / Class / Content / Link` 生产旧样本 | 高置信普通用法降级 |
| COMMON-12 | 上述普通词存在同名正式马匹 | 不删除术语，当前普通用法仍不阻断 |

## 4. 混合和不确定用法

| ID | 场景 | 预期 |
|---|---|---|
| MIX-01 | `Brilliant was brilliant at Sha Tin` | 第一次 proper，第二次 common |
| MIX-02 | 同文先写完整真实马名，后文普通词同形 | 分别分类，不互相覆盖 |
| MIX-03 | 标题只有 `Brilliant Result` 且无实体证据 | 不得仅因标题大写判 proper |
| MIX-04 | 标题疑似核心马名但证据冲突 | `uncertain` 且 blocker/人工 |
| MIX-05 | 背景段落偶然 uncertain | warning，不单独阻断 |
| MIX-06 | 译文已保留实际英文文本 | 无论 uncertain 与否均不产生缺失 blocker |

## 5. 真实专名保护

| ID | 场景 | 预期 |
|---|---|---|
| PROPER-01 | `Kentucky Derby` 未保留 | 继续 blocker |
| PROPER-02 | `Belmont Stakes` 未保留 | 继续 blocker |
| PROPER-03 | 真实骑师完整人名未保留 | 继续 blocker |
| PROPER-04 | 真实练马师完整人名未保留 | 继续 blocker |
| PROPER-05 | 专名已使用中文译名 | 通过 |
| PROPER-06 | 专名已保留实际英文或 alias | 通过 |
| PROPER-07 | 地区不匹配术语 | 先地区排除，不做高成本分类 |
| PROPER-08 | 普通词降级但另有真实专名缺失 | 文章仍被真实专名 blocker 阻断 |

## 6. 索引与批次上下文

| ID | 场景 | 预期 |
|---|---|---|
| INDEX-01 | 100 篇同批次 | 术语索引只构建一次 |
| INDEX-02 | 不同语言/地区批次 | 使用隔离索引，不跨范围污染 |
| INDEX-03 | 新增或更新术语 | 后续批次重建新版本索引 |
| INDEX-04 | alias 启停或合并 | 后续命中与新状态一致 |
| INDEX-05 | 旧批次上下文仍在内存 | 仅当前批次可继续使用固定快照，新批次不得复用旧索引 |
| INDEX-06 | 大量术语无命中 | 不逐篇全量正则编译，查询和 CPU 有界 |
| INDEX-07 | 100 篇执行完整重复检测 | 重复候选语料按批次加载，不出现每篇一次的候选查询 |
| INDEX-08 | 100 篇读取马匹 alias/结构化证据 | 批量预取，不出现按文章或按命中 N+1 |
| INDEX-09 | 两次更新时间相同但 alias 内容不同 | 规范化快照 SHA 不同，后续批次重建 |

## 7. 重处理命令

| ID | 场景 | 预期 |
|---|---|---|
| CMD-01 | dry-run 指定地区和 24 小时 | 只扫描范围内未发布 core blocker 候选；文章零写入，仅持久化独立 Run/Lock 审计 |
| CMD-02 | limit=5 | 最多完整校验5篇，候选预筛选有界 |
| CMD-03 | 固定绝对窗口及 `(first_seen_at,id)` 复合 cursor 续跑 | 相同时间戳、跨时间戳及两页间当前时间推进均不重复、不遗漏，窗口结束后新稿不混入 |
| CMD-04 | 达到 max-seconds | 安全停止并输出下一游标 |
| CMD-05 | 任意地区第二个进程 | 在读取正文前因全局单例租约冲突退出 |
| CMD-06 | 进程异常退出 | 租约过期后可事务化接管，不永久占用 |
| CMD-07 | 人工终态/已发布/重复文章 | 不进入恢复候选 |
| CMD-08 | dry-run 运行记录 | 数据库持久化选择器、候选指纹、规则/设置/术语快照、分类、性能摘要和 manifest SHA |
| CMD-09 | commit run ID/manifest 不匹配 | 拒绝写入 |
| CMD-10 | 文章状态在 dry-run 后漂移 | 跳过并报告，不覆盖新状态 |
| CMD-11 | commit 完整通过 | 只恢复发布候选，不直接发布、不创建 QQ delivery |
| CMD-12 | commit 仍有 blocker | 保持人工审核并记录原因 |
| CMD-13 | 重复 commit | 幂等，无重复副作用 |
| CMD-14 | dry-run 后容器重建 | 运行记录和审核结果仍存在，可继续 commit |
| CMD-15 | 规则/设置/术语快照漂移 | 整批 commit 拒绝，文章零写入 |
| CMD-16 | 单篇源文/译文/状态漂移 | 只跳过该篇并报告，不覆盖新状态 |
| CMD-17 | 租约续期期间第二进程启动 | 第二进程退出；有效 owner 持续运行 |
| CMD-18 | 旧 owner 在租约接管后结束 | 不得释放或覆盖新 owner 租约 |
| CMD-19 | commit 中途抛异常 | 当前批次文章、AutomationLog 和恢复时间全部回滚，run 标为失败 |
| CMD-20 | commit 初检后术语库发生变化 | 写入前或事务提交前整批拒绝并回滚，记录预期/实际快照 |

## 8. 灰度模式

| ID | 场景 | 预期 |
|---|---|---|
| MODE-01 | mode=`off` | 门禁输出与旧实现一致，不产生新分类副作用 |
| MODE-02 | mode=`shadow` | 保存有界新旧差异审计，但文章门禁和工作流状态仍由旧规则决定 |
| MODE-03 | mode=`enforce` | 新上下文分类正式参与门禁 |
| MODE-04 | 非法 mode | 配置检查失败或保守回退 `off`，不得意外 enforce |
| MODE-05 | 从 shadow 切回 off | 新审计保留，后续文章恢复旧门禁 |

## 9. 产量投影与性能

| ID | 场景 | 预期 |
|---|---|---|
| PERF-01 | 生产等价100篇完整 dry-run | 60秒内完成、总 SQL 不超过35条 |
| PERF-02 | 性能报告 | 包含真实查询数、索引构建次数、赛事实体/外部马名 alias/额外马名术语/重复语料预取次数、扫描/完成数、耗时和内存证据 |
| PERF-03 | 36篇生产基线 fixture | 全部保持已翻译、>=75、无重复的投影属性 |
| PERF-04 | 普通词规则只清除部分 blocker | 分开统计清除、仍阻断和完整通过 |
| PERF-05 | dry-run 完整通过 | 不得计为已公开，只计恢复候选预测 |
| PERF-06 | 发布窗口后续处理 | 继续遵守每地区1-5篇、去重、配额和QQ规则 |
| PERF-07 | 100 篇完整 dry-run 峰值 RSS | 相比基线增量不超过 256 MiB |
| PERF-08 | 100 篇完整 dry-run 查询曲线 | 查询数不随文章数线性增长，记录术语/实体/重复语料预取次数 |

## 10. 模型、迁移和后台

| ID | 场景 | 预期 |
|---|---|---|
| MODEL-01 | SQLite/PostgreSQL 创建运行记录 | 状态默认值、JSON 字段、时间和索引一致可用 |
| MODEL-02 | 任意范围存在有效租约 | 单例 Lock 唯一约束与认领事务只允许一个 owner 成功 |
| MODEL-03 | migration apply -> rollback -> apply | 均成功，不修改既有文章数据 |
| ADMIN-01 | 非 staff 访问运行记录后台 | 被现有后台认证拒绝 |
| ADMIN-02 | staff 查看运行记录 | 可搜索状态/地区/run ID，字段只读，无直接发布动作 |

## 11. 回归和生产验收

| ID | 场景 | 预期 |
|---|---|---|
| REG-01 | 完整 stable 测试 | 全部通过 |
| REG-02 | Django check / migrations check | 通过且无意外迁移 |
| REG-03 | SQLite 与 PostgreSQL | 分类和游标行为一致 |
| REG-04 | 自然新稿 shadow 24小时 | 输出 common/uncertain/proper 和误放抽样 |
| REG-05 | 香港/英国/法国/美国小批量 dry-run | 各地区有文章级明细和人工抽检结论 |
| REG-06 | 近期历史小批量 commit | 只恢复候选，发布由后续窗口完成 |
| REG-07 | 上线后产量 | 分开报告 blocker清除、恢复候选、最终公开，目标新增2-5篇/天 |
| REG-08 | 回滚分类开关 | 恢复旧门禁，不删除审计结果、不改变已发布文章 |
| REG-09 | 生产容器环境 | HEAD、migration、mode、web/worker/beat 配置一致，日志和 `/healthz/` 正常 |
