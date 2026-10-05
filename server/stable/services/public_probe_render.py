"""来源无关的synthetic结果展示leaf；显式输入，无环境、文件或网络IO。"""
from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urlsplit, parse_qsl
from stable.services import content_contracts as f01
from stable.services import public_probe_contracts as c013

LIMIT_KEYS = 'wire_bytes decoded_bytes depth nodes markers fields rows'.split()
CELL_KEYS = 'position horse_number horse_name jockey_name trainer_name finish_time margin odds popularity'.split()
ROLE_FIELDS = {
    'detail.result.hero': 'ribbon horse_name jockey_name trainer_name finish_time popularity'.split(),
    'detail.result.podium': 'position horse_name margin'.split(),
    'detail.result.table': CELL_KEYS,
    'detail.result.nav': ['text'], 'detail.result.stale': ['text'],
    'calendar.result.card': ['status', 'winner'],
}
TUPLE_KEYS = 'candidate_sha subject target_key F01_document_ref input_version generation origin_ref origin_sha256 permission_ref permission_sha256 display_mapping_ref display_mapping_sha256 surface_ref audience_ref capability body_contract_version'
MARKER_KEYS = 'schema_version subject surface_ref capability revision_ref permission_version content_digest'


class _Failure(Exception):
    def __init__(self, reason, state='unverified'):
        self.reason, self.state = reason, state


def _need(value, reason, state='unverified'):
    if not value: raise _Failure(reason, state)


def _norm(value):
    return re.sub(r'[ \t\n\r\f]+', ' ', unicodedata.normalize('NFC', value.replace('\r\n', '\n'))).strip()


@dataclass
class _Node:
    tag: str
    attrs: dict
    parent: object = None
    parts: list = field(default_factory=list)

    def descendants(self):
        for p in self.parts:
            if isinstance(p, _Node):
                yield p
                yield from p.descendants()

    def hidden(self):
        n = self
        while n is not None:
            style = n.attrs.get('style', '').lower().replace(' ', '')
            if ('hidden' in n.attrs or n.attrs.get('aria-hidden', '').strip().lower() == 'true'
                    or 'display:none' in style or 'visibility:hidden' in style): return True
            n = n.parent
        return False

    def text(self):
        if self.hidden() or self.tag in ('script', 'style', 'template', 'noscript'): return ''
        return ''.join(p.text() if isinstance(p, _Node) else p for p in self.parts)


class _DOM(HTMLParser):
    """严格平衡树，不做浏览器repair；成本在建树时逐项核对。"""
    def __init__(self, limits):
        super().__init__(convert_charrefs=True)
        self.root = _Node('#document', {})
        self.stack = [self.root]
        self.cost = {k: 0 for k in ('depth', 'nodes', 'markers', 'fields', 'rows')}
        self.limits, self.bad = limits, False

    def bump(self, name, n=1):
        self.cost[name] += n
        _need(self.cost[name] <= self.limits[name], name+'_limit', 'rejected')

    def handle_starttag(self, tag, attrs):
        self.bump('nodes')
        depth = len(self.stack)
        self.cost['depth'] = max(self.cost['depth'], depth)
        _need(depth <= self.limits['depth'], 'depth_limit', 'rejected')
        if len(dict(attrs)) != len(attrs): self.bad = True
        a = dict(attrs)
        if any(value is None and key != 'hidden' for key, value in attrs): self.bad = True
        a = {key: ('' if value is None else value) for key,value in a.items()}
        for attr, metric in [('data-o03-marker', 'markers'), ('data-o03-field', 'fields'), ('data-o03-row', 'rows')]:
            if attr in a: self.bump(metric)
        n = _Node(tag, a, self.stack[-1]); self.stack[-1].parts.append(n); self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs); self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if len(self.stack) <= 1 or self.stack[-1].tag != tag: self.bad = True
        else: self.stack.pop()

    def handle_data(self, data):
        if data: self.bump('nodes'); self.stack[-1].parts.append(data)

    def handle_comment(self, data):
        # Comments are not visible and do not contribute any field value.
        pass

    def handle_decl(self, decl):
        if decl.lower() != 'doctype html': self.bad = True


def _owner(n, attr):
    n = n.parent
    while n is not None:
        if attr in n.attrs: return n
        n = n.parent
    return None


