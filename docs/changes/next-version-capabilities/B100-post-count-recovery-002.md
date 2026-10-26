# B100 计数后现场核验包 002

状态：修订候选，等待原 R 只读复审；**不含现场执行授权**。用户批准范围仅为准备修订包并交原 R 审核。本次未运行 carrier、SSH、Docker、远端脚本或生产读取。

## 固定绑定

- 原 B100 manifest：`8ed1d55bb73b6fa680637f8769f8e037113717f32d739fccf42b033203221325`
- 原 B100 commands：`e15ca35a300f65447062d921cf0043854aec0752d9bc0f7d353709ecc19380d2`
- 原 count summary：`7189c774c154ce5975f38edc5c8a73be9db8eea13aea1f40ffb94f4d9f3b1064`
- 新 manifest SHA-256：`823c6eb896fd6a6a91d5fa3909385b1a44cc6dcf47a5ebdc6e19f0ce846f9904`
- 新 commands SHA-256：`6f1563f624a4d36071a3de1a9c5731c3a05dcc996e1f0f8c3f086c1a3cc7ff85`
- host-inspect.py SHA-256：`fd3fb008b5a84c99571c8f71abfb9feded205c2e64d8f3b5556a3d39729674a6`
- run-once.py SHA-256：`bab10680ceb3b66800541f30ba008d4e551b0a7609173fa8d272285bdaf476cf`

## 修订内容

001 因原 R `REVISE` 结论保留不动；002 为新的封存对象。002 删除所有容器内 `exec`，因此容器 BASE 明确为 `NOT_OBSERVED`。唯一远端步骤是固定 SSH 命令：先核对固定 boot id，再用目录 fd 与 `O_NOFOLLOW` 逐层访问固定路径，读取有界的一层目录项、固定白名单文件摘要、绑定记录白名单字段及最多四个精确 PID 的最小身份；之后至多执行一次固定 CID 的 Docker inspect。没有清理、信号、锁修改、重跑 count、SQL 或业务数据读取。

对原 R findings 的处理：

- 容器 payload 不再放在另一层 transport 中；实际 SSH payload 字节与封存的 host-inspect.py 完全一致，并由 carrier、commands 与 manifest SHA 绑定。
- 固定路径逐层打开目录 fd，所有组件用 `O_NOFOLLOW`；一层枚举通过 `scandir(fd)` 增量读取并受每目录与全局条目上限约束。
- owner/recovery JSON 先核 operation/thread/manifest 或完整 owner/driver 身份绑定，再输出仅白名单字段；嵌套身份字段限制为精确整数/数字字符串，状态和 digest 格式受限。
- 文件读取按实际读到的字节逐块计入总预算；stdout/stderr按流有界消费，不以事后 `communicate()` 作为上限。remote script 有20秒自限时；Docker 客户端最长5秒并仅终止本地自有进程组。此终止不声称 Docker daemon 一侧观察请求已经结束。
- carrier 的异常分类不捕获并吞掉成功退出的 `SystemExit`；所有不确定状态停止且不重试。

## 精确边界与限制

运行 carrier 必须在之后由用户另行批准精确 manifest SHA；当前 `execution_authorized=false`。SSH连接最多一次、无自动重试，客户端30秒，stdout 32 KiB、stderr 4 KiB。远端快照 JSON 32 KiB、总读取 256 KiB、单文件 64 KiB、目录总计160项且每目录128项。内容不满足绑定/元数据限制时返回 unknown 或停止。容器镜像/Base 内容、当前现场与锁状态仍为 `NOT_OBSERVED`；本包无法证明 daemon 侧超时后请求已消失。

## 静态验证

仅完成 host-inspect.py 与 run-once.py 的 Python AST 解析、JSON/命令结构检查及 SSH base64 payload 与封存脚本逐字节相等检查。没有 import/exec、单元测试、生产读取或网络连接。旧包001仍保留原路径与 SHA，状态由本候选 supersede；待原 R 审核后，再依根 AGENTS.md 对精确只读命令另行向用户确认。
