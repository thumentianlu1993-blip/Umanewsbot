"""O03 完整模板 synthetic observer。无 IO/框架/时钟；成功不是 production 权限。"""
from datetime import datetime
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import re
import unicodedata


_PHASES = [
    ('rejected', 'invalid_limits wire_limit decoded_limit depth_limit nodes_limit markers_limit fields_limit rows_limit'),
    ('rejected', 'invalid_utf8 duplicate_json_key invalid_structure duplicate_attribute unexpected_tag unexpected_attribute unexpected_script script_bytes_mismatch root_boundary void_nesting'),
    ('unverified', 'context_schema response_incomplete denial_unverified redirect_unbound clock_unknown capability_absence_unverified'),
    ('unverified', 'unknown_profile css_version_unbound visibility_unbound membership_mismatch no_required_targets role_structure unmodeled_visible_content'),
    ('unverified', 'missing_marker marker_schema subject_binding surface_binding candidate_binding token_unbound token_conflict origin_permission_unbound generation_binding row_identity_unbound permission_expired mapping_binding'),
    ('unverified', 'missing_role duplicate_role missing_field duplicate_field row_cardinality duplicate_row column_contract required_placeholder wrapper_mismatch related_role_mismatch'),
    ('unverified', 'content_mismatch body_digest_mismatch'),
    ('unverified', 'c013_not_verified'),
]
_REASONS = {reason: (rank, status) for rank, (status, reasons) in enumerate(_PHASES, 1) for reason in reasons.split()}
_MAXIMUMS = dict(wire_bytes=262144, decoded_bytes=262144, depth=64, nodes=12000, markers=64, fields=4096, rows=512)
_SPACE = ' \t\r\n\f'
_MARKER_KEYS = ('schema_version', 'subject', 'surface_ref', 'capability', 'revision_ref', 'permission_version', 'content_digest')


class _Failure(Exception):
    def __init__(self, reason):
        self.reason = reason


def _need(condition, reason):
    if not condition:
        raise _Failure(reason)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _digest(value):
    return _hash(_canonical(value))


def _norm(text):
    return re.sub(r'[ \t\r\n\f]+', ' ', unicodedata.normalize('NFC', text.replace('\r\n', '\n'))).strip(_SPACE)


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def _guard_json(value, *, maximum_nodes=12000):
    count = 0
    active = set()
    def visit(item, depth):
        nonlocal count
        count += 1
        _need(depth <= 64, 'depth_limit')
        _need(count <= maximum_nodes, 'nodes_limit')
        _need(type(item) in (dict, list, str, int, bool, type(None)), 'invalid_structure')
        if type(item) in (dict, list):
            _need(id(item) not in active, 'invalid_structure')
            active.add(id(item))
            if type(item) is dict:
                _need(all(type(key) is str for key in item), 'invalid_structure')
                for key, child in item.items():
                    visit(key, depth + 1); visit(child, depth + 1)
            else:
                for child in item: visit(child, depth + 1)
            active.remove(id(item))
    visit(value, 0)


def _read_json(raw, ceiling, *, maximum_nodes=12000):
    _need(type(raw) is bytes, 'invalid_structure')
    _need(len(raw) <= ceiling, 'wire_limit')
    try:
        value = json.loads(raw.decode('utf-8', errors='strict'), object_pairs_hook=_json_pairs,
                           parse_constant=lambda unused: (_ for _ in ()).throw(_Failure('invalid_structure')))
    except UnicodeDecodeError:
        raise _Failure('invalid_utf8') from None
    except (json.JSONDecodeError, RecursionError):
        raise _Failure('invalid_structure') from None
    _guard_json(value, maximum_nodes=maximum_nodes)
    return value


def _private_square(value):
    """已审 private 算术叶片：仅≤1024 bits 使用原生乘法。"""
    _need(type(value) is int and value >= 0, 'invalid_structure')
    width = value.bit_length()
    _need(width <= 524288, 'invalid_structure')
    if width <= 1024:
        return value * value
    half = width // 2
    mask = (1 << half) - 1
    low = value & mask
    high = value >> half
    del mask
    z0 = _private_square(low)
    z2 = _private_square(high)
    summed = low + high
    del low, high
    z1 = _private_square(summed)
    del summed
    temporary = z1 - z0
    z1 = temporary
    del temporary
    temporary = z1 - z2
    z1 = temporary
    del temporary
    left = z2 << (2 * half)
    middle = z1 << half
    temporary = left + middle
    del left, middle
    result = temporary + z0
    del temporary
    return result


def _private_power10(exponent):
    """binary-prefix 幂；不缓存幂或使用巨型原生乘法/pow。"""
    _need(type(exponent) is int and 1 <= exponent <= 262144, 'invalid_structure')
    power = 1
    for bit in range(exponent.bit_length() - 1, -1, -1):
        temporary = _private_square(power)
        power = temporary
        del temporary
        if (exponent >> bit) & 1:
            left = power << 3
            right = power << 1
            temporary = left + right
            del left, right
            power = temporary
            del temporary
    return power


def _private_integer_width(number, remaining):
    """原 signed bit_length 必超判先于 abs；精确 digits 不编码整数。"""
    negative = number < 0
    capacity = remaining - int(negative)
    _need(capacity >= 1, 'wire_limit')
    if number == 0:
        return 1
    width = number.bit_length()
    _need(width <= 4 * capacity, 'wire_limit')
    magnitude = abs(number)
    high = min(capacity, width)
    if width > capacity:
        threshold = _private_power10(high)
        too_large = magnitude >= threshold
        del threshold
        _need(not too_large, 'wire_limit')
    low = 0
    while high - low > 1:
        middle = (low + high) // 2
        threshold = _private_power10(middle)
        greater_equal = magnitude >= threshold
        del threshold
        if greater_equal:
            low = middle
        else:
            high = middle
    return low + 1 + int(negative)


def _guard_private_input(value):
    """private 固定16384 nodes/262144 canonical UTF8 bytes/depth64。"""
    count = 0
    byte_count = 0
    active = set()

    def add_bytes(amount):
        nonlocal byte_count
        _need(amount <= 262144 - byte_count, 'wire_limit')
        byte_count += amount

    def visit(item, depth, *, is_key=False):
        nonlocal count
        _need(depth <= 64, 'depth_limit')
        count += 1
        _need(count <= 16384, 'nodes_limit')
        kind = type(item)
        _need(kind in (dict, list, str, int, bool, type(None)), 'invalid_structure')
        _need(not is_key or kind is str, 'invalid_structure')
        if kind in (dict, list):
            identity = id(item)
            _need(identity not in active, 'invalid_structure')
            active.add(identity)
            try:
                add_bytes(2)  # 两个括号；不复制/排序整个容器。
                first = True
                if kind is dict:
                    for key, child in item.items():
                        if not first: add_bytes(1)
                        first = False
                        # 键也按 depth→node→类型顺序检查，不能提前扫描后缀。
                        visit(key, depth + 1, is_key=True)
                        add_bytes(1)
                        visit(child, depth + 1)
                else:
                    for child in item:
                        if not first: add_bytes(1)
                        first = False
                        visit(child, depth + 1)
            finally:
                active.remove(identity)
        elif kind is str:
            add_bytes(2)
            for char in item:
                code = ord(char)
                _need(not 0xD800 <= code <= 0xDFFF, 'invalid_utf8')
                if char in '\\"\b\f\n\r\t': amount = 2
                elif code < 32: amount = 6
                elif code < 128: amount = 1
                elif code < 2048: amount = 2
                elif code < 65536: amount = 3
                else: amount = 4
                add_bytes(amount)
        elif kind is bool:
            add_bytes(4 if item else 5)
        elif kind is type(None):
            add_bytes(4)
        else:
            add_bytes(_private_integer_width(item, 262144 - byte_count))

    visit(value, 0)


