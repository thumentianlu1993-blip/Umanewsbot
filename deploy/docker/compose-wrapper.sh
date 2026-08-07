#!/bin/sh
set -eu

die() {
  echo "compose-wrapper: $*" >&2
  exit 2
}

# This is deliberately a small grammar.  It exists to make the repository's
# one-off shape unambiguous; it is not intended to mirror every Compose flag.
validate_compose_grammar() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --help)
        [ "$#" -eq 1 ] || die "--help cannot be combined with a Compose command"
        return 0
        ;;
      -f|--file|-p|--project-name|--project-directory|--env-file|--profile)
        [ "$#" -ge 2 ] || die "global option $1 requires a value"
        [ -n "$2" ] || die "global option $1 requires a non-empty value"
        case "$2" in -*) die "global option $1 has an ambiguous value" ;; esac
        shift 2
        ;;
      --file=*|--project-name=*|--project-directory=*|--env-file=*|--profile=*)
        [ -n "${1#*=}" ] || die "global option requires a non-empty value"
        shift
        ;;
      --)
        die "ambiguous global -- is not supported"
        ;;
      -*)
        die "unsupported global option: $1"
        ;;
      *)
        break
        ;;
    esac
  done

  [ "$#" -gt 0 ] || die "Compose subcommand is required"
  [ "$1" = "run" ] || return 0
  shift

  [ "${1:-}" = "--rm" ] || die "run must start with --rm --no-deps"
  shift
  [ "${1:-}" = "--no-deps" ] || die "run must start with --rm --no-deps"
  shift

  while [ "$#" -gt 0 ]; do
    case "$1" in
      -e|--env|-v|--volume|-w|--workdir|-u|--user|--name|--entrypoint|-l|--label|-p|--publish)
        [ "$#" -ge 2 ] || die "run option $1 requires a value"
        [ -n "$2" ] || die "run option $1 requires a non-empty value"
        case "$2" in -*) die "run option $1 has an ambiguous value" ;; esac
        shift 2
        ;;
      --env=*|--volume=*|--workdir=*|--user=*|--name=*|--entrypoint=*|--label=*|--publish=*)
        [ -n "${1#*=}" ] || die "run option requires a non-empty value"
        shift
        ;;
      -T|--no-TTY|--quiet-pull|--service-ports|--use-aliases|--build)
        shift
        ;;
      --pull=always|--pull=missing|--pull=never)
        shift
        ;;
      --)
        die "run service must not be preceded by --"
        ;;
      -*)
        die "unsupported run option before service: $1"
        ;;
      *)
        [ -n "$1" ] || die "run service is required"
        return 0
        ;;
    esac
  done
  die "run service is required"
}

if docker compose version >/dev/null 2>&1; then
  validate_compose_grammar "$@"
  exec docker compose "$@"
fi

if command -v docker-compose >/dev/null 2>&1; then
  validate_compose_grammar "$@"
  exec docker-compose "$@"
fi

echo "Neither 'docker compose' nor 'docker-compose' is available." >&2
exit 1
