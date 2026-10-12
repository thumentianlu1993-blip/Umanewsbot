"""串行原CI命令的预算/owned资源/失败证据；不加载业务或改变native分片。"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from tools.test_impact.core import digest

SOFT = 6600
BUSINESS = 6000
FINAL = {'cleanup': 60, 'verify': 60, 'image': 240, 'evidence': 180, 'final': 60}


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def checksum(path, deadline=None, clock=time.monotonic):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            if deadline is not None and clock() >= deadline: raise TimeoutError('checksum deadline')
            value.update(block)
    return value.hexdigest()

def append(path, event):
    with Path(path).open('a') as stream:
        stream.write(json.dumps(dict(event, at=time.monotonic()), ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def absent(result, name):
    # Daemon errors and permission errors are never proof of absence.
    return (result.returncode == 1 and result.stdout.strip() == '' and
            result.stderr.strip() in ('Error: No such object: ' + name,
                                     'Error: No such container: ' + name))


def remove_owned(name, run=None, deadline=None):
    run = run or subprocess.run
    deadline = deadline or time.monotonic() + 40
    left = deadline - time.monotonic()
    if left <= 0: raise TimeoutError('owned cleanup budget exhausted')
    rm = run(['docker', 'rm', '-f', name], capture_output=True, text=True, timeout=min(30,left))
    left = deadline - time.monotonic()
    if left <= 0: raise TimeoutError('owned postcheck budget exhausted')
    inspect = run(['docker', 'inspect', '--format', '{{.Id}}', name],
                  capture_output=True, text=True, timeout=min(10,left))
    return {'name': name, 'rm_exit': rm.returncode, 'rm_stdout': rm.stdout,
            'rm_stderr': rm.stderr, 'inspect_exit': inspect.returncode,
            'inspect_stdout': inspect.stdout, 'inspect_stderr': inspect.stderr,
            'absent': absent(inspect, name), 'clean': rm.returncode == 0 and absent(inspect, name)}


class OwnedObserver:
    """原runner可选接口；无ledger时原算法不走此分支。"""
    def __init__(self, ledger, deadline, final_reserve):
        if not math.isfinite(deadline) or not math.isfinite(final_reserve) or final_reserve < 600:
            raise ValueError('owned deadline/final600 invalid')
        self.ledger = Path(ledger)
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.deadline = deadline
        self.final_reserve = final_reserve

    def event(self, kind, **values):
        append(self.ledger, dict(kind=kind, run_id=os.environ.get('GITHUB_RUN_ID', 'local'),
                                 run_attempt=os.environ.get('GITHUB_RUN_ATTEMPT', 'local'), **values))

    def admission(self, seconds):
        if time.monotonic() + seconds + 30 + self.final_reserve > self.deadline:
            self.event('budget-refused', seconds=seconds)
            raise RuntimeError('insufficient full invoke + cleanup + final reserve')

    def run(self, command, stage, **kwargs):
        remaining = self.deadline - self.final_reserve - time.monotonic()
        if remaining <= 0:
            raise RuntimeError('business deadline exhausted')
        timeout = min(kwargs.pop('timeout', remaining), remaining)
        check = kwargs.pop('check', False)
        process = subprocess.Popen(command, **kwargs)
        self.event('process-start', stage=stage, pid=process.pid, pgid=os.getpgid(process.pid))
        try:
            code = process.wait(timeout=timeout)
        finally:
            self.event('process-observed', stage=stage, pid=process.pid, returncode=process.poll())
        if check and code:
            raise subprocess.CalledProcessError(code, command)
        return subprocess.CompletedProcess(command, code)

    def start(self, name, cidfile, key, profile):
        self.event('container-start', name=name, cidfile=str(cidfile), key=key, profile=profile)

    def cleanup(self, name, cidfile):
        identity = Path(cidfile).read_text().strip() if Path(cidfile).exists() else None
        if identity is not None and not re.fullmatch('[0-9a-f]{64}', identity):
            self.event('identity-invalid', name=name, container_id=identity)
            raise RuntimeError('invalid owned cidfile')
        facts = remove_owned(identity or name)
        facts.update(name=name, cleanup_target=identity or name)
        self.event('container-cleanup', container_id=identity, **facts)
        if not facts['clean']:
            raise RuntimeError('owned cleanup failed or absence unknown')


class SerialCancelled(BaseException):
    pass


class Executor:
    """仅监督自己的新session进程组；取消不等于容器已消失。"""
    def run(self, command, deadline, event_file):
        if time.monotonic() >= deadline:
            return {'exit':1,'stdout':'','stderr':'process budget refused before launch','process_absent':True,'cancelled':False}
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        append(event_file, {'kind': 'supervisor-process', 'pid': process.pid, 'pgid': process.pid,
                            'command': command})
        cancelled = False
        old = {}
        def interrupt(signum, frame):
            raise SerialCancelled('signal ' + str(signum))
        for signum in (signal.SIGTERM, signal.SIGINT):
            old[signum] = signal.signal(signum, interrupt)
        try:
            stdout, stderr = process.communicate(timeout=max(.001, deadline - time.monotonic()))
        except (subprocess.TimeoutExpired, SerialCancelled) as exc:
            cancelled = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate(timeout=5)
            stderr += '\n' + repr(exc)
        finally:
            for signum, handler in old.items():
                signal.signal(signum, handler)
        try:
            os.killpg(process.pid, 0)
            group_absent = False
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            group_absent = True
        return {'exit': process.returncode, 'stdout': stdout, 'stderr': stderr,
                'pid':process.pid,'pgid':process.pid,'finished':time.monotonic(),
                'process_absent': group_absent, 'cancelled': cancelled}

    def cleanup(self, ledger, deadline=None):
        events = [json.loads(line) for line in Path(ledger).read_text().splitlines()] if Path(ledger).exists() else []
        starts = {e['name']: e for e in events if e['kind'] == 'container-start'}
        facts = []
        deadline = deadline or time.monotonic() + 60
        for name in starts:
            if time.monotonic() >= deadline:
                return False, facts + [{'clean':False,'error':'owned cleanup deadline'}]
            previous = [e for e in events if e['kind'] == 'container-cleanup' and e['name'] == name]
            failed_before = any(not e['clean'] for e in previous)
            cidfile = Path(starts[name]['cidfile'])
            identity = cidfile.read_text().strip() if cidfile.exists() else None
            if identity and not re.fullmatch('[0-9a-f]{64}',identity):
                return False, facts + [{'name':name,'clean':False,'identity_unknown':True}]
            target = identity or name
            if previous and previous[-1]['clean']:
                result = subprocess.run(['docker', 'inspect', '--format', '{{.Id}}', target],
                                        capture_output=True, text=True, timeout=min(10,max(.001,deadline-time.monotonic())))
                facts.append({'name': name, 'clean': absent(result, target) and not failed_before, 'container_id':identity,
                              'inspect_exit': result.returncode, 'inspect_stdout': result.stdout,
                              'inspect_stderr': result.stderr})
            else:
                result = remove_owned(target, deadline=deadline)
                result.update(name=name,container_id=identity,cleanup_target=target)
                result['clean'] = result['clean'] and not failed_before
                facts.append(result)
        return all(f['clean'] for f in facts) and not any(e['kind'] == 'identity-invalid' for e in events), facts


class Serial:
    def __init__(self, output, budget, executor=None, clock=time.monotonic):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.budget = budget
        self.clock = clock
        self.executor = executor or Executor()
        self.status_path = self.output / 'serial-status.json'
        self.events = self.output / 'owned-resources.jsonl'
        self.status = json.loads(self.status_path.read_text()) if self.status_path.exists() else {
            'attempted': {}, 'expected': [], 'not_started': [], 'phase_results': {}, 'fatal': False}
        identity = {k:budget.get(k) for k in ('run_id','run_attempt','job','start')}
        if self.status_path.exists() and self.status.get('job_identity') != identity:
            raise ValueError('serial state belongs to another job/start')
        self.status['job_identity'] = identity

    def persist(self):
        self.status['not_started'] = [k for k in self.status['expected'] if k not in self.status['attempted']]
        save(self.status_path, self.status)

    def check_plan(self):
        path = self.output / 'execution-plan.json'
        raw = path.read_bytes()
        plan = json.loads(raw)
        if hashlib.sha256(raw).hexdigest() != self.status['plan_raw'] or digest(plan) != self.status['plan_canonical']:
            raise ValueError('frozen plan changed')
        return plan

    def call(self, command, phase, final=False):
        deadline = min(self.clock() + FINAL[phase], self.budget['start'] + SOFT) if final else self.budget['start'] + BUSINESS
        append(self.events, {'kind':'phase-start','phase':phase,'command':command,'deadline':deadline})
        result = self.executor.run(command, deadline, self.events)
        try:
            clean, facts = self.executor.cleanup(self.events, min(self.clock() + 60, deadline if final else self.budget['start'] + SOFT))
        except BaseException as exc:
            clean, facts = False, [{'clean':False,'error':repr(exc),'unknown':True}]
        result.update(clean=clean, owned_postcheck=facts)
        self.status['phase_results'][phase] = result
        if not clean or not result['process_absent'] or result.get('cancelled'):
            self.status['fatal'] = True
        self.persist()
        return result

    def inventory(self):
        plan = self.check_plan()
        if 'inventory' in self.status['phase_results']: raise ValueError('inventory already attempted')
        selection = self.output / 'inventory-selection.json'
        result = self.call([sys.executable,'scripts/impact_ci.py','--base',plan['base_sha'],
            '--head',plan['test_sha'],'--test',plan['test_sha'],'--scope','inventory',
            '--reason','只收集完整目录，不执行全量测试','--output',str(selection)], 'inventory-plan')
        if result['exit'] or self.status['fatal']: raise RuntimeError('inventory selection failed')
        result = self.call(self.native(selection, output=self.output/'inventory',collect_only=True,
            image=self.status['image']), 'inventory')
        if result['exit'] or self.status['fatal']: raise RuntimeError('inventory failed')
        inv = json.loads((self.output/'inventory'/'execution-plan.json').read_text())
        if inv['image_id'] != self.status['image']: raise ValueError('inventory image drift')
        self.check_plan()
        self.status['inventory_complete'] = True
        self.persist()

    def native(self, plan, output=None, **options):
        cmd = [sys.executable, 'scripts/run_test_plan.py', '--plan', str(plan), '--output', str(output or self.output),
               '--resource-ledger', str(self.events), '--invoke-deadline-monotonic', str(self.budget['start'] + SOFT),
               '--final-reserve-seconds', '600']
        for key, value in options.items():
            cmd.append('--' + key.replace('_', '-'))
            if value is not True:
                cmd.append(str(value))
        return cmd

    def collect(self, selection, image):
        if 'collection' in self.status['phase_results']:
            raise ValueError('collection already attempted')
        selected = json.loads(Path(selection).read_text())
        if any(self.budget.get(k) is not None and selected[k] != self.budget[k] for k in ('run_id','run_attempt')):
            raise ValueError('selection budget identity drift')
        self.status['selection_raw'] = hashlib.sha256(Path(selection).read_bytes()).hexdigest()
        self.status['selection_identity'] = {k: selected[k] for k in ('run_id', 'run_attempt', 'test_sha', 'test_tree', 'mode')}
        # Mark before any resource creation, including failed attempts.
        self.status['phase_results']['collection'] = {'started': True}
        self.persist()
        try:
            result = self.call(self.native(selection, collect_only=True, build=True, export_image=image), 'collection')
        finally:
            exported = Path(image)
            self.status['partial_image'] = {'path':str(exported),'exists':exported.exists(),
                'bytes':exported.stat().st_size if exported.exists() else None,
                'sha256':None,
                'collect_success_confirmed':False}
            if exported.exists() and not self.status['fatal'] and self.clock() < self.budget['start']+BUSINESS:
                try: self.status['partial_image']['sha256']=checksum(exported,self.budget['start']+BUSINESS,self.clock)
                except TimeoutError as exc: self.status['partial_image']['checksum_error']=repr(exc)
            self.persist()
        if result['exit'] != 0 or self.status['fatal']:
            raise RuntimeError('collection failed/cleanup uncertain')
        plan = json.loads((self.output / 'execution-plan.json').read_text())
        if hashlib.sha256(Path(selection).read_bytes()).hexdigest() != self.status['selection_raw']:
            raise ValueError('selection changed during collection')
        if any(plan[k] != value for k, value in self.status['selection_identity'].items() if k != 'mode') or not (plan['mode'] == selected['mode'] or selected['mode'] == 'targeted' and plan['mode'] == 'expanded'):
            raise ValueError('collection identity drift')
        keys = [b['key'] for b in plan['batches']]
        if len(keys) != len(set(keys)) or (not keys and plan['mode'] != 'docs-only'):
            raise ValueError('duplicate or non-docs empty batches')
        if type(plan['count']) is not int or plan['count'] != sum(len(b['ids']) for b in plan['batches']):
            raise ValueError('native count mismatch')
        ids = [i for b in plan['batches'] for i in b['ids']]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate native IDs')
        self.status.update(expected=keys, plan_raw=hashlib.sha256((self.output / 'execution-plan.json').read_bytes()).hexdigest(),
                           plan_canonical=digest(plan), image=plan.get('image_id'), image_complete=False)
        if plan['mode'] != 'docs-only':
            image = Path(image)
            events = [json.loads(line) for line in self.events.read_text().splitlines()]
            complete = any(e['kind'] == 'process-observed' and e.get('stage') == 'image-export' and e.get('returncode') == 0 for e in events)
            if not image.is_file() or image.stat().st_size == 0 or not complete:
                raise ValueError('complete image export evidence missing')
            self.status.update(image_complete=True, image_sha256=checksum(image,self.budget['start']+BUSINESS,self.clock))
        self.status['partial_image']['collect_success_confirmed'] = True
        self.persist()

    def execute(self):
        plan = self.check_plan()
        if not plan['batches'] and plan['mode'] != 'docs-only': raise ValueError('non-docs empty plan')
        failed = False
        for batch in plan['batches']:
            key = batch['key']
            try:
                self.check_plan()
                if not re.fullmatch('batch-[0-9]+', key) or key in self.status['attempted'] or any((self.output / (key + suffix)).exists() for suffix in ('.json', '.log')):
                    raise ValueError('duplicate/unsafe batch attempt')
                seconds = 2100 if batch['profile'] == 'release-postgres' else 600
                if self.clock() + seconds + 30 + 600 > self.budget['start'] + SOFT:
                    raise ValueError('budget insufficient; remaining batches stay not-started')
                if self.status['fatal']:
                    raise ValueError('previous identity/cleanup failure')
                self.status['attempted'][key] = {'started': True, 'profile': batch['profile']}
                self.persist()
                result = self.call(self.native(self.output / 'execution-plan.json', batch=key, image=self.status['image']), key)
                self.check_plan()
                report = json.loads((self.output / (key + '.json')).read_text())
                identity = {'key': key, 'profile': batch['profile'], 'plan_digest': digest(plan),
                            **{k: plan[k] for k in ('run_id', 'run_attempt', 'test_tree')}}
                if any(report[k] != v for k, v in identity.items()):
                    raise ValueError('report/image identity drift')
                executed = report['executed']
                lines = (self.output / (key + '.log')).read_text().splitlines()
                if any(line.startswith('RUN') and not line.startswith('RUN ') for line in lines):
                    raise ValueError('malformed RUN line')
                run = [line[4:] for line in lines if line.startswith('RUN ')]
                if type(report['exit_code']) is not int or type(result['exit']) is not int or report['lifecycle'] != 'complete' or len(executed) != len(set(executed)) or set(executed) != set(batch['ids']) or run != executed:
                    raise ValueError('strict native lifecycle/RUN/identity failure')
                if any(type(report[f]) is not list for f in ('failures', 'errors', 'skips', 'expected_failures', 'unexpected_successes')):
                    raise ValueError('malformed outcomes')
                if self.status['fatal'] or result['exit'] != report['exit_code']:
                    raise ValueError('cleanup/process/native exit mismatch')
                self.status['attempted'][key].update(exit=result['exit'], complete=True)
                failed |= result['exit'] != 0 or bool(report['failures'] or report['errors'] or report['expected_failures'] or report['unexpected_successes'])
            except BaseException as exc:
                self.status.update(fatal=True, error=repr(exc))
                self.persist()
                raise
            self.persist()
        if failed:
            raise RuntimeError('business batches failed; all clean batches were attempted')

    def verify(self):
        attempt = self.output / 'verify-attempt.json'
        if attempt.exists() or (self.output / 'summary.json').exists():
            raise ValueError('verifier attempt/output already exists')
        report_paths = list(self.output.rglob('batch-*.json'))
        report_keys = [path.stem for path in report_paths]
        report_diff = {'report_paths':[str(path.relative_to(self.output)) for path in report_paths],
                       'missing':sorted(set(self.status['expected'])-set(report_keys)),
                       'extra':sorted(set(report_keys)-set(self.status['expected'])),
                       'duplicates':sorted(k for k in set(report_keys) if report_keys.count(k)>1),
                       'not_started':self.status['not_started']}
        save(attempt, dict(started=True,**report_diff))
        try:
            self.check_plan()
            self.reserve('verify')
            result = self.call([sys.executable, 'scripts/verify_test_plan.py', '--plan', str(self.output / 'execution-plan.json'),
                                '--reports', str(self.output), '--output', str(self.output / 'summary.json')], 'verify', final=True)
            save(attempt, dict(result, **report_diff,
                               summary_exists=(self.output / 'summary.json').exists()))
            if result['exit'] or self.status['fatal'] or self.status['not_started'] or report_diff['extra'] or report_diff['duplicates'] or report_diff['missing'] or not (self.output / 'summary.json').exists():
                raise RuntimeError('original verifier failed or summary absent')
        except BaseException as exc:
            evidence = json.loads(attempt.read_text())
            evidence.update(error=repr(exc), summary_exists=(self.output / 'summary.json').exists())
            save(attempt, evidence)
            raise

    def finish(self):
        try:
            clean, facts = self.executor.cleanup(self.events, min(self.clock() + 60, self.budget['start'] + SOFT))
        except BaseException as exc:
            clean, facts = False, [{'clean':False,'error':repr(exc),'unknown':True}]
        self.status.update(final_owned_postcheck=facts, cleanup_complete=clean,
                           fatal=self.status['fatal'] or not clean)
        self.persist()
        if self.status['fatal']:
            raise RuntimeError('cleanup/identity uncertain')

    def final(self, image_outcome, evidence_outcome):
        self.check_plan()
        self.reserve('final')
        self.status.update(image_upload=image_outcome, evidence_upload=evidence_outcome)
        self.status['success'] = (not self.status['fatal'] and not self.status.get('error')
            and evidence_outcome == 'success' and self.status.get('cleanup_complete') is True
            and (not self.status.get('image_complete') or image_outcome == 'success')
            and self.status['phase_results'].get('verify',{}).get('exit') == 0
            and not self.status['not_started']
            and all(v.get('complete') is True and type(v.get('exit')) is int and v['exit']==0
                for v in self.status['attempted'].values()))
        self.persist()
        if not self.status['success']:
            raise RuntimeError('final artifacts/verification/owned status incomplete')

    def reserve(self, stage):
        remaining = sum(FINAL[k] for k in list(FINAL)[list(FINAL).index(stage):])
        if stage == 'verify' and not self.status.get('cleanup_complete'):
            remaining += FINAL['cleanup']
        if self.clock() + remaining > self.budget['start'] + SOFT:
            self.status.update(fatal=True, error='final budget exhausted')
            self.persist()
            raise RuntimeError('final stage budget exhausted')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('phase', choices=['collect', 'execute', 'verify', 'finish', 'reserve', 'inventory', 'final'])
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--budget', required=True, type=Path)
    p.add_argument('--selection', type=Path)
    p.add_argument('--image', type=Path)
    p.add_argument('--stage', choices=list(FINAL))
    p.add_argument('--image-outcome', default='skipped')
    p.add_argument('--evidence-outcome', default='skipped')
    args = p.parse_args()
    budget = json.loads(args.budget.read_text())
    if type(budget['start']) not in (int,float) or not math.isfinite(budget['start']) or not 0 <= budget['start'] <= time.monotonic():
        raise ValueError('invalid monotonic job start')
    if budget.get('job') != os.environ.get('GITHUB_JOB'):
        raise ValueError('budget belongs to another workflow job')
    if budget['run_id'] != os.environ.get('GITHUB_RUN_ID', 'local') or budget['run_attempt'] != os.environ.get('GITHUB_RUN_ATTEMPT', 'local'):
        raise ValueError('budget job identity mismatch')
    serial = Serial(args.output, budget)
    try:
        if args.phase == 'collect': serial.collect(args.selection, args.image)
        elif args.phase == 'execute': serial.execute()
        elif args.phase == 'verify': serial.verify()
        elif args.phase == 'finish': serial.reserve('cleanup'); serial.finish()
        elif args.phase == 'reserve': serial.reserve(args.stage)
        elif args.phase == 'inventory': serial.inventory()
        else:
            try:
                serial.final(args.image_outcome,args.evidence_outcome)
            finally:
                print(json.dumps(serial.status,ensure_ascii=False))
    except BaseException as exc:
        serial.status.update(error=repr(exc), success=False)
        serial.persist()
        raise
    if args.phase == 'collect' and os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('image_complete=' + str(serial.status['image_complete']).lower() + '\n')


if __name__ == '__main__': main()
