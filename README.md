# taskwarrior-valore

Standalone Taskwarrior value and priority assessment utility.

`assess_value.py` exports matching Taskwarrior tasks, asks weighted benefit/cost questions, calculates a normalized `value`, and optionally writes both `value` and `priority` back to Taskwarrior.

## Requirements

- Python 3.10+
- Taskwarrior CLI available as `task`
- Taskwarrior `value` UDA configured
- Python dependencies from `requirements.txt`

## Taskwarrior Setup

The tool writes the normalized assessment score to a Taskwarrior UDA named `value`.
Configure it before using the tool:

```bash
task config uda.value.type numeric
task config uda.value.label Value
```

Equivalent `.taskrc` entries:

```text
uda.value.type=numeric
uda.value.label=Value
```

## Install Dependencies

```bash
python3 -m pip install -r requirements.txt
```

## Usage

Interactive filter picker:

```bash
./assess_value.py
```

Assess matching tasks:

```bash
./assess_value.py +PENDING project:Work
```

Preview without modifying Taskwarrior:

```bash
./assess_value.py +PENDING --dry-run
```

Skip tasks that already have a positive `value` field:

```bash
./assess_value.py +PENDING --only-unrated
```

Limit a batch:

```bash
./assess_value.py +PENDING --limit 5
```

Use simple numeric prompts instead of the questionary checkbox UI:

```bash
./assess_value.py +PENDING --simple-input
```

Use a custom config file:

```bash
./assess_value.py +PENDING --config ./valore.toml
```

## Configuration

By default, the tool reads `valore.toml` from the current working directory if it exists.

Example:

```toml
[priority.thresholds]
high = 70
medium = 40
```

Thresholds control how the normalized value maps to Taskwarrior priority:

- `H`: value >= `priority.thresholds.high`
- `M`: value >= `priority.thresholds.medium`
- `L`: value below `priority.thresholds.medium`

Thresholds must satisfy:

```text
0 <= medium <= high <= 100
```

## Scoring

Benefit dimensions increase task value:

- Outcome Value
- Time Sensitivity
- Commitment
- Leverage

Cost dimensions reduce task value:

- Effort
- Uncertainty / Friction

The current weights are:

- Outcome Value: `5`
- Time Sensitivity: `4`
- Commitment: `4`
- Leverage: `3`
- Effort: `2`
- Uncertainty / Friction: `2`

Costs reduce the score, but they are intentionally weighted lower than benefits. This avoids burying high-value work just because it is hard.

The normalized value is mapped to Taskwarrior priority:

- `H`: value >= 70
- `M`: value >= 40
- `L`: value < 40
