#!/usr/bin/env python3
"""Create and verify the host-only repair runtime without following symlinks."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    name = "migration_history_repair"
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    root_fd = os.open(root, directory_flags)
    try:
        try:
            os.mkdir("runtime", 0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        runtime_entry = os.stat("runtime", dir_fd=root_fd, follow_symlinks=False)
        parent_fd = os.open("runtime", directory_flags, dir_fd=root_fd)
    finally:
        os.close(root_fd)
    try:
        parent = os.fstat(parent_fd)
        if (
            not stat.S_ISDIR(runtime_entry.st_mode)
            or not stat.S_ISDIR(parent.st_mode)
            or runtime_entry.st_uid != os.getuid()
            or parent.st_uid != os.getuid()
            or (runtime_entry.st_dev, runtime_entry.st_ino)
            != (parent.st_dev, parent.st_ino)
        ):
            raise SystemExit("repair runtime parent is untrusted")
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        entry = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        child_fd = os.open(name, directory_flags, dir_fd=parent_fd)
        try:
            opened = os.fstat(child_fd)
            trusted = (
                stat.S_ISDIR(entry.st_mode)
                and stat.S_ISDIR(opened.st_mode)
                and entry.st_uid == os.getuid()
                and opened.st_uid == os.getuid()
                and stat.S_IMODE(entry.st_mode) == 0o700
                and stat.S_IMODE(opened.st_mode) == 0o700
                and (entry.st_dev, entry.st_ino) == (opened.st_dev, opened.st_ino)
            )
            if not trusted:
                raise SystemExit("repair runtime directory is untrusted")
        finally:
            os.close(child_fd)
    finally:
        os.close(parent_fd)


if __name__ == "__main__":
    main()
