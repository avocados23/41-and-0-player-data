#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${REPO_ROOT}/.venv"

command -v git >/dev/null 2>&1 || { echo "setup-local: Git is required" >&2; exit 1; }
command -v "${PYTHON_BIN}" >/dev/null 2>&1 || { echo "setup-local: Python 3.12+ is required" >&2; exit 1; }

python_version="$(${PYTHON_BIN} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "${python_version}" != 3.1[2-9] && "${python_version}" != 3.[2-9][0-9] ]]; then
	echo "setup-local: Python 3.12+ is required; found ${python_version}" >&2
	exit 1
fi

cd "${REPO_ROOT}"
if [[ ! -d "${VENV_DIR}" ]]; then
	if ! "${PYTHON_BIN}" -m venv "${VENV_DIR}"; then
		echo "setup-local: Python venv support is required (install python3-venv)." >&2
		exit 1
	fi
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install --requirement requirements.txt
"${VENV_DIR}/bin/python" -m pip install --editable . --no-deps

if [[ ! -f .env ]]; then
	cp .env.example .env
	chmod 600 .env
	echo "Created .env from .env.example; update credentials before running database jobs."
else
	echo "Kept existing .env unchanged."
fi

git config core.hooksPath .githooks
echo "Local setup complete. Use ${VENV_DIR}/bin/python for pipeline commands."
