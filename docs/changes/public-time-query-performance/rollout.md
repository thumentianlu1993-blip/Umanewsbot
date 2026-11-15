# 交付准备

工作区 public-time-query-performance，分支 codex/public-time-query-performance，起点 633f80ce。仅本线程修改本工作区。当前尚未实现、验证、合并或发布。

候选无迁移、配置/开关、生产数据动作、采集或外发。预期只需重建 web；worker/Beat 代码不消费本次公开 SELECT 优化，发布时核对实际契约后精确列包。发布前读取生产 HEAD/镜像、任务、资源、锁并保护现场 GPTBot/Amazonbot 阻断与 robots。不能让全量配置覆盖既有热修。

回滚仅恢复获准发布前 web 镜像及原 compose 引用，无数据库恢复操作。验收首页、赛事列表、详情、health，以及同参数公开 SQL 结果一致性/目录扫描次数；固定预算单轮、单条 SQL 10 秒，异常停止并回滚。生产动作和合并按照根 AGENTS.md 的 G2/G3；本文件不定义新的人工门禁。
