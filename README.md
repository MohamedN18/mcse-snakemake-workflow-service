# README

## Repository Structure

This repository contains all the files I implemented or modified, which include:

* **HPCSerA**: New routes to delete, upload, download and list files.
* **Agent**:
   - python script `snakeD.py` that manages and executes job related Snakefiles.
   - Shell scripts for the functions and modified version of `agent.py` (see the Agent chapter for details).
* **MCSE-CLI**: Python-based CLI tool implemented as a package (`mcse/`) and split into
  multiple modules (commands, API helpers, status handling, configuration).

---

## Notice

This code was developed and tested **entirely on an HPC cluster using Slurm**.

Because the agent could not reliably reach HPCSerA when running outside the cluster, all components were deployed on the cluster for testing. As a result, the **client (MCSE-CLI)**, **HPCSerA**, and the **agent / snakeD** all run on the cluster in this setup.

This does **not** change the overall design or behavior of the system. In a real deployment, only the agent needs to run on the cluster. A user would simply need to adjust the `api_server` field in `cred.json`, and the same code will work with HPCSerA running externally.

Furthermore, because the **HPCSerA web interface is not accessible from the cluster**, the usual MFA-style confirmation step cannot be performed.
For this reason, **`init` is executed as an async function** in this setup.

Switching back to MFA is trivial and requires only a single change in
`MCSE_CLI/mcse/commands.py` (around line 77):
```
api_url = f"{API_SERVER}/async-function/user/{credentials['username']}/project/{credentials['project']}/functionname/init"
```
change to:

```
api_url = f"{API_SERVER}/mfa-function/user/{credentials['username']}/project/{credentials['project']}/functionname/init"
```
---

## Environment Overview

This setup runs **fully on an HPC cluster** and uses **Slurm** for job execution.

## Python Environments

This repository uses **two separate Python environments**, reflected by two
`requirements.txt` files:

1. **HPCSerA environment**
   - Used for the HPCSerA API server
   - Dependencies listed in:
     ```
     BA_Code/hpcsera/requirements.txt
     ```

2. **Agent / snakeD / MCSE-CLI environment**
   - Used by the agent, `snakeD.py`, and the MCSE CLI
   - Dependencies listed in:
     ```
     BA_Code/agent/requirements.txt
     ```

Both environments were created and tested **directly on the HPC cluster**.

### Cluster Modules

The following cluster module was loaded during development and testing:

```
gcc/14.2.0
```
No additional modules were required.

### Components

- **HPCSerA API Server**
  - Runs on the cluster
  - Provides async-function endpoints and file-management routes
  - Stores job files in a private directory (API-side storage)

- **Agent**
  - Runs on the cluster
  - Executes async functions (`init`, `start`, `upload`, `status`, `delete`)
  - Manages campaign storage (workspace allocation via shell scripts)
  - Maintains the watch directory and uploads job metadata/logs to HPCSerA

- **snakeD**
  - Runs persistently on the agent side
  - Polls the watch directory
  - Detects runs marked as `QUEUED`
  - Starts **Snakemake** with the **Slurm executor plugin**
  - Tracks execution progress and updates `status.json`
  - Records Slurm job IDs submitted **by Snakemake** (one per rule)

- **MCSE-CLI**
  - Used by the user on the cluster
  - Communicates only with HPCSerA

---

## MCSE-CLI
This is a local Python CLI tool implemented as a package (`mcse`).

It can be executed either via:
- `python3 -m mcse`, or
- a shell alias (e.g. `alias mcse="python3 -m mcse"` added to `.bashrc`).

After updating `.bashrc`, run:


```
source ~/.bashrc
```

### Commands

* `mcse init <Snakefile>`
  - Initializes a **new job/workspace** and registers the first run (Run ID = 1).
  - Uploads the Snakefile to the API job folder.
  - Triggers agent `init.sh` which allocates workspace + creates `status.json`.

  **Flags**
  - `--jobid <JOB_ID>`: Attach a new Snakefile as a **new run** to an existing job/workspace.
  - `--no-overwrite`: Abort if a file with the same Snakefile name already exists in the API job folder (useful with `--jobid`).

