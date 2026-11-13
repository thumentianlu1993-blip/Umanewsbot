# 英国付费传输修复

## 问题与范围

运行时 `_runtime_json` 复用 `the_racing_api_transport`，但该发送器原白名单只接受 Free／原精确结果端点。此前采集测试注入原件，未贯穿真实发送器，导致离线通过而自然调度拒绝 Pro 请求。修复为 `uk_paid` 增加已批准的四类端点；保留 HTTPS、精确主机、禁止跳转、GB、limit=20、skip=0..180 步长20，以及 big-races 最长60天窗口。既有 Free、result_by_id 与证明预算不变。

## 验证

新增测试保留真实 `_runtime_json -> _fetch_json -> the_racing_api_transport` 路径，只替换 DNS、HTTP 连接和共享预算存储；RED 复现白名单拒绝，GREEN 与原 Free 回归共32项通过。测试不访问生产或第三方。非法地区、分页、日期、重复参数、额外参数、主机和跳转边界在 DNS 前拒绝。独立复审及正式范围 CI 完成前不发布。

## 当前生产与修复包

生产数据包 `4caf8136` 已提交；100场、512行及100公开页已验证。候选 bda46916 的网站正常，Beat、worker、race_sync_v2_worker已停止。自然运行后控制字段和 source_refs 漂移，旧 after-image CAS 不匹配，未执行恢复。

修复候选 `282ae4f9ca1a624fc1e965faf50df8f993cebd07` 在 bda46916 上只更新发送器与测试文件。拟只替换四应用镜像及 release SHA，保留现有策略、数据包与公开数据，不迁移、不重导数据、不清理缓存、不重置熔断。新包将核对停服状态和当前数据、更新 web、验证健康与公开入口、启动双 worker、恢复 Beat 并验收当前正式卡／报名自然更新。若修复失败，恢复 bda46916 网站并保持 Beat／双 worker停止，不覆盖运行后数据。精确提交和镜像冻结后按根 AGENTS.md 交付。
