#!/usr/bin/env python3
"""Проверка установки навыков в каталог выбранного хоста.

    python3 scripts/verify_install.py --target <имя|путь> [--repo PATH] [--verbose] [--json]

Для каждого навыка репозитория проверяет, что в цели установки он на месте и
валиден: каталог существует, `SKILL.md` на месте, `name` во frontmatter совпадает
с именем каталога, `description` непустое, `version` — semver. Плюс проверка
наличия хоста и предложение проверить список навыков в сессии.

Коды выхода: 0 — всё на месте, 1 — расхождения или пустая цель, 2 — ошибка
использования (неизвестная цель, каталога нет).

Только стандартная библиотека, внешних зависимостей нет.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
REPO = Path(__file__).resolve().parent.parent
HOST_NAMES = (
    "claude",
    "opencode",
    "codex",
    "gemini",
    "cursor",
    "copilot",
    "kiro",
)
SESSION_HOSTS = ("claude", "opencode", "codex", "gemini")


class UsageError(Exception):
    """Ошибка аргументов или цели: код выхода 2."""


def host_dir(name: str, repo: Path) -> Path:
    """Каталог навыков хоста — та же таблица, что в scripts/install.sh."""
    home = Path.home()
    mapping = {
        "claude": home / ".claude" / "skills",
        "opencode": home / ".config" / "opencode" / "skill",
        "codex": home / ".codex" / "skills",
        "gemini": home / ".gemini" / "skills",
        "cursor": repo / ".cursor" / "skills",
        "copilot": repo / ".github" / "skills",
        "kiro": repo / ".kiro" / "skills",
    }
    if name not in mapping:
        raise UsageError(f"неизвестная цель: {name}")
    return mapping[name]


def resolve_target(name: str, repo: Path) -> tuple[str, Path]:
    """(имя, каталог для проверки)."""
    if name == "windsurf":
        raise UsageError(
            "windsurf: нет нативного каталога навыков — правила задаются настройками "
            "хоста, проверять нечего (см. README)"
        )
    if name in HOST_NAMES:
        path = host_dir(name, repo)
        if not path.is_dir():
            raise UsageError(
                f"нет каталога {path} для цели {name}: сначала установи "
                f"./scripts/install.sh --target {name}"
            )
        return name, path
    looks_like_path = (
        "/" in name or "\\" in name or name.startswith(("~", "."))
    )
    if not looks_like_path:
        raise UsageError(
            f"неизвестная цель: {name}. Цели: claude, opencode, codex, "
            "gemini, cursor, copilot, kiro или существующий каталог путём"
        )
    path = Path(name).expanduser()
    if not path.is_dir():
        raise UsageError(f"нет каталога {path}: --target требует существующий каталог")
    return name, path.resolve()


def discover_skills(repo: Path) -> list[tuple[str, str, Path]]:
    """[(имя, группа, каталог)] по skills/<группа>/<навык>/SKILL.md."""
    skills: list[tuple[str, str, Path]] = []
    seen: dict[str, Path] = {}
    for skill_md in sorted((repo / "skills").glob("*/*/SKILL.md")):
        skill_dir = skill_md.parent
        name = skill_dir.name
        if name in seen:
            raise UsageError(f"дубль имени навыка в репозитории: {name}")
        seen[name] = skill_dir
        skills.append((name, skill_dir.parent.name, skill_dir))
    if not skills:
        raise UsageError(f"в {repo / 'skills'} нет навыков: проверять нечего")
    return skills


def frontmatter(text: str) -> dict[str, str] | None:
    """Поля YAML-frontmatter или None, если блока нет либо он не закрыт."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    data: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip().strip("\"'")
    return data