* `mcse upload --jobid <JOB_ID> <file>`
  - Uploads an additional input file to the API job folder.
  - Triggers agent `upload.sh` to download the file into the workspace **if the workspace is ACTIVE**.
  - Before uploading, the CLI triggers a fresh `status` update and checks `workspace.state` (prevents uploading into an expired workspace).

  **Flags**
  - `--no-overwrite`: Abort if a file with the same name already exists in the API job folder.

* `mcse start --jobid <JOB_ID>`
  - Marks a run as `QUEUED` and writes requested resources into `status.json`.
  - `snakeD` detects `QUEUED` and starts Snakemake using the **Slurm executor plugin**.
  - Before starting, the CLI triggers a fresh `status` update and checks `workspace.state` (prevents starting if workspace expired).

  **Flags**
  - `--run <RUN_ID>`: Start a specific run (otherwise uses `active_run_id`).
  - `--job-name <NAME>`: Slurm job name (recorded in status.json / passed to Snakemake profile).
  - `--cpus <N>`: CPUs per task.
  - `--mem <SIZE>`: Memory (e.g. `2G`, `8000M`).
  - `--time <HH:MM:SS>`: Time limit.
  - `--partition <NAME>`: Partition (e.g. `medium`).

* `mcse status --jobid <JOB_ID>`
  - Deletes old API-side `status.json` first (if it exists).
  - Triggers agent `status.sh` to:
    - update workspace remaining time/state via `ws_list`
    - upload fresh `status.json`
    - upload the current Snakemake log (if available)
  - CLI then polls the API job folder until the new `status.json` appears and prints it.

  **Flags**
  - `--run <RUN_ID>`: Print log for a specific run (otherwise uses `active_run_id` or latest).

* `mcse list --jobid <JOB_ID>`
  - Lists all files stored in the API job folder for that job.

* `mcse delete --jobid <JOB_ID>`
  - Deletes the entire API job folder (Snakefiles, uploads, logs, status.json).
  - Triggers agent `delete.sh` to remove the watch directory and (by default) release the workspace.

  **Flags**
  - `--filename <NAME>`: Delete **only** this file from the API job folder (still triggers agent `delete.sh` for matching cleanup behavior).
  - `--keep-workspace`: Prevent workspace release on agent side (do not call `ws_release`).


### Credentials
For the CLI to work, there must be a `jobs/` folder in the current working directory
(from which `mcse` is executed), containing the file:

```
jobs/cred.json
```
---

## HPCSerA

### File Locations:

* Python backend logic:
  `HPCSerA/API-Server/file_management/`
  **Note**: You need to manually create the `file_management/` directory inside `API-Server/` and place the following two Python files there:
  * `file_routes.py`
  * `__init__.py`

* YAML file:
  `HPCSerA/API-Server/OpenAPI/`
  Just add the `file_management.yml` to the `OpenAPI` folder.

### New Endpoints:

* **Upload File**
  `POST /file-management/user/{user_name}/project/{project_name}/functionid/{function_id}/upload`

* **List Files**
  `GET /file-management/user/{user_name}/project/{project_name}/functionid/{function_id}/list_files`

* **Get File**
  `GET /file-management/user/{user_name}/project/{project_name}/functionid/{function_id}/get_file/{file_name}`

* **Delete File**
  `DELETE /file-management/user/{user_name}/project/{project_name}/functionid/{function_id}/delete_file/{file_name}`

* **Delete Job Folder**
  `DELETE /file-management/user/{user_name}/project/{project_name}/functionid/{function_id}/delete_job`

### Token Permissions:

Two new token scopes were added:

* `post_file` – required for uploads
* `get_file` – required for downloading and listing files
* `delete_file` - required fir deleteing folders/specific files within a folder

When creating a new token, make sure to include these new scopes to be able to use the file management functionality.

For guidance on how to create users, projects, tokens, and the `cred.json` structure, see the README of the HPCSerA Git-repository.

### Example curl Usage:

#### Upload

```
curl -X POST \
  http://<API_SERVER>/file-management/user/<USER>/project/<PROJECT>/functionid/36/upload \
  -H "Authorization: Bearer <TOKEN>" \
  -F "file=@yourfile.txt" \
  -F "job_id=36" \
  -F "function_name=$function_name"
```

#### List

```
curl -X GET \
  http://<API_SERVER>/file-management/user/<USER>/project/<PROJECT>/functionid/36/list_files \
  -H "Authorization: Bearer <TOKEN>"
```

#### Download