def _structure(dom):
    nodes = list(dom.root.descendants())
    _need(not dom.bad and len(dom.stack) == 1, 'invalid_structure', 'rejected')
    roles = [n for n in nodes if 'data-o03-role' in n.attrs]
    for n in roles:
        role = n.attrs['data-o03-role']
        if role == 'detail.result.table' and (n.tag != 'section' or n.attrs.get('id') != 'results'):
            raise _Failure('duplicate_or_cross_event_role', 'rejected')
    markers = [n for n in nodes if 'data-o03-marker' in n.attrs]
    _need(len(markers) <= 1, 'duplicate_marker', 'rejected')
    scripts = [n for n in nodes if n.tag == 'script']
    _need(all(n in markers and n.attrs.get('type') == 'application/json' for n in scripts)
          and len(scripts) <= 1, 'unexpected_script', 'rejected')
    allowed = set('html body main section div nav a table thead tbody tr th td h2 span b strong small script'.split())
    _need(all(n.tag in allowed for n in nodes), 'invalid_structure', 'rejected')
    _need(len([n for n in nodes if n.tag == 'html']) == 1 and len([n for n in nodes if n.tag == 'body']) == 1,
          'invalid_structure', 'rejected')
    html_node = next(n for n in nodes if n.tag == 'html')
    body_node = next(n for n in nodes if n.tag == 'body')
    _need(html_node.parent is dom.root and body_node.parent is html_node
          and len([n for n in dom.root.parts if isinstance(n, _Node)]) == 1, 'invalid_structure', 'rejected')
    _need(all(isinstance(p, _Node) or not _norm(p) for p in dom.root.parts), 'invalid_structure', 'rejected')
    _need(all((p is body_node) if isinstance(p, _Node) else not _norm(p) for p in html_node.parts), 'invalid_structure', 'rejected')
    parents = {'main': {'body'}, 'thead': {'table'}, 'tbody': {'table'}, 'tr': {'thead','tbody'}, 'th': {'tr'}, 'td': {'tr'}}
    for n in nodes:
        _need(n.tag not in parents or n.parent.tag in parents[n.tag], 'invalid_structure', 'rejected')
        _need(not any(k.startswith('on') for k in n.attrs), 'invalid_structure', 'rejected')
        if 'data-o03-field' in n.attrs:
            owner = _owner(n, 'data-o03-role')
            if not n.hidden() and owner is not None:
                _need(n.tag == 'span' and n.attrs['data-o03-field'] in ROLE_FIELDS.get(owner.attrs['data-o03-role'], []), 'extra_field', 'rejected')
        if 'data-o03-row' in n.attrs:
            owner = _owner(n, 'data-o03-role')
            own = n.attrs.get('data-o03-role')
            valid = own in ('detail.result.hero', 'calendar.result.card') or (n.tag == 'tr' and n.parent.tag == 'tbody')
            if owner is not None and owner.attrs['data-o03-role'] == 'detail.result.table':
                valid = n.tag == 'tr' and n.parent.tag == 'tbody'
            elif owner is not None and owner.attrs['data-o03-role'] == 'detail.result.podium':
                valid = n.tag == 'span' and n.parent is owner
            _need(valid, 'invalid_structure', 'rejected')
        if n.tag == 'script':
            _need(not any(k in n.attrs for k in ('data-o03-field', 'data-o03-row', 'data-o03-role')), 'unexpected_script', 'rejected')
    if not markers: return nodes, roles, None
    marker_node = markers[0]
    _need(marker_node.tag == 'script' and marker_node.attrs.get('data-o03-marker') == 'result-family', 'outer_schema', 'rejected')
    try:
        marker = f01._read(''.join(p for p in marker_node.parts if isinstance(p, str)))
        f01._object(marker, MARKER_KEYS)
        _need(marker['schema_version'] == 'o03.render.v1', 'outer_schema', 'rejected')
        for k in MARKER_KEYS.split(): f01._text(marker[k])
        f01._hash(marker['content_digest'])
    except f01.ContractError: raise _Failure('outer_schema', 'rejected')
    return nodes, roles, marker


