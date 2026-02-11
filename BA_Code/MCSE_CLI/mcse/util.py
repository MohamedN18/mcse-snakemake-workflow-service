# mcse/util.py
import hashlib
import subprocess

# Compute checksum of the submitted snakefile (used when working with mfa functions and comparing checksums on API's web-interface)
def compute_checksum(file_path):
	"""
	Computes the SHA-256 checksum of a file.

	Parameters
	----------
	file_path : str
		Path to the file to hash.

	Returns
	-------
	str or None
		The hexadecimal checksum string, or None on failure.
	"""
	try:
		with open(file_path, "rb") as f:
			data = f.read()
		checksum = hashlib.sha256(data).hexdigest()
		return checksum
	except Exception as e:
		print(f"Error computing checksum: {e}")
		return None


def validate_snakefile(snakefile_path):
	"""
	Validate a Snakefile for syntax and DAG correctness using Snakemake.

	Performs two checks:
	1) Lint check (--lint) for basic Snakefile syntax issues (warnings printed, never aborts).
	2) Dry-run check (--dry-run) to ensure DAG logic is valid (missing inputs, cycles, etc.).

	Returns True if dry-run succeeds, False otherwise.
	"""

	print("Running Snakefile lint (warnings only, do not abort)...")
	lint_proc = subprocess.run(
		["snakemake", "--snakefile", snakefile_path, "--lint"],
		capture_output=True,
		text=True
	)
	if lint_proc.stdout.strip() or lint_proc.stderr.strip():
		print("Snakefile lint output (warnings may appear):\n", lint_proc.stdout, lint_proc.stderr)

	print("Running Snakefile dry-run...")
	dryrun_proc = subprocess.run(
		["snakemake", "--snakefile", snakefile_path, "--dry-run", "--cores", "1"],
		capture_output=True,
		text=True
	)
	if dryrun_proc.returncode != 0:
		print("Snakefile dry-run DAG check failed:\n", dryrun_proc.stdout, dryrun_proc.stderr)
		return False

	print("Snakefile validation passed.")
	return True



