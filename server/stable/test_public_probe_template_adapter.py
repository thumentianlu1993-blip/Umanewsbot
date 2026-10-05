"""C020 受审合同的真实模板测试；类内设置隔离，SQL 由 SimpleTestCase 禁用。"""
from django.test import SimpleTestCase, override_settings
from stable.testing_public_probe.support import (
    approved_cases, adapter_inputs, render_case, render_approved_original,
)
from stable.services.public_probe_template_adapter import parse_template_render
from stable.testing_public_probe.settings import TEMPLATE_TEST_SETTINGS


@override_settings(**TEMPLATE_TEST_SETTINGS)
class TemplateAdapterFirstRed(SimpleTestCase):
    databases = set()

    def test_full_template_legacy_without_projection(self):
        document = approved_cases()
        for case in document['positive_and_missing_cases']:
            with self.subTest(case=case['case_id']):
                html = render_case(case)
                self.assertIn(b'<!doctype html>', html.lower())
                self.assertIn(b'</html>', html)
                self.assertIn(b'/static/stable/public.css', html)
                self.assertNotIn(b'o03.render.v1', html)

    def test_first_positive_independent_expected(self):
        document = approved_cases()
        case = document['positive_and_missing_cases'][0]
        result = parse_template_render(**adapter_inputs(document, case))
        self.assertEqual(result['leaf_status'], 'template_fixture_verified')
        self.assertEqual(result['body'], case['expected_body'])
        self.assertIsNotNone(result['receipt'])

    def test_full_original_bytes_without_projection(self):
        document = approved_cases()
        for case in document['positive_and_missing_cases']:
            with self.subTest(case=case['case_id']):
                self.assertEqual(render_case(case), render_approved_original(case))

    def test_positive_and_missing_contract_matrix(self):
        document = approved_cases()
        self.assertEqual(len(document['positive_and_missing_cases']), 25)
        for case in document['positive_and_missing_cases']:
            with self.subTest(case=case['case_id']):
                result = parse_template_render(**adapter_inputs(document, case))
                self.observed_positive[case['case_id']] = result
                outcome = case['outcome']
                self.assertEqual(result['leaf_status'], outcome['leaf_status'])
                self.assertEqual(result['reason'], outcome['reason'])
                self.assertEqual(result['c013_status'], outcome['c013_status'])
                self.assertIs(result['synthetic_only'], True)
                self.assertIs(result['real_origin_verified'], False)
                self.assertIs(result['real_permission_verified'], False)
                self.assertIs(result['complete_original_scope'], False)
                self.assertEqual(result['sla'], 'unverified')
                if outcome['receipt_constructed']:
                    self.assertEqual(result['body'], case['expected_body'])
                    self.assertEqual(result['body_digest'], case['expected_body_sha256'])
                    self.assertIsNotNone(result['receipt'])
                    self.assertEqual(result['receipt']['body_digest'], case['expected_body_sha256'])
                    self.assertEqual(result['comparison']['status'], 'public_read_verified')
                else:
                    self.assertIsNone(result['receipt'])

    observed_positive = {}
    observed_negative = {}
    observed_meta = {}
    observed_private_budget = {}
    observed_private_arithmetic = {}
    observed_supplementary_baselines = {}
    observed_supplementary_reasons = {}

    def test_supplementary_baseline_reason_isolation(self):
        """五个独立参数保留旧reason覆盖；不改原72个输入/前置顺序。"""
        from stable.testing_public_probe.support import baseline_reason_inputs, SourceDOM, canonical_bytes
        from copy import deepcopy
        import hashlib
        parameters = (
            ('S07-equal-count-duplicate', 'P-official-old-detail-strict_display_v1',
             'same-cardinality-duplicate-row', 'unverified', 'duplicate_row', 6),
            ('S23-linked-double-entity', 'P-official-old-detail-strict_display_v1',
             'linked-double-entity', 'unverified', 'content_mismatch', 7),
            ('S26-position-valid-script-type', 'P-official-old-card-strict_display_v1',
             'position-valid-unauthorized-script-type', 'rejected', 'unexpected_script', 2),
            ('S72-private-results-only', 'P-official-old-detail-strict_display_v1',
             'private-results-only-retained-html', 'unverified', 'origin_permission_unbound', 5),
            ('S64-context-targets-null', 'P-official-old-card-strict_display_v1',
             'context-targets-null', 'unverified', 'context_schema', 3),
        )
        self.assertEqual(len(parameters), 5)
        document = approved_cases()
        for identity, case_id, operation, status, reason, rank in parameters:
            with self.subTest(supplementary=identity):
                case = next(c for c in document['positive_and_missing_cases'] if c['case_id'] == case_id)
                original = adapter_inputs(document, case)
                baseline = parse_template_render(**original)
                self.observed_supplementary_baselines[identity] = {
                    'leaf_status': baseline['leaf_status'], 'reason': baseline['reason'],
                    'body_digest': baseline['body_digest'], 'receipt_constructed': baseline['receipt'] is not None,
                }
                self.assertEqual(baseline['leaf_status'], 'template_fixture_verified')
                self.assertEqual(baseline['body'], case['expected_body'])
                self.assertIsNotNone(baseline['receipt'])
                inputs = baseline_reason_inputs(original, operation)
                changed_key = ('context' if operation == 'context-targets-null' else
                               'private' if operation == 'private-results-only-retained-html' else 'html')
                self.assertNotEqual(inputs[changed_key], original[changed_key])
                self.assertEqual({k: v for k, v in inputs.items() if k != changed_key},
                                 {k: v for k, v in original.items() if k != changed_key})
                before = SourceDOM(original['html']); after = SourceDOM(inputs['html'])
                if operation == 'same-cardinality-duplicate-row':
                    before_rows = before.select(root=before.one(attr='id', value='results'), tag='tr')[1:]
                    rows = after.select(root=after.one(attr='id', value='results'), tag='tr')[1:]
                    self.assertEqual(len(before_rows), 4); self.assertEqual(len(rows), 4)
                    self.assertEqual([row.attrs['data-o03-row'] for row in rows],
                                     [row.attrs['data-o03-row'] for row in before_rows[:3]] + [before_rows[0].attrs['data-o03-row']])
                    self.assertEqual(len({row.attrs['data-o03-row'] for row in rows}), 3)
                elif operation == 'linked-double-entity':
                    rows = after.select(root=after.one(attr='id', value='results'), tag='tr')[1:]
                    token = rows[2].attrs['data-o03-row']
                    podium_row = after.one(root=after.one(cls='podium-line'), attr='data-o03-row', value=token)
                    nodes = [after.one(root=rows[2], attr='data-o03-field', value='horse_name'),
                             after.one(root=podium_row, attr='data-o03-field', value='horse_name')]
                    self.assertEqual(original['private']['template_context']['results'][2]['horse_name'], 'Café & 星')
                    self.assertEqual([after.source[node.opening_end:node.closing_start] for node in nodes],
                                     ['Café &amp;amp; 星'] * 2)
                elif operation == 'position-valid-unauthorized-script-type':
                    old = next(node for node in before.select(tag='script') if 'data-o03-marker' not in node.attrs)
                    node = next(node for node in after.select(tag='script') if 'data-o03-marker' not in node.attrs)
                    self.assertEqual(old.attrs, {}); self.assertEqual(node.attrs, {'type': 'text/javascript'})
                    self.assertEqual(node.parent.tag, 'main'); self.assertTrue(node.parent.has_class('race-page'))
                    siblings = node.parent.children; index = siblings.index(node)
                    self.assertTrue(siblings[index - 1].has_class('date-axis')); self.assertEqual(siblings[index + 1].tag, 'form')
                    self.assertEqual(after.source[node.opening_end:node.closing_start], before.source[old.opening_end:old.closing_start])
                elif operation == 'context-targets-null':
                    wanted = deepcopy(original['context']); wanted['targets'] = None
                    self.assertEqual(inputs['context'], wanted)
                    self.assertEqual(inputs['html'], original['html'])
                else:
                    wanted = deepcopy(original['private'])
                    wanted['template_context']['results'] = wanted['template_context']['results'][:1]
                    wanted['template_context_sha256'] = hashlib.sha256(canonical_bytes(wanted['template_context'])).hexdigest()
                    self.assertEqual(inputs['private'], wanted)
                    self.assertEqual(len(inputs['private']['template_context']['top_results']), 4)
                    self.assertEqual(inputs['html'], original['html'])
                result = parse_template_render(**inputs)
                self.observed_supplementary_reasons[identity] = {
                    'case_id': case_id, 'operation': operation,
                    'html_before_sha256': hashlib.sha256(original['html']).hexdigest(),
                    'html_after_sha256': hashlib.sha256(inputs['html']).hexdigest(),
                    'private_before_sha256': hashlib.sha256(canonical_bytes(original['private'])).hexdigest(),
                    'private_after_sha256': hashlib.sha256(canonical_bytes(inputs['private'])).hexdigest(),
                    'leaf_status': result['leaf_status'], 'reason': result['reason'], 'priority_rank': result['priority_rank'],
                    'receipt_constructed': result['receipt'] is not None, 'c013_status': result['c013_status'],
                }
                self.assertEqual((result['leaf_status'], result['reason'], result['priority_rank']), (status, reason, rank))
                self.assertIsNone(result['receipt']); self.assertEqual(result['c013_status'], 'not_constructed')

    def test_private_square_independent_oracle(self):
        """Oracle 使用有界内置乘法；不得调用受测算法生成 expected。"""
        import sys
        from unittest.mock import patch
        from stable.services import public_probe_template_adapter as adapter
        setting = sys.get_int_max_str_digits()
        specs = [(0, 'zero'), (1, 'one')]
        specs += [(width, pattern) for width in (1023, 1024, 1025, 1026, 2047, 2048, 2049)
                  for pattern in ('low-zero', 'low-full', 'both-full', 'sum-carry')]
        specs += [(524288, 'both-full')]
        for width, pattern in specs:
            key = 'square/' + str(width) + '/' + pattern
            with self.subTest(arithmetic=key), patch.object(sys, 'set_int_max_str_digits', side_effect=AssertionError('int/string setting mutation')):
                if pattern == 'zero': value = 0
                elif pattern == 'one': value = 1
                else:
                    half = width // 2
                    low = 0 if pattern == 'low-zero' else (1 << half) - 1
                    high = ((1 << (width - half)) - 1 if pattern == 'both-full'
                            else 1 << (width - half - 1))
                    if pattern == 'sum-carry': low = 1 << (half - 1)
                    value = (high << half) + low
                    self.assertEqual(value.bit_length(), width)
                    del high, low
                expected = value * value
                actual = adapter._private_square(value)
                self.assertEqual(actual, expected)
                self.observed_private_arithmetic[key] = {
                    'input_bits': value.bit_length(), 'result_bits': actual.bit_length(),
                    'oracle': 'bounded-native-multiply', 'equal': True,
                }
                del value, expected, actual
        for name, value in [('negative', -1), ('bool', True), ('null', None),
                            ('float', 1.0), ('above-bits', 1 << 524288)]:
            with self.subTest(square_invalid=name):
                with self.assertRaises(adapter._Failure) as captured: adapter._private_square(value)
                self.assertEqual(captured.exception.reason, 'invalid_structure')
                self.observed_private_arithmetic['square-invalid/' + name] = {'reason': 'invalid_structure'}
        self.assertEqual(sys.get_int_max_str_digits(), setting)

    def test_private_power10_independent_oracle(self):
        """每轮仅保留一个≤262144指数的内置幂 oracle，无全量表/字符串。"""
        import sys
        from unittest.mock import patch
        from stable.services import public_probe_template_adapter as adapter
        setting = sys.get_int_max_str_digits()
        exponents = (1, 2, 3, 4, 7, 8, 15, 16, 21, 42, 85, 170, 255, 256,
                     1023, 1024, 21845, 43690, 65535, 65536, 131071, 131072, 262143, 262144)
        for exponent in exponents:
            key = 'power10/' + str(exponent)
            with self.subTest(arithmetic=key), patch.object(sys, 'set_int_max_str_digits', side_effect=AssertionError('int/string setting mutation')):
                expected = 10 ** exponent
                actual = adapter._private_power10(exponent)
                self.assertEqual(actual, expected)
                self.observed_private_arithmetic[key] = {
                    'exponent': exponent, 'result_bits': actual.bit_length(),
                    'oracle': 'bounded-native-power', 'equal': True,
                }
                del expected, actual
        for name, exponent in [('zero', 0), ('negative', -1), ('bool', True),
                               ('float', 1.0), ('null', None), ('above-exponent', 262145)]:
            with self.subTest(power_invalid=name):
                with self.assertRaises(adapter._Failure) as captured: adapter._private_power10(exponent)
                self.assertEqual(captured.exception.reason, 'invalid_structure')
                self.observed_private_arithmetic['power-invalid/' + name] = {'reason': 'invalid_structure'}
        self.assertEqual(sys.get_int_max_str_digits(), setting)

    def test_private_incremental_canonical_and_first_failure(self):
        """小型独立 JSON oracle 验所有字符宽度；首故障不能扫描未知后缀。"""
        import json
        from unittest.mock import patch
        from stable.services import public_probe_template_adapter as adapter
        width = adapter._private_integer_width
        payloads = ('', '"\\', '\b\f\n\r\t', '\x00\x01\x1f', '\u0080', '\u07ff',
                    '\u0800', '\uffff', '\U00010000', '\U0010ffff')
        for index, payload in enumerate(payloads):
            with self.subTest(canonical_character_class=index):
                value = {'p': payload, 'x': 7}
                length = len(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                        separators=(',', ':'), allow_nan=False).encode('utf-8'))
                with patch.object(adapter, '_private_integer_width', wraps=width) as observed:
                    self.assertIsNone(adapter._guard_private_input(value))
                    observed.assert_called_once_with(7, 262144 - (length - 1))
                self.observed_private_arithmetic['canonical/' + str(index)] = {'canonical_bytes': length, 'remaining_exact': True}
        cycle = []; cycle.append(cycle)
        cases = [('byte-before-cycle', {'x': 'a' * 262137, 'tail': cycle}, 'wire_limit'),
                 ('node-before-invalid-key', {'x': [None] * 16381, 1: None}, 'nodes_limit')]
        for name, value, reason in cases:
            with self.subTest(first_failure=name):
                with self.assertRaises(adapter._Failure) as captured: adapter._guard_private_input(value)
                self.assertEqual(captured.exception.reason, reason)
                self.observed_private_arithmetic[name] = {'reason': reason, 'suffix_unvisited': True}

    def test_private_input_fixed_resource_boundaries(self):
        """只验即将受审的资源前检；schema/业务正例仍由原25输入独立验证。"""
        import json
        from stable.services import public_probe_template_adapter as adapter
        guard = getattr(adapter, '_guard_private_input')
        def canonical_size(value):
            return len(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                  separators=(',', ':'), allow_nan=False).encode('utf-8'))
        exact_depth = None
        for unused in range(63): exact_depth = [exact_depth]
        cases = [
            ('nodes', {'x': [None] * 16381}, {'x': [None] * 16382}, 'nodes_limit'),
            ('bytes-ascii', {'x': 'a' * 262136}, {'x': 'a' * 262137}, 'wire_limit'),
            ('bytes-UTF8', {'x': '汉' * 87378 + 'aa'}, {'x': '汉' * 87378 + 'aaa'}, 'wire_limit'),
            ('bytes-escaped', {'x': '\n' * 131068}, {'x': '\n' * 131068 + 'a'}, 'wire_limit'),
            ('depth', {'x': exact_depth}, {'x': [exact_depth]}, 'depth_limit'),
        ]
        for name, exact, above, reason in cases:
            with self.subTest(private_boundary=name):
                if name.startswith('bytes-'):
                    self.assertEqual(canonical_size(exact), 262144)
                    self.assertEqual(canonical_size(above), 262145)
                self.assertIsNone(guard(exact))
                with self.assertRaises(adapter._Failure) as captured: guard(above)
                self.assertEqual(captured.exception.reason, reason)
                self.observed_private_budget[name] = {'exact': 'accepted', 'plus_one_reason': reason}

        # Integer punctuation is 6 bytes for {"x":N}; string punctuation above is 8.
        # Expected digits come from authored powers, never str/dumps of these integers.
        import sys
        from unittest.mock import patch
        digits_setting = sys.get_int_max_str_digits()
        integer_cases = [(str(n), n, digits) for n, digits in
                         [(0, 1), (9, 1), (10, 2), (99, 2), (100, 3),
                          (-9, 1), (-10, 2), (-99, 2), (-100, 3)]]
        for exponent in (1, 2, 100, 5000):
            power = 10 ** exponent
            for delta, digits in ((-1, exponent), (0, exponent + 1), (1, exponent + 1)):
                for sign in (1, -1):
                    integer_cases.append(('power-' + str(exponent) + '/' + str(delta) + '/' + str(sign),
                                          sign * (power + delta), digits))
        for name, number, digits in integer_cases:
            with self.subTest(private_integer=name), patch.object(sys, 'set_int_max_str_digits', side_effect=AssertionError('int/string setting mutation')):
                # {"p":"","x":N} has 13 punctuation bytes, plus sign and digits.
                padding = 262144 - 13 - (number < 0) - digits
                self.assertIsNone(guard({'p': 'a' * padding, 'x': number}))
                with self.assertRaises(adapter._Failure) as captured:
                    guard({'p': 'a' * (padding + 1), 'x': number})
                self.assertEqual(captured.exception.reason, 'wire_limit')
                self.observed_private_budget['integer/' + name] = {
                    'known_digits': digits, 'negative': number < 0,
                    'exact': 'accepted', 'plus_one_reason': 'wire_limit',
                }
        for sign, digits in ((1, 262138), (-1, 262137)):
            with self.subTest(private_integer_max_sign=sign), patch.object(sys, 'set_int_max_str_digits', side_effect=AssertionError('int/string setting mutation')):
                exact = sign * 10 ** (digits - 1)
                above = sign * 10 ** digits
                self.assertIsNone(guard({'x': exact}))
                with self.assertRaises(adapter._Failure) as captured: guard({'x': above})
                self.assertEqual(captured.exception.reason, 'wire_limit')
                self.observed_private_budget['integer-max/' + str(sign)] = {
                    'punctuation': 6, 'known_digits': digits,
                    'sign_bytes': sign < 0, 'exact': 'accepted', 'plus_one_reason': 'wire_limit',
                }
        # bool must use JSON true/false widths rather than integer 1/0 widths.
        bool_padding = 262144 - len('{"p":"","x":true}')
        self.assertIsNone(guard({'p': 'a' * bool_padding, 'x': True}))
        with self.assertRaises(adapter._Failure) as captured:
            guard({'p': 'a' * bool_padding, 'x': False})
        self.assertEqual(captured.exception.reason, 'wire_limit')
        self.observed_private_budget['bool-width'] = {'true_exact': 'accepted', 'false_plus_one_reason': 'wire_limit'}
        power10 = getattr(adapter, '_private_power10')
        for number in (0, 1, 9, 10, 100, -1, -9, -10, -100):
            with self.subTest(private_unpadded_integer=number):
                def bounded_power(exponent):
                    self.assertGreaterEqual(exponent, 1)
                    self.assertLessEqual(exponent, number.bit_length())
                    return power10(exponent)
                with patch.object(adapter, '_private_power10', side_effect=bounded_power) as observed:
                    self.assertIsNone(guard({'x': number}))
                    self.assertLessEqual(observed.call_count, 1 + max(0, (number.bit_length() - 1).bit_length()))
                    if number in (0, 1, -1): observed.assert_not_called()
                    self.observed_private_budget['unpadded-integer/' + str(number)] = {
                        'accepted': True, 'original_bit_length': number.bit_length(),
                        'power_calls': observed.call_count,
                        'maximum_exponent': max((call.args[0] for call in observed.call_args_list), default=0),
                    }
        with patch.object(adapter, '_private_power10', side_effect=AssertionError('ones must not need decimal powers')) as observed:
            self.assertIsNone(guard({'x': [1] * 16381}))
            observed.assert_not_called()
            self.observed_private_budget['bulk-small-integers'] = {
                'accepted': True, 'nodes': 16384, 'canonical_bytes': 32769,
                'integer_count': 16381, 'power_calls': 0,
            }
        self.assertEqual(sys.get_int_max_str_digits(), digits_setting)

    def test_private_budget_preserves_existing_DTO_guards(self):
        from stable.services import public_probe_template_adapter as adapter
        guard = getattr(adapter, '_guard_private_input')
        existing_exact = {'x': [None] * 11997}  # dict/key/list + items = 12000
        existing_above = {'x': [None] * 11998}
        self.assertIsNone(adapter._guard_json(existing_exact))
        with self.assertRaises(adapter._Failure) as captured: adapter._guard_json(existing_above)
        self.assertEqual(captured.exception.reason, 'nodes_limit')
        self.assertIsNone(guard(existing_above))
        shared = [None]; self.assertIsNone(guard({'a': shared, 'b': shared}))
        cycle = []; cycle.append(cycle)
        for name, value, reason in [('cycle', {'x': cycle}, 'invalid_structure'),
                                    ('float', {'x': 1.5}, 'invalid_structure'),
                                    ('key-type', {1: None}, 'invalid_structure'),
                                    ('surrogate', {'x': '\ud800'}, 'invalid_utf8')]:
            with self.subTest(private_invalid=name):
                with self.assertRaises(adapter._Failure) as captured: guard(value)
                self.assertEqual(captured.exception.reason, reason)
        from unittest.mock import patch
        import sys
        digits_setting = sys.get_int_max_str_digits()
        far = 1 << (8 * 262144)
        for sign in (1, -1):
            for suffix_name, suffix in (('cycle', cycle), ('surrogate', '\ud800')):
                with self.subTest(private_far_integer_sign=sign, unvisited_suffix=suffix_name):
                    # Proposed integer branch must preflight bit_length before abs.
                    with patch.object(adapter, 'abs', side_effect=AssertionError('unbounded abs'), create=True) as forbidden_abs, patch.object(sys, 'set_int_max_str_digits', side_effect=AssertionError('int/string setting mutation')):
                        with self.assertRaises(adapter._Failure) as captured:
                            guard({'x': sign * far, 'tail': suffix})
                        self.assertEqual(captured.exception.reason, 'wire_limit')
                        forbidden_abs.assert_not_called()
                    self.observed_private_budget['far-integer/' + str(sign) + '/' + suffix_name] = {
                        'original_bit_length': far.bit_length(), 'reason': 'wire_limit', 'abs_calls': 0,
                    }
        for suffix_name, suffix in (('cycle', cycle), ('surrogate', '\ud800')):
            with self.subTest(private_nodes_unvisited_suffix=suffix_name):
                with self.assertRaises(adapter._Failure) as captured:
                    guard({'x': [None] * 16381 + [suffix]})
                self.assertEqual(captured.exception.reason, 'nodes_limit')
                self.observed_private_budget['nodes-first/' + suffix_name] = {'reason': 'nodes_limit', 'suffix_unvisited': True}
        self.assertEqual(sys.get_int_max_str_digits(), digits_setting)
        self.observed_private_budget['scope-and-types'] = {
            'other_DTO_nodes_exact': 12000, 'other_DTO_nodes_plus_one_reason': 'nodes_limit',
            'private_12001': 'accepted', 'aliased_acyclic_values': 'accepted',
            'cyclic_or_unsupported_values': 'rejected',
        }
    observed_review_baselines = {}
    observed_review_mutations = {}

    def _review_baseline(self, document, case):
        """先证明相同原件可成功；前置失败不能冒充两项 P2 的 RED。"""
        from stable.testing_public_probe.support import canonical_bytes
        import hashlib
        inputs = adapter_inputs(document, case)
        result = parse_template_render(**inputs)
        self.observed_review_baselines[case['case_id']] = {
            'leaf_status': result['leaf_status'], 'reason': result['reason'],
            'body_digest': result.get('body_digest'),
            'receipt_constructed': result['receipt'] is not None,
            'independent_expected_body_sha256': hashlib.sha256(canonical_bytes(case['expected_body'])).hexdigest(),
        }
        self.assertEqual(result['leaf_status'], 'template_fixture_verified', 'P2 baseline must verify before HTML mutation')
        self.assertEqual(result['body'], case['expected_body'])
        self.assertIsNotNone(result['receipt'])
        return inputs

    def _review_observe_edit(self, original, dom, edit, key):
        from copy import deepcopy
        import hashlib
        from stable.testing_public_probe.support import canonical_bytes
        inputs = deepcopy(original)
        inputs['html'] = dom.replace([edit])
        self.assertNotEqual(inputs['html'], original['html'])
        bound_original = {k: v for k, v in original.items() if k != 'html'}
        self.assertEqual({k: v for k, v in inputs.items() if k != 'html'}, bound_original)
        # 三份 contract 是 bytes；显式编码后只做原件摘要，不导出额外身份。
        raw_identity = {k: v.hex() if isinstance(v, bytes) else v for k, v in bound_original.items()}
        result = parse_template_render(**inputs)
        self.observed_review_mutations[key] = {
            'html_before_sha256': hashlib.sha256(original['html']).hexdigest(),
            'html_after_sha256': hashlib.sha256(inputs['html']).hexdigest(),
            'edit': {'start': edit[0], 'end': edit[1], 'replacement': edit[2]},
            'unchanged_non_html_inputs_sha256': hashlib.sha256(canonical_bytes(raw_identity)).hexdigest(),
            'leaf_status': result['leaf_status'], 'reason': result['reason'],
            'priority_rank': result['priority_rank'], 'c013_status': result['c013_status'],
            'body_digest': result.get('body_digest'), 'receipt_constructed': result['receipt'] is not None,
        }
        return result

    def test_review_R01_scalar_nested_nodes_rejected(self):
        from stable.testing_public_probe.support import SourceDOM
        document = approved_cases()
        cases = [c for c in document['positive_and_missing_cases']
                 if c['page_type'] == 'detail' and c['template_context']['winner'] is not None]
        self.assertEqual(len(cases), 12)
        for case in cases:
            inputs = self._review_baseline(document, case); dom = SourceDOM(inputs['html'])
            for part in ('name', 'ribbon', 'nav'):
                node = dom.one(attr='data-o03-part', value=part) if part != 'nav' else dom.one(attr='data-o03-role', value='detail.result.nav')
                self.assertEqual(node.children, [], 'approved scalar has no element descendants')
                original_text = dom.source[node.opening_end:node.closing_start]
                for wrapper in ('<span>{}</span>', '<span class="site-nav">{}</span>'):
                    key = 'R01-nested/' + case['case_id'] + '/' + part + '/' + ('hidden-class' if 'site-nav' in wrapper else 'plain')
                    with self.subTest(review_case=key):
                        result = self._review_observe_edit(inputs, dom, dom.inner_edit(node, wrapper.format(original_text)), key)
                        self.assertEqual((result['leaf_status'], result['reason'], result['priority_rank']),
                                         ('unverified', 'role_structure', 4))
                        self.assertIsNone(result['receipt'])
                        self.assertEqual(result['c013_status'], 'not_constructed')

    def test_review_R01_scalar_outer_class_and_wrapper_controls(self):
        from stable.testing_public_probe.support import SourceDOM
        document = approved_cases()
        cases = [c for c in document['positive_and_missing_cases']
                 if c['case_id'] in ('P-official-old-detail-legacy', 'P-official-old-detail-strict_display_v1')]
        self.assertEqual(len(cases), 2)
        for case in cases:
            inputs = self._review_baseline(document, case); dom = SourceDOM(inputs['html'])
            for part in ('name', 'ribbon', 'nav'):
                node = dom.one(attr='data-o03-part', value=part) if part != 'nav' else dom.one(attr='data-o03-role', value='detail.result.nav')
                extra_class = (node.attrs.get('class', '') + ' site-nav').strip()
                whole = dom.source[node.start:node.end]
                replacement = '<b' + whole[len('<' + node.tag):-(len(node.tag) + 3)] + '</b>'
                edits = [('outer-class', dom.attribute_edit(node, 'class', extra_class)),
                         ('outer-wrapper', (node.start, node.end, replacement))]
                for variant, edit in edits:
                    key = 'R01-control/' + case['case_id'] + '/' + part + '/' + variant
                    with self.subTest(review_case=key):
                        result = self._review_observe_edit(inputs, dom, edit, key)
                        # 原完整 envelope 已保护外层：这是保留控制，不声称新 RED。
                        if part == 'nav' and variant == 'outer-wrapper':
                            self.assertEqual((result['leaf_status'], result['reason'], result['priority_rank']),
                                             ('rejected', 'invalid_structure', 2))
                        else:
                            self.assertEqual((result['leaf_status'], result['priority_rank']), ('unverified', 4))
                            self.assertIn(result['reason'], ('role_structure', 'unmodeled_visible_content'))
                        self.assertIsNone(result['receipt'])

    def test_review_R02_medal_classes_bound_to_independent_DTO(self):
        from stable.testing_public_probe.support import SourceDOM
        document = approved_cases()
        cases = [c for c in document['positive_and_missing_cases'] if c['page_type'] == 'detail']
        self.assertEqual(len(cases), 13)
        for case in cases:
            inputs = self._review_baseline(document, case); dom = SourceDOM(inputs['html'])
            table = dom.one(attr='data-o03-role', value='detail.result.table')
            tbody = dom.one(root=table, tag='tbody'); rows = tbody.children
            self.assertEqual(len(rows), len(case['template_context']['results']))
            self.assertEqual(rows[0].attrs['class'], 'medal-1')
            mutations = [('first-medal-3', rows[0], 'medal-3'), ('first-cleared', rows[0], '')]
            if case['origin_ref'] == 'fixture-origin:dead-heat':
                self.assertEqual([r['display_finish_position'] for r in case['template_context']['results'][:2]], [1, 1])
                self.assertEqual(rows[1].attrs['class'], 'medal-1')
                mutations += [('tied-second-medal-2', rows[1], 'medal-2'), ('tied-second-cleared', rows[1], '')]
            for variant, row, replacement in mutations:
                key = 'R02-medal/' + case['case_id'] + '/' + variant
                with self.subTest(review_case=key):
                    result = self._review_observe_edit(inputs, dom, dom.attribute_edit(row, 'class', replacement), key)
                    self.assertEqual((result['leaf_status'], result['reason'], result['priority_rank']),
                                     ('unverified', 'role_structure', 4))
                    self.assertIsNone(result['receipt'])
                    self.assertEqual(result['c013_status'], 'not_constructed')

    def test_behavioral_negative_matrix(self):
        from stable.testing_public_probe.support import negative_inputs
        document = approved_cases()
        cases = [case for case in document['future_negative_cases'] if case['case_id'] not in {
            'N62-equality-budget', 'N65-expected-feedback', 'N67-table-slice'}]
        self.assertEqual(len(cases), 72)
        for case in cases:
            with self.subTest(case=case['case_id']):
                result = parse_template_render(**negative_inputs(document, case))
                self.observed_negative[case['case_id']] = result
                self.assertEqual((result['leaf_status'], result['reason'], result['priority_rank']),
                                 (case['expected_status'], case['expected_primary_reason'], case['expected_rank']))
                self.assertIsNone(result['receipt'])
                self.assertEqual(result['c013_status'], 'not_constructed')

    def test_marker_script_safe_transport_equivalence(self):
        from copy import deepcopy
        import hashlib
        import json
        from stable.testing_public_probe.support import SourceDOM, canonical_bytes
        document = approved_cases();case = deepcopy(document['positive_and_missing_cases'][0])
        case['projection']['marker']['subject'] = '/races/2026/synthetic-final/?a=1&b=2'
        html = render_case(case, case['projection']);dom = SourceDOM(html)
        node = dom.one(tag='script', attr='data-o03-marker')
        raw = dom.source[node.opening_end:node.closing_start]
        self.assertIn('\\u0026', raw)
        self.assertIn('\\u003D', raw)
        decoded = json.loads(raw)
        self.assertEqual(decoded, case['projection']['marker'])
        self.assertEqual(hashlib.sha256(canonical_bytes(decoded)).hexdigest(),
                         hashlib.sha256(canonical_bytes(case['projection']['marker'])).hexdigest())
        inputs = adapter_inputs(document, document['positive_and_missing_cases'][0]);inputs['html'] = html
        result = parse_template_render(**inputs)
        self.assertEqual(result['reason'], 'subject_binding')
        self.assertIsNone(result['receipt'])

    def test_marker_duplicate_key_and_invalid_type(self):
        from stable.testing_public_probe.support import SourceDOM, marker_edit
        document = approved_cases();case = document['positive_and_missing_cases'][0]
        inputs = adapter_inputs(document, case);dom = SourceDOM(inputs['html']);node = dom.one(tag='script',attr='data-o03-marker')
        raw = dom.source[node.opening_end:node.closing_start]
        inputs['html'] = dom.replace([dom.inner_edit(node, raw[:-1]+',"subject":"/races/2026/synthetic-final/"}')])
        self.assertEqual(parse_template_render(**inputs)['reason'], 'duplicate_json_key')
        for value in [True, None, [], {}]:
            with self.subTest(value=value):
                inputs = adapter_inputs(document, case);marker_edit(inputs,lambda marker:marker.update(subject=value))
                result = parse_template_render(**inputs)
                self.assertEqual(result['reason'], 'marker_schema');self.assertIsNone(result['receipt'])

    def test_marker_close_and_script_injection_rejected(self):
        from stable.testing_public_probe.support import SourceDOM
        document = approved_cases();case = document['positive_and_missing_cases'][0]
        inputs = adapter_inputs(document, case);dom = SourceDOM(inputs['html']);node = dom.one(tag='script',attr='data-o03-marker')
        raw = dom.source[node.opening_end:node.closing_start]
        inputs['html'] = dom.replace([dom.inner_edit(node,raw+'</script><script>alert(1)')])
        result = parse_template_render(**inputs)
        self.assertEqual(result['leaf_status'], 'rejected');self.assertIsNone(result['receipt'])
        from stable.services.public_probe_template_adapter import _escapejs
        from django.utils.html import escapejs
        raw = '</script>"\'\\=&-;`\u2028\u2029\n'
        self.assertEqual(_escapejs(raw), str(escapejs(raw)))
        # Encoder equivalence does not widen the API subject regex.
        inputs = adapter_inputs(document, case)
        from stable.testing_public_probe.support import marker_edit
        marker_edit(inputs, lambda marker: marker.update(subject='/races/<invalid>/'))
        self.assertEqual(parse_template_render(**inputs)['reason'], 'marker_schema')

    def test_meta_expected_feedback_is_detected(self):
        from unittest.mock import patch
        from copy import deepcopy
        from stable.testing_public_probe.support import SourceDOM
        from stable.services import public_probe_template_adapter as observer
        document = approved_cases();case = next(c for c in document['positive_and_missing_cases'] if c['case_id']=='P-official-old-detail-strict_display_v1')
        inputs = adapter_inputs(document, case);dom = SourceDOM(inputs['html']);table = dom.one(attr='id',value='results')
        node = dom.select(root=table,attr='data-o03-field',value='horse_name')[0]
        inputs['html'] = dom.replace([dom.inner_edit(node,'错误马名')])
        self.assertNotEqual(parse_template_render(**inputs)['leaf_status'], 'template_fixture_verified')
        with patch.object(observer, '_extract_body', return_value=deepcopy(case['expected_body'])):
            mutant = parse_template_render(**inputs)
        self.observed_meta['N65-expected-feedback' if '错误马名' in inputs['html'].decode() else 'N67-table-slice'] = {'mutant': mutant, 'mutation_detection': 'assertion must fail'}
        self.assertEqual(mutant['leaf_status'], 'template_fixture_verified')
        with self.assertRaises(AssertionError):
            self.assertNotEqual(mutant['leaf_status'], 'template_fixture_verified')

    def test_meta_missing_fourth_row_is_detected(self):
        from unittest.mock import patch
        from copy import deepcopy
        from stable.testing_public_probe.support import SourceDOM
        from stable.services import public_probe_template_adapter as observer
        document = approved_cases();case = next(c for c in document['positive_and_missing_cases'] if c['case_id']=='P-official-old-detail-strict_display_v1')
        inputs = adapter_inputs(document, case);dom = SourceDOM(inputs['html']);table = dom.one(attr='id',value='results')
        rows = dom.select(root=table,tag='tr')[1:];inputs['html'] = dom.replace([(rows[-1].start, rows[-1].end, '')])
        self.assertEqual(parse_template_render(**inputs)['reason'], 'row_cardinality')
        original = observer._extract_body
        def ignore_and_invent_last(dom, marker_node, marker, tuple_value, origin, mapping, private, context, definitions):
            changed = deepcopy(private);changed['profile']['declared_result_rows'] = 3
            body = original(dom, marker_node, marker, tuple_value, origin, mapping, changed, context, definitions)
            body['roles'][-1]['rows'].append(deepcopy(case['expected_body']['roles'][-1]['rows'][-1]))
            return body
        with patch.object(observer, '_extract_body', side_effect=ignore_and_invent_last):
            mutant = parse_template_render(**inputs)
        self.observed_meta['N65-expected-feedback' if '错误马名' in inputs['html'].decode() else 'N67-table-slice'] = {'mutant': mutant, 'mutation_detection': 'assertion must fail'}
        self.assertEqual(mutant['leaf_status'], 'template_fixture_verified')
        with self.assertRaises(AssertionError):
            self.assertNotEqual(mutant['leaf_status'], 'template_fixture_verified')

    def test_meta_all_seven_resource_boundaries(self):
        from copy import deepcopy
        from html.parser import HTMLParser
        class Counter(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.values = dict(depth=0,nodes=0,markers=0,fields=0,rows=0);self.stack=[]
            def handle_starttag(self,tag,attrs):
                self.values['nodes']+=1;self.values['depth']=max(self.values['depth'],len(self.stack)+1)
                attrs=dict(attrs)
                for name,attribute in [('markers','data-o03-marker'),('fields','data-o03-field')]:self.values[name]+=attribute in attrs
                self.values['rows']+=tag=='tr' or 'data-o03-row' in attrs
                if tag not in ('meta','link','input'):self.stack.append(tag)
            def handle_startendtag(self,tag,attrs):
                self.handle_starttag(tag,attrs)
                if tag not in ('meta','link','input'):self.stack.pop()
            def handle_endtag(self,tag):self.stack.pop()
            def handle_data(self,data):self.values['nodes']+=bool(data)
            def handle_comment(self,data):self.values['nodes']+=1
            def handle_decl(self,data):self.values['nodes']+=1
        document = approved_cases();case = next(c for c in document['positive_and_missing_cases'] if c['case_id']=='P-official-old-detail-strict_display_v1')
        inputs = adapter_inputs(document, case);counter = Counter();counter.feed(inputs['html'].decode());counter.close()
        counters = dict(counter.values, wire_bytes=len(inputs['html']), decoded_bytes=len(inputs['html'].decode().encode()))
        for key,value in counters.items():
            with self.subTest(counter=key):
                exact=deepcopy(inputs);exact['context']['limits'][key]=value
                self.assertEqual(parse_template_render(**exact)['leaf_status'],'template_fixture_verified')
                below=deepcopy(exact);below['context']['limits'][key]=value-1
                expected = 'invalid_limits' if value == 1 else {'wire_bytes': 'wire_limit', 'decoded_bytes': 'decoded_limit'}.get(key, key + '_limit')
                self.assertEqual(parse_template_render(**below)['reason'],expected)
