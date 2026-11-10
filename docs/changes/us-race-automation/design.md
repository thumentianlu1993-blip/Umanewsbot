# 采集设计

## 来源选择

| 阶段 | 主入口 | 数据契约与未解决项 |
|---|---|---|
| 平地赛程 | TOBA 年度表 | 日期、赛名、场地、级别、距离、场地类型、条件、奖金；chart URL 只引用，不自动访问 Equibase |
| 障碍赛程 | NSA 条件册和结果 | 正文日期、赛事编号、级别、场地；已赛与未赛都是候选，不以名单空白推断状态 |
| 报名/出马 | Del Mar 目录、PDF、日期卡；NSA Entries 链接 | 报名排序不是马号，编号卡保留 finalized 状态；未支持格式明确报错 |
| 临场 | Del Mar changes | 正文日期/发布时间、马号/马名、退赛、负重、场况；旧日期不消费 |
| 全场结果 | NSA PDF；既有 Sporting Life 作为候选 | NSA 逐匹着差/赔率缺失；DRF 全窗口发现与可持续使用待证；TRA 北美缺权限 |

## 模块

- us_racing_sources.py：纯解析，BeautifulSoup/现有 pdfplumber，输出候选和来源字段，不联网/查库。
- us_source_collection.py：目录导航、受限 HTTP/缓存回放、回执与窗口报告。链接逐次验证；缓存按 URL SHA，记录原始字节 SHA、抓取时刻，重放不刷新抓取时刻。
- verify_us_sources：仅写指定目录。默认离线；allow-network 只启用三个公开来源的有界发现，不启用生产策略。至多80请求，每文档8 MiB，20秒读取超时；目录按日期过滤，同一URL每轮只请求一次。错误保留到报告并非零退出。
- 复用 race_data_source_adapters 的 discover_source_url/parse_reference_observation Del Mar 分支。只有明确正式卡可作为标准 observation；未定稿卡作为采集候选保留。policy、身份和 publication gate 不变。

## 身份与语义

有编号候选键为（来源、日期、场地、来源赛事编号）；无编号时使用（来源、日期、场地、规范化完整赛名）。缺日期的 not run 使用（来源、年度、场地、规范化完整赛名、not_run），只放年度 unresolved。相同键且所有业务字段相同才去重；同键字段不同记录 conflict 并保留双方，不最后写入覆盖。候选键只用于来源清单，不授予生产强身份。名称仅精确定位，无模糊跨源合并。Del Mar 固定 America/Los_Angeles，NSA 已核场地使用 America/New_York；未知场地待核，不能给全美国套一个时区。

名单完整与字段完整分开。result_phase 只来自结果正文；冠军时间属于比赛，胜出着差不是每匹落后冠军距离。PGM=马号、entries PP=页面当前位置（可能退赛后重排，不能当原始抽签）、chart PP=出发位置。

先解析 TOBA 所有等级，再过滤目标范围；被过滤行仍留来源库存供冲突核对。报告关联只在日期、场地相同且完整名称一致时进行；机械规范化可展开名称末尾 S. 为 STAKES，去掉末尾括号 Grade/Gr. 等级标识、统一空白/大小写；其他名称差异不猜测。Bob Hope 两源可因此关联，报告保存 Listed/G3 双方值、URL、原文SHA，不计入已确认生产分母，也不授予生产身份。其他跨源键碰撞或多解列 ambiguity。不自动解决等级/日期冲突；无日期 not run 留年度 unresolved。未发布、格式未支持、权限拒绝、网络错误、字段不全分别报告。

## 持久化与恢复

本批只落来源证据，无新增 Celery task/数据库变更，因此没有新事务/租约/迁移。标准 observation 仍过原身份与政策链路。报告临时写入后原子替换；原件按内容SHA存储，回执完整后可重放。刷新回执保留版本历史；解析失败恢复本轮刷新前的回放入口，成功解析才保留新入口。损坏PDF异常转为来源错误而非中断整批。报名目录月份/日期使用其fetched_at在洛杉矶的年份，再由PDF正文核验，不以重放年份推断。后续写入必须复用现有 claim/lease/baseline、owner/manual lock、幂等与交接规则。

不能取得全窗口完整结果、报名覆盖或使用条件时，列具体缺口，不提交“美国全范围可发布”发布包。采集层交付与整体上线分别报告。
