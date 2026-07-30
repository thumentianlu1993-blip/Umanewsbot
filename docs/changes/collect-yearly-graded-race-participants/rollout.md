# 单年度分级赛全部参赛马研究 Rollout

## 当前检查点

- 原主工作区 `/Users/mentianlu/Code/umanews` 在任务开始时包含大量其他会话改动，本任务不触碰。
- 独立 worktree：
  `/Users/mentianlu/.codex/worktrees/graded-race-participants/umanews`。
- 分支：`codex/generalize-graded-race-participants`。
- 基线：`origin/main@6d073dc07cb29201bbc922255923820c872a0467`。
- 旧研究来源：`origin/research/2026-graded-top5-wikipedia@61d4c526`；实际可复用代码版本
  `c7cb5d7d`。
- 旧研究相对新主线 ahead 12 / behind 49，禁止整分支 merge。
- 已按获准方案完成 collector、测试、workflow、README 和 region manifest 说明的离线候选；
  当前全部为未提交改动。未运行 GitHub Actions 或联网 collector，未 commit、push、创建 PR、
  部署或触碰生产。

## 并行与重叠

- PR #24 和旧 research branch 作为冻结 evidence 保留，不原地改写。
- 新任务只在 main-derived worktree 新增通用 collector/workflow；旧文件不在 main，因而没有
  运行入口冲突。
- 主线已有 `.codex/scripts/check_workflow_contract.py` 和测试，实施时只做必要兼容，禁止覆盖
  当前 workflow 治理。
- 如实现前 `origin/main` 前进，先 fetch、记录新 OID、检查目标文件重叠；重叠影响设计时回到
  同一方案 reviewer 复审。

## 阶段门禁

1. [x] 五份方案文档齐全。
2. [x] 独立方案 reviewer `APPROVED`。
3. [x] 用户针对已审方案明确确认实现。
4. [x] 新测试取得真实 RED。
5. [x] 实现 subagent 在限定文件内完成 GREEN；未 commit/push/联网。
6. [x] 第一至第二十轮 findings 修复后的 collector `32/32`、`39/39`、`46/46`、`49/49`、
   `53/53`、`56/56`、`60/60`、`64/64`、`66/66`、`69/69`、`70/70`、`71/71`、`73/73`、
   `75/75`、`76/76`、`77/77`、`79/79`、`81/81`、`82/82` 为历史轮次；当前完整离线复验为
   collector `83/83`、
   workflow 静态合同 `11/11`、现有 workflow
   contract `26/26`；synthetic 首次 exit `75`、同目录续跑 exit `0`，逐字节等价并生成
   精确 7 文件。
7. [ ] 独立代码 reviewer 首轮为 `REVISE（7 P1 + 4 P2）`，第二轮为
   `REVISE（2 P1 + 3 P2）`，第三轮为 `REVISE（4 P1 + 2 P2）`，第四轮为
   `REVISE（3 P1）`，第五轮为 `REVISE（1 P1 + 3 P2）`，第六轮为
   `REVISE（1 P1 + 1 P2）`，第七轮为 `REVISE（2 P1 + 2 P2）`，第八轮为
   `REVISE（2 P1）`，第九轮为 `REVISE（P0=0 / P1=0 / P2=1）`，第十轮为
   `REVISE（2 P1 + 1 P2）`，第十一轮为 `REVISE（P1=1）`，第十二轮为
   `REVISE（P1=1）`，第十三轮为 `REVISE（1 P1 + 1 P2）`，第十四轮为
   `REVISE（1 P1 + 1 P2）`，第十五轮为 `REVISE（P1=1）`，第十六轮为
   `REVISE（P1=1）`，第十七轮为 `REVISE（2 P1）`，第十八轮为
   `REVISE（P1=1）`。第十八轮修复后，同一 reviewer 第十九轮曾
   `APPROVED（P0/P1/P2=0/0/0）`；session
   `019fb2f6-da26-7463-81b3-0b3c52ed4cf0`，审阅时 content manifest
   `cfb5630c1dc29a0d04b62816a4ce2f296640308e838614d96d57af2d6fbce0a1`，pre/review/post
   均 exit `0` 且只读。该结论仅为历史快照。第二十轮与第二十一轮最终确认均为
   `REVISE（P2=1）`；最新修复显式区分 country fact 的 missing/controlled/uncontrolled，
   非空未知 country 不按 region 回填并 fail closed；标准五地区仅 missing 可按明确 region
   通过，AU/DE/Middle East 不放宽。修复已纳入 `83/83`，待第二十二轮确认至 actionable
   finding 清零。
