#!/bin/bash
set -euo pipefail

# Args from agent:
# $1 job_id
# $2 optional run_id (can be empty)
# $3 function_id (appended by agent; ignore)

if [ "$#" -eq 2 ]; then
    JOB_ID="$1"
    REQUESTED_RUN_ID=""   # no run specified
    # $2 is function_id (ignore)
elif [ "$#" -eq 3 ]; then
    JOB_ID="$1"
    REQUESTED_RUN_ID="$2"  # optional run to prioritize
    # $3 is function_id (ignore)
else
    echo "Usage:"
    echo "  $0 <job_id> <function_id>"
    echo "  $0 <job_id> <optional_run_id> <function_id>"
    exit 1
fi

WATCH_BASE="$HOME/BA_Code/Agent/job-watch"
WATCH_DIR="$WATCH_BASE/$JOB_ID"
STATUS_FILE="$WATCH_DIR/status.json"

if [ ! -f "$STATUS_FILE" ]; then
	echo "Error: status.json not found for job ID $JOB_ID."
	exit 1
fi

echo "status.json found: $STATUS_FILE"

# ------------------------------------------------------------------
# Update workspace remaining time using ws_list
# ------------------------------------------------------------------
WS_NAME="$(jq -r '.workspace.name // empty' "$STATUS_FILE")"

if [ -z "$WS_NAME" ] || [ "$WS_NAME" = "null" ]; then
	jq '.workspace.remaining_time = "expired"
	    | .workspace.state = "EXPIRED"' \
	   "$STATUS_FILE" > "$STATUS_FILE.tmp" && mv "$STATUS_FILE.tmp" "$STATUS_FILE"
else
	WS_BLOCK="$(ws_list 2>/dev/null | awk -v id="$WS_NAME" '
		$0 ~ "^id: "id"$" {inblk=1; next}
		$0 ~ "^id: " && inblk==1 {exit}
		inblk==1 {print}
	')"

	if [ -n "$WS_BLOCK" ]; then
		WS_REMAINING="$(printf '%s\n' "$WS_BLOCK" | awk -F': ' '/remaining time/ {print $2; exit}')"

		if [ -z "$WS_REMAINING" ] || [ "$WS_REMAINING" = "expired" ]; then
			jq '.workspace.remaining_time = "expired"
			    | .workspace.state = "EXPIRED"' \
			   "$STATUS_FILE" > "$STATUS_FILE.tmp" && mv "$STATUS_FILE.tmp" "$STATUS_FILE"
		else
			jq --arg rt "$WS_REMAINING" \
			   '.workspace.remaining_time = $rt
			    | .workspace.state = "ACTIVE"' \
			   "$STATUS_FILE" > "$STATUS_FILE.tmp" && mv "$STATUS_FILE.tmp" "$STATUS_FILE"
		fi
	else
		jq '.workspace.remaining_time = "expired"
		    | .workspace.state = "EXPIRED"' \
		   "$STATUS_FILE" > "$STATUS_FILE.tmp" && mv "$STATUS_FILE.tmp" "$STATUS_FILE"
	fi
fi

# ------------------------------------------------------------------
# Upload status.json to API
# ------------------------------------------------------------------
CREDENTIALS_FILE="$HOME/BA_Code/Agent/jobs/cred.json"
USER_NAME="$(jq -r '.username' "$CREDENTIALS_FILE")"
PROJECT_NAME="$(jq -r '.project' "$CREDENTIALS_FILE")"
API_SERVER="$(jq -r '.api_server' "$CREDENTIALS_FILE")"
TOKEN="$(jq -r '.token' "$CREDENTIALS_FILE")"

UPLOAD_URL="http://$API_SERVER/file-management/user/$USER_NAME/project/$PROJECT_NAME/functionid/$JOB_ID/upload"

HTTP_CODE_STATUS="$(curl -s -o /dev/null -w "%{http_code}" \
	-X POST \
	-H "Authorization: Bearer $TOKEN" \
	-F "file=@$STATUS_FILE" \
	-F "function_name=upload" \
	-F "system_upload=true" \
	"$UPLOAD_URL")"

if [ "$HTTP_CODE_STATUS" -ne 200 ]; then
	echo "Error: failed to upload status.json (HTTP $HTTP_CODE_STATUS)" >&2
	exit 1
fi

echo "Uploaded status.json to API."

# ------------------------------------------------------------------
# Upload snakemake log based on which run we are working with
# ------------------------------------------------------------------
JOB_DIR="$(jq -r '.job_dir' "$STATUS_FILE")"

HAS_RUNS="$(jq -r 'has("runs") and (.runs | type == "object")' "$STATUS_FILE")"

SNAKEMAKE_LOG_NAME=""
if [ "$HAS_RUNS" = "true" ]; then
	if [ -n "$REQUESTED_RUN_ID" ]; then
		RUN_ID="$REQUESTED_RUN_ID"
	else
		RUN_ID="$(jq -r '.active_run_id // empty' "$STATUS_FILE")"
	fi

	if [ -n "$RUN_ID" ]; then
		SNAKEMAKE_LOG_NAME="$(jq -r --arg rid "$RUN_ID" '.runs[$rid].logs.snakemake // empty' "$STATUS_FILE")"
	fi
else
	SNAKEMAKE_LOG_NAME="$(jq -r '.logs.snakemake // empty' "$STATUS_FILE")"
fi

if [ -z "$SNAKEMAKE_LOG_NAME" ]; then
	exit 0
fi

SNAKEMAKE_LOG_FILE="$JOB_DIR/$SNAKEMAKE_LOG_NAME"

if [ -f "$SNAKEMAKE_LOG_FILE" ]; then
	HTTP_CODE_SNAKE="$(curl -s -o /dev/null -w "%{http_code}" \
		-X POST \
		-H "Authorization: Bearer $TOKEN" \
		-F "file=@$SNAKEMAKE_LOG_FILE" \
		-F "function_name=upload" \
		-F "system_upload=true" \
		"$UPLOAD_URL")"

	if [ "$HTTP_CODE_SNAKE" -eq 200 ]; then
		echo "Uploaded $SNAKEMAKE_LOG_NAME to API."
	fi
fi

exit 0
