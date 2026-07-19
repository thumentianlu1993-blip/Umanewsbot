# 项目总览

## 产品目标

构建一个供认证内部用户使用的中文赛马资讯工作台，将多地区赛马资讯采集、翻译、校对并形成
可检索的内部内容；当前产品边界不向匿名访客、搜索引擎或社群公开新闻原文和译文。

## 核心链路

项目主链路为：

`抓取 -> 翻译 -> 术语纠偏 -> 人工编辑审核 / 内部发布 -> 认证后网页端`

每一环的职责：

- 抓取：从上游来源拉取新闻列表与详情
- 翻译：先按来源正文边界移除网页框架、编辑注、无关链接和博彩推广，再将正文翻译为中文；赔率与作为赛事标题、马主等专名组成部分的博彩公司名称允许保留。日文普通赛马词、拍卖产驹、追切、访谈和出马表等场景使用字段级占位符与确定性格式保证完整、统一输出
- 术语纠偏：通过术语库保护专有名词和完整未知马名，未知马名不得按已知子术语拆译；人物、机构、普通词和英文单词型术语按文章上下文区分专名、马匹、普通词和不确定用法。不同来源语言只使用相应来源名匹配，中文译名仅用于中文文章反向识别
- 人工编辑审核：在后台修订标题、正文、摘要、标签
- 内部发布：沿用发布状态表达“内部可阅读”，所有页面、API 和 media 均要求认证
- 外部分发：QQ、旧手动 PushLog 和包含新闻内容的邮件/QQ 通知在内部模式下一律阻断

## 当前核心来源

- `netkeiba`
  - 新着顺
  - 访问量榜
  - 注目数榜
- `JRA`
  - 官方新闻

## 多地区新闻生产边界

项目当前仍以日本赛马新闻为主线，既有线上模型具备中国香港、英国、法国、美国新闻源承载
能力；当前无提交候选进一步支持把爱尔兰、加拿大、阿联酋、沙特和澳大利亚作为五个
独立新闻地区。
阿联酋和沙特可以在界面视觉上归入“中东”，但持久化、来源准入和灰度必须分开，不使用
`middle_east` 合并键。地区 choice 与 race-live 主线的两条 `0047` 由
`0048_merge_20260719_2242.py` 汇合，第三批 SourceSite choices 由后续 `0049` 承接；第二轮
main 基线的另一个 `0048_raceeventrunner_external_runner_identity.py` 最终与功能
`0049` 汇入无操作 `0050_merge_20260720_0017.py`，形成该基线唯一 migration leaf；当前
候选已重新集成 `origin/main@a122ff6d…`，须在本候选重验 DAG；
赛事与马匹运营表单以及 Django `RaceEventAdmin` 仍只允许旧五区加 `other`，既保留旧
`other` 记录的可编辑性，也不开放新五区结构化录入。实际抓取任务、自动选择器、公共
horse/race resolver 以及 historical、P0、race-live capability sets 仍锁在日本、中国香港、
英国、法国、美国五区。本任务没有提供新五区结构化数据抓取或生产能力。多地区常态生产遵循
灰度原则：

