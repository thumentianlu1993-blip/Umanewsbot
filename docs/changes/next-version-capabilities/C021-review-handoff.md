# C021 首次 GREEN 候选审核交接

记录时间：2026-10-05，北京时间。此材料已于02:23权限恢复后**成功发送给原 R，明确排在 A021 之后仅做静态审核**；尚未取得独立审核结论、分配运行窗口或执行 GREEN。此前 `send_message_to_thread` 的权限阻塞已解除，继续原审核会话，没有创建替代审核会话。

## 固定候选与责任

- 原审核会话：`01a0fdc6-2d8d-7d10-9662-a7b042e56ef0`，模型 `gpt-6.1-sol` / `medium`。
- 派单 ID：`R-C021-FIRST-GREEN-PACK-REVIEW-001`。实际工具成功及原 R 确认顺序已记录在协调台账；本文件不代替执行结果。
- C 工作树：`/Users/mentianlu/.codex/worktrees/bc9b/umanews`。
- 最终代码和派生夹具提交：`3732fd2fa5ef7f15f75649407bd13d840404de2d`；基础源码归档提交：`bb8f400c9f9f62529291aec8e19af56e56696155`。
- 私有执行包：`/Users/mentianlu/.codex/runtime/c021-o03-template-adapter-green-001`。
- 审核责任：原 R 只读检查代码、固定样例、执行脚本与资源边界，在自己的审核工作树记录结论；不得修改其他工作树或执行本包。返修继续原 C / R 上下文。

## 已完成的协调核验

root 独立核对归档和 Git 原件：1,906 个实际快照文件、114 个固定来源、14 个 overlay、122 个 descriptor 来源均与记录一致；原 v1 六件逐字节保持 `0ebb7d7a0a5be4d0f88088cba708ea63d8dde09d`。新七件与最终提交一致。此项只证明载体与来源，不替代代码正确性审核。

root 从旧 golden 独立重建身份映射和完整新 golden，没有调用作者派生脚本、导入候选、渲染模板或调用 adapter。130 项身份映射无冲突且与 derivation 一致；24 组 tuple、108 个行 token、24 组非空 body/anchor 摘要全部吻合；25 组可见 `template_context` 逐项完全不变。新 golden 整体深比较相等；origin、permission、F01、display mapping、lineage 与原范围均保持。75 个负向/元规格只有 N09 主原因由 `duplicate_field` 改为 `missing_field`，其余字段、分母和优先级不变。

N09 的独立定案为 R `403c3b657d5f0be9050a33140cc1ee6e78c1e79c`，报告 SHA256 `193e466d3496755f219a2ae517dbab2bb53f783aa1ba566407d5c94ef6fde0d8`；不要把这次允许的单原因派生改动扩展为新增重复字段覆盖。

| 固定对象 | SHA256 |
| --- | --- |
| manifest.json | `e1a8a6f886e71558b65fce83865f802dd15cff8c5abacfcf320dd051349837c6` |
| source-hashes.json | `c283280a72c7b055a7e82aed9d6b15dc47324ae4e3a9276c245cc95389247117` |
| candidate canonical descriptor | `d76f1f7b9b89cf6857fe99ede2528ced9f452cee56a84f34f8099da2f403b49f` |
| worker.py | `b793a96454031933f150cbbf20b0a573cf2f79736198520cc7a6ddd18284d0e7` |
| run_round.py | `6accbd8e58bccf868eaa6ed40072352a7a730612693adb1998643f58ea4c74a4` |
| root source-verification.json | `2c09d059755be99995132a509568be187d1a4a5d67094354e2700cc88397303a` |
| root derived-verification.json | `836e088b2b13dafa98e5e990d8ad59220bc4d8fc5a50cf7b9454c8f7478128cf` |

root 两份核验结果与独立派生脚本位于 `/private/tmp/umanews-root-c021-green-pack-verification-3732/`。实际运行收据仍不存在。

## 待原 R 审核的重点

1. 真实固定模板的有限解释器：嵌套循环、parentloop 与条件、过滤器及 HTML 转义语义是否正确；全量页面可见内容与固定 envelope 是否绑定。只支持既定有限语法，未知结构必须拒绝。
2. 两模板合计 14 个 `escapejs` 位置：七键 Marker 使用精确解码对象做身份比较，不能以 script 原始字节替代 canonical 对象哈希。确认攻击字符串、重复键、额外脚本、隐藏/额外可见内容不会产生成功回执。
3. source、candidate、origin、permission、F01、tuple、行 token 和 expected body 的依赖顺序；全 scope 原件装配，不能根据实际 Marker 选择输入。现有实现只处理单 required target，多目标必须 fail closed；`complete_original_scope=false`，不能宣称完整公开覆盖。
4. 72 个行为负例和 3 个元测试必须真实修改对应输入/观察输出，保留原 54 个案例与 4 个 R 反例。N09 修改所有四行的 td[4]；expected feedback 与 invented-fields 元测试不得只验证自造 helper。资源元测试应逐项验证相等与减一边界；Marker 最小值减一得到 0 时按既定 `invalid_limits` 处理。
5. 新实现显式区分输入 JSON 上限与原 HTML 上限。HTML 七项预算不变。输入合同声明 schema 131,072 bytes / 12,000 nodes、envelope 524,288 bytes / 24,000 nodes、evidence 262,144 bytes / 12,000 nodes，深度 64；解释器 30,000 步、循环深度 3、数组长度 512。须独立判断这些边界及超限行为，root 的大小核对不等于批准增加预算。
6. worker 相对原首 RED v2 仅增加测试结束后的计数读取与三个计数字段；runner 字节相同。仍需审核实际命令、依赖、禁止网络和 SQL 的 guard、固定源码装配、结果落盘与失败清理。

静态测量（节点包含对象键和值）：contract 106,134 bytes / 5,255 nodes / 深度14；envelope 388,002 bytes / 14,070 nodes / 深度5；evidence-contract 18,690 bytes / 891 nodes / 深度14。三者均落在新声明上限内，尚未进行运行时预算验收。

## 待审核的执行范围

计划 105 个唯一 unittest 方法：原 94 加新增 11；25 个正向/缺失输入、72 个行为负向、3 个元规格按子例单列，不能计入唯一方法数。当前实际 GREEN 为未执行，不得从静态计数推断通过。

只有原 R 批准固定包后，root 才实时检查资源并分配新窗口。原初始 RED 窗口已经使用并释放，不可复用。限定专用 socket `unix:///Users/mentianlu/.colima/umanews-impact-ci/docker.sock`，固定镜像 `sha256:ab8494e6202dced04a6c2b5b885b3d1f2d9c80776ec8ae8d97f3552aae6b3ecc`，`--pull=never`、2 CPU、2 GiB、256 pids、UID/GID `10001:10001`、network none；总时限900秒含20秒清理。Django dummy DB，不启动 PostgreSQL、Redis、Celery 或 HTTP，不读取生产凭据，不挂 Docker socket，不访问默认 Docker context。完整命令与挂载以固定 run_round.py / manifest 为准。

允许完成本地固定包的技术审核；合并、生产、公开启用和高影响动作仍只按根 `AGENTS.md` 处理。本包不包含这些动作。
