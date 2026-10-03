# C010 / O02 交协调者的有界只读SQL设计（未执行）

2026-10-03 Asia/Shanghai。本线不连接生产。root先排除B独占窗口及冲突资源，重核固定运行身份；SQL交由root在既有只读连接执行并保留私有收据。下面使用public为预期schema，Q1先核真实schema；不一致则停止改SQL，不猜对象。所有查询不返回新闻/术语正文、原始键、用户数据或凭据。

## 会话与预算

采用专用连接、default_transaction_read_only=on，再BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY；每条statement_timeout=3s、lock_timeout=250ms、idle_in_transaction_session_timeout=5s；设置max_parallel_workers_per_gather=0、work_mem=4MB、temp_file_limit=16MB。事务成功/失败均ROLLBACK并关闭连接。root工具调用总预算45s，任何超时立即终止此批，不自动重试扫描或放宽限制。不得交互暂停在开放snapshot中。此配置只适用于本会话；不修改服务器全局配置。

第一批只Q1–Q4四SELECT，最大执行12s，期望输出不超过100条schema元数据；不足证据或出错停下。Q5–Q7三个heap汇总另批，经root资源核定，最大9s；可能全表扫描但受CPU/时间/temp预算约束，LIMIT不被当扫描预算。统计超时记unknown。索引健康扩展检查/REINDEX/ANALYZE不在此请求。

```sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '3s';
SET LOCAL lock_timeout = '250ms';
SET LOCAL idle_in_transaction_session_timeout = '5s';
SET LOCAL max_parallel_workers_per_gather = 0;
SET LOCAL work_mem = '4MB';
SET LOCAL temp_file_limit = '16MB';
```

## Q1：运行数据库与精确表身份/大小

单条SELECT输出不含database名称/用户/host，只含版本与collation信息、目标表schema及规模。

```sql
SELECT current_setting('server_version') AS server_version,
       current_setting('server_encoding') AS encoding,
       d.datlocprovider, d.datcollate, d.datctype, d.daticulocale,
       d.datcollversion,
       pg_database_collation_actual_version(d.oid) AS actual_collversion,
       n.nspname AS schema_name, c.relname, c.reltuples::bigint AS estimated_rows,
       pg_relation_size(c.oid) AS heap_bytes,
       pg_total_relation_size(c.oid) AS total_bytes
FROM pg_database d
CROSS JOIN pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE d.datname=current_database()
  AND c.relkind IN ('r','p')
  AND c.relname IN ('stable_newsarticle','stable_termcandidate')
ORDER BY n.nspname,c.relname;
```

## Q2：两处约束/索引完整定义与标志

```sql
SELECT n.nspname, t.relname, con.conname, con.contype,
       con.convalidated, con.condeferrable, con.condeferred,
       pg_get_constraintdef(con.oid) AS constraint_definition,
       i.indisunique, i.indisvalid, i.indisready, i.indislive,
       i.indkey::text, i.indcollation::text, i.indclass::text,
       pg_get_indexdef(i.indexrelid) AS index_definition
FROM pg_constraint con
JOIN pg_class t ON t.oid=con.conrelid
JOIN pg_namespace n ON n.oid=t.relnamespace
LEFT JOIN pg_index i ON i.indexrelid=con.conindid
WHERE con.conname IN ('uq_article_source_article_id','uq_term_candidate_type_normalized')
ORDER BY n.nspname,t.relname,con.conname;
```

## Q3：键列collation声明/实际provider版本

包括default collation的列记录，并与Q1实际database规则共同解释，不能只核一个ICU是否存在。

```sql
SELECT n.nspname, t.relname, a.attname,
       format_type(a.atttypid,a.atttypmod) AS column_type,
       a.attnotnull, cn.nspname AS collation_schema,
       co.collname, co.collprovider, co.collisdeterministic,
       co.collcollate, co.collctype, co.colliculocale, co.collversion,
       pg_collation_actual_version(co.oid) AS actual_collversion
FROM pg_attribute a
JOIN pg_class t ON t.oid=a.attrelid
JOIN pg_namespace n ON n.oid=t.relnamespace
LEFT JOIN pg_collation co ON co.oid=a.attcollation
LEFT JOIN pg_namespace cn ON cn.oid=co.collnamespace
WHERE n.nspname='public' AND a.attnum>0 AND NOT a.attisdropped
  AND ((t.relname='stable_newsarticle' AND a.attname IN ('source_site','source_article_id'))
    OR (t.relname='stable_termcandidate' AND a.attname IN ('term_type','source_language','normalized_key')))
ORDER BY t.relname,a.attnum;
```