- 通用 enabled 来源轮询默认关闭，启用时按地区、来源、抓取间隔和每轮上限运行。
- 非日本新闻默认人工审核，只有显式配置允许的地区和来源才进入内部已发布状态。
- QQ 群 `allowed_regions` 只保留兼容数据；内部模式下不会产生任何新闻内容发送。
- 外部赛马数据库 importer 只作为受控数据导入与马名识别底座，不属于新闻常态调度。
- 代码侧支持按赛事、马匹、骑师、正文语境和来源证据计算主地区与相关地区，并以 `off|shadow|enforce` 分阶段启用；相关地区页面和 QQ 查询另有独立开关。
- 法国来源发布时间分为已验证时间与 fallback 时间，未验证时间不得绕过新鲜度门禁；瞬时翻译失败可有界重试，但自动调度默认关闭。
- 这些能力只有通过真实 gold set、生产 dry-run 和灰度验收后才可开启，迁移和部署本身不会改变现有线上归属或自动重试行为。
- 新地区和新来源逐项记录技术可达、内部 scope、公开禁止和 terms risk；透明请求技术 blocked
  的来源不绕过，技术 accepted 也不会自动启用。第三批十二个直接来源已经实现且仍全部
  `enabled=false / production_approved=false`。迁移后的仓库外 `/tmp` SQLite 受控 live
  probe 使用透明 bounded HTTP、每源 listing `1`/detail 最多 `2`、零生产写入；24-source
  registry 为 `16 accepted / 8 blocked`，第三批自身为 `8 accepted / 4 blocked`。
  HRI/Woodbine/ERA 虽 listing HTTP `200`，仍因详情 `missing_published_at` 端到端 blocked；
  JCSA/Racing Victoria live accepted。来源级
  `usage_scope=internal_only` / `public_publish_allowed=false` 独立于全局登录墙，公开查询、
  详情和 QQ 必须共同阻断。Ireland/Canada 可复用英美/全球来源的强赛事信号。只有发表日期的
  可信稿按来源当地发表日与抓取日绝对日差 `0/1` 进入候选，`>1` 记为
  历史，缺失或未验证时间为 `unresolved` 且不入库。Google News discovery 不属于本批实现。
- 最新约 `2026-07-19T17:41Z` 的严格六小时候选只有 Ireland `2`；Canada、UAE、Saudi、
  Australia 均为 `0`。本轮样本均为精确时间，没有用 date-only 规则提高数量。真实 RTÉ
  正文已用 dummy provider 跑通 translation task/`TranslationRun` 持久化，但本机无
  SiliconFlow/OpenAI key，真实中文远程模型仍未验证。
- 旧 QQ 灰度字段保留但在内部模式下不发送新闻；恢复外部分发必须另起任务。
- translation/rewrite 的外部 AI 处理由共享
  `NEWS_EXTERNAL_AI_PROCESSING_ENABLED=false` 默认门控制；站点内部总门默认
  `SITE_INTERNAL_ONLY_ENABLED=true`。失败通知只能发送无新闻内容的白名单运维摘要。
- 内部模式上线必须启用 secure session/CSRF cookies，并选择 direct HTTPS redirect，或显式
  `SITE_INTERNAL_ONLY_TRUSTED_TLS_TERMINATION=true` 加合法
  `SECURE_PROXY_SSL_HEADER` HTTPS 反代合同；同时还需受认证 local media 或私有 OSS 短期
  签名。不安全组合 fail closed。
- 外部 AI 关闭时 translation retry 不 claim，preclaim 会释放，batch skip 不计 translated；
  运维通知仅允许安全 counts/IDs，文章级失败通知为 `article_id`-only，不包含来源 URL。
- 首次代码审核七项 finding 已修复，但完整性门禁仍为 `BLOCKED`。当前候选已重新集成
  `origin/main@a122ff6d…`，`origin/main..HEAD=0`，仍须由同一 reviewer 复审最终精确版本；
  代码未部署，生产仍未内部化。

## 准实时赛事赛果链路

准实时赛果与新闻、历史回填分离。来源事实先保存为 append-only observation 和 immutable
revision，再经四层 policy、逐赛事 allowlist、来源条款/authority、participant 完整性和
owner/claim CAS 决定是否形成公开 projection。The Racing API 只提供快速
`provisional_result`；官方来源的独立 evidence 才能支持后续 `official_result` 或
`corrected_result`。

首个公开候选只覆盖英国 event `924` 的已存 shadow revision，使用无网络、可哈希的
promotion/disable/restore manifest。暂定赛果可以先公开，但页面必须清晰显示“暂定”与
“尚待官方来源复核”；BHA 当前只采用人工浏览器复核和离线 evidence receipt，不自动抓取，
也不复制第三方评级、评论、赔率或页面正文。scheduler 默认关闭，其他赛事和地区不会因
部署代码自动进入公开范围。