def _schema_matches(value, schema, definitions):
    """固定合同中的有限 JSON Schema 子集；不解外部 ref、不补默认值。"""
    if '$ref' in schema:
        ref = schema['$ref']
        if not ref.startswith('#/$defs/') or '/' in ref[len('#/$defs/'):]: return False
        target = definitions.get(ref[len('#/$defs/'):])
        return target is not None and _schema_matches(value, target, definitions)
    if 'anyOf' in schema and not any(_schema_matches(value, branch, definitions) for branch in schema['anyOf']): return False
    if 'oneOf' in schema and sum(_schema_matches(value, branch, definitions) for branch in schema['oneOf']) != 1: return False
    if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']): return False
    if 'enum' in schema and not any(type(value) is type(item) and value == item for item in schema['enum']): return False
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool, 'null': type(None)}
    if 'type' in schema and (schema['type'] not in types or type(value) is not types[schema['type']]): return False
    if type(value) is dict:
        properties = schema.get('properties', {})
        patterns = schema.get('patternProperties', {})
        if not set(schema.get('required', [])) <= set(value): return False
        if not schema.get('minProperties', 0) <= len(value) <= schema.get('maxProperties', 12000): return False
        for key, item in value.items():
            children = ([properties[key]] if key in properties else []) + [child for pattern, child in patterns.items() if re.search(pattern, key)]
            if not children:
                additional = schema.get('additionalProperties', {})
                if additional is False: return False
                if type(additional) is dict: children.append(additional)
            if not all(_schema_matches(item, child, definitions) for child in children): return False
    if type(value) is list:
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 12000): return False
        if 'items' in schema and not all(_schema_matches(item, schema['items'], definitions) for item in value): return False
    if type(value) is str:
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 524288): return False
        if 'pattern' in schema and re.search(schema['pattern'], value) is None: return False
    if type(value) is int and not schema.get('minimum', -9223372036854775808) <= value <= schema.get('maximum', 9223372036854775807): return False
    return True


def _escapejs(value):
    """与固定 Django 5.2.1 escapejs 同一字符表；只用于 marker transport 槽。"""
    mapping = {ord(char): '\\u%04X' % ord(char) for char in '\\"\'><&=-;`\u2028\u2029'}
    mapping.update({code: '\\u%04X' % code for code in range(32)})
    _need(type(value) is str, 'marker_schema')
    return value.translate(mapping)


class _Node:
    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.parent = tag, attrs or {}, parent
        self.children = []
    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, _Node): yield from child.walk()
    def text(self):
        return ''.join(child.text() if isinstance(child, _Node) else child for child in self.children)
    def elements(self):
        return [child for child in self.children if isinstance(child, _Node)]
    def has_class(self, name):
        return name in self.attrs.get('class', '').split()


class _DOM(HTMLParser):
    def __init__(self, grammar):
        super().__init__(convert_charrefs=True)
        self.grammar = grammar
        self.root = _Node('#root'); self.stack = [self.root]
        self.errors = []
        self.counts = dict(depth=0, nodes=0, markers=0, fields=0, rows=0)
        self.doctypes = 0
    def fault(self, reason): self.errors.append(reason)
    def handle_decl(self, decl):
        self.counts['nodes'] += 1; self.doctypes += 1
        if decl.lower() != 'doctype html' or len(self.stack) != 1 or any(isinstance(c, _Node) or _norm(c) for c in self.root.children): self.fault('root_boundary')
    def unknown_decl(self, data): self.fault('invalid_structure')
    def handle_pi(self, data): self.fault('invalid_structure')
    def handle_comment(self, text):
        self.counts['nodes'] += 1
        if text.strip(_SPACE): self.fault('invalid_structure')
    def handle_data(self, text):
        if text:
            self.counts['nodes'] += 1; self.stack[-1].children.append(text)
            if len(self.stack) == 1 and text.strip(_SPACE): self.fault('root_boundary')
    def start(self, tag, attrs, closed):
        self.counts['nodes'] += 1
        self.counts['depth'] = max(self.counts['depth'], len(self.stack))
        pairs = [key for key, unused in attrs]
        if len(pairs) != len(set(pairs)): self.fault('duplicate_attribute')
        values = dict(attrs)
        self.counts['markers'] += 'data-o03-marker' in values
        self.counts['fields'] += 'data-o03-field' in values
        self.counts['rows'] += tag == 'tr' or 'data-o03-row' in values
        if tag not in self.grammar['tags']: self.fault('unexpected_tag')
        allowed = {key.lower() for key in self.grammar['attributes']}
        if not set(values) <= allowed: self.fault('unexpected_attribute')
        if ('aria-hidden' in values and (tag not in {'svg', 'path', 'circle', 'rect'} or values['aria-hidden'] != 'true')): self.fault('unexpected_attribute')
        node = _Node(tag, values, self.stack[-1]); self.stack[-1].children.append(node)
        if tag in self.grammar['svg_empty_tags']:
            if not closed or self.stack[-1].tag != 'svg': self.fault('invalid_structure')
        elif closed and tag not in self.grammar['void_tags']: self.fault('invalid_structure')
        if not closed and tag not in self.grammar['void_tags']: self.stack.append(node)
    def handle_starttag(self, tag, attrs): self.start(tag, attrs, False)
    def handle_startendtag(self, tag, attrs): self.start(tag, attrs, True)
    def handle_endtag(self, tag):
        if tag in self.grammar['void_tags']: self.fault('void_nesting'); return
        if len(self.stack) == 1 or self.stack[-1].tag != tag:
            self.fault('invalid_structure'); return
        self.stack.pop()
    def finish(self):
        self.close()
        if len(self.stack) != 1: self.fault('invalid_structure')
        elements = self.root.elements()
        if self.doctypes != 1 or len(elements) != 1 or elements[0].tag != 'html': self.fault('root_boundary')
        elif [node.tag for node in elements[0].elements()] != ['head', 'body']: self.fault('root_boundary')
        return self


def _first_error(reasons):
    if reasons:
        raise _Failure(min(reasons, key=lambda reason: (_REASONS[reason][0], _PHASES[_REASONS[reason][0]-1][1].split().index(reason))))


def _failure_result(reason):
    rank, status = _REASONS[reason]
    return dict(leaf_status=status, reason=reason, priority_rank=rank, body=None, receipt=None,
                c013_status='not_constructed', synthetic_only=True, real_origin_verified=False,
                real_permission_verified=False, complete_original_scope=False, sla='unverified')


