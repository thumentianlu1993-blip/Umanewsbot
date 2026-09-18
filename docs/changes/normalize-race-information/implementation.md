# 赛事信息归一化实施记录

2026-09-18。用户指令“开始实现吧”后，从联网刷新确认的 `origin/main@91410e7aa077a0b3ea963cccfcd64b935f4369d1` 创建独立 `codex/normalize-race-information`，目录 `/private/tmp/umanews-normalize-race-information`。原 `horse_data` 脏工作区未切分支、未清理。

## 实现与覆盖

- 在既有 `race_field_normalization.py` 增加独立严格展示解析器；旧写入解析和统计合同保持原样。使用不可变 `DisplayField`，含状态、原因、规则版本和输入摘要。
- 距离使用 Fraction 精确计算与 Decimal 输出；公制统一米，英制只展示英里／英尺并附约合米。未知单位、含糊 `m`、裸数字、残留文本和冲突均待核实。
- 等级完整匹配体系与数字，展示 `G1`、`Jpn2`、`J-G3`、`L`、`OP`；保留年度，未知／冲突不猜。类别与等级分离。
- 年龄性别、材质、赛种、路线、负重、计时、差距、编号、热门排名、赔率和时间共用解析；天气、going体系、币种／奖金口径缺证据时保留缺失／待核实状态，不造卡片。
- `RaceTermResolver(mode='strict_display_v1')` 统一五种实体。主值与别名先合并、按实体去重；类型、地区、语言隔离，同层冲突不任意挑选。大小写、全半角和空白用于匹配，不机械改专名大小写。每请求最多10次术语查询。
- `prepare_context` 在现有视图选择公开对象之后运行。接入日历、详情、首页、侧栏、快讯、新闻卡片、马匹履历／主要胜场及后台预览；支持 ORM、dict、SimpleNamespace。不会反查被隐藏的赛果。
- 历史记录日期／名次使用共用适配，明确同着状态保留；关联赛事只有已公开且已加载时才能提供元数据。计时沿用既有确认条件。
- 后台候选预览为请求内临时值，出马／赛果最多预览20行，不修改 `candidate_payload`、`diff_payload`、人工锁或应用状态。
- 新开关 `RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED` 默认 false，关闭后恢复原模板、模型属性和 legacy resolver。数据库迁移0、业务回写0、新任务0、AI调用0。

## 来源证据与限制

只读取 `source_refs.field_units` 的显式字段单位声明；不按国家、域名或数字大小猜单位。当前没有新增来源推断注册表。已有真实 JRA fixture 明示 `kg` 可直接解析；缺少单位声明的旧数据可能展示“待核实”，需后续只读盘点后补充经证实的来源映射。已有术语ID如果没有可核验的年度／地区关联证据，也不无条件覆盖年度名称。SQL不全表扫描，无法召回的特殊Unicode别名仍是待补缺口。

不重翻译新闻正文、简介／血统等自由文本；赛事原名作为原文对照仍保留。没有宣称全库数据已经清洗、词库全部翻译或生产已启用。本轮无生产读取，线上覆盖率及开关状态未知。

## 只读盘点

新增 `preview_race_information_normalization`，不提供 apply。离线 JSONL 不连接数据库；库内必须指定 `--from-db --database default --model --region --year`，连接地址／只读账户由环境显式配置。PostgreSQL使用只读事务，SQLite使用 query_only；测试验证写SQL被拒绝。

每次默认200条、最多10000条，每批200，按主键递增，可用 `--after-id` 续跑。输出路径必须不存在，目录权限0700；JSONL只包含字段原值／展示值／状态／摘要，summary记录范围、游标、完成状态、规则版本、文件实现摘要和调用者提供的代码SHA。代码SHA是调用者声明，须绑定实际固定checkout；实现摘要可识别同SHA下的工作区差异。报告不保证跨批一致性快照。原值和展示值均脱敏URL查询参数，不输出完整 raw_payload/source_refs；失败报告 `completed=false`。

离线示例（输入按整数id递增）：

```bash
python server/manage.py preview_race_information_normalization \
  --input /absolute/path/events.jsonl --model event --limit 200 \
  --code-sha <实际40位提交SHA> --output /absolute/path/new-report
```

## 验证

最初3项入口测试中2项有效RED（Jpn大小写、英制单位），其后严格解析和页面测试GREEN。最终测试、基线差集、独立review见 `validation.md`。本地隔离PostgreSQL与主线基线使用独立数据库；测试禁止真实外网，不使用生产数据库／Redis／队列。

## 发布前单位来源适配（2026-09-18）

补充仅2026年的JRA/NAR/France Galop目录及HKJC官方本地赛事合同，以来源标识、HTTPS官方地址、地区/年份和完整数字+m确定公制；未知来源和裸数字不作推断，显式单位冲突拒绝，候选替换距离须用自身来源证据。只是展示，不回写。来源对照：[NAR目录](https://www.keiba.go.jp/dirtgraderace/2026/racelist/index.html)、[France Galop目录](https://www.france-galop.com/sites/default/files/2026-02/groupes_listed_plat_2026_v7.pdf)、[HKJC官方途程列](https://racing.hkjc.com/racing/english/international-racing/g2-g3-races/index.aspx/1000)。后续年份须重新验证合同，不能自动外推。
