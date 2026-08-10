# 任务

- [x] (integration) 为 production census 增加确定性单地区补全批次编译器及 RED/GREEN 测试。
- [x] (application) 为 reviewed completion loader 增加 source-bound v2 batch contract 及反例测试。
- [x] (integration) 增加全局 batch plan 与严格顺序 execution ledger，机器拒绝漏跑、跳批和重复批次。
- [x] (integration) 增加独立 PR workflow，实际运行 Django adapter 合同而不破坏研究 workflow 的无生产面约束。
- [x] (application) 运行 P0 adapter、production apply 和 workflow 相关回归。
- [x] (operations) 更新当前状态、决策和部署运行手册，记录五地区范围与生产门禁。
- [x] (operations) 独立只读审查完成；提交、推送 Draft PR，并在 CI 后进入 G2。
- [x] (integration) 新增 participant completion 到 rolling release draft 的 SHA 绑定、语义去重与
  occurrence evidence 保全桥接。
- [x] (application) 增加重复内容冲突、ledger/completion 漂移、候选字节漂移与防覆盖测试，并用真实
  batch-0001 r2 验证 `50 occurrence = 32 unique + 16 blocked + 2 deduplicated`。
- [ ] (operations) 合并并以高风险开关全关闭部署桥接代码；生成生产 draft 后仍等待四模块人工审核，
  不执行 G3 或写库。