def parse_template_render(*, html, context, private, expected_body, expected,
                          anchor, now, envelope_contract, schema_contract,
                          evidence_documents):
    """只签合成模板比较；缺失、冲突、未知或未建模观察均无 receipt。"""
    try:
        schema = _read_json(schema_contract, 131072)
        envelope = _read_json(envelope_contract, 524288, maximum_nodes=24000)
        _need(type(schema) is dict and type(schema.get('$defs')) is dict and type(envelope) is dict and type(envelope.get('grammar')) is dict, 'invalid_structure')
        definitions = schema['$defs']
        _need({'Limits','PrivateInput','ResponseContext','Marker','PrivateTuple','RowBinding','SyntheticProof','Body','DetailContext','CalendarContext'} <= set(definitions), 'unknown_profile')
        _need(type(context) is dict and 'limits' in context and _schema_matches(context['limits'], definitions['Limits'], definitions), 'invalid_limits')
        limits = context['limits']
        _need(all(limits[key] <= value for key, value in _MAXIMUMS.items()), 'invalid_limits')
        _need(type(html) is bytes, 'invalid_structure')
        _need(len(html) <= limits['wire_bytes'], 'wire_limit')
        try: text = html.decode('utf-8', errors='strict')
        except UnicodeDecodeError: raise _Failure('invalid_utf8') from None
        _need(len(text.encode('utf-8')) <= limits['decoded_bytes'], 'decoded_limit')
        dom = _DOM(envelope['grammar']); dom.feed(text); dom.finish()
        _first_error([key + '_limit' for key in ('depth', 'nodes', 'markers', 'fields', 'rows') if dom.counts[key] > limits[key]])
        marker_values, script_issues = _scripts(dom, envelope, context.get('page_type'))
        _first_error(dom.errors + script_issues)
        documents = _read_json(evidence_documents, 262144)
        _need(type(documents) is dict and set(documents) == {'origins', 'permissions', 'f01_documents', 'display_mappings'}, 'invalid_structure')
        _need(all(type(value) is dict and len(value) <= 8 for value in documents.values()), 'origin_permission_unbound')
        _need(_schema_matches(context, definitions['ResponseContext'], definitions), 'context_schema')
        _need(context['body_state'] == 'normal', 'response_incomplete')
        _need(context['status'] not in (403, 404, 500), 'denial_unverified')
        _need(context['status'] == 200, 'redirect_unbound')
        _need(context['clock_error_ms'] is not None, 'clock_unknown')
        for index, value in enumerate((context, private, expected_body, expected, anchor)):
            if index == 1: _guard_private_input(value)
            else: _guard_json(value)
        _need(_schema_matches(private, definitions['PrivateInput'], definitions), 'unknown_profile')
        _need(_schema_matches(private['template_context'], definitions['DetailContext' if context['page_type']=='detail' else 'CalendarContext'], definitions), 'unknown_profile')
        if all(target['score_state']=='required_bound' for target in context['targets']):
            _need(marker_values or _nodes(dom.root,attr='data-o03-role'), 'capability_absence_unverified')
        _full_envelope(dom, envelope, context, private)
        marker_node, marker, tuple_value, origin, mapping, loaded = _bind(marker_values, context, private, documents, schema, now, envelope_contract, schema_contract)
        for node in _nodes(dom.root,attr='data-o03-row'):
            _row_identity(node,tuple_value,origin,private,definitions,event=node.attrs.get('data-o03-role')=='calendar.result.card')
        body = _extract_body(dom, marker_node, marker, tuple_value, origin, mapping, private, context, definitions)
        _need(_schema_matches(body, definitions['Body'], definitions), 'wrapper_mismatch')
        _need(_schema_matches(expected_body, definitions['Body'], definitions), 'content_mismatch')
        _need(body == expected_body, 'content_mismatch')
        digest = _digest(body)
        _need(digest == marker['content_digest'], 'body_digest_mismatch')
        from stable.services import public_probe_contracts as c013
        from stable.services import content_contracts as f01
        receipt = dict(schema_version='o03.read.v1',scope_ref=context['scope_ref'],candidate_sha=tuple_value['candidate_sha'],
                       expectation_sha=_digest(expected),input_version=tuple_value['input_version'],entity=loaded['snapshot']['entity'],
                       capability=tuple_value['capability'],surface_ref=tuple_value['surface_ref'],audience_ref=tuple_value['audience_ref'],
                       generation=tuple_value['generation'],receipt_id='parsed-template:'+private['profile_ref'],
                       request_started_at=context['request_started_at'],response_completed_at=context['response_completed_at'],
                       clock_error_ms=context['clock_error_ms'],status=context['status'],complete=True,conflict=False,denial_verified=False,
                       marker={key:marker[key] for key in ('revision_ref','permission_version','content_digest')},body_digest=digest)
        try: comparison = c013.compare_public(expected,receipt,anchor=anchor,as_of=now).to_dict()
        except f01.ContractError: raise _Failure('c013_not_verified') from None
        _need(comparison['public_read_verified'] is True,'c013_not_verified')
        return dict(leaf_status='template_fixture_verified',reason='matching_template_fixture_only',priority_rank=None,
                    body=body,body_digest=digest,receipt=receipt,c013_status=comparison['status'],comparison=comparison,
                    synthetic_only=True,real_origin_verified=False,real_permission_verified=False,complete_original_scope=False,sla='unverified')
    except _Failure as exc:
        return _failure_result(exc.reason)
    except (KeyError, TypeError, ValueError, IndexError, RecursionError):
        # Malformed closed input must never escape as a successful or partial receipt.
        return _failure_result('invalid_structure')


_WORDS = re.compile(r'''"[^"]*"|'[^']*'|[^\s]+''')
_PATH = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\.\d+)*$')


def _words(source):
    return _WORDS.findall(source)


def _compile_program(tokens):
    """仅固定 token 列表的有限 AST，不编译 Python 或任何可调用表达式。"""
    for index, token in enumerate(tokens):
        _need(type(token) is dict and set(token) == {'index', 'kind', 'source'}
              and type(token['index']) is int and token['index'] == index
              and token['kind'] in {'literal', 'directive', 'variable'} and type(token['source']) is str,
              'unknown_profile')
    def parse(index, stops=()):
        nodes = []
        while index < len(tokens):
            token = tokens[index]; source = token['source']
            if token['kind'] == 'literal': nodes.append(('literal', source)); index += 1; continue
            if token['kind'] == 'variable':
                _need(source.startswith('{{') and source.endswith('}}'), 'unknown_profile')
                nodes.append(('variable', source[2:-2].strip())); index += 1; continue
            _need(source.startswith('{%') and source.endswith('%}'), 'unknown_profile')
            words = _words(source[2:-2].strip()); _need(bool(words), 'unknown_profile')
            tag = words[0]
            if tag in stops: return nodes, index, words
            if tag == 'if':
                branches = []; condition = ' '.join(words[1:]); index += 1
                while True:
                    body, index, end = parse(index, ('elif', 'else', 'endif'))
                    branches.append((condition, body)); _need(end is not None, 'unknown_profile')
                    if end[0] == 'elif': condition = ' '.join(end[1:]); index += 1; continue
                    if end[0] == 'else':
                        body, index, end = parse(index + 1, ('endif',)); _need(end is not None, 'unknown_profile')
                        branches.append((None, body))
                    _need(end[0] == 'endif', 'unknown_profile'); index += 1; break
                nodes.append(('if', branches)); continue
            if tag == 'for':
                _need(len(words) == 4 and words[2] == 'in' and _PATH.fullmatch(words[1]) is not None, 'unknown_profile')
                body, index, end = parse(index + 1, ('empty', 'endfor')); _need(end is not None, 'unknown_profile')
                empty = []
                if end[0] == 'empty': empty, index, end = parse(index + 1, ('endfor',))
                _need(end is not None and end[0] == 'endfor', 'unknown_profile')
                nodes.append(('for', words[1], words[3], body, empty)); index += 1; continue
            if tag in {'block', 'timezone'}:
                _need(len(words) == 2, 'unknown_profile')
                body, index, end = parse(index + 1, ('end' + tag,)); _need(end is not None, 'unknown_profile')
                nodes.append((tag, words[1], body)); index += 1; continue
            _need(tag in {'load', 'extends', 'include', 'url', 'static', 'race_field', 'race_grade_class'}, 'unknown_profile')
            nodes.append(('tag', words)); index += 1
        return nodes, index, None
    nodes, index, end = parse(0)
    _need(index == len(tokens) and end is None, 'unknown_profile')
    return nodes


