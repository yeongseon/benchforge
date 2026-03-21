from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

import benchflow.workers.python.psycopg_worker  # noqa: F401, E402  # pyright: ignore[reportUnusedImport]
import benchflow.workers.python.sqlalchemy_worker  # noqa: F401, E402  # pyright: ignore[reportUnusedImport]

# Optional workers — loaded when their driver packages are installed
try:
    import benchflow.workers.python.pycubrid_worker  # noqa: F401, E402  # pyright: ignore[reportUnusedImport]
except ImportError:
    pass

try:
    import benchflow.workers.python.pymysql_worker  # noqa: F401, E402  # pyright: ignore[reportUnusedImport]
except ImportError:
    pass
from benchflow.core.result import CompareResult, ComparisonItem, RunResult

app = typer.Typer(
    name="bench",
    help="BenchFlow \u2014 Scenario-based polyglot database benchmark platform",
    no_args_is_help=True,
)
console = Console()


@app.command()
def run(
    scenario_path: Annotated[str, typer.Argument(help="Path to scenario YAML file")],
    output: Annotated[str, typer.Option("--output", "-o", help="Output JSON path")] = "",
    iterations: Annotated[
        int,
        typer.Option(
            "--iterations",
            "-n",
            help="Number of experiment iterations (overrides scenario)",
        ),
    ] = 0,
    seed: Annotated[
        int | None,
        typer.Option(
            "--seed",
            help="Random seed for reproducibility (overrides scenario)",
        ),
    ] = None,
    capture_db_info: Annotated[
        bool,
        typer.Option(
            "--capture-db-info",
            help="Capture DB server config via introspect()",
        ),
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run a benchmark scenario against all defined targets."""
    if verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from benchflow.core.runner.runner import run_benchmark
    from benchflow.core.scenario.loader import load_scenario

    scenario = load_scenario(scenario_path)

    if not scenario.targets:
        console.print("[red]Error:[/red] No targets defined in scenario file.")
        console.print("Add a 'targets' section to your scenario YAML.")
        raise typer.Exit(1)

    n_iter = iterations if iterations > 0 else None
    effective_iterations = n_iter or scenario.experiment.iterations

    console.print(f"[bold]Running scenario:[/bold] {scenario.name}")
    console.print(
        f"  concurrency={scenario.load.concurrency}, "
        f"duration={scenario.load.duration}s, "
        f"warmup={scenario.load.warmup.duration}s"
    )
    if effective_iterations > 1:
        console.print(
            f"  iterations={effective_iterations}, seed={seed or scenario.experiment.seed}"
        )
    console.print(f"  targets: {[t.stack_id for t in scenario.targets]}")
    console.print()

    result = run_benchmark(
        scenario,
        iterations_override=n_iter,
        seed_override=seed,
        capture_db_info=capture_db_info,
    )

    if not output:
        output = f"reports/{result.run_id}.json"

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    result.save(output)

    _print_summary(result)
    console.print(f"\n[green]Results saved to:[/green] {output}")


@app.command()
def compare(
    baseline_path: Annotated[str, typer.Argument(help="Path to baseline result JSON")],
    contender_path: Annotated[str, typer.Argument(help="Path to contender result JSON")],
    output: Annotated[str, typer.Option("--output", "-o", help="Output comparison JSON")] = "",
) -> None:
    """Compare two benchmark results."""
    baseline = RunResult.load(baseline_path)
    contender = RunResult.load(contender_path)

    scenario_match = baseline.scenario.signature == contender.scenario.signature
    if not scenario_match:
        console.print(
            "[yellow]Warning:[/yellow] Scenario signatures differ. "
            "Results may not be directly comparable."
        )

    comparisons: list[ComparisonItem] = []

    baseline_targets = {t.stack_id: t for t in baseline.targets}
    contender_targets = {t.stack_id: t for t in contender.targets}

    common_stacks = set(baseline_targets.keys()) & set(contender_targets.keys())

    for stack_id in sorted(common_stacks):
        bt = baseline_targets[stack_id]
        ct = contender_targets[stack_id]

        baseline_steps = {s.name: s for s in bt.steps}
        contender_steps = {s.name: s for s in ct.steps}

        common_steps = set(baseline_steps.keys()) & set(contender_steps.keys())

        for step_name in sorted(common_steps):
            bs = baseline_steps[step_name]
            cs = contender_steps[step_name]

            comparisons.append(
                ComparisonItem(
                    stack_id=stack_id,
                    step=step_name,
                    baseline=bs.latency_summary,
                    contender=cs.latency_summary,
                    p50_ratio=round(cs.latency_summary.p50_ns / bs.latency_summary.p50_ns, 3)
                    if bs.latency_summary.p50_ns > 0
                    else 0.0,
                    p95_ratio=round(cs.latency_summary.p95_ns / bs.latency_summary.p95_ns, 3)
                    if bs.latency_summary.p95_ns > 0
                    else 0.0,
                    p99_ratio=round(cs.latency_summary.p99_ns / bs.latency_summary.p99_ns, 3)
                    if bs.latency_summary.p99_ns > 0
                    else 0.0,
                    throughput_ratio=round(cs.throughput_ops_s / bs.throughput_ops_s, 3)
                    if bs.throughput_ops_s > 0
                    else 0.0,
                    error_delta=cs.errors - bs.errors,
                )
            )

    compare_result = CompareResult(
        baseline_run_id=baseline.run_id,
        contender_run_id=contender.run_id,
        scenario_name=baseline.scenario.name,
        scenario_match=scenario_match,
        comparisons=comparisons,
    )

    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w") as f:
            json.dump(compare_result.model_dump(), f, indent=2, default=str)

    _print_comparison(compare_result)


@app.command()
def report(
    result_path: Annotated[str, typer.Argument(help="Path to result JSON")],
    output: Annotated[str, typer.Option("--output", "-o", help="Output HTML path")] = "",
) -> None:
    """Generate an HTML report from benchmark results."""
    from benchflow.core.report.html import generate_html_report

    result = RunResult.load(result_path)

    if not output:
        output = result_path.replace(".json", ".html")

    html = generate_html_report(result)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        f.write(html)

    console.print(f"[green]Report generated:[/green] {output}")


def _print_summary(result: RunResult) -> None:
    table = Table(title=f"Benchmark Results — {result.scenario.name}")
    table.add_column("Target", style="cyan")
    table.add_column("Step", style="white")
    table.add_column("Ops", justify="right")
    table.add_column("p50 (ms)", justify="right", style="green")
    table.add_column("p95 (ms)", justify="right", style="yellow")
    table.add_column("p99 (ms)", justify="right", style="red")
    table.add_column("Throughput", justify="right")
    table.add_column("Errors", justify="right")

    for target in result.targets:
        for step in target.steps:
            ls = step.latency_summary
            table.add_row(
                target.stack_id,
                step.name,
                str(step.ops),
                f"{ls.p50_ns / 1_000_000:.2f}",
                f"{ls.p95_ns / 1_000_000:.2f}",
                f"{ls.p99_ns / 1_000_000:.2f}",
                f"{step.throughput_ops_s:.0f} ops/s",
                str(step.errors),
            )

    console.print(table)


def _print_comparison(compare: CompareResult) -> None:
    table = Table(title="Comparison: baseline vs contender")
    table.add_column("Stack", style="cyan")
    table.add_column("Step", style="white")
    table.add_column("p50 ratio", justify="right")
    table.add_column("p95 ratio", justify="right")
    table.add_column("p99 ratio", justify="right")
    table.add_column("Throughput ratio", justify="right")
    table.add_column("Verdict", justify="center")

    for c in compare.comparisons:
        verdict = _verdict(c.p95_ratio)
        table.add_row(
            c.stack_id,
            c.step,
            _format_ratio(c.p50_ratio),
            _format_ratio(c.p95_ratio),
            _format_ratio(c.p99_ratio),
            _format_ratio(c.throughput_ratio, higher_is_better=True),
            verdict,
        )

    console.print(table)
    console.print(f"\nBaseline: {compare.baseline_run_id} → Contender: {compare.contender_run_id}")
    if not compare.scenario_match:
        console.print("[yellow]⚠ Scenario signatures differ[/yellow]")


def _format_ratio(ratio: float, higher_is_better: bool = False) -> str:
    if ratio == 0.0:
        return "N/A"
    if higher_is_better:
        color = "green" if ratio >= 1.0 else "red"
    else:
        color = "green" if ratio <= 1.0 else "red"
    return f"[{color}]{ratio:.3f}x[/{color}]"


def _verdict(p95_ratio: float) -> str:
    if p95_ratio == 0.0:
        return "N/A"
    if p95_ratio <= 0.95:
        return "[green]✓ faster[/green]"
    if p95_ratio >= 1.05:
        return "[red]✗ slower[/red]"
    return "[white]≈ same[/white]"


if __name__ == "__main__":
    app()
