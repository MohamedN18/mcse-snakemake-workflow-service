#!/bin/bash
set -euo pipefail

# Args from agent:
# $1 file_name
# $2 job_id
# $3 function_id (appended by agent; ignore)

if [ "$#" -ne 3 ]; then
	echo "Usage: $0 <file_name> <job_id>"
	exit 1
fi

FILE_NAME="$1"
JOB_ID="$2"

# -------------------------------
# Read workspace path from status.json
# -------------------------------
WATCH_BASE="$HOME/BA_Code/Agent/job-watch"
WATCH_DIR="$WATCH_BASE/$JOB_ID"
STATUS_FILE="$WATCH_DIR/status.json"

if [ ! -f "$STATUS_FILE" ]; then
	echo "Error: status.json not found in watch dir: $STATUS_FILE"
	echo "You must run 'mcse init' first."
	exit 1
fi

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
# Read credentials
# -------------------------------
CREDENTIALS_FILE="$HOME/BA_Code/Agent/jobs/cred.json"
USER_NAME="$(jq -r '.username' "$CREDENTIALS_FILE")"
PROJECT_NAME="$(jq -r '.project' "$CREDENTIALS_FILE")"
API_SERVER="$(jq -r '.api_server' "$CREDENTIALS_FILE")"
TOKEN="$(jq -r '.token' "$CREDENTIALS_FILE")"

# -------------------------------
# Download file from API into workspace
# -------------------------------
FILE_URL="http://$API_SERVER/file-management/user/$USER_NAME/project/$PROJECT_NAME/functionid/$JOB_ID/get_file/$FILE_NAME"
OUTPUT_PATH="$JOB_DIR/$FILE_NAME"

echo "Downloading file from $FILE_URL to $OUTPUT_PATH"

HTTP_CODE="$(curl -s -o "$OUTPUT_PATH" -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$FILE_URL")"
if [ "$HTTP_CODE" -ne 200 ]; then
	echo "Error: Failed to download file '$FILE_NAME' (HTTP $HTTP_CODE)" >&2
	rm -f "$OUTPUT_PATH" || true
	exit 1
fi

echo "File successfully downloaded to $OUTPUT_PATH"
exit 0
