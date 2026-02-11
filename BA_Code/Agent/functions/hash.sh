#!/bin/bash
set -euo pipefail

# hash.sh <snakemake_file_name> <job_id>
# this file will only execute if we are working with a mfa-function, it computes checksum of Snakefile for webinterface
if [ "$#" -ne 2 ]; then
	echo "Usage: $0 <snakemake_file_name> <job_id>"
	exit 1
fi

# Assign arguments to variables
FILE_NAME=$1
JOB_ID=$2

# Read credentials from cred.json
CREDENTIALS_FILE="$HOME/BA_Code/Agent/jobs/cred.json"
USER_NAME="$(jq -r '.username' "$CREDENTIALS_FILE")"
PROJECT_NAME="$(jq -r '.project' "$CREDENTIALS_FILE")"
API_SERVER="$(jq -r '.api_server' "$CREDENTIALS_FILE")"
TOKEN="$(jq -r '.token' "$CREDENTIALS_FILE")"

# Temp folder that init.sh will consume
TMP_BASE="$HOME/BA_Code/Agent/tmp-init-files"
TMP_JOB_DIR="$TMP_BASE/$JOB_ID"
mkdir -p "$TMP_JOB_DIR"

DEST_PATH="$TMP_JOB_DIR/$FILE_NAME"

DOWNLOAD_URL="http://$API_SERVER/file-management/user/$USER_NAME/project/$PROJECT_NAME/functionid/$JOB_ID/get_file/$FILE_NAME"

HTTP_CODE="$(curl -s -o "$DEST_PATH" -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$DOWNLOAD_URL")"
if [ "$HTTP_CODE" -ne 200 ]; then
	echo "File download failed with status code: $HTTP_CODE" >&2
	exit 1
fi

CHECKSUM="$(sha256sum "$DEST_PATH" | awk '{ print $1 }')"
echo "$CHECKSUM"

exit 0
