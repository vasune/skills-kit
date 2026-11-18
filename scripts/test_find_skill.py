#!/usr/bin/env python3
"""Тесты find_skill.py на временных репозиториях.

    python3 ./scripts/test_find_skill.py

Настоящий каталог не трогается: навыки и INDEX пишутся в tempfile, CLI
запускается подпроцессом, поведение проверяется по выводу и коду возврата.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
FIND_PY = SCRIPTS / "find_skill.py"

DATABASE = "Открывать, когда нужны миграции базы данных PostgreSQL."
FRONTEND = "Открывать, когда собирается React-фронтенд."
MACOS = "Use when checking macOS autostart or a stuck service."


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def skill_text(name: str, description: str) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f'description: "{description}"\n'
        "version: 1.0.0\n"
        "author: test\n"
        "license: MIT\n"
        "---\n\n"
        f"# {name}\n"
    )


def make_repo(root: Path, skills: dict[str, tuple[str, str]]) -> None:
    rows = []
    for name, (description, level) in skills.items():
        write(root / "skills" / "core" / name / "SKILL.md", skill_text(name, description))
        rows.append(
            f"| [`{name}`](skills/core/{name}/SKILL.md) | {level} | когда | 1 |"
        )
    write(
        root / "INDEX.md",
        "# Каталог\n\n| Навык | Ур. | Когда | Файлов |\n|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n",
    )


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(FIND_PY), *args, "--repo", str(root)],
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        check=False,
    )


class RepoTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        make_repo(
            self.repo,
            {
                "database": (DATABASE, "L1"),
                "frontend": (FRONTEND, "L2"),
                "macos-service": (MACOS, "L1"),
            },
        )

    def json_rows(self, *args: str) -> list[dict]:
        result = run_cli(self.repo, "--json", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)


class SearchTests(RepoTestCase):
    def test_known_phrase_finds_own_skill(self) -> None:
        result = run_cli(self.repo, "нужны миграции базы данных")
        self.assertEqual(result.returncode, 0)
        lines = [line for line in result.stdout.splitlines() if "SKILL.md" in line]
        self.assertIn("database", lines[0])
        self.assertIn("skills/core/database/SKILL.md", lines[0])

    def test_english_phrase_finds_english_skill(self) -> None:
        rows = self.json_rows("my service is stuck on macOS")
        self.assertEqual(rows[0]["name"], "macos-service")
        self.assertGreater(rows[0]["score"], 0)

    def test_russian_alias_finds_english_skill(self) -> None:
        make_repo(self.repo, {"planner": ("Write a markdown plan; no execution.", "L1")})
        rows = self.json_rows("напиши план")
        self.assertEqual(rows[0]["name"], "planner")
        self.assertGreater(rows[0]["score"], 0)

    def test_search_synonyms_find_macos(self) -> None:
        rows = self.json_rows("как поставить автозапуск на маке")
        self.assertEqual(rows[0]["name"], "macos-service")
        self.assertGreater(rows[0]["score"], 0)

    def test_json_shape_and_sorting(self) -> None:
        rows = self.json_rows("нужны миграции базы данных")
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(
                set(row), {"name", "level", "path", "score", "description"}
            )
            self.assertIsInstance(row["score"], float)
            self.assertEqual(len(f"{row['score']:.3f}"), 5)
        scores = [row["score"] for row in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(rows[0]["level"], "L1")
        self.assertEqual(rows[0]["path"], "skills/core/database/SKILL.md")
        self.assertEqual(rows[0]["description"], DATABASE)

    def test_top_limits_results(self) -> None:
        rows = self.json_rows("миграции", "--top", "1")
        self.assertEqual(len(rows), 1)


class NoMatchAndListTests(RepoTestCase):
    def test_nonsense_phrase_reports_no_match(self) -> None:
        result = run_cli(self.repo, "абракадабра")
        self.assertEqual(result.returncode, 0)
        self.assertIn("похожего навыка нет", result.stdout)
        self.assertIn("ближайшие", result.stdout)
        self.assertIn("SKILL.md", result.stdout)

    def test_json_no_match_stays_valid_and_exits_zero(self) -> None:
        result = run_cli(self.repo, "абракадабра", "--json")
        self.assertEqual(result.returncode, 0)
        rows = json.loads(result.stdout)
        self.assertEqual(len(rows), 3)
        self.assertIn("похожего навыка нет", result.stderr)

    def test_list_prints_all_skills(self) -> None:
        result = run_cli(self.repo, "--list")
        self.assertEqual(result.returncode, 0)
        for name in ("database", "frontend", "macos-service"):
            self.assertIn(name, result.stdout)
        self.assertIn("всего навыков: 3", result.stdout)
        self.assertIn("L2", result.stdout)
        self.assertIn("skills/core/frontend/SKILL.md", result.stdout)

    def test_no_arguments_returns_usage(self) -> None:
        result = run_cli(self.repo)
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage", result.stderr.lower())

    def test_bad_top_is_usage_error(self) -> None:
        result = run_cli(self.repo, "миграции", "--top", "0")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
