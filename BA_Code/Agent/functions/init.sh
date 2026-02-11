#!/bin/bash
set -euo pipefail

# Args:
# New job:	<snakemake_file_name> <function_id>
# Existing job:	<snakemake_file_name> <job_id> <function_id>
if [ "$#" -ne 2 ] && [ "$#" -ne 3 ]; then
	echo "Usage:"
	echo "  $0 <snakemake_file_name> <function_id>"
	echo "  $0 <snakemake_file_name> <job_id> <function_id>"
	exit 1
fi

FILE_NAME="$1"

# If 2 args: JOB_ID is the function_id (new job)
# If 3 args: JOB_ID is provided explicitly (existing job) -> last arg is function_id from agent (ignore)
if [ "$#" -eq 2 ]; then
	JOB_ID="$2"
	IS_EXISTING_JOB="false"
else
	JOB_ID="$2"
	IS_EXISTING_JOB="true"
fi

# -------------------------------
# Create the folder that snakeD will loop
# -------------------------------
WATCH_BASE="$HOME/BA_Code/Agent/job-watch"
WATCH_DIR="$WATCH_BASE/$JOB_ID"
STATUS_JSON="$WATCH_DIR/status.json"
mkdir -p "$WATCH_DIR"

# Read credentials from cred.json
CREDENTIALS_FILE="$HOME/BA_Code/Agent/jobs/cred.json"
USERNAME="$(jq -r '.username' "$CREDENTIALS_FILE")"
PROJECT="$(jq -r '.project' "$CREDENTIALS_FILE")"
TOKEN="$(jq -r '.token' "$CREDENTIALS_FILE")"
API_SERVER="$(jq -r '.api_server' "$CREDENTIALS_FILE")"


# -------------------------------
# Existing job: load job_dir from status.json and append a new run
# -------------------------------
if [ "$IS_EXISTING_JOB" = "true" ]; then
  # status.json not found
	if [ ! -f "$STATUS_JSON" ]; then
		echo "Error: status.json not found for existing job: $STATUS_JSON"
		exit 1
	fi
  # job dir inside workspace not found
	EXEC_JOB_DIR="$(jq -r '.job_dir' "$STATUS_JSON")"
	if [ -z "$EXEC_JOB_DIR" ] || [ "$EXEC_JOB_DIR" = "null" ]; then
		echo "Error: job_dir missing in status.json for job $JOB_ID"
		exit 1
	fi
  # Name exists in status.json but directory no longer exists
	if [ ! -d "$EXEC_JOB_DIR" ]; then
		echo "Error: execution job_dir does not exist: $EXEC_JOB_DIR"
		echo "Workspace may have expired. Use ws_list to check, then ws_extend/ws_restore if possible."
		exit 1
	fi


	# Determine next run id
	NEXT_RUN_ID="$(jq -r 'if (.runs | type) == "object" and (.runs | length) > 0 then (.runs | keys | map(tonumber) | max) + 1 else 1 end' "$STATUS_JSON")"

	# Download Snakefile and store it in workspace
	DOWNLOAD_URL="http://$API_SERVER/file-management/user/$USERNAME/project/$PROJECT/functionid/$JOB_ID/get_file/$FILE_NAME"
	DEST_SNAKEFILE="$EXEC_JOB_DIR/$FILE_NAME"

	echo "Downloading Snakefile from HPCSerA:"
	echo "  $DOWNLOAD_URL"

	HTTP_CODE="$(curl -s -w "%{http_code}" \
		-H "Authorization: Bearer $TOKEN" \
		-o "$DEST_SNAKEFILE" \
		"$DOWNLOAD_URL")"

	if [ "$HTTP_CODE" -ne 200 ]; then
		echo "Error: failed to download Snakefile (HTTP $HTTP_CODE)" >&2
		rm -f "$DEST_SNAKEFILE"
		exit 1
	fi

	# Append new run entry + set active_run_id
	jq --arg rid "$NEXT_RUN_ID" \
	   --arg sf "$FILE_NAME" \
	   --arg created "$(date +"%Y-%m-%dT%H:%M:%S")" \
	   '.runs = (.runs // {})
	    | .runs[$rid] = {
		"snakefile": $sf,
		"state": "PENDING",
		"timestamps": {
			"created": $created,
			"queued": null,
			"started": null,
			"finished": null
		},
		"snakemake_exit_code": null,
		"requested_resources": {
			"job_name": null,
			"partition": null,
			"time": null,
			"mem": null,
			"cpus_per_task": null
		},
		"slurm": {
        "executor": "snakemake-executor-plugin-slurm",
        "job_ids": [],
        "jobs_submitted": 0,
        "last_update": null
		},
		"logs": {
			"snakemake": null
		}
	    }
	    | .active_run_id = ($rid | tonumber)' \
	   "$STATUS_JSON" > "$STATUS_JSON.tmp" && mv "$STATUS_JSON.tmp" "$STATUS_JSON"

	echo "Added Snakefile to existing job $JOB_ID"
	echo "  run_id:        $NEXT_RUN_ID"
	echo "  watch_dir:     $WATCH_DIR"
	echo "  snakefile:     $DEST_SNAKEFILE"

	exit 0
