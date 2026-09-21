#!/usr/bin/env python3
"""受共享锁保护的0079 one-shot分派；迁移仍只在run-release-tasks.sh。"""

import os
from release_0079 import ROOT, contract, compose, run, probe
from run_release_0079_preflight import control_args, prepare_env


def main():
    env = prepare_env(dict(os.environ))
    if any(probe(s, env)["running"] for s in contract.SERVICES if s != "nginx"):
        raise ValueError("0079 release task requires all application services stopped")
    run(["python3", ROOT / "deploy/release_0079.py", "verify"], env=env)
    args = control_args(env) + [
        "-e",
        "PGOPTIONS=-c lock_timeout=5000 -c statement_timeout=300000",
        "-e",
        "RELEASE_SCHEMA_GENERATION=0079",
        "-e",
        "RELEASE_TASK_PHASE=all",
        "web",
        "sh",
        "/app/deploy/docker/run-release-tasks.sh",
    ]
    print(compose(args, env))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError):
        raise SystemExit("0079 one-shot refused; services remain stopped")
