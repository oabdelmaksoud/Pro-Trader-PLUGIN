#!/usr/bin/env bash
# Pro-Trader — One-step setup
# Usage: ./setup.sh

set -e

VENV_DIR=".venv"
REQUIRED_MAJOR=3
MIN_MINOR=10
MAX_MINOR=13

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║       Pro-Trader Setup               ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ── Find a suitable Python (3.10–3.13) ──────────────────────────────────────

find_python() {
    # Try specific versions first (prefer 3.13 → 3.12 → 3.11 → 3.10)
    for minor in 13 12 11 10; do
        for cmd in "python3.${minor}" "python3${minor}"; do
            if command -v "$cmd" &>/dev/null; then
                echo "$cmd"
                return 0
            fi
        done
    done

    # Fall back to python3 / python if version is in range
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            ver=$("$cmd" -c "import sys; print(f'{sys.version_info.minor}')" 2>/dev/null)
            if [ -n "$ver" ] && [ "$ver" -ge "$MIN_MINOR" ] && [ "$ver" -le "$MAX_MINOR" ]; then
                echo "$cmd"
                return 0
            fi
        fi
    done

    return 1
}

PYTHON=$(find_python)
if [ -z "$PYTHON" ]; then
    echo "❌ Python 3.10–3.13 required (3.14+ is not yet supported)."
    echo ""
    if command -v brew &>/dev/null; then
        echo "   Install with:  brew install python@3.13"
    else
        echo "   Install Python 3.13 from https://python.org/downloads/"
    fi
    exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "→ Using $PYTHON ($PY_VERSION)"

# ── Create venv (recreate if wrong Python version) ────────────────────────

if [ -d "$VENV_DIR" ]; then
    VENV_MINOR=$("$VENV_DIR/bin/python" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "0")
    if [ "$VENV_MINOR" -lt "$MIN_MINOR" ] || [ "$VENV_MINOR" -gt "$MAX_MINOR" ]; then
        echo "→ Existing venv uses Python 3.$VENV_MINOR — recreating with $PY_VERSION..."
        rm -rf "$VENV_DIR"
    fi
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "→ Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

# Activate
source "$VENV_DIR/bin/activate"

# ── Install ─────────────────────────────────────────────────────────────────

echo "→ Installing Pro-Trader..."
pip install --upgrade pip -q
pip install -e ".[all]" -q

# ── Launch wizard ───────────────────────────────────────────────────────────

echo ""
pro-trader setup
