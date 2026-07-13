#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${ROOT_DIR}/app"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "Python executable not found at ${PYTHON_BIN}" >&2
    exit 1
fi

# Default environment for local test runs. Can be overridden by caller.
export DJANGO_ENV="${DJANGO_ENV:-development}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-test-secret}"

cd "${APP_DIR}"

# Ensure coverage.py is available in the selected environment.
"${PYTHON_BIN}" -m coverage --version >/dev/null

# Allow an optional test target argument, defaulting to all tests package.
TEST_TARGET="${1:-tests}"

"${PYTHON_BIN}" -m coverage erase
"${PYTHON_BIN}" -m coverage run --rcfile=.coveragerc manage.py test "${TEST_TARGET}" -v 2
"${PYTHON_BIN}" -m coverage report --rcfile=.coveragerc -m
"${PYTHON_BIN}" -m coverage lcov --rcfile=.coveragerc -o coverage.lcov

# Normalize LCOV source file paths so editors opened at repo root can map files.
LCOV_TMP_FILE="${APP_DIR}/coverage.lcov.tmp"
awk '
    /^SF:/ {
        path = substr($0, 4)
        if (path ~ /^\// || path ~ /^app\//) {
            print $0
        } else {
            print "SF:app/" path
        }
        next
    }
    { print $0 }
' coverage.lcov > "${LCOV_TMP_FILE}"
mv "${LCOV_TMP_FILE}" coverage.lcov

echo "Coverage LCOV report: ${APP_DIR}/coverage.lcov"