class _Program:
    """固定受审模板语法的纯解释器；所有数组/属性来自独立 DTO。"""
    def __init__(self, envelope, context):
        self.envelope = envelope; self.context = dict(context)
        self.context.update(self.context.pop('shared'))
        self.programs = {}; self.operations = 0; self.loop_depth = 0
        for item in envelope['template_programs']:
            _need(type(item) is dict and set(item) == {'template', 'source', 'tokens'}, 'unknown_profile')
            name = item['template'].removeprefix('server/stable/templates/')
            _need(name in {'stable/public/base.html', 'stable/public/race_detail.html', 'stable/public/race_calendar.html', 'stable/public/_article_card.html'} and name not in self.programs, 'unknown_profile')
            raw = ''.join(token['source'] for token in item['tokens']).encode('utf-8')
            _need(_hash(raw) == item['source']['sha256'] and len(raw) == item['source']['bytes'], 'unknown_profile')
            self.programs[name] = _compile_program(item['tokens'])
        _need(len(self.programs) == 4, 'unknown_profile')
    def step(self):
        self.operations += 1; _need(self.operations <= 30000, 'nodes_limit')
    def atom(self, token, context):
        if len(token) >= 2 and token[0] in '\"\'' and token[-1] == token[0]:
            return token[1:-1]
        if re.fullmatch(r'-?\d+', token): return int(token)
        if token == 'True': return True
        if token == 'False': return False
        if token == 'None': return None
        _need(_PATH.fullmatch(token) is not None, 'unknown_profile')
        parts = token.split('.'); value = context.get(parts[0], '')
        for key in parts[1:]:
            if type(value) is dict: value = value.get(key, '')
            elif type(value) is list and key.isdecimal() and int(key) < len(value): value = value[int(key)]
            elif value in (None, ''): return ''
            else: raise _Failure('unknown_profile')
        _need(not callable(value), 'unknown_profile')
        return value
    def date_format(self, value, format_string):
        if not value: return ''
        _need(type(value) is str, 'unknown_profile')
        try:
            stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError: raise _Failure('unknown_profile') from None
        if stamp.tzinfo is not None:
            # 固定部署标签 Asia/Shanghai；此合成 2026 子域无 DST。
            from datetime import timezone, timedelta
            stamp = stamp.astimezone(timezone(timedelta(hours=8)))
        codes = {'Y': str(stamp.year), 'm': '%02d' % stamp.month, 'n': str(stamp.month),
                 'd': '%02d' % stamp.day, 'j': str(stamp.day), 'H': '%02d' % stamp.hour,
                 'i': '%02d' % stamp.minute, 'D': ('星期一','星期二','星期三','星期四','星期五','星期六','星期日')[stamp.weekday()]}
        _need(format_string in {'Y-m-d', 'm-d H:i', 'Y-m-d H:i', 'm月d日', 'Y年', 'n月j日', 'D', 'Y年n月j日', 'n月', 'j日'}, 'unknown_profile')
        return ''.join(codes.get(char, char) for char in format_string)
    def value(self, expression, context, *, marker_slot=False):
        pieces = re.split(r'\|(?=(?:[^\"\']|\"[^\"]*\"|\'[^\']*\')*$)', expression)
        value = self.atom(pieces[0], context)
        for item in pieces[1:]:
            parts = item.split(':', 1); name = parts[0]
            argument = self.value(parts[1], context) if len(parts) == 2 else None
            _need(name in {'default', 'date', 'length', 'slice', 'stringformat', 'truncatechars', 'escapejs'}, 'unknown_profile')
            if name == 'default': value = value or argument
            elif name == 'date': value = self.date_format(value, argument)
            elif name == 'length': value = len(value)
            elif name == 'slice':
                _need(type(value) in (list, str) and type(argument) is str and re.fullmatch(r'-?\d*:-?\d*', argument), 'unknown_profile')
                left, right = argument.split(':'); value = value[slice(int(left) if left else None, int(right) if right else None)]
            elif name == 'stringformat': _need(argument == 's', 'unknown_profile'); value = str(value)
            elif name == 'truncatechars':
                _need(type(argument) is int and argument == 92, 'unknown_profile')
                value = str(value); value = value if len(value) <= argument else value[:argument-1] + '…'
            elif name == 'escapejs':
                _need(marker_slot and expression.split('|')[0] in {'public_probe_projection.marker.' + key for key in _MARKER_KEYS}, 'unknown_profile')
                value = _escapejs(value)
        return value
    def condition(self, source, context):
        words = _words(source)
        def branch(parts):
            if 'or' in parts:
                index = parts.index('or'); return branch(parts[:index]) or branch(parts[index+1:])
            if 'and' in parts:
                index = parts.index('and'); return branch(parts[:index]) and branch(parts[index+1:])
            _need(len(parts) in (1, 3), 'unknown_profile')
            left = self.value(parts[0], context)
            if len(parts) == 1: return bool(left)
            right = self.value(parts[2], context)
            _need(parts[1] in ('==', '!=', '>'), 'unknown_profile')
            return left == right if parts[1] == '==' else left != right if parts[1] == '!=' else left > right
        return branch(words)
    def field(self, words, context):
        _need(len(words) in (3, 4), 'unknown_profile')
        obj = self.value(words[1], context); name = self.value(words[2], context)
        _need(type(obj) is dict and type(name) is str, 'unknown_profile')
        legacy = self.value(words[3], context) if len(words) == 4 else ''
        if name == 'grade': return obj['public_display']['grade']['text']
        if name == 'date': return obj['local_date'] or '北京时间待定'
        if name == 'time':
            value = obj['public_time_label']
            _need(type(value) is str and (value == '北京时间待定' or re.fullmatch(r'\d\d:\d\d（北京时间）', value)), 'unknown_profile')
            return value
        if name == 'eligibility':
            raw = obj['eligibility_text']
            # 此受审 finite DTO 子域只包含已审三岁及以上；未知语义不猜。
            _need(raw in ('', '3岁及以上'), 'unknown_profile')
            return raw
        if not context['race_information_enabled']: return legacy
        return obj['public_display'][name]['text']
    def render_nodes(self, nodes, context, blocks=None):
        output = []
        for node in nodes:
            self.step(); kind = node[0]
            if kind == 'literal': output.append(node[1])
            elif kind == 'variable':
                is_marker = node[1].startswith('public_probe_projection.marker.')
                value = self.value(node[1], context, marker_slot=is_marker)
                value = '' if value is None else str(value)
                output.append(value if is_marker else escape(value, quote=True).replace('&#x27;', '&#x27;'))
            elif kind == 'if':
                for condition, body in node[1]:
                    if condition is None or self.condition(condition, context):
                        output.append(self.render_nodes(body, dict(context), blocks)); break
            elif kind == 'for':
                values = self.value(node[2], context); _need(type(values) is list and len(values) <= 512, 'unknown_profile')
                self.loop_depth += 1; _need(self.loop_depth <= 3, 'unknown_profile')
                if not values: output.append(self.render_nodes(node[4], dict(context), blocks))
                for index, value in enumerate(values):
                    child = dict(context); child[node[1]] = value
                    child['forloop'] = {'counter0': index, 'parentloop': context.get('forloop', {})}
                    output.append(self.render_nodes(node[3], child, blocks))
                self.loop_depth -= 1
            elif kind == 'block': output.append(self.render_nodes((blocks or {}).get(node[1], node[2]), dict(context), blocks))
            elif kind == 'timezone':
                _need(node[1] == '\"Asia/Shanghai\"', 'unknown_profile')
                output.append(self.render_nodes(node[2], dict(context), blocks))
            elif kind == 'tag':
                words = node[1]; tag = words[0]
                if tag == 'load':
                    _need(set(words[1:]) <= {'static', 'race_information', 'tz'}, 'unknown_profile')
                elif tag == 'extends':
                    _need(words == ['extends', '\"stable/public/base.html\"'], 'unknown_profile')
                elif tag == 'include':
                    _need(words == ['include', '\"stable/public/_article_card.html\"', 'with', 'article=article'], 'unknown_profile')
                    output.append(self.render_nodes(self.programs['stable/public/_article_card.html'], dict(context), blocks))
                elif tag == 'url':
                    _need(len(words) == 2, 'unknown_profile'); key = self.atom(words[1], context)
                    _need(key in context['url_map'], 'unknown_profile'); output.append(escape(context['url_map'][key], quote=True))
                elif tag == 'static':
                    _need(words == ['static', "'stable/public.css'"], 'unknown_profile'); output.append(escape(context['url_map']['static_css'], quote=True))
                elif tag == 'race_grade_class':
                    _need(len(words) == 2, 'unknown_profile'); obj = self.value(words[1], context)
                    code = obj['public_display']['grade']['code']
                    output.append('g'+code[-1] if code in {'G1','G2','G3','JG1','JG2','JG3','JPN1','JPN2','JPN3'} else 'g-other')
                elif tag == 'race_field':
                    if words[-2:] == ['as', 'eligibility']:
                        context['eligibility'] = self.field(words[:-2], context)
                    else: output.append(escape(str(self.field(words, context)), quote=True))
        return ''.join(output)
    def render(self, page):
        name = 'stable/public/race_' + ('detail' if page == 'detail' else 'calendar') + '.html'
        child = self.programs[name]
        blocks = {node[1]: node[2] for node in child if node[0] == 'block'}
        _need(set(blocks) == {'title', 'content'}, 'unknown_profile')
        return self.render_nodes(self.programs['stable/public/base.html'], dict(self.context), blocks)


