# C021 基线修复方向（待原 R 静态审核）

2026-10-05，Asia/Shanghai。范围为既有 C021 合成模板适配器；人工门禁引用根 `AGENTS.md`。原执行 `600e0903` 的 108 方法确实运行，但 80 error / 20 failure 阻断了 P2 目标验证，不能计为有效 P2 RED。

## 已核实的原因

- C 已在 `d3c1d106f308c9c66d773944441e0ac0200ec4ed` 最小修正 HTMLParser 的 `offset` 属性冲突及两项 meta reason，尚未执行新轮。
- 新 evidence schema 把既有 origin/raw 的 `corrected` 错写成 `correction`，participants 的 `normalized_status` 漏了既有 `dead_heat`。静态诊断必须递归 schema-valued `additionalProperties`；正确诊断有 10 个 case 的原件违反新 schema。不能改原件迁就 schema。
- 固定镜像 `sha256:ab8494e6202dced04a6c2b5b885b3d1f2d9c80776ec8ae8d97f3552aae6b3ecc` 内 Django 5.2.1 的 `DateFormat.D` 读取 `WEEKDAYS_ABBR`，zh_Hans `.mo` 将 Mon…Sun 翻译为星期一…星期日；适配器写成周一…周日。worker 明确断言 `LANGUAGE_CODE == 'zh-hans'`。这是固定源码差异证据，尚未取得修正后实际渲染证明，不能据此声称 12 个 calendar case 全部解决。
- 原 v3 的 25 个私有输入按 dict key/value 都计节点：最大 PrivateInput 为 14,760 节点、深度 8、canonical UTF-8 204,386 bytes；其 template_context 为 12,967 节点、深度 7、163,710 bytes。四个其他对象 context / expected_body / expected / anchor 最大分别 151 / 248 / 61 / 45 节点。当前统一 12,000 限制阻断既有 complete-nonleaf 样本，但合同的 HTML DOM nodes 上限并不是 PrivateInput 上限。

root 静态证据：`/Users/mentianlu/.codex/runtime/c021-root-django-locale-static-001/receipt.json` SHA `14ffc3320030db15b0c85332c1e817e39a9d5b542113ab69b4dba9c5a0a413d7`；从本地固定镜像导出并核对 config、全部七个 raw layer 与 rootfs diff_ids，六份 Django 文件 SHA 已绑定。`private-input-sizes.json` SHA `8ac77ea773d150d3d1ae040659d82e075d4d4d07821b3addadae663acb1ee3a4` 绑定完整 25 case 的原 v3 golden SHA。未导入 Django/业务模块、未渲染、未创建或启动容器。

## 下一包的具体方向

1. 新派生 evidence schema 精确对齐原件 `official|corrected` 和 `finished|disqualified|dead_heat`。保留旧 v1/v2/v3、原 raw/visible inputs 与失败运行原件，必要的 identity/DAG 重算单独派生；不能扩大来源/权限或掩盖原件差异。
2. 修复星期显示的方案及固定镜像来源一并列入包。后续最小代码修正只针对已经核实的七项翻译映射，不盲改其他日期规则或模板。实际 calendar 全量基线仍由新受控执行验证。
3. 提交独立 PrivateInput 预算草案：**16,384 key/value nodes、262,144 canonical UTF-8 bytes、depth 64**。它是固定信任配置，不能从调用方输入放宽；只作用于 private（含 template_context），其他四 DTO 既有 12,000 节点约束、HTML 七项、schema/envelope/evidence JSON 及展开预算均不变。说明逐节点/字节计量、递归/循环拒绝、超限 reason/priority、检查时序和拒绝前内存界；不得先无界深拷贝/序列化再检验。未知更大样本仍拒绝，不能以本补丁扩大完整业务范围。
4. 该预算是补齐合同缺项，不得伪称已获原合同批准。先形成精确合同、测试矩阵与固定可审提交给原 R；原 R 静态批准后才能修改适配器预算并生成新执行包。可准备 schema/locale 的最小 diff 与相应测试，但本轮不运行适配器、Django 或容器。
5. 新包至少证明枚举旧原件匹配且未知值拒绝；private 节点/字节/深度在 exact 与 +1 边界行为；HTML DOM 12,000 保持；源输入/额外四 DTO/展开上限不放宽。保留现有 108 方法分母及 114 HTML 修改目标；原新增三个 P2 方法/helpers 保持 AST，独立新增边界方法不混入原分母。
6. R 批准后按固定包申请新 root 资源窗口，先取全部既有正例通过、P2 目标真实失败的有效 RED；R01/R02 scalar/medal 修复继续在有效 RED 后实施，且 RED→GREEN 完整目标测试 bytes 相同。未清除基线失败时不能计 P2 RED 或关闭 finding。

本方向不授权新增真实请求、生产数据/配置/服务动作、native 全包运行、合并或发布。