def _bind_observed(marker, context, private, now):
    _need(context['body_state'] != 'denial' and context['status'] not in (403, 404), 'denial_unverified')
    _need(context['body_state'] != 'empty', 'capability_absence_unverified')
    _need(marker is not None, 'capability_absence_unverified')
    _need(context['body_state'] == 'normal', 'missing_evidence')
    urlmap = private['canonical_url_map'].get(context['subject_mapping_ref'])
    _need(urlmap is not None, 'subject_binding')
    subject = urlmap['subject']
    for name in ('requested_url', 'final_url'):
        u = urlsplit(context[name])
        _need(u.scheme == 'https' and u.hostname == urlmap['allowed_host'] and u.netloc == u.hostname
              and not u.fragment, 'subject_binding')
        if context['surface_ref'] == 'detail.result-family':
            _need(not u.query and u.path == subject, 'subject_binding')
        else:
            query = parse_qsl(u.query, keep_blank_values=True)
            _need(u.path == '/races/' and len(query) == len(dict(query))
                  and set(dict(query)) <= {'tab', 'year', 'q'}
                  and context['requested_url'] == context['final_url'], 'subject_binding')
    _need(marker['subject'] == subject, 'subject_binding')
    entries = private['private_token_index'].get(marker['revision_ref'])
    _need(type(entries) is list and bool(entries), 'token_unbound')
    _need(all(t == entries[0] for t in entries), 'token_conflict', 'rejected')
    t = entries[0]
    f01._object(t, TUPLE_KEYS)
    _need(t['surface_ref'] == context['surface_ref'] == marker['surface_ref'], 'surface_binding')
    _need(t['audience_ref'] == context['audience_ref'] == 'anonymous', 'audience_binding')
    _need(t['capability'] == context['capability'] == marker['capability'] and t['capability'] in ('result', 'correction'), 'capability_binding')
    _need(t['subject'] == subject and t['target_key'] == urlmap['target_key'], 'subject_binding')
    _need(t['origin_ref'] is not None, 'origin_permission_unbound')
    _need(t['permission_ref'] is not None, 'permission_unbound')
    _need(t['display_mapping_ref'] is not None, 'display_mapping_unbound')
    origin = private['origins'].get(t['origin_ref']); permission = private['permissions'].get(t['permission_ref'])
    display = private['display_mappings'].get(t['display_mapping_ref'])
    _need(origin is not None, 'origin_permission_unbound'); _need(permission is not None, 'permission_unbound')
    _need(display is not None, 'display_mapping_unbound')
    _need(origin['complete_under_fixture_rule_only'] is True and origin['fixture_requirement_ref'], 'origin_completeness_unbound')
    _need(f01._sha(origin) == t['origin_sha256'] and f01._sha(permission) == t['permission_sha256']
          and f01._sha(display) == t['display_mapping_sha256'], 'private_content_binding')
    _need(t['candidate_sha'] == private['candidate_sha'] and marker['revision_ref'] == 'pv1:'+f01._sha(t), 'token_binding')
    f01._hash(t['candidate_sha']); f01._version(t['input_version']); f01._text(t['generation'])
    _need(t['body_contract_version'] == display['body_contract_version'] == 'o03.result-body.v1', 'display_mapping_unbound')
    doc = private['f01_documents'].get(t['F01_document_ref']); _need(doc is not None, 'input_version_unbound')
    loaded = f01.parse_input(doc).to_dict()
    _need(loaded['input_version'] == t['input_version'] and loaded['snapshot']['entity']['canonical_id'] == t['target_key'], 'input_version_unbound')
    _need(origin['target_key'] == t['target_key'] == origin['raw_material']['target_key']
          and f01._sha(origin['raw_material']) == origin['raw_material_sha256'], 'origin_permission_unbound')
    _need(any(m['revision_ref'] == t['origin_ref'] and m['capability'] == t['capability'] for m in loaded['snapshot']['materials'])
          and any(e['artifact_sha256'] == origin['raw_material_sha256'] for e in loaded['snapshot']['evidence']), 'origin_permission_unbound')
    f01._object(permission, 'synthetic_only target_key origin_ref capability audience_ref allowed_surfaces allowed valid_from valid_until proof_ref permission_generation permission_version')
    f01._require(type(permission['synthetic_only']) is bool and type(permission['allowed']) is bool, 'permission_boolean')
    f01._count(permission['permission_generation'])
    f01._require(type(permission['allowed_surfaces']) is list and all(type(v) is str for v in permission['allowed_surfaces']), 'permission_surfaces')
    f01._time(now); f01._time(permission['valid_from']); f01._time(permission['valid_until'])
    _need(permission['allowed'] is True and permission['target_key'] == t['target_key'] and permission['origin_ref'] == t['origin_ref']
          and permission['audience_ref'] == t['audience_ref'] and permission['capability'] == t['capability']
          and t['surface_ref'] in permission['allowed_surfaces'] and permission['proof_ref']
          and c013._stamp(permission['valid_from']) <= c013._stamp(now) <= c013._stamp(permission['valid_until']), 'permission_unbound')
    _need(marker['permission_version'] == permission['permission_version']
          == 'pp1:'+f01._sha({k:v for k,v in permission.items() if k != 'permission_version'}), 'permission_binding')
    style = private['approved_styles'].get(private['profile']['approved_style_ref'])
    _need(style is not None and style['selected_nodes_visible_unless_blocked'] is True and style['external_stylesheets'] == [], 'visibility_unbound')
    _need(all(type(proof) is str and proof for proof in origin['participant_proof_refs'].values()), 'row_identity_unbound')
    _need(all(type(row) is dict and set(row) == {'target_key','origin_ref','participant_ref','proof_ref'} for row in private['private_row_token_index'].values()), 'row_identity_unbound')
    _need(all(type(row['proof_ref']) is str and row['proof_ref'] for row in private['private_row_token_index'].values()
              if row['origin_ref'] == t['origin_ref']), 'row_identity_unbound')
    return t, origin, display, loaded