def _nodes(root, *, tag=None, class_name=None, attr=None, value=None):
    return [node for node in root.walk() if (tag is None or node.tag == tag)
            and (class_name is None or node.has_class(class_name))
            and (attr is None or attr in node.attrs and (value is None or node.attrs[attr] == value))]


def _one(nodes, reason):
    _need(len(nodes) == 1, reason)
    return nodes[0]


def _scripts(dom, envelope, page):
    markers = []; issues = []; calendar = []
    for node in _nodes(dom.root, tag='script'):
        if 'data-o03-marker' in node.attrs:
            if node.attrs != {'type': 'application/json', 'data-o03-marker': 'result-family'}: issues.append('unexpected_script')
            if node.elements(): issues.append('invalid_structure')
            markers.append(node)
        else:
            calendar.append(node)
            if page != 'calendar' or node.attrs or len(calendar) > 1: issues.append('unexpected_script')
            elif node.text() != envelope['script']['raw_inner_utf8']: issues.append('script_bytes_mismatch')
            if node.parent.tag != 'main' or not node.parent.has_class('race-page'): issues.append('invalid_structure')
            else:
                siblings = node.parent.elements(); index = siblings.index(node)
                if index == 0 or not siblings[index-1].has_class('date-axis') or index+1 >= len(siblings) or siblings[index+1].tag != 'form': issues.append('invalid_structure')
    for node in _nodes(dom.root, attr='data-o03-role', value='detail.result.nav'):
        if not (node.tag == 'a' and node.parent.tag == 'nav' and node.parent.has_class('race-subnav')): issues.append('invalid_structure')
    # Collect JSON faults too; rank/reason order must not depend on inspection order.
    marker_values = []
    for node in markers:
        try: marker_values.append((node, _read_json(node.text().encode('utf-8'), 262144)))
        except _Failure as exc: issues.append(exc.reason)
    return marker_values, issues


def _membership(dom, context, private):
    _need(_digest({key: context[key] for key in ('scope_ref','page_type','subject_mapping_ref','members','targets')}) == context['scope_sha256'], 'membership_mismatch')
    refs = [target['target_ref'] for target in context['targets']]
    _need(len(refs) == len(set(refs)), 'membership_mismatch')
    members = context['members']
    _need(len({member['member_ref'] for member in members}) == len(members), 'membership_mismatch')
    if context['page_type'] == 'detail':
        _need(members == [], 'membership_mismatch')
    else:
        cards = _nodes(dom.root, tag='a', class_name='cal-card')
        groups = private['template_context']['groups']
        approved = [(gi, ci, event) for gi, group in enumerate(groups) for ci, event in enumerate(group['events'])]
        _need(len(cards) == len(members) == len(approved), 'membership_mismatch')
        for card, member, (gi, ci, event) in zip(cards, members, approved):
            _need(member['group_index'] == gi and member['card_index'] == ci and member['dto_ref'] == event['dto_ref']
                  and card.attrs.get('href') == member['subject'] == event['public_path'], 'membership_mismatch')
            parent = card.parent
            _need(parent.has_class('agenda-races') and parent.parent.has_class('agenda-day'), 'membership_mismatch')
    _need(bool(context['targets']), 'no_required_targets')
    for target in context['targets']:
        related = [member for member in members if member['target_ref'] == target['target_ref']]
        if context['page_type'] == 'calendar':
            _need(len(related) == 1 and target['member_ref'] == related[0]['member_ref'] and target['subject'] == related[0]['subject'], 'membership_mismatch')
    _need(len(context['targets']) == 1, 'unknown_profile')  # 不凭单份 profile 给多个 target 自签全 scope。


def _leaf_classes(node):
    return (node.has_class('winner-ribbon') or node.has_class('winner-name') or node.has_class('winner-crew')
            or node.has_class('podium-line') or node.has_class('race-result-status')
            or node.attrs.get('id') == 'results'
            or node.tag == 'a' and node.attrs.get('href') == '#results' and node.parent.has_class('race-subnav'))


def _envelope_tree(node, subject):
    """完整非叶片精确树；只有声明位置内容由后续完整字段/包装器阶段观察。"""
    if node.tag == 'script' and 'data-o03-marker' in node.attrs: return None
    attrs = dict(node.attrs)
    leaf = _leaf_classes(node)
    card = node.has_class('cal-card') and attrs.get('href') == subject
    status = node.has_class('cal-card-status') and node.parent.has_class('cal-card') and node.parent.attrs.get('href') == subject
    if leaf or card:
        for key in ('data-o03-role','data-o03-part','data-o03-row','data-o03-field'): attrs.pop(key, None)
    children = []
    if leaf or status: children = [('#declared-leaf',)]
    else:
        for child in node.children:
            if isinstance(child, _Node):
                value = _envelope_tree(child, subject)
                if value is not None: children.append(value)
            elif _norm(child): children.append(('#text', _norm(child)))
    return (node.tag, tuple(sorted(attrs.items(), key=lambda item: item[0])), tuple(children))


def _full_envelope(dom, envelope, context, private):
    profile = private['profile']; data = private['template_context']
    _need(profile['envelope_ref'] == context['envelope_ref'] == envelope['schema_version'], 'unknown_profile')
    _need(private['template_context_sha256'] == _digest(data), 'unknown_profile')
    _need(private['css_sha256'] == envelope['css']['source']['sha256'] and private['css_url'] == envelope['css']['url'], 'css_version_unbound')
    _need(_hash(envelope['css']['raw_utf8'].encode('utf-8')) == private['css_sha256'], 'css_version_unbound')
    _membership(dom, context, private)
    subject = context['targets'][0]['subject']
    roles = _nodes(dom.root, attr='data-o03-role')
    allowed = {'detail.result.hero','detail.result.podium','detail.result.stale','detail.result.nav','detail.result.table'} if context['page_type']=='detail' else {'calendar.result.card'}
    _need(all(node.attrs['data-o03-role'] in allowed for node in roles), 'role_structure')
    if context['targets'][0]['score_state'] == 'required_bound':
        if context['page_type'] == 'detail':
            for class_name, role, count in [('winner-ribbon','detail.result.hero',int(profile['declared_hero'])),
                                          ('winner-name','detail.result.hero',int(profile['declared_hero'])),
                                          ('winner-crew','detail.result.hero',int(profile['declared_hero'])),
                                          ('podium-line','detail.result.podium',int(profile['declared_podium_rows']>0)),
                                          ('race-result-status','detail.result.stale',int(profile['declared_stale']))]:
                candidates = _nodes(dom.root, class_name=class_name)
                _need(len(candidates)==count and all(node.attrs.get('data-o03-role')==role for node in candidates), 'role_structure')
            _need(len(_nodes(dom.root, attr='data-o03-role',value='detail.result.table')) == 1
                  and len(_nodes(dom.root, attr='data-o03-role',value='detail.result.nav')) == 1, 'role_structure')
        else:
            _need(len(_nodes(dom.root, attr='data-o03-role',value='calendar.result.card')) == 1, 'role_structure')
    # Expected skeleton uses independently declared guards/cardinality. Dynamic tokens/JSON
    # are holes here and are proven exclusively from actual observations in stage 5/6.
    program = _Program(envelope, data)
    target = context['targets'][0]
    complete = target['score_state']=='required_bound'
    dummy = '0'*64
    program.context['public_probe_projection'] = dict(
        complete=complete,marker=dict(schema_version='o03.render.v1',subject=target['subject'],
        surface_ref=target['surface_ref'],capability=target['capability'],revision_ref='pv2:'+dummy,
        permission_version='pp2:'+dummy,content_digest=dummy),hero_row_token='pr2:'+dummy,
        podium_row_tokens=['pr2:'+dummy]*profile['declared_podium_rows'],
        table_row_tokens=['pr2:'+dummy]*profile['declared_result_rows'],card_row_token='pe2:'+dummy)
    _leaf_shape(dom)
    rendered = program.render(context['page_type'])
    reference = _DOM(envelope['grammar']); reference.feed(rendered); reference.finish(); _first_error(reference.errors)
    _need(_envelope_tree(dom.root, subject) == _envelope_tree(reference.root, subject), 'unmodeled_visible_content')


