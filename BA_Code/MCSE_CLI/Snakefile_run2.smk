# ----------------------------------------
# Example Snakemake workflow for MCSE + SLURM plugin
# ----------------------------------------

rule all:
    input:
        "results/summary.txt"


# Rule with SMALL resources
rule generate_numbers:
    output:
        "results/numbers.txt"
    threads: 1
    resources:
        mem_mb=256
    shell:
        """
        mkdir -p results
        seq 1 100000 > {output}
        """


# Rule with BIGGER + DIFFERENT resources
rule square_numbers:
    input:
        "results/numbers.txt"
    output:
        "results/squares.txt"
    threads: 4
    resources:
        mem_mb=2048
    shell:
        """
        awk '{{ print $1*$1 }}' {input} > {output}
        """


# Rule with NO resources defined -> should use your snakeD defaults
rule summarize:
    input:
        "results/squares.txt"
    output:
        "results/summary.txt"
    threads: 1
    shell:
        """
        echo "Lines: $(wc -l < {input})" > {output}
        echo "First: $(head -n 1 {input})" >> {output}
        echo "Last: $(tail -n 1 {input})" >> {output}
        """
