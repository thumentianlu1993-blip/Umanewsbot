# PR239 合并交付材料

2026-10-06 01:51，Asia/Shanghai。正式PR测试、独立review与候选外可信verifier均已通过；**等待用户选择本次G2交付范围，尚未获批准**。人工确认唯一依据为根 [AGENTS.md](../../../AGENTS.md)。

## 固定对象与行为

[PR239](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/239) 固定head `63bb2416e775c60bd3c594967b9f893574f36ccc`，base/main `ec0a12506cf2131eb6f6d774d9941f764f15c845`。实际受验merge commit `72b54b82dbc682fb37eb0b881d38915f3fe1e88e` 的两个parents恰为上述base、head；tree `77c1521672a5f9037674f88e83ed8eff3ecc16c2` 与候选相同。

相对main共11文件，新增两项局部能力及其测试、说明和影响映射：

- 新闻分析Responses适配器及mock测试：默认关闭；验证正文证据、候选身份和返回结构，配置无效或输入不匹配时零请求；显式启用后也不自动重试、不写ORM或自动发布。数值配置错误不会阻断原服务装载。
- 公开赛果探针ORM只读快照加载器：在短只读事务中独立核来源身份、修订阶段和确认投影，再复核变化；缺失、漂移或冲突返回未验证。它尚未接入生产view/探针，不宣称来源、响应绑定或SLA已经验证。

本次不部署业务镜像、不应用生产配置值、不启用模型或公开自动化，无迁移、服务重建/重启、生产数据写删、真实付费API或外部发送。源码新增关闭态配置定义，合并不等于生产配置已变更。

## 独立审核与测试

原R对B020配置返修 `6ba6cbc4`、C026确认投影返修 `ee21b707` 均通过；集成映射原finding由 `aa621abe` 关闭。候选为满足strict ancestry合入实际main后，代码树完全不变；原R `869295ac` 核对精确parents、同树、96,299字节新旧diff一致和同一controls，官方前后指纹/私有seal一致，原审核结论适用于本head。

正式[CI37345802939](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/37345802939) 的 `tests` 与 `test-plan-gate` 均成功。原始报告为full **6,566项、47批：6,556通过、10项明确许可跳过、0失败、0错误、0意外成功**。全部实际ID唯一，batch生命周期complete、exit0。10项跳过为8项缺真实缓存、1项镜像契约未启用、1项要求root EUID，均沿原10/16复核期限；跳过不计通过。

候选外verifier从固定main `ec0a1250` 提取，SHA256 `7e58cb72042dd76ef064f9121589f1a06655aad6befc1278d389ffc8799c7d7d`，与此前受信版本原字节一致。它已下载本轮实际CI镜像并独立重收集完整ID/分批，核原始报告、受审controls、base/head/tree和有效分支保护，最终exit0、`status=verified`。没有重跑业务全量。下载进展有实际网络计数，完整结束后自有verifier/下载进程均已退出，专用daemon无运行容器。01:51再次核实际PR仍OPEN/Draft/MERGEABLE、head/base未变，`test-plan-gate` 必需、strict=true、enforce_admins=true。

首次verifier因ROOT提供的controls记录使用 `head_sha` 而入口要求 `commit`，在下载artifact或启动Docker前退出。已保留原受审输入，另生成符合入口合同的白名单：仅把同一已审核head映射为 `commit`，control blobs未变，verifier未改。该技术纠正不重跑业务测试，也不改变审核范围。

| 证据 | 值 |
|---|---|
| 原始CI输入SHA256 | `2cb546bb287fcd5a4205c23afa290e461ec5e18f0289a30a0d401d39dced6d4d` |
| plan digest | `c172f6d8998e4198f8eee4ac6dc4559144f2e640725291307c16298920cc772e` |
| content digest | `ffb5fc76955ca79a545c44c5ffa70d683f0937dbb629017bfe370f5180ba637a` |
| 实际CI image ID | `sha256:8e5ef1e2746f036aa00a6c50bd043949267e1b1fe3635be912d97399606dd3ca` |
| 测试artifact | `11361029219`，521,234字节 |
| 镜像artifact | `11361153945`，396,294,110字节 |
| 最终交付收据SHA256 | `f6bd82ec08d6d9349ed5a14424fd74cef03dc3c0a7b5b1a2caf670e5991f90fa` |
| 测试artifact ZIP SHA256 | `e16424d764df516fb3941f5ffa72aaaf2d2949c318b2e4a59b334b2172996454` |
| verifier入口白名单SHA256 | `2c272283742a6a5b6e653b80c64096d6fd0a82d707743a3a928bdb4f26aad03b` |

## 获准后拟执行范围

本次一次选择：**A：只合并上述固定PR239，不发布；B：合并同一PR239，并连续执行[006单次诊断/首样本包](B028-first-sample-delivery-006.md)（推荐）**。006的原R技术复审与精确绑定已完成，完整manifest为 `3e561f256030c8d13695764ffbe07d7069b2dabcdbbd019120fba2f9559e6b28`。B只增加该包的一次有限生产读取、私有暂存/传输/签收、互斥和条件式恢复，不包含整版业务镜像发布。PR239代码与006私有工具是两个独立固定对象，不互相替代证据。004现场根因仍未知，B可能只得到更明确的失败类别；不能保证取得样本。

若仅合并，执行前重核head、base/main、有效必需检查与保护，使用正常远端合并并核实际merge commit/parents/tree/main；不使用管理员绕过、force-push或修改其他工作树。远端结果未知先核实际状态，不重复副作用。生产动作全部为0；撤回代码另准备实际merge commit的revert PR，不把合并批准扩大为生产回滚。

真实来源、完整F02样本、质量/费用/时延、恢复演练与自然观察仍按版本任务验收；此次合并不代表整版开发结束、启用或公开验收通过。