def _bind(marker_values, context, private, documents, schema, now, envelope_bytes, schema_bytes):
    from stable.services import content_contracts as f01
    defs = schema['$defs']; target = context['targets'][0]
    _need(_schema_matches(documents, defs['EvidenceDocuments'], defs), 'origin_permission_unbound')
    descriptor = private['candidate_descriptor']
    _need(_digest(descriptor) == private['candidate_sha'] == private['profile']['candidate_sha'], 'candidate_binding')
    _need(_hash(envelope_bytes) == descriptor['envelope_sha256'] and _hash(schema_bytes) == descriptor['contract_sha256'], 'candidate_binding')
    for table, refs in [('origins','origin_document_refs'),('permissions','permission_document_refs'),('f01_documents','f01_document_refs'),('display_mappings','display_mapping_refs')]:
        _need(set(documents[table]) <= set(private[refs]), 'origin_permission_unbound')
    _need(target['score_state'] == 'required_bound', 'origin_permission_unbound')
    _need(bool(marker_values), 'missing_marker')
    _need(len(marker_values) == len(context['targets']), 'marker_schema')
    marker_node, marker = marker_values[0]
    _need(_schema_matches(marker, defs['Marker'], defs), 'marker_schema')
    url = private['url_binding']
    _need(context['requested_url'] == url['requested_url'] and context['final_url'] in url['allowed_final_urls']
          and context['page_type'] == url['page_type'] and context['scope_ref'] == url['scope_ref'], 'subject_binding')
    _need(marker['subject'] == target['subject'], 'subject_binding')
    _need(marker['surface_ref'] == target['surface_ref'] and marker['capability'] == target['capability'], 'surface_binding')
    entries = private['revision_token_index'].get(marker['revision_ref'], [])
    _need(type(entries) is list and bool(entries), 'token_unbound')
    _need(len(entries) == 1, 'token_conflict')
    tuple_value = entries[0]
    _need(_schema_matches(tuple_value, defs['PrivateTuple'], defs), 'origin_permission_unbound')
    _need(tuple_value['candidate_sha'] == private['candidate_sha'] and marker['revision_ref'] == 'pv2:'+_digest(tuple_value), 'candidate_binding')
    permission_entries = private['permission_token_index'].get(marker['permission_version'], [])
    _need(bool(permission_entries), 'token_unbound'); _need(len(permission_entries)==1, 'token_conflict')
    _need(permission_entries[0] == tuple_value, 'token_conflict')
    _need(marker['permission_version'] == 'pp2:'+_digest({'tuple_sha256':_digest(tuple_value),'permission_sha256':tuple_value['permission_sha256']}), 'token_unbound')
    for key in ('subject','target_key','F01_document_ref','origin_ref','permission_ref','display_mapping_ref','surface_ref','capability','generation'):
        _need(tuple_value[key] == target[key], 'origin_permission_unbound' if key in {'target_key','origin_ref','permission_ref','F01_document_ref'} else 'mapping_binding' if key=='display_mapping_ref' else 'generation_binding' if key=='generation' else 'surface_binding')
    _need(tuple_value['audience_ref']==context['audience_ref']=='anonymous', 'origin_permission_unbound')
    origin = documents['origins'].get(tuple_value['origin_ref']); permission = documents['permissions'].get(tuple_value['permission_ref'])
    mapping = documents['display_mappings'].get(tuple_value['display_mapping_ref']); document = documents['f01_documents'].get(tuple_value['F01_document_ref'])
    _need(all(value is not None for value in (origin,permission,mapping,document)), 'origin_permission_unbound')
    _need(_digest(origin)==tuple_value['origin_sha256'] and _digest(permission)==tuple_value['permission_sha256'], 'origin_permission_unbound')
    _need(_digest(mapping)==tuple_value['display_mapping_sha256'], 'mapping_binding')
    _need(origin['synthetic_only'] is True and origin['complete_under_fixture_rule_only'] is True
          and origin['target_key']==tuple_value['target_key']==origin['raw_material']['target_key']
          and _digest(origin['raw_material'])==origin['raw_material_sha256'], 'origin_permission_unbound')
    try: loaded = f01.parse_input(document).to_dict()
    except f01.ContractError: raise _Failure('origin_permission_unbound') from None
    _need(loaded['input_version']==tuple_value['input_version'] and loaded['snapshot']['entity']['canonical_id']==tuple_value['target_key'], 'origin_permission_unbound')
    materials = [item for item in loaded['snapshot']['materials'] if item['revision_ref']==tuple_value['origin_ref'] and item['capability']==tuple_value['capability']]
    _need(len(materials)==1 and materials[0]['completeness']=='complete' and materials[0]['validation']=='passed', 'origin_permission_unbound')
    participants = origin['raw_material']['participants']; profile=private['profile']
    _need(bool(participants) and len({row['participant_ref'] for row in participants})==len(participants)
          and all(type(row['source_horse_number']) is str and row['source_horse_number'] and type(row['source_horse_name']) is str and row['source_horse_name'] for row in participants), 'origin_permission_unbound')
    _need([item['stable_key'] for item in materials[0]['data']['participants']]==[row['participant_ref'] for row in participants], 'origin_permission_unbound')
    _need(all(item['horse_ref']==row['horse_ref'] and item['status']==row['normalized_status'] for item,row in zip(materials[0]['data']['participants'],participants)), 'origin_permission_unbound')
    _need(any(item['artifact_sha256']==origin['raw_material_sha256'] and item['capability']==tuple_value['capability'] and not item['contract_ref']['revoked'] for item in loaded['snapshot']['evidence']), 'origin_permission_unbound')
    _need(type(permission['permission_generation']) is int and permission['allowed'] is True
          and permission['target_key']==tuple_value['target_key'] and permission['origin_ref']==tuple_value['origin_ref']
          and permission['capability']==tuple_value['capability'] and permission['audience_ref']=='anonymous'
          and tuple_value['surface_ref'] in permission['allowed_surfaces'], 'origin_permission_unbound')
    from stable.services import public_probe_contracts as c013
    _need(c013._stamp(permission['valid_from']) <= c013._stamp(now) < c013._stamp(permission['valid_until']), 'permission_expired')
    _need(mapping['synthetic_only'] is True and mapping['origin_ref']==tuple_value['origin_ref'] and mapping['presentation_mode']==profile['presentation_mode']
          and mapping['body_contract_version']==tuple_value['body_contract_version']=='o03.result-template-body.v1', 'mapping_binding')
    _need([row['participant_ref'] for row in mapping['ordered_rows']]==profile['ordered_participant_refs']==[row['participant_ref'] for row in participants], 'origin_permission_unbound')
    if context['page_type']=='detail':
        rows=private['template_context']['results']
        _need(len(rows)==len(participants) and private['template_context']['top_results']==rows[:5], 'origin_permission_unbound')
        for row, raw, approved in zip(rows,participants,mapping['ordered_rows']):
            _need(row['participant_ref']==raw['participant_ref'] and row['horse_number']==raw['source_horse_number'] and row['horse_name']==raw['source_horse_name'], 'origin_permission_unbound')
            for field, name in [('jockey_name','jockey_name'),('trainer_name','trainer_name'),('finish_time','finish_time'),('margin','margin'),('odds','odds_value'),('popularity','popularity')]:
                _need(row[name]==(raw['source_fields'][field] or ''), 'origin_permission_unbound')
            if profile['presentation_mode']=='strict_display_v1':
                _need(all(row['public_display'][key]['text']==value for key,value in approved['cells'].items()), 'mapping_binding')
        winner=private['template_context']['winner']
        _need(winner is None or winner==rows[0], 'origin_permission_unbound')
    return marker_node, marker, tuple_value, origin, mapping, loaded