def _fields(container, role, names, optional=()):
    raw = [n for n in container.descendants() if 'data-o03-field' in n.attrs
           and _owner(n, 'data-o03-role') is role and _owner(n, 'data-o03-row') is
           (container if 'data-o03-row' in container.attrs else _owner(container, 'data-o03-row'))]
    values = {}
    for key in names:
        all_nodes = [n for n in raw if n.attrs['data-o03-field'] == key]
        visible = [n for n in all_nodes if not n.hidden()]
        _need(len(visible) <= 1, 'duplicate_field')
        if not visible:
            if key in optional: values[key] = None; continue
            raise _Failure('missing_visible_field' if all_nodes else 'missing_field')
        value = _norm(visible[0].text())
        _need(bool(value), 'missing_visible_field')
        values[key] = value
    return values


def _role_node(n):
    role = n.attrs['data-o03-role']
    selectors = {
        'detail.result.hero': ('section', 'race-hero'), 'detail.result.podium': ('div', 'podium-line'),
        'detail.result.table': ('section', None), 'detail.result.nav': ('a', None),
        'detail.result.stale': ('div', None), 'calendar.result.card': ('a', 'cal-card'),
    }
    _need(role in selectors, 'invalid_structure', 'rejected')
    tag, cls = selectors[role]
    _need(n.tag == tag and (cls is None or cls in n.attrs.get('class', '').split()), 'invalid_structure', 'rejected')
    if role == 'detail.result.podium':
        _need(_owner(n, 'data-o03-role') is not None and _owner(n, 'data-o03-role').attrs['data-o03-role'] == 'detail.result.hero', 'invalid_structure', 'rejected')
    elif role == 'detail.result.stale':
        _need(_owner(n, 'data-o03-role') is not None and _owner(n, 'data-o03-role').attrs['data-o03-role'] == 'detail.result.hero', 'invalid_structure', 'rejected')
    elif role == 'detail.result.nav':
        _need(n.parent.tag == 'nav' and n.parent.attrs.get('class') == 'race-subnav' and n.parent.parent.tag == 'main', 'invalid_structure', 'rejected')
    else:
        _need(n.parent.tag == 'main', 'invalid_structure', 'rejected')
        _need(_owner(n, 'data-o03-role') is None, 'invalid_structure', 'rejected')


def _role_structure(roles, context, profile):
    visible = [n for n in roles if not n.hidden()]
    names = [n.attrs['data-o03-role'] for n in visible]
    _need(len(names) == len(set(names)), 'duplicate_role')
    for n in visible: _role_node(n)
    if context['surface_ref'] == 'detail.result-family':
        wanted = ['detail.result.hero', 'detail.result.podium'] if profile['declared_hero'] else []
        if profile['declared_stale']: wanted += ['detail.result.stale']
        wanted += ['detail.result.nav', 'detail.result.table']
        _need(set(names) == set(wanted), 'missing_role')
        _need(names == wanted, 'role_order')
    else:
        _need(names == ['calendar.result.card'], 'missing_role')
    return visible, names


def _row_proof(token, t, origin, private):
    row = private['private_row_token_index'].get(token)
    _need(row is not None and row['proof_ref'] and row['target_key'] == t['target_key'], 'row_identity_unbound')
    _need(row['origin_ref'] == t['origin_ref'], 'content_mismatch')
    participant = row['participant_ref']
    if participant is not None:
        _need(participant in origin['participant_proof_refs'] and row['proof_ref'] == origin['participant_proof_refs'][participant], 'row_identity_unbound')
        _need(token == 'pr1:'+f01._sha(dict(origin_ref=t['origin_ref'], participant_ref=participant, target_key=t['target_key'])), 'row_identity_unbound')
    else:
        _need(token == 'pe1:'+f01._sha(dict(origin_ref=t['origin_ref'], target_key=t['target_key'])), 'row_identity_unbound')
    return participant


