# 任务

## 测试

- [x] (operations) 为备份、上传、恢复和 Nginx 配置新增真实 RED 合同。

## 实现

- [x] (operations) 修复 low-cost/RDS 备份与恢复网络边界、原子发布和校验。
- [x] (operations) 修复 OSS endpoint 示例、容器化上传与远端大小复核。
- [x] (operations) 将已验证生产 Nginx 配置同步回仓库。

## 验证

- [x] (operations) 备份/Nginx 16 项与组合 195 项测试、shell syntax、Nginx SHA、Django/
  migration/workflow contract 和 `git diff --check`。
- [ ] (operations) 在候选镜像内执行真实 local backup、TOC 与 OSS 只读/上传 smoke。

## review

- [x] (operations) 独立只读首轮 3 项 P1 已测试先行修复；同一 reviewer 第 2 轮复审 `APPROVED`，
  审前后 fingerprint 均为 `720e872ff30d19fb93d485859f6c0be886b84059b56b574c05c0c405f150092a`。

## 发布

- [ ] (operations) 经精确 G2 commit/push/PR/merge 并 false/off 部署。
- [ ] (operations) 在共享部署锁内修正生产 OSS endpoint，执行新 backup+upload+head verify。
- [ ] (operations) `nginx -t` 后平滑 reload，禁止重启数据库或启用 lifecycle/race-live。
- [ ] (operations) OSS 恢复证据成立后，另行生成本地备份清理 manifest；删除仍需独立授权。