def _row_identity(node, tuple_value, origin, private, definitions, *, event=False):
    token = node.attrs.get('data-o03-row')
    _need(type(token) is str and token in private['row_token_index'], 'token_unbound')
    row = private['row_token_index'][token]
    _need(_schema_matches(row, definitions['RowBinding'], definitions), 'row_identity_unbound')
    _need(row['tuple_sha256']==_digest(tuple_value) and token==('pe2:' if event else 'pr2:')+_digest(row), 'token_unbound')
    _need(row['generation']==tuple_value['generation'], 'generation_binding')
    proofs = private['proof_documents']
    _need(len({proof['proof_ref'] for proof in proofs})==len(proofs), 'row_identity_unbound')
    documents = {proof['proof_ref']:proof for proof in proofs}
    for ref, is_event in [(row['proof_ref'],event),(row['event_proof_ref'],True)]:
        proof=documents.get(ref)
        _need(proof is not None and _schema_matches(proof,definitions['SyntheticProof'],definitions), 'row_identity_unbound')
        _need(proof['target_key']==tuple_value['target_key'] and proof['F01_document_ref']==tuple_value['F01_document_ref']
              and proof['origin_ref']==tuple_value['origin_ref'] and proof['generation']==tuple_value['generation']
              and proof['synthetic_only'] is True and proof['real_identity_authenticated'] is False, 'row_identity_unbound')
        if is_event:
            _need(proof['participant_ref'] is None and proof['horse_ref'] is None, 'row_identity_unbound')
        else:
            _need(proof['participant_ref']==row['participant_ref'] and proof['horse_ref']==row['horse_ref']
                  and origin['participant_proof_refs'].get(row['participant_ref'])==ref, 'row_identity_unbound')
    if event: _need(row['participant_ref'] is None and row['horse_ref'] is None, 'row_identity_unbound')
    else:
        matching=[item for item in origin['raw_material']['participants'] if item['participant_ref']==row['participant_ref']]
        _need(len(matching)==1 and matching[0]['horse_ref']==row['horse_ref'], 'row_identity_unbound')
    return row


def _fields(node, names, optional=()):
    fields = _nodes(node, attr='data-o03-field')
    counts = {name: [item for item in fields if item.attrs['data-o03-field']==name] for name in names}
    issues=[]
    if any(not counts[name] for name in names if name not in optional): issues.append('missing_field')
    if any(len(values)>1 for values in counts.values()): issues.append('duplicate_field')
    if any(item.attrs['data-o03-field'] not in names for item in fields): issues.append('duplicate_field')
    _first_error(issues)
    return {name: _norm(values[0].text()) if values else None for name,values in counts.items()}


def _extract_body(dom, marker_node, marker, tuple_value, origin, mapping, private, context, definitions):
    profile=private['profile']
    body=dict(schema_version='o03.result-template-body.v1',subject=marker['subject'],surface_ref=marker['surface_ref'],
              capability=marker['capability'],presentation_mode=profile['presentation_mode'],roles=[])
    if context['page_type']=='calendar':
        card=_one(_nodes(dom.root,attr='data-o03-role',value='calendar.result.card'),'missing_role')
        _row_identity(card,tuple_value,origin,private,definitions,event=True)
        _need(card.parent==marker_node.parent and marker_node in card.parent.elements()
              and card.parent.elements().index(card)==card.parent.elements().index(marker_node)+1,'related_role_mismatch')
        status=_one(_nodes(card,class_name='cal-card-status'),'missing_field')
        values=_fields(status,('status','winner'),optional=('winner',))
        status_node=_one(_nodes(status,attr='data-o03-field',value='status'),'missing_field')
        _need(status_node.tag=='strong' and status_node.parent==status,'column_contract')
        smalls=[node for node in status.elements() if node.tag=='small']
        winner_visible=None
        if values['winner'] is not None:
            small=_one(smalls,'wrapper_mismatch'); winner_visible=_norm(small.text())
            _need(winner_visible=='冠军 '+values['winner'],'wrapper_mismatch')
        _need(set(node.tag for node in status.elements())<={'strong','small'} and all(not _norm(child) for child in status.children if isinstance(child,str)),'wrapper_mismatch')
        body['roles']=[dict(role='calendar.result.card',row_token=card.attrs['data-o03-row'],
                           fields=dict(href=card.attrs['href'],status=values['status'],winner=values['winner']),winner_visible_text=winner_visible)]
        return body
    main=_one(_nodes(dom.root,tag='main',class_name='race-page'),'missing_role')
    _need(marker_node.parent==main and main.elements()[0]==marker_node,'related_role_mismatch')
    hero_parts=[node for node in _nodes(dom.root,attr='data-o03-role',value='detail.result.hero')]
    if profile['declared_hero']:
        parts={name:[node for node in hero_parts if node.attrs.get('data-o03-part')==name] for name in ['ribbon','name','crew']}
        _need(all(len(values)==1 for values in parts.values()) and len(hero_parts)==3,'duplicate_role' if len(hero_parts)>3 else 'missing_role')
        ribbon,name,crew=[parts[key][0] for key in ['ribbon','name','crew']]
        _need(ribbon.parent==name.parent==crew.parent and ribbon.parent.has_class('race-hero'),'related_role_mismatch')
        _need(ribbon.attrs.get('data-o03-row')==name.attrs.get('data-o03-row')==crew.attrs.get('data-o03-row'),'related_role_mismatch')
        fields=_fields(ribbon,('ribbon',));fields.update(_fields(name,('horse_name',)))
        fields.update(_fields(crew,('jockey_name','trainer_name','finish_time','popularity'),optional=('jockey_name','trainer_name','finish_time','popularity')))
        observed_crew=[]
        labels={'jockey_name':'骑师','trainer_name':'练马师','finish_time':'完赛时间','popularity':'热门排名' if profile['presentation_mode']=='strict_display_v1' else '人气'}
        for item in crew.elements():
            _need(item.tag=='div' and item.attrs=={} and [child.tag for child in item.elements()]==['span','b'],'wrapper_mismatch')
            label,value=item.elements();key=value.attrs.get('data-o03-field')
            _need(key in labels and _norm(label.text())==labels[key],'wrapper_mismatch')
            visible=_norm(value.text());observed_crew.append(dict(field=key,label=_norm(label.text()),visible_text=visible))
            if key=='popularity' and profile['presentation_mode']=='legacy':
                match=re.fullmatch(r'第 ([0-9]+) 人气',visible);_need(match is not None,'wrapper_mismatch');fields[key]=match.group(1)
        _need([item['field'] for item in observed_crew]==[key for key in labels if fields[key] is not None],'wrapper_mismatch')
        body['roles'].append(dict(role='detail.result.hero',row_token=ribbon.attrs['data-o03-row'],fields=fields,crew=observed_crew))
    if profile['declared_podium_rows']>0:
        podium=_one(_nodes(dom.root,attr='data-o03-role',value='detail.result.podium'),'missing_role')
        rows=podium.elements();_need(len(rows)==profile['declared_podium_rows'] and all(node.tag=='span' for node in rows),'row_cardinality')
        result=[]
        for node in rows:
            fields=_fields(node,('position','horse_name','margin'),optional=('margin',));visible=_norm(node.text())
            wanted=fields['position']+'名 '+fields['horse_name']+('（'+fields['margin']+'）' if fields['margin'] is not None else '')
            _need(visible==wanted,'wrapper_mismatch');result.append(dict(row_token=node.attrs['data-o03-row'],cells=fields,visible_text=visible))
        body['roles'].append(dict(role='detail.result.podium',rows=result))
    if profile['declared_stale']:
        stale=_one(_nodes(dom.root,attr='data-o03-role',value='detail.result.stale'),'missing_role')
        _need(_norm(stale.text())=='数据可能已过期','wrapper_mismatch');body['roles'].append(dict(role='detail.result.stale',text=_norm(stale.text())))
    nav=_one(_nodes(dom.root,attr='data-o03-role',value='detail.result.nav'),'missing_role')
    values=_fields(nav,('text',));_need(nav.attrs.get('href')=='#results' and values['text']=='赛果','wrapper_mismatch')
    body['roles'].append(dict(role='detail.result.nav',fields=dict(text=values['text'],href=nav.attrs['href'])))
    table=_one(_nodes(dom.root,attr='data-o03-role',value='detail.result.table'),'missing_role')
    heading=_one([node for node in table.elements() if node.tag=='h2'],'column_contract')
    grid=_one(_nodes(table,tag='table',class_name='data-table'),'column_contract')
    _need([node.tag for node in grid.elements()]==['thead','tbody'],'column_contract')
    thead,tbody=grid.elements();header=_one(thead.elements(),'column_contract')
    labels=['名次','马号','马名','骑师','练马师','时间','差距','赔率 / 热门排名' if profile['presentation_mode']=='strict_display_v1' else '赔率 / 人气']
    keys=['position','horse_number','horse_name','jockey_name','trainer_name','finish_time','margin','odds_popularity']
    _need(header.tag=='tr' and [node.tag for node in header.elements()]==['th']*8 and [_norm(node.text()) for node in header.elements()]==labels,'column_contract')
    rows=tbody.elements();row_tokens=[node.attrs.get('data-o03-row') for node in rows]
    _need(len(rows)==profile['declared_result_rows'],'row_cardinality')
    _need(len(row_tokens)==len(set(row_tokens)),'duplicate_row')
    # 来源/row identity 已绑定；先保留行数/重复的既定失败，再校 DTO 排名样式。
    positions = {row['participant_ref']: row['display_finish_position']
                 for row in private['template_context']['results']}
    for node in rows:
        participant = private['row_token_index'][node.attrs['data-o03-row']]['participant_ref']
        position = positions[participant]
        medal = 'medal-' + str(position) if position in (1, 2, 3) else ''
        _need(node.attrs.get('class') == medal, 'role_structure')
    result=[];names=keys[:-1]+['odds','popularity']
    for node in rows:
        _need(node.tag=='tr' and [child.tag for child in node.elements()]==['td']*8,'column_contract')
        values=_fields(node,names);cells=node.elements()
        for index,key in enumerate(keys[:-1]):
            declared=_nodes(cells[index],attr='data-o03-field')
            _need(len(declared)==1 and declared[0].attrs['data-o03-field']==key,'column_contract')
            _need(_norm(cells[index].text())==values[key],'wrapper_mismatch')
        last=cells[-1];last_fields=last.elements()
        _need(len(last_fields)==2 and [child.tag for child in last_fields]==['span','span']
              and [child.attrs.get('data-o03-field') for child in last_fields]==['odds','popularity']
              and ''.join(child for child in last.children if isinstance(child,str)).strip(_SPACE)=='/','column_contract')
        _need(all(values[key] not in {'','待核实','-','—'} for key in ('position','horse_number','horse_name')),'required_placeholder')
        result.append(dict(row_token=node.attrs['data-o03-row'],cells=values))
    _need(_norm(heading.text())=='赛果','column_contract')
    body['roles'].append(dict(role='detail.result.table',heading=_norm(heading.text()),columns=[dict(key=key,text=label) for key,label in zip(keys,labels)],rows=result))
    rows_by_token={row['row_token']:row for row in result}
    if profile['declared_hero']:
        hero=body['roles'][0];_need(result and hero['row_token']==result[0]['row_token'],'related_role_mismatch')
        for key,value in hero['fields'].items():
            if key in result[0]['cells'] and value is not None:_need(value==result[0]['cells'][key],'related_role_mismatch')
    for role in body['roles']:
        if role['role']=='detail.result.podium':
            _need([row['row_token'] for row in role['rows']]==[row['row_token'] for row in result[1:3]],'related_role_mismatch')
            for row in role['rows']:
                _need(row['row_token'] in rows_by_token and all(value is None or value==rows_by_token[row['row_token']]['cells'][key] for key,value in row['cells'].items()),'related_role_mismatch')
    return body


