# 年度 `other` 赛事地区清单

当 UmaFans 比赛页只显示“其他”时，可通过仓库内 regular JSON 文件按完整 canonical race URL
指定地区。禁止 symlink、工作树外路径、重复 URL 和模糊匹配。

```json
{
  "schema_version": 1,
  "year": 2025,
  "classification_complete": false,
  "races": [
    {
      "url": "http://umafans.run/races/2025/example/",
      "region": "middle_east",
      "country": "united_arab_emirates",
      "evidence": "reviewed UmaFans RaceEvent identity"
    }
  ]
}
```

`region` 只接受 `australia`、`germany`、`middle_east`、`out_of_scope`。中东国家只接受
`united_arab_emirates`、`saudi_arabia`、`qatar`、`bahrain`。

只有人工确认清单 exact 覆盖该年度 sitemap 中全部“其他”赛事 URL 后，才可设置
`classification_complete=true`。缺失或多出任一 URL 都会 fail closed；不完整清单只报告
`classification_incomplete`，不得据此声称新地区没有公开范围内赛事。赛事地区清单不构成
马匹 profile identity 证据。

URL 的 scheme 是 exact identity 的一部分，必须与生成该年度 sitemap 的 base origin 一致。
当前正式 workflow 使用 HTTP，因此新清单必须记录 `http://umafans.run/...`；不得把旧 HTTPS
URL 直接用于 HTTP run，也不得在 resume 时改写清单 URL。
