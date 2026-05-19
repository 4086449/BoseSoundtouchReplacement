#!/bin/sh
# Shared configuration for shell helpers.
# All network settings are loaded from .env (or environment variables).

_CONFIG_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# Source .env file if it exists (skip comments and blank lines)
if [ -f "$_CONFIG_DIR/.env" ]; then
  set -a
  . "$_CONFIG_DIR/.env"
  set +a
fi

# Defaults (used if neither .env nor environment provides a value)
BOSE_IP="${BOSE_IP:-10.0.0.199}"
PI_IP="${PI_IP:-10.0.0.241}"
PROXY_PORT="${PROXY_PORT:-8091}"
SPEAKER_NAME="${SPEAKER_NAME:-Living Room}"
ACTIVE_ZONE_NAME="${ACTIVE_ZONE_NAME:-}"
