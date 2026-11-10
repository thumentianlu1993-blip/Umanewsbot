# 发布与回滚

## 当前状态

PR #293、#294 已合并；法国80个唯一目标、59历史场511行赛果、10场旧登记/80匹名单交接与49项日港政策换绑均已提交并验收。Geny同URL主页面重载修复已通过298项范围CI（零跳过）、独立复审与精确交付核验；生产窄候选 `5669283d`、应用镜像 `7fc5473c`、浏览器镜像 `30d27626` 由固定包 `8bd146098913` 于北京时间2026-11-10 04:07:46完成发布。五服务运行、四应用实际版本一致、双worker pong、双域健康通过，QQ关闭。

21/21未来目标已完成自然调度检查，失败数0：11场共253条名单预览，10场明确暂无已公布名单；最后一场795在04:17:19由自然调度成功，未手工派发或重置失败记录。最终80/80公开页通过，511行历史赛果与253条预览核对一致；79页使用输入与HTML双SHA不变的既有通过证据。正式卡接管、赛后自然更新仍按原约定等待真实赛事节点，不能把当前预览或诊断实取计作该项通过。

当前固定包为 `8bd146098913`，无需重新执行历史导入。维护使用原目录的base、pinned-images、france-browser、application-identity、capacity，再追加 `/opt/umanews-external-staging/france-geny-reload-5669283d/release-identity.json`；完整命令见[运维手册](../../deploy_runbook.md)。失败时核实停写，浏览器恢复本次前镜像/环境，Web保留健康获准镜像或精确恢复；不自动恢复数据库。详情见[证据](release_evidence.md)。

下文是历史草案，用于追溯业务范围，不作为当前生产执行入口；当前恢复仅使用经根AGENTS.md批准的精确后继包。

## 发布包草案

- 无模型迁移。候选提交、PR、镜像digest与测试收据在冻结后绑定。
- 新增 `france_browser` 服务（无宿主端口），`FRANCE_BROWSER_URL=http://france_browser:8080`；外部独立会话文件只读挂载。应用web、race-data-sync worker、beat使用同一候选镜像；其他服务按实际代码依赖核对。
- 法国功能配置：`RACE_DATA_SYNC_FRANCE_PRE_RACE_ENABLED=True`、60天早期名单窗口；既有enabled providers追加 `geny,france_galop`，regions追加 `france`，保留日港配置。共享字段开关维持准入清单，禁止顺带开启race-live或QQ。
- combined-policy保留日港routes，追加法国Geny正式time/card/result与France Galop早期名单route。policy digest变更需要把现有49场日港登记（43日本、6香港）按当前基线、旧新route digest制作rebind manifest；不能仅替换策略导致旧登记停止更新。
- 数据包80唯一目标，10AQPS补档，注册精确来源名称，4→784旧URL产品映射，59历史场511行；生产数据库保留81条事件含旧重复记录。JSON证据存外部专用artifact目录，manifest绑定源SHA与当前DB基线。
- 当前数据草案manifest SHA：`cb373a608bb343348f9c0a1cd2dafb2a1d079354dd883b76613f27a1b8502dc0`。这是草案，不构成发布授权；若基线漂移须重生成数据差异与绑定。

## 执行与验收

按根AGENTS.md的发布协调、锁与门禁执行。冻结前实时只读复核生产镜像、队列/租约、策略、登记、配置、资源和备份面。独立France Galop会话已在Linux headless验证；生产安装后仍须先在实际服务内读取验证，再打开法国采集开关。本机Chrome访问或Geny成功均不替代这一项。

批准包内执行：取得release锁并停相关采集写入 → 保存配置/策略及受影响行的可恢复备份 → 加载固定镜像与会话 → combined-policy及现有登记rebind的dry-run/apply → 法国manifest dry-run/apply → 开法国开关 → 恢复调度并验证。数据命令只读本地归档，默认事务回滚；apply带`--expected-sha256`和产品映射批准者ID。

验收：80唯一公开页HTTP及字段；10AQPS类别/条件；4旧URL指向784；59结果511行及非出走状态；21未来目标11名单253行、10明确未公布；来源平台/北京时间/公斤/距前马；日港现有登记继续可claim；队列与预算正常、QQ关闭。随后等实际节点验证报名→正式卡→赛后自动变化，不提前宣布自然回归通过。

## 恢复与停止

浏览器认证失效、未知身份/状态、基线漂移或不完整来源均保留旧资料并停止相关写入。代码恢复先停法国开关/worker，恢复旧镜像和配置；策略回退必须连同既有登记的旧digest/代数状态恢复，不能只替换policy文件。数据回滚恢复精确备份中的受影响事件、结果、名单、来源名称、身份、登记/跟踪、候选、映射及操作收据；不得删除无关数据或全库覆盖。回滚后核对日港调度和旧公开页。

## 独立登录操作

运维在装有该版本Playwright的本机环境运行 `node deploy/france-browser/login.cjs /仓库外私有目录/france-galop-session.json`。在独立窗口正常登录，确认分级赛目录可见后回车。工具只导出法国域状态，不接受命令行密码；文件0600且不覆盖既有文件。后续安装/验证绑定到最终发布包，过期时同流程生成新文件并验证。
