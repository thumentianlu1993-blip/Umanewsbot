#!/usr/bin/env python3
"""只读确认外部 Compose 常驻服务不属于 Umanews；不明元数据一律拒绝。"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
from pathlib import Path


class UnprovenOwnership(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise UnprovenOwnership(reason)


def inspect(kind, identity):
    require(bool(re.fullmatch(r'[A-Za-z0-9_.:-]+', identity)) and not identity.startswith('-'),
            'invalid inspect identity')
    command = ['docker', *(['image'] if kind == 'image' else []), 'inspect', identity]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=15, check=True)
        require(len(result.stdout) <= 2 * 1024 * 1024, 'inspect output exceeds bound')
        data = json.loads(result.stdout)
    except (subprocess.SubprocessError, UnicodeError, json.JSONDecodeError) as exc:
        raise UnprovenOwnership('inspect failed or returned invalid JSON') from exc
    require(isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict),
            'inspect object is missing or ambiguous')
    return data[0]


def absolute_path(value):
    require(isinstance(value, str) and value.startswith('/') and
            posixpath.normpath(value) == value and '\x00' not in value,
            'invalid host path')
    return value


def host_path(value):
    absolute_path(value)
    try:
        return str(Path(value).resolve(strict=False))
    except (OSError, RuntimeError) as exc:
        raise UnprovenOwnership('host path alias cannot be resolved') from exc


def resource_inventory(project):
    require(bool(re.fullmatch(r'[a-z0-9_-]+', project)), 'invalid expected project')
    fmt = '{{.ID}}|{{.Label "com.docker.compose.service"}}|{{.Label "com.docker.compose.project"}}|{{.Label "com.docker.compose.oneoff"}}|{{.Label "com.docker.compose.project.working_dir"}}'
    try:
        result = subprocess.run(['docker', 'ps', '-a', '--filter',
            'label=com.docker.compose.project='+project, '--filter',
            'label=com.docker.compose.service', '--format', fmt],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=True)
        require(len(result.stdout) <= 1024 * 1024, 'resource census exceeds bound')
        rows = [line.split('|') for line in result.stdout.decode().splitlines() if line]
    except (subprocess.SubprocessError, UnicodeError) as exc:
        raise UnprovenOwnership('resource census failed') from exc
    require(0 < len(rows) <= 64 and all(len(row) == 5 and row[2] == project for row in rows),
            'resource census is missing or malformed')
    require(len({row[0] for row in rows}) == len(rows), 'duplicate resource census identity')
    return rows


def overlap(left, right):
    return posixpath.commonpath([left, right]) in (left, right)


def repository(reference):
    require(isinstance(reference, str) and reference and not any(c.isspace() for c in reference),
            'image repository is unknown')
    value = reference.split('@', 1)[0]
    if ':' in value.rsplit('/', 1)[-1]:
        value = value.rsplit(':', 1)[0]
    require(value not in ('sha256', '<none>') and not re.fullmatch(r'[0-9a-f]{64}', value),
            'image repository is unknown')
    return value


def config(data, *, image=False):
    value = data.get('Config')
    # Docker 镜像没有标签时可省略 Labels 或返回 null；容器身份标签仍必须存在。
    if image and isinstance(value, dict) and value.get('Labels') is None:
        value = {**value, 'Labels': {}}
    require(isinstance(value, dict) and isinstance(value.get('Labels'), dict) and
            isinstance(value.get('Env'), list), 'image or container config is incomplete')
    require(all(isinstance(item, str) and '=' in item for item in value['Env']),
            'invalid environment metadata')
    keys = [item.split('=', 1)[0] for item in value['Env']]
    require(len(keys) == len(set(keys)), 'duplicate environment metadata')
    return value


def revision(value):
    marker = value['Labels'].get('org.opencontainers.image.revision', '')
    require(isinstance(marker, str) and len(marker) <= 256 and
            not any(char.isspace() for char in marker), 'revision metadata is invalid')
    return marker


def reject_application_markers(value, owned_revisions):
    # OCI revision 是通用元数据；只有命中本项目身份时才能作为归属证据。
    marker = revision(value)
    require(not marker or marker not in owned_revisions,
            'application revision identity exists')
    prefixes = ('UMANEWS_', 'RACE_EVENT_LIFECYCLE_', 'RACE_LIVE_', 'RACE_DATA_SYNC_')
    require(not any(item.split('=', 1)[0].upper().startswith(prefixes)
                    for item in value['Env']), 'application environment marker exists')


def networks(data, *, stopped=False):
    settings = data.get('NetworkSettings')
    require(isinstance(settings, dict), 'network settings are missing')
    value = settings.get('Networks')
    require(isinstance(value, dict) and value, 'network isolation is unknown')
    require(all(isinstance(name, str) and name and isinstance(item, dict) and
                isinstance(item.get('NetworkID'), str) and (item['NetworkID'] or stopped)
                for name, item in value.items()), 'network identity is incomplete')
    # Docker 停止容器后可清空 NetworkID；保留声明的网络名，仍保护其数据挂载。
    return set(value), {item['NetworkID'] for item in value.values() if item['NetworkID']}


def mounts(data):
    value = data.get('Mounts')
    require(isinstance(value, list), 'mount isolation is unknown')
    result = []
    for item in value:
        require(isinstance(item, dict) and isinstance(item.get('RW'), bool),
                'mount metadata is incomplete')
        target = absolute_path(item.get('Destination'))
        require(not target.endswith('/docker.sock'), 'Docker socket mount exists')
        if item.get('Type') == 'tmpfs':
            continue
        require(item.get('Type') in ('bind', 'volume'), 'unknown mount type')
        source = host_path(item.get('Source'))
        require(not source.endswith('/docker.sock'), 'Docker socket source exists')
        require(not overlap(source, host_path('/run/user')),
                'rootless runtime socket directory mount exists')
        sockets = {host_path('/var/run/docker.sock'), host_path('/run/docker.sock')}
        endpoint = os.environ.get('DOCKER_HOST', '')
        require(not endpoint or endpoint.startswith('unix:///'), 'nonlocal Docker endpoint')
        if endpoint:
            sockets.add(host_path(endpoint[len('unix://'):]))
        require(not any(overlap(source, socket) for socket in sockets),
                'Docker socket or parent mount exists')
        require(not any(overlap(source, host_path(root)) for root in ('/proc', '/sys', '/dev')),
                'host pseudo filesystem mount exists')
        # 只读时区文件不承载应用身份或生产数据，允许不同项目共用。
        if source in {host_path('/etc/localtime'), host_path('/etc/timezone')} and not item['RW']:
            continue
        result.append(source)
    return result


def verify_row(row, data, *, running_required=True):
    cid, service, project, oneoff, workdir = row
    require(isinstance(data.get('Id'), str) and data['Id'].startswith(cid),
            'container identity drift')
    state = data.get('State')
    require(isinstance(state, dict) and isinstance(state.get('Running'), bool) and
            (state['Running'] or not running_required) and state.get('Restarting') is False,
            'container state is not stable')
    value = config(data)
    expected = {'com.docker.compose.service': service, 'com.docker.compose.project': project,
                'com.docker.compose.oneoff': oneoff,
                'com.docker.compose.project.working_dir': workdir}
    require(all(value['Labels'].get(key) == item for key, item in expected.items()),
            'container labels changed since census')
    absolute_path(workdir)
    return value


def prove_unrelated(snapshot, cid, project, release_dir, image):
    require(snapshot.stat().st_size <= 1024 * 1024, 'census exceeds size bound')
    rows = [line.split('|') for line in snapshot.read_text().splitlines() if line]
    require(0 < len(rows) <= 256 and all(len(row) == 5 for row in rows),
            'census is missing or malformed')
    require(len({row[0] for row in rows}) == len(rows), 'duplicate census identity')
    foreign = [row for row in rows if row[0] == cid]
    require(len(foreign) == 1, 'foreign service is missing from census')
    row = foreign[0]
    require(row[1] in ('web', 'worker', 'beat') and row[2] and row[2] != project and
            row[3] in ('False', 'false'), 'foreign service is not an unrelated resident')
    anchors = [item for item in rows if item[2] == project and item[1] in ('web', 'worker', 'beat')]
    require(1 <= len(anchors) <= 3 and len({item[1] for item in anchors}) == len(anchors) and
            any(item[1] == 'web' for item in anchors), 'application census anchors are ambiguous')
    owned_paths = {host_path(release_dir)}
    owned_names, owned_network_ids, owned_repositories = set(), set(), set()
    owned_revisions = set()
    owned_images = {}
    for anchor in anchors:
        require(anchor[3] in ('False', 'false') and anchor[4] == release_dir,
                'application anchor labels mismatch')
        data = inspect('container', anchor[0]); value = verify_row(anchor, data)
        require(data.get('Image') == image, 'application anchor image mismatch')
        owned_repositories.add(repository(value.get('Image')))
        if revision(value):
            owned_revisions.add(revision(value))
        names, ids = networks(data); owned_names.update(names); owned_network_ids.update(ids)
        owned_paths.update(mounts(data))
    # 镜像身份锚点与资源归属分开：包括 db/redis/nginx 等本项目依赖，亦含停止容器。
    resources = resource_inventory(project)
    require({tuple(item) for item in rows if item[2] == project} <=
            {tuple(item) for item in resources},
            'application resource disappeared or changed since census')
    for resource in resources:
        data = inspect('container', resource[0])
        resource_config = verify_row(resource, data, running_required=False)
        image_id = data.get('Image', '')
        if image_id not in owned_images:
            owned_image = inspect('image', image_id)
            require(owned_image.get('Id') == image_id, 'application image identity mismatch')
            owned_images[image_id] = config(owned_image, image=True)
        image_revision = revision(owned_images[image_id])
        if image_revision:
            owned_revisions.add(image_revision)
        if revision(resource_config):
            owned_revisions.add(revision(resource_config))
        names, ids = networks(data, stopped=not data['State']['Running'])
        owned_names.update(names); owned_network_ids.update(ids)
        owned_paths.add(host_path(resource[4])); owned_paths.update(mounts(data))
    data = inspect('container', cid); value = verify_row(row, data)
    require(data.get('Image') not in owned_images, 'application image in foreign project')
    reject_application_markers(value, owned_revisions)
    image_data = inspect('image', data.get('Image', ''))
    require(image_data.get('Id') == data['Image'], 'image inspect identity mismatch')
    image_config = config(image_data, image=True)
    reject_application_markers(image_config, owned_revisions)
    require(revision(value) == revision(image_config),
            'container and image revision metadata differ')
    tags = image_data.get('RepoTags')
    require(isinstance(tags, list) and tags, 'foreign image has no repository provenance')
    refs = {repository(value.get('Image')), *(repository(tag) for tag in tags)}
    require(not refs.intersection(owned_repositories), 'application repository alias exists')
    host = data.get('HostConfig')
    require(isinstance(host, dict) and host.get('Privileged') is False and
            host.get('PidMode') == '' and host.get('IpcMode') in ('private', '') and
            host.get('VolumesFrom') in (None, []) and
            all(host.get(key) in (None, []) for key in ('CapAdd', 'Devices', 'DeviceRequests')),
            'foreign container shares host privileges')
    mode = host.get('NetworkMode')
    require(isinstance(mode, str) and mode and mode != 'host' and
            not mode.startswith(('container:', 'service:')), 'foreign network namespace is shared')
    names, ids = networks(data)
    require(not names.intersection(owned_names) and not ids.intersection(owned_network_ids),
            'foreign service shares an application network')
    paths = [host_path(row[4]), *mounts(data)]
    require(not any(overlap(a, b) for a in paths for b in owned_paths),
            'foreign service shares application files')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--container-id', required=True)
    parser.add_argument('--expected-project', required=True)
    parser.add_argument('--expected-release-dir', required=True)
    parser.add_argument('--expected-image-id', required=True)
    args = parser.parse_args()
    try:
        prove_unrelated(args.snapshot, args.container_id, args.expected_project,
                        args.expected_release_dir, args.expected_image_id)
    except (UnprovenOwnership, OSError, TypeError, KeyError) as exc:
        # 仅输出固定分类，不回显 Docker 输出、环境值或未验证元数据。
        reason = str(exc) if isinstance(exc, UnprovenOwnership) else 'metadata inspection failed'
        print('lifecycle ownership: '+reason, file=sys.stderr)
        return 1
    print('unrelated resident isolation verified')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
