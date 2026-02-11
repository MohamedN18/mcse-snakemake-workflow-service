# mcse/commands.py
import os
import time

from .api import (
	API_SERVER,
	credentials,
	make_get_request,
	make_post_request,
	make_delete_request,
	upload_file_to_server,
)

from .status import (
	delete_status_file_on_api,
	ensure_workspace_active,
)

from .util import compute_checksum, validate_snakefile


def init_job(file_path, job_id=None, no_overwrite=False):
	"""
	Submits a new Snakemake job to the API and uploads the Snakefile.
	If job_id is provided, a new Snakefile is added to an existing job/workspace.

	If no_overwrite is True and the target job already contains a file with the same name,
	the operation aborts before uploading.

	Parameters
	----------
	file_path : str
		Path to the local Snakemake file to submit.
	job_id : str, optional
		Existing job ID (workspace) to attach this Snakefile to.
	no_overwrite : bool, optional
		If True, abort if a file with the same name already exists in the job folder.

	Returns
	-------
	None
		Outputs status messages and job information to stdout.
	"""

	# Validate Snakefile before doing anything
	print("Validating snakefile correctness ...")
	if not validate_snakefile(file_path):
		print("Aborting init due to Snakefile validation failure.")
		return

	# Extract just file name in case a full path was provided
	file_name = os.path.basename(file_path)

	reserved = ["status.json", "snakemake.log", "slurm.log"]
	if file_name in reserved:
		print(f"Error: {file_name} is a reserved file name.")
		return

	# If job_id was provided, we add a snakefile to an existing workspace/job
	if job_id is not None:
		# Ensure job exists on API side (and fetch file list for overwrite checks)
		list_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/list_files"
		list_response = make_get_request(list_url)
		if not list_response:
			return

		# If workspace expired -> stop 
		if not ensure_workspace_active(job_id, "init"):
			return

		# If overwrite is disabled, abort when the name already exists
		file_list = list_response.json().get("files", [])
		if no_overwrite and file_name in file_list:
			print(f"Error: File '{file_name}' already exists for Job ID {job_id}.")
			print("Overwrite disabled (--no-overwrite). Choose a different filename or remove --no-overwrite to overwrite existing file.")
			return

		# Upload new Snakefile
		if not upload_file_to_server(job_id, file_path, "init"):
			return

		# Make an init request with the new Snakefile 
		api_url = f"{API_SERVER}/async-function/user/{credentials['username']}/project/{credentials['project']}/functionname/init"
		data = {
			"args": [file_name, str(job_id)],
			"output": "/tmp",
			"input": "/HPCSerA/API-Server/app/jobs/",
			"callback_url": "http://call-home.de"
		}
		response_data = make_post_request(api_url, data)
		if not response_data:
			return

		print(f"Snakefile submitted successfully for existing Job ID: {job_id}")
		print("Note: If a file with the same name already existed, it was overwritten (unless --no-overwrite was used).")
		print("Calling mcse start --jobid will start the latest uploaded Snakefile, you can control which file gets executed by using the --run flag when calling mcse start.")
		print("To find out what Run-IDs exist, call mcse status --jobid after init finishes to view the information.")
		checksum = compute_checksum(file_path)
		if checksum:
			print(f"Checksum of the uploaded Snakefile: {checksum}")

		return

	# Submit the init job (new workspace/job)
	api_url = f"{API_SERVER}/async-function/user/{credentials['username']}/project/{credentials['project']}/functionname/init"
	data = {
		"args": [file_name],
		"output": "/tmp",
		"input": "/HPCSerA/API-Server/app/jobs/",
		"callback_url": "http://call-home.de"
	}
	response_data = make_post_request(api_url, data)
	if not response_data:
		return

	# Extract job id from response and print it
	function_id = str(response_data.get("functionid", "UNKNOWN"))
	print(f"Job submitted successfully! JOB-ID: {function_id}")
	print("Run ID: 1")

	# Upload Snakefile to API-side job folder
	if upload_file_to_server(function_id, file_path, "init"):
		checksum = compute_checksum(file_path)
		if checksum:
			print(f"Checksum of the uploaded Snakefile: {checksum}")




