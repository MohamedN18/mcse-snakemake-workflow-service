# mcse/api.py
import requests

from .config import load_credentials, api_server, headers as build_headers

# Load credentials
credentials = load_credentials()
API_SERVER = api_server(credentials)
HEADERS = build_headers(credentials)

def make_post_request(url, data, headers=HEADERS):
	"""
	Sends a POST request to a specified API endpoint with JSON data.

	This function is used to submit jobs or data to the API server and returns
	the parsed JSON response if the request is successful.

	Parameters
	----------
	url : str
		The full API endpoint URL to send the POST request to.
	data : dict
		The JSON-serializable payload to include in the request body.
	headers : dict, optional
		HTTP headers to include in the request. Defaults to HEADERS.

	Returns
	-------
	dict or None
		The JSON response from the API if the request succeeds,
		or None if the request fails.
	"""
	response = requests.post(url, headers=headers, json=data)
	if response.status_code != 200:
		print(f"POST request failed. URL: {url}, Status: {response.status_code}, Response: {response.text}")
		return None
	return response.json()


def make_get_request(url, headers=HEADERS):
	"""
	Sends a GET request to the given API endpoint.

	Parameters
	----------
	url : str
		The API endpoint to request.
	headers : dict, optional
		HTTP headers to include.

	Returns
	-------
	requests.Response or None
		The response object if successful, otherwise None.
	"""
	response = requests.get(url, headers=headers)
	if response.status_code != 200:
		print(f"GET request failed. URL: {url}, Status: {response.status_code}, Response: {response.text}")
		return None
	return response


def make_delete_request(url, headers=HEADERS):
	"""
	Sends a DELETE request to the given API endpoint.

	Parameters
	----------
	url : str
		The API endpoint to request.
	headers : dict, optional
		HTTP headers to include.

	Returns
	-------
	requests.Response or None
		The response object if successful, otherwise None.
	"""
	response = requests.delete(url, headers=headers)
	# Note: for delete we tolerate 404 as "already deleted / not present"
	if response.status_code not in (200, 404):
		print(f"DELETE request failed. URL: {url}, Status: {response.status_code}, Response: {response.text}")
		return None
	return response


def upload_file_to_server(job_id, file_path, function_name):
	"""
	Uploads a local file to the API server for a specific job.

	Parameters
	----------
	job_id : str
		The job or function ID used to determine the upload folder.
	file_path : str
		Path to the local file to upload.
	function_name : str
		The name of the function the file belongs to.

	Returns
	-------
	bool
		True if the upload succeeds, otherwise False.
	"""
	upload_url = f"{API_SERVER}/file-management/user/{credentials['username']}/project/{credentials['project']}/functionid/{job_id}/upload"
	with open(file_path, 'rb') as f:
		files = {'file': f}
		data = {'function_name': function_name}
		response = requests.post(upload_url, files=files, data=data, headers={"Authorization": f"Bearer {credentials['token']}"})
	if response.status_code == 200:
		print(f"File Upload Successful: {response.text}")
		return True
	else:
		print(f"File Upload Failed: {response.text}")
		return False