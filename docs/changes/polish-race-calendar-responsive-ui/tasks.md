# 赛事日历月份与等级徽标任务清单

## 0. 方案门禁

- [x] 0.1 (application) 从最新已核验 `origin/main` 创建独立干净 worktree 和
  `codex/polish-race-calendar-responsive-ui`
- [x] 0.2 (application) 只读探索 view、context、模板、CSS、测试、时区、状态 class 和共用徽标
- [x] 0.3 (operations) 用仓库外临时 SQLite 数据在真实 390px 页面复现月份缺失和徽标压窄
- [x] 0.4 (application) 核对 `simplify-public-navigation-and-attribution` 当前/计划文件范围
- [x] 0.5 (application) 编写五份持久方案文档
- [x] 0.6 (operations) 未参与方案编写的 reviewer 完成独立方案审核（首轮 `REVISE`）
- [x] 0.7 (application) 有 finding 时修订方案并复用同一 reviewer 会话限定复审至通过
- [x] 0.8 (operations) 方案审核通过后向用户汇报并停在实现确认门禁

## 1. 测试先行（取得用户实现授权后）

- [x] 1.1 (operations) 启动测试 subagent 前重新记录并行公共页面 change 的 HEAD、完整修改文件和
  共享函数/selector hunk；只有稳定版本、完成 rebase 或双方 owner 锁定不重叠边界之一成立才继续
- [x] 1.2 (application) 测试 subagent 新建聚焦测试文件，覆盖同月、跨月、跨年、星期和非硬编码
- [x] 1.3 (application) 测试 subagent 按具体日期 group/selector 覆盖 today、锚点、圆点、焦点条和 URL
- [x] 1.4 (application) 测试 subagent 覆盖固定 42px CSS 契约、移动端 auto 覆盖、G1/G2/G3/JPN1
- [x] 1.5 (application) 测试 subagent 覆盖四个全角字符、空等级、长标题、共用页面和桌面契约
- [x] 1.6 (application) 测试 subagent 运行聚焦测试并保存由目标行为缺失导致的真实 RED

## 2. 实现（测试 subagent 完成并确认 RED 后）

- [x] 2.1 (application) 实现 subagent 在 `public_race_calendar()` 增加当前结果是否跨年的只读元数据
- [x] 2.2 (application) 实现 subagent 修改赛事日历模板，逐项显示月日并在跨年时逐项显示年份
- [x] 2.3 (application) 实现 subagent 保留 today/race-dot/focus/anchor，并补 today/target 可访问反馈
- [x] 2.4 (application) 实现 subagent 最小修改共用 `.grade-badge` 固定尺寸、全角两行和空等级回退
- [x] 2.5 (application) 实现 subagent 修复日历移动 flex 覆盖并让长标题在标题区换行
- [x] 2.6 (application) 实现 subagent 运行 GREEN；不得修改模型、迁移、赛事数据或新闻/马匹链路

## 3. 主代理整合验证（全部实现 subagent 结束后）

- [x] 3.1 (application) 运行聚焦测试和 `RaceEventPageMVPTests`
- [x] 3.2 (application) 运行赛事日历、首页近期赛事、赛事详情和新闻赛事预告回归
- [x] 3.3 (application) 运行与 `simplify-public-navigation-and-attribution` 的联合回归
- [x] 3.4 (application) 运行 Django check、无迁移检查、模板渲染和 `git diff --check`
- [x] 3.5 (integration) 必要时运行完整 stable 回归并区分基线失败与新增失败
- [x] 3.6 (operations) 完成 1440px、390px 和必要 375px/320px 真实视觉验收
- [x] 3.7 (operations) 保存可审计尺寸/overflow/console/截图结果，确认临时截图不在 Git 范围

## 4. 独立代码审核

- [x] 4.1 (operations) 未参与实现的 reviewer subagent 按 fingerprint 规则实际执行 Codex 原生只读 review
- [x] 4.2 (application) 有 actionable finding 时修复测试时钟、移除本地 symlink 并同步 durable status
- [ ] 4.3 (operations) 复用同一 code reviewer 会话，只复审 finding、修复及直接触及路径
- [ ] 4.4 (operations) 最新成功 review 后停止并汇报 fingerprint、测试/视觉证据和残余风险

## 5. 发布（最新成功代码 review 后仍需用户明确授权）

- [ ] 5.1 (operations) 取得用户针对当前受审版本的 commit/push/PR/部署授权
- [ ] 5.2 (operations) 按同一 scope 重算 fingerprint，显式 stage 并验证 index content hash
- [ ] 5.3 (operations) 仅按授权执行 commit、push、PR/merge 和部署
- [ ] 5.4 (operations) 验证生产 HEAD/镜像、Django check、无迁移、healthz 和真实桌面/移动页面
- [ ] 5.5 (operations) 按 evidence-only closure 回写真实发布证据并复用同一 code reviewer 会话审核
