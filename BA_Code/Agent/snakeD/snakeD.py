#!/usr/bin/env python3
import os
import json
import subprocess
import time
import re
from datetime import datetime

HOME = os.path.expanduser("~")
WATCH_BASE_DIR = os.path.join(HOME, "BA_Code", "Agent", "job-watch")
CHECK_INTERVAL = 10

# How often to refresh slurm job_ids from the Snakemake log while RUNNING
SLURM_ID_POLL_INTERVAL = 5

def now_ts():
	"""
	Returns a timestamp string in ISO-like format used across status.json.

	Returns
	-------
	str
		Timestamp formatted as YYYY-MM-DDTHH:MM:SS.
	"""
	return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

def atomic_write_json(path, obj):
	"""
	Writes JSON atomically to avoid partially-written status.json files.

	This is important because snakeD polls repeatedly and other processes
	may read status.json while it is being updated.

	Parameters
	----------
	path : str
		Path to the JSON file to write.
	obj : dict
		JSON-serializable object to write.

	Returns
	-------
	None
	"""
	tmp_path = path + ".tmp"
	with open(tmp_path, "w") as f:
		json.dump(obj, f, indent=2)
	os.replace(tmp_path, path)

def parse_time_to_minutes(time_str):
	"""
	Converts a time string in HH:MM:SS to minutes (rounded up).

	The SLURM executor plugin commonly expects runtime as a numeric value
	(e.g. minutes) in default-resources. If parsing fails, returns 60.

	Parameters
	----------
	time_str : str
		Time string formatted as HH:MM:SS.

	Returns
	-------
	int
		Runtime in minutes (minimum 1).
	"""
	try:
		parts = (time_str or "").strip().split(":")
		if len(parts) != 3:
			return 60
		h = int(parts[0])
		m = int(parts[1])
		s = int(parts[2])
		total = h * 60 + m
		if s > 0:
			total += 1
		if total < 1:
			total = 1
		return total
	except Exception:
		return 60

def parse_mem_to_mb(mem_str):
	"""
	Converts a memory string (e.g. "2G", "8000M") to MB.

	If parsing fails, returns None.

	Parameters
	----------
	mem_str : str
		Memory string, typically with suffix G or M.

	Returns
	-------
	int or None
		Memory in MB, or None if parsing fails.
	"""
	try:
		s = (mem_str or "").strip().upper()
		if not s:
			return None
		if s.endswith("G"):
			return int(float(s[:-1]) * 1024)
		if s.endswith("M"):
			return int(float(s[:-1]))
		return int(float(s))
	except Exception:
		return None

def pick_queued_run(status):
	"""
	Picks the next queued run for a multi-run job.

	Priority:
		1) If active_run_id exists AND that run is QUEUED -> pick it first.
		2) Otherwise pick the lowest run_id with state == "QUEUED".

	Parameters
	----------
	status : dict
		Parsed status.json content.

	Returns
	-------
	str or None
		Run ID to execute, or None if no queued run exists.
	"""
	runs = status.get("runs")
	if not isinstance(runs, dict) or not runs:
		return None

	queued = []
	for rid, robj in runs.items():
		try:
			state = (robj or {}).get("state", "")
			if state == "QUEUED":
				queued.append(rid)
		except Exception:
			continue

	if not queued:
		return None

	# Prefer active_run_id if it's queued
	active = status.get("active_run_id", None)
	if active is not None:
		active_str = str(active)
		if active_str in queued:
			return active_str

	# Otherwise choose the lowest queued id
	try:
		return sorted(queued, key=lambda x: int(x))[0]
	except Exception:
		return sorted(queued)[0]


def ensure_profile(job_dir, run_id, resources):
	"""
	Creates a per-run Snakemake profile folder inside the job directory.

	The profile is used to pass executor/plugin settings and default resources
	to Snakemake (SLURM executor plugin), based on status.json requested_resources.

	Parameters
	----------
	job_dir : str
		Path to the execution directory (workspace job_dir).
	run_id : str
		Run ID used to name the profile directory.
	resources : dict
		requested_resources from status.json for this run.

	Returns
	-------
	str
		Path to the created profile directory.
	"""
	profile_dir = os.path.join(job_dir, f".mcse_profile_run{run_id}")
	os.makedirs(profile_dir, exist_ok=True)
	cfg_path = os.path.join(profile_dir, "config.yaml")

	job_name = (resources or {}).get("job_name") or "snakemake_job"
	partition = (resources or {}).get("partition") or "medium"
	time_limit = (resources or {}).get("time") or "01:00:00"
	cpus = (resources or {}).get("cpus_per_task") or 1
	mem = (resources or {}).get("mem") or "2G"

	runtime_min = parse_time_to_minutes(time_limit)
	total_mem_mb = parse_mem_to_mb(mem)

	# Convert "total mem" to "mem per cpu" if possible (common pattern for cluster executors).
	mem_mb_per_cpu = None
	try:
		cpu_i = int(cpus)
		if cpu_i < 1:
			cpu_i = 1
		if total_mem_mb is not None:
			mem_mb_per_cpu = max(1, int(total_mem_mb / cpu_i))
	except Exception:
		mem_mb_per_cpu = None

	lines = []
	lines.append("executor: slurm")
	lines.append("jobs: 50")
	lines.append("default-resources:")
	lines.append(f"  slurm_partition: \"{partition}\"")
	lines.append(f"  runtime: {runtime_min}")
	lines.append(f"  cpus_per_task: {int(cpus) if str(cpus).isdigit() else 1}")
	if mem_mb_per_cpu is not None:
		lines.append(f"  mem_mb_per_cpu: {mem_mb_per_cpu}")

	# job_name is kept in status.json; some setups support job name via resources/profiles,
	# but it depends on executor/plugin behavior

	with open(cfg_path, "w") as f:
		f.write("\n".join(lines) + "\n")

	return profile_dir

