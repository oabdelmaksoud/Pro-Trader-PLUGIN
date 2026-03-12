#!/usr/bin/env bash
# Pro-Trader — One-step setup
# Usage: ./setup.sh

set -e

VENV_DIR=".venv"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║       Pro-Trader Setup               ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# Find python3
PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
if [ -z "$PYTHON" ]; then
    echo "❌ Python 3 not found. Install it first:"
    echo "   brew install python3"
    exit 1
fi

# Create venv if needed
if [ ! -d "$VENV_DIR" ]; then
    echo "→ Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

# Activate
source "$VENV_DIR/bin/activate"

# Install
echo "→ Installing Pro-Trader..."
pip install --upgrade pip -q
pip install -e ".[all]" -q

# Launch wizard
echo ""
pro-trader setup