To **print** the contents of a file directly in the terminal:

```
curl -X GET \
  http://<API_SERVER>/file-management/user/<USER>/project/<PROJECT>/functionid/36/get_file/yourfile.txt \
  -H "Authorization: Bearer <TOKEN>"
```

To **store** the downloaded file under its original name:

```
curl -X GET \
  http://<API_SERVER>/file-management/user/<USER>/project/<PROJECT>/functionid/36/get_file/yourfile.txt \
  -H "Authorization: Bearer <TOKEN>" \
  -o yourfile.txt
```

#### Delete a single file

```
curl -X DELETE \
  http://<API_SERVER>/file-management/user/<USER>/project/<PROJECT>/functionid/36/delete_file/yourfile.txt \
  -H "Authorization: Bearer <TOKEN>"
```


#### Delete the whole job folder
```
curl -X DELETE \
  http://<API_SERVER>/file-management/user/<USER>/project/<PROJECT>/functionid/36/delete_job \
  -H "Authorization: Bearer <TOKEN>"
```
**Note**: When using the Python-based CLI tool, downloaded files are automatically saved with the correct name. No need to specify `-o`.

---

## Agent

### Code Modifications
- Modiefied `agent.py` to use HTTP instead of HTTPS.

- Two lines in `agent.py` were modified to also pass the job ID (`function_id`) to the shell scripts:

#### Original

```
40: run_args = [home_dir + '/functions/' + job['name'] + '.sh', *job['args']]
60: run_args = [home_dir + '/functions/hash.sh', *job['args']]
```

#### Modified

```
40: run_args = [home_dir + '/functions/' + job['name'] + '.sh', *job['args'], str(job['function_id'])]
60: run_args = [home_dir + '/functions/hash.sh', *job['args'], str(job['function_id'])]
```

This change was required specifically for the **init** job, since the function ID is not known yet on the client side at submission time and cannot be passed via arguments. For all other jobs (`start`, `upload`, `status`, `delete`), the function ID is provided by the user via the CLI.

### Key Responsibilities

- Download input files from HPCSerA
- Allocate **campaign storage/workspace** using `ws_allocate`
- Maintain a **stable watch directory**
- Submit Snakemake workflows as **Slurm batch jobs**
- Collect execution metadata and logs
- Upload results back to HPCSerA
- Delete job-related data and optionally release the workspace (`ws_release`)

---
### Directory Layout (Agent Side)

#### Watch Directory (polled by snakeD)
```
$HOME/BA_Code/Agent/job-watch/<job_id>/status.json
```

This directory **always exists**, even if campaign storage expires.

#### Campaign Storage (execution directory)

Allocated via `ws_allocate` command, example structure:

```
/mnt/ceph-ssd/workspaces/ws/<project>/<workspace_name>/<job_id>/
    Snakefile
    example_input_file.txt
    ...
```
---

### `status.json`

`status.json` is stored in the **watch directory** and uploaded to HPCSerA.

It contains:

* Workspace info (path/name/duration + remaining time updated via `ws_list`)
  - `workspace.remaining_time` is updated by `status.sh`
  - `workspace.state` is set to `ACTIVE` or `EXPIRED` depending on `ws_list`
* Multi-run state under `runs` (each `mcse init --jobid ...` adds a new run)
* Service-level state per run (`PENDING`, `QUEUED`, `RUNNING`, `FINISHED`, `FAILED`)
* Timestamps
* Requested resources
* Slurm metadata per run (Snakemake Slurm executor)
  - `slurm.executor`
  - `slurm.job_ids` (list of sbatch job IDs collected over time)
  - `slurm.jobs_submitted`
  - `slurm.last_update`
* Paths to logs

---

## snakeD
### What `snakeD.py` Does

- Polls the watch directory
- Reads `status.json`
- If a run is `QUEUED`:
  - Starts Snakemake in the workspace using the **slurm executor plugin**
  - Tracks execution progress and updates `runs[run_id]` fields (state/timestamps/log path)
  - Collects submitted Slurm job IDs over time and appends them to:
    - `runs[run_id].slurm.job_ids`
    - increments `runs[run_id].slurm.jobs_submitted`
    - updates `runs[run_id].slurm.last_update`

**Important:** `snakeD` does not submit a single wrapper sbatch job. Snakemake (via the executor plugin) submits sbatch jobs per rule as needed.

