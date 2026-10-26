# B100 owner 字段只读诊断包 005

用户已批准本短设计的准备与原 R 复审；尚未授权远端执行。004 原封存和单次执行收据保持不变。

目标是解释 `owner_record_invalid_owner_identity` 的字段形状原因。固定 writer 的身份字段含 `state`、不含 `gid`；004 的六字段校验额外要求 `gid`。`driver_identity=null` 可合法存在，不能推导进程是否启动或回收。

## 精确候选

- runtime：`/Users/mentianlu/.codex/runtime/b100-post-count-recovery-005`
- manifest SHA：`b007cd2fd2fcff1bac3b64f9e17849faef82bfce820dbc0626810d20afdab649`
- commands SHA：`1f07128227f00248b7e923e75691b1eeff920bd6dd260fbb1b313eaf985501b8`
- seal SHA：`4121f45ccb7a9a1cde811f2fd3201a3b96d1f9eaf87a1b64b9f0e47db1b7ab1e`

## 观察边界

仅一次固定 SSH。先 fd 锚定读取固定 boot-id；匹配后打开固定 H/lock 根核对路径和权限，不枚举目录；仅读取 `lock/owner.json`。文件前后 stat、SHA 和 mode/owner/link/大小检查保留；boot 与 owner 共用 65,664 字节预算。owner 最大65,536字节，远端JSON输出最大16KiB。

只有 operation/thread/原始 count manifest 及 writer source SHA 全匹配，才输出四种固定 owner state 或 UNRECOGNIZED，以及 owner/driver 身份固定字段的缺失/null/类型/格式错误码。身份数值与任意未知字段/字符串不输出；writer 与004校验结果并列，不补造gid。null允许作为writer字段形状，但进程生命周期始终NOT_OBSERVED。

不读取其他记录、子目录、token或进程身份；不调用Docker、DB或抓取；不清理、不发信号给旧进程、不改锁/文件、不重跑count。观察timer20秒，最终非阻塞输出另限2秒；SSH客户端30秒。该预算不证明解释器启动耗时或断连后的远端终止。carrier若超时仅回收自己启动的SSH客户端组，不证明远端终止；任何unknown不重试。

## 本地验证

诊断逻辑采用合成JSON契约测试：先在最小拒绝实现上观察1项明确断言RED，再完成9项GREEN。初次全体stub运行中的失败/错误原件单独保留，不称为产品基线RED。测试只导入受`__main__`保护的纯诊断函数，没有执行候选entry/main、SSH或远端读取。静态AST、JSON、SHA、SSH argv内嵌payload与封存host脚本字节一致性检查通过。所有运行态和生产接受仍未证明。

## 复审与后续

交原R同一上下文仅静态只读复审；reviewer不得执行脚本/import/测试/SSH/Docker/生产探测，不修改文件。通过前不执行；若继续执行，需用户对最终精确manifest另外确认。后续清理或锁动作不属于本设计。

## 原 R 最终结论

`APPROVE_READ_ONLY_SOURCE_PACKAGE_ONLY`，P0/P1/P2/P3均0；原R在同一上下文核验seal12项、index11项、SSH payload与host源码字节绑定及carrier沿用004。未执行/import候选、测试或远端命令，未写文件。本结论只覆盖精确源码包，不证明当前owner字段、进程/锁终态、解释器启动或断连后的远端终止。source SHA比较仅核对记录内声明，不能独立认证当前写入进程。用户此次批准准备及复审；005的单次远端执行仍待对上述精确manifest另行授权，004保持停止。
