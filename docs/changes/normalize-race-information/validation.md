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

## 全量状态（本地交付准备时）

完整stable发现候选5084项。主线与候选完整测试正在独立数据库执行，尚无最终差集结论，不能称全量通过。驱动复用仓库CI的DiscoverRunner结果收集方式，另外移除继承代理、阻断外部DNS/TCP；只允许本任务隔离PostgreSQL端口。早期未收紧代理隔离的完整运行已主动中止，不作为全量完成证据。当前原始日志和最终JSON写入 `/private/tmp/race-normalization-full-{baseline,final}-isolated.*`；完成后更新本节。

本轮没有读取／写入生产，没有在线覆盖率或发布验收结论。默认关闭开关不代表线上生效。远程push被自动审批拒绝，未创建Draft PR；当前只交付本地分支。
