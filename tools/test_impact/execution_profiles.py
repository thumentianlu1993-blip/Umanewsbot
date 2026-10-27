"""全量验证专用环境；精确 native 身份决定权限和固定缓存。"""
from pathlib import Path
from tools.test_impact import fixture_inputs as primary
from tools.test_impact import fixture_inputs_secondary as secondary
from tools.test_impact import fixture_inputs_remaining as remaining

ROOT_PROFILE = 'django-root-artifact'
ROOT_ID = 'stable.test_race_live_gate_remediation.RollbackGateBehaviorRemediationTests.test_root_artifact_is_exact_0700_0600_secret_free_and_no_replace'
CACHE_PROFILES = {'django-cache-primary': primary, 'django-cache-secondary': secondary,
                  'django-cache-remaining': remaining}
PROFILES = frozenset(('python', 'django', 'release-postgres', ROOT_PROFILE, *CACHE_PROFILES))


def resolve_profile(native_id, mapping):
    matches = [key for key in mapping if native_id == key or native_id.startswith(key + '.')]
    return mapping[max(matches, key=len)] if matches else None


def validate_privilege(profile, uid, gid, cap_eff):
    expected_uid = 0 if profile == ROOT_PROFILE else 10001
    # Linux CAP_KILL(5), CAP_SETGID(6), CAP_SETUID(7) only.
    expected_caps = 0xe0 if profile == ROOT_PROFILE else 0
    if (profile not in PROFILES or any(type(value) is not int for value in (uid,gid,cap_eff))
            or uid != expected_uid or gid != expected_uid or cap_eff != expected_caps):
        raise ValueError('execution profile privilege mismatch')


def current_capabilities():
    values = [line.split(':', 1)[1].strip() for line in Path('/proc/self/status').read_text().splitlines()
              if line.startswith('CapEff:')]
    if len(values) != 1:
        raise ValueError('missing effective capability evidence')
    return int(values[0], 16)


def validate_batch(batch):
    profile = batch.get('profile')
    if profile not in PROFILES:
        raise ValueError('unknown execution profile')
    if profile == ROOT_PROFILE:
        if batch.get('ids') != [ROOT_ID]:
            raise ValueError('root profile requires exactly the original native ID')
    elif profile in CACHE_PROFILES:
        ids = batch.get('ids')
        if (type(ids) is not list or not ids or any(type(i) is not str for i in ids)
                or len(ids) != len(set(ids)) or not set(ids) <= set(CACHE_PROFILES[profile].NATIVE_IDS)):
            raise ValueError('cache profile requires a nonempty unique native subset')


def cache_environment(batch, plan, binding, code_sha, source_root=Path('/source')):
    validate_batch(batch)
    if batch['profile'] not in CACHE_PROFILES:
        return {}
    if (code_sha != plan.get('test_sha') or code_sha != binding.get('test_sha')
            or plan.get('test_tree') != binding.get('test_tree')):
        raise ValueError('cache profile source mismatch')
    return CACHE_PROFILES[batch['profile']].resource_environment(source_root)
