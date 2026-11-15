#!/usr/bin/env python3
"""从既有 P04-1 JSONL 创建只读目录，并对已导出的赛事名称演练；无网络、无 DB 写入。"""
import argparse
from collections import Counter
import csv
import hashlib
import json
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from stable.services.hkjc_name_catalog import NameCatalog, context_key


def japanese_display_aliases(occurrences, jra_rows):
    """只复用上一轮已建立的同场/同马/同角色行引用，不重新靠姓名联表。"""
    rows = [json.loads(line) for line in jra_rows.read_text().splitlines()]
    aliases = {}
    for line in occurrences.read_text().splitlines():
        person = json.loads(line)
        kind = person['role']
        index = person.get('supplement_evidence_row')
        if (kind not in {'jockey', 'trainer'} or not isinstance(index, int)
                or person.get('native_match_basis') != 'same_date_unique_horse_available_pedigree_and_role'):
            continue
        row = rows[index]
        if row['date'] != person['date_hkjc']:
            raise ValueError('JRA occurrence date mismatch')
        name = row.get(kind + '_ja', '').strip()
        # 日文中的外籍人员缩写（如 C．ルメール）是显示别名，不冒充其当地原名。
        import unicodedata
        if not re.fullmatch(r'[A-ZＡ-Ｚ][.．]?\s*[ァ-ヺー・\s]+', name):
            continue
        if not unicodedata.normalize('NFKC', name).strip():
            continue
        aliases[kind, person['occurrence_id']] = {
            'name': name, 'source': row['ja_source'], 'jra_row': index,
            'occurrence_id': person['occurrence_id']}
    return aliases


def build(horses, people, occurrences=None, jra_rows=None):
    from opencc import OpenCC
    convert = OpenCC('t2s').convert
    entries = []
    inputs = {}
    extra = japanese_display_aliases(occurrences, jra_rows) if occurrences and jra_rows else {}
    if bool(occurrences) != bool(jra_rows):
        raise ValueError('people occurrences and JRA rows must be supplied together')
    for path in [occurrences, jra_rows]:
        if path:
            inputs[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path, is_horse in [(horses, True), (people, False)]:
        raw = path.read_bytes()
        inputs[path.name] = hashlib.sha256(raw).hexdigest()
        for line in raw.decode().splitlines():
            row = json.loads(line)
            kind = 'horse' if is_horse else row['role']
            raw_target = row.get('chinese_name_zh_hant', '').strip()
            target = re.sub(r'\s*\((?:a|-[0-9]+)\)\s*$', '', raw_target, flags=re.I)
            if kind not in {'horse', 'jockey', 'trainer'} or not target:
                continue
            if not is_horse and row.get('chinese_status') != 'official_complete':
                continue
            if any('\ue000' <= ch <= '\uf8ff' or ch == '\ufffd' for ch in target):
                continue  # 缓存中的缺字字形不能当作中文姓名发布。
            names = [row['registration_name'] if is_horse else row['latin_source_name']]
            if not row.get('native_ambiguity'):
                names.append(row['original_name'])
            # 原字段已是中文时，只允许回认目录实际收录的官方中文写法。
            names.extend([target, convert(target)])
            evidence = {}
            for occurrence_id in row.get('occurrence_ids', []) if not is_horse else []:
                alias = extra.get((kind, occurrence_id))
                if alias:
                    names.append(alias['name'])
                    evidence.setdefault(alias['name'], alias)
            entries.append({'id': row['name_record_id'], 'kind': kind,
                            'names': sorted({x.strip() for x in names if x and x.strip()}),
                            'target': convert(target), 'source_zh_hant': raw_target,
                            'source': row['source_url'], 'alias_evidence': list(evidence.values())})
    NameCatalog(entries)
    return {'schema': 'hkjc-name-display-v1', 'inputs_sha256': inputs, 'entries': entries}


def preview(catalog, race_csv, output):
    resolver = NameCatalog(catalog['entries'])
    counts, unique, examples = Counter(), {}, []
    contextual = {}
    with race_csv.open() as stream:
        rows = list(csv.DictReader(stream))
    with (output / 'matches.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        fields = ['row_type', 'id', 'event_id', 'country_region', 'year', 'visibility_status',
                  'kind', 'original', 'display', 'state', 'reason', 'evidence_ids', 'name_context']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            for kind in ['horse', 'jockey', 'trainer']:
                name = row[kind + '_name']
                if not name.strip():
                    counts[kind + ':empty'] += 1
                    continue
                key = (kind, name)
                if key not in unique:
                    unique[key] = resolver.match(name, kind)
                # 旧快照的 history.year 是父赛事年，不能拿来消歧历届冠军。
                identity = {'race_year': row.get('winner_year') if row['row_type'] == 'history' else row['year']}
                if kind == 'horse':
                    identity.update({field: row.get(field) for field in ('country', 'birth_year', 'age', 'sire', 'dam')})
                cache_key = (*key, context_key(identity))
                if cache_key not in contextual:
                    contextual[cache_key] = resolver.match(name, kind, identity)
                match = contextual[cache_key]
                counts[kind + ':' + match.state] += 1
                if row['visibility_status'] == 'published':
                    counts['published:' + kind + ':' + match.state] += 1
                result = {k: row[k] for k in fields[:6]}
                result.update(kind=kind, original=name, display=match.text, state=match.state,
                              reason=match.reason, evidence_ids='|'.join(match.evidence_ids),
                              name_context=json.dumps(dict(context_key(identity)), ensure_ascii=False))
                writer.writerow(result)
                if len(examples) < 30 and match.state == 'normalized' and name != match.text:
                    examples.append(result)
    summary = {'rows': len(rows), 'events': len({r['event_id'] for r in rows}),
               'input_sha256': hashlib.sha256(race_csv.read_bytes()).hexdigest(),
               'catalog_entries': dict(Counter(r['kind'] for r in catalog['entries'])),
               'occurrences': dict(sorted(counts.items())),
               'unique_names': dict(sorted(Counter(k[0] + ':' + m.state for k, m in unique.items()).items())),
               'examples': examples}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    with (output / 'unique-names.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['kind', 'original', 'display', 'state', 'reason', 'evidence_ids'])
        for (kind, raw), match in sorted(unique.items()):
            writer.writerow([kind, raw, match.text, match.state, match.reason, '|'.join(match.evidence_ids)])
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--horses', type=Path, required=True)
    parser.add_argument('--people', type=Path, required=True)
    parser.add_argument('--race-csv', type=Path)
    parser.add_argument('--people-occurrences', type=Path)
    parser.add_argument('--jra-rows', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    catalog = build(args.horses, args.people, args.people_occurrences, args.jra_rows)
    path = args.output / 'catalog.json'
    path.write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    (args.output / 'catalog.sha256').write_text(sha + '\n')
    result = {'catalog_sha256': sha, 'entries': len(catalog['entries'])}
    if args.race_csv:
        result.update(preview(catalog, args.race_csv, args.output))
        result.pop('examples')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
