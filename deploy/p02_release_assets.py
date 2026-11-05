#!/usr/bin/env python3
"""关闭态文件备份；仅配置归档显式允许挂载内部的目录指针。"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile


def directory_link(path, root):
    """仅接受指向同根真实目录的规范相对路径，不经过其他链接。"""
    target = os.readlink(path)
    relative = PurePosixPath(target)
    if (not target or relative.is_absolute() or ".." in relative.parts
            or relative.as_posix() != target or target == "."):
        raise ValueError("P02 directory pointer target is not a bounded relative path")
    destination = path.parent / target
    try:
        resolved = destination.resolve(strict=True)
        if not resolved.is_relative_to(root.resolve()) or not resolved.is_dir():
            raise ValueError("P02 directory pointer escapes its mount or is not a directory")
        current = root
        for part in destination.relative_to(root).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("P02 directory pointer cannot traverse another link")
    except (OSError, RuntimeError) as exc:
        raise ValueError("P02 invalid directory pointer") from exc
    return {"type": "directory_link", "target": target}


def inventory(roots, *, allow_directory_links=False):
    result = {}
    for label, root in roots.items():
        root = Path(root)
        if not root.is_dir() or root.is_symlink():
            raise ValueError("P02 asset root is not a real directory")
        for path in sorted(root.rglob("*")):
            key = str(PurePosixPath(label) / path.relative_to(root).as_posix())
            if path.is_symlink() and allow_directory_links:
                result[key] = directory_link(path, root)
                continue
            if path.is_symlink() or (not path.is_file() and not path.is_dir()):
                raise ValueError("P02 asset links or special files are not supported")
            if path.is_file():
                sha = hashlib.sha256()
                with path.open("rb") as stream:
                    while block := stream.read(1024 * 1024):
                        sha.update(block)
                result[key] = sha.hexdigest()
    return result


def backup(roots, output, *, allow_directory_links=False):
    before = inventory(roots, allow_directory_links=allow_directory_links)
    output = Path(output)
    if output.exists():
        verify_archive(output, before, allow_directory_links=allow_directory_links)
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
    if inventory(roots, allow_directory_links=allow_directory_links) != before:
        raise ValueError("P02 assets changed during closed backup")
    verify_archive(partial, before, allow_directory_links=allow_directory_links)
    os.link(partial, output, follow_symlinks=False)
    partial.unlink()
    return before


def verify_archive(path, expected, *, allow_directory_links=False):
    actual = {}
    members = {}
    with tarfile.open(path, mode="r:") as tar:
        for item in tar:
            name = PurePosixPath(item.name)
            if (name.is_absolute() or ".." in name.parts or name.as_posix() != item.name
                    or item.name in members):
                raise ValueError("P02 unsafe backup member")
            members[item.name] = item
            if item.issym() and allow_directory_links:
                target = PurePosixPath(item.linkname)
                if (not item.linkname or target.is_absolute() or ".." in target.parts
                        or target.as_posix() != item.linkname or item.linkname == "."):
                    raise ValueError("P02 unsafe backup directory pointer")
                actual[item.name] = {"type": "directory_link", "target": item.linkname}
            elif not (item.isfile() or item.isdir()):
                raise ValueError("P02 unsafe backup member")
            if item.isfile():
                if item.name in actual:
                    raise ValueError("P02 duplicate backup member")
                sha = hashlib.sha256()
                with tar.extractfile(item) as stream:
                    while block := stream.read(1024 * 1024):
                        sha.update(block)
                actual[item.name] = sha.hexdigest()
    for name, member in members.items():
        for parent in PurePosixPath(name).parents:
            if str(parent) in members and not members[str(parent)].isdir():
                raise ValueError("P02 backup member descends through a non-directory")
        if member.issym():
            target = PurePosixPath(name).parent / member.linkname
            if str(target) not in members or not members[str(target)].isdir():
                raise ValueError("P02 backup pointer target is not a real directory")
            for parent in target.parents:
                if str(parent) in members and not members[str(parent)].isdir():
                    raise ValueError("P02 backup pointer traverses another link")
    if actual != expected:
        raise ValueError("P02 backup does not reproduce the source file inventory")


def config_inventory(source):
    """证书文件链接物化；内部目录指针保留，越界和循环均拒绝。"""
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
        if resolved.is_dir() and path.is_symlink():
            result[key] = directory_link(path, source)
        elif resolved.is_dir():
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
    if target.exists() or target.is_symlink():
        raise ValueError("P02 configuration copy target already exists")
    before = config_inventory(source)
    for relative, entry in before.items():
        origin = source if relative == "." else source / relative
        dest = target if relative == "." else target / relative
        if entry["type"] == "directory":
            dest.mkdir(mode=0o700, parents=True, exist_ok=True)
        elif entry["type"] == "directory_link":
            continue
        else:
            dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(origin.resolve(strict=True), dest)
            dest.chmod(0o600)
    for relative, entry in before.items():
        if entry["type"] == "directory_link":
            (target / relative).symlink_to(entry["target"], target_is_directory=True)
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
