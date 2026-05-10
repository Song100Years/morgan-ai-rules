#!/usr/bin/env bash
# deploy_guardian_to_vps.sh - Stage guardian prompt on VPS for Morgan to install.
#
# Per memory feedback_vps_ops_workflow: this script never invokes sudo. It only
# uploads the file + an installer script + a hash record to a per-run staging
# dir on the VPS, then prints the command for Morgan to run sudo manually.
#
# Output: prints staging path on VPS + the install command line.
#
# Env (optional):
#   VPS_HOST (default: morgan@76.13.180.174)
#   GUARDIAN_REF (default: <repo>/agents/guardian.md)

set -euo pipefail
export PYTHONIOENCODING=utf-8

VPS_HOST="${VPS_HOST:-morgan@76.13.180.174}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GUARDIAN_REF="${GUARDIAN_REF:-$REPO_ROOT/agents/guardian.md}"

if [[ ! -r "$GUARDIAN_REF" ]]; then
    echo "ERROR: guardian reference copy not found: $GUARDIAN_REF" >&2
    exit 1
fi

ts=$(date -u +%Y%m%dT%H%M%SZ)
remote_dir="morgan_phase2b_deploy_${ts}"

# Pre-compute hash of the file we are about to ship. CRLF normalization keeps
# Windows-checked-out content matching the LF copy git stores on disk.
ref_hash=$(tr -d '\r' < "$GUARDIAN_REF" | sha256sum | awk '{print $1}')

tmp_local=$(mktemp -d)
trap 'rm -rf "$tmp_local"' EXIT

# Stage payload.
tr -d '\r' < "$GUARDIAN_REF" > "$tmp_local/guardian.md"
printf '%s  guardian.md\n' "$ref_hash" > "$tmp_local/guardian.md.sha256"

cat > "$tmp_local/install.sh" <<'INSTALL_EOF'
#!/usr/bin/env bash
# Run on VPS: sudo bash ~/morgan_phase2b_deploy_<ts>/install.sh
# Verifies the staged hash before installing to /etc/guardian/prompt.md (0444).
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
    echo "ERROR: install.sh must be run as root (sudo bash ...)" >&2
    exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

expected=$(awk '{print $1}' guardian.md.sha256)
actual=$(tr -d '\r' < guardian.md | sha256sum | awk '{print $1}')
if [[ "$expected" != "$actual" ]]; then
    echo "ERROR: staged guardian.md hash mismatch" >&2
    echo "  expected $expected" >&2
    echo "  actual   $actual"   >&2
    exit 2
fi

mkdir -p /etc/guardian
install -m 0444 -o root -g root guardian.md /etc/guardian/prompt.md

echo "Installed /etc/guardian/prompt.md (0444 root:root)"
sha256sum /etc/guardian/prompt.md
ls -la /etc/guardian/prompt.md
INSTALL_EOF
chmod +x "$tmp_local/install.sh"

cat > "$tmp_local/README.txt" <<README_EOF
Phase 2b guardian prompt staging - $ts UTC
Source repo path: agents/guardian.md
Reference sha256: $ref_hash

Files:
  guardian.md         - prompt body (LF, 0444 after install)
  guardian.md.sha256  - expected hash (CRLF-normalized)
  install.sh          - sudo installer; verifies hash before copying

Install on VPS (Morgan runs as root):
  sudo bash ~/$remote_dir/install.sh

After install, agent verifies read-only with:
  sha256sum /etc/guardian/prompt.md
  ls -la /etc/guardian/prompt.md
README_EOF

echo "Local staging dir : $tmp_local"
echo "Reference sha256  : $ref_hash"
echo "Uploading to VPS  : $VPS_HOST:~/$remote_dir/"
echo

ssh -o BatchMode=yes "$VPS_HOST" "mkdir -p ~/$remote_dir"
scp -o BatchMode=yes \
    "$tmp_local/guardian.md" \
    "$tmp_local/guardian.md.sha256" \
    "$tmp_local/install.sh" \
    "$tmp_local/README.txt" \
    "$VPS_HOST:~/$remote_dir/"

cat <<DONE_EOF

Upload complete.

Morgan must run on VPS (this script does NOT sudo):

    ssh $VPS_HOST
    sudo bash ~/$remote_dir/install.sh

Expected sha256 after install: $ref_hash
DONE_EOF