fi

# -------------------------------
# New job: Create Campaign storage / workspace
# -------------------------------
WS_NAME="mcse_job_${JOB_ID}"

WS_OUT="$(ws_allocate "$WS_NAME" 2>&1)"

WS_DIR="$(printf '%s\n' "$WS_OUT" | grep '^/' | head -n 1)"
WS_DAYS="$(printf '%s\n' "$WS_OUT" | awk -F': ' '/remaining time in days/ {print $2; exit}')"
WS_FS="$(printf '%s' "$WS_DIR" | awk -F'/' 'NF>=3 {print $3; exit}')"



if [ -z "$WS_DIR" ] || [ ! -d "$WS_DIR" ]; then
  echo "Error: ws_allocate did not return a valid directory."
  echo "Returned: '$WS_DIR'"
  exit 1
fi

# Fallback if parsing failed 
WS_DAYS="${WS_DAYS:-null}"
WS_FS="${WS_FS:-null}"

EXEC_JOB_DIR="$WS_DIR/$JOB_ID"
mkdir -p "$EXEC_JOB_DIR"

# ------------------------------------------------------------------
# Instead we download Snakefile directly here (should be done in hash.sh in case we are using mfa-function like intended)
# ------------------------------------------------------------------
DOWNLOAD_URL="http://$API_SERVER/file-management/user/$USERNAME/project/$PROJECT/functionid/$JOB_ID/get_file/$FILE_NAME"
DEST_SNAKEFILE="$EXEC_JOB_DIR/$FILE_NAME"

echo "Downloading Snakefile from HPCSerA:"
echo "  $DOWNLOAD_URL"

HTTP_CODE="$(curl -s -w "%{http_code}" \
	-H "Authorization: Bearer $TOKEN" \
	-o "$DEST_SNAKEFILE" \
	"$DOWNLOAD_URL")"

if [ "$HTTP_CODE" -ne 200 ]; then
	echo "Error: failed to download Snakefile (HTTP $HTTP_CODE)" >&2
	rm -f "$DEST_SNAKEFILE"
	exit 1
fi

# -------------------------------
# Create initial status.json
# -------------------------------
cat <<EOF > "$STATUS_JSON"
{
  "hpcsera_job_id": "$JOB_ID",
  "workspace": {
    "path": "$WS_DIR",
	"name": "$WS_NAME",
    "days_allocated": $WS_DAYS,
	"filesystem": "$WS_FS",
	"remaining_time": null,
	"state": "ACTIVE"
  },
  "job_dir": "$EXEC_JOB_DIR",
  "active_run_id": 1,
  "runs": {
    "1": {
      "snakefile": "$FILE_NAME",
      "state": "PENDING",
      "timestamps": {
        "created": "$(date +"%Y-%m-%dT%H:%M:%S")",
        "queued": null,
        "started": null,
        "finished": null
      },
      "snakemake_exit_code": null,
      "requested_resources": {
        "job_name": null,
        "partition": null,
        "time": null,
        "mem": null,
        "cpus_per_task": null
      },
      "slurm": {
        "executor": "snakemake-executor-plugin-slurm",
        "job_ids": [],
        "jobs_submitted": 0,
        "last_update": null
      },
      "logs": {
        "snakemake": null
      }
    }
  }
}
EOF

echo "Initialized job $JOB_ID"
echo "  workspace_dir: $WS_DIR"
echo "  exec_job_dir:  $EXEC_JOB_DIR"
echo "  watch_dir:     $WATCH_DIR"
echo "  snakefile:     $DEST_SNAKEFILE"

exit 0
