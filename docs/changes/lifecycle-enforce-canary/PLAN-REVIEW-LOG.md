# 方案审核记录

## 第 1 轮：REVISE

独立 reviewer 提出 4 项 P1：DB 自证不构成 runtime 信任根；24h expiry 无法覆盖 event 187；
worker 在 post-verifier 前存在 queued scanner 窗口；promotion 缺宿主 shared lock 与 PostgreSQL
全局串行。方案已全部修订，并追加 runtime pause/visibility、rotation 边界与 OperationLog 权威说明。

## 第 2 轮：REVISE

上一轮 3 项关闭；activation 仍缺精确数据/CAS 合同，且 host manifest 没有进入 current/recreated web
的可执行接口。现已锁定 inactive/active + 共享 64 位 activation ID、每次 enable 先 disarm 后在完整
advisory-lock verifier 内原子激活，并采用 1 MiB 有界 `--manifest-stdin`。Beat 顺序统一为 active
verify 后启动并观察首个正常 tick，不增加手工 scanner 路径。

## 第 3 轮：APPROVED

上一轮 activation 与 stdin 两项 P1 均关闭，无新 P0/P1。实现需把 activation ID 固定为 32-byte
entropy 的 64 位 lowercase hex；false/off recovery 清空两份 env 的 canary SHA/IDs 并纳入 coherence；
recreated web 的 exec 需先过有界健康门禁。
