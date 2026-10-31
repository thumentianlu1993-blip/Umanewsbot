"""仅两个精确合同允许专用执行环境；不允许按模块提升权限。"""
ROOT_TEST = 'stable.test_race_live_gate_remediation.RollbackGateBehaviorRemediationTests.test_root_artifact_is_exact_0700_0600_secret_free_and_no_replace'
IMAGE_TEST = 'stable.test_migration_history_repair.MigrationHistoryRepairDockerImageContractTests.test_candidate_image_contains_only_the_exact_reviewed_audit_file'
SPECIAL = {ROOT_TEST: 'root-django', IMAGE_TEST: 'application-image'}


def profile_for(ident, default):
    return SPECIAL.get(ident, default)


def validate_special_batch(batch):
    profile, ids = batch['profile'], batch['ids']
    if profile in SPECIAL.values():
        expected = [ident for ident, owner in SPECIAL.items() if owner == profile]
        if ids != expected:
            raise ValueError('special profile requires its single exact test ID')
    elif any(ident in SPECIAL for ident in ids):
        raise ValueError('special test cannot use a regular execution profile')


def validate_root_status(status, uid, gid):
    if uid != 0 or gid != 0 or status.get('NoNewPrivs', '').strip() != '1':
        raise ValueError('root test identity/no-new-privileges mismatch')
    if any(int(status[key].strip(), 16) for key in ('CapBnd', 'CapPrm', 'CapEff', 'CapInh', 'CapAmb')):
        raise ValueError('root test capabilities not fully dropped')


def expected_image(plan, batch):
    import re
    validate_special_batch(batch)
    dependency = plan.get('image_id')
    if not isinstance(dependency, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', dependency):
        raise ValueError('missing or invalid dependency image identity')
    key = 'application_image_id' if batch['profile'] == 'application-image' else 'image_id'
    image = plan.get(key)
    if not isinstance(image, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        raise ValueError('missing or invalid batch image identity')
    return image


def verify_special_report(plan, batch, report):
    if batch['profile'] == 'root-django':
        isolation = report.get('isolation', {})
        validate_root_status(isolation.get('capabilities', {}), isolation.get('uid'), isolation.get('gid'))
    elif batch['profile'] == 'application-image':
        if plan.get('application_image_id') == plan.get('image_id'):
            raise ValueError('application image cannot be dependency test image')
        if report.get('application_revision') != plan.get('test_sha'):
            raise ValueError('application report revision mismatch')
