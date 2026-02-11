import os
import shutil
import flask
import app
import Database
from async_function import auth

HOME = os.path.expanduser("~")
UPLOAD_FOLDER = os.path.join(
	HOME,
	"BA_Code",
	"HPCSerA",
	"hpcsera-job-files"
)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def function_owned_by_user_project(function_id: str, token_value: str, project_name: str) -> bool:
	"""
	Checks whether a given function/job ID belongs to the authenticated user
	and the specified project.

	Parameters
	----------
	function_id : str
		The function/job ID whose ownership should be verified.
	token_value : str
		The authentication token extracted from the request's Authorization header.
	project_name : str
		The project name specified in the request URL.

	Returns
	-------
	bool
		True if the function/job ID belongs to the authenticated user and project,
		False otherwise.
	"""

	# Resolve token -> user
	token = Database.tokens.Token.query.filter_by(token_value=str(token_value)).first()
	if token is None:
		return False

	# Resolve project -> must belong to the same user
	project = Database.projects.Project.query.filter_by(
		project_name=project_name,
		user_id=token.user_id
	).first()
	if project is None:
		return False

	# Resolve function/job -> must belong to user and project
	func = Database.functions.Function.query.filter_by(
		id=int(function_id),
		user_id=token.user_id,
		project_id=project.id
	).first()

	return func is not None



def is_safe_filename(file_name: str) -> bool:
	"""
	Basic filename validation to prevent path traversal.

	Why needed:
	-----------
	"file_name" is coming from the URL path. Without checks, a user could pass something
	like "../../somefile" and escape the job directory, potentially reading/deleting
	files outside of the intended job folder.

	Parameters
	----------
	file_name : str
		Filename from the request path.

	Returns
	-------
	bool
		True if the filename looks safe (no slashes, no '..'), otherwise False.
	"""
	if file_name is None:
		return False
	if "/" in file_name or "\\" in file_name:
		return False
	if ".." in file_name:
		return False
	return True


def is_safe_function_id(function_id: str) -> bool:
	"""
	Basic function_id validation to prevent path traversal.

	Why needed:
	-----------
	"function_id" is used to build the job directory path (UPLOAD_FOLDER/<function_id>).
	Without checks, a value like "../../otherdir" could escape UPLOAD_FOLDER and
	cause reads/deletes outside of the intended job folder (especially needed for delete_job).

	Parameters
	----------
	function_id : str
		Function/job id from the request path.

	Returns
	-------
	bool
		True if the function_id looks safe (no slashes, no '..'), otherwise False.
	"""
	if function_id is None:
		return False
	s = str(function_id)
	if "/" in s or "\\" in s:
		return False
	if ".." in s:
		return False
	return True


def is_safe_job_dir(job_dir: str) -> bool:
	"""
	Ensure the computed job_dir stays inside UPLOAD_FOLDER.

	This ensures that symlinks or weird edge cases cannot trick path resolution.

	Parameters
	----------
	job_dir : str
		Full path to the computed job directory.

	Returns
	-------
	bool
		True if job_dir resolves within UPLOAD_FOLDER, otherwise False.
	"""
	try:
		base = os.path.realpath(UPLOAD_FOLDER)
		target = os.path.realpath(job_dir)
		return (target == base) or target.startswith(base + os.sep)
	except Exception:
		return False