def _guard_visible_text(role, checked_nodes=(), *, fields=True):
    """Selected role text must be modeled fields or separately checked static wrappers.

    Ignore nested roles here: each selected role is checked independently. Never
    consume hidden text or expand the scope to other content on the page.
    """
    checked = {id(n) for n in checked_nodes}

    def visit(node):
        if node.hidden() or id(node) in checked: return
        if node is not role and 'data-o03-role' in node.attrs: return
        if fields and 'data-o03-field' in node.attrs: return
        for part in node.parts:
            if isinstance(part, _Node): visit(part)
            else: _need(not _norm(part), 'unmodeled_visible_content')

    visit(role)


def _extract(nodes, roles, marker, bound, context, private):
    t, origin, display, loaded = bound
    for n in nodes:
        style = n.attrs.get('style', '').lower().replace(' ', '')
        _need('aria-hidden' not in n.attrs or n.attrs['aria-hidden'].strip().lower() in ('true', 'false'), 'visibility_unbound')
        known_classes = {'race-hero','winner-ribbon','winner-name','winner-crew','podium-line','race-subnav','data-table','cal-card','cal-card-status'}
        _need(set(n.attrs.get('class', '').split()) <= known_classes, 'visibility_unbound')
        _need(not style or style in ('display:none', 'display:none;', 'visibility:hidden', 'visibility:hidden;'), 'visibility_unbound')
    profile = private['profile']
    roles, names = _role_structure(roles, context, profile)
    selected = []
    if t['surface_ref'] == 'detail.result-family':
        wanted = (['detail.result.hero', 'detail.result.podium'] if profile['declared_hero'] else [])
        if profile['declared_stale']: wanted += ['detail.result.stale']
        wanted += ['detail.result.nav', 'detail.result.table']
        _need(set(names) == set(wanted), 'missing_role')
        _need(names == wanted, 'role_order')
        _need(not any('data-o03-row' in n.attrs and _owner(n, 'data-o03-role') is None
                      and n.attrs.get('data-o03-role') != 'detail.result.hero' for n in nodes), 'invalid_structure', 'rejected')
        _need(not any('data-o03-field' in n.attrs and not n.hidden() and _owner(n, 'data-o03-role') is None for n in nodes), 'extra_field', 'rejected')
        rolemap = dict(zip(names, roles))
        table = rolemap['detail.result.table']
        tables = [n for n in table.descendants() if n.tag == 'table']
        _need(len(tables) == 1 and tables[0].attrs.get('class') == 'data-table', 'invalid_structure', 'rejected')
        table_node = tables[0]
        heads = [n for n in table_node.descendants() if n.tag == 'thead']
        bodies = [n for n in table_node.descendants() if n.tag == 'tbody']
        _need(len(heads) == len(bodies) == 1 and heads[0].parent is table_node and bodies[0].parent is table_node, 'invalid_structure', 'rejected')
        labels = [_norm(n.text()) for n in heads[0].descendants() if n.tag == 'th']
        _need(labels == [c['text'] for c in display['columns']], 'column_contract')
        columns = [dict(key=c['key'], text=label) for c, label in zip(display['columns'], labels)]
        headings = [n for n in table.parts if isinstance(n, _Node) and n.tag == 'h2']
        _need(len(headings) == 1 and _norm(headings[0].text()) == '赛果', 'unmodeled_visible_content')
        checked_table_text = headings + [n for n in heads[0].descendants() if n.tag == 'th']
        rownodes = [n for n in bodies[0].parts if isinstance(n, _Node) and n.tag == 'tr']
        tokens = [n.attrs.get('data-o03-row') for n in rownodes]
        _need(len(tokens) == len(set(tokens)), 'duplicate_row')
        _need(len(rownodes) == profile['declared_result_rows'] == len(origin['raw_material']['participants']), 'row_cardinality')
        rows = []
        for row in rownodes:
            cells = _fields(row, table, CELL_KEYS)
            for k in profile['required_value_fields']:
                _need(cells[k] not in ('待核实', '-', '—'), 'required_placeholder')
            tds = [n for n in row.parts if isinstance(n, _Node)]
            _need(len(tds) == 8 and all(n.tag == 'td' for n in tds), 'column_contract')
            for cell, keys in zip(tds, [[k] for k in CELL_KEYS[:7]]+[['odds', 'popularity']]):
                found = [n.attrs['data-o03-field'] for n in cell.descendants() if 'data-o03-field' in n.attrs and not n.hidden()]
                _need(found == keys, 'column_contract')
                cell_text = ' / '.join(cells[k] for k in keys)
                _need(_norm(cell.text()) == cell_text, 'content_mismatch')
            checked_table_text.extend(tds)
            rows.append(dict(row_token=row.attrs.get('data-o03-row'), cells=cells))
        _guard_visible_text(table, checked_table_text, fields=False)
        hero = None; podium = None
        if profile['declared_hero']:
            hn = rolemap['detail.result.hero']; pn = rolemap['detail.result.podium']
            hero = dict(role='detail.result.hero', row_token=hn.attrs.get('data-o03-row'), fields=_fields(hn, hn, ROLE_FIELDS['detail.result.hero'], optional=('jockey_name', 'trainer_name', 'finish_time', 'popularity')))
            _need(hero['fields']['horse_name'] not in ('待核实', '-', '—'), 'required_placeholder')
            prows = [n for n in pn.descendants() if 'data-o03-row' in n.attrs and _owner(n, 'data-o03-role') is pn]
            _need(len(prows) == profile['declared_podium_rows'] and len(prows) <= 2, 'row_cardinality')
            podium = dict(role='detail.result.podium', rows=[dict(row_token=n.attrs['data-o03-row'], cells=_fields(n, pn, ROLE_FIELDS['detail.result.podium'], optional=('margin',))) for n in prows])
            _need(hero['row_token'] == rows[0]['row_token'] and hero['fields']['ribbon'] == 'WINNER · 冠军', 'related_role_mismatch')
            for k in ('horse_name', 'jockey_name', 'trainer_name', 'finish_time', 'popularity'):
                if hero['fields'][k] is not None: _need(hero['fields'][k] == rows[0]['cells'][k], 'related_role_mismatch')
            for i, pr in enumerate(podium['rows']):
                _need(pr['row_token'] == rows[i+1]['row_token'], 'related_role_mismatch')
                for k in ('position', 'horse_name', 'margin'):
                    if pr['cells'][k] is not None: _need(pr['cells'][k] == rows[i+1]['cells'][k], 'related_role_mismatch')
                expected_text = pr['cells']['position']+'名 '+pr['cells']['horse_name']
                if pr['cells']['margin'] is not None: expected_text += '（'+pr['cells']['margin']+'）'
                _need(_norm(prows[i].text()) == expected_text, 'related_role_mismatch')
            _guard_visible_text(pn, prows, fields=False)
            _guard_visible_text(hn)
        participants = [_row_proof(r['row_token'], t, origin, private) for r in rows]
        _need(participants == [p['participant_ref'] for p in origin['raw_material']['participants']], 'content_mismatch')
        for row, raw in zip(rows, origin['raw_material']['participants']):
            for k, availability in raw['field_availability'].items():
                _need(availability in ('available', 'known_missing'), 'origin_completeness_unbound')
                if row['cells'][k] in ('-', '—'):
                    _need(availability == 'known_missing' and k in display['optional_known_missing'], 'required_placeholder')
        for name in names:
            if name == 'detail.result.hero': selected.append(hero)
            elif name == 'detail.result.podium': selected.append(podium)
            elif name == 'detail.result.table': selected.append(dict(role=name, columns=columns, rows=rows))
            else:
                n = rolemap[name]; fields = _fields(n, n, ['text'])
                if name == 'detail.result.nav':
                    fields['href'] = n.attrs.get('href'); _need(fields == dict(text='赛果', href='#results'), 'related_role_mismatch')
                else: _need(fields['text'] == '数据可能已过期', 'related_role_mismatch')
                _guard_visible_text(n)
                selected.append(dict(role=name, fields=fields))
    else:
        _need(names == ['calendar.result.card'], 'missing_role')
        _need(not any('data-o03-field' in n.attrs and not n.hidden() and _owner(n, 'data-o03-role') is None for n in nodes), 'extra_field', 'rejected')
        n = roles[0]; fields = _fields(n, n, ['status', 'winner'], optional=('winner',))
        fields = dict(href=n.attrs.get('href'), **fields)
        _need(fields['href'] == t['subject'], 'subject_binding')
        _need(_row_proof(n.attrs.get('data-o03-row'), t, origin, private) is None, 'row_identity_unbound')
        source_key = origin['raw_material']['source_revision']
        winner = origin['raw_material']['participants'][0]['participant_ref']
        _need(fields['winner'] == (display['independent_golden_row_values'][source_key][winner]['horse_name'] if profile['declared_hero'] else None), 'related_role_mismatch')
        checked_card_text = []
        if fields['winner'] is not None:
            wn = next(n for n in n.descendants() if n.attrs.get('data-o03-field') == 'winner' and not n.hidden())
            _need(_norm(wn.parent.text()) == '冠军 '+fields['winner'], 'related_role_mismatch')
            checked_card_text.append(wn.parent)
        _guard_visible_text(n, checked_card_text)
        selected = [dict(role='calendar.result.card', row_token=n.attrs.get('data-o03-row'), fields=fields)]
    return dict(schema_version=t['body_contract_version'], subject=t['subject'], surface_ref=t['surface_ref'], capability=t['capability'], roles=selected)


