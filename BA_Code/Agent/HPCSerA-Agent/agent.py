import requests
import json
import sys
import os
import subprocess

class Credentials:
    username: str
    token: str
    project: str
    api_server: str

    def __init__(self, config_file_path):
        with open(config_file_path, 'r') as f:
            config = json.load(f)

        self.username = config['username']
        self.token = config['token']
        self. project = config['project']
        self.api_server = config["api_server"]

def look_for_new_job(credentials):
    new_job = requests.get('http://' + credentials.api_server + '/agent/username/' + credentials.username + '/projectname/' + credentials.project,
                           headers={"Authorization":"Bearer "+credentials.token})
    return new_job.json()

def update_job_status(credentials, new_status,functionid):
    print(f"update job status: {new_status}")
    response = requests.put('http://' + credentials.api_server + '/async-function/user/' + credentials.username + '/project/' + credentials.project + '/functionid/' + str(functionid) , 
                            headers={"Authorization":"Bearer "+credentials.token},
                            json={"state":new_status})
    print(response)
    print(response.text)

def execute_function(job):
    home_dir = os.getenv('HOME')
    if not home_dir:
        print('$HOME environment variable must be set', file=sys.stderr)
        exit()
    ########### added function_id to line below, otherwise init.sh has no access to the id
    run_args = [home_dir + '/functions/' + job['name'] + '.sh', *job['args'], str(job['function_id'])]
    print(run_args)
    return subprocess.run(run_args, shell=False, capture_output=True)
    
def update_slurm_id_running(credentials, slurm_id, function_id,state):
    response = requests.put('http://' + credentials.api_server + '/async-function/user/' + credentials.username + '/project/' + credentials.project + '/functionid/' + str(function_id) , 
                            headers={"Authorization":"Bearer "+credentials.token},
                            json={"state":state,"slurm_id":slurm_id})
    print(response)

def get_job_for_checksum_update(credentials):
    new_job = requests.get('http://' + credentials.api_server + '/mfa-checksum/user/' + credentials.username + '/project/' + credentials.project,
                           headers={"Authorization":"Bearer "+credentials.token})
    return new_job.json()

def calculate_checksum(job):
    home_dir = os.getenv('HOME')
    if not home_dir:
        print('$HOME environment variable must be set', file=sys.stderr)
        exit()
    run_args = [home_dir + '/functions/hash.sh', *job['args'], str(job['function_id'])]
    print(run_args)
    job = subprocess.run(run_args, shell=False, capture_output=True, text=True)
    checksum = job.stdout.strip()
    return checksum

def update_checksum(credentials, function_id, checksum):
    response = requests.put('http://' + credentials.api_server + '/mfa-checksum/user/' +credentials.username + '/project/' + credentials.project + '/functionid/' + str(function_id), headers={"Authorization":"Bearer "+credentials.token}, json={"checksum":checksum})
    print(response.url)
    print(response)
    print(response.text)
    
def run_post_slurm_command(function_id):
    post_command = os.path.join(os.getenv('HOME'), '.viking', 'post_slurm.sh')
    if os.path.exists(post_command):
        subprocess.run([post_command, str(function_id)], shell=False)

def control_slurm_job_state(credentials, slurm_id, function_id):
    ret = subprocess.run(['sacct','--jobs=' + str(slurm_id), '--format=State', '--parsable2'], shell=False, capture_output=True)
    ret = ret.stdout.decode()
    ret = ret.replace("\n","")
    ret = ret.replace("State","")
    if 'PENDING' in ret or 'RUNNING' in ret:
        print(f"job with slurm id {slurm_id} is still running")
        return
    run_post_slurm_command(function_id)
    if 'CANCELLED' in ret:
        update_slurm_id_running(credentials, slurm_id, function_id,'CANCELLED')
    if 'FAILED' in ret:
        update_slurm_id_running(credentials, slurm_id, function_id,'FAILED')
    ret = ret.replace("COMPLETED","")
    if len(ret) == 0:
        update_slurm_id_running(credentials, slurm_id, function_id,'COMPLETED')
    else:
        update_slurm_id_running(credentials, slurm_id, function_id,'ProbFAILED')
    print(f"updated state of job with slurm id {slurm_id}")

def main_loop():
    credentials = Credentials(sys.argv[1])

    # draft of checksum workflow
    job = get_job_for_checksum_update(credentials)
    if ('Bad_request' not in job.keys()):
        checksum = calculate_checksum(job)
        print("update checksum")
        update_checksum(credentials, job['function_id'], checksum)
    else:
        print("No checksums to be updated.")


    job = look_for_new_job(credentials)
    if "Bad_request" in job:
        print("No job to be run.")
        return
    if 'type' in job:
        print('Something went wrong, please ask an admin', file=sys.stderr)
        exit()
    if job['slurm_id'] is not None:
        print(f'control slurm state of job {job["slurm_id"]}')
        control_slurm_job_state(credentials,job['slurm_id'],job['function_id'])
        exit()

    result = execute_function(job)
    print(result)
    print(result.stdout.decode().rstrip("\n"))

    isBatchJob = result.stdout is not None and (result.stdout.decode().rstrip("\n").isnumeric() or result.stdout.decode().startswith('Submitted batch job'))

    if isBatchJob:
        if result.stdout.decode().startswith('Submitted batch job'):
            slurm_id = result.stdout.decode().rstrip("\n")[20:]
        else:
            slurm_id = result.stdout.decode().rstrip("\n")

        # Assume this is a Slurm JobID
        print(f"Slurm id: {slurm_id}")
        update_slurm_id_running(credentials, int(slurm_id), job['function_id'],"BatchJobRunning")
        exit()
    update_job_status(credentials,"FINISHED",job['function_id'])

main_loop()
