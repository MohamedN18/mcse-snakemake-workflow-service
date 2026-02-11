# mcse/config.py
import json
import os

def load_credentials() -> dict:
	# Read cred.json 
	BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	cred_path = os.path.join(BASE_DIR, "jobs", "cred.json")
	with open(cred_path) as f:
		return json.load(f)

def api_server(credentials: dict) -> str:
	return f"http://{credentials['api_server']}"

def headers(credentials: dict) -> dict:
	return {
		"Authorization": f"Bearer {credentials['token']}",
		"Content-Type": "application/json",
	}
