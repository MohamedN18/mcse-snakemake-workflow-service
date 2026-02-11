# mcse/__main__.py
import argparse

from .commands import (
    init_job,
    upload_file,
    start_job,
    check_status,
    list_files,
    delete_job,
)


def main():
	parser = argparse.ArgumentParser(description="MCSE CLI Tool for HPCSerA")
	subparsers = parser.add_subparsers(dest="command", required=True)

	parser_init = subparsers.add_parser("init", help="Initialize a new Snakemake job")
	parser_init.add_argument("--jobid", required=False, default=None, help="Existing Job ID (attach Snakefile to existing workspace)")
	parser_init.add_argument("--no-overwrite", action="store_true", help="Abort if a file with the same name already exists in the job folder (useful with --jobid).")
	parser_init.add_argument("file_path", help="Path to the Snakemake file")

	parser_upload = subparsers.add_parser("upload", help="Upload a file for an existing job")
	parser_upload.add_argument("--jobid", required=True, help="Job ID")
	parser_upload.add_argument("--no-overwrite", action="store_true", help="Abort if a file with the same name already exists in the job folder.")
	parser_upload.add_argument("file_path", help="Path to the file to upload")

	parser_start = subparsers.add_parser("start", help="Start execution of a job")
	parser_start.add_argument("--jobid", required=True, help="Job ID")
	parser_start.add_argument("--job-name", dest="job_name", default=None, help="Slurm job name")
	parser_start.add_argument("--cpus", type=int, default=None, help="CPUs per task")
	parser_start.add_argument("--mem", default=None, help="Memory (e.g. 2G, 8000M)")
	parser_start.add_argument("--time", dest="time_limit", default=None, help="Time limit (HH:MM:SS)")
	parser_start.add_argument("--partition", default=None, help="Slurm partition (e.g. medium)")
	parser_start.add_argument("--run", required=False, default=None, help="Run ID (optional)")

	parser_status = subparsers.add_parser("status", help="Check the status of a job")
	parser_status.add_argument("--jobid", required=True, help="Job ID")
	parser_status.add_argument("--run", required=False, default=None, help="Run ID (optional)")

	parser_list = subparsers.add_parser("list", help="List files within a job folder")
	parser_list.add_argument("--jobid", required=True, help="Job ID")

	parser_delete = subparsers.add_parser("delete", help="Delete a job folder or a specific file for a job")
	parser_delete.add_argument("--jobid", required=True, help="Job ID")
	parser_delete.add_argument("--filename", required=False, default=None, help="Optional: delete only this file (otherwise delete whole job folder)")
	parser_delete.add_argument("--keep-workspace", action="store_true", help="Prevent workspace release on agent side (do not call ws_release)")

	args = parser.parse_args()

	if args.command == "init":
		init_job(args.file_path, args.jobid, args.no_overwrite)
	elif args.command == "upload":
		upload_file(args.jobid, args.file_path, args.no_overwrite)
	elif args.command == "start":
		start_job(args.jobid, args.job_name, args.cpus, args.mem, args.time_limit, args.partition, args.run)
	elif args.command == "status":
		check_status(args.jobid, args.run)
	elif args.command == "list":
		list_files(args.jobid)
	elif args.command == "delete":
		delete_job(args.jobid, args.filename, args.keep_workspace)
	else:
		parser.print_help()

if __name__ == "__main__":
	main()
