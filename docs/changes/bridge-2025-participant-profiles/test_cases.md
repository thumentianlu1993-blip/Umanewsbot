# 测试用例

1. 同一 source artifact 与参数生成稳定批次顺序、连续 rank 和逐文件 SHA。
2. 非实际起跑、identity conflict、缺来源 URL、多地区身份候选进入 exclusions，不进入补全 CSV。
3. v2 manifest 可接受单地区 1..100 行，不要求五地区各十匹。
4. source artifact SHA、大小、路径、candidate key、马名、来源、地区或 actual-start 证据漂移均拒绝。
5. v2 地区计数、rank、总量或未知地区不一致均拒绝。
6. 既有无 v2 contract 的 50 行 loader 测试保持通过。
