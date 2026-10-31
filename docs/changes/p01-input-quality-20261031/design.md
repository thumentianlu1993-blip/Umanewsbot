# 输入修正与定点质量验证

用户已批准：修正文拼接，建立现有三个失败案例与正确对照，实体/审校小规模对照，之后根据结果决定是否能进入完整流水线。保持当前线程worktree与分支，不跑全量CI，无新抓取/生产写入/部署/外发。

实现仅修正news_content中HTML文本提取：行内元素连接保留原始文本节点间空白，不人为增加分隔；br和块级元素有语义分隔；表格单元格/列表项保持既有边界。注释/非正文脚本不可进入正文。默认所有语言使用DOM文本邻接原则，不按具体词删空格，不相信HTML自动链接为实体证明。clean SHA变化使旧内容证据失效；不得将旧跨度/缓存应用到新清洗文本。增加嵌套行内标签、词内链接、英文显式空白/词内强调、br、表格列表/段落和真实截取最小回归。先RED后GREEN，定向六模块及来源抽取相关测试，独立只读review。

离线准备：原3篇缓存HTML重新clean，记录原始HTML hash及新旧clean差异；以冻结旧实体输出重放，展示文本变化后证据必须重算，不绕过校验。建立评价期望：22726普通词ラストラン不得当horse；22725实体text必须字面存在且contexts唯一；7611两次France Galop分别定位。保留模型少抽/错分不能单靠结构校验发现的局限，代理标注不等于人工gold。

付费实验仅在修复及review通过后冻结新包：最多10次调用、整批增量0.50美元、历史20美元保守上界(当前5.27198346含旧unknown0.03872088)。原3篇重清洗实体各base/deep一次(6次)；22726一对固定错误/修正译文各base/deep一次(4次)。均调用生产request_spec/reservation_amount/prompt_for和validator；不自动升级/重试/扩大输出，不跑整条流水线。8192输出上限、120秒超时，新增unknown停止全批不重发；预约余额不足则停止，全部本地/远端收据核对。原名保留，不连接生产术语DB。新包不复用旧operation。小测试图隔离输入改善和模式差异，初轮保持原提示词，避免多个变量同时变化；若仍失败，报告为下一轮提示/契约改进依据，不无限追加付费试错。

全流程最后记录是否存在候选组合能正确处理3篇实体且对坏译文拒绝/好译文不误拒。仅10次诊断不足证明生产质量；无论结果不自动开启发布。实体与审校未达标时不进入后续完整流水线扩样。

## 独立审查修正

1. 每篇冻结必要实体occurrence：原文精确block/start/end、type、text及唯一context；不以coverage=complete自报或空数组作为通过。冻结禁止误抽的普通词及词内片段。结果区分schema/定位失败、必要occurrence遗漏/错类、禁止误抽、定点集合通过；集合通过不等于全部专名人工gold。审校负例必须verdict=fail、evidence_valid=true且issue引用命中注入错误目标跨度；uncertain/schema错误/引用失败/截断均不算检出；正例须有效pass。缺格不计通过。
2. 四次审校payload完整冻结：同新clean、同代理标注并重新定位的entities、同空editorial；不读取前六次实体模型输出，坏/好目标仅改变b0指定短语(最后一战↔ラストラ战)。两版与新块ID一致，离线hard checks通过且注入跨度唯一，其他字节一致。非人工gold，代理修正参考须独立只读对照确认。每个case显式调用request_spec(stage,profile=base/deep,payload=payload)，不从生产required_profile推断实验profile；不改变生产实体路由。
3. 文本边界明确：行内a/span/em/strong等保留原文本节点邻接和原有空白；br及div/p/section/article/header/footer/aside/nav/main/address/figure/figcaption/blockquote/ul/ol/li/table/tr/td/th/dl/dt/dd/h1-h6/hr/pre在文本递归投影中提供空格边界，最终压缩已有空白。根walk仍保留原有BLOCK_TAGS分块/表格管道/列表换行结构；不含BLOCK_TAGS的div保留结构分隔，不把相邻div合成AB。验证根inline、p、table、list四条路径，注释/script/style不输出；不解析外部CSS或全局去空白。
4. 实验只比较新输入下base/deep。旧输出重放只证明哈希/跨度需要失效，不能归因模型效果改善于清洗修正。初轮不改prompt。运行包核验必须覆盖两版目标唯一差异、必要实体非空、模型profile和费用上界，以及原缓存字节一致。