def _complete(body, marker, bound, context, expected_body, expected, anchor, now):
    t, origin, display, loaded = bound
    digest = f01._sha(body)
    _need(marker['content_digest'] != origin['raw_material_sha256'], 'digest_domain_mismatch')
    _need(body == expected_body and digest == marker['content_digest'], 'content_mismatch')
    # Observed version comes exclusively from the observed opaque token's private tuple.
    receipt = dict(schema_version='o03.read.v1', scope_ref=context['scope_ref'], candidate_sha=t['candidate_sha'],
                   expectation_sha=f01._sha(expected), input_version=t['input_version'], entity=loaded['snapshot']['entity'],
                   capability=t['capability'], surface_ref=t['surface_ref'], audience_ref=t['audience_ref'], generation=t['generation'],
                   receipt_id=context['receipt_id'], request_started_at=context['request_started_at'], response_completed_at=context['response_completed_at'],
                   clock_error_ms=context['clock_error_ms'], status=context['status'], complete=True, conflict=False, denial_verified=False,
                   marker={k:marker[k] for k in ('revision_ref', 'permission_version', 'content_digest')}, body_digest=digest)
    comparison = c013.compare_public(expected, receipt, anchor=anchor, as_of=now).to_dict()
    _need(comparison['public_read_verified'] is True, 'comparison_unverified')
    return c013.ProbeDocument(f01._encode(dict(leaf_status='fixture_verified', reason='matching_fixture_only', body=body,
                   body_digest=digest, receipt=receipt, c013_status=comparison['status'], comparison=comparison,
                   complete_original_scope=False, synthetic_only=True)))


