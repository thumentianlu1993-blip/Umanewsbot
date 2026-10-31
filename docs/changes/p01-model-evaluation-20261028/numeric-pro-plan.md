# 数字日期修复后的20篇全Pro思考复测

**状态：2026-10-31按用户要求暂停，未完成20篇。详见[numeric-pro-pause.md](numeric-pro-pause.md)。**

用户授权：先修复数字和日期误拦截，翻译也换成Pro思考模式，用原20篇复测，累计费用20美元以内。

代码固定为 `7878ab4d933a58017288a9baca690356884ec1c9`；模型包SHA `cf587c3fda37d95538f0965136fd324e9445a384c1a04278db6ffdb8a644f396`。只读缓存输入、提示词和输出契约与上轮一致，五阶段均为DeepSeek Pro思考high，不发送max_tokens。没有生产配置变更、抓取扩围、业务数据写入、发布或外发。

累计保守上界起点4.89675234美元，含旧unknown预约0.03872088美元。每次调用按峰时无缓存输入及供应商最大393216输出token预留；总占用不得超过20美元。每篇最多10次，整批最多200次，串行，HTTP1200秒。新unknown保留预约并停止，只读查已有收据，不重发。模型输出仍经过同一校验，不把自审通过等同人工gold或发布验收。

本地修复与独立review证据见[numeric-date-fix.md](numeric-date-fix.md)，固定参数见[numeric-pro-package.json](numeric-pro-package.json)。实测已启动，最终统计待全部完成或命中停止条件后补齐。
