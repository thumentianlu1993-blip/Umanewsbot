# B006 合成转存与原 R 独立接收

2026-10-03，Asia/Shanghai。正常转存 T01 已完成实际宿主持久化、独立接收与来源绑定；仅覆盖合成 metadata。真实 F02 样本与保留集仍为 0，D01/D02 尚待，不代表五场景全部通过、黄金集完成或 M01 解锁。

## 实际转存

固定 v9 计划 `24629091a99ca116b9b517f7e66bf496b9ab13ba17ddc1cd453a10a519640e65`、本地合成镜像 `1a43ef3fb48ac13c9e247dc1f8f17d0f12cb52a6a0df2513b2e54c68e6f735ae`。源与工具在普通只读层，仅控制状态使用 1 MiB tmpfs；UID 10001、目录 0700、文件 0600 与输入哈希已核。实际三次 probe exec、一次 cp，宿主九文件验证、fsync/rename 及 `host_verified` 成功。总耗时 0.926 秒，自有容器删除、attach 回收；未启动 PG。

原始执行收据 `/Users/mentianlu/.codex/runtime/b006-transfer-v9/receipt.json`，SHA256 `2b903eda1f33a15d1e38589f70852a2a78465fb2292dcf4aef8710b6049d68d2`。历史失败与原始收据保持不变。

## 独立接收及真实来源

原 R 实际读取九文件、manifest、capsule、source commitment、transfer.complete，并运行原只读 verifier；报告提交 `31c8490e`，APPROVED。接收时间 `2026-10-03T23:18:56+08:00`。R 未调用 Docker/PG/网络，未写签收控制状态。

协调者通过 `read_thread` 取得原始完整 final JSON，交原 `f02_receipt_bridge.deliver` 的受信 reader；来源取自实际 API 返回值，并非包内 issuer 或 producer 文件：

| 绑定 | 实际值 |
|---|---|
| R thread | `01a0fdc6-2d8d-7d10-9662-a7b042e56ef0` |
| R turn | `01a10250-a391-7c60-a7c5-994ef2281502` |
| R final message | `msg_076bb14b186bd293016ac11d054dfc87d0bdbc5718414acaa3` |
| canonical payload SHA256 | `5195fe9cd04ee17d599026c1aa3bb04c9348fdda6dff76f5db338773cb1ad842` |
| capsule SHA256 | `671b292382ce643a0157b6c388422e93c72ed3d35e2321d712f25eb923b441f0` |
| manifest SHA256 | `584b2f36f009959d786592826320270adaa9764591e0769999f242d370cce290` |
| observation | `B006-synthetic-metadata` |

原 bridge 成功生成 `R.source.json` 与 `R.received`，后者状态 `delivered_to_R=true`。两文件权限 0600；SHA256 分别为 `d29a159b8b141a281cc442508540742300c0d8b7c1db4cb0be586853e49d340b`、`3992e1dc7e83f95f02c245da56869ea6b45de5bbd4da9995e7bfc34db4289306`。短时签名材料仅在原 bridge 内存中生成，不持久化密钥。

实际 API 记录与 bridge 结果保存在私有目录 `/Users/mentianlu/.codex/runtime/root-b006-trusted-receipt/`。原始 `receipt.json`、`transfer.complete` 及只读 `inspect_host` 的 `delivered_to_R=false` 表示转存当时的状态；后续独立接收以新增 `R.received` 为证，不改写历史。签收后再次宿主完整性校验通过。

## 后续

B007 已派最小 D01/D02 合成负例准备，先固定只读坏源方案及哈希，再技术审核和安排本机窗口。真实生产 metadata/content 尚无本轮执行包或采样证据。人工确认唯一依据为根 [AGENTS.md](../../../AGENTS.md)。
