# Tasks: 重赏导入马术语别名与赛事关联

## (application) 实现

- [x] 创建 `add_graded_horse_term_aliases` management command
- [x] 创建 `horse_race_record_event_matching` 服务与 `RaceEventMatcher`
- [x] 创建 `link_graded_horse_race_records` management command
- [x] 修改 `import_graded_horses_to_profiles` 在创建记录时同步尝试关联赛事
- [x] 编写自动化测试 `test_graded_horse_aliases_and_links.py`

## (integration) 验证

- [x] 本地运行新增测试，全部通过
- [x] 本地运行 `stable.tests.test_management_command` 回归测试
- [x] reviewer 复审判分页修复通过
- [x] 生产 dry-run 预览匹配率
- [x] 生产执行别名命令并复查计数
- [x] 生产执行赛事关联命令并复查计数
- [ ] 访问前端马匹详情页确认赛事链接出现

## (operations) 部署

- [x] 创建变更文档（spec/design/test_cases/tasks/rollout）
- [x] 通过独立 reviewer 审核
- [x] 用户授权发布
- [x] 部署到生产环境
- [x] 运行生产命令并记录证据
- [x] 更新 `docs/current_state.md` / `docs/project_status.md`
