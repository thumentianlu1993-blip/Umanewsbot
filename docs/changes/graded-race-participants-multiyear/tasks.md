# 任务清单

- [x] (application) 固化单年份、全体实际参赛马、扩展地区与三语马名数据契约。
- [x] (application) 新增纯函数测试：结果状态、地区识别、等级范围、马名推导。
- [x] (application) 新增通用年度采集器，不覆盖旧 2026 artifact 脚本。
- [x] (application) 实现 discover/races/merge_races/profiles/merge_profiles/finalize 分阶段运行。
- [x] (application) 实现原子 checkpoint、稳定分片、resume 和 time budget 安全停止。
- [x] (application) 移除 Wikipedia/Wikidata 依赖与输出。
- [x] (application) 实现非日本/香港英文名质量门禁和复核队列。
- [x] (integration) 仓库 CI 已完成 py_compile、14 项专项测试和 diff check。
- [ ] (integration) 使用少量赛事 URL 做一次真实网络 smoke run。
- [ ] (review) 由未参与实现的 reviewer 做只读代码审核。
- [ ] (operations) 用户确认后再决定是否执行完整历史年份任务；不部署生产、不写数据库。