**Environment Assumption:**  
`snakeD` starts Snakemake from a preconfigured Python virtual environment.  
Specifically, around line 305, the following environment is activated before invoking Snakemake:

`{HOME}/BA_Code/Agent/agent-env/bin/activate`

This virtual environment must contain all dependencies required for Snakemake execution and the Slurm executor plugin.  
It can be created using the agent-side `requirements.txt`.

If a different environment layout is used, this path must be adjusted accordingly in `snakeD.py`.

---

## Functions Directory

All job logic lives in the `functions/` directory:

* `init.sh`: allocate workspace, download Snakefile, create/extend status.json (adds a new run entry)
* `start.sh`: mark run as QUEUED and set requested resources
* `upload.sh` : download uploaded files from HPCSerA
* `status.sh` : update workspace remaining time (ws_list), upload status.json and snakemake log to HPCSerA
* `delete.sh` : delete watch dir and (optionally) release workspace; also supports deleting a specific file only
* `hash.sh` : (currently unused on cluster, kept for future MFA setup)

**Note**: All scripts must be executable:

```
chmod +x functions/*.sh
```

### Dependencies

The agent and shell scripts use `jq` to read values from local JSON files (`cred.json`, `status.json`).

To install (if not already available):

```
sudo apt install jq
```

For workflow execution, the environment running `snakeD` needs:
- `snakemake`
- `snakemake-executor-plugin-slurm`
- a working Slurm client environment (`sbatch`, `squeue`, etc. available)

### Credentials

The `cred.json` file **must be placed at**:

```
/home/cloud/jobs/cred.json
```

---
## Example Usage / Workflow

This section describes the end-to-end execution flow of a job, from the user’s perspective down to Slurm execution.

The system consists of:
- MCSE-CLI (user-facing)
- HPCSerA (API + file storage)
- Agent (async execution + workspace management)
- snakeD (Snakemake management)
- Slurm (actual job execution)

---

### 1. Start Required Services

On the cluster:

**Start the HPCSerA API server**
    ```
    python3 ~/BA_Code/HPCSerA/API-Server/run.py   
    ```
**Start snakeD on the agent side**
    ```
    python3 ~/BA_Code/Agent/snakeD/snakeD.py 
    ```


---

### 2. Initialize a New Job

The user initializes a job by submitting a Snakefile:
   ```
   mcse init Snakefile
   ```
What happens:

- MCSE-CLI uploads the Snakefile to HPCSerA
- An async `init` function is created on HPCSerA
- The agent executes `init.sh` (agent.py needs to be run manually after each command client uses to execute corresopnding .sh file), run via:
    ```
   python3 ~/BA_Code/Agent/HPCSerA-Agent/agent.py ~/BA_Code/Agent/jobs/cred.json
   ```
- A campaign workspace is allocated using `ws_allocate`
- A stable watch directory is created
- `status.json` is created with:
  - workspace metadata
  - run information (`run_id = 1`)
  - initial state = `PENDING`

Example output:
   ```
   Job submitted successfully! Function ID: 42
   File Upload Successful: {"message": "File Snakefile uploaded for job 42."}
   SHA256: 123abc...
   ```
**Note: if we are working with an mfa function like intended the user would have to accept the job on HPCSerA web-interface.**

---
### 3. Upload Additional Files (Optional)
**Example command**  
   ```
    mcse upload --jobid 42 input.txt
   ```
Behavior:

- MCSE-CLI first triggers a fresh `status` update
- Workspace state is checked
- If the workspace is `ACTIVE`:
  - File is uploaded to HPCSerA
  - Agent downloads it into the workspace
- If the workspace is `EXPIRED`, the command aborts with an error

---

### 4. Start Job Execution
   ```
    mcse start --jobid 42 (optional request slurm resources --job-name ... --time HH:MM:SS so on)
   ```

What happens:

- MCSE-CLI triggers a fresh `status` update
- Workspace state is validated (`ACTIVE`)
- Agent updates `status.json`:
  - run state -> `QUEUED`
  - requested resources are stored
- `snakeD` detects the queued run
- `snakeD` starts **Snakemake with the Slurm executor plugin**
- Snakemake submits **one sbatch job per rule**
- Submitted Slurm job IDs are recorded incrementally in `status.json`

---

