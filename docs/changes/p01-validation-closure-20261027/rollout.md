# 扩围验证记录

2026-10-27用户批准扩围；基线a8afb863。当前为定位和设计阶段，尚未修改运行代码、启用特殊profile或运行真实镜像准备。日志定位文件在本机runtime/p01-validation-closure/log-diagnostic；没有修改生产或联网抓取。

后续按固定SHA登记RED/GREEN、真实缓存/镜像/root合同、全量及正式核验、独立review和容器清理。所有旧失败保留；不通过修改旧收据或延期skip取得通过。交付人工门禁引用根AGENTS.md。

## 定向验证与审核状态（2026-10-27）

- 21d7f17b：原日志溢出批198项全部通过，PG完整日志23617字节，stop/postmaster均0；三组固定缓存3+3+2全部通过、0skip；真实镜像原native及20项辅助合同共21项通过，新建镜像已移除。
- 5d57af99：root原native及完整PG回执通过，uid/gid0，pidfile-check/stop/postmaster均0；普通collect-only只生成collection与生命周期文件，38项收集、无镜像动作。126项相关工具回归通过。
- 首轮独立审核C1–C7已修复并复审关闭；C8为实际Docker返回的小写精确缺失文案，加入唯一已观察变体，退出码/完整CID/空白stdout约束不变，并验证错误CID、权限、daemon及附加错误均拒绝。
- 上述是定向资格，不能替代最终同SHA全量。旧失败/partial输出保留；本轮最终全量与C8复审进行中。没有合并、部署或生产动作。
