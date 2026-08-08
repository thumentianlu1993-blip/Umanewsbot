# 发布与运行计划

## 发布包

- 代码：本 change 的固定 commit/PR；
- migration：无；
- 配置与开关：无变化，历史写入开关在 census 审核前保持关闭；
- 服务：构建固定镜像并按受保护 deploy 编排重启 web/worker/beat/nginx；
- 验证：服务健康、Django check、migration plan 为零、生产 12 对只读身份复算；
- 回滚：在任何数据 apply 前可直接回滚上一镜像；数据 apply 后使用同 manifest 的 exact rollback。

## 数据阶段

1. 生成新的 no-replace census 目录，保存 manifest/census/template/summary 的 size 与 SHA。
2. 独立审核全部 14 actions。12 个 duplicate boundary 必须逐对确认官方身份和 survivor；另外两个
   series 必须审核 edition/target/path 变换。任何模糊项输出给用户并等待，不猜测。
3. 绑定 reviewed manifest、approval、action scope、maintenance evidence 和新备份执行 apply。
4. 运行 verifier，保存 receipt、rollback artifact 与健康证据。
5. verifier 通过后才启动 2025 `full_network=true`；临时网络错误按精确 checkpoint 最多 6 个 run，
   确定性错误立即停止并一次性报告。

## 当前状态

实现与 36 项 Release B 测试已通过；独立只读 review 未发现 actionable defect。尚未提交、合并或
部署，未生成新 census，零生产写入。
