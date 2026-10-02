# PR233 CI策略启用包

用户在2026-10-02明确要求“启用并上线”，范围为PR233及上一轮列明的首次校准、实际交付核验、严格保护和策略切换。
本包以PR233最终head和实时main/base/tree绑定；精确SHA、CI run、review及delivery receipt由执行记录保存。
人工确认门禁仅引用根AGENTS.md。

## 操作范围

- 单候选full首次校准：每批≤200，最多4容器并发，不执行基线全量；所有失败/skip显式记录。
- 独立review通过后，从受信Git对象提取核验器到候选目录外，以同run镜像重新收集并核验证据。
- GitHub main保护：strict required checks与enforce_admins；正式交付统一要求真实PR的`test-plan-gate`；手动校准的prefixed check不计入GitHub PR门禁。不增加人工审批人数或旁路身份。
- 设置仓库变量`IMPACT_TEST_POLICY=active`，合并PR233，切换统一PR gate，启用受控高风险及日周full入口。
- 没有数据库迁移、生产配置/数据动作、应用镜像重建或服务重启；没有QQ、邮件、通知或真实抓取动作。

## 验证

核对真实API的检查名称、成功run/attempt、完整合并tree、控制文件身份、实际收集全集、strict/admin保护和base未前移。
主线启用后，以文档小改动的真实PR验证新入口只做静态检查、不执行业务数据库测试，并核对旧入口不再自动触发。
其他targeted/expanded/full/error分支用已有合同与计划回放验证；首次full通过不等于10个明确环境覆盖缺口已消失。

## 失败处理与回滚

任一必需核验失败时不合并。修改前保存原始保护配置、变量状态、主线SHA与旧workflow。
合并前失败可恢复原保护/变量状态，不影响业务服务。
合并后若新入口不能正确拦截或执行，通过受审revert恢复旧workflow和原变量/保护配置；不得仅关闭新检查后继续交付。
回滚会恢复旧测试成本，但不涉及生产数据库、镜像或业务数据恢复。

## 首次引导兼容修复

实际GitHub check-run名包含reusable workflow调用前缀。核验器从已验证的bootstrap workflow推导唯一required context；
普通PR仍严格要求无前缀的`test-plan-gate`，不得用引导检查替代。新增小测试先RED，再48项GREEN；等待独立复审。

## 首次校准返修记录

`37010615475`因首次保护检查名兼容修复取消，不计校准通过。
`37011044271`对ae9dbb19分批校准失败：21份完整报告、4065个开始执行的ID；另13批无完整报告，未冒充全量通过。
确认并修复：头条同版本并发夹具、单个runner命令测试的宿主磁盘依赖、镜像缺少标准python3入口、
事务测试重置序列与初始数据碰撞、固定日期registry夹具过期。37项隔离PG直接回归全部通过、零skip。
两类真实迁移测试按完整类单独分批，保持全量集合及类边界，避免与普通测试挤满200项造成600秒超时。
逐例开始日志写入artifact供超时定位；本机跨架构诊断的faulthandler自动堆栈触发解释器崩溃，已移除该临时诊断，仅保留逐例日志。
新分片合同先RED再通过，本地工具49项通过。后续仍需最终SHA完整校准与独立review。

本机交付核验使用专用`colima-umanews-impact-ci`、classic image store及本地unix socket，与CI镜像config ID一致。
Docker29默认containerd store导入同tar返回manifest ID，不能将其当作CI config ID使用；未放宽镜像身份校验。

## 第二轮完整校准的清理问题

`37014124643`在136998b3上执行6164项、41批，零业务断言失败、10项既定环境skip，
但batch-019在销毁测试库时发现遗留连接，因此整体失败，未合并或激活。其余40批完整通过。
并发写入测试使用`close_old_connections`，未过期的线程连接未真正关闭。新增直接清理断言，
单例RED得到`[False, False] != [True, True]`并再次出现删库被占用；四处线程finally改为显式关闭自己的连接。
原有并发、锁、幂等及事务断言保留，未改业务代码或放宽测试库清理门禁。后续记录直接GREEN、独立复审及最终校准。

## 真实PR引导兼容修复

手动校准37017985056在7067935e上完成6164项/41批：6154通过、10项既定skip、零失败/错误。
旧核验器输出的manual verified仅证明其当时的证据核验，不构成GitHub PR合并依据：真实merge被必需检查门禁拒绝，未绕过保护。
独立审核批准改为真实PR事件；空提交d0f2b7eb与7067935e的tree及19个controls完全相同。
PR37025319082在计划阶段被正确阻断：payload的TEST_SHA仍为旧head的a243b576，而HEAD_SHA已是d0f2b7eb，未启动整套测试。
已先复现三处PR旧/空merge缓存选错及manual误作交付的7个RED断言，再改为事件`github.sha`；manual/定时复用入口仍用显式candidate。
正式交付核验收紧为仅接受真实pull_request，首版独立审核的trusted-sha机制仍保留。strict/admin/app15368持续有效，未产生无required-check空窗。

入口修复后，本地50项工具合同全部通过；未启动本地业务全量。最终真实PR校验及交付凭证仍待执行。

## 最终启用状态

连接清理修复的8项PostgreSQL直接回归零失败/错误/skip，独立复审APPROVE。最终185a7d07的真实PR完整校验通过，
候选外交付核验、保护配置、策略开关及PR233合并均已完成；精确证据见[启用证据](activation-evidence.md)。
此前各段“待完成”是历史状态。真实文档PR验收随本记录PR执行；未为该验收重跑全量。
