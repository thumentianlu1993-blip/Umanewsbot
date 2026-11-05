#!/usr/bin/env python3
"""关闭态静态/媒体文件备份与验证；拒绝链接、设备文件和目录穿越。"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile


def inventory(roots):
    result = {}
    for label, root in roots.items():
        root = Path(root)
        if not root.is_dir() or root.is_symlink():
            raise ValueError("P02 asset root is not a real directory")
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or (not path.is_file() and not path.is_dir()):
                raise ValueError("P02 asset links or special files are not supported")
            if path.is_file():
                sha = hashlib.sha256()
                with path.open("rb") as stream:
                    while block := stream.read(1024 * 1024):
                        sha.update(block)
                result[str(PurePosixPath(label) / path.relative_to(root).as_posix())] = sha.hexdigest()
    return result


def backup(roots, output):
    before = inventory(roots)
    output = Path(output)
    if output.exists():
        verify_archive(output, before)
        return before
    partial = output.with_name(output.name + ".partial")
    # 未完成文件保留，调用者不能把它当成功；同一停写切点可重新生成自己的临时文件。
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        with tarfile.open(fileobj=stream, mode="w") as tar:
            for label, root in roots.items():
                tar.add(root, arcname=label, recursive=True)
        stream.flush()
        os.fsync(stream.fileno())
    if inventory(roots) != before:
        raise ValueError("P02 assets changed during closed backup")
    verify_archive(partial, before)
    os.link(partial, output, follow_symlinks=False)
    partial.unlink()
    return before


def verify_archive(path, expected):
    actual = {}
    with tarfile.open(path, mode="r:") as tar:
        for item in tar:
            name = PurePosixPath(item.name)
            if name.is_absolute() or ".." in name.parts or not (item.isfile() or item.isdir()):
                raise ValueError("P02 unsafe backup member")
            if item.isfile():
                if item.name in actual:
                    raise ValueError("P02 duplicate backup member")
                sha = hashlib.sha256()
                with tar.extractfile(item) as stream:
                    while block := stream.read(1024 * 1024):
                        sha.update(block)
                actual[item.name] = sha.hexdigest()
    if actual != expected:
        raise ValueError("P02 backup does not reproduce the source file inventory")


def config_inventory(source):
    """配置链接只允许指向同一挂载根内的普通文件，拒绝目录链接和循环。"""
    source = Path(source)
    if source.is_symlink() or not source.exists():
        raise ValueError("P02 configuration root missing or linked")
    boundary = source.resolve()
    paths = [source] if source.is_file() else [source, *sorted(source.rglob("*"))]
    result = {}
    for path in paths:
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("P02 invalid configuration link") from exc
        if not (resolved == boundary or resolved.is_relative_to(boundary)):
            raise ValueError("P02 configuration link escapes its mount")
        key = "." if path == source else path.relative_to(source).as_posix()
        if resolved.is_dir() and not path.is_symlink():
            result[key] = {"type": "directory"}
        elif resolved.is_file():
            digest = hashlib.sha256()
            with resolved.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    digest.update(block)
            result[key] = {"type": "file", "sha256": digest.hexdigest()}
        else:
            raise ValueError("P02 unsupported configuration member")
    return result


def materialize_config(source, target):
    import shutil
    source, target = Path(source), Path(target)
    before = config_inventory(source)
    for relative, entry in before.items():
        origin = source if relative == "." else source / relative
        dest = target if relative == "." else target / relative
        if entry["type"] == "directory":
            dest.mkdir(mode=0o700, parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(origin.resolve(strict=True), dest)
            dest.chmod(0o600)
    if config_inventory(source) != before or config_inventory(target) != before:
        raise ValueError("P02 configuration changed during materialization")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "inventory", "static"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--static", type=Path, required=True)
    parser.add_argument("--media", type=Path)
    args = parser.parse_args()
    roots = {"static": args.static}
    if args.action != "static":
        if args.media is None:
            parser.error("media root required for backup or full inventory")
        roots["media"] = args.media
    value = backup(roots, args.output) if args.action == "backup" else inventory(roots)
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    print(json.dumps({"file_count": len(value), "sha256": hashlib.sha256(data).hexdigest()}))


if __name__ == "__main__":
    main()