def _result(state, reason, **extra):
    return c013.ProbeDocument(f01._encode(dict(leaf_status=state, reason=reason, body=None, receipt=None,
                                             c013_status='not_constructed', **extra)))


def _inputs(context, private, expected_body, expected, anchor, now):
    f01._object(context, 'requested_url final_url status body_state audience_ref subject_mapping_ref scope_ref surface_ref capability receipt_id request_started_at response_completed_at clock_error_ms')
    for k in ('requested_url','final_url','audience_ref','subject_mapping_ref','scope_ref','surface_ref','capability','receipt_id'): f01._text(context[k])
    f01._require(type(context['status']) is int and 100 <= context['status'] <= 599, 'http_status')
    f01._enum(context['body_state'], ('normal','empty','denial','unknown'))
    f01._enum(context['surface_ref'], ('detail.result-family','calendar.main.result-summary'))
    f01._enum(context['capability'], ('result','correction'))
    f01._count(context['clock_error_ms'], nullable=True)
    for k in ('request_started_at','response_completed_at'): f01._time(context[k])
    f01._time(now)
    f01._require(c013._stamp(context['request_started_at']) <= c013._stamp(context['response_completed_at']) <= c013._stamp(now), 'receipt_time_order')
    f01._object(private, 'private_token_index private_row_token_index origins permissions display_mappings f01_documents approved_styles canonical_url_map candidate_sha profile')
    for k in ('private_token_index','private_row_token_index','origins','permissions','display_mappings','f01_documents','approved_styles','canonical_url_map','profile'):
        f01._require(type(private[k]) is dict, 'private_object')
    f01._hash(private['candidate_sha'])
    p = private['profile']
    f01._object({k:v for k,v in p.items() if k != 'origin_kind'}, 'origin_ref permission_ref display_mapping_ref private_token required_value_fields optional_known_missing approved_style_ref declared_hero declared_podium_rows declared_result_rows declared_stale')
    if 'origin_kind' in p: f01._text(p['origin_kind'])
    for k in ('origin_ref','permission_ref','display_mapping_ref','approved_style_ref'): f01._text(p[k], nullable=True)
    f01._text(p['private_token'])
    f01._require(type(p['optional_known_missing']) is list and all(type(k) is str and k in CELL_KEYS for k in p['optional_known_missing']), 'profile_optional_fields')
    for k in ('declared_hero','declared_stale'): f01._require(type(p.get(k)) is bool, 'profile_boolean')
    for k in ('declared_podium_rows','declared_result_rows'): f01._count(p.get(k))
    f01._require(p['declared_podium_rows'] <= 2, 'profile_rows')
    f01._require(type(p.get('required_value_fields')) is list and p['required_value_fields'] == ['position','horse_number','horse_name'], 'profile_required_fields')
    f01._object(expected_body, 'schema_version subject surface_ref capability roles')
    f01._require(expected_body['schema_version'] == 'o03.result-body.v1' and type(expected_body['roles']) is list, 'body_schema')
    for k in ('subject','surface_ref','capability'): f01._text(expected_body[k])
    for role in expected_body['roles']:
        f01._require(type(role) is dict and role.get('role') in ROLE_FIELDS, 'body_role')
        name = role['role']
        if name == 'detail.result.table':
            f01._object(role, 'role columns rows')
            f01._require(type(role['columns']) is list and type(role['rows']) is list, 'body_rows')
            for col in role['columns']:
                f01._object(col, 'key text'); f01._text(col['key']); f01._text(col['text'])
            rows = role['rows']; keys = CELL_KEYS
        elif name == 'detail.result.podium':
            f01._object(role, 'role rows'); f01._require(type(role['rows']) is list, 'body_rows')
            rows = role['rows']; keys = ROLE_FIELDS[name]
        else:
            f01._object(role, 'role fields row_token' if name in ('detail.result.hero','calendar.result.card') else 'role fields')
            keys = ROLE_FIELDS[name]+(['href'] if name in ('detail.result.nav','calendar.result.card') else [])
            f01._object(role['fields'], ' '.join(keys))
            optional = ('jockey_name','trainer_name','finish_time','popularity') if name == 'detail.result.hero' else ('winner',) if name == 'calendar.result.card' else ()
            for key in keys: f01._text(role['fields'][key], nullable=key in optional)
            if 'row_token' in role: f01._text(role['row_token'])
            continue
        for row in rows:
            f01._object(row, 'row_token cells'); f01._text(row['row_token']); f01._object(row['cells'], ' '.join(keys))
            for key in keys: f01._text(row['cells'][key], nullable=name == 'detail.result.podium' and key == 'margin')
    f01._require(type(expected) is dict and type(anchor) is dict, 'expected_anchor_object')


