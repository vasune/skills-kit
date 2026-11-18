#!/usr/bin/env python3
"""Тесты routing_eval.py на временных репозиториях.

    python3 ./scripts/test_routing_eval.py

Настоящий каталог не трогается: навыки и кейсы пишутся в tempfile. Каждый
класс провала проверяется «ловушкой»: сильное описание проходит, слабое —
падает, negative уходит владельцу, коллизия ловится.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import routing_eval  # noqa: E402

ROUTING_PY = SCRIPTS / "routing_eval.py"

DATABASE = "Открывать, когда нужны миграции базы данных PostgreSQL."
FRONTEND = "Открывать, когда собирается React-фронтенд."
DEPLOY = "Открывать, когда деплой в Yandex Cloud."


# --- сборка временного репозитория ----------------------------------------


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def skill_text(name: str, description: str) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "version: 1.0.0\n"
        "author: test\n"
        "license: MIT\n"
        "---\n\n"
        f"# {name}\n"
    )


def make_repo(
    root: Path,
    skills: dict[str, str],
    cases: dict[str, dict],
) -> None:
    for name, description in skills.items():
        write(root / "skills" / "core" / name / "SKILL.md", skill_text(name, description))
    for name, case in cases.items():
        write(
            root / "evals" / "routing" / f"{name}.json",
            json.dumps({"skill": name, **case}, ensure_ascii=False, indent=2) + "\n",
        )


def default_repo(root: Path) -> None:
    make_repo(
        root,
        {"database": DATABASE, "frontend": FRONTEND, "deploy": DEPLOY},
        {
            "database": {
                "positive": ["нужны миграции базы данных"],
                "negative": [{"prompt": "собираем React-фронтенд", "owner": "frontend"}],
            }
        },
    )


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROUTING_PY), "--repo", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class RepoTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def default_repo(self) -> None:
        default_repo(self.repo)


# --- чистые функции --------------------------------------------------------


class PureRuleTests(unittest.TestCase):
    def test_stemmer_unifies_russian_endings(self) -> None:
        stems = {routing_eval.stem(word) for word in ("навык", "навыки", "навыков")}
        self.assertEqual(stems, {"навык"})
        self.assertEqual(routing_eval.stem("миграции"), routing_eval.stem("миграцию"))

    def test_normalize_removes_trigger_and_stopwords(self) -> None:
        self.assertEqual(routing_eval.normalize("Открывать, когда use when"), [])
        tokens = routing_eval.normalize("нужны миграции базы данных")
        self.assertIn("migration", tokens)
        self.assertNotIn("нужны", tokens)

    def test_aliases_bridge_russian_and_english(self) -> None:
        self.assertIn("plan", routing_eval.normalize("напиши план"))
        self.assertIn("plan", routing_eval.normalize("plans"))
        self.assertIn("commit", routing_eval.normalize("коммит"))
        self.assertIn("bug", routing_eval.normalize("ошибка"))
        self.assertEqual(
            routing_eval.normalize("навыки"), routing_eval.normalize("skills")
        )

    def test_aliases_can_be_disabled(self) -> None:
        self.assertIn("план", routing_eval.normalize("план", aliases=False))
        self.assertNotIn("plan", routing_eval.normalize("план", aliases=False))

    def test_tokenize_keeps_hyphenated_terms_apart(self) -> None:
        self.assertEqual(
            routing_eval.tokenize("React-фронтенд, macOS."),
            ["react", "фронтенд", "macos"],
        )


# --- метрики ---------------------------------------------------------------


class MetricsTests(RepoTestCase):
    def test_strong_description_passes_floor(self) -> None:
        self.default_repo()
        result, errors = routing_eval.evaluate(self.repo)
        self.assertEqual(errors, [])
        self.assertEqual(result.positive_total, 1)
        self.assertEqual(result.rank1_hits, 1)
        self.assertEqual(result.negative_errors, [])

    def test_alias_lets_english_description_catch_russian_query(self) -> None:
        make_repo(
            self.repo,
            {
                "planner": "Write a markdown plan; no execution.",
                "frontend": "Открывать, когда собирается React-фронтенд.",
            },
            {"planner": {"positive": ["напиши план"]}},
        )
        with_aliases, _ = routing_eval.evaluate(self.repo)
        without_aliases, _ = routing_eval.evaluate(self.repo, aliases=False)
        self.assertEqual(with_aliases.rank1_hits, 1)
        self.assertEqual(without_aliases.rank1_hits, 0)

    def test_weak_description_fails_positive(self) -> None:
        make_repo(
            self.repo,
            {
                "database": "Открывать, когда нужна помощь.",
                "postgres": DATABASE,
                "frontend": FRONTEND,
            },
            {"database": {"positive": ["нужны миграции базы данных"]}},
        )
        result, errors = routing_eval.evaluate(self.repo)
        self.assertEqual(errors, [])
        self.assertEqual(result.rank1_hits, 0)
        self.assertEqual(result.rank1_rate, 0.0)
        self.assertEqual(len(result.positive_failures), 1)

        cli = run_cli(self.repo, "--min-rank1", "90")
        self.assertEqual(cli.returncode, 1)
        self.assertIn("провал: rank-1 0%", cli.stdout)

    def test_floor_zero_lets_failure_through(self) -> None:
        make_repo(
            self.repo,
            {
                "database": "Открывать, когда нужна помощь.",
                "postgres": DATABASE,
                "frontend": FRONTEND,
            },
            {"database": {"positive": ["нужны миграции базы данных"]}},
        )
        cli = run_cli(self.repo, "--min-rank1", "0")
        self.assertEqual(cli.returncode, 0)

    def test_top_k_counts_rank_two(self) -> None:
        make_repo(
            self.repo,
            {
                "alpha": "Открывать, когда нужен database migration.",
                "beta": "Открывать, когда нужен database migration.",
            },
            {"beta": {"positive": ["нужен database migration"]}},
        )
        result, errors = routing_eval.evaluate(self.repo, top=3)
        self.assertEqual(errors, [])
        self.assertEqual(result.rank1_hits, 0)
        self.assertEqual(result.topk_hits, 1)
        self.assertEqual(result.topk_rate, 100.0)

    def test_negative_must_reach_owner(self) -> None:
        make_repo(
            self.repo,
            {"database": DATABASE, "frontend": FRONTEND},
            {
                "frontend": {
                    "positive": ["собираем React-фронтенд"],
                    "negative": [
                        {"prompt": "нужны миграции базы данных", "owner": "database"}
                    ],
                }
            },
        )
        result, errors = routing_eval.evaluate(self.repo)
        self.assertEqual(errors, [])
        self.assertEqual(result.negative_errors, [])

    def test_negative_drift_is_reported(self) -> None:
        make_repo(
            self.repo,
            {"database": DATABASE, "frontend": FRONTEND},
            {
                "database": {
                    "positive": ["нужны миграции базы данных"],
                    "negative": [
                        {"prompt": "нужны миграции базы данных", "owner": "frontend"}
                    ],
                }
            },
        )
        result, errors = routing_eval.evaluate(self.repo)
        self.assertEqual(errors, [])
        self.assertEqual(len(result.negative_errors), 1)
        self.assertIn("должен уйти в frontend", result.negative_errors[0])

        cli = run_cli(self.repo)
        self.assertEqual(cli.returncode, 1)
        self.assertIn("ошибка negative", cli.stdout)

    def test_collision_detected_for_duplicate_descriptions(self) -> None:
        make_repo(
            self.repo,
            {
                "alpha": "Открывать, когда пишется отчёт для руководства.",
                "beta": "Use when пишется отчёт для руководства.",
            },
            {"alpha": {"positive": ["пишется отчёт для руководства"]}},
        )
        result, errors = routing_eval.evaluate(self.repo)
        self.assertEqual(errors, [])
        self.assertEqual(len(result.collisions), 1)
        self.assertIn("alpha", result.collisions[0][:2])

    def test_no_collision_for_distinct_descriptions(self) -> None:
        self.default_repo()
        result, errors = routing_eval.evaluate(self.repo)
        self.assertEqual(errors, [])
        self.assertEqual(result.collisions, [])

    def test_collision_threshold_is_configurable(self) -> None:
        make_repo(
            self.repo,
            {
                "alpha": "Открывать, когда пишется отчёт для руководства.",
                "beta": "Use when пишется отчёт для руководства и цифры, картинки.",
            },
            {"alpha": {"positive": ["пишется отчёт для руководства"]}},
        )
        default, _ = routing_eval.evaluate(self.repo)
        self.assertEqual(len(default.collisions), 1)
        strict, _ = routing_eval.evaluate(self.repo, collision_threshold=0.99)
        self.assertEqual(strict.collisions, [])


    def test_known_miss_is_excused_from_floor(self) -> None:
        make_repo(
            self.repo,
            {
                "database": "Открывать, когда нужна помощь.",
                "postgres": DATABASE,
                "frontend": FRONTEND,
            },
            {
                "database": {
                    "positive": ["нужны миграции базы данных"],
                    "known_miss": "Tier-2 не знает синонимов: чинить описание",
                }
            },
        )
        result, errors = routing_eval.evaluate(self.repo)
        self.assertEqual(errors, [])
        self.assertEqual(result.rank1_hits, 0)
        self.assertEqual(result.known_miss_total, 1)
        self.assertEqual(result.audited_total, 0)
        self.assertEqual(result.rank1_rate, 100.0)

        cli = run_cli(self.repo, "--min-rank1", "90")
        self.assertEqual(cli.returncode, 0, cli.stdout)
        self.assertIn("known_miss (не влияет на floor): 1", cli.stdout)

        verbose = run_cli(self.repo, "--min-rank1", "90", "--verbose")
        self.assertIn("known_miss: database:", verbose.stdout)
        self.assertIn("Tier-2 не знает синонимов", verbose.stdout)

    def test_known_miss_must_be_non_empty_string(self) -> None:
        make_repo(
            self.repo,
            {"database": DATABASE},
            {
                "database": {
                    "positive": ["нужны миграции базы данных"],
                    "known_miss": 42,
                }
            },
        )
        _, errors = routing_eval.evaluate(self.repo)
        self.assertTrue(any("known_miss должен быть" in error for error in errors))


# --- схема кейсов и CLI ----------------------------------------------------


class SchemaTests(RepoTestCase):
    def test_unknown_skill_in_case(self) -> None:
        make_repo(
            self.repo,
            {"database": DATABASE},
            {"ghost": {"positive": ["что-то"]}},
        )
        _, errors = routing_eval.evaluate(self.repo)
        self.assertTrue(any("навыка ghost нет" in error for error in errors))

    def test_unknown_negative_owner(self) -> None:
        make_repo(
            self.repo,
            {"database": DATABASE},
            {
                "database": {
                    "positive": ["нужны миграции базы данных"],
                    "negative": [{"prompt": "другое", "owner": "ghost"}],
                }
            },
        )
        _, errors = routing_eval.evaluate(self.repo)
        self.assertTrue(any("owner=ghost" in error for error in errors))

    def test_duplicate_positive(self) -> None:
        make_repo(
            self.repo,
            {"database": DATABASE, "frontend": FRONTEND},
            {
                "database": {"positive": ["нужны миграции"]},
                "frontend": {"positive": ["нужны миграции"]},
            },
        )
        _, errors = routing_eval.evaluate(self.repo)
        self.assertTrue(any("positive повторяется" in error for error in errors))


class CliTests(RepoTestCase):
    def test_verbose_lists_failures(self) -> None:
        make_repo(
            self.repo,
            {
                "database": "Открывать, когда нужна помощь.",
                "postgres": DATABASE,
                "frontend": FRONTEND,
            },
            {"database": {"positive": ["нужны миграции базы данных"]}},
        )
        cli = run_cli(self.repo, "--verbose", "--min-rank1", "0")
        self.assertEqual(cli.returncode, 0)
        self.assertIn("провал: database", cli.stdout)

    def test_clean_repo_exit_zero_and_metrics(self) -> None:
        self.default_repo()
        cli = run_cli(self.repo, "--min-rank1", "90")
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        self.assertIn("rank-1: 100%", cli.stdout)
        self.assertIn("top-k:", cli.stdout)
        self.assertIn("floor rank-1: 90% — пройден", cli.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
