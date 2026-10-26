# B100 计数后现场核验包 004

状态：修订候选，等待原 R 只读复审；不含现场执行授权。用户授权仅为准备只读恢复包并交原 R 审核。本轮未执行候选脚本、测试、SSH、Docker或生产读取。

## 固定绑定

- 原 B100 manifest：`8ed1d55bb73b6fa680637f8769f8e037113717f32d739fccf42b033203221325`
- 原 B100 commands：`e15ca35a300f65447062d921cf0043854aec0752d9bc0f7d353709ecc19380d2`
- 原 count summary：`7189c774c154ce5975f38edc5c8a73be9db8eea13aea1f40ffb94f4d9f3b1064`
- 新 manifest SHA-256：`bb3915adb4bfe7970d30e55d71a1e1b7d4cf82e5893751051c14e0b6639fe9e6`
- 新 commands SHA-256：`7cac33401d8bb767f7204584082d4129eeff40504de88a1ab0bde4802582d1f6`
- host-inspect.py SHA-256：`a3288c9b85027571d120644f31d43765013d81d8e20f9bd5e023c5b59829c3d4`
- run-once.py SHA-256：`96015ec0c4e7fb5e03b8d839056f41602269c260d3a338dfa88022d5c683b452`

## 对 003 复审 findings 的处理

003 原件保留。004先验证并读取锁目录的owner.json，完成operation/thread/manifest与owner/driver身份格式绑定；只有校验通过才继续打开H子目录、枚举目录或读其他固定文件。后续每个identity-bearing JSON在下一个文件I/O前完成解析、绑定、字段类型检查与白名单投影。`owner.final`/`owner.recovery`的解析状态单独为`projection_state`，源业务状态输出在`owner_state`，不相互覆盖。owner身份/state字段缺失、类型错误或非法状态即停；出现的可选布尔字段也严格校验。

`ReadBudget`在读取boot id之前创建并由所有固定文件及最多四个`/proc/stat`读取共享，累计硬上限256KiB；每次`os.read`的大小先受单文件剩余量和总预算剩余量共同限制。达到目录项上限即停止，不请求下一项。

远端20秒观察timer只在确需终止仍存活的自有Docker客户端期间暂停，清理宽限最多1.5秒，然后恢复同一个绝对观察截止时间；正常Docker返回后timer保持有效直至快照完成。正常结果与STOP结果均通过非阻塞fd写出，最终输出阶段限2秒；不得用Python stdout缓冲写入，无法完成时直接有限退出。上限为20秒观察 + 最多1.5秒自有客户端teardown + 2秒输出，共23.5秒。SSH客户端仍有30秒硬超时，但其断开不证明远端已终止。

## 精确范围

单次固定SSH host snapshot：比较固定boot id；打开H/lock根后优先验证owner；逐层fd锚定/`O_NOFOLLOW`检查固定路径；有界读取固定文件摘要和白名单字段；最多4个精确PID身份；最后至多一次固定CID Docker inspect。**无docker exec，容器BASE明确`NOT_OBSERVED`**。不读DB、业务数据、日志、token内容、cmdline、环境、cwd、exe、mounts或labels；不清理、发信号、修改锁/文件、重跑count或抓取。

SSH客户端30秒，stdout32KiB、stderr4KiB；Docker inspect5秒；每文件64KiB、同一总读取256KiB（包含boot及proc stat）、目录总计160项/每目录128项、远端JSON32KiB。所有unknown/unsafe/超限均fail-closed且不重试。Docker daemon侧请求终止、当前现场、容器BASE与镜像内容均未证明。

## 静态验证

仅完成Python AST解析、JSON/SHA封存核对、SSH base64 payload与host脚本逐字节比较。没有导入/执行候选、测试、模拟、SSH、Docker或生产读取；execution_authorized=false。旧001/002/003封存和报告不修改。原R复审完成后，精确只读命令仍须另行用户批准。
