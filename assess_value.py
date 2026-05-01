#!/usr/bin/env python3
"""Standalone Taskwarrior priority assessment utility.

This script is intentionally independent from TaskVarios. It reads pending tasks
from Taskwarrior, asks weighted value/risk questions, then writes `value` and
`priority` back to the selected task.
"""

from __future__ import annotations

import argparse
import json
import logging
import shlex
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from rich import box
from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

try:
    from questionary import Choice, Style, checkbox
except ImportError:
    Choice = None
    Style = None
    checkbox = None

logger = logging.getLogger("assess_priority")
console = Console()


@dataclass(frozen=True)
class Answer:
    code: str
    text: str
    value: int


@dataclass(frozen=True)
class Dimension:
    name: str
    group: str
    question: str
    kind: str
    weight: int
    answers: tuple[Answer, ...]


@dataclass(frozen=True)
class PriorityThresholds:
    high: float = 70.0
    medium: float = 40.0


DEFAULT_CONFIG_PATH = Path("valore.toml")
DEFAULT_THRESHOLDS = PriorityThresholds()


DIMENSIONS = (
    Dimension(
        name="Outcome Value",
        group="1. Outcome Value",
        question="If completed, how valuable is the outcome?",
        kind="benefit",
        weight=5,
        answers=(
            Answer("Critical", "Critical outcome or major progress", 5),
            Answer("High", "High-value outcome", 4),
            Answer("Meaningful", "Meaningful progress", 3),
            Answer("Some Value", "Some useful value", 2),
            Answer("Minor", "Minor value", 1),
            Answer("None", "Little or no value", 0),
        ),
    ),
    Dimension(
        name="Time Sensitivity",
        group="2. Time Sensitivity",
        question="How much does the task's value decay if delayed?",
        kind="benefit",
        weight=4,
        answers=(
            Answer("Immediate", "Must happen today or now", 5),
            Answer("This Week", "Value drops if not done this week", 4),
            Answer("This Month", "Value drops if not done this month", 3),
            Answer("This Quarter", "Value drops if not done this quarter", 2),
            Answer("Eventually", "Timing matters, but not soon", 1),
            Answer("No Pressure", "No meaningful timing pressure", 0),
        ),
    ),
    Dimension(
        name="Commitment",
        group="3. Commitment",
        question="How strong is the external or internal commitment?",
        kind="benefit",
        weight=4,
        answers=(
            Answer("Hard", "Hard commitment, blocking others, or serious consequence", 5),
            Answer("Promised", "Promised or clearly expected by someone", 4),
            Answer("Personal", "Important personal commitment", 3),
            Answer("Soft", "Soft commitment", 2),
            Answer("Optional", "Optional or tentative", 1),
            Answer("None", "No meaningful commitment", 0),
        ),
    ),
    Dimension(
        name="Leverage",
        group="4. Leverage",
        question="Does this unlock, simplify, or multiply other work?",
        kind="benefit",
        weight=3,
        answers=(
            Answer("Massive", "Unblocks or multiplies many things", 5),
            Answer("High", "Unblocks important work", 4),
            Answer("Workflow", "Improves future workflow or reduces repeated friction", 3),
            Answer("Some", "Some leverage beyond the task itself", 2),
            Answer("Isolated", "Mostly isolated benefit", 1),
            Answer("None", "No leverage", 0),
        ),
    ),
    Dimension(
        name="Effort",
        group="5. Effort",
        question="How much cost in time/resources will this task require?",
        kind="cost",
        weight=2,
        answers=(
            Answer("Massive", "Massive project: requires months of effort", 5),
            Answer("Large", "Large project: requires weeks of effort", 4),
            Answer("Medium", "Medium project: requires days of work", 3),
            Answer("Small", "Small task: takes hours", 2),
            Answer("Quick", "Quick task: less than 1 hour", 1),
            Answer("Minimal", "Minimal effort: minutes", 0),
        ),
    ),
    Dimension(
        name="Uncertainty / Friction",
        group="6. Uncertainty / Friction",
        question="How unclear, risky, or frictional is this task?",
        kind="cost",
        weight=2,
        answers=(
            Answer("Very High", "Very unclear, high risk, or heavy friction", 5),
            Answer("High", "Significant unknowns or friction", 4),
            Answer("Moderate", "Some uncertainty or friction", 3),
            Answer("Low", "Mostly clear with minor friction", 2),
            Answer("Very Low", "Very clear and low friction", 1),
            Answer("None", "Trivial, clear, and frictionless", 0),
        ),
    ),
)

