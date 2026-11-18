#!/usr/bin/env python3
"""Тесты scripts/verify_install.py на временных репозиториях и целях.

    python3 scripts/test_verify_install.py

Каждый тест собирает минимальный репозиторий навыков во временном каталоге, цель
установки и запускает скрипт подпроцессом — так проверяется контракт CLI целиком:
коды выхода, человеческий вывод и JSON.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VERIFY = REPO / "scripts" / "verify_install.py"
SKILLS = {"alpha": "core", "beta": "code"}


def skill_text(name: str, version: str = "1.0.0", raw: str | None = None) -> str:
    if raw is not None:
        return raw
    return (
        "---\n"
        f"name: {name}\n"
        "description: Открывать, когда проверяется установка.\n"
        f"version: {version}\n"
        "---\n\n"
        f"# {name}\n"
    )


class VerifyInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.target = self.root / "target"
        self.target.mkdir()
        for name, group in SKILLS.items():
            self.write_skill(self.repo / "skills" / group / name, name)

    # --- сборка фикстур ---------------------------------------------------

    def write_skill(self, skill_dir: Path, name: str, **kwargs) -> None:
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            skill_text(name, **kwargs), encoding="utf-8"
        )

    def install_all(self) -> None:
        for name, group in SKILLS.items():
            shutil.copytree(
                self.repo / "skills" / group / name, self.target / name
            )

    def run_verify(
        self,
        *args: str,
        home: Path | None = None,
        bin_dir: Path | None = None,
    ) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        if home is not None:
            env["HOME"] = str(home)
            # Windows: Path.home() читает USERPROFILE, а не HOME.
            env["USERPROFILE"] = str(home)
            path = "/usr/bin:/bin"  # без claude и прочих хостов
            if bin_dir is not None:
                path = f"{bin_dir}:{path}"
            env["PATH"] = path
        cmd = [sys.executable, str(VERIFY), "--repo", str(self.repo), *args]
        return subprocess.run(cmd, capture_output=True, encoding="utf-8", env=env)

    # --- тесты ------------------------------------------------------------

    def test_all_present_is_ok(self) -> None:
        self.install_all()
        result = self.run_verify("--target", str(self.target))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("на месте: 2", result.stdout)
        self.assertIn("итог: OK", result.stdout)

    def test_missing_skill_dir_is_error(self) -> None:
        self.install_all()
        shutil.rmtree(self.target / "beta")
        result = self.run_verify("--target", str(self.target))
        self.assertEqual(result.returncode, 1)
        self.assertIn("beta", result.stdout)
        self.assertIn("нет каталога", result.stdout)
        self.assertIn("итог: ПРОВАЛ", result.stdout)

    def test_missing_skill_md_is_error(self) -> None:
        self.install_all()
        (self.target / "alpha" / "SKILL.md").unlink()
        result = self.run_verify("--target", str(self.target))
        self.assertEqual(result.returncode, 1)
        self.assertIn("alpha", result.stdout)
        self.assertIn("нет SKILL.md", result.stdout)

    def test_name_mismatch_is_error(self) -> None:
        self.install_all()
        (self.target / "alpha" / "SKILL.md").write_text(
            skill_text("wrong-name"), encoding="utf-8"
        )
        result = self.run_verify("--target", str(self.target))
        self.assertEqual(result.returncode, 1)
        self.assertIn("wrong-name", result.stdout)
        self.assertIn("не совпадает с каталогом", result.stdout)

    def test_broken_frontmatter_is_error(self) -> None:
        self.install_all()
        (self.target / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\n", encoding="utf-8"
        )
        result = self.run_verify("--target", str(self.target))
        self.assertEqual(result.returncode, 1)
        self.assertIn("битый frontmatter", result.stdout)

    def test_non_semver_version_is_error(self) -> None:
        self.install_all()
        (self.target / "alpha" / "SKILL.md").write_text(
            skill_text("alpha", version="1.0"), encoding="utf-8"
        )
        result = self.run_verify("--target", str(self.target))
        self.assertEqual(result.returncode, 1)
        self.assertIn("version не semver", result.stdout)

    def test_empty_target_is_error(self) -> None:
        result = self.run_verify("--target", str(self.target))
        self.assertEqual(result.returncode, 1)
        self.assertIn("цель пуста", result.stdout)
        self.assertIn("отсутствует: 2", result.stdout)

    def test_unknown_target_is_usage_error(self) -> None:
        result = self.run_verify("--target", "nope")
        self.assertEqual(result.returncode, 2)
        self.assertIn("неизвестная цель", result.stderr)

    def test_missing_target_dir_is_usage_error(self) -> None:
        result = self.run_verify("--target", str(self.root / "does-not-exist"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("нет каталога", result.stderr)

    def test_json_output_is_valid(self) -> None:
        self.install_all()
        result = self.run_verify("--target", str(self.target), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["skills_total"], 2)
        self.assertEqual(data["ok"], 2)
        self.assertEqual(data["missing"], 0)
        self.assertTrue(data["passed"])
        self.assertEqual(len(data["rows"]), 2)
        self.assertIn("host", data)

    def test_json_reports_problems(self) -> None:
        self.install_all()
        (self.target / "beta" / "SKILL.md").unlink()
        result = self.run_verify("--target", str(self.target), "--json")
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertFalse(data["passed"])
        self.assertEqual(data["missing"], 1)
        self.assertEqual(data["problems"][0]["skill"], "beta")

    def test_verbose_lists_all_skills(self) -> None:
        self.install_all()
        result = self.run_verify("--target", str(self.target), "--verbose")
        self.assertEqual(result.returncode, 0)
        self.assertIn("alpha | alpha/SKILL.md | на месте", result.stdout)
        self.assertIn("beta | beta/SKILL.md | на месте", result.stdout)

    def test_named_host_uses_home(self) -> None:
        home = self.root / "home"
        (home / ".claude" / "skills").mkdir(parents=True)
        self.install_all()
        for name in SKILLS:
            shutil.copytree(self.target / name, home / ".claude" / "skills" / name)
        result = self.run_verify("--target", "claude", home=home)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[skip] claude — хост не установлен", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
