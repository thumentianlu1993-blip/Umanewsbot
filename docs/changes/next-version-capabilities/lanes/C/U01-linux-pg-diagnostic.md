# C-003 / U01 固定 Linux/PG16 短验证

日期：2026-10-03（Asia/Shanghai）。原R已批准行为`2b9398f756507c5e58deb7f534d0d2b624850ae4`并关闭C003-P2-01；共享精确映射`c9c798ac6190c1ad3f6ed8abb804b453641bc507`已受审，本线cherry-pick成`4c11df4ba9899efb64d544e14246eabd13dfb1c8`。本报告仅短诊断；完整回归由协调者统一安排。

## 固定输入与策略

交付base：`907f8de699b31a6fcc80acc78e9ba070aadc4f28`。集成test SHA：`4c11df4ba9899efb64d544e14246eabd13dfb1c8`。原真实RED SHA：`5c66088d821c249e41141dd5f8ba062c3edaf210`。

正式影响计划生成成功，无unknown：full、246 domains、293 labels；plan digest `8745a9fd93504ace9d34f99f0723f4f551a1f0d7250c10eedd24dc6096069e2d`。标签数量不是实际测试数量；未执行此full计划。

短计划明确标`diagnostic_only=true`，RED仅原缺陷单例，GREEN仅两个已登记展示测试模块，collection准确39项/1批；均不超过200项。没有缩交付base、修改策略或免除必要full。

## 隔离环境

独立DOCKER_CONFIG：`/Users/mentianlu/.codex/runtime/c003-impact-docker`，只连接本地专用Colima unix socket，未改全局context、未设置DOCKER_HOST/DOCKER_CONTEXT。独立TMPDIR：`/Users/mentianlu/.codex/runtime/c003-impact-temp`。

固定immutable image：`sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905`，从候选Dockerfile/requirements缓存构建。runner按固定Git archive、只读源码、非root、network none执行。实际版本：PostgreSQL16.15（Ubuntu16.15-0ubuntu0.24.04.1，aarch64）、Python3.12.3、Django5.2.1、Linux6.8.0-100-generic/glibc2.39。

两批隔离探针均仅lo，外部Python/curl请求blocked，nested Docker daemon blocked。开始时误写`--batch django-001`被runner“no selected batches”拒绝，无容器启动；读取collection实际key为`batch-000`后修正，未盲重试。

## 结果

- 原RED：1项、两flag子例均真实`1 not found in []`，0error/0skip，lifecycle complete、exit1，7.4466秒；缺陷而非基础设施失败。
- GREEN：39项、0failure/0error/0skip，lifecycle complete、exit0，8.7998秒。
- 198合成输入（33+144+4+17）在原生PG表达式与Python解析之间代码相等，三个等级家族集合相等；案例期望、业务字段未变均通过。测试显式assert能力探测为真，证明此隔离实例存在UTF8/NFKC/und-x-icu。单次投影数据查询为1，首次连接能力探测独立多1次。
- 分页前等级筛选、历史重点、本周焦点两路径、事件两展示flag、冲突/地方体系/JRA来源身份和目录名后缀，以及公开关联马匹记录G2/隐藏关联G3、无隐式关联查询/GET无DML回归通过。

以上证明198个已定义输入及现有完整等级语法组合，不宣称所有Unicode版本或真实生产数据已验收。生产仅PG binary16.14由协调者读过，实际服务encoding/normalize/ICU尚未读取，不标目标兼容。

## 可复核产物与命令

产物目录：`/Users/mentianlu/.codex/runtime/c003-impact-evidence/`。

- `formal-plan-4c11.json`：正式策略计划（未执行）。
- `red-focused-diagnostic-plan.json`、`red-5c660/execution-plan.json`及`batch-000.json/log`。
- `green-focused-4c11.json`、`green-4c11/execution-plan.json`及`batch-000.json/log`、`image-build.log`。
- RED receipt SHA256：`ba91f4b8b4ba4efd11d22091899970870b4238aafec1a8d0f0a6702c06f74c7b`。
- GREEN receipt SHA256：`8db64b35964cdd8fa15d90ebb42ef11b6b29e3db3b50c23a412527f5ec0e7834`。

```sh
python3 scripts/plan_affected_tests.py --base 907f8de699b31a6fcc80acc78e9ba070aadc4f28 --head 4c11df4ba9899efb64d544e14246eabd13dfb1c8 --output /Users/mentianlu/.codex/runtime/c003-impact-evidence/formal-plan-4c11.json
```

执行runner均前缀`env -u DOCKER_CONTEXT -u DOCKER_HOST DOCKER_CONFIG=/Users/mentianlu/.codex/runtime/c003-impact-docker TMPDIR=/Users/mentianlu/.codex/runtime/c003-impact-temp`：先GREEN focused `--build --collect-only --image umanews-c003-short:4c11`，再固定image ID执行GREEN收集计划的`--batch batch-000`及原RED focused计划。计划与日志保留完整实际参数/固定树。

完成后`docker ps`为空，无在途容器或batch，资源已回报协调者释放。不继续启动full、生产探测或部署。本报告新增不改变受测行为字节；提交后最终文档head由交接消息绑定。
