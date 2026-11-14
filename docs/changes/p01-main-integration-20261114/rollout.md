# P01主线集成交付包

## 范围与当前证据

PR #317 替代旧栈增量PR #314。以main `15d8b53e` 为基线，完整P01依赖首次进入主线。
实际发布commit、OCI config/manifest、归档SHA、配置链SHA与控制脚本SHA由本次专属runtime的
`execution-plan.json` 和 `execution-binding.json` 固定，执行前全部核对。以下保留发布前方案，实际结果见末节。

生产只读基线：四应用 `3f967f64`，Web healthy，QQ关闭；完整Compose链保留法国、美国、英国、日本与NAR配置。
25,066篇新闻，新闻表714,612,736字节（快照数量，不要求采集运行期间恒定）。

## 迁移与数据边界

实际未应用迁移为以下七项，不能只依据最大编号0084判断：

- 0080_translation_retry_budget：新增两张预算/请求表；无回填。
- 0081_managed_readonly_steps：新增两张只读任务表；无回填。
- 0083_merge_france_basic_fields、0085_merge_us_divisions：无操作的图合并记录。
- 0086_p01_news_quality：P01新表、新闻版本号及nullable关联列；版本号有数据库默认0。
- 0087_p01_immutable_publication、0088_p01_sealed_evidence：P01证据保护触发器。

首次上线保持 `NEWS_QUALITY_MODE=off`，index/feed/dispatch均false，不创建P01预算或运行记录。
无历史新闻重译、真实模型请求、自动发布、实体库批量回填、QQ或其他消息发送。
Nginx仅检查并reload原有配置；P01匿名曝光日志配置和专属worker随之后续激活另行部署。

## 执行顺序

1. 获取production release flock及既有部署锁；核对运行镜像、完整配置链、空闲磁盘至少3GiB。
2. 加载固定镜像；一次性容器只读验证精确七项迁移、关闭态和QQ关闭。
3. 暂停Beat，等待两个worker原任务自然排空，再温和停止worker和Web。排空失败恢复原Beat，不重建worker。
4. 私有备份完整配置/.env、旧schema、django_migrations及受影响三表（newsarticle和两张首页标题表）；验证归档非空、TOC、SHA。
5. 对停写后三表原列做数量及内容摘要，执行迁移一次（锁等待10秒、语句120秒）；校验空迁移计划、原列摘要完全一致。
6. collectstatic，重建Web并等待healthy，Nginx检查及reload；验证首页、健康页、原新闻及代表性赛事。
7. 重建两个worker并确认ping，最后恢复Beat；核对四应用实际镜像/版本、P01关闭、QQ关闭，落盘完成凭据并释放锁。

服务重建仅web、worker、race_sync_v2_worker、beat；保留数据库、Redis、Nginx容器、浏览器采集服务及其他项目。
Web停服窗口包含备份和DDL，不保证零停机。备份TOC/SHA验证不等于完整灾备恢复演练。

## 恢复

首次关闭态发布失败时，只有P01运行/发布/请求记录均为空才可恢复原 `3f967f64` 完整配置链四应用。
保留新增空表、列和触发器，不执行逆迁移、不覆盖数据库。已通过隔离PostgreSQL的真实旧分支升级、原新闻保留、历史ORM写入测试。
如果出现P01记录或无法确认排空/停止状态，停止自动旧镜像恢复并保留证据，进行前向修复或另备精确数据恢复包。
一旦后续激活P01，旧镜像恢复条件不再自动成立。

## 验证状态

247项P01回归、缓存修复44项回归及两种迁移起点兼容测试通过；最终范围CI和独立复审另见本次执行证据。
真实模型质量、正式预算、全量人工gold及自然运行验收仍未取得，本次代码部署不代表这些能力已激活或验收。
人工门禁统一依据[根AGENTS.md](../../../AGENTS.md)。


## 2026-11-14 实际发布结果

北京时间21:33:56完成发布。PR #317已合并，merge为
`efb2a6c7e7b7e554515217fd38fd7c40c674249a`；运行源提交为
`e6c47a98569f9eef626ac905f989cb9ba20b6726`，镜像`umanews-p01:e6c47a98-r2`，
OCI manifest为`sha256:cad9f07b406cdfd29ca76a77f7775a637633e30e7825dc7efa161b28101068a4`。
合并树与受测树一致；最终范围CI为1,584项、9批、零失败、零跳过，交付验证器结果verified，
代码及发布控制器独立复审通过。

首轮七项迁移全部完成，schema到0088；停写快照为25,067篇新闻，三张受影响表原列的数量和SHA
在迁移前后完全一致。随后Web因镜像复制后启动脚本缺少执行权限而失败，控制器恢复旧四应用并
验证健康，保留新增schema。R2只修复8个脚本执行权限，文件内容及原镜像层保持一致；四个实际
应用入口均通过隔离启动探针，包差异经原独立审核上下文复审。R2预检严格要求空迁移计划，
没有再次执行DDL或数据恢复。

最终四应用的镜像及revision一致，Web健康、两个worker ping通过、Beat恢复；首页、健康页、
三篇现有新闻、法国凯旋门新路径，以及NAR的68行（12选定/56候补）和JRA的18行公开名单通过。
两类发布锁均已释放。`NEWS_QUALITY_MODE=off`，index/feed/dispatch关闭，P01运行记录为0，
QQ关闭。本轮没有真实模型调用、历史重译、数据回填或外部发送，未进行P01自然运行质量验收。

生产证据分别位于`/opt/umanews-external-staging/p01-e6c47a98/evidence/`（首轮迁移及恢复）与
`/opt/umanews-external-staging/p01-e6c47a98-r2/evidence/`（最终发布）；后者
`controller-result.json`为`released_and_verified`。本机证据根为
`/Users/mentianlu/.codex/runtime/p01-main-integration-20261114/`，保留原包、修正版绑定、
`delivery-verified.json`、`production-result-r2.json`和`post-release-verified.json`。