8. [ ] 复用同一 reviewer 会话执行第二十二轮最终只读确认并冻结新 fingerprint。第十九轮审阅时
   fingerprint `89a8021db567eaaed7003680cd85377ca04ec7ee08d48168ef3212cbcb51d262`
   不得称为最终发布指纹。
9. [ ] 第二十二轮确认后，等待用户针对新 fingerprint 授权 commit/push/创建或更新 PR。
10. [ ] 正式 `full_network=true` 单年度 run 需要单独明确授权；每个年份均是独立 run/manifest，
    不得从代码审查或 Git 发布授权推导。

## 首次实施迁移

- 不 cherry-pick 旧研究的文档/status 提交。
- 只把 `c7cb5d7d` 的通用基础层迁入新命名文件，再用新增 RED 驱动范围改造。
- 新 run schema/tool identity 与旧 PR #24 不兼容。旧 2026 artifacts 只作为历史 evidence，
  不允许新 collector resume。
- 新 collector 首次正式 run 必须 fresh start；之后只在相同 year、collector SHA、base commit、
  region manifest SHA 和完整 tool identity 的 runs 间精确恢复。

## 失败边界

- 新地区公共页没有明确标签且无 reviewed region manifest：跳过并报告，不猜地区；未覆盖全部
  other URL 时 `classification_incomplete`。
- 某地区零纳入赛事：只有年度分类完整才能写 `no_public_in_scope_races`，否则报告
  `classification_incomplete`，不把 workflow success 写成该地区数据成功。
- 强制英文地区缺英文：保留参赛事实和 horse row，进入 review queue，不伪造英文名。
- 未知结果状态：保留原始证据并进入复核，不计入参赛行。
- 泛化 `other` profile 的唯一同名搜索结果：缺原名+出生年/country 证据时 unresolved，不跨国合并。
- 某 race 只有 non-starter 或结果结构无法证明实际参赛：该 race error，不产出空成功。
- 任一 stage safe-stop：退出 75、上传 checkpoint、阻断下游。
- manifest/index/input/tool/year/region SHA 漂移：确定性停止，不自动 fresh fallback。

## 回滚

- 方案阶段：删除本 change 文档即可；不影响运行时。
- 实现未发布：删除新 collector、tests、workflow、README/manifest docs，旧主线行为不变。
- 发布后但未正式联网：撤销研究分支/PR 即可，无生产状态。
- 正式研究 run 后：artifact 保留 evidence；代码回滚不删除历史 artifact，新版本不读取不兼容
  checkpoint。

## 状态回写

方案审核通过并完成离线实现后已更新：

- `docs/current_state.md`
- `docs/project_status.md`
- `docs/changes/collect-yearly-graded-race-participants/tasks.md`
- `docs/changes/collect-yearly-graded-race-participants/test_cases.md`
- 本文件

代码审核后继续更新上述状态与审核证据；只有实际发布或正式联网 run 发生后，才新增对应
`release_report.md`，不得预写未发生的 Actions、联网采集或生产证据。

本 change 默认不修改 `docs/decisions.md`、`docs/deploy_runbook.md` 或
`docs/project_overview.md`，因为它不改变生产模型、部署和产品链路；如范围后来扩为
`RacingRegion` schema 或生产页面改造，必须回到规格/方案审核。
