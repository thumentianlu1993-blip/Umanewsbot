#!/bin/sh
# Read-only, host-wide lifecycle runtime census.
set -eu

fail() {
  echo "lifecycle runtime coherence: $*" >&2
  exit 1
}

require() {
  eval "value=\${$1:-}"
  [ -n "$value" ] || fail "$1 is required"
}

for name in COMPOSE_FILE EXPECTED_LIFECYCLE_ENABLED EXPECTED_LIFECYCLE_MODE \
  EXPECTED_COMPOSE_PROJECT EXPECTED_RELEASE_DIR EXPECTED_IMAGE_ID \
  EXPECTED_RELEASE_COMMIT EXPECTED_BEAT_STATE; do
  require "$name"
done

EXPECTED_LIFECYCLE_ENFORCE_CANARY_SHA256="${EXPECTED_LIFECYCLE_ENFORCE_CANARY_SHA256:-}"
EXPECTED_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS="${EXPECTED_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS:-}"

case "$COMPOSE_FILE" in
  docker-compose.prod.yml|docker-compose.prod.lowcost.yml) ;;
  *) fail "COMPOSE_FILE is not allowlisted" ;;
esac
case "$EXPECTED_LIFECYCLE_ENABLED" in true|false) ;; *) fail "invalid expected enabled value" ;; esac
case "$EXPECTED_LIFECYCLE_MODE" in off|shadow|enforce) ;; *) fail "invalid expected mode" ;; esac
case "$EXPECTED_BEAT_STATE" in running|stopped) ;; *) fail "invalid expected Beat state" ;; esac
case "$EXPECTED_COMPOSE_PROJECT" in *[!a-z0-9_-]*|"") fail "invalid expected Compose project" ;; esac
case "$EXPECTED_IMAGE_ID" in -*|*[!A-Za-z0-9:._-]*|"") fail "invalid expected image ID" ;; esac
case "$EXPECTED_RELEASE_DIR" in /*) ;; *) fail "EXPECTED_RELEASE_DIR must be absolute" ;; esac
case "$EXPECTED_RELEASE_COMMIT" in
  *[!0-9a-f]*|"") fail "EXPECTED_RELEASE_COMMIT must be a lowercase 40-character OID" ;;
esac
[ "${#EXPECTED_RELEASE_COMMIT}" -eq 40 ] || fail "EXPECTED_RELEASE_COMMIT must be a lowercase 40-character OID"
if [ "$EXPECTED_LIFECYCLE_MODE" = "enforce" ]; then
  case "$EXPECTED_LIFECYCLE_ENFORCE_CANARY_SHA256" in
    *[!0-9a-f]*|"") fail "expected enforce canary SHA must be lowercase SHA-256" ;;
  esac
  [ "${#EXPECTED_LIFECYCLE_ENFORCE_CANARY_SHA256}" -eq 64 ] || fail "expected enforce canary SHA must be lowercase SHA-256"
  case "$EXPECTED_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS" in
    *[!0-9,]*|""|*,*,*) fail "expected enforce canary event IDs must be two comma-separated integers" ;;
  esac
  first_canary_id="${EXPECTED_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS%%,*}"
  second_canary_id="${EXPECTED_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS#*,}"
  [ -n "$first_canary_id" ] && [ -n "$second_canary_id" ] \
    && [ "$first_canary_id" != "$second_canary_id" ] \
    || fail "expected enforce canary event IDs must be two distinct integers"
  case "$first_canary_id/$second_canary_id" in
    0/*|0?*/*|*/0|*/0?*) fail "expected enforce canary event IDs must be canonical positive integers" ;;
  esac
else
  [ -z "$EXPECTED_LIFECYCLE_ENFORCE_CANARY_SHA256" ] || fail "canary SHA must be empty outside enforce"
  [ -z "$EXPECTED_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS" ] || fail "canary event IDs must be empty outside enforce"
fi

snapshot="$(mktemp "${TMPDIR:-/tmp}/umanews-lifecycle-census.XXXXXX")" || fail "cannot create census snapshot"
trap 'rm -f "$snapshot"' EXIT HUP INT TERM

# Format labels in the host-wide running set.  Do not scope this to a Compose
# project: an old checkout is precisely what this check must detect.
docker ps --filter label=com.docker.compose.service \
  --format '{{.ID}}|{{.Label "com.docker.compose.service"}}|{{.Label "com.docker.compose.project"}}|{{.Label "com.docker.compose.oneoff"}}|{{.Label "com.docker.compose.project.working_dir"}}' \
  > "$snapshot" || fail "docker ps census failed"