def upload_file(job_id, file_path, no_overwrite=False):
	"""
	Uploads a file to an existing job and triggers an upload task.

	If no_overwrite is True and the target job already contains a file with the same name,
	the operation aborts before uploading.

	Parameters
	----------
	job_id : str
		The job or function ID the file belongs to.
	file_path : str
		Path to the local file to upload.
	no_overwrite : bool, optional
		If True, abort if a file with the same name already exists in the job folder.

	Returns
	-------
	None
		Outputs status messages and submits the upload job.
	"""

	# Extract just file name in case a full path was provided
	file_name = os.path.basename(file_path)

	reserved = ["status.json", "snakemake.log", "slurm.log"]
	if file_name in reserved:
		print(f"Error: {file_name} is a reserved file name.")
		return

	# If overwrite is disabled, check if file already exists in API-side job folder
	list_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/list_files"
	list_response = make_get_request(list_url)
	if not list_response:
		return

	# Before uploading, ensure workspace still exists
	if not ensure_workspace_active(job_id, "upload"):
		return

	file_list = list_response.json().get("files", [])
	if no_overwrite and file_name in file_list:
		print(f"Error: File '{file_name}' already exists for Job ID {job_id}.")
		print("Overwrite disabled (--no-overwrite). Choose a different filename or remove --no-overwrite.")
		return

	if not upload_file_to_server(job_id, file_path, "upload"):
		return

	# Upload file 
	api_url = f"{API_SERVER}/async-function/user/{credentials['username']}/project/{credentials['project']}/functionname/upload"
	data = {
		"args": [file_name, str(job_id)],
		"output": "/tmp",
		"input": "/HPCSerA/API-Server/app/jobs/",
		"callback_url": "http://call-home.de"
	}
	response_data = make_post_request(api_url, data)
	if not response_data:
		return



def start_job(job_id, job_name=None, cpus=None, mem=None, time_limit=None, partition=None, run_id=None):
	"""
	Starts execution of an existing job on the agent.

	Parameters
	----------
	job_id : str
		The job or function ID to start.
	job_name : str, optional
		Optional display name for the job.
	cpus : int, optional
		Number of CPU cores to request.
	mem : str, optional
		Memory requirement (e.g., "8G").
	time_limit : str, optional
		Maximum runtime for the job.
	partition : str, optional
		Cluster partition to run the job on.
	run_id : str, optional
		Optional run ID (for multiple Snakefiles per job).

	Returns
	-------
	None
		Validates the job and submits the start request.
	"""

	# Use the list function to check if job folder exists (i.e. if providded id in args is valid)
	list_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/list_files"
	list_response = make_get_request(list_url)
	if not list_response:
		return

	# Before starting, check if workspace still exists
	if not ensure_workspace_active(job_id, "start"):
		return

	# Submit the start job with job id as an async function
	api_url = f"{API_SERVER}/async-function/user/{credentials['username']}/project/{credentials['project']}/functionname/start"
	data = {
		"args": [
			str(job_id),
			job_name if job_name is not None else "",
			str(cpus) if cpus is not None else "",
			mem if mem is not None else "",
			time_limit if time_limit is not None else "",
			partition if partition is not None else "",
			str(run_id) if run_id is not None else ""
			],
		"output": "/tmp",
		"input": "/tmp",
		"callback_url": "http://call-home.de"
	}
	response_data = make_post_request(api_url, data)
	if not response_data:
		return

	print(f"Starting job with ID: {job_id}")




def check_status(job_id, run_id=None):
	"""
	Triggers a status check for a job, polls for status.json, and prints logs on completion.

	Parameters
	----------
	job_id : str
		The job or function ID to check.
	run_id : str, optional
		Optional run ID (for multiple Snakefiles per job).

	Returns
	-------
	None
		Prints status.json and (if available) the Snakemake log.
	"""

	list_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/list_files"
	poll_interval = 5
	max_retries = 12

	# Delete old status.json (if it exists). Safe: API returns 404 if missing.
	delete_status_file_on_api(job_id)

	# Trigger a status check job
	api_url = f"{API_SERVER}/async-function/user/{credentials['username']}/project/{credentials['project']}/functionname/status"
	data = {
		"args": [str(job_id), str(run_id) if run_id is not None else ""],
		"output": "/tmp",
		"input": "/tmp",
		"callback_url": "http://call-home.de"
	}
	response_data = make_post_request(api_url, data)
	if not response_data:
		return

	print(f"Fetching status for job {job_id}...")

	# ------- POLL FOR STATUS.JSON -------
	status_content = None
	for _ in range(max_retries):
		list_response = make_get_request(list_url)
		if not list_response:
			print("Error: Could not retrieve file list from API server.")
			return

		file_list = list_response.json().get("files", [])
		if "status.json" not in file_list:
			print("status.json not yet available, waiting...")
			time.sleep(poll_interval)
			continue

		get_status_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/get_file/status.json"
		status_response = make_get_request(get_status_url)
		if not status_response:
			print("Failed to fetch status.json from server.")
			return

		print("\n----- status.json -----")
		print(status_response.text)
		print("-----------------------\n")

		status_content = status_response.json()
		break

	if status_content is None:
		print("Could not retrieve status.json after multiple retries.")
		return

	# Determine snakemake log name for the chosen run
	snakemake_log_name = None
	runs_obj = status_content.get("runs", None)

	if isinstance(runs_obj, dict) and runs_obj:
		if run_id is None:
			active_run_id = status_content.get("active_run_id", None)
			if active_run_id is not None:
				run_id = str(active_run_id)
			else:
				try:
					run_id = sorted(runs_obj.keys(), key=lambda x: int(x))[-1]
				except Exception:
					run_id = sorted(runs_obj.keys())[-1]

		run_obj = runs_obj.get(str(run_id), None) or {}
		logs_obj = run_obj.get("logs", {}) or {}
		snakemake_log_name = logs_obj.get("snakemake", None)

	if not snakemake_log_name:
		print("No snakemake log recorded in status.json (logs.snakemake is missing or null).")
		return

	# ------- POLL FOR SNAKEMAKE LOG -------
	for _ in range(max_retries):
		list_response = make_get_request(list_url)
		if not list_response:
			print("Error: Could not retrieve file list from API server.")
			return

		file_list = list_response.json().get("files", [])
		if snakemake_log_name not in file_list:
			print(f"{snakemake_log_name} not yet available, waiting...")
			time.sleep(poll_interval)
			continue

		get_log_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/get_file/{snakemake_log_name}"
		log_response = make_get_request(get_log_url)
		if not log_response:
			print(f"Error fetching {snakemake_log_name}")
			return

		print(f"\n----- {snakemake_log_name} -----")
		print(log_response.text)
		print("-------------------------\n")
		return

	print("Snakemake log was not uploaded yet or could not be retrieved.")



