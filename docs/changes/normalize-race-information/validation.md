# 验证记录

基线：`91410e7aa077a0b3ea963cccfcd64b935f4369d1`。业务代码在独立审阅第三轮后冻结，见[代码审阅记录](CODE_REVIEW.md)。

## 已完成

- RED：3项入口测试，2项因待实现行为失败；日志SHA256 `687700f16788478a0cc87a3b9fddd5da0f31513d8965c1495a4d45aede1694e6`。
- 新增31项SQLite测试全通过，含解析、模板、术语冲突、五地区、历史记录、候选预览及只读报告。
- 新开关开启下93项隔离PostgreSQL测试全通过，包含上述31项及JRA赛前、人工核验赛前、实时赛果可见性门禁。0跳过。
- 独立审阅3轮，10项P2已修复；最后14项独立内存验证通过，APPROVED。
- Django check、makemigrations --check --dry-run通过（无迁移）；工作流合同与4项合同测试通过；git diff --check通过。
- 40场、200条唯一出马行使用10次术语查询；原始业务字段不回写，候选payload/diff不修改，隐藏赛事未补查。

93项命令（必须显式配置本地隔离PostgreSQL、内存broker及禁用dotenv）：

```bash
RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=true python server/manage.py test \
  stable.test_race_information_display stable.test_race_information_display_pages \
  stable.test_race_information_preview stable.test_race_pre_race \
  stable.tests.test_reviewed_pre_race \
  stable.test_realtime_race_results.RaceLivePublicStatusTests --noinput
```

## 完整stable对照已完成

| 版本 | 测试数 | 失败 | 错误 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| 固定主线91410e7a | 5053 | 18 | 194 | 18 |
| 本次实现71a820bd | 5084 | 18 | 194 | 18 |

按 `(failure/error类型, test.id)` 多重集比较，新增0、消除0；异常类比较也相同。新增31项均通过。此结论是同一隔离环境下未发现新增失败，**不是全量全绿，也不是GitHub CI或生产验收通过**。精确失败名称、次数、日志及原始JSON SHA256见 [full_suite_evidence.json](full_suite_evidence.json)。两份原始日志／结果位于 `/private/tmp/race-normalization-full-{baseline,final}-isolated.*`。

本地环境：macOS、Python3.12、Django5.2.1、专用PostgreSQL16容器；候选／主线独立数据库，禁用dotenv、内存broker/cache、移除继承代理、禁止外部DNS/TCP。完整套件使用默认关闭的新开关，相关93项另外显式打开新开关。代码运行内容绑定71a820bd；运行期间仅清理两行行末空白，AST完全一致，未更改业务逻辑。早期未收紧代理继承的完整运行已中止，不作为完成证据。

基线错误包含环境限制：96条NotADirectoryError（macOS `/var` 符号链接），部分artifact安全校验因 `/var` 与 `/private/var` 路径差异拒绝，14条FileNotFoundError中包含子进程找不到 `python`。另有固定主线本身的断言／数据约束失败。本次没有把全部212条失败／错误都归为产品缺陷，也没有修改不相关的采集、发布或数据库合同来让测试通过。后续Linux CI应使用规范临时路径及正确虚拟环境PATH重新核验这些平台相关入口。

本轮没有读取／写入生产，没有在线覆盖率或发布验收结论。默认关闭开关不代表线上生效。自动审批拒绝了远程push，未创建Draft PR、未运行GitHub CI；当前交付本地分支，远程操作仍待用户明确授权。

最终定向日志SHA256：

- `race-normalization-round2-tests.log`：`b4b283790d8ba915d02605510444c547892b33a71b577d03624785db5484e0b2`。
- `race-normalization-round2-postgres.log`：`330f5c4914763122de6e4d33262bb01400416fb47203c391cfeec2769107bf89`。

## 2026-09-18 发布前兼容修复

生产服务器内只读聚合发现25条中12条m缺少新单位元数据。新增官方目录合同适配；两项测试先取得6处预期失败，最终归一化三个模块35项通过。原独立reviewer复审APPROVED。此增量不重跑本机5084项；最终PR Linux CI和候选镜像实际聚合另行记录。

### 真实格式补充后的最终局部验证

服务器候选只读预览发现场地前后缀、千分位、abt、yds及JRA“等级+原名”尚不兼容，已据公开网页补充完整消费语法，等级去尾须匹配官方目录和原名。37项归一化测试通过；同一独立reviewer再次APPROVED。最终隔离overlay在相同25场得到等级25条normalized，距离24条normalized、1条原缺失、unknown/conflict均0；overlay版本不能冒充最终镜像，后续固定镜像仍需复验。全部明细保留服务器，仅输出聚合，未业务写入。
