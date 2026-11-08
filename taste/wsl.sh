#!/usr/bin/env bash
# Run a taste/ script inside WSL with the Linux venv (Inkling's renderer only ships for Linux).
#   wsl -d Ubuntu -- bash taste/wsl.sh train_sft.py --pilot
set -euo pipefail
cd "$(dirname "$0")"
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/taste" UV_LINK_MODE=copy
exec "$HOME/.local/bin/uv" run --frozen python "$@"