def _leaf_shape(dom):
    """叶片 scalar/count 可延后；其余可见节点/属性没有通配洞。"""
    def attrs(node, allowed):
        _need(set(node.attrs) <= set(allowed), 'role_structure')
    def layout(node):
        _need(all(not _norm(child) for child in node.children if isinstance(child,str)), 'unmodeled_visible_content')
    # 固定模板 scalar 叶片仅有文本，不能从任意元素后代拼回相同内容。
    for class_name, tag in (('winner-name', 'div'), ('winner-ribbon', 'span')):
        for node in _nodes(dom.root, class_name=class_name):
            _need(node.tag == tag and node.attrs.get('class') == class_name
                  and not node.elements(), 'role_structure')
            attrs(node, ('class', 'data-o03-role', 'data-o03-part', 'data-o03-row', 'data-o03-field'))
    for node in _nodes(dom.root, attr='data-o03-role', value='detail.result.nav'):
        _need(node.tag == 'a' and node.attrs.get('href') == '#results'
              and not node.elements(), 'role_structure')
        attrs(node, ('href', 'data-o03-role', 'data-o03-field'))
    for crew in _nodes(dom.root,class_name='winner-crew'):
        layout(crew)
        for item in crew.elements():
            _need(item.tag=='div' and [node.tag for node in item.elements()]==['span','b'],'role_structure')
            attrs(item,()); layout(item)
            label,value=item.elements();attrs(label,());attrs(value,('data-o03-field',))
            _need(not label.elements() and not value.elements(),'role_structure')
    for podium in _nodes(dom.root,class_name='podium-line'):
        layout(podium)
        for row in podium.elements():
            _need(row.tag=='span','role_structure');attrs(row,('data-o03-row',))
            children=row.elements()
            _need([node.tag for node in children] in (['span','b'],['span','b','span']),'role_structure')
            for child in children:
                attrs(child,('data-o03-field',));_need(not child.elements(),'role_structure')
    for section in _nodes(dom.root,attr='id',value='results'):
        children=section.elements();_need(len(children)==2 and children[0].tag=='h2' and children[1].has_class('race-table-wrap'),'role_structure');layout(section)
        heading,wrapper=children;attrs(heading,());_need(not heading.elements(),'role_structure')
        attrs(wrapper,('class',));layout(wrapper)
        table=_one(wrapper.elements(),'role_structure');_need(table.tag=='table' and table.attrs=={'class':'data-table'},'role_structure');layout(table)
        _need([node.tag for node in table.elements()]==['thead','tbody'],'role_structure')
        head,body=table.elements();attrs(head,());attrs(body,());layout(head);layout(body)
        tr=_one(head.elements(),'role_structure');_need(tr.tag=='tr','role_structure');attrs(tr,());layout(tr)
        for th in tr.elements():_need(th.tag=='th' and th.attrs=={} and not th.elements(),'role_structure')
        for row in body.elements():
            _need(row.tag=='tr','role_structure');attrs(row,('class','data-o03-row'));layout(row)
            _need(row.attrs.get('class') in ('','medal-1','medal-2','medal-3'),'role_structure')
            for index,cell in enumerate(row.elements()):
                _need(cell.tag=='td','role_structure')
                attrs(cell,('class','data-o03-field'))
                _need(cell.attrs.get('class','')==('num' if index in (1,5) else ''),'role_structure')
                if index==2:
                    strong=_one(cell.elements(),'role_structure');_need(strong.tag=='strong','role_structure');attrs(strong,('data-o03-field',));_need(not strong.elements(),'role_structure')
                elif index==7:
                    for child in cell.elements():_need(child.tag=='span' and not child.elements(),'role_structure');attrs(child,('data-o03-field',))
                else:_need(not cell.elements(),'role_structure')
    for card in _nodes(dom.root,attr='data-o03-role',value='calendar.result.card'):
        status=_one(_nodes(card,class_name='cal-card-status'),'role_structure');layout(status)
        for child in status.elements():
            _need(child.tag in {'strong','small'},'role_structure')
            attrs(child,('data-o03-field',) if child.tag=='strong' else ())
            if child.tag=='strong':_need(not child.elements(),'role_structure')
            else:
                for value in child.elements():_need(value.tag=='span' and not value.elements(),'role_structure');attrs(value,('data-o03-field',))
