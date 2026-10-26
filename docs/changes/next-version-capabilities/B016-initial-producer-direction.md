# B016 初始来源载体修订方向

2026-10-05 05:55，Asia/Shanghai。同一 `B016-FULL-FINITE-AFTER-ACTOR-CLOCK-001` 内的技术答复；人工确认只引用根 AGENTS.md。固定基础为 B `7b32011a` 和原 R `f7400f14` 的 actor clock 增量结论，完整 finite 材料仍未批准。依据 B015 schema §1、B016 W1/W3/C11 与 v6 `initial-producer-boundary.json`。

## 已确认的缺口

B015 exact Index 的 producer 必须为真实第一采集 Operation 的 OpRef/CapRef。W3 初始库存包含 root 12 次调用、N0 额外 6 次交换调用与 N0 cap clock 的 3 次调用。root 不属于 managed Role，有限 primitive 中没有完整 root–N0 bridge 操作；不能给这些初始原件随意填写 cap/case 首消费者。

现有 exact EvidenceIndex 继续标 MISSING。独立 material/source-association 表可以保存实际来源字段、SHA、库存位置与 first_consumer，但不得更名为完整 EvidenceIndex，也不采用 unqualified aggregate producer 作为成功例外。

## 原 B 的静态修订责任

在 B016 文档和独立 runtime 子目录形成一个有限初始化 producer 载体草案，与其余完整 finite 材料一同回原 R 审核：

- 冻结旧 B015/W1/W3 字节，明确新版本或分支。新增引用只作用于新包 Index 中确实 pre-Intent 原件的来源绑定；不扩大全局 Role、case/cap Operation、depends_on、HandleRef 或 Receipt 权限。
- 区分一次原始调用与 ClockCalls/Exchange/PairedClock/Domain 等派生件。派生件列全有限输入和唯一重算规则，不能以 aggregate 标签跳过底层原件。沿既有 21 槽精确一次归属，补列实际发现的其它 pre-Intent 原件闭合清单，不增加真实调用。
- 固定 exact 字段、tag、版本、数量/字节上限、有限索引、root_domain/Linux 域隔离、首采集与后消费关系、输出与来源双向覆盖。producer 记录与被索引原件不得经 Intent/cap/输出反指产生摘要循环。确实无法闭合的对象继续单列缺口，不默认授信首消费者。
- 给出固定正反例：伪 aggregate、借后消费、跨包/observer、缺少/重复/错误槽、未来/self/cycle、SHA/输出归属不符、初始与后续 actor clock 混用。全部新材料计入现有 64 帧、单原件 8192、总原件 1MiB、重试 8 及其余既定配额，不提额。
- 正常/故障链、FD 终态、Receipt 见证、source-state 与 instrumentation 继续独立补齐。148 操作/50 帧和 163 操作/55 帧仅为作者构造计数；故障加 8 重试为 63 帧，尚不是完整合法包验收。

该修订准备不解锁 parser、native、容器、网络或生产。source qualification 与外部 provider/clock/native 资格仍 MISSING，任何派生/hash 一致均不升级真实性。完整 fixed 材料经同原 R 审后，再确定实现条件；旧 exact Index 的缺口不会被草案覆盖。

协调者只维护本方向和台账；B 只写自有 B016 文档/runtime，保留旧保护文件及其他线程改动。若有限分支无法闭合，提交最小具体反例供协调者判断，并继续独立部分。
