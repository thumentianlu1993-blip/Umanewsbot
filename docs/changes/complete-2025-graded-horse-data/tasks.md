# 2025 分级赛参赛马补全与生产导入任务

## 0. 基线与 RED

- [x] (integration) 固化 run `31269803408` 七文件 SHA、partial 计数和地区/profile/name gap
- [x] (operations) 只读核对生产 2025 赛事/赛果与 HorseProfile 完整度，不写数据库
- [x] (integration) 为拉丁赛果行英文名证据取得真实 RED
- [x] (integration) 修复英文名证据并升级 policy version，聚焦完整测试 `102/102`
- [x] (integration) 实现可复现 gap census 命令和固定摘要测试

## 1. 官方赛事覆盖

- [x] (integration) 为 AU/DE/UAE/SA/QAT/BHR 建立 provider policy、URL/request budget 离线合同；redirect/request ledger 接线待 workflow 阶段完成
- [x] (integration) 写入六类 result fixture 与严格 parser 回归；catalog fixture 随 catalog adapter 补入
- [x] (integration) 实现 TJCIS AU/DE/Middle East catalog parser/adapter、官方 result parser 与
  manifest-bound checkpoint runner；受审赛事 URL manifest 的自动发现/接线仍属 workflow 任务
- [ ] (operations) 扩展 workflow checkpoint DAG、artifact identity 和 safe-stop 合同

## 2. 生产身份与地区

- [x] (application) 新增 RacingRegion choices、migration 0072 和新地区回归
- [x] (application) 扩展只读 production participant candidate census 为八地区、单年和实际起跑范围
- [x] (integration) 复用 source refs/provider ID，输出 bind_existing/create_new/ambiguous/blocked mapping
- [x] (application) 验证唯一已有 provider identity 优先绑定、弱名称 blocked 和重复身份 ambiguous

## 3. 完整资料补全

- [ ] (integration) 扩展 P0 adapter config 至 AU/DE/Middle East，并冻结逐 provider authority
- [ ] (integration) 实现新增来源 cache/parser/identity/budget/checkpoint
- [ ] (application) 验证基础资料、二代血统、完整生涯及主胜鞍重算门禁
- [ ] (integration) 生成全部 2025 候选的 reviewed completion artifact

## 4. 生产导入桥

- [ ] (application) 扩展 reviewed P0 prepare/dry-run/apply/receipt/verifier 至年度 scope
- [ ] (application) 完成 SQLite 与真实 PostgreSQL 原子性、幂等和 rollback 测试
- [ ] (operations) 生成生产只读 dry-run、blocker=0 与精确发布/回滚包

## 5. 审核、发布与运行

- [ ] (integration) 运行受影响完整测试、workflow contract、Django/migration/diff 检查
- [ ] (application) 独立 reviewer 审核完整 diff 并关闭 findings
- [ ] (operations) G2 后 commit/push/PR 合并和部署候选
- [ ] (operations) 精确 G3 后执行外部全量 2025 采集并审核 artifact
- [ ] (operations) 精确 G3 后执行写前备份、maintenance、apply、verifier 和线上抽检