def extract_slurm_job_ids_from_log(log_path):
	"""
	Extracts SLURM job IDs from a Snakemake run log, need ids to be stored in status.json.

	The slurm executor plugin commonly prints lines like:
	  "Job 3 has been submitted with SLURM jobid 12237391 (...)."

	We also keep a fallback for classic sbatch output like:
	  "Submitted batch job 12237391"

	Parameters
	----------
	log_path : str
		Path to the Snakemake log file (e.g. snakemake_run1.log).

	Returns
	-------
	list[int]
		Unique SLURM job IDs found in the log (sorted).
	"""
	if not os.path.exists(log_path):
		return []

	job_ids = set()

	# Plugin format (what you showed)
	pat_plugin = re.compile(r"\bSLURM\s+jobid\s+(\d+)\b", re.IGNORECASE)

	# Classic sbatch format (fallback)
	pat_sbatch = re.compile(r"\bSubmitted\s+batch\s+job\s+(\d+)\b", re.IGNORECASE)

	try:
		with open(log_path, "r", errors="replace") as f:
			for line in f:
				m = pat_plugin.search(line)
				if m:
					try:
						job_ids.add(int(m.group(1)))
						continue
					except Exception:
						pass

				m = pat_sbatch.search(line)
				if m:
					try:
						job_ids.add(int(m.group(1)))
					except Exception:
						pass
	except Exception:
		return []

	return sorted(job_ids)


def start_snakemake_with_plugin(job_dir, snakefile_name, profile_dir, log_path):
	"""
	Starts Snakemake process and uses the SLURM executor plugin.

	Snakemake will submit one SLURM job per rule (as needed), and will monitor
	the workflow until completion.

	We run Snakemake inside "bash -c" so we can activate the venv.

	Parameters
	----------
	job_dir : str
		Execution directory where Snakemake should run.
	snakefile_name : str
		Snakefile filename stored inside job_dir.
	profile_dir : str
		Path to the Snakemake profile directory.
	log_path : str
		Path to the log file where stdout/stderr will be appended.

	Returns
	-------
	subprocess.Popen
		Running Snakemake process handle.
	"""
	snakefile_path = os.path.join(job_dir, snakefile_name)

	cmd = f"""
set -e
source "{HOME}/BA_Code/Agent/agent-env/bin/activate"
snakemake --directory "{job_dir}" --snakefile "{snakefile_path}" --profile "{profile_dir}" \
	--rerun-incomplete --retries 3
"""

	# Append stdout/stderr to the run log
	logf = open(log_path, "a")
	proc = subprocess.Popen(["bash", "-c", cmd], stdout=logf, stderr=logf)
	# Attach log file handle so we can close it later
	proc._mcse_logf = logf
	return proc