### 5. Check Job Status
  ```
  mcse status --jobid 42 
  ```

Behavior:

- Old API-side `status.json` is deleted (if present)
- Agent `status.sh` is triggered
- `status.sh`:
  - calls `ws_list`
  - updates workspace `remaining_time` and `state`
  - uploads a fresh `status.json`
  - uploads the current Snakemake log (if available)
- MCSE-CLI polls until the new `status.json` appears
- Status and logs are printed to the terminal

---

### 6. Multiple Runs per Job
A job can contain **multiple runs**, where each run represents **one execution of a specific Snakefile inside the same workspace**.

A new run is created by attaching an additional Snakefile to an existing job:
  ```
  mcse init --jobid 42 NewSnakefile.smk 
  ```

The new run can then be started explicitly:
  ```
  mcse start --jobid 42 --run 2
  ```
Behavior:

- Each run has its own:
  - Snakefile
  - execution state
  - timestamps
  - Slurm job list (one job ID per rule)
  - Snakemake log
- All runs:
  - share the same workspace
  - can reuse intermediate or input files
---

### 7. Delete Files or Jobs

Delete a single file:
  ```
  mcse delete --jobid 42 --filename input.txt
  ```

Delete the entire job:
  ```
  mcse delete --jobid 42
  ```


Delete job but keep workspace:
  ```
  mcse delete --jobid 42 --keep-workspace
  ```
Behavior:

- API-side files are deleted first
- Agent `delete.sh` is triggered
- Watch directory is cleaned
- Workspace is released unless `--keep-workspace` is set

---

### Example `status.json` (two runs)

```json
{
  "hpcsera_job_id": "42",
  "workspace": {
    "path": "/mnt/ceph-ssd/workspaces/ws/<project>/<user>-mcse_job_42",
    "name": "mcse_job_42",
    "days_allocated": 1,
    "filesystem": "ceph-ssd",
    "remaining_time": "0 days 23 hours",
    "state": "ACTIVE"
  },
  "job_dir": "/mnt/ceph-ssd/workspaces/ws/<project>/<user>-mcse_job_42/42",
  "active_run_id": 2,
  "runs": {
    "1": {
      "snakefile": "Snakefile_run1.smk",
      "state": "FINISHED",
      "timestamps": {
        "created": "2026-01-18T16:51:11",
        "queued": "2026-01-18T16:53:47",
        "started": "2026-01-18T16:53:53",
        "finished": "2026-01-18T16:58:18"
      },
      "snakemake_exit_code": 0,
      "requested_resources": {
        "job_name": "example_job",
        "partition": "medium",
        "time": "01:00:00",
        "mem": "2G",
        "cpus_per_task": 1
      },
      "slurm": {
        "executor": "snakemake-executor-plugin-slurm",
        "job_ids": [12244738, 12244744, 12244753],
        "jobs_submitted": 3,
        "last_update": "2026-01-18T16:58:18"
      },
      "logs": {
        "snakemake": "snakemake_run1.log"
      }
    },
    "2": {
      "snakefile": "Snakefile_run2.smk",
      "state": "FINISHED",
      "timestamps": {
        "created": "2026-01-18T16:59:01",
        "queued": "2026-01-18T16:59:56",
        "started": "2026-01-18T16:59:58",
        "finished": "2026-01-18T17:04:13"
      },
      "snakemake_exit_code": 0,
      "requested_resources": {
        "job_name": "snakemake_job",
        "partition": "medium",
        "time": "01:00:00",
        "mem": "2G",
        "cpus_per_task": 1
      },
      "slurm": {
        "executor": "snakemake-executor-plugin-slurm",
        "job_ids": [12244769, 12244773, 12244780],
        "jobs_submitted": 3,
        "last_update": "2026-01-18T17:04:13"
      },
      "logs": {
        "snakemake": "snakemake_run2.log"
      }
    }
  }
}
```

### Notes

- `status.json` always exists in the watch directory, even if the workspace expires (unless client delets job folder)
- Workspace expiration is detected dynamically via `ws_list`
- Slurm job IDs are tracked **per rule**, not per workflow
- The system supports safe re-runs without re-allocating storage
- `mcse list` and `mcse status` can be called at any point after `init`
---

## TODO

* Re-enable MFA-based `init` once HPCSerA web access is available
* Optional: validate Snakefile syntax during `mcse init`