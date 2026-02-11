# mcse/status.py
import time

from .api import (
	API_SERVER,
	credentials,
	make_get_request,
	make_post_request,
	make_delete_request,
)


def delete_status_file_on_api(job_id):
	"""
	Deletes status.json for a job folder on the API server (if it exists).

	Prevents returning an old status.json

	Parameters
	----------
	job_id : str
		The job or function ID whose status.json should be deleted.

	Returns
	-------
	None
		Prints a warning if deletion fails (non-fatal).
	"""

	list_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/list_files"
	list_response = make_get_request(list_url)
	if not list_response:
		return

	file_list = list_response.json().get("files", [])
	if "status.json" in file_list:
		delete_status_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/delete_file/status.json"
		delete_resp = make_delete_request(delete_status_url)
		if not delete_resp:
			# In case we could not delete old file
			print("Warning: Failed to delete old status.json (may return stale status).")



def refresh_status_and_get_json(job_id, poll_interval=5, max_retries=12):
	"""
	Triggers a fresh agent-side status update and returns the newest status.json from the API.

	This helper is used to:
	- Refresh status.json so we can check workspace state (ACTIVE/EXPIRED)
	- Prevent stale reads by deleting the old status.json first

	Parameters
	----------
	job_id : str
		The job or function ID to refresh status for.
	poll_interval : int, optional
		Seconds to sleep between polls.
	max_retries : int, optional
		How many times to poll the API for status.json.

	Returns
	-------
	dict or None
		Parsed JSON content of status.json, or None on failure.
	"""

	# URL for listing all files in a specific job folder
	list_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/list_files"

	# Delete old status.json first to avoid stale results
	delete_status_file_on_api(job_id)

	# Trigger a status check job (agent executes status.sh and uploads new status.json)
	api_url = f"{API_SERVER}/async-function/user/{credentials['username']}/project/{credentials['project']}/functionname/status"
	data = {
		"args": [str(job_id)],
		"output": "/tmp",
		"input": "/tmp",
		"callback_url": "http://call-home.de"
	}
	response_data = make_post_request(api_url, data)
	if not response_data:
		return None

	# Poll until status.json exists
	for _ in range(max_retries):

		list_response = make_get_request(list_url)
		if not list_response:
			print("Error: Could not retrieve file list from API server.")
			return None

		file_list = list_response.json().get("files", [])
		if "status.json" not in file_list:
			print("status.json not yet available, waiting...")
			time.sleep(poll_interval)
			continue

		get_status_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/get_file/status.json"
		status_response = make_get_request(get_status_url)
		if not status_response:
			print("Failed to fetch status.json from server.")
			return None

		try:
			return status_response.json()
		except Exception as e:
			print(f"Error parsing status.json: {e}")
			return None

	print("Could not retrieve status.json after multiple retries.")
	return None


def ensure_workspace_active(job_id, action_name):
	"""
	Ensures the workspace for a job is still ACTIVE before performing an action.

	We cannot know on the API server if the workspace still exists, because workspaces live
	on the cluster and may expire. Therefore we trigger a fresh status update (status.sh),
	fetch status.json, and check workspace.state.

	Parameters
	----------
	job_id : str
		The job or function ID to validate.
	action_name : str
		Name of the action ("upload", "start", etc.) for error messages.

	Returns
	-------
	bool
		True if workspace is ACTIVE, False otherwise.
	"""

	print(f"Checking workspace state (ACTIVE/EXPIRED) for job {job_id} before {action_name}...")
	status_content = refresh_status_and_get_json(job_id)
	if status_content is None:
		print(f"Error: Could not refresh status for job {job_id}. Cannot {action_name}.")
		return False

	workspace = status_content.get("workspace", {}) or {}
	state = workspace.get("state", None)

	if state == "ACTIVE":
		return True

	if state == "EXPIRED":
		print(f"Error: Workspace for job {job_id} is EXPIRED. Cannot {action_name}.")
		print("Hint: You need to re-init a new job/workspace and re-upload your workflow/files.")
		return False

	print(f"Error: Invalid or missing workspace.state for job {job_id} (got: {state}). Cannot {action_name}.")
	print("Hint: Run 'mcse status --jobid <ID>' to inspect status.json.")
	return False