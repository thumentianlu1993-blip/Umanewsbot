# 法国赛前身份种子修复与验证

范围：通用身份读取接纳法国采集器已校验的 Geny 正式编号赛卡；沿用现有候选、baseline、来源路线、摘要、重新取页、强身份、名单完整性和原子登记协议。不接纳 France Galop 报名或候补名单，不更改其他地区逻辑，不迁移。

用例：
- 无既有来源、无系列别名绑定时，冻结真实 Geny 赛卡由 france_pre_race_v1 保存，可生成身份收据并登记，正式赛果发布及重复观察幂等。捕获遗漏法国类型。
- registration/declared、无编号/重复编号、非 Geny URL、赛事日期/外部 ID 不一致、非法国赛事均拒绝。捕获错误扩大身份证据范围。
- validated=false、baseline 漂移、摘要非法仍拒绝。捕获既有校验退化。
- 原有法国正式绑定与日本/香港/多来源身份回归保持。新测试仅使用冻结 fixture、隔离数据库，禁止真实网络。

小型修复方案核对：沿用 seed_evidence → seed_receipt → resolve_observation → attach_multisource_observation；不增加旁路写入。独立审核在测试与实现完成后进行。交付时绑定固定提交/镜像、无迁移、保留 2048 次/4 GiB 配置；生产单场目标仅 846，验证正式赛果与公开页，应用回退保留正确业务数据。

## 本地证据与范围

最小 RED：新增 FranceIdentitySeedTests 在旧实现中 3 测试、2 失败，分别为 seed=None 和 strong_identity_required。修复后 3/3 通过（含 11 个拒绝子例、完整正式赛果入库及重复绑定幂等）。SQLite 用于快速行为诊断，最终 PostgreSQL 与 Linux 无网络验证以固定提交 CI 为准。

共享身份文件默认触发 full，因此为本次精确字节增设一次性选测清单；新领域只列法国与所有现有 seed 消费者、身份/登记/PG并发回归，附 infrastructure/core。未放宽通用 shared/high-risk 规则。独立审核同时检查选测边界与控制文件。
