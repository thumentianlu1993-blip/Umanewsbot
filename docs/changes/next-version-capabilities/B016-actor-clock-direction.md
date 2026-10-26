# B016 后续 actor clock 技术修订方向

2026-10-05，Asia/Shanghai。root 对 `c5dd2c5482ea3a6d40191b7719fc8b72104494f5` 的技术处置，任务 `B016-ACTOR-CLOCK-CONTRACT-PREPARE-001`。根 `AGENTS.md` 为唯一人工门禁来源。本次只准准备有限合同与静态素材，不批准 parser、native 或实际取证执行。

## 事实与范围

root 已核文档固定 Git/父提交与 1515 项索引文件的完整字节、长度和 SHA；反例 SHA `6892509a04a72c024e8347b0475c2e429b380bf2790d14d8e2540e40176dc7f6`。B015 要求每 actor bootstrap clock 与后续 cutoff/dispatch 采样；B016 W2 却把每次返回固定到初始 W3 的 N0 slots 9/10/11。后出生 G_H 的调用无法复用这些来源、调用者与时段。本结论是规范矛盾，不是行为 RED，也不验证完整 cap/case。

只修复已要求的实际采样无法表达这一问题。保留已有 clock primitive、Request 和 Obs 的业务含义、角色集合、操作与重试数量限制；不借此增加采样范围、来源资格或真实权限。

## 选定方向与 B 的交付

1. **初始配对与后续采样分开。** W3 的 PairedClock、ClockCalls 21 项、root/N0 observer、challenge、外部资格和原公式保持。初始 cap clock 仍按 slots 9/10/11 核对。所有 case 使用同一固定 root bracket、Input anchor、step_origin、root 120 秒和阶段截止；后续 clock 不修改、不续期这些值。
2. **新增同一 clock kind 的有限原件分支。** B 起草独立版本 tag（建议 `B016-clock-sample-v1`）与封闭字段表，完整保存实际 collector、reader/object、DomainRef、对初始配对的引用，以及 MONOTONIC/REALTIME/MONOTONIC 三项真实返回及各自采样区间。三个条目只能有序连续前缀，明确成功、错误、未返回与 partial 的 exact union；只保留实际已有值。原件不得反指消费它的 CallRaw、Operation 或成功 Obs，避免自环。
3. **输出判别明确。** 为后续采样与初始配对确定互斥的 typed output/tag 和索引范围，不能按缺字段猜分支，不能把新采样硬塞旧 9/10/11 槽。三个 CallRaw 的 request、primitive/step、reader/object、provider、物理时域、rc/errno、Timespec 值与真实 Step 区间逐项核对。后续 sample 的三项本身必须先存在，再由 CallRaw/Step/Obs 消费；禁止 Obs 反填原件。
4. **身份与时间因果不靠标签。** 后出生 actor 必须有已核出生和身份因果；不同 actor 的单调时间可比较性按已审物理 time namespace/boot 等规则证明，不能只因为数字相近或复用 DomainRef 放行。MONOTONIC 返回必须落在其实际调用区间，各 actor 的已知采样保持单调，所有实际采样仍在同一资格窗口与原截止内。
5. **wall 语义明确。** 后续 REALTIME 是该调用的原始返回，不用于重新计算 Input anchor/deadline。W3 已批准的 root wall/LINUX MONOTONIC 外部资格不能自动扩张为每 actor REALTIME 全窗无阶跃证明；如果后续判定需要额外 wall 一致性，必须写出已存在的资格前提及可核公式，否则保持 unknown/缺件，不暗加物理保证。新原件与条件数学不能认证 provider/source/native。
6. **完整静态正反例。** 至少给出初始 cap、后出生 G、叶、较晚 N0 final、故障 dispatch 的准确采样绑定示例；保留旧冲突反例，并覆盖错 actor/domain/provider、错时段/索引/顺序、未来/循环引用、错误/未返回/partial、旧 pair 冒充新调用、后续采样企图续窗。不同 schema 版本、null 字段、caller 伪造 ok 均 fail closed。本阶段这些是静态材料核验，不计仓库 43 方法或行为 RED。
7. **实字节计量。** 新分支单件 ≤8192 bytes，明确累计占用同一 1MiB；Operation/wire、cap/case 帧、2048 op、展开与访问预算、每帧首 slice≤3 op、最多8重试均保持。更新 H/N01 六项必需 clock 与故障 dispatch 的实际操作/帧/原件计数，不从旧符号数推算、不压缩分母。不能容纳则交实际超限证据，不自行提高限额。

B 只修改自己 B016 文档、必要的自有静态素材/索引，保留 c5dd/v1–v4 原件和旧 module/tests/六基线；新目录保存版本，不覆盖旧反例。先提交可独立审查的增量合同、完整字段/依赖图、实际正反例及逐项预算。root 验收材料后交同原 R 定向复审；通过再继续完整 finite 素材，完整素材另审后才新 parser。无业务/helper 导入、仓库测试、拟议 native 调用、容器/VM/DB/网络/资源窗口。

## 状态边界

cap 55 帧/58 op、H/N01 非 clock 137 op/46 帧与 partial 分支仍只是局部素材。FD 全终态、Receipt 每见证、状态/来源矩阵及完整 case 尚未整体验收。初始 provider/source 和 native 资格仍 MISSING，F02 真实样本仍未因此增加。