def handle_job(job_id, watch_dir):
	"""
	Checks a job's status.json and starts the next queued run (if any).

	This updates status.json to RUNNING, starts Snakemake with the SLURM executor plugin,
	periodically updates SLURM job_ids while running, and then finalizes status.json.

	Parameters
	----------
	job_id : str
		HPCSerA job ID.
	watch_dir : str
		Path to the job-watch directory for this job.

	Returns
	-------
	bool
		True if a run was executed, False otherwise.
	"""
	status_file = os.path.join(watch_dir, "status.json")
	if not os.path.exists(status_file):
		return False

	with open(status_file) as f:
		status = json.load(f)

	job_dir = status.get("job_dir")
	if not job_dir:
		print(f"[ERROR] job_dir missing in status.json for job {job_id}")
		return False
	if not os.path.isdir(job_dir):
		print(f"[ERROR] job_dir does not exist for job {job_id}: {job_dir}")
		return False

	run_id = pick_queued_run(status)
	if run_id is None:
		return False

	run_obj = status.get("runs", {}).get(str(run_id), {}) or {}
	snakefile_name = run_obj.get("snakefile", None)
	if not snakefile_name:
		print(f"[ERROR] snakefile missing for job {job_id} run {run_id}")
		return False

	snakefile_path = os.path.join(job_dir, snakefile_name)
	if not os.path.isfile(snakefile_path):
		print(f"[ERROR] snakefile not found for job {job_id} run {run_id}: {snakefile_path}")
		return False

	log_name = f"snakemake_run{run_id}.log"
	log_path = os.path.join(job_dir, log_name)

	# Mark RUNNING before starting Snakemake to avoid duplicate start in the next poll cycle
	status["active_run_id"] = int(run_id)
	status.setdefault("runs", {})
	status["runs"].setdefault(str(run_id), {})
	status["runs"][str(run_id)]["state"] = "RUNNING"
	status["runs"][str(run_id)].setdefault("timestamps", {})
	status["runs"][str(run_id)]["timestamps"]["started"] = now_ts()
	status["runs"][str(run_id)].setdefault("logs", {})
	status["runs"][str(run_id)]["logs"]["snakemake"] = log_name

	# Each rule has its own SLURM ID
	status["runs"][str(run_id)]["slurm"] = {
		"executor": "snakemake-executor-plugin-slurm",
		"job_ids": [],
		"jobs_submitted": 0,
		"last_update": None
	}

	atomic_write_json(status_file, status)

	resources = status["runs"][str(run_id)].get("requested_resources", {}) or {}
	profile_dir = ensure_profile(job_dir, run_id, resources)

	print(f"[INFO] Starting Snakemake for job {job_id} run {run_id} using slurm executor plugin")

	# Start Snakemake
	proc = start_snakemake_with_plugin(job_dir, snakefile_name, profile_dir, log_path)

	# While running: periodically parse the run log for "Submitted batch job <id>" and update status.json
	last_ids = set()
	while True:
		rc = proc.poll()
		job_ids = extract_slurm_job_ids_from_log(log_path)
		job_ids_set = set(job_ids)

		# Only write status.json if something changed
		if job_ids_set != last_ids:
			last_ids = job_ids_set

			with open(status_file) as f:
				status = json.load(f)

			status.setdefault("runs", {})
			status["runs"].setdefault(str(run_id), {})
			status["runs"][str(run_id)].setdefault("slurm", {})

			status["runs"][str(run_id)]["slurm"]["executor"] = "snakemake-executor-plugin-slurm"
			status["runs"][str(run_id)]["slurm"]["job_ids"] = sorted(job_ids_set)
			status["runs"][str(run_id)]["slurm"]["jobs_submitted"] = len(job_ids_set)
			status["runs"][str(run_id)]["slurm"]["last_update"] = now_ts()

			atomic_write_json(status_file, status)

		# If finished, break; otherwise sleep and continue
		if rc is not None:
			exit_code = rc
			break
		time.sleep(SLURM_ID_POLL_INTERVAL)

	# Close log file handle
	try:
		proc._mcse_logf.close()
	except Exception:
		pass

	# Reload status.json (in case other processes updated it while Snakemake was running)
	with open(status_file) as f:
		status = json.load(f)

	final_state = "FINISHED" if exit_code == 0 else "FAILED"
	status["runs"][str(run_id)]["state"] = final_state
	status["runs"][str(run_id)].setdefault("timestamps", {})
	status["runs"][str(run_id)]["timestamps"]["finished"] = now_ts()
	status["runs"][str(run_id)]["snakemake_exit_code"] = exit_code

	# Ensure slurm ids are up to date at end
	job_ids = extract_slurm_job_ids_from_log(log_path)
	status["runs"][str(run_id)].setdefault("slurm", {})
	status["runs"][str(run_id)]["slurm"]["executor"] = "snakemake-executor-plugin-slurm"
	status["runs"][str(run_id)]["slurm"]["job_ids"] = job_ids
	status["runs"][str(run_id)]["slurm"]["jobs_submitted"] = len(job_ids)
	status["runs"][str(run_id)]["slurm"]["last_update"] = now_ts()

	atomic_write_json(status_file, status)

	print(f"[INFO] Job {job_id} run {run_id} finished with exit code {exit_code}")
	return True

def main_loop():
	"""
	Main loop of snakeD.

	Polls the job-watch directory and processes jobs that have queued runs.
	"""
	print("[INFO] SnakeD started, polling for jobs...")
	os.makedirs(WATCH_BASE_DIR, exist_ok=True)

	while True:
		for job_id in os.listdir(WATCH_BASE_DIR):
			watch_dir = os.path.join(WATCH_BASE_DIR, job_id)
			if os.path.isdir(watch_dir):
				handle_job(job_id, watch_dir)
		time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
	main_loop()