def upload_file(user_name: str, project_name: str, function_id: str) -> flask.Response:
	"""
	Handles file upload to a job folder on the API server.

	Parameters
	----------
	user_name : str
		The user uploading the file.
	project_name : str
		The project to which the file belongs.
	function_id : str
		The job/function ID used to identify the folder.

	Returns
	-------
	flask.Response
		JSON response indicating success or failure.
	"""

	token_value = flask.request.headers.get("Authorization", None)[7:] # token_value is a string beginning with 'Bearer', so delete first 7 characters to get token

	if not auth.user_authenticate(token_value, user_name, project_name):
		print('error: invalid project / user rights belonging to token')
		return flask.make_response(flask.jsonify({'error': 'invalid project / user rights belonging to token'}), 403)

	# Prevent path traversal / escaping UPLOAD_FOLDER via function_id
	if not is_safe_function_id(function_id):
		return flask.make_response(flask.jsonify({"error": "Invalid function ID."}), 400)

	if 'file' not in flask.request.files:
		return flask.jsonify({"error": "Missing file"}), 400

	file = flask.request.files['file']
	function_name = flask.request.form['function_name']

	# Save to directory named by function_id
	job_dir = os.path.join(UPLOAD_FOLDER, str(function_id))

	# Ensure job_dir stays inside UPLOAD_FOLDER
	if not is_safe_job_dir(job_dir):
		return flask.make_response(flask.jsonify({"error": "Invalid function ID."}), 400)

	# Ensure function_id belongs to this user/project
	if not function_owned_by_user_project(function_id, token_value, project_name):
		return flask.jsonify({"error": f"Function ID {function_id} not found or not owned by user/project."}), 403

	# Only create a job folder if it is an init job
	if function_name == 'init':
		os.makedirs(job_dir, exist_ok=True)
	else:
		if not os.path.exists(job_dir):
			return flask.jsonify({"error": f"Job folder {function_id} does not exist! Use mcse init to create a job folder."}), 400

	# Prevent user from uploading files with reserved names
	# System uploads (status.sh) can still upload these via system_upload=true
	reserved = ["status.json", "snakemake.log", "slurm.log"]	# may need to adjust later
	system_upload = flask.request.form.get("system_upload", "false").lower() == "true"
	if file.filename in reserved and not system_upload:
		return flask.jsonify({"error": f"{file.filename} is a reserved file name."}), 400

	# Prevent weird filenames on upload too
	if not is_safe_filename(file.filename):
		return flask.jsonify({"error": "Invalid filename."}), 400

	file_path = os.path.join(job_dir, file.filename)
	file.save(file_path)

	return flask.jsonify({"message": f"File {file.filename} uploaded for job {function_id}."}), 200


def list_job_files(user_name: str, project_name: str, function_id: str) -> flask.Response:
	"""
	Lists all files stored in a job folder on the API server.

	Parameters
	----------
	user_name : str
		The user making the request.
	project_name : str
		The project containing the job.
	function_id : str
		The job ID whose files are being queried.

	Returns
	-------
	flask.Response
		JSON with a list of filenames or error message.
	"""

	token_value = flask.request.headers.get("Authorization", None)[7:] # token_value is a string beginning with 'Bearer', so delete first 7 characters to get token

	if not auth.user_authenticate(token_value, user_name, project_name):
		print('error: invalid project / user rights belonging to token')
		return flask.make_response(flask.jsonify({'error': 'invalid project / user rights belonging to token'}), 403)

	# Prevent path traversal / escaping UPLOAD_FOLDER via function_id
	if not is_safe_function_id(function_id):
		return flask.make_response(flask.jsonify({"error": "Invalid function ID."}), 400)

	job_dir = os.path.join(UPLOAD_FOLDER, str(function_id))

	# Ensure job_dir stays inside UPLOAD_FOLDER
	if not is_safe_job_dir(job_dir):
		return flask.make_response(flask.jsonify({"error": "Invalid function ID."}), 400)

	# Ensure function_id belongs to this user/project
	if not function_owned_by_user_project(function_id, token_value, project_name):
		return flask.make_response(flask.jsonify({"error": "Job ID not found"}), 404)

	if not os.path.exists(job_dir):
		return flask.make_response(flask.jsonify({"error": "Job ID not found"}), 404)

	# Get list of filenames
	files = os.listdir(job_dir)
	return flask.jsonify({"job_id": function_id, "files": files})


def get_file(user_name: str, project_name: str, function_id: str, file_name: str) -> flask.Response:
	"""
	Serves a file download from the job folder on the API server.

	Parameters
	----------
	user_name : str
		The user requesting the file.
	project_name : str
		The project associated with the job.
	function_id : str
		The ID of the job folder.
	file_name : str
		The name of the file to download.

	Returns
	-------
	flask.Response
		The requested file as a download, or a 404 error.
	"""

	token_value = flask.request.headers.get("Authorization", None)[7:] # token_value is a string beginning with 'Bearer', so delete first 7 characters to get token

	if not auth.user_authenticate(token_value, user_name, project_name):
		print('error: invalid project / user rights belonging to token')
		return flask.make_response(flask.jsonify({'error': 'invalid project / user rights belonging to token'}), 403)

	# Prevent path traversal / escaping UPLOAD_FOLDER via function_id
	if not is_safe_function_id(function_id):
		return flask.make_response(flask.jsonify({"error": "Invalid function ID."}), 400)

	# Prevent path traversal / escaping job_dir via file_name
	if not is_safe_filename(file_name):
		return flask.make_response(flask.jsonify({"error": "Invalid filename."}), 400)

	job_dir = os.path.join(UPLOAD_FOLDER, str(function_id))

	# Ensure job_dir stays inside UPLOAD_FOLDER
	if not is_safe_job_dir(job_dir):
		return flask.make_response(flask.jsonify({"error": "Invalid function ID."}), 400)

	file_path = os.path.join(job_dir, file_name)

	# Ensure function_id belongs to this user/project
	if not function_owned_by_user_project(function_id, token_value, project_name):
		return flask.make_response(flask.jsonify({"error": "File not found"}), 404)

	if not os.path.exists(file_path):
		return flask.make_response(flask.jsonify({"error": "File not found"}), 404)

	return flask.send_file(file_path, as_attachment=True, download_name=file_name)


