import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from assess_value import (
    DIMENSIONS,
    PriorityThresholds,
    calculate_priority,
    load_config,
    validate_questionary_selection,
    validate_thresholds,
)


class PriorityCalculationTests(unittest.TestCase):
    def test_max_scores_are_high_priority(self):
        scores = {
            "Outcome Value": 5,
            "Time Sensitivity": 5,
            "Commitment": 5,
            "Leverage": 5,
            "Effort": 0,
            "Uncertainty / Friction": 0,
        }

        results = calculate_priority(scores, DIMENSIONS)

        self.assertEqual(results["normalized_value"], 100.0)
        self.assertEqual(results["priority"], "H")

    def test_cost_heavy_scores_are_low_priority(self):
        scores = {
            "Outcome Value": 0,
            "Time Sensitivity": 0,
            "Commitment": 0,
            "Leverage": 0,
            "Effort": 5,
            "Uncertainty / Friction": 5,
        }

        results = calculate_priority(scores, DIMENSIONS)

        self.assertEqual(results["normalized_value"], 0.0)
        self.assertEqual(results["priority"], "L")

    def test_midrange_scores_are_medium_priority(self):
        scores = {
            "Outcome Value": 3,
            "Time Sensitivity": 3,
            "Commitment": 3,
            "Leverage": 3,
            "Effort": 3,
            "Uncertainty / Friction": 3,
        }

        results = calculate_priority(scores, DIMENSIONS)

        self.assertGreaterEqual(results["normalized_value"], 40)
        self.assertLess(results["normalized_value"], 70)
        self.assertEqual(results["priority"], "M")

    def test_thresholds_can_be_customized(self):
        scores = {
            "Outcome Value": 3,
            "Time Sensitivity": 3,
            "Commitment": 3,
            "Leverage": 3,
            "Effort": 3,
            "Uncertainty / Friction": 3,
        }

        results = calculate_priority(
            scores,
            DIMENSIONS,
            PriorityThresholds(high=55, medium=35),
        )

        self.assertEqual(results["priority"], "H")

    def test_high_value_high_effort_can_still_be_high_priority(self):
        scores = {
            "Outcome Value": 5,
            "Time Sensitivity": 4,
            "Commitment": 4,
            "Leverage": 4,
            "Effort": 5,
            "Uncertainty / Friction": 4,
        }

        results = calculate_priority(scores, DIMENSIONS)

        self.assertGreaterEqual(results["normalized_value"], 70)
        self.assertEqual(results["priority"], "H")


class QuestionaryValidationTests(unittest.TestCase):
    def test_accepts_one_answer_per_dimension(self):
        selected = [f"{index}_answer" for index in range(len(DIMENSIONS))]

        self.assertTrue(validate_questionary_selection(selected, DIMENSIONS))

    def test_rejects_duplicate_dimension(self):
        selected = ["0_answer", "0_other", "1_answer", "2_answer", "3_answer", "4_answer"]

        self.assertEqual(
            validate_questionary_selection(selected, DIMENSIONS),
            "Select only one answer for each question.",
        )

    def test_rejects_missing_dimension(self):
        selected = ["0_answer", "1_answer"]

        self.assertIn(
            "Select exactly one answer per question.",
            validate_questionary_selection(selected, DIMENSIONS),
        )


class ConfigTests(unittest.TestCase):
    def test_loads_thresholds_from_toml(self):
        with TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "valore.toml"
            config_path.write_text(
                "[priority.thresholds]\nhigh = 80\nmedium = 50\n",
                encoding="utf-8",
            )

            thresholds = load_config(config_path)

        self.assertEqual(thresholds, PriorityThresholds(high=80.0, medium=50.0))

    def test_missing_config_uses_defaults(self):
        with TemporaryDirectory() as tmp_dir:
            thresholds = load_config(Path(tmp_dir) / "missing.toml")

        self.assertEqual(thresholds, PriorityThresholds())

    def test_rejects_invalid_thresholds(self):
        with self.assertRaises(ValueError):
            validate_thresholds(PriorityThresholds(high=30, medium=70))


if __name__ == "__main__":
    unittest.main()