def delete_job(job_id, file_name=None, keep_workspace=False):
	"""
	Deletes a job or a specific file for a job, and triggers the agent-side delete.sh.

	- If file_name is provided:
	  -> only delete that file on the API server (e.g. --filename status.json)
	     and call agent delete.sh with args [job_id, file_name, keep_workspace_flag]
	- If file_name is NOT provided:
	  -> delete the whole job folder on the API server and call agent delete.sh with args
	     [job_id, "", keep_workspace_flag]

	Parameters
	----------
	job_id : str
		The job or function ID to delete.
	file_name : str, optional
		Optional single file to delete inside the API job folder.
	keep_workspace : bool, optional
		If True, prevent the agent from releasing the workspace (ws_release).
	"""

	# Verify the job folder exists first
	list_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/list_files"
	list_response = make_get_request(list_url)
	if not list_response:
		return

	# ---- API-side deletion first ----
	if file_name:
		# delete a single file on API side
		delete_file_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/delete_file/{file_name}"
		delete_resp = make_delete_request(delete_file_url)
		if not delete_resp:
			return
		print(f"Deleted file '{file_name}' from API job folder {job_id} (or it did not exist).")
	else:
		if keep_workspace:
			# Clear API job folder contents but keep the folder (preserve JOB_ID usability)
			file_list = list_response.json().get("files", [])
			for f in file_list:
				delete_file_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/delete_file/{f}"
				delete_resp = make_delete_request(delete_file_url)
				if not delete_resp:
					return
			print(f"Cleared API job folder contents for {job_id} (kept folder because --keep-workspace).")
		else:
			# delete the entire job folder on API side
			delete_job_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/delete_job"
			delete_resp = make_delete_request(delete_job_url)
			if not delete_resp:
				return
			print(f"Deleted API job folder {job_id} (or it did not exist).")

	# Submit a delete job to trigger delete.sh by agent(deletes watch dir used by snakeD, workspace release,etc.)
	# Agent delete behavior is controlled by args:
	#   args[0] = job_id
	#   args[1] = filename ("" means full delete)
	#   args[2] = keep_workspace flag ("1" or "0")
	api_url = f"{API_SERVER}/async-function/user/{credentials['username']}/project/{credentials['project']}/functionname/delete"
	data = {
		"args": [
			str(job_id),
			file_name if file_name is not None else "",
			"1" if keep_workspace else "0"
		],
		"output": "/tmp",
		"input": "/tmp",
		"callback_url": "http://call-home.de"
	}
	response_data = make_post_request(api_url, data)
	if not response_data:
		return

	print(f"Triggered agent delete for job {job_id}.")



def list_files(job_id):
	"""
	Lists all files stored for a specific job.

	Parameters
	----------
	job_id : str
		The job or function ID to query.

	Returns
	-------
	None
		Prints the file names in the job folder.
	"""
	list_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/list_files"
	list_response = make_get_request(list_url)
	if not list_response:
		return

	file_list = list_response.json().get("files", [])
	if file_list:
		print(f"Files for job {job_id}:")
		for file_name in file_list:
			print(file_name)
	else:
		print("Job folder is empty.")
