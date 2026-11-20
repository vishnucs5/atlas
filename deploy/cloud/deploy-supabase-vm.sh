#!/usr/bin/env bash
# Deploy ATLAS with Supabase PostgreSQL from a checked-out repository on a Linux VM.
set -Eeuo pipefail

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

for command in docker curl stat awk; do
  command -v "$command" >/dev/null 2>&1 || fail "Required command is missing: $command"
done

docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin is required."

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(CDPATH= cd -- "$script_dir/../.." && pwd)"
env_file="${ATLAS_ENV_FILE:-$script_dir/.env.supabase}"
compose_file="$script_dir/docker-compose.supabase.yml"

[[ -f "$env_file" ]] || fail "Create $env_file from .env.supabase.example first."
[[ -f "$compose_file" ]] || fail "Deployment manifest is missing: $compose_file"

# The environment file contains production credentials and must not be group/world readable.
permissions="$(stat -c '%a' "$env_file")"
[[ "$permissions" == "600" ]] || fail "Set owner-only permissions first: chmod 600 $env_file"

atlas_domain="$(awk -F= '/^ATLAS_DOMAIN=/{sub(/^[^=]*=/, ""); print; exit}' "$env_file")"
[[ -n "$atlas_domain" ]] || fail "ATLAS_DOMAIN is required in $env_file"

compose=(docker compose --env-file "$env_file" -f "$compose_file")

# Validates every required variable without echoing its value.
"${compose[@]}" config --quiet
"${compose[@]}" up -d --build --remove-orphans

ready_url="https://${atlas_domain}/readyz"
for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error --max-time 10 "$ready_url" >/dev/null; then
    printf 'ATLAS is ready at %s\n' "$ready_url"
    exit 0
  fi
  sleep 2
done

printf 'ATLAS did not become ready at %s. Recent API and proxy logs follow.\n' "$ready_url" >&2
"${compose[@]}" logs --tail=200 api caddy >&2
exit 1
