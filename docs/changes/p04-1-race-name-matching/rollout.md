# 赛事名称接入交付设计

当前处于交付准备，未合并、未发布。人工门禁仅引用根 AGENTS.md。

## 已核基线

2026-11-15只读核对四应用均为 `e6c47a98569f9eef626ac905f989cb9ba20b6726`；Web healthy，
统一赛事展示已启用、HKJC目录未配置，QQ关闭，上一发布owner已释放。
容器完整Compose链及镜像身份保存在本轮runtime的baseline.json；不能拿宿主旧checkout代替运行版本。
主线 `efb2a6c7` 与运行提交同树。本分支已整合该主线，待更新的settings、race_information_display、race_term_display
三个既有文件在生产镜像中与主线逐字节相同，可采用基于现有生产镜像的增量构建。

## 发布包内容

- 包含名称解析代码、真实目录、展示接入和范围测试；精确commit/PR、镜像digest、包SHA在冻结后的执行清单绑定。
- 目录位于 `/app/server/stable/data/hkjc_name_catalog_20261115.json`，SHA为
  `675fa8e79fef4b8cffb495dff1bc4a515732d97fa999aa99eb01db28612f78c5`，共20519条来源证据。
- 在现有完整Compose链后追加本包覆盖，四应用设置RACE_HKJC_NAME_CATALOG_PATH和RACE_HKJC_NAME_CATALOG_SHA256；
  原RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=true保持。
- 无模型/迁移、无业务数据写入，无爬取/调用扩量、无对外消息、无采集或新闻功能开关变化。
- 四应用web/worker/race_sync_v2_worker/beat重建；Nginx按原维护方式检测并重新加载上游。
- 延续现有唯一发布协调器及OS锁：配置/镜像/目录/版本预检，暂停Beat，排空worker，保存原配置恢复面，
  切换Web并验证名称页面，再恢复双worker和Beat；不清队列、不撤销任务。

## 验证与恢复

候选镜像先在隔离环境验证：完整目录SHA及关键映射、页面输出与原数据守恒、开关关闭回退、未知及冲突保留。
发布包执行时再次核对固定基线及数据库schema；公网抽查日本/英国/法国/美国与香港既有名称回退，
覆盖出马表/赛果/历史冠军，核四应用版本和双worker就绪。

失败时恢复原完整Compose链及固定 `e6c47a98569f9eef626ac905f989cb9ba20b6726` 应用镜像和原配置；
也可按包内流程清空名称目录配置关闭本功能。无数据库回滚、无原始数据覆盖；保留期间自然采集的数据。
不得把尚未运行的预检、CI、回滚演练或公网验收记为完成。
