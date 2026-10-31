#!/usr/bin/env python3
"""P02存活锁：内核锁加旧入口互斥目录，custody管道关闭后自动释放。"""

from contextlib import AbstractContextManager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import select
import stat
import subprocess
import sys
import time


class ReleaseLock(AbstractContextManager):
    def __init__(self, directory, metadata):
        self.directory = Path(directory)
        self.metadata = metadata
        self.token = secrets.token_hex(32)
        self.process = None

    def __enter__(self):
        for name in ("owner", "thread", "operation", "candidate_commit", "resource_domain"):
            if not isinstance(self.metadata.get(name), str) or not self.metadata[name]:
                raise ValueError("P02 release lock metadata is incomplete")
        self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "guard", str(self.directory)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.process.stdin.write((json.dumps({**self.metadata, "token": self.token, "owner_pid": os.getpid()}) + "\n").encode())
        self.process.stdin.flush()
        ready, _, _ = select.select([self.process.stdout], [], [], 5)
        message = self.process.stdout.readline() if ready else b""
        if message != b"ready\n":
            self.process.stdin.close()
            self.process.wait(timeout=5)
            self.process.stdout.close()
            raise ValueError("P02 deployment resource is locked or unsafe")
        self.identity = self.directory.stat().st_ino
        return self

    @property
    def pass_fds(self):
        return (self.process.stdin.fileno(),)

    def verify(self):
        if self.process.poll() is not None or self.directory.stat().st_ino != self.identity:
            raise ValueError("P02 deployment lock custody lost")
        expected = hashlib.sha256(self.token.encode()).hexdigest()
        if (self.directory / "token_sha256").read_text().strip() != expected:
            raise ValueError("P02 deployment lock token changed")

    def __exit__(self, *args):
        if self.process:
            self.process.stdin.close()
            self.process.wait(timeout=5)
            self.process.stdout.close()


def guard(directory):
    directory = Path(directory)
    if not directory.is_absolute() or directory.resolve() != directory or ".." in directory.parts:
        raise ValueError("unsafe lock path")
    metadata = json.loads(sys.stdin.buffer.readline())
    token = metadata.pop("token")
    metadata.update(guardian_pid=os.getpid(), started_at=datetime.now(timezone.utc).isoformat())
    token_sha = hashlib.sha256(token.encode()).hexdigest()
    fd = os.open(str(directory) + ".p02-custody", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        os.close(fd)
        raise ValueError("unsafe custody lock")
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # 原旧入口使用原子mkdir；两个代际在同一目录上竞争，不存在先检查再运行窗口。
    directory.mkdir(mode=0o700)
    inode = directory.stat().st_ino
    names = {"pid", "action", "started_at_utc", "token_sha256", "metadata.json", "heartbeat.json"}
    try:
        values = {"pid": str(os.getpid()), "action": "deploy", "started_at_utc": metadata["started_at"],
                  "token_sha256": token_sha, "metadata.json": json.dumps(metadata)}
        for name, value in values.items():
            path = directory / name
            out = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(out, "w") as stream:
                stream.write(value + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        print("ready", flush=True)
        while True:
            heartbeat = directory / "heartbeat.json"
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
            out = os.open(heartbeat, flags, 0o600)
            with os.fdopen(out, "w") as stream:
                json.dump({"guardian_pid": os.getpid(), "at": datetime.now(timezone.utc).isoformat(),
                           "monotonic": time.monotonic()}, stream)
            ready, _, _ = select.select([sys.stdin.buffer], [], [], 1)
            if ready and not os.read(sys.stdin.fileno(), 4096):
                break
    finally:
        # 不清理另一owner替换的目录，也不递归删除陌生内容。
        if directory.stat().st_ino == inode and (directory / "token_sha256").read_text().strip() == token_sha:
            if {p.name for p in directory.iterdir()} <= names:
                for name in names:
                    (directory / name).unlink(missing_ok=True)
                directory.rmdir()
        os.close(fd)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "guard":
        raise SystemExit(2)
    try:
        guard(sys.argv[2])
    except (OSError, ValueError, KeyError):
        raise SystemExit(1)