check_service() {
  service="$1"
  expected="$2"
  count=0
  selected=""
  while IFS='|' read -r cid row_service row_project row_oneoff row_workdir; do
    [ "$row_service" = "$service" ] || continue
    [ -n "$cid" ] || fail "$service census returned an empty container ID"
    case "$cid" in -*|*[!A-Za-z0-9_.-]*) fail "$service census returned an invalid container ID" ;; esac
    case "$row_oneoff" in True|true) fail "running $service one-off exists ($cid)" ;; False|false) ;; *) fail "$service has an invalid one-off label" ;; esac
    count=$((count + 1))
    selected="$cid"
    [ "$row_project" = "$EXPECTED_COMPOSE_PROJECT" ] || fail "$service belongs to an unexpected Compose project"
    [ "$row_workdir" = "$EXPECTED_RELEASE_DIR" ] || fail "$service belongs to an unexpected release directory"
  done < "$snapshot"

  if [ "$expected" = "absent" ]; then
    [ "$count" -eq 0 ] || fail "Beat must be stopped host-wide"
    return 0
  fi
  [ "$count" -eq 1 ] || fail "$service must have exactly one running resident container"

  state="$(docker inspect --format '{{.State.Running}} {{.State.Restarting}}' "$selected")" || fail "$service inspect failed"
  [ "$state" = "true false" ] || fail "$service is not stably running"
  actual_service="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$selected")" || fail "$service label inspect failed"
  actual_project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$selected")" || fail "$service project inspect failed"
  actual_oneoff="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.oneoff"}}' "$selected")" || fail "$service one-off inspect failed"
  actual_workdir="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$selected")" || fail "$service working directory inspect failed"
  [ "$actual_service" = "$service" ] || fail "$service label mismatch"
  [ "$actual_project" = "$EXPECTED_COMPOSE_PROJECT" ] || fail "$service project mismatch"
  case "$actual_oneoff" in False|false) ;; *) fail "$service is not a resident container" ;; esac
  [ "$actual_workdir" = "$EXPECTED_RELEASE_DIR" ] || fail "$service release directory mismatch"

  actual_image="$(docker inspect --format '{{.Image}}' "$selected")" || fail "$service image inspect failed"
  [ "$actual_image" = "$EXPECTED_IMAGE_ID" ] || fail "$service image ID mismatch"
  container_commit="$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$selected")" || fail "$service container revision inspect failed"
  # A compact inspection adapter may serialize metadata as a pipe-delimited
  # record; Docker itself returns the single label value.
  case "$container_commit" in *'|'*) container_commit="${container_commit##*|}" ;; esac
  [ "$container_commit" = "$EXPECTED_RELEASE_COMMIT" ] || fail "$service container revision mismatch"
  actual_commit="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$actual_image")" || fail "$service image revision inspect failed"
  [ "$actual_commit" = "$EXPECTED_RELEASE_COMMIT" ] || fail "$service image revision mismatch"

  env_output="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$selected")" || fail "$service environment inspect failed"
  enabled_count="$(printf '%s\n' "$env_output" | awk -F= '$1=="RACE_EVENT_LIFECYCLE_ENABLED"{n++} END{print n+0}')"
  mode_count="$(printf '%s\n' "$env_output" | awk -F= '$1=="RACE_EVENT_LIFECYCLE_MODE"{n++} END{print n+0}')"
  canary_sha_count="$(printf '%s\n' "$env_output" | awk -F= '$1=="RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256"{n++} END{print n+0}')"
  canary_ids_count="$(printf '%s\n' "$env_output" | awk -F= '$1=="RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS"{n++} END{print n+0}')"
  [ "$enabled_count" -eq 1 ] || fail "$service lifecycle enabled key count is not one"
  [ "$mode_count" -eq 1 ] || fail "$service lifecycle mode key count is not one"
  if [ "$EXPECTED_LIFECYCLE_ENABLED/$EXPECTED_LIFECYCLE_MODE" = "false/off" ] \
    && [ -z "$EXPECTED_LIFECYCLE_ENFORCE_CANARY_SHA256" ] \
    && [ -z "$EXPECTED_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS" ]; then
    [ "$canary_sha_count" -le 1 ] || fail "$service enforce canary SHA key count exceeds one"
    [ "$canary_ids_count" -le 1 ] || fail "$service enforce canary event IDs key count exceeds one"
  else
    [ "$canary_sha_count" -eq 1 ] || fail "$service enforce canary SHA key count is not one"
    [ "$canary_ids_count" -eq 1 ] || fail "$service enforce canary event IDs key count is not one"
  fi
  actual_enabled="$(printf '%s\n' "$env_output" | awk -F= '$1=="RACE_EVENT_LIFECYCLE_ENABLED"{print substr($0,index($0,"=")+1)}')"
  actual_mode="$(printf '%s\n' "$env_output" | awk -F= '$1=="RACE_EVENT_LIFECYCLE_MODE"{print substr($0,index($0,"=")+1)}')"
  actual_canary_sha="$(printf '%s\n' "$env_output" | awk -F= '$1=="RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_SHA256"{print substr($0,index($0,"=")+1)}')"
  actual_canary_ids="$(printf '%s\n' "$env_output" | awk -F= '$1=="RACE_EVENT_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS"{print substr($0,index($0,"=")+1)}')"
  [ "$actual_enabled" = "$EXPECTED_LIFECYCLE_ENABLED" ] || fail "$service lifecycle enabled mismatch"
  [ "$actual_mode" = "$EXPECTED_LIFECYCLE_MODE" ] || fail "$service lifecycle mode mismatch"
  [ "$actual_canary_sha" = "$EXPECTED_LIFECYCLE_ENFORCE_CANARY_SHA256" ] || fail "$service enforce canary SHA mismatch"
  [ "$actual_canary_ids" = "$EXPECTED_LIFECYCLE_ENFORCE_CANARY_EVENT_IDS" ] || fail "$service enforce canary event IDs mismatch"
}

check_service web present
check_service worker present
if [ "$EXPECTED_BEAT_STATE" = "running" ]; then
  check_service beat present
else
  check_service beat absent
fi

echo "lifecycle runtime coherence verified"
