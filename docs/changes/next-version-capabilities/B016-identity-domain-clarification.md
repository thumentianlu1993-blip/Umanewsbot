# B016 身份域比较：已回传的待审技术方向

2026-10-05，Asia/Shanghai。关联原任务 `B016-CAP-CONTEXT-CLARIFICATION-001`，初始规范草稿 `3def650263fc4eb59b761780540331db9e5641a8`，最新部分断点 `57fb5a318fbce7d1ddb2edc72a6c55f04a736241`。本文是 root 针对 B 所报歧义的最小规范增量方向，**已于02:23成功发送给 B 并取得继续工作的确认，尚未获原 R 审核，不是 parser 新语义的实施批准**。此前工具权限阻塞已解除；已有两份未提交代码与原规范保留。

## 定位与方向

固定 B015 DomainSet 同时包含物理域字段与每次观察的 `reader`、`target`、`sample_ref`。后一组值随采样变化，不能把整个 DomainSet DTO 的字节相等当作不同观察属于同一物理域的唯一标准。root 核对了 B015 schema、原语卡及 B 当前 `_derive_identity`：单次观察的原件推导核验和跨观察身份比较必须分别保留。

建议 B 只将以下规则补入现有待审增量，与完整 canonical 素材一起交原 R，先不修改受此规则影响的 parser：

1. **单次观察仍严格核完整 DTO。** DomainSet 必须逐字段等于该次已验证 namespace/boot/proc 原件的推导结果；`reader`、`target`、`sample_ref`、类型、原件摘要、来源、采样及因果关系全部校验，不能以物理字段相同代替来源证明。
2. **跨观察物理域比较只抽取精确不变量。** pid/net/time 各自的 `(device, inode)`、boot 的 `id_sha`、proc 的 `(device, inode, mount_id, fs_type)` 必须全部相等。输入先通过原 exact schema 与原件绑定，不能对任意字典直接投影后授信。
3. **每次观察的定位字段独立约束。** reader 必须是该操作真实获准的采集者，target 必须是被核对的同一登记对象；每个 ref 必须指向本包中合法的对应原件。不同 reader 只在既有拓扑与句柄转交规则允许时成立，不能通过忽略 reader/target 接受跨对象或跨权限观察。
4. **身份及生命周期其余规则不变。** PID、start_ticks、UID/GID、exe/argv 摘要继续严格核；parent/state 的变化只走既有领养/退出分支，original snapshot 不改写。物理 PID namespace 不同即不按同一数字 PID 接受，不新增跨 namespace 映射。
5. **不改摘要或其它相等关系。** DomainRef/DomainSet 摘要继续覆盖原完整对象；不得将其改成物理 tuple 摘要，不把不同观察折叠为同一原件，也不全局替换所有 DomainSet 相等校验。同一观察、Input/holder 的原有自洽关系仍按各自合同核验。时钟域、样本新鲜度与因果排序另行保留，不能靠新 tuple 比较豁免。

待审真值表至少包括：同物理域且各自原件/reader/target 合法的新观察；逐个物理字段改变；错 reader、错 target、错/缺原件；同 PID 但 start_ticks 或物理 namespace 变化；合法领养仅 parent 按规则变化；原 original snapshot 被覆写。正向素材须完整，负例不得借其它先行错误假称覆盖了目标规则。

该方向不新增采集、网络、权限或 native 资格，也不改变 B014 旧 fake schema；不能据此解除目前仍缺的真实来源与整包闭合条件。

## 路由测试补证

B 报告公开验证入口已接 raw/lifecycle。root 检查发现作者 RED/GREEN 测试快照之间将 event key 从字符串改为合法整数 `seq=1`，原两阶段整测试文件摘要不同。root 未覆盖作者证据，在独立临时快照中把同一份已修正 GREEN 测试分别放到原 RED/GREEN 模块上复验：一个方法的两个路由子例实际断言 RED，修复模块同方法 GREEN。

这是有限 pure doubles 下的入口路由验证，不是完整 Evidence、raw/receipt 各分支正向或 OS 真实性证明。作者最终 43 方法仍只计组件矩阵。

- 相同测试 SHA：`e738516f68811ec393b1956e122f9db10c20313f889c74019e8144c703bffa34`。
- RED 模块 SHA：`b1bddee6cc39c3017eaf8a92b462a61877a5a2863b3c4095a7a0dd1e4e753b5f`。
- GREEN 模块 SHA：`204c0782e16ccd3a9118d238ff1cabefcc37d9c2644a67efe2105c6c1c7bd393`。
- root 独立补证：`/private/tmp/umanews-root-b016-routing-evidence-v1/verification.json`，SHA `abd24ef9ba96d1cad95ddd745682bdc8521059524fc5745aa9cb575054625b86`。

权限恢复后已核原 B 空闲，通过 `B016-IDENTITY-DOMAIN-DIRECTION-001` 一次性回传本方向与补证；工具成功与 B 的 active 确认均已收取。仍不能将送达当作原 R 已批准。
