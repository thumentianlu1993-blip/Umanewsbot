#!/bin/sh
set -eu

reject() {
  printf '%s\n' "historical detail runner v2 rejected input: $*" >&2
  exit 2
}

image=""
descriptor=""
repo_root=""
plan_root=""
run_root=""
host_lock_root=""
stage=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --image|--descriptor|--repo-root|--plan-root|--run-root|--host-lock-root|--stage)
      option="$1"
      [ "$#" -ge 2 ] || reject "missing value for $option"
      value="$2"
      shift 2
      case "$option" in
        --image) image="$value" ;;
        --descriptor) descriptor="$value" ;;
        --repo-root) repo_root="$value" ;;
        --plan-root) plan_root="$value" ;;
        --run-root) run_root="$value" ;;
        --host-lock-root) host_lock_root="$value" ;;
        --stage) stage="$value" ;;
      esac
      ;;
    --apply|--database|--database-url|--db-url|--argv|--shell|--env-file)
      reject "forbidden option $1"
      ;;
    *)
      reject "unsupported option $1"
      ;;
  esac
done

[ -n "$image" ] || reject "--image is required"
[ -n "$descriptor" ] || reject "--descriptor is required"
[ -n "$repo_root" ] || reject "--repo-root is required"
[ -n "$plan_root" ] || reject "--plan-root is required"
[ -n "$run_root" ] || reject "--run-root is required"
[ -n "$host_lock_root" ] || reject "--host-lock-root is required"
[ -n "$stage" ] || reject "--stage is required"

case "$image" in
  sha256:*) image_digest="${image#sha256:}" ;;
  *) reject "image must be an immutable sha256 digest" ;;
esac
case "$image_digest" in
  ''|*[!0-9a-f]*) reject "image must be an immutable sha256 digest" ;;
esac
[ "${#image_digest}" -eq 64 ] || reject "image must be an immutable sha256 digest"

validate_root() {
  label="$1"
  root="$2"
  [ -d "$root" ] || reject "$label root is missing"
  [ ! -L "$root" ] || reject "$label root is a symlink"
  physical="$(CDPATH= cd -- "$root" 2>/dev/null && pwd -P)" || reject "$label root is invalid"
  [ "$physical" = "$root" ] || reject "$label root contains a symlink or is not canonical"
}

validate_root repo "$repo_root"
validate_root plan "$plan_root"
validate_root run "$run_root"
validate_root host_lock "$host_lock_root"
[ -f "$descriptor" ] || reject "descriptor is missing"
[ ! -L "$descriptor" ] || reject "descriptor is a symlink"
case "$descriptor" in
  "$plan_root"/*) ;;
  *) reject "descriptor must be inside plan root" ;;
esac
descriptor_dir="${descriptor%/*}"
descriptor_name="${descriptor##*/}"
physical_descriptor_dir="$(CDPATH= cd -- "$descriptor_dir" 2>/dev/null && pwd -P)" || reject "descriptor path is invalid"
[ "$physical_descriptor_dir/$descriptor_name" = "$descriptor" ] || reject "descriptor path contains a symlink or is not canonical"

descriptor_image_digest="$(
  PYTHONDONTWRITEBYTECODE=1 python3 -c \
    'import json,sys; value=json.load(open(sys.argv[1], encoding="utf-8")); print(value.get("image", {}).get("digest", ""))' \
    "$descriptor"
)" || reject "descriptor image digest is unreadable"
[ "$descriptor_image_digest" = "$image" ] || reject "image digest mismatch with descriptor"

inspection="$(docker image inspect --format '{{.Id}}|{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")" || {
  reject "image inspection failed"
}
case "$inspection" in
  *'|'*) ;;
  *) reject "image inspection output is invalid" ;;
esac
actual_image_digest="${inspection%%|*}"
actual_image_revision="${inspection#*|}"
[ "$actual_image_digest" = "$descriptor_image_digest" ] || reject "actual image digest mismatch"
case "$actual_image_revision" in
  ''|*[!0-9a-f]*) reject "actual image revision is invalid" ;;
esac
[ "${#actual_image_revision}" -eq 40 ] || reject "actual image revision is invalid"

runner_tool="$repo_root/runtime/tools/historical_race_detail_runner_v2.py"
[ -f "$runner_tool" ] || reject "runner v2 tool is missing from repo root"
PYTHONDONTWRITEBYTECODE=1 python3 "$runner_tool" \
  --descriptor "$descriptor" \
  --repo-root "$repo_root" \
  --plan-root "$plan_root" \
  --run-root "$run_root" \
  --host-lock-root "$host_lock_root" \
  --stage "$stage" \
  --actual-image-digest "$actual_image_digest" \
  --actual-image-revision "$actual_image_revision" \
  --preflight-only >/dev/null || reject "runner v2 preflight failed"

case "$stage" in
  discover|cache) network_mode="bridge" ;;
  parse|validate|package) network_mode="none" ;;
  *) reject "unsupported stage $stage" ;;
esac

exec docker run --rm \
  --read-only \
  --network "$network_mode" \
  --entrypoint python \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=128m \
  -v "$repo_root:$repo_root:ro" \
  -v "$plan_root:$plan_root:ro" \
  -v "$run_root:$run_root:rw" \
  -v "$host_lock_root:$host_lock_root:rw" \
  "$image" \
  "$repo_root/runtime/tools/historical_race_detail_runner_v2.py" \
    --descriptor "$descriptor" \
    --repo-root "$repo_root" \
    --plan-root "$plan_root" \
    --run-root "$run_root" \
    --host-lock-root "$host_lock_root" \
    --stage "$stage" \
    --actual-image-digest "$actual_image_digest" \
    --actual-image-revision "$actual_image_revision"
