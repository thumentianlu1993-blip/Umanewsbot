"""真实 shell 校验器 + 隔离 Docker 元数据；不连接 Docker 或生产服务。"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from stable.test_lifecycle_shadow_hardening import CoherenceHarness, _write_executable


JSON_DOCKER = r'''#!/usr/bin/python3
import json,os,subprocess,sys
from pathlib import Path
args=sys.argv[1:];state=Path(os.environ['FAKE_CENSUS_STATE'])
if args and args[0]=='ps' and '-a' in args:
    project=next(x.split('=',2)[2] for x in args if x.startswith('label=com.docker.compose.project='))
    with open(os.environ['FAKE_CENSUS_LOG'],'a') as log:log.write(' '.join(args)+'\n')
    print('\n'.join(x for x in (state/('resource-ps' if (state/'resource-ps').exists() else 'ps')).read_text().splitlines() if x.split('|')[2]==project))
    raise SystemExit(0)
if len(args)==2 and args[0]=='inspect':
    path=state/('json-'+args[1])
elif len(args)==3 and args[:2]==['image','inspect']:
    path=state/('image-'+args[2])
else:
    raise SystemExit(subprocess.call([str(Path(__file__).with_name('docker-original')),*args]))
with open(os.environ['FAKE_CENSUS_LOG'],'a') as log:log.write(' '.join(args)+'\n')
if not path.exists():raise SystemExit(1)
print(path.read_text())
'''


def metadata(cid, service, *, foreign=False):
    project='foreign-app' if foreign else 'umanews'
    revision={} if foreign else {'org.opencontainers.image.revision':'a'*40}
    return {
        'Id':cid, 'Image':'sha256:foreign' if foreign else 'sha256:good',
        'State':{'Running':True,'Restarting':False},
        'Config':{
            'Image':project+':latest',
            'Labels':{**revision,'com.docker.compose.service':service,
                'com.docker.compose.project':project,'com.docker.compose.oneoff':'False',
                'com.docker.compose.project.working_dir':'/srv/foreign' if foreign else '/srv/release'},
            'Env':['FOREIGN_SERVICE=true','SECRET_MUST_NOT_LEAK=hunter2'] if foreign else
                  ['RACE_EVENT_LIFECYCLE_ENABLED=true','RACE_EVENT_LIFECYCLE_MODE=shadow'],
        },
        'HostConfig':{'NetworkMode':project+'_default','PidMode':'','IpcMode':'private',
                      'Privileged':False,'VolumesFrom':None},
        'NetworkSettings':{'Networks':{project+'_default':{'NetworkID':project+'-network-id'}}},
        'Mounts':[{'Type':'bind','Source':'/srv/'+project+'-data','Destination':'/data','RW':True}],
    }


class OwnershipHarness(CoherenceHarness):
    def __init__(self, base):
        super().__init__(base)
        (self.bin/'docker').rename(self.bin/'docker-original')
        _write_executable(self.bin/'docker',JSON_DOCKER)
        for service,cid in self.services.items():
            self.write_container(metadata(cid,service))
        self.foreign=metadata('cid-foreign','worker',foreign=True)
        self.foreign_image={
            'Id':'sha256:foreign','RepoTags':['foreign-app:latest'],
            'Config':{'Labels':{},'Env':['SECRET_MUST_NOT_LEAK=hunter2']},
        }

    def write_container(self, data):
        (self.state/('json-'+data['Id'])).write_text(json.dumps([data]))

    def add_foreign(self, *, service='worker', oneoff='False'):
        self.foreign['Config']['Labels']['com.docker.compose.service']=service
        self.foreign['Config']['Labels']['com.docker.compose.oneoff']=oneoff
        self.write_container(self.foreign)
        (self.state/('image-'+self.foreign['Image'])).write_text(json.dumps([self.foreign_image]))
        with (self.state/'ps').open('a') as stream:
            stream.write(f'cid-foreign|{service}|foreign-app|{oneoff}|/srv/foreign\n')


class LifecycleCensusOwnershipTests(SimpleTestCase):
    def assert_safe_output(self,result,harness):
        self.assertNotIn('hunter2',result.stdout+result.stderr)
        for call in harness.log.read_text().splitlines():
            self.assertTrue(call.startswith(('ps ','inspect ','image inspect ')),call)

    def test_isolated_unrelated_resident_does_not_block_umanews(self):
        for service in ('web','worker','beat'):
            with self.subTest(service=service),TemporaryDirectory() as tmp:
                h=OwnershipHarness(Path(tmp));h.add_foreign(service=service)
                result=h.run()
                self.assertEqual(result.returncode,0,result.stderr)
                self.assert_safe_output(result,h)

    def test_docker_image_without_labels_has_no_revision_marker(self):
        for label_shape in (None, 'absent'):
            with self.subTest(label_shape=label_shape),TemporaryDirectory() as tmp:
                h=OwnershipHarness(Path(tmp))
                if label_shape == 'absent':
                    del h.foreign_image['Config']['Labels']
                else:
                    h.foreign_image['Config']['Labels']=None
                h.add_foreign();result=h.run()
                self.assertEqual(result.returncode,0,result.stderr)
                self.assert_safe_output(result,h)

    def test_unrelated_beat_does_not_block_expected_stopped_beat(self):
        with TemporaryDirectory() as tmp:
            h=OwnershipHarness(Path(tmp))
            path=h.state/'ps';path.write_text('\n'.join(x for x in path.read_text().splitlines() if '|beat|' not in x)+'\n')
            h.add_foreign(service='beat');result=h.run(EXPECTED_BEAT_STATE='stopped')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assert_safe_output(result,h)

    def test_application_markers_or_shared_resources_fail_closed(self):
        def set_revision(h):h.foreign_image['Config']['Labels']['org.opencontainers.image.revision']='b'*40
        def set_container_revision(h):h.foreign['Config']['Labels']['org.opencontainers.image.revision']='b'*40
        def set_env(h):h.foreign['Config']['Env'].append('UMANEWS_RELEASE_COMMIT='+'b'*40)
        def set_flag(h):h.foreign['Config']['Env'].append('RACE_EVENT_LIFECYCLE_ENABLED=false')
        def set_image_env(h):h.foreign_image['Config']['Env'].append('RACE_LIVE_ENABLED=false')
        def same_image(h):h.foreign['Image']='sha256:good';h.foreign_image['Id']='sha256:good'
        def repo_alias(h):h.foreign_image['RepoTags'].append('umanews:old')
        def config_repo(h):h.foreign['Config']['Image']='umanews:old'
        def shared_network(h):h.foreign['NetworkSettings']['Networks']['umanews_default']={'NetworkID':'umanews-network-id'}
        def alias_network(h):h.foreign['NetworkSettings']['Networks']['foreign-app_default']['NetworkID']='umanews-network-id'
        def host_network(h):h.foreign['HostConfig']['NetworkMode']='host'
        def shared_bind(h):h.foreign['Mounts'][0]['Source']='/srv/umanews-data'
        def parent_bind(h):h.foreign['Mounts'][0]['Source']='/srv'
        def child_bind(h):h.foreign['Mounts'][0]['Source']='/srv/umanews-data/credentials'
        def socket_bind(h):h.foreign['Mounts'][0]['Source']='/var/run/docker.sock'
        def privileged(h):h.foreign['HostConfig']['Privileged']=True
        def host_pid(h):h.foreign['HostConfig']['PidMode']='host'
        def volumes_from(h):h.foreign['HostConfig']['VolumesFrom']=['cid-web:ro']
        def workdir(h):h.foreign['Config']['Labels']['com.docker.compose.project.working_dir']='/srv/release'
        cases=[set_revision,set_container_revision,set_env,set_flag,set_image_env,same_image,
               repo_alias,config_repo,shared_network,alias_network,host_network,shared_bind,
               parent_bind,child_bind,socket_bind,privileged,host_pid,volumes_from,workdir]
        for mutate in cases:
            with self.subTest(case=mutate.__name__),TemporaryDirectory() as tmp:
                h=OwnershipHarness(Path(tmp));mutate(h);h.add_foreign();result=h.run()
                self.assertNotEqual(result.returncode,0)
                self.assert_safe_output(result,h)

    def test_unknown_or_racing_metadata_fails_closed(self):
        def missing_network(h):del h.foreign['NetworkSettings']
        def missing_mounts(h):del h.foreign['Mounts']
        def missing_state(h):del h.foreign['State']
        def stopped(h):h.foreign['State']['Running']=False
        def bad_image(h):h.foreign_image['Id']='sha256:changed'
        def empty_tags(h):h.foreign_image['RepoTags']=[]
        def bad_labels(h):h.foreign['Config']['Labels']['com.docker.compose.project']='changed'
        def missing_env(h):del h.foreign_image['Config']['Env']
        def missing_network_id(h):h.foreign['NetworkSettings']['Networks']['foreign-app_default']={}
        def bad_mount(h):h.foreign['Mounts'][0]['Source']='relative/path'
        for mutate in [missing_network,missing_mounts,missing_state,stopped,bad_image,empty_tags,
                       bad_labels,missing_env,missing_network_id,bad_mount]:
            with self.subTest(case=mutate.__name__),TemporaryDirectory() as tmp:
                h=OwnershipHarness(Path(tmp));mutate(h);h.add_foreign();result=h.run()
                self.assertNotEqual(result.returncode,0)
                self.assert_safe_output(result,h)

    def test_docker_socket_parent_and_symlink_alias_fail_closed(self):
        for source in ('/var/run','/run','/var','/'):
            with self.subTest(source=source),TemporaryDirectory() as tmp:
                h=OwnershipHarness(Path(tmp));h.foreign['Mounts'][0]['Source']=source
                h.add_foreign();result=h.run()
                self.assertNotEqual(result.returncode,0);self.assert_safe_output(result,h)
        with TemporaryDirectory() as tmp:
            h=OwnershipHarness(Path(tmp));alias=Path(tmp)/'socket-parent'
            alias.symlink_to('/var/run',target_is_directory=True)
            h.foreign['Mounts'][0]['Source']=str(alias)
            h.add_foreign();result=h.run()
            self.assertNotEqual(result.returncode,0);self.assert_safe_output(result,h)

    def test_dependency_volumes_and_networks_are_protected_even_when_stopped(self):
        for service in ('db','redis'):
            for running in (True,False):
                for shared in ('volume','network'):
                    with self.subTest(service=service,running=running,shared=shared),TemporaryDirectory() as tmp:
                        h=OwnershipHarness(Path(tmp));dep=metadata('cid-'+service,service)
                        dep['State']['Running']=running
                        dep['Mounts'][0]['Source']='/volumes/'+service+'-private'
                        dep['Config']['Labels']['com.docker.compose.project.working_dir']='/srv/old-release'
                        dep['NetworkSettings']['Networks']={'private-'+service:{'NetworkID':'private-'+service+'-id'}}
                        h.write_container(dep)
                        with (h.state/'ps').open('a') as stream:
                            stream.write(f'cid-{service}|{service}|umanews|False|/srv/old-release\n')
                        if shared=='volume':
                            h.foreign['Mounts'][0]['Source']=dep['Mounts'][0]['Source']
                        else:
                            h.foreign['NetworkSettings']['Networks']={'private-'+service:{'NetworkID':'private-'+service+'-id'}}
                        h.add_foreign();result=h.run()
                        self.assertNotEqual(result.returncode,0);self.assert_safe_output(result,h)

    def test_host_pseudo_filesystems_devices_and_added_capabilities_are_not_isolated(self):
        for source in ('/proc','/sys','/dev'):
            with self.subTest(source=source),TemporaryDirectory() as tmp:
                h=OwnershipHarness(Path(tmp));h.foreign['Mounts'][0]['Source']=source
                h.add_foreign();result=h.run()
                self.assertNotEqual(result.returncode,0);self.assert_safe_output(result,h)
        for key,value in [('CapAdd',['SYS_ADMIN']),('Devices',[{'PathOnHost':'/dev/sda'}]),
                          ('DeviceRequests',[{'Driver':'nvidia'}])]:
            with self.subTest(key=key),TemporaryDirectory() as tmp:
                h=OwnershipHarness(Path(tmp));h.foreign['HostConfig'][key]=value
                h.add_foreign();result=h.run()
                self.assertNotEqual(result.returncode,0);self.assert_safe_output(result,h)

    def test_foreign_oneoff_and_inspect_failure_still_block(self):
        with TemporaryDirectory() as tmp:
            h=OwnershipHarness(Path(tmp));h.add_foreign(oneoff='True');result=h.run()
            self.assertNotEqual(result.returncode,0);self.assert_safe_output(result,h)
        with TemporaryDirectory() as tmp:
            h=OwnershipHarness(Path(tmp));h.add_foreign();(h.state/'json-cid-foreign').unlink()
            result=h.run();self.assertNotEqual(result.returncode,0);self.assert_safe_output(result,h)

    def test_nondefault_socket_and_parent_fail_closed(self):
        for source in ('/run/user/1000/docker.sock', '/run/user/1000', '/run/user',
                       '/opt/rootless/docker.sock'):
            with self.subTest(source=source),TemporaryDirectory() as tmp:
                h=OwnershipHarness(Path(tmp));h.foreign['Mounts'][0].update(
                    Source=source, Destination='/host/control.sock')
                h.add_foreign();result=h.run()
                self.assertNotEqual(result.returncode,0);self.assert_safe_output(result,h)

    def test_dependency_disappearing_or_changing_between_censuses_fails_closed(self):
        for changed in (False,True):
            with self.subTest(changed=changed),TemporaryDirectory() as tmp:
                h=OwnershipHarness(Path(tmp));dep=metadata('cid-db','db')
                dep['Mounts'][0]['Source']='/volumes/private-db'
                h.write_container(dep)
                initial=(h.state/'ps').read_text()
                with (h.state/'ps').open('a') as stream:
                    stream.write('cid-db|db|umanews|False|/srv/release\n')
                h.foreign['Mounts'][0]['Source']='/volumes/private-db'
                if changed:
                    initial+='cid-db|db|umanews|False|/srv/changed\n'
                    dep['Config']['Labels']['com.docker.compose.project.working_dir']='/srv/changed'
                    dep['Mounts'][0]['Source']='/volumes/replacement-db'
                    h.write_container(dep)
                (h.state/'resource-ps').write_text(initial)
                h.add_foreign();result=h.run()
                self.assertNotEqual(result.returncode,0);self.assert_safe_output(result,h)
