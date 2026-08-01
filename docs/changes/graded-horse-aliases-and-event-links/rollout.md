# Rollout: 重赏导入马术语别名与赛事关联

## 发布前检查清单

- [ ] 代码已通过 review
- [ ] 用户已授权发布
- [ ] 生产 DB 已备份或处于可回滚状态
- [ ] 生产环境代码已更新到包含本次改动的版本

## 部署步骤

1. 将包含改动的分支部署到生产服务器。
2. 进入 server 目录，激活虚拟环境。
3. 运行别名命令（dry-run 预览）：
   ```bash
   python manage.py add_graded_horse_term_aliases --dry-run
   ```
4. 确认预览数字合理后，执行：
   ```bash
   python manage.py add_graded_horse_term_aliases
   ```
5. 运行赛事关联命令（dry-run 预览）：
   ```bash
   python manage.py link_graded_horse_race_records --dry-run
   ```
6. 确认预览数字合理后，执行：
   ```bash
   python manage.py link_graded_horse_race_records
   ```
7. （可选）如需重新导入全部马匹，运行：
   ```bash
   python manage.py import_graded_horses_to_profiles
   ```

## 验证命令

```bash
# 已添加别名的术语数
python manage.py shell -c "
from stable.models import TermEntry, TermType, TermAlias
terms = TermEntry.objects.filter(term_type=TermType.HORSE, source_ja__regex=r'\s+\([A-Z]{2,3}\)$')
print('conflict terms:', terms.count())
print('with base alias:', TermAlias.objects.filter(term__in=terms).values('term').distinct().count())
"

# 已关联赛事的记录数
python manage.py shell -c "
from stable.models import HorseRaceRecord
print('linked:', HorseRaceRecord.objects.filter(source_refs__has_key='theracingapi_race_id', event__isnull=False).count())
print('total:', HorseRaceRecord.objects.filter(source_refs__has_key='theracingapi_race_id').count())
"
```

## 回滚

- 别名：删除本次创建的 `TermAlias` 并清空对应 `TermEntry.aliases_ja` 中的基础名。由于命令幂等，可直接重新运行以恢复。
- 赛事关联：将 `HorseRaceRecord.event` 清空即可：
  ```bash
  python manage.py shell -c "
from stable.models import HorseRaceRecord
HorseRaceRecord.objects.filter(source_refs__has_key='theracingapi_race_id').update(event=None)
"
  ```

## 发布后观察

- 监控 `HorseRaceRecord.event` 关联比例。
- 抽样检查前端马匹详情页，确认赛事链接可点击且指向正确赛事。
- 观察文章自动链接命中率是否提升。
