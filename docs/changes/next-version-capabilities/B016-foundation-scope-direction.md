# B016 基础采集域与有界来源登记修订方向

2026-10-05，Asia/Shanghai。接续 `B016-FINITE-V7-INITIAL-CLOSURE-001`，固定 B `3ac9499e1846f7f7bf185de1aa5355dd530c07ce`，parent `f0b0f51c7cd01efa1fa1e6bc32c88b566b12e5c8`。这是原任务内离线来源载体的技术定向，人工确认仅按根 [AGENTS.md](../../../AGENTS.md)。不改变真实来源、权限、生产或执行资源范围。

## 已核事实与选择

协调者核对 C16、原三份 Domain/Namespace/boot 字节及最小反例，并逐 length/SHA 核过 v7 的 11177 工件。当前 clock Scope 先依赖 DomainSet，不能再让其底层 acquisition 依赖同一个 Scope；否则来源图闭环。现有 25 个 clock record 槽已满，8004 字节表也不能隐藏附加记录。四 cap 和四 clock 子图的局部通过不代表完整 Index/Receipt。

采用 **基础采集 scope → 底层原始调用 → Namespace/Domain/Identity 等有限派生 → 原 clock scope → 原 21 slots 与配对 → Intent/cap/Input/case → Index/Receipt** 的顺序。基础层不引用从自己结果产生的 Domain、Identity、Intent、cap、Index、Receipt 或 runtime/hash 报告。保留旧 v1–v7、B015、W1/W3 和已审 actor-clock 字节；新 v8 草案独立版本，不在旧 exact union 内偷偷补字段或提高边界。

## 基础 scope 的固定边界

新基础对象使用 `tag=B016-foundation-scope-v1, version=1`；exact 字段为 `tag,version,op,challenge,case,controller,code_sha,image_sha,bundle_sha,target,collector_sources`。其中 op/challenge/case/controller 和三个预先固定的代码/镜像/包摘要沿该次原预备输入，不含后续产物摘要。

`target` exact 为 `{role:"N0",selector:"initial_self"}`。这是有限初始取样选择器，不是已验证 Identity，不接收任意 PID、路径、回调或用户可选角色。实际 PID/start/uid/argv/exe 等值须来自各独立原始输入，派生后再核同一观察对象，不能先用 Identity DTO 宣布真实性。

`collector_sources` exact 含 `root` 与 `N0` 两项，每项 exact 为 `code_sha,provider_sha,clock_source_id`，保持原 root/N0 固定来源标识和彼此隔离。它们只绑定采集代码与时源选择，不自证 provider 资格。基础 scope 不含 DomainRef；后续 clock scope 的 `linux_domain_ref` 只能指基础层已完整推导的 DomainSet。两个 scope 通过同 op/challenge/case/代码输入与明确的基础 scope 摘要关联，不靠某些字段相同就隐式合并。

基础 acquisition 的 timing 仅沿原初始 Namespace timing 的同 observer 来源表达，必须列实际原始 clock 调用或明确尚缺的来源；不借新 scope 凭空产生可比较时间，不把 root 与 N0 单调时钟混用。完整域与配对形成后仍按原窗口、资格和因果检查，不能反向更改基础原件。

## 新登记版本与数量上限

新包草案明确使用 `schema=B016-native-evidence-index-v3, version=3`；v2 的 clock-only 草案仍保留为条件性子图。v3 的来源登记仅用于确实 pre-Intent 原件的 producer 关联，不扩展全局 Role、Operation/depends_on、HandleRef、case/cap 引用或 Receipt 权限。

选择有限分块登记，以下是新草案上限，不是已存在执行资格：

- 一个 case 最多 **128 条初始化 record，含原 clock 的 25 条**；基础层最多 103 条。记录 strict integer 连续索引，无 bool、空洞、重复、未来或自引用；原 clock 的 21 槽序号和实际一次采集归属另外严格保持，不能因全局索引偏移重算调用次数。
- 每 record canonical bytes 不超过 2048；登记分块最多 **16 块、每块不超过 8192 bytes**，全部块及其外壳总计不超过 **131072 bytes**；顺序、总数、摘要、无重复覆盖必须显式核。不得用压缩、外部文件或多次执行规避这些上限。
- 两个 scope、所有新增原始输入、记录和块都扣同一 **1MiB provided/consumed 总预算**；没有额外赠送的 128KiB。每单原件 8192、64 帧、2048 op、每 slice 3 op、重试 8、展开 16384、depth 64、nodes 1024、work 16777216 及原时间界保持。先核 wire 和全包累计预算，再有界展开；分块不能增加无限拼接内存。
- B 负责在这些上限内给出 exact 顶层/分块/record union/引用语法和原始调用库存，按四 case 的实际规范字节重算。采用顶层逐块有界验证，不要求把所有记录展开进一个受 nodes 1024 限制的单视图；每视图和累计 work 均需明确计数。完整 source/FD/Receipt 包超过任一既定全局上限时回报具体最大对象、实际差额与最小反例，不能丢证据或继续提高上限。

这允许 B 直接完成本技术方向的精确草案，无需为每个字段布局再停一次；实现 parser 或执行真实采集仍未解锁。草案与完整有限材料必须交原 R 审核。

## 原始来源与失败语义

每条基础 acquisition 只能表示一种固定 primitive 的一次真实语义调用及其返回，或显式 finite transport 收到的一份外部原始字节；没有任意 `aggregate`、自由 field map 或 callback。每份派生件列完整有限输入、唯一 recipe、输出 kind/bytes/SHA；producer/原件与所有消费者双向覆盖，不能以 first_consumer 代首采集。同 SHA 原件不得声明不同 kind/producer。

Namespace、boot、proc 必须拆到底层固定采集及其完整成功/失败前缀。Identity 的 stat/status/argv/exe 及前后观察必须各有独立原始来源；新 synthetic 正控应从明确的底层 synthetic 输入向前生成，而不是把旧 Identity 拆字段伪称原始采集。新输入若改变输出，应在新包沿依赖重绑并清楚记录，不覆盖旧材料。

Lease 的 start/liveness 双报告及外部 qualification 由显式有界接收原件进入来源图；接收者、有限消息类型、实际字节/时间/关联必须核验。报告内容只读到一组字段不等于已验证提供者或已授予运行许可；资格仍 MISSING，锁归属不能从 PID 存活推断。无法提供底层原始来源时保留 exact 缺件，不封装一份现成报表冒原子 syscall。

所有 error/EINTR/pending/unknown 保留真实已完成前缀、FD 创建和 close 不确定性；条件性数学重算和来源认证分开。基础层正常路径闭合后，继续补失败状态、复合 instrumentation 调用库存、Receipt 完整 wire 和独立传输时间；不以本基础层通过替代全包验收。

## 本批产物与验收

B 只修改自有 B016 文档与新 v8 runtime，保护两未跟踪 module/tests 和已有八保护文件。交付确切版本与字段、固定四上下文、规范 provided=consumed 字节预算、来源/摘要两类无环图，以及跨 scope/observer、future/self/cycle、重复 producer、漏原始前缀、分块重排/遗漏/重复/超界等反例；保留原 clock 13 负例及所有原分母。

本批只用 JSON/AST/hash/有限普通文件静态检查；不导入候选或 helper、不跑仓库 43 tests、native/OS probe、容器/VM、网络或生产，不占 C 的执行资源。达到原单批最多 3 个百分点额度界或具体无法闭合的最小合同阻塞时，固定真实 checkpoint 回主协调；不扩大任务或伪报完成。最终 full Index/Receipt、parser 与资格分别记录，当前均未通过。