def parse_render(html, *, context, limits, private, expected_body, expected, anchor, now):
    """解析实际UTF8 bytes；expected仅比较，不用于生成观察正文。"""
    f01._require(type(html) is bytes, 'html_bytes')
    # Normalize explicit JSON structures to private copies; no caller-owned mutable result escapes.
    context, private, expected_body, expected, anchor = [f01._read(v) for v in (context, private, expected_body, expected, anchor)]
    _inputs(context, private, expected_body, expected, anchor, now)
    try:
        _need(limits is not None, 'budget_unbound')
        f01._object(limits, ' '.join(LIMIT_KEYS))
        for k in LIMIT_KEYS: f01._require(type(limits[k]) is int and limits[k] > 0, 'render_limit')
        _need(len(html) <= limits['wire_bytes'], 'wire_bytes_limit', 'rejected')
        _need(len(html) <= limits['decoded_bytes'], 'decoded_bytes_limit', 'rejected')
        try: text = html.decode('utf-8', errors='strict')
        except UnicodeDecodeError: raise _Failure('invalid_encoding', 'rejected')
        dom = _DOM(limits); dom.feed(text); dom.close()
        nodes, roles, marker = _structure(dom)
        if marker is not None: _role_structure(roles, context, private['profile'])
        bound = _bind_observed(marker, context, private, now)
        body = _extract(nodes, roles, marker, bound, context, private)
        return _complete(body, marker, bound, context, expected_body, expected, anchor, now)
    except _Failure as e: return _result(e.state, e.reason)
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise f01.ContractError('malformed_render_input') from e
