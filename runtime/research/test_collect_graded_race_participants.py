from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from graded_participants.checkpoint import CheckpointStore, run_checkpointed
from graded_participants.collector import Collector
from graded_participants.core import (
    ParticipantRow, classify_region, grade_is_in_scope, infer_names,
    keys_sha256, normalize_result_status, stable_shard,
)
from graded_participants.pipeline import parse_args


class FakeResponse:
    def __init__(self, url: str, content: bytes, status_code: int = 200):
        self.url = url; self.content = content; self.status_code = status_code; self.headers = {}
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(self.status_code)


class FakeClient:
    def __init__(self, pages: dict[str, bytes]): self.pages = pages; self.request_count = 0
    def get(self, url: str, *, params=None): self.request_count += 1; return FakeResponse(url, self.pages[url])


RACE_HTML = '''
<main class="race-page">
  <div class="race-hero-meta-text">澳大利亚 · Flemington</div>
  <div class="race-hero-name">测试锦标</div>
  <div class="race-hero-original">Test Stakes · 2025-03-01</div>
  <div id="overview"><div class="race-meta-grid">
    <div><span>马场</span><b>Flemington</b></div><div><span>等级</span><b>G1</b></div>
    <div><span>日期</span><b>2025-03-01</b></div><div><span>状态</span><b>已结束</b></div>
  </div></div>
  <section id="results"><table><tbody>
    <tr><td>1</td><td>1</td><td>Alpha</td><td>J1</td><td>T1</td><td>1:30</td><td>-</td><td>2.0 / 1</td></tr>
    <tr><td>2</td><td>2</td><td>Bravo</td><td>J2</td><td>T2</td><td>1:31</td><td>1</td><td>3.0 / 2</td></tr>
    <tr><td>PU</td><td>3</td><td>Charlie</td><td>J3</td><td>T3</td><td>-</td><td>-</td><td>4.0 / 3</td></tr>
    <tr><td>SCR</td><td>4</td><td>Delta</td><td>J4</td><td>T4</td><td>-</td><td>-</td><td>-</td></tr>
    <tr><td>5</td><td>5</td><td>Echo</td><td>J5</td><td>T5</td><td>1:35</td><td>5</td><td>8.0 / 5</td></tr>
    <tr><td>DSQ</td><td>6</td><td>Foxtrot</td><td>J6</td><td>T6</td><td>-</td><td>-</td><td>9.0 / 6</td></tr>
    <tr><td>NR</td><td>7</td><td>Golf</td><td>J7</td><td>T7</td><td>-</td><td>-</td><td>-</td></tr>
  </tbody></table></section>
</main>'''.encode()


class Tests(unittest.TestCase):
    def test_result_statuses(self):
        self.assertEqual(normalize_result_status('3'), (3, 'finished', True))
        self.assertEqual(normalize_result_status('PU'), (None, 'pulled_up', True))
        self.assertEqual(normalize_result_status('DSQ'), (None, 'disqualified', True))
        self.assertEqual(normalize_result_status('SCR'), (None, 'scratched', False))
        self.assertEqual(normalize_result_status('NR'), (None, 'non_runner', False))

    def test_new_regions(self):
        empty = {'labels': {}, 'racecourses': {}, 'urls': {}}
        self.assertEqual(classify_region(label='澳大利亚', racecourse='', race_name_original='', url='https://umafans.run/x', overrides=empty), 'australia')
        self.assertEqual(classify_region(label='德国', racecourse='', race_name_original='', url='https://umafans.run/x', overrides=empty), 'germany')
        self.assertEqual(classify_region(label='阿联酋', racecourse='', race_name_original='', url='https://umafans.run/x', overrides=empty), 'middle_east')

    def test_other_region_hint_and_override(self):
        empty = {'labels': {}, 'racecourses': {}, 'urls': {}}
        self.assertEqual(classify_region(label='其他', racecourse='Meydan', race_name_original='Dubai Turf', url='https://umafans.run/x', overrides=empty), 'middle_east')
        override = {'labels': {}, 'racecourses': {}, 'urls': {'https://umafans.run/x': 'germany'}}
        self.assertEqual(classify_region(label='其他', racecourse='Meydan', race_name_original='', url='https://umafans.run/x', overrides=override), 'germany')

    def test_grade_scope(self):
        self.assertTrue(grade_is_in_scope('japan', 'Jpn1'))
        self.assertTrue(grade_is_in_scope('australia', 'Group 2'))
        self.assertFalse(grade_is_in_scope('germany', 'Listed'))

    def test_names(self):
        self.assertEqual(infer_names({'浪漫勇士'}, 'ROMANTIC WARRIOR (IRE)'), ('浪漫勇士', '', 'ROMANTIC WARRIOR'))
        self.assertEqual(infer_names({'イクイノックス'}, 'イクイノックス'), ('', 'イクイノックス', ''))

    def test_parse_all_starters(self):
        url = 'https://umafans.run/races/2025/test/'
        service = Collector(base_url='https://umafans.run', client=FakeClient({url: RACE_HTML}),
                            year=2025, cutoff=date(2025, 12, 31),
                            region_overrides={'labels': {}, 'racecourses': {}, 'urls': {}})
        record = service.parse_race_page(url)
        self.assertTrue(record['included']); self.assertEqual(len(record['rows']), 5)
        self.assertEqual([row['horse_display_name'] for row in record['rows']], ['Alpha', 'Bravo', 'Charlie', 'Echo', 'Foxtrot'])
        self.assertEqual(record['rows'][2]['result_status'], 'pulled_up')

    def test_year_dynamic(self):
        url = 'https://umafans.run/races/2025/test/'
        service = Collector(base_url='https://umafans.run', client=FakeClient({url: RACE_HTML}),
                            year=2024, cutoff=date(2024, 12, 31),
                            region_overrides={'labels': {}, 'racecourses': {}, 'urls': {}})
        self.assertEqual(service.parse_race_page(url)['skip_reason'], 'date_out_of_scope')

    def test_no_wikipedia_fields(self):
        fields = set(ParticipantRow.__dataclass_fields__)
        self.assertFalse(any('wikipedia' in field or 'wikidata' in field for field in fields))

    def test_checkpoint_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            keys = ['a', 'b', 'c']; calls = []
            store = CheckpointStore(Path(tmp), stage='sample', manifest_sha256='x' * 64,
                                    shard_index=0, shard_count=1, input_keys_sha256=keys_sha256(keys))
            kwargs = dict(store=store, resume=True, start_index=0, limit=0,
                          time_budget_seconds=0, checkpoint_every=1)
            run_checkpointed(keys, process=lambda key: calls.append(key) or {'status': 'success'}, **kwargs)
            run_checkpointed(keys, process=lambda key: calls.append(key) or {'status': 'success'}, **kwargs)
            self.assertEqual(calls, keys)

    def test_stable_shards(self):
        keys = [f'horse-{i}' for i in range(100)]
        self.assertEqual({k: stable_shard(k, 4) for k in keys}, {k: stable_shard(k, 4) for k in reversed(keys)})

    def test_args_single_year(self):
        args = parse_args(['--stage', 'discover', '--year', '2025'])
        self.assertEqual(args.year, 2025); self.assertTrue(args.output_dir.endswith('/2025'))


if __name__ == '__main__': unittest.main()
