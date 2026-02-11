#!/bin/bash
set -euo pipefail

# Args:
#   $1 job_id
#   $2 file_name (optional) - if set, delete only this file inside job_dir
#   $3 keep_workspace (optional) - "1"(true)/"0"(false)
#   $4 function_id (agent appends; ignore)

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <job_id> [file_name] [keep_workspace]"
  exit 1
fi

JOB_ID="$1"
FILE_NAME="${2:-}"
KEEP_WORKSPACE="${3:-false}"

# -------------------------------
# Paths
# -------------------------------
WATCH_BASE="$HOME/BA_Code/Agent/job-watch"
WATCH_DIR="$WATCH_BASE/$JOB_ID"
STATUS_JSON="$WATCH_DIR/status.json"

# -------------------------------
# Check keep-workspace flag 
# -------------------------------
KEEP_WS_NORM="$KEEP_WORKSPACE"
if [ "$KEEP_WS_NORM" = "1" ]; then KEEP_WS_NORM="true"; fi
if [ "$KEEP_WS_NORM" = "0" ]; then KEEP_WS_NORM="false"; fi

# -------------------------------
# Filename validation (prevents path traversal)
# -------------------------------
is_safe_filename() {
  local name="$1"
  if [ -z "$name" ]; then
    return 1
  fi
  if echo "$name" | grep -qE '(/|\\|\.\.)'; then
    return 1
  fi
  return 0
}

# -------------------------------
# In case watch dir (looped by snakeD) or status.json missing
# -------------------------------
if [ ! -d "$WATCH_DIR" ]; then
  echo "[WARN] watch_dir not found for job $JOB_ID: $WATCH_DIR"
  exit 0
fi

if [ ! -f "$STATUS_JSON" ]; then
  if [ -n "$FILE_NAME" ]; then
    echo "[ERROR] status.json missing, cannot locate job_dir to delete file: $FILE_NAME"
    exit 1
  fi

  # Full delete requested, but status.json missing -> we cannot locate job_dir/workspace.
  # If keep-workspace is enabled, we must not delete the watch dir because user intends reuse.
  if [ "$KEEP_WS_NORM" = "true" ]; then
    echo "[WARN] status.json missing for job $JOB_ID; keep-workspace enabled -> preserving watch_dir."
    echo "[WARN] Cannot clear workspace job_dir without status.json. You may need to re-init a new job."
    exit 0
  fi
  # If we could not find worksapce simply remove the watch dir since we know its path
  echo "[WARN] status.json missing, deleting only watch dir for job $JOB_ID"
  rm -rf "$WATCH_DIR"
  exit 0
fi

# -------------------------------
# Read workspace/job info from status.json
# -------------------------------
JOB_DIR="$(jq -r '.job_dir // empty' "$STATUS_JSON")"
WS_NAME="$(jq -r '.workspace.name // empty' "$STATUS_JSON")"
WS_FS="$(jq -r '.workspace.filesystem // empty' "$STATUS_JSON")"
WS_DIR="$(jq -r '.workspace.path // empty' "$STATUS_JSON")"

if [ -z "$JOB_DIR" ] || [ "$JOB_DIR" = "null" ]; then
  echo "[ERROR] job_dir missing in status.json for job $JOB_ID"
  exit 1
fi

# -------------------------------
# Case 1: delete only a file inside the workspace job_dir (so inside /.../workspace-name/<jobid>/)
# -------------------------------
if [ -n "$FILE_NAME" ]; then
  if ! is_safe_filename "$FILE_NAME"; then
    echo "[ERROR] invalid file_name: $FILE_NAME"
    exit 1
  fi

  TARGET="$JOB_DIR/$FILE_NAME"

  # Ensure target is inside JOB_DIR
  case "$TARGET" in
    "$JOB_DIR"/*) ;;
    *)
      echo "[ERROR] refusing to delete outside job_dir: $TARGET"
      exit 1
      ;;
  esac

  if [ ! -e "$TARGET" ]; then
    echo "[WARN] file not found (nothing to delete): $TARGET"
    exit 0
  fi

  # Delete file (or directory if someone passed a folder name -> not implemented yet)
  if [ -d "$TARGET" ]; then
    rm -rf "$TARGET"
    echo "[INFO] deleted directory: $TARGET"
  else
    rm -f "$TARGET"
    echo "[INFO] deleted file: $TARGET"
  fi

  exit 0
fi

# -------------------------------
# Case 2: full delete (job_dir + watch_dir + optional ws_release)
# -------------------------------

# Ensure job_dir is inside workspace path (prevents deleting random dirs if status.json is corrupted)
if [ -n "$WS_DIR" ] && [ "$WS_DIR" != "null" ]; then
  case "$JOB_DIR" in
    "$WS_DIR"/*) ;;
    *)
      echo "[ERROR] refusing to delete job_dir outside workspace.path"
      echo "  workspace.path: $WS_DIR"
      echo "  job_dir:        $JOB_DIR"
      exit 1
      ;;
  esac
fi

if [ -d "$JOB_DIR" ]; then
  rm -rf "$JOB_DIR"
  echo "[INFO] deleted job_dir: $JOB_DIR"
else
  echo "[WARN] job_dir not found: $JOB_DIR"
fi

# -------------------------------
# If keep-workspace is enabled: preserve watch_dir and reset status.json, do NOT ws_release
# -------------------------------
if [ "$KEEP_WS_NORM" = "true" ]; then
  echo "[INFO] keep-workspace enabled: preserving watch_dir and resetting status.json"

  # Recreate execution dir so init.sh existing-job case can proceed
  mkdir -p "$JOB_DIR"
  echo "[INFO] recreated job_dir: $JOB_DIR"

  # Reset runs + active_run_id but keep workspace/job_dir metadata
  jq '
    .active_run_id = null
    | .runs = {}
    | .workspace.remaining_time = null
    | .workspace.state = "ACTIVE"
  ' "$STATUS_JSON" > "$STATUS_JSON.tmp" && mv "$STATUS_JSON.tmp" "$STATUS_JSON"

  exit 0
fi

rm -rf "$WATCH_DIR"
echo "[INFO] deleted watch_dir: $WATCH_DIR"

# -------------------------------
# Optionally release workspace (only executes when calling delete --jobid with no flags)
# -------------------------------
if [ -z "$WS_NAME" ] || [ "$WS_NAME" = "null" ]; then
  echo "[WARN] workspace.name missing: cannot call ws_release"
  exit 0
fi

# If filesystem exists, use it; otherwise rely on default FS (trying to match ws_release docs)
if [ -n "$WS_FS" ] && [ "$WS_FS" != "null" ]; then
  echo "[INFO] releasing workspace: $WS_NAME (filesystem: $WS_FS)"
  ws_release -F "$WS_FS" "$WS_NAME" || echo "[WARN] ws_release failed"
else
  echo "[INFO] releasing workspace: $WS_NAME"
  ws_release "$WS_NAME" || echo "[WARN] ws_release failed"
fi

exit 0
