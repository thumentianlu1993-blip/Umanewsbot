# C178：L03 文章→赛事返回最小实现源候选

状态：MINIMAL_IMPLEMENTATION_SOURCE_ONLY / GREEN_NOT_RUN，待同R_C源码窄审。直接parent `0f9f13d220975519d44a2d1333ed15122e97d800`，PR main base仍 `1dd5e0a508957672bcddd1c33e454fbbef1b75c1`。最终head/tree由本线runtime source-binding绑定；未amend旧提交，未push或触发CI。

## 原RED与本次改动

C177正常PR253 run38865206805/attempt1，test-merge `185eab7aa0036653194b3c93ef8ef921e9909a9f`，tree `34ef6c571ddf41f39c4b25e2af01213b15071513`；6871唯一方法/49批完整，目标8方法执行、6控制通过，两主方法四subTest均在143行因赛事入口丢news token的AssertionError失败。原R_C报告SHA256 `e08d45a8a1a11da90823d175364c3ce2c2d57390308ec2b02d10210c3d0f713b`批准仅目标RED证据。完整CI与gate仍failure，10旧skip、batch-037一条RUN行粘连分隔符限制均保留；此RED没有提前证明完整回程。

只改 `server/stable/views.py::public_article_detail` 与真实模板 `server/stable/templates/stable/public/detail.html`：

- 先沿原AUTO/MANUAL、目标PUBLISHED过滤，再调用一次既有 `_public_detail_nav(request, allowed={"news"}, default="news")`。
- 给每个现有link.event只附本次请求内的 `public_list_detail_url`：仅非空已验证token传入原 `_public_href(event.public_path, {"return_nav": token})`；空token或helper空结果回退event.public_path。不写DB、不重签发、不直接拼未经验证GET，不变更身份/届次/名称/排序/公开资格。
- 原teaser选择仍从同一race_links的event对象选取，因而与chip复用该临时href；模板只把chip和teaser两个赛事href改读该属性。horse href与允许来源不改。原article上下文使用同一次navigation dict，没有第二次解析或新helper。

坏/重复/过期/跨kind输入仍由原校验合同拒绝且返回裸路径；现有codec、allowed kinds、盐、TTL、预算、模型/关系/权限和其他views函数保持。`prepare_context`仍处理原对象，不替换race_links/teaser对象或移除其临时属性；本次未改该服务。

## 不变对象与静态证据

C176测试 `server/stable/test_article_race_navigation.py`完整SHA256保持 `8788aed4cd6b4126238c33db331507a3bbc339c0964d40a4d3ac3c2851d63773`，8唯一方法、原断言、过期负例与重签语义断言均不动。catalog、rules、models/settings、导航codec、runner/workflow、skip名单全部与parent字节相同。C177原件和R报告按原SHA保护，未重写原RED。

标准库AST feature_version3.12与compile-source仅解析views源码，顶层模块除public_article_detail外AST一致；模板文本严格只有两href表达式替换，标签/结构/horse链接未动。Git diff/check通过。没有导入候选/Django或渲染模板，没有planner/collection/tests/DB/Redis/服务/Docker/网络/CI、本地测试域或宿主/demo替跑。

## 未来同PR正常CI包

新runtime ci-packet绑定本候选head/tree，复用唯一Draft PR253及原分支。ROOT先送同R_C窄审，再精确派非force push/正常synchronize CI；本轮不接触远端。

未来测试字节必须仍为上述C176 SHA。新run需重新绑定当前base/head/test-merge树与run/attempt、完整plan、收集/执行分母及所有原始批次；同一正常affected_tests工作流、catalog差异使旧/新full覆盖保留，不缩原6871方法/49批基线、不删任何旧label。新分母/分批若有真实可解释差异，应列明并回ROOT核验，不能把缺失转通过。原10skip按原ID/reason/profile/review_by=2026-10-16单列覆盖缺口，不自动延期，也不靠skip让两个主方法通过。

仅当实际8目标方法全部无fail/error/skip、两个完整page2→文章→chip/teaser→race→back→news链连同最终新签名语义均走完，并完成正常原分母与控制回归，才可按证据评定本切片GREEN。当前仅提出预期，不声称任何实际GREEN；完整L03、L02/H06、I2/生产与部署均不因本源码候选接受。无merge/deploy/启用动作。
