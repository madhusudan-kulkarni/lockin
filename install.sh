#!/usr/bin/env bash
set -euo pipefail

bold()  { echo -e "\033[1m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
red()   { echo -e "\033[31m$1\033[0m"; }

need() {
  if ! command -v "$1" &>/dev/null; then
    red "Missing: $1 — $2"
    exit 1
  fi
}

need python3  "python >= 3.11"
if ! command -v nft &>/dev/null && ! command -v iptables &>/dev/null; then
  red "Missing firewall backend. Install nftables or iptables."
  exit 1
fi
echo ""

bold "Installing lockin..."
if command -v uv &>/dev/null; then
  uv tool install --force lockin-blocker
elif command -v pip &>/dev/null; then
  pip install --upgrade lockin-blocker
else
  red "Neither uv nor pip found. Install one first."
  exit 1
fi

green "lockin installed. Run 'lockin --help' to get started."
