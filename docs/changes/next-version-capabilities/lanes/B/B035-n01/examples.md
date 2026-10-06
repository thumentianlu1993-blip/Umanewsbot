# B035：三个正文清洗实例

全部为本地开发示例，不是F02真实gold或生产验收。没有抓取、模型调用或数据库写入。真实抓取时间无法从fixture确认；演示生成于2026-10-06。

## 正常正文

既有开发反例 hrn_normal_article.html（非真实gold）

结果：`ok`；正文容器：`.article-body`。

清洗前（仅用于本地对照的页面文本）：

```text
The trainer opened the season with a patient plan for the unbeaten colt.

The next target

The team will use a local prep before travelling in October.

We will let the horse tell us when he is ready.

A quiet week at the farm.

One final breeze before entry day.

The colt returned home sound, and the full campaign remains intact.
```

清洗后：

```text
The trainer opened the season with a patient plan for the unbeaten colt.

The next target

The team will use a local prep before travelling in October.

We will let the horse tell us when he is ready.

A quiet week at the farm.

One final breeze before entry day.

The colt returned home sound, and the full campaign remains intact.
```


## 导航广告污染

合成开发样例；使用既有Sporting Life Article__ArticleBody结构（非真实gold）

结果：`ok`；正文容器：`[class*='Article__ArticleBody']`。

清洗前（仅用于本地对照的页面文本）：

```text
Local test
Navigation links
Blue Horizon is 7/2 for the feature race.
Book now the festival begins on Saturday.
Free bets sign up offer.
The rider said the plan remains unchanged.
```

清洗后：

```text
Blue Horizon is 7/2 for the feature race.

the festival begins on Saturday.

The rider said the plan remains unchanged.
```

- `body-020417ad384c01e6ef03` — removed / structured_noise：Navigation links → 删除
- `body-d7682d2e2ecc1be554c6` — modified / link_cta：Book now the festival begins on Saturday. → the festival begins on Saturday.
- `body-caf915553150c8ce408b` — removed / betting_promotion：Free bets sign up offer. → 删除

## 正文不足：可信容器缺失

合成模板漂移例（非真实gold）

结果：`selector_not_found`；正文容器：`未找到`。

清洗前（仅用于本地对照的页面文本）：

```text
Template drift
Log in for free bets
Top Stories
```

清洗后：

```text
（无可采纳正文，明确报缺口）
```


区块ID绑定来源、捕获正文HTML摘要、逻辑位置与原文。同一输入可重复生成，重复段落不会合并；不同捕获不冒称同一持久身份。`paragraph[n]`指结构噪声去除后的逻辑段落序号；结构噪声使用去除前DOM路径。原始页面HTML沿现有字段保留，区块含原文、结果、原因，供既有元数据消费者使用。

剩余：五地区真实启用模板、独立gold误删/污染率、生产持久化和现场验收未完成。