PRESET_FILTERS = {
    "1": ("Overdue", "+OVERDUE +PENDING"),
    "2": ("Due Today", "due:today +PENDING"),
    "3": ("Due Tomorrow", "due:tomorrow +PENDING"),
    "4": ("Inbox", "+in +PENDING"),
    "5": ("All Pending", "+PENDING"),
}

PROMPT_STYLE = (
    Style.from_dict(
        {
            "qmark": "fg:#e91e63 bold",
            "question": "bold",
            "instruction": "fg:#ff9d00 italic",
            "pointer": "fg:#ef029a bold",
            "highlighted": "fg:#9aef02 bold",
            "selected": "fg:#cc5454",
            "separator": "fg:#cc5454",
            "disabled": "fg:#efce02 italic",
        }
    )
    if Style
    else None
)


def run_task(args: Iterable[str]) -> str:
    """Run the Taskwarrior CLI and return stdout."""
    command = ["task", *args]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Taskwarrior command failed: {command}")
    return result.stdout


def export_tasks(filter_query: str) -> list[dict]:
    """Export matching tasks from Taskwarrior."""
    args = [*shlex.split(filter_query), "export"]
    output = run_task(args)
    return json.loads(output or "[]")


def modify_task(task_uuid: str, *modifiers: str) -> None:
    """Modify a task without Taskwarrior confirmation prompts."""
    run_task(["rc.confirmation=off", task_uuid, "modify", *modifiers])


def complete_task(task_uuid: str) -> None:
    run_task(["rc.confirmation=off", task_uuid, "done"])


def delete_task(task_uuid: str) -> None:
    run_task(["rc.confirmation=off", task_uuid, "delete"])


def select_filter() -> str:
    table = Table(title="Preset Filters", box=box.ROUNDED)
    table.add_column("Number", style="cyan", justify="center")
    table.add_column("Name", style="green")
    table.add_column("Query", style="dim")
    for key, (name, query) in PRESET_FILTERS.items():
        table.add_row(key, name, query)
    console.print(table)

    selected = Prompt.ask(
        "Enter a Taskwarrior filter or select a number",
        choices=[*PRESET_FILTERS.keys(), "custom"],
        default="5",
    )
    if selected in PRESET_FILTERS:
        return PRESET_FILTERS[selected][1]
    return Prompt.ask("Enter custom Taskwarrior filter")


def build_question_choices(dimensions: tuple[Dimension, ...]) -> list:
    choices = []
    for dimension_index, dimension in enumerate(dimensions):
        choices.append(
            Choice(
                title=f"{dimension.group}: {dimension.question}",
                disabled=True,
            )
        )
        for answer in dimension.answers:
            choices.append(
                Choice(
                    title=f"{answer.code}: {answer.text}",
                    value=f"{dimension_index}_{answer.code}",
                )
            )
    return choices


def validate_questionary_selection(selected: list[str], dimensions: tuple[Dimension, ...]):
    selected_dimensions = [
        int(value.split("_", 1)[0])
        for value in selected
        if "_" in value
    ]
    if len(selected_dimensions) != len(dimensions):
        return (
            "Select exactly one answer per question. "
            f"Selected {len(selected_dimensions)} of {len(dimensions)}."
        )
    if len(set(selected_dimensions)) != len(dimensions):
        return "Select only one answer for each question."
    return True


def collect_scores_with_questionary(
    dimensions: tuple[Dimension, ...],
) -> dict[str, Answer] | None:
    if checkbox is None:
        raise RuntimeError(
            "questionary is required for the default assessment UI. "
            "Install it with `python3 -m pip install questionary`, or run with `--simple-input`."
        )

    selected_values = checkbox(
        message="Assess this task. Select one answer per question:",
        choices=build_question_choices(dimensions),
        validate=lambda selected: validate_questionary_selection(selected, dimensions),
        qmark="?",
        instruction="(Use space to select, Enter to confirm)",
        style=PROMPT_STYLE,
    ).ask()

    if selected_values is None:
        return None

    selected_answers = {}
    for selected in selected_values:
        dimension_index_raw, answer_code = selected.split("_", 1)
        dimension = dimensions[int(dimension_index_raw)]
        answer = next(item for item in dimension.answers if item.code == answer_code)
        selected_answers[dimension.name] = answer
    return selected_answers


