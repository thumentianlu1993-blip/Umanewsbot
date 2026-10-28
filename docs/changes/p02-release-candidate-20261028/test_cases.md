# 验证

本次验证：全新 PostgreSQL 隔离库，核心与地区 115 项；既有受影响套件；makemigrations --check；从0079迁移到目标的精确计划；依赖清单和 git diff --check。首轮测试环境使用 SQL_ASCII 导致 Unicode JSON 错误，已重建专用 UTF8 库复验，不能记录成产品 RED。

后续执行器必须先有拒绝错误数据库/commit/image/manifest/备份、非0079起点、非前缀续跑、并发 coordinator、残留 writer、超时、catalog 漂移、未完成static而误签complete的真实失败测试，再实现；使用合成数据和隔离副本，不访问生产或来源服务。故障注入覆盖每个停服、备份、DDL提交、static和服务恢复切点。

当前519项不同测试通过（115+124+137+90+53）。主线缺少交接分支额外测试，所以不能沿用历史491/318计数。完整选择列表见validation.json。

迁移验证最初只建立stable0079，auth停在旧依赖节点，post_migrate权限字段长度报错；该库废弃。最终在另一全新库先建立全部框架叶和stable0079，再运行精确六步计划，target叶/空剩余计划核验通过。合成空库时长不能作为生产锁预算。
