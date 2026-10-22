#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
buildozer -v android debug
printf '\nAPK output: %s\n' "$(pwd)/bin/"