def check_skill(name: str, target: Path) -> tuple[str, str, str]:
    """(статус, путь файла относительно цели, пояснение)."""
    dest = target / name
    rel = f"{name}/SKILL.md"
    if not dest.is_dir():
        return "missing", rel, "нет каталога"
    skill_md = dest / "SKILL.md"
    if not skill_md.is_file():
        return "missing", rel, "нет SKILL.md"
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as error:
        return "broken", rel, f"не читается: {error.strerror or error}"
    meta = frontmatter(text)
    if meta is None:
        return "broken", rel, "битый frontmatter"
    if not meta.get("name"):
        return "broken", rel, "пустое name"
    if meta["name"] != name:
        return "broken", rel, f"name={meta['name']} не совпадает с каталогом {name}"
    if not meta.get("description"):
        return "broken", rel, "пустое description"
    version = meta.get("version", "")
    if not version:
        return "broken", rel, "нет version"
    if not SEMVER.match(version):
        return "broken", rel, f"version не semver: {version}"
    return "ok", rel, ""


def host_checks(name: str, repo: Path, skills: list[tuple[str, str, Path]]) -> list[dict]:
    """Хоста-специфичные проверки: то, что не доказывается файлами."""
    checks: list[dict[str, str]] = []

    def add(check: str, status: str, detail: str) -> None:
        checks.append({"check": check, "status": status, "detail": detail})

    binary = shutil.which(name)
    if binary and name in SESSION_HOSTS:
        add(name, "info", "проверь в сессии: список навыков")
    elif binary:
        add(name, "info", f"бинарь найден: {binary}")
    else:
        add(name, "skip", "хост не установлен")
    return checks


def collect(target_name: str, repo: Path) -> dict:
    """Полные данные проверки для человеческого и машинного вывода."""
    name, target = resolve_target(target_name, repo)
    skills = discover_skills(repo)
    rows: list[dict[str, str]] = []
    problems: list[dict[str, str]] = []
    counts = {"ok": 0, "missing": 0, "broken": 0}
    for skill, group, _skill_dir in skills:
        status, rel, detail = check_skill(skill, target)
        row = {"skill": skill, "file": rel, "status": status, "detail": detail}
        rows.append(row)
        counts[status] += 1
        if status != "ok":
            problems.append(row)

    empty = not any((target / skill).is_dir() for skill, _group, _dir in skills)

    checks = host_checks(name, repo, skills)
    host_failed = any(item["status"] == "fail" for item in checks)
    passed = not problems and not host_failed and not empty
    return {
        "target": name,
        "target_path": str(target),
        "repo": str(repo),
        "skills_total": len(skills),
        "ok": counts["ok"],
        "missing": counts["missing"],
        "broken": counts["broken"],
        "empty": empty,
        "rows": rows,
        "problems": problems,
        "host": {"name": name, "checks": checks},
        "passed": passed,
    }


STATUS_LABEL = {"ok": "на месте", "missing": "отсутствует", "broken": "битый"}


def print_human(data: dict, verbose: bool) -> None:
    print(f"цель: {data['target']} → {data['target_path']}")
    print(f"навыков в репозитории: {data['skills_total']}")
    print(
        f"на месте: {data['ok']}, отсутствует: {data['missing']}, "
        f"битых: {data['broken']}"
    )
    for item in data["host"]["checks"]:
        print(f"хост {data['host']['name']}: [{item['status']}] {item['check']} — {item['detail']}")
    if data["empty"]:
        print("цель пуста: ни одного каталога навыка не найдено")
    if data["rows"] and verbose:
        print()
        print("навык | файл | статус")
        for row in data["rows"]:
            print(f"{row['skill']} | {row['file']} | {STATUS_LABEL[row['status']]}")
    if data["problems"]:
        print()
        print("проблемы (навык | файл | статус):")
        for row in data["problems"]:
            print(
                f"{row['skill']} | {row['file']} | "
                f"{STATUS_LABEL[row['status']]}: {row['detail']}"
            )
    print("итог: OK" if data["passed"] else "итог: ПРОВАЛ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверка установки навыков в каталог выбранного хоста"
    )
    parser.add_argument(
        "--target", required=True, help="имя цели (claude, opencode, codex, …) или путь"
    )
    parser.add_argument(
        "--repo", default=str(REPO), help="корень репозитория с skills/ (по умолчанию — этот)"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="таблица по всем навыкам, а не только проблемы"
    )
    parser.add_argument("--json", action="store_true", help="машинный вывод одним JSON-объектом")
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    try:
        data = collect(args.target, repo)
    except UsageError as error:
        print(f"ошибка: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print_human(data, args.verbose)
    return 0 if data["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
