# B135有限纯核合同（实现前冻结）

仅新增content_review_decisions.py与语义unittest，基线1312e0e7；不改N01/ingest/publish/schema或他线。输出只有候选副本及diff，publish_eligible/qualified始终false。失败无candidate/diff，unknown protection允许manual候选diff，不叫N02-clean。没有provider、retry、DB、持久/UI或发布gate。

输入packet exact dict：schema_version=1；source exact {site,article_ref,capture_ref}非空str；capture_sha256=64小写hex；policy_ref非空str；body_parse_status枚举ok/selector_not_found/empty_after_cleaning/parse_error；protection exact {state:known|unknown,ref:str|null,protected_ids:list[ID]}（known需ref）；template exact {state:known|unknown,ref:str|null,version:str|null}（known需两ref）；trace为N01 metadata7字段（removed_count/removed_rules/trace_version/body_html_sha256/before_text/after_text/blocks）。块六字段block_id/locator/original_text/text/decision/reasons＋可选original_html_sha256；类型严格，ID重算与source/capture/locator/original绑定，重复拒绝。text是post-N01，eligible只非空kept/modified；removed空text，不复活script/CTA。原顺序重建必须等于after_text。

显式profile exact {id,purpose:TEST_ONLY|CALLER_SUPPLIED,source_site,policy_ref,limits}，无默认，无真实issuer声明；适用site/policy须匹配packet。limits exact八个positive exact int：packet_bytes/verdict_bytes/result_bytes/blocks/field_bytes/reason_bytes/quote_bytes/depth；整数表示<=2^31−1，depth<=64是递归安全支持界，不是业务阈值。测试profile32KiB/16KiB/32KiB、64blocks、8192field/quote bytes、1024reason bytes、depth12明确synthetic TEST_ONLY，不生产默认。结果候选/audit超result_bytes整包拒绝；固定小型错误响应不受错误profile/result cap约束，不带用户内容。无silent截断。

input_digest=canonical UTF8 SHA256({packet:完整可信字段,profile:完整适用profile})；canonical sort_keys/separators/ensure_asciiFalse/严格JSONbuiltin类型（无float/对象、循环拒绝）；不NFC。对所有影响保护、模板、上下文与重建的字段以及limits适用信息绑定。先有界验证/快照再处理，hash只证明caller可信包绑定，不外部认证或权限。

显式attempt exact str枚举available/unavailable/refused/timeout/invalid；未知分类拒绝。非available blocked无候选，不silent退到old/N01正文ok。verdict exact {schema_version:1,input_digest,policy_ref,decisions}；decision exact {block_id,action:keep|delete,reason非空str,evidence:{start,end,quote}}。eligible ID恰好一次、无额外/缺失/重复，不允许body/HTML/SQL/权限字段；证据exact int半开Unicodecodepoint区间，bool拒绝，quote逐字等于post-N01 text切片。delete必须[0,len(text))整块，original_text仅溯源，不回补modified前CTA。所有违约整包拒绝，不partial；protected delete blocked。reason/quote指令仅数据。

profile自身元字段每项<=1024UTF8 bytes、固定形状envelope<=16KiB/depth8，是解析安全支持界，不是业务通过线或生产profile默认。JSON整数字段支持63-bit幅值，profile limits为positive31-bit。以上技术界仅拒绝不支持输入。

输出status candidate_valid/needs_manual_review/review_blocked；reason固定码，candidate_text字符串或null、diff有序delete overlay、input/decision摘要、quality_gaps列表、publish_eligible=false/qualified=false。unknown protection为manual并可展示合法候选diff；所有输入/模型错误或删空为blocked，无text/diff。quality_policy_unresolved固定保留；template unknown缺baseline；TEST_ONLY标记不质量认证。合法decision按trace顺序重建，用原normalize_whitespace；不修改任何输入。short/noise只可留统计、不作通过线，template SHA不是模板变化；无retry/provider或现有publish路径封堵证明。

先实际N01生成A/B/C都eligible fixture（合成非F02gold）及原结果控制，再最小no-op用candidate正文/diff断言取得RED；无import/setup/TypeError假RED。随后GREEN和保护/重复ID/完整性/范围/Unicode/上限/attempt/空/keepall/幂等语义，原N01 trace纯回归。已有venv，不安装/启动DB/容器或新runner；原B035最小Django配置只用于模型枚举import，连接与socket均拒绝。

## 实际TDD与交付界限

2026-10-14现成venv Python3.12.13/Django5.2.1/BS4 4.12.3。原N01实际cleaner生成A/B/C三eligible且重建一致，最小no-op真实RED：1test/1功能FAIL/0ERROR，候选正文None与A+B不符。不是setup/type/import失败。RED源/test/log保留。

GREEN：23新语义unittest＋12旧N01 trace，共35PASS/0ERROR，约0.049s测试体；DB ensure_connection与socket.connect被拒绝，最小Django apps配置只用于原SourceSite枚举/模型定义import，无查询/连接、无provider/SDK/安装/容器。扩展测试首次2处缺json import的ERROR日志另存且已修，不计作RED。未跑含DB的news_content_boundaries全模块或新native/CI。

覆盖wholepacket/limits digest、quote/重要块保护、未知manual、重复文本按ID、removed/script/style及modified前CTA不复活、Unicode逐码点/NFC不转换、bool/越界/全块删除、packet/verdict/result exact byte边界、UTF8 reason/quote/field/block/depth caps、空结果与unavailable/refused/timeout/invalid、keepall/幂等/输入不变。输出diff.before_text是post-N01有效块，完整基线通过input_digest绑定caller仍持有的trace.after_text；不重复或修改整个N01原件。

本模块未接入任何ingest/publish/controller路径，永不qualified/publish_eligible。不宣称失败已封完整旧发布路径、模型语义准确、真实F02 gold、TC-N01指标、有界实际retry/模板issuer或整N02/I2完成。新test未擅改共享catalog/rules，原R代码审后由ROOT登记影响/安排后续交付；不绕过unknown-path门禁。
