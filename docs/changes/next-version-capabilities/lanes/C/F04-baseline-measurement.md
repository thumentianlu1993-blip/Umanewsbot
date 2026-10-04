# F04 固定旧版隔离浏览器基线

2026-10-03，Asia/Shanghai；实测 04:22:39–04:24:26。旧代码固定 `907f8de699b31a6fcc80acc78e9ba070aadc4f28` 的独立 Git archive，未使用受审工作树运行。Q01@924a原R两P2已APPROVED/CLOSED（审核报告e95fbac359f59ac8311a7882268e40c88c861460）；本报告不修改其行为字节，也不代表formal/full或生产交付。

## 结果与局限

六路径在桌面和手机各重复3次，36条正式run全部保留。五条路径30次达到浏览器/fixture终点；第六条6次只证明dispatch接受，未执行worker/provider，不算业务处理完成。只测旧版；新UI未实施，不能计算30%改善、90%自动完成率或人工编辑效率。

这是Chrome独立上下文中的DOM程序化点击、输入和真实页面导航，不是人工操作速度/阅读差异耗时，也不是物理手机键盘。task2验证原译入口导航与译文存在；task5验证应用后的fixture数据，未测人工理解差异或决策时间。初始页面加载、fixture准备和登录不计入正式run。点击时浏览器时间戳到下一页DOMContentLoaded作为navigation wait；同步DOM脚本耗时另记active_script_ms。人工active_ui_ms全部unknown/null。total_browser_ms包含工具编排间隙，不能用作用户总耗时或主动操作。下表只统计实际导航等待，不能把几十毫秒当编辑任务完成时间。

| 路径 | 桌面 n/终点 | 桌面导航等待中位 ms | 手机 n/终点 | 手机导航等待中位 ms |
|---|---|---:|---|---:|
| 工作台→待审核候选列表 | 3/页面/数据终点 | 30.50 | 3/页面/数据终点 | 30.30 |
| 候选详情→编辑器原译入口 | 3/页面/数据终点 | 32.10 | 3/页面/数据终点 | 29.80 |
| 修改正文→保存草稿→预览 | 3/页面/数据终点 | 61.00 | 3/页面/数据终点 | 59.00 |
| 快速术语创建→一次性应用 | 3/页面/数据终点 | 76.00 | 3/页面/数据终点 | 72.90 |
| 赛事候选→应用 | 3/页面/数据终点 | 44.50 | 3/页面/数据终点 | 42.90 |
| 修改保存→触发自动化（仅接受） | 3/仅接受 | 91.50 | 3/仅接受 | 81.90 |

保存/修复正文12项、术语应用6项、赛事应用6项均额外只读核验runtime SQLite，24项断言通过；6个候选status为applied。dispatch.jsonl恰6条accepted_only。浏览器每次后续导航resource列表均loopback；末3导航网络列表包含GET/POST/302/200且仅127.0.0.1，应用阻断请求日志不存在。HTTP返回或接受确认没有冒充异步完成。

## 视口偏差与失败分母

桌面精确emulate1280×900。手机精确device screen及visual viewport390×844、touch/mobile；候选详情/编辑器layout innerWidth为421–424、innerHeight911–919，工作台/赛事初始layout390×844。实际窄屏内容向右超过390（原文链接及内容区域等，最右约409px），不能标手机无溢出；长合成标识/URL可能影响宽度，尚未用真实内容或短fixture隔离归因。正式run保留实际viewport，不篡改为390。

准备时iframe harness被旧版X-Frame-Options拒绝：6条失败未开始任务，total_ms=null，原始记录保留preflight-iframe-failures.json。改为独立页面直接导航，未移除安全响应头。另1条首轮校准使用resize得到1280×751，保留calibration-inexact-viewport.json，不混入精确视口的3次样本。完整尝试账本=6个preflight失败+1个校准+36个正式run；没有删除失败、拼接中断或仅挑最优。工具artifact路径被Chrome connector拒绝两次，均在执行前拒绝、无run，改为返回JSON后保存本地。

## 隔离环境与恢复面

运行包 `/Users/mentianlu/.codex/runtime/f04-baseline/`：清env、禁dotenv、只读固定源码，runtime SQLite/locmem缓存与邮件、memory broker；合成staff和F04_SYNTHETIC账号对象。macOS sandbox OS层deny outbound，仅localhost:8894；最终profile下外部socket为PermissionError，本地socket与无proxy HTTP200。初次urllib继承宿主proxy被OS拒绝，改无proxy复验本地HTTP；不是外网可达。OneBot和requests显式阻断；dispatch是接受记录stub。不接生产PG/Redis、模型、QQ/SMTP、真实来源，不占Linux PG窗口。

已关闭专用浏览器页和8894服务。fixture数据库/账号密码文件仅runtime0600，密码不进入报告/消息/仓库。原始源码与fixture输入脚本/manifest保留以重建；原数据库在测前未额外复制，重跑应从固定seed脚本新建另一个独立runtime，不在已消费fixture上冒充首轮。

## 证据索引

- native-results-36.json：36条逐run初始/后续URL、视口、操作、导航等待、脚本耗时、编排总时长、结果与未知值。
- native-checkpoint-12/18/24/30.json：增量断点；preflight-iframe-failures.json及calibration-inexact-viewport.json保留异常。
- endpoint-db-checks.json、requests.jsonl（不记body/token）、dispatch.jsonl：数据及接受记录。
- fixture-manifest.json、serve.py、resume.py、network.sb、native-runner.js、native-action.js、native-settle.js：固定输入及编排逻辑。native-runner需要已登录Chrome pageId和tools运行环境，不是独立CLI。

核心文件SHA256：
- native-results-36.json：`fda7fe70224458f3e6a683b883b11b32a835ce46a586e55adbf31bc261047197`
- endpoint-db-checks.json：`34fa30ad0a49bf9da236c2b08010f9e4220e1c232a82d3a5468a7814560fc3c2`
- fixture-manifest.json：`aa4152fcb43a795cfb63d83f912b10ed42aa1bd4d60992540c03dd55cd13d3e6`
- serve.py：`1a78982e14d0557f06a35043619d1abbf7b3fbec18ca83b8be8f4b6038f9c968`
- resume.py：`8658fc157e80ab449f9e1983125ecaf70b1defe42272be5a1cd4a9f2cdc4f776`
- network.sb：`fd0e9f957f1d2a0cec613328c6ee90fb608864edbbf98d3c6911670a4ebe18f0`
- native-runner.js：`c628a00a6861bd8733f2c1a2cbb291e366dbc23f861a3f8c2fabc7e23e2ba06a`
- native-action.js：`4b3ad2389925d818406ba3e5e366b6ad1d32d5502dafec3e0a446a37e151c552`
- native-settle.js：`4a5e819b1326f56b566919ebf0b28d49ebd2546248397c22c3c1c54ae7fc6543`

F04旧路径自动化合成基线已补；人工主动时间、真实手机阅读/输入、自动化业务终点、旧新比较仍未验证。本事实报告交协调者/原R核对，不自行扩展Q02或其它实现。
