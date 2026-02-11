#!/bin/bash
set -euo pipefail

# Expected args from agent:
# $1 job_id
# $2 job_name (optional)
# $3 cpus (optional)
# $4 mem (optional)
# $5 time (optional)
# $6 partition (optional)
# $7 run_id (optional)
# $8 function_id (agent appends; ignore)

if [ "$#" -lt 1 ]; then
	echo "Usage: $0 <job_id> [job_name] [cpus] [mem] [time] [partition] [run_id]"
	exit 1
fi

JOB_ID="$1"
JOB_NAME="${2:-}"
CPUS="${3:-}"
MEM="${4:-}"
TIME_LIMIT="${5:-}"
PARTITION="${6:-}"
RUN_ID="${7:-}"

# -------------------------------
# Path for status.json
# -------------------------------
WATCH_BASE="$HOME/BA_Code/Agent/job-watch"
WATCH_DIR="$WATCH_BASE/$JOB_ID"
STATUS_FILE="$WATCH_DIR/status.json"

if [ ! -f "$STATUS_FILE" ]; then
	echo "Error: status.json not found in watch dir: $STATUS_FILE"
	echo "You must run 'mcse init' first."
	exit 1
fi

# -------------------------------
# Read workspace path from status.json
# -------------------------------
JOB_DIR="$(jq -r '.job_dir' "$STATUS_FILE")"
if [ -z "$JOB_DIR" ] || [ "$JOB_DIR" = "null" ]; then
	echo "Error: job_dir missing in status.json for job $JOB_ID"
	exit 1
fi

if [ ! -d "$JOB_DIR" ]; then
	echo "Error: execution job_dir does not exist: $JOB_DIR"
	echo "Workspace may have expired. Use ws_list to check, then ws_extend/ws_restore if possible."
	exit 1
fi

# -------------------------------
# Determine run id.
# -------------------------------
HAS_RUNS="$(jq -r 'has("runs") and (.runs | type == "object")' "$STATUS_FILE")"
RUNS_LEN="$(jq -r '(.runs | length) // 0' "$STATUS_FILE")"

# Check if status.json has correct structure with "runs"
if [ "$HAS_RUNS" != "true" ] || [ "$RUNS_LEN" -eq 0 ]; then
	echo "Error: No runs found in status.json for job $JOB_ID."
	echo "You must run 'mcse init' (or 'mcse init --jobid ...') to create a run before starting."
	exit 1
fi

# If run id does not exist
if [ -z "$RUN_ID" ]; then
	ACTIVE_RUN="$(jq -r '.active_run_id // empty' "$STATUS_FILE")"
	if [ -n "$ACTIVE_RUN" ] && [ "$ACTIVE_RUN" != "null" ]; then
		RUN_ID="$ACTIVE_RUN"
	else
		RUN_ID="$(jq -r '.runs | keys | map(tonumber) | max' "$STATUS_FILE")"
	fi
fi

# Get snakefile name from status.json
SNAKEFILE_NAME="$(jq -r --arg rid "$RUN_ID" '.runs[$rid].snakefile // empty' "$STATUS_FILE")"
if [ -z "$SNAKEFILE_NAME" ] || [ "$SNAKEFILE_NAME" = "null" ]; then
	echo "Error: could not find snakefile for run_id=$RUN_ID in status.json"
	exit 1
fi

# If snakefile does not exist in worksapce
SNAKEFILE_PATH="$JOB_DIR/$SNAKEFILE_NAME"
if [ ! -f "$SNAKEFILE_PATH" ]; then
	echo "Error: Snakefile not found in execution dir: $SNAKEFILE_PATH"
	exit 1
fi

# Default resources used if a snakerule does not have them defined (only used if client didnt provide them)
DEFAULT_JOB_NAME="snakemake_job"
DEFAULT_CPUS=1
DEFAULT_MEM="2G"
DEFAULT_TIME="01:00:00"
DEFAULT_PARTITION="medium"

# ---- Apply defaults if empty ----
JOB_NAME="${JOB_NAME:-$DEFAULT_JOB_NAME}"
CPUS="${CPUS:-$DEFAULT_CPUS}"
MEM="${MEM:-$DEFAULT_MEM}"
TIME_LIMIT="${TIME_LIMIT:-$DEFAULT_TIME}"
PARTITION="${PARTITION:-$DEFAULT_PARTITION}"

# -------------------------------
# Update status.json
# -------------------------------
if [ "$HAS_RUNS" = "true" ]; then
	jq --arg rid "$RUN_ID" \
	   --arg name "$JOB_NAME" \
	   --arg part "$PARTITION" \
	   --arg time "$TIME_LIMIT" \
	   --arg mem "$MEM" \
	   --argjson cpus "$CPUS" \
	   --arg queued "$(date +"%Y-%m-%dT%H:%M:%S")" \
	   '.active_run_id = ($rid | tonumber)
	    | .runs[$rid].state="QUEUED"
	    | .runs[$rid].timestamps.queued = $queued
	    | .runs[$rid].requested_resources.job_name=$name
	    | .runs[$rid].requested_resources.partition=$part
	    | .runs[$rid].requested_resources.time=$time
	    | .runs[$rid].requested_resources.mem=$mem
	    | .runs[$rid].requested_resources.cpus_per_task=$cpus' \
	   "$STATUS_FILE" > "$STATUS_FILE.tmp" && mv "$STATUS_FILE.tmp" "$STATUS_FILE"

	echo "Job $JOB_ID run $RUN_ID marked as QUEUED and ready for SnakeD to pick up."
else
	jq --arg name "$JOB_NAME" \
	   --arg part "$PARTITION" \
	   --arg time "$TIME_LIMIT" \
	   --arg mem "$MEM" \
	   --argjson cpus "$CPUS" \
	   --arg queued "$(date +"%Y-%m-%dT%H:%M:%S")" \
	   '.state="QUEUED"
	    | .timestamps.queued = $queued
	    | .requested_resources.job_name=$name
	    | .requested_resources.partition=$part
	    | .requested_resources.time=$time
	    | .requested_resources.mem=$mem
	    | .requested_resources.cpus_per_task=$cpus' \
	   "$STATUS_FILE" > "$STATUS_FILE.tmp" && mv "$STATUS_FILE.tmp" "$STATUS_FILE"

	echo "Job $JOB_ID marked as QUEUED and ready for SnakeD to pick up."
fi

exit 0