def delete_file(user_name: str, project_name: str, function_id: str, file_name: str) -> flask.Response:
	"""
	Deletes a specific file from a job folder on the API server.

	This is useful for workflows where the client wants to remove an old status.json
	before triggering the agent to upload a fresh one, avoiding stale results.

	Parameters
	----------
	user_name : str
		The user requesting the deletion.
	project_name : str
		The project associated with the job.
	function_id : str
		The ID of the job folder.
	file_name : str
		The name of the file to delete (e.g. "status.json").

	Returns
	-------
	flask.Response
		JSON response indicating success or failure.
	"""

	token_value = flask.request.headers.get("Authorization", None)[7:] # token_value is a string beginning with 'Bearer', so delete first 7 characters to get token

	if not auth.user_authenticate(token_value, user_name, project_name):
		print('error: invalid project / user rights belonging to token')
		return flask.make_response(flask.jsonify({'error': 'invalid project / user rights belonging to token'}), 403)

	# Prevent path traversal / escaping UPLOAD_FOLDER via function_id
	if not is_safe_function_id(function_id):
		return flask.make_response(flask.jsonify({"error": "Invalid function ID."}), 400)

	# Prevent path traversal / escaping job_dir via file_name
	if not is_safe_filename(file_name):
		return flask.make_response(flask.jsonify({"error": "Invalid filename."}), 400)

	job_dir = os.path.join(UPLOAD_FOLDER, str(function_id))

	# Ensure job_dir stays inside UPLOAD_FOLDER
	if not is_safe_job_dir(job_dir):
		return flask.make_response(flask.jsonify({"error": "Invalid function ID."}), 400)

	file_path = os.path.join(job_dir, file_name)

	# Ensure function_id belongs to this user/project
	if not function_owned_by_user_project(function_id, token_value, project_name):
		return flask.make_response(flask.jsonify({"error": "File not found"}), 404)

	if not os.path.exists(file_path):
		return flask.make_response(flask.jsonify({"error": "File not found"}), 404)

	try:
		os.remove(file_path)
	except Exception as e:
		return flask.make_response(flask.jsonify({"error": f"Failed to delete file: {e}"}), 500)

	return flask.jsonify({"message": f"File {file_name} deleted for job {function_id}."}), 200


def delete_job(user_name: str, project_name: str, function_id: str) -> flask.Response:
	"""
	Deletes the entire job folder for a function_id on the API server.

	This is meant to be called by the MCSE 'delete' operation, where we want to
	remove all stored job files for this job_id (Snakefiles, logs, status.json, uploads).

	Parameters
	----------
	user_name : str
		The user requesting the deletion.
	project_name : str
		The project associated with the job.
	function_id : str
		The ID of the job folder to delete.

	Returns
	-------
	flask.Response
		JSON response indicating success or failure.
	"""

	token_value = flask.request.headers.get("Authorization", None)[7:] # token_value is a string beginning with 'Bearer', so delete first 7 characters to get token

	if not auth.user_authenticate(token_value, user_name, project_name):
		print('error: invalid project / user rights belonging to token')
		return flask.make_response(flask.jsonify({'error': 'invalid project / user rights belonging to token'}), 403)

	# Prevent path traversal / escaping UPLOAD_FOLDER via function_id
	if not is_safe_function_id(function_id):
		return flask.make_response(flask.jsonify({"error": "Invalid function ID."}), 400)

	job_dir = os.path.join(UPLOAD_FOLDER, str(function_id))

	# Ensure job_dir stays inside UPLOAD_FOLDER
	if not is_safe_job_dir(job_dir):
		return flask.make_response(flask.jsonify({"error": "Invalid function ID."}), 400)

	# Ensure function_id belongs to this user/project
	if not function_owned_by_user_project(function_id, token_value, project_name):
		return flask.make_response(flask.jsonify({"error": "Job ID not found"}), 404)

	if not os.path.exists(job_dir):
		return flask.make_response(flask.jsonify({"error": "Job ID not found"}), 404)

	try:
		shutil.rmtree(job_dir)
	except Exception as e:
		return flask.make_response(flask.jsonify({"error": f"Failed to delete job folder: {e}"}), 500)

	return flask.jsonify({"message": f"Job folder {function_id} deleted."}), 200
