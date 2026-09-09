# 发布转换测试时钟与日历夹具修复

## 问题与范围

`RaceLivePublicationTransitionTests` 使用固定的 2026-07-20 时点创建来源、策略与
allowlist，有效期为其后 20 天。构建 manifest 和 apply 时间虽显式传入该时点，服务的
`_validate_exact_pre` 仍按 `timezone.now()` 重新核对权限是否到期。9 月执行测试时，
正常发布用例因此停在 `shadow contract` 校验，尚未运行原有发布、幂等及公开展示断言。
这项实时到期拒绝是正确的生产合同，不能改成信任回填的 apply 时间。

修改仅在共享测试夹具中以 `enterContext` 固定测试时钟，并自动恢复；其继承类和复用
setup 的 PostgreSQL 测试使用同一时点。补齐夹具的 `local_date`，使原有默认日历展示
断言使用实际有日期的赛事；当前 `public_default_race_date_window` 明确排除无日期记录。
不改应用、迁移、权限期限、公开规则、网络行为或现有测试断言。

新增回归独立验证来源、全局策略及官方核验路由有效期：每种权限在准备时有效，真实
时钟前进后，dry-run 和回填旧时间的 apply 都必须拒绝，且发布、旧赛果、事件、操作
日志及抓取状态不变。时钟恢复后，同一 manifest 仍满足 exact pre-state。

## 验证与交付边界

- 主线 `f62a6eda` 上原发布用例真实 RED：1 项，因 `shadow contract` 报错。
- 仅固定时钟后：新增到期回归通过；原发布用例运行到日历冠军断言才失败，证实缺少
  `local_date` 是后续夹具问题，而不是到期拒绝尚未解决。
- 首轮三个模块的离线 SQLite 回归共 54 项、14.123 秒：23 项通过，23 项测试产生 27 条
  错误记录，8 项 PostgreSQL 测试跳过。原发布/日历展示用例与新增到期回归在基类及
  继承类均通过。错误记录中 25 条受 Windows 目录 0700 权限限制；另 2 条是既有
  `QuerySet.update(slug=...)` 夹具违反模型写入合同，在生产候选的 Linux 基线也存在。
  本次不宣称三个模块全绿；固定候选的 Linux/PG16 CI 待提交后核验。
- 首轮 `9fef94fd` 的 [Linux/PG16 CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/34345529390)
  已按提交与构件 SHA256 核验：4,945 项、31 failures、223 errors、20 skipped，240 个
  唯一失败 ID；相对生产消除 34 个、无新增。新增到期回归无失败或跳过，45 项发布合同、
  Django check、migration drift 及正式前后指纹通过。相关模块仍有 4 条错误：两条 slug
  夹具错误由下述后续修复处理；另外两条是发布审计约束及官方发布的外连接加锁问题，
  继续单独排查。证据为 `runtime/fix-publication-test-clock/ci-comparison-r1.json`。
- 原生独立只读审核未发现新增可操作缺陷，静态解析和 `git diff --check` 通过。
  工作流合同检查仍有主线既有的 5 处文档旧引用，4 项合同测试中 1 项受其影响，
  已由独立 PR #186 修复；本分支没有更改检查器或降低规则。
- 证据保存在 `runtime/fix-publication-test-clock/`；全量修复数以实际 Linux 构件对照
  生产候选 `69955960` 为准，不将预估或独立分支结果相加。
- 本修复不操作生产；交付沿用根 [AGENTS.md](../../../AGENTS.md)。

## 后续身份漂移夹具修复

首轮的两条 slug 错误发生在夹具构造阶段：`RaceEventQuerySet.update` 正确禁止直接
更新身份字段，原测试尚未到达 manifest 漂移拒绝断言。现在通过读取独立模型实例并
调用 `RaceEvent.save()` 修改 slug，保留身份校验和公开路径同步；事务回滚后不留下
被改写的共享模型实例。测试先确认未改变的 manifest 正常通过，再保留全部 11 种
状态变更及原拒绝断言，避免由过期等无关错误造成假通过。

保存的首轮两条真实 RED 与本次 GREEN 对照位于
`runtime/fix-publication-test-clock/slug-regression-evidence.json`。基类和继承类的
身份漂移、正常发布/日历及到期回归共 6 项在离线 SQLite 下全部通过（4.186 秒）。
本次只重跑直接受影响回归；Linux/PG16 的固定候选结果仍需独立核验，不推算整套结果。
