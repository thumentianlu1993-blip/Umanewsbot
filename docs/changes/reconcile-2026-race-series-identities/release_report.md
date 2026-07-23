# 发布报告：2026 赛事系列身份只读审核工具与正式审核包

## 发布边界

- 本次授权仅包含提交、推送、部署只读审核工具和生成正式生产审核包。
- 未授权、未执行系列归并、field repairs、prepare/apply/commit 或其他生产业务数据写入。
- 人工定稿工作簿不构成后续数据写入授权。

## 版本与部署

- approved parent：`d64c69264df8bf16389e99514fb4ab553ca3f37b`
- 行为代码审核 content manifest：`943431514ffa8b814fc2076eb40ad96ddc5d25a6b1896cd81b1e9a7504bacdd2`
- 行为代码审核 fingerprint：`db9d0f9b00cad1f1fbfcc784837fc54210e78bc7e7a292b0b720cd85f23c1c85`
- 代码批准后的文档增量审核 content manifest：
  `d513dd8cd61031013d3e365b23c2af655d6b3a802ae20bf48c0c793104855d53`
- 最终发布冻结 fingerprint（含上述文档增量）：
  `2062b52e452fdecafacb10ae572dd27a26cddf751a56145532323b50a542f4c6`
- 发布提交：`17d7757aec764755394339400eb2523eae896fa5`
- 生产部署前 HEAD：`15645b054ff1c4057b1463d3382892cbe4c68106`
- 生产部署后 HEAD：`17d7757aec764755394339400eb2523eae896fa5`
- web/worker 镜像：`sha256:5a3dd28b846954837ade517e5d85aa2bba3b4651d322876f950f0cdfcda45e44`
- migration：无；Django check、命令 help、HTTP `/healthz/` 通过。

## 正式只读快照

- 快照时间：`2026-07-23T02:44:23.655795+00:00`
- 总 target：1,085
- 已关联：684
- 唯一名称匹配但系列不同：226
- 同名多候选：11
- 无名称匹配：162
- 未举办：2
- 异常：0
- `blocks_decisions=false`
- canonical rows SHA-256：`409dde2ff311b4a0e640541c033dd82a7f232b17267818aa8a022e989fe2f2e9`

正式五分类计数与探索基线一致，按当前计数门禁没有触发重新确认。但当前未记录 target/candidate
identity-set digest，不能据此排除候选集合发生等量替换；这项限制保留为已知非阻塞后续建议。

## 审核包

生产主机持久化目录：
`runtime/race_series_identity_review/formal-20260723T104700+0800/`

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| `manifest.json` | 970 | `9d0df5da1e942f77bbabe9df7c84a921ea9325564ce821ab5f17ebf2f13eee47` |
| `review.csv` | 320011 | `afa06b10cb1d3a7ade13e95f6d18385379a2813458fe61f34ce98440770be1cf` |
| `review.json` | 722827 | `951ef701c21f994de1f584530b8cca2eec9ae7b1a3f3858aaf5ddc59d447b0aa` |
| `review.xlsx` | 166837 | `c4e09f8bc0d5a5dc912d6b57efb79173d69f9fb70ce057a9d9f6a1526d30c80b` |
| `snapshot.json` | 2542679 | `1073fa0bbaf6a2b3e3dfa1217fe1afe0b01a80796e47552a182524b0d27ae98a` |

容器内 `/app/runtime` 未挂载，因此导出成功后立即用 `docker cp` 将同一目录持久化到生产主机。
五个脱敏文件随后复制到本地，逐文件 SHA 与生产记录一致。六张工作表全部实际导入并渲染，公式
错误扫描匹配 0 项；工作簿结构、首屏可读性和异常空表均符合预期。

## 下一门禁

1. 用户审核完整未关联总账，优先定稿“唯一名称匹配”表的 `decision` 与 `review_note`。
2. 以原始 manifest 为信任根回读定稿工作簿，生成 decisions 和空 field repairs。
3. 运行既有 prepare 与 prepared verifier，数据库仍保持零写入。
4. 对精确 decisions/manifest 完成同一 reviewer 限定复审。
5. 用户对精确数据批次另行授权后，才允许备份和生产 apply。