def collect_scores_simple(dimensions: tuple[Dimension, ...]) -> dict[str, Answer]:
    console.print("[bold]Assess this task. Enter one score per question.[/bold]")
    selected_answers = {}
    for dimension in dimensions:
        table = Table(
            title=f"{dimension.group}: {dimension.question}",
            box=box.ROUNDED,
            show_lines=False,
        )
        table.add_column("Score", style="cyan", justify="center")
        table.add_column("Answer", style="green")
        table.add_column("Meaning", style="white")
        for answer in dimension.answers:
            table.add_row(str(answer.value), answer.code, answer.text)
        console.print(table)

        while True:
            value = IntPrompt.ask("Score", default=0)
            answer = next(
                (item for item in dimension.answers if item.value == value),
                None,
            )
            if answer:
                selected_answers[dimension.name] = answer
                break
            console.print("[red]Enter a valid score from the table.[/red]")
    return selected_answers


def validate_thresholds(thresholds: PriorityThresholds) -> PriorityThresholds:
    if not 0 <= thresholds.medium <= thresholds.high <= 100:
        raise ValueError(
            "Priority thresholds must satisfy 0 <= medium <= high <= 100."
        )
    return thresholds


def load_config(config_path: Path | None) -> PriorityThresholds:
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return DEFAULT_THRESHOLDS

    with config_path.open("rb") as config_file:
        data = tomllib.load(config_file)

    priority_config = data.get("priority", {})
    thresholds_config = priority_config.get("thresholds", {})
    thresholds = PriorityThresholds(
        high=float(thresholds_config.get("high", DEFAULT_THRESHOLDS.high)),
        medium=float(thresholds_config.get("medium", DEFAULT_THRESHOLDS.medium)),
    )
    return validate_thresholds(thresholds)


def calculate_priority(
    scores: dict[str, int],
    dimensions: tuple[Dimension, ...],
    thresholds: PriorityThresholds = DEFAULT_THRESHOLDS,
) -> dict:
    thresholds = validate_thresholds(thresholds)
    benefit_score = sum(
        scores[dimension.name] * dimension.weight
        for dimension in dimensions
        if dimension.kind == "benefit"
    )
    cost_score = sum(
        scores[dimension.name] * dimension.weight
        for dimension in dimensions
        if dimension.kind == "cost"
    )
    net_score = benefit_score - cost_score

    max_benefit = sum(
        max(answer.value for answer in dimension.answers) * dimension.weight
        for dimension in dimensions
        if dimension.kind == "benefit"
    )
    max_cost = sum(
        max(answer.value for answer in dimension.answers) * dimension.weight
        for dimension in dimensions
        if dimension.kind == "cost"
    )

    normalized_value = round(((net_score + max_cost) / (max_benefit + max_cost)) * 100, 2)
    if normalized_value >= thresholds.high:
        priority = "H"
    elif normalized_value >= thresholds.medium:
        priority = "M"
    else:
        priority = "L"

    return {
        "benefit_score": benefit_score,
        "cost_score": cost_score,
        "net_score": net_score,
        "normalized_value": normalized_value,
        "priority": priority,
        "threshold_high": thresholds.high,
        "threshold_medium": thresholds.medium,
    }


def display_assessment_preview(
    selected_answers: dict[str, Answer],
    results: dict,
) -> None:
    table = Table(title="Assessment Preview", box=box.ROUNDED)
    table.add_column("Dimension", style="cyan")
    table.add_column("Answer", style="green")
    table.add_column("Score", justify="right")
    table.add_column("Meaning", style="white")

    for dimension in DIMENSIONS:
        answer = selected_answers[dimension.name]
        table.add_row(
            dimension.name,
            answer.code,
            str(answer.value),
            answer.text,
        )

    console.print(table)
    console.print(f"[green]Benefit score: {results['benefit_score']}[/green]")
    console.print(f"[green]Cost score: {results['cost_score']}[/green]")
    console.print(f"[green]Net score: {results['net_score']}[/green]")
    console.print(f"[green]Normalized value: {results['normalized_value']}[/green]")
    console.print(
        "[green]"
        f"Priority: {results['priority']} "
        f"(H >= {results['threshold_high']}, M >= {results['threshold_medium']})"
        "[/green]"
    )


