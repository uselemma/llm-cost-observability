#!/usr/bin/env bash
set -euo pipefail
SECRET_ID="${BUILDKITE_GITHUB_SECRET_ID:-buildkite/github}"
# Agents need instance-profile or prior OIDC assume to read SM; Elastic CI
# secrets plugin may also inject GH_TOKEN directly.
if [[ -n "${GH_TOKEN:-}" && -n "${GHCR_USERNAME:-}" ]]; then
  export GHCR_TOKEN="$GH_TOKEN"
else
  RAW="$(aws secretsmanager get-secret-value --secret-id "$SECRET_ID" --query SecretString --output text)"
  TOKEN="$(jq -er '.token | select(type == "string" and length > 0)' <<<"$RAW")"
  USERNAME="$(jq -er '.username // "buildkite"' <<<"$RAW")"
  export GH_TOKEN="$TOKEN" GITHUB_TOKEN="$TOKEN" GHCR_USERNAME="$USERNAME" GHCR_TOKEN="$TOKEN"
fi
cat <<EOF
export GH_TOKEN=$(printf %q "$GH_TOKEN")
export GITHUB_TOKEN=$(printf %q "$GITHUB_TOKEN")
export GHCR_USERNAME=$(printf %q "$GHCR_USERNAME")
export GHCR_TOKEN=$(printf %q "$GHCR_TOKEN")
EOF
