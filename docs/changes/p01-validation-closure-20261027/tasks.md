# 实施任务

- [x] (operations) 测试定位：核对10个skip及现有资源，保存固定SHA日志超限诊断。
- [x] (integration) 测试：先补精确profile/缓存准入、root隔离、镜像证据反例。
- [x] (integration) 实现：复用固定缓存验证和真实镜像准备/只读证据。
- [x] (operations) 实现：仅指定root用例的隔离profile与真实PG监督；修正巨型SQL测试输入。
- [x] (operations) 验证：定向RED/GREEN、固定e16a0cb2全量7681项0skip、正式结果与owned生命周期核验、59个容器及临时镜像收尾。
- [x] (application) 验证：同一独立reviewer关闭C1–C9，候选APPROVED；回写实际结果，不合并/部署。

本线程主代理单独实施；独立reviewer只读，不覆盖其他线程工作。

最终证据与未执行的真实业务验收见[验收记录](validation.md)。