def display_task(task: dict) -> None:
    title = f"Task {task.get('id', task.get('uuid', 'unknown'))}"
    table = Table(title=title, box=box.ROUNDED)
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")
    for field in ("description", "project", "priority", "value", "due", "scheduled", "tags", "uuid"):
        if field in task:
            table.add_row(field, str(task[field]))
    console.print(table)


def rate_task(
    task: dict,
    thresholds: PriorityThresholds,
    dry_run: bool = False,
    simple_input: bool = False,
) -> None:
    selected_answers = (
        collect_scores_simple(DIMENSIONS)
        if simple_input
        else collect_scores_with_questionary(DIMENSIONS)
    )
    if selected_answers is None:
        console.print("[blue]Rating cancelled.[/blue]")
        return

    scores = {
        dimension_name: answer.value
        for dimension_name, answer in selected_answers.items()
    }
    results = calculate_priority(scores, DIMENSIONS, thresholds)
    display_assessment_preview(selected_answers, results)

    if dry_run:
        console.print("[yellow]Dry run: task was not modified.[/yellow]")
        return

    if not Confirm.ask("Apply this value and priority?", default=True):
        console.print("[blue]Assessment not applied.[/blue]")
        return

    modify_task(
        task["uuid"],
        f"value:{results['normalized_value']:.2f}",
        f"priority:{results['priority']}",
    )
    console.print(
        f"[green]Updated {task['uuid']} with value:{results['normalized_value']:.2f} priority:{results['priority']}[/green]"
    )


def assess_tasks(
    filter_query: str,
    thresholds: PriorityThresholds,
    dry_run: bool = False,
    simple_input: bool = False,
    only_unrated: bool = False,
    limit: int | None = None,
) -> None:
    tasks = export_tasks(filter_query)
    if only_unrated:
        tasks = [
            task
            for task in tasks
            if float(task.get("value", 0) or 0) <= 0
        ]
    if limit is not None:
        tasks = tasks[:limit]

    if not tasks:
        console.print(f"[yellow]No tasks matched filter: {filter_query}[/yellow]")
        return

    console.print(f"[green]Found {len(tasks)} task{'s' if len(tasks) != 1 else ''}: {filter_query}[/green]")
    for task in tasks:
        console.rule()
        display_task(task)
        if float(task.get("value", 0) or 0) > 0:
            console.print(f"[yellow]Task already has value:{task['value']}[/yellow]")

        action = Prompt.ask(
            "Choose action",
            choices=["rate", "done", "delete", "skip", "quit"],
            default="skip",
        )
        if action == "rate":
            rate_task(
                task,
                thresholds,
                dry_run=dry_run,
                simple_input=simple_input,
            )
        elif action == "done":
            if dry_run:
                console.print("[yellow]Dry run: task was not completed.[/yellow]")
            else:
                complete_task(task["uuid"])
                console.print("[green]Task marked done.[/green]")
        elif action == "delete":
            if dry_run:
                console.print("[yellow]Dry run: task was not deleted.[/yellow]")
            else:
                delete_task(task["uuid"])
                console.print("[green]Task deleted.[/green]")
        elif action == "quit":
            return
        else:
            console.print("[blue]Skipped.[/blue]")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assess Taskwarrior task priority independently from TaskVarios."
    )
    parser.add_argument(
        "filter",
        nargs="*",
        help="Taskwarrior filter tokens, for example: +in project:Work",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculate priority without modifying tasks.",
    )
    parser.add_argument(
        "--simple-input",
        action="store_true",
        help="Use numeric prompts instead of the questionary checkbox UI.",
    )
    parser.add_argument(
        "--only-unrated",
        action="store_true",
        help="Skip tasks that already have a positive value field.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Assess at most this many matching tasks.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to TOML config file. Defaults to {DEFAULT_CONFIG_PATH}.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    filter_query = " ".join(args.filter) if args.filter else select_filter()

    try:
        thresholds = load_config(args.config)
        assess_tasks(
            filter_query,
            thresholds,
            dry_run=args.dry_run,
            simple_input=args.simple_input,
            only_unrated=args.only_unrated,
            limit=args.limit,
        )
    except KeyboardInterrupt:
        console.print("\n[red]Interrupted.[/red]")
        return 130
    except RuntimeError as error:
        console.print(f"[red]{error}[/red]")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
