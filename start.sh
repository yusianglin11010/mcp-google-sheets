#!/usr/bin/env bash

set -euo pipefail

readonly project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly allowlist_file="${project_dir}/config/allowed-emails.txt"
readonly env_file="${project_dir}/.env"

cd "${project_dir}"

if [[ ! -s "${allowlist_file}" ]]; then
  if [[ ! -f "${env_file}" ]]; then
    echo "Missing .env; copy .env.example to .env and configure it first." >&2
    exit 1
  fi

  readonly configured_emails="$(
    sed -n 's/^[[:space:]]*AUTH_ALLOWED_EMAILS[[:space:]]*=[[:space:]]*//p' "${env_file}" \
      | tail -n 1
  )"
  if [[ -z "${configured_emails}" ]]; then
    echo "Set AUTH_ALLOWED_EMAILS in .env or create config/allowed-emails.txt." >&2
    exit 1
  fi

  mkdir -p "$(dirname "${allowlist_file}")"
  printf '%s\n' "${configured_emails}" \
    | tr ',' '\n' \
    | sed 's/^[[:space:]]*//; s/[[:space:]]*$//; /^$/d' \
    > "${allowlist_file}"
  chmod 644 "${allowlist_file}"
  echo "Initialized config/allowed-emails.txt from AUTH_ALLOWED_EMAILS."
fi

# The container runs as uid 10001 and needs read access to the bind-mounted file.
chmod 644 "${allowlist_file}"

docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build --remove-orphans sheets-mcp