Q2若索引indcollation不同列默认规则，第二轮必须另按该OID取完整collation记录；列结果不能替代索引相等规则。

## Q4：实际全部入站FK（所有schema，包含复合键）

输出定义/列号以便下一轮生成逐关系有界引用计数；最多100行的预算若超过则不截断宣称完备，改私有完整元数据收据。

```sql
SELECT sn.nspname AS source_schema, sc.relname AS source_table,
       con.conname, con.conkey::text AS source_columns,
       tn.nspname AS target_schema, tc.relname AS target_table,
       con.confkey::text AS target_columns,
       con.convalidated, con.confdeltype, con.confupdtype,
       pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class sc ON sc.oid=con.conrelid
JOIN pg_namespace sn ON sn.oid=sc.relnamespace
JOIN pg_class tc ON tc.oid=con.confrelid
JOIN pg_namespace tn ON tn.oid=tc.relnamespace
WHERE con.contype='f' AND tn.nspname='public'
  AND tc.relname IN ('stable_newsarticle','stable_termcandidate')
ORDER BY sn.nspname,sc.relname,con.conname;
```

第一批完毕ROLLBACK。汇总第二批开启同样新只读事务，并强制heap与sort聚合避免已知unique索引或优化器unique假设隐藏重复；必须保存对应EXPLAIN（不ANALYZE）计划确认Seq Scan/并行禁用，不满足则停。两表约束本来NOT NULL；若Q3发现非预期schema先停。

```sql
SET LOCAL enable_indexscan = off;
SET LOCAL enable_indexonlyscan = off;
SET LOCAL enable_bitmapscan = off;
SET LOCAL enable_hashagg = off;
```

## Q5：新闻byte完全相同键组汇总

不输出原始键/ID列表；byte等价不是业务归一化/大小写处理。cte materialized禁止group查询直接借父表unique索引假设，扫描计划仍需确认。

```sql
WITH heap AS MATERIALIZED (
  SELECT convert_to(source_site,'UTF8') AS k1,
         convert_to(source_article_id,'UTF8') AS k2
  FROM public.stable_newsarticle
), groups AS (
  SELECT count(*) AS n FROM heap GROUP BY k1,k2 HAVING count(*)>1
)
SELECT count(*) AS duplicate_groups,
       coalesce(sum(n),0) AS rows_in_duplicate_groups,
       coalesce(sum(n-1),0) AS excess_rows,
       coalesce(max(n),0) AS max_group_rows FROM groups;
```

## Q6：术语byte完全相同键组汇总

```sql
WITH heap AS MATERIALIZED (
  SELECT convert_to(term_type,'UTF8') AS k1,
         convert_to(source_language,'UTF8') AS k2,
         convert_to(normalized_key,'UTF8') AS k3
  FROM public.stable_termcandidate
), groups AS (
  SELECT count(*) AS n FROM heap GROUP BY k1,k2,k3 HAVING count(*)>1
)
SELECT count(*) AS duplicate_groups,
       coalesce(sum(n),0) AS rows_in_duplicate_groups,
       coalesce(sum(n-1),0) AS excess_rows,
       coalesce(max(n),0) AS max_group_rows FROM groups;
```

## Q7：已知新闻报错键的heap只读复核

两个%s仅为psycopg参数占位符，参数由root从私有错误收据获取，不shell插值、不写文件或显示。原列相等运算按其collation定义；若Q2发现索引使用另一collation，此统计不称索引相等统计。byte汇总与本查询需要分开标注，不能互相替代。

```sql
SELECT count(*) AS matching_heap_rows
FROM public.stable_newsarticle
WHERE source_site=%s AND source_article_id=%s;
ROLLBACK;
```

## 第二轮待第一批事实生成（本次不执行）

逐索引collation/OID元数据；两表原业务相等规则分组与byte组对照；私有候选ID/字段digest及差异布尔（正文不回传）；每个真实FK关系的目标ID集合计数与重指后的unique碰撞数；JSON/审计/公开URL等非FK业务引用范围。root每条仍设3s，按表拆批及硬期限，不自动递归扫描全库。完整ID与内容仅保留服务器私有收据，线程只接收摘要、digest和未闭合项。

Q1–Q7是诊断设计，尚无数据库执行或语法验证结果，不可写为测试PASS或当前健康证明。