## 历史赛事数据链路

历史赛事与新闻常态任务分离，按“正式总账 -> selection artifact -> 网络抓取 artifact -> 离线打包/dry-run -> 受控落库 -> 逐场验收”推进。batch006 起标准批次为单地区最多 250 场，仍保留地区进度、排除 snapshot、来源身份、审批 SHA、写前备份和 draft 可见性门禁。

正式批次使用 typed recipe 的分片计划：每个 shard 从实际输入内容证明 target scope，plan 同时绑定 selection、approval、manifest、镜像、工具和资源预算。日期与详情碎片只产生完整候选或带证据 gap；数据库写后由只读 verifier 核对来源、模块、数量、provenance 和 draft 状态。地区距离单位按来源原文保留，不在编排层统一换算。

长周期历史任务由独立原生 Docker runner 执行，不加入 Celery/Beat，也不属于普通 Compose project。crawl 与 apply 使用不同网络和数据库角色；runner 只按固定镜像和结构化 plan 执行，依靠数据库租约、runtime 文件锁、心跳和双 checkpoint 恢复。普通应用部署不得处理 runner、DB、Redis 或共享网络。

正式 artifact 流水线已在生产镜像 `main@ab95c6ef` 部署并通过隔离、暂停恢复和工具根拒绝 smoke。年度赛历 request/cache/parse 扩展已完成本地验收，法国 2023-2024 达到 `250/250`；batch006 将按冻结的 1061 场 selection 拆为 11 个地区×年份 scope，待新镜像部署后开始抓取，历史公开继续关闭。

## 技术栈主干

- Web / 后台：`Django`
- 数据库：`PostgreSQL`
- 异步任务：`Celery`
- 队列 / Broker：`Redis`
- 容器编排：`Docker Compose`
- 反向代理：`Nginx`
- 翻译接口：`OpenAI-compatible`，当前已支持 `SiliconFlow`
- 媒体存储：`本地磁盘 / 阿里云 OSS`

## 后台、前台、分发渠道定位

### 后台

后台承担运营与审核职责，主要用于：

- 查看抓取文章
- 维护术语库
- 编辑译文
- 审核发布
- 查看来源状态与任务状态
- 手动触发推送

当前业务后台入口为：

- `/admin/`

`Django Admin` 作为框架自带原生后台保留，用于底层数据排查与管理，不作为日常运营主入口。

### 前台

前台承担内容展示职责，主要用于：

- 向认证内部用户展示已发布新闻列表和文章详情
- 向认证内部用户展示赛事日历与年度赛事详情页，用于把赛前资料、赛后赛果和相关新闻按赛事组织
- 向认证内部用户展示已发布马匹资料页，并支持用户关注马匹及其子孙代相关新闻
- 匿名 API、sitemap 与 media 不提供业务内容；`/healthz/`、登录和静态资源是最小例外

当前生产域名仍为：

- `umafans.run`
- `www.umafans.run`

当前生产仍是既有公开 HTTP 运行态；本次内部访问代码尚未部署。完成 HTTPS/获准 TLS、私有
media、独立代码审核和用户新授权前，不得把上述域名写成已内部化。

赛事数据在后台分为三层口径：截至 2024 年的历史正式总账、2025 年以后的当前/未来正式赛程，以及超过宽限期后的赛果完成度。公开日历可以包含展示扩展赛事，但不得因此改变正式总账或赛果完整率；正式目标与公开赛事通过赛事系列和官方届次唯一关联。

### 分发渠道

目标分发边界为：

- 网页端仅限认证内部访问
- QQ Bot、旧手动 PushLog 和包含新闻内容的邮件/QQ 通知一律阻断
- 运维通知只允许任务名、稳定错误分类、计数、时间和内部对象 ID 等白名单字段

这一边界已在本地代码实现并通过聚焦测试，但尚未部署到生产。
