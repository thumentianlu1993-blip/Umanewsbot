# B016 私有路径与返回载体决策输入

2026-10-05，Asia/Shanghai。接续 B `43de074c` 与原 R `29a411cd` 的局部静态来源映射审核。现行 1MiB 合同继续有效，2MiB 候选禁用；本文只确定下一步静态计量输入。人工确认仍只按根 [AGENTS.md](../../../AGENTS.md)。

## 私有路径与 producer

ROOT 选定后续候选 Index 的确定性路径为 `artifacts/<64位小写内容SHA256>`，共74个ASCII字节；文件名64字节，符合固定 B 源码 `scripts/f02_native_primitives.py:355-358` 的既有路径语法。路径由已核完整原件字节的摘要产生，相同内容沿原去重规则仅一个路径；不同内容不得借碰撞或别名复用。此规则用于后续完整条目静态赋值与 canonical 实际计费，没有创建文件，没有扩大 parser 读取权限。path 仍不是任意文件读取命令。

这只解决路径选择，不证明 kind 或首个 producer。R 已定位 `cap-material-v2/build_material.py:189-193` 的明确 `cap_payload` 构造，可从冻结调用链继续补齐；完整静态来源链、参数与原件字节、实际 OpRef 以及更早 owner 排除，可以证明 firstness。新增 mint 日志不是唯一证据方式，OS 资格也不是静态分析的前提。`check_cap.graph()` 的首次遍历消费者与唯一 direct Step 引用均不得升级为首个 producer。

## 返回载体先解决物理通道和计量冲突

固定 B 的 `B-015-native-primitives-contract.md` 规定 stdout/stderr 合计8192字节、Receipt上限32768字节；`B-015-native-schema.md` 规定 N0 结束关闭3/4/5及对象 pidfd，最终 Receipt 通过保留 stdout 返回。源码 `resources()` 同时固定 `output_bytes=8192` 与 `receipt_bytes=32768`。因此完整 core、Receipt 与诊断输出的物理运输和计数关系需要明确，不能直接把2MiB core或24KiB见证投影放进现有 stdout 并豁免其费用。

ROOT 负责最终选型；B 当前卡 `B016-M04-M05-RETURN-TRANSPORT-CONSTRAINTS-001` 只提供精确来源锚点与一个最少改动候选。候选必须列清通道创建者、持有者、生命周期、全部编码字节和六类费用、输出上限适用面、错误/截断/超限/迟到拒绝，以及需要显式修订的旧条款。不能偷偷添加免费FD、共享目录、额外角色或新的加密/外部provider。

完整返回的认证仍依赖固定执行代码、镜像、出生与通道身份的真实资格，普通SHA或声明字段不提供认证。ROOT独立完整末字节接收观察必须在最终Index/Receipt之后产生，绑定完整返回与受信时钟域并计E，不回写先产Index形成摘要环。未发生实际发送时，M04实际发送账仍未产生；静态载体成本与M05时钟合同不冒充实际发送或资格实测。

收到固定候选后由ROOT决定技术修订范围，再交同原R独立审核；本卡不启动生成器、parser、协议、native或资源窗口，不关闭R01/R03。

## 10:34 候选收取与选择

ROOT已读 B `21bee629` 的完整单一方案及固定载体字段，选择“既有stdin传固定prepared输入、N0 stdout传协议、stderr传全包日志”的方向供原R静态审核。非N0 stdout需在固定出生代码内以`dup3(2,1,0)`转到日志端，并证明来源、继承别名和全部writer退出；不按现有共享stdout假定N0独占。原8KiB改为日志计数、协议另受六类总额、stdio预期file改pipe、Receipt只记N0局部日志、ROOT后产全包日志与独立接收时钟，均为候选需显式修订事项，没有变成现行合同。prepared早发后在core返回需照实际次数重复收费。

ROOT核出两处纯计数问题，已交原B最小更正：magic实际20字节，正确的外层93与encoded2190不变；来源索引实际5条，验证摘要不得写6。更正后交同原R在C包后审查。该选择不是执行批准，不证明2MiB容量、认证或时钟资格，也不新增FD编号、角色、资源或时间。M04实际发送账、M05实际受信载体仍缺。

计数更正已由 B `76eb48e3` 固定，ROOT核新7索引工件及报告共26712字节、旧v17七原件和三核心复制不变。两项计数问题已关闭，新候选已排同原R在当前C包后审核；未批准实施、启用或运行。

## 10:55 T01静态闭合与M02续接

B `b1e24963` 经原R `f702f669` 窄复审关闭T01候选输入缺口：只有实际继承protocol alias的受信child允许唯一2→1原子替换；已证继承log的后代保持原binding，失败/unknown不放行，47/12为上界。现行合同仍未修改，2MiB候选禁用；来源、时钟、实际发送账与成本R01/来源R03保持开放。

ROOT继续既有74ASCII路径选择，下一有限卡仅沿冻结源码和原件补M02真实首producer、kind与完整Index字段；第一消费者、唯一Step引用、内容同SHA均不单独证明firstness。此静态任务不启动载体实现或原件生成器，不将尚未发生的M04发送填成实际事实。
