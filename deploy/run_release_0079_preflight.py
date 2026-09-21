#!/usr/bin/env python3
"""仅控制容器关闭writer，创建精确0079 handoff。"""

import os
from pathlib import Path
from release_0079 import ROOT, REPAIR, candidate, compose, contract, run


def control_args(env):
    args = ["run", "--rm", "--no-deps", "-v", f"{REPAIR}:{REPAIR}:rw"]
    for flag in contract.WRITER_FLAGS:
        args += ["-e", f"{flag}=false"]
    for key in (
        "COMPOSE_FILE",
        "EXPECTED_CANDIDATE_COMMIT",
        "EXPECTED_CANDIDATE_IMAGE_ID",
        "EXPECTED_PRODUCTION_DB_IDENTITY_SHA256",
        "RELEASE_B_PREFLIGHT_ARTIFACT_PATH",
        "RELEASE_B_PREFLIGHT_ARTIFACT_SHA256",
        "RELEASE_B_PREFLIGHT_ACTION",
        "EXPECTED_DEPLOYMENT_LOCK_TOKEN_SHA256",
        *(key.upper() for key in contract.BINDING_FIELDS),
    ):
        args += ["-e", f'{key}={env.get(key, "")}']
    return args


def prepare_env(env):
    run([ROOT / "deploy/deployment_lock.sh", "verify"], env=env)
    candidate(env)
    path = Path(env["RELEASE_B_PREFLIGHT_ARTIFACT_PATH"])
    if REPAIR not in path.parents or ".." in path.parts:
        raise ValueError("0079 handoff must remain in repair root")
    fd = contract._parent(path)
    os.close(fd)
    env["EXPECTED_DEPLOYMENT_LOCK_TOKEN_SHA256"] = run(
        [
            "cat",
            Path(env.get("DEPLOYMENT_LOCK_DIR", "/tmp/umanews-deployment.lock"))
            / "token_sha256",
        ],
        env=env,
    )
    return env


if __name__ == "__main__":
    try:
        env = prepare_env(dict(os.environ))
        print(
            compose(
                [
                    *control_args(env),
                    "web",
                    "python",
                    "manage.py",
                    "release_0079_schema",
                    "handoff",
                ],
                env,
            )
        )
    except (ValueError, KeyError, OSError):
        raise SystemExit(
            "0079 handoff preflight refused; inspect bounded release evidence"
        )
