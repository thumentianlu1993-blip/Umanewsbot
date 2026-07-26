# The Racing API schema v2 proof runner 任务

## 测试

- [x] (integration) 为 v2 显式 region、固定路由、实际 path artifact 编写测试并取得真实 RED。
- [x] (operations) 为管理命令 `--region` 透传和缺失 region fail-closed 编写真实 RED。
- [x] (integration) 为非法/缺失 region、registry budget 和 transport 零调用编写测试。
- [x] (integration) 修复旧 unsafe URL 测试，确保 resolver 未被调用且测试环境绝不联网。

## 实现

- [x] (integration) 在 proof service 中按 schema v1/v2 分流并保留 v1 兼容。
- [x] (integration) 通过受审 route builder 构建 v2 固定三路由并记录实际尝试 path。
- [x] (operations) 管理命令新增 `--region` 并把合同错误转换为 `CommandError`。

## 验证

- [x] (integration) 运行新增测试、完整 proof、多地区 pipeline 和 racecard sync 回归。
- [x] (application) 运行 realtime 失败用例基线对照，排除本次回归。
- [x] (operations) 运行 Django、迁移漂移、编译和 diff 检查。

## review

- [x] (integration) 复用独立 reviewer 会话关闭 P1/P2 finding 并取得 `APPROVED`。
- [x] (operations) 冻结 review fingerprint；review 后任何变更必须重新复审。

## 发布

- [ ] (operations) 用户授权后才允许 commit、push、PR；本轮不部署。
- [ ] (operations) 针对精确 fingerprint 另取最多 3 请求的只读联网授权。
- [ ] (operations) 联网前核对 secret 元数据、registry SHA/有效期、唯一 output 和零业务写入。
- [ ] (integration) 保存并验证去敏 artifact；不得据单次 proof 声明覆盖率或实时性。
