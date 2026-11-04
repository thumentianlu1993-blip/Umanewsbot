"""私有v3累计收集预算；None调用保持原容器/算法，不使用全局计数器。"""
from dataclasses import fields, is_dataclass
from datetime import datetime
import json
import re


class TermCaptureRefusal(ValueError):
    pass


def primitive(value):
    if is_dataclass(value):
        return {f.name: primitive(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return ({k: primitive(v) for k, v in value.items()} if all(type(k) is str for k in value)
                else [[primitive(k), primitive(v)] for k, v in value.items()])
    if isinstance(value, (list, tuple, set)):
        return [primitive(v) for v in value]
    if isinstance(value, re.Match):
        return [value.group(0), value.start(), value.end()]
    if isinstance(value, str):
        return str(value)
    if type(value) in (int, bool) or value is None:
        return value
    # Only the loader's scalar namespaces/models are admitted, without property/FK access.
    data = getattr(value, '__dict__', None)
    if isinstance(data, dict):
        return {k: primitive(v) for k, v in data.items() if k != '_state'}
    raise TermCaptureRefusal('read_terms_invalid')


def canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise TermCaptureRefusal('read_terms_invalid') from exc


class CaptureBudget:
    def __init__(self):
        self.objects = self.collections = self.strings = 0
        self.object_bytes = self.collection_bytes = self.string_bytes = 0

    def charge(self, kind, value):
        count_name = {'object': 'objects', 'collection': 'collections', 'string': 'strings'}[kind]
        byte_name = kind + '_bytes'
        size = len(canonical(primitive(value)))
        if (getattr(self, count_name) + 1 > (256 if kind == 'object' else 1024)
                or getattr(self, byte_name) + size > 128 * 1024
                or self.object_bytes + self.collection_bytes + self.string_bytes + size > 256 * 1024):
            raise TermCaptureRefusal('read_terms_limit')
        setattr(self, count_name, getattr(self, count_name) + 1)
        setattr(self, byte_name, getattr(self, byte_name) + size)

    def string(self, value):
        if type(value) is not str:
            raise TermCaptureRefusal('read_terms_invalid')
        if len(value) > 1024:
            raise TermCaptureRefusal('read_terms_limit')
        try:
            size = len(value.encode())
        except UnicodeError as exc:
            raise TermCaptureRefusal('read_terms_invalid') from exc
        if size > 1024:
            raise TermCaptureRefusal('read_terms_limit')
        self.charge('string', value)


class _List(list):
    def __init__(self, values=(), budget=None, strings=False):
        self.budget, self.strings = budget, strings
        super().__init__()
        self.extend(values)

    def append(self, value):
        if self.budget:
            if self.strings:
                if len(self) >= 64:
                    raise TermCaptureRefusal('read_terms_limit')
                self.budget.string(value)
            else:
                self.budget.charge('collection', value)
        super().append(value)

    def extend(self, values):
        for value in values:
            self.append(value)


class _Dict(dict):
    def __init__(self, values=(), budget=None):
        self.budget = budget
        super().__init__()
        for key, value in values:
            self[key] = value

    def __setitem__(self, key, value):
        if self.budget:
            self.budget.charge('collection', (key, value))
        super().__setitem__(key, value)

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]


class _Set(set):
    def __init__(self, values=(), budget=None):
        self.budget = budget
        super().__init__()
        self.update(values)

    def add(self, value):
        if value not in self and self.budget:
            self.budget.charge('collection', value)
        super().add(value)

    def update(self, values):
        for value in values:
            self.add(value)


def capture_list(values=(), budget=None):
    return list(values) if budget is None else _List(values, budget)


def capture_dict(values=(), budget=None):
    return dict(values) if budget is None else _Dict(values, budget)


def capture_set(values=(), budget=None):
    return set(values) if budget is None else _Set(values, budget)


def capture_tuple(values=(), budget=None):
    return tuple(values) if budget is None else tuple(capture_list(values, budget))


def capture_sorted(values, budget=None, **kwargs):
    result = capture_list(values, budget)
    result.sort(**kwargs)
    return result


def capture_fromkeys(values, budget=None):
    if budget is None:
        return dict.fromkeys(values)
    result = capture_dict(budget=budget)
    for value in values:
        # Repeated inputs are charged too, before deduplication.
        budget.charge('collection', value)
        result.setdefault(value)
    return result


def capture_strings(values=(), budget=None):
    return list(values) if budget is None else _List(values, budget, strings=True)


def capture_unique_strings(values, budget=None):
    if budget is None:
        return list(dict.fromkeys(values))
    result = capture_strings(budget=budget)
    seen = capture_set(budget=budget)
    for value in values:
        # Charge the streamed input before copying or deduplicating it. A refused
        # string must never be inserted into an intermediate collection first.
        budget.string(value)
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def capture_object(factory, budget=None, **kwargs):
    if budget is not None:
        budget.charge('object', kwargs)
    return factory(**kwargs)


def capture_split(text, budget=None):
    if budget is None:
        return text.split()
    return capture_list((m.group(0) for m in re.finditer(r"\S+", text)), budget)


def capture_findall(pattern, text, budget=None):
    if budget is None:
        return re.findall(pattern, text)
    compiled = re.compile(pattern)
    def values():
        for match in compiled.finditer(text):
            yield (match.group(0) if compiled.groups == 0 else
                   match.group(1) if compiled.groups == 1 else match.groups())
    return capture_list(values(), budget)
