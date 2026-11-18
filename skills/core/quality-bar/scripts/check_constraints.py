#!/usr/bin/env python3
"""Гард планки проекта: ищет в диффе ходы, которые ослабляют проверки.

    python3 scripts/check_constraints.py              # рабочее дерево против HEAD
    python3 scripts/check_constraints.py --staged     # только проиндексированное
    python3 scripts/check_constraints.py --root PATH  # корень проекта
    python3 scripts/check_constraints.py --self-test  # проверить сам гард

Коды возврата: 0 — чисто, 1 — найдено ослабление или плохой формат файла,
2 — проверить не удалось (нет CONSTRAINTS.md, не git-репозиторий, нет HEAD).
Код 2 никогда не означает «чисто»: молчание проверки — не доказательство.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

CONSTRAINTS = "CONSTRAINTS.md"
DOC_SUFFIXES = (".md", ".txt", ".rst")

SUPPRESSIONS = re.compile(
    r"@ts-ignore|@ts-nocheck|@ts-expect-error|eslint-disable|#\s*noqa"
    r"|#\s*type:\s*ignore|pylint:\s*disable|istanbul\s+ignore|stryker\s+disable"
    r"|nosemgrep|gitleaks:allow|#\s*pragma:\s*no\s*cover|@SuppressWarnings",
    re.I,
)
TEST_SOFTEN = re.compile(
    r"\.(?:skip|only|todo|failing)\s*\(|@pytest\.mark\.(?:skip|xfail)|pytest\.skip\("
    r"|@unittest\.skip|#\[ignore\]|\bt\.Skip\(|@Ignore\b|xit\(|xdescribe\(",
    re.I,
)
STUB = re.compile(
    r"NotImplementedError|NotImplementedException"
    r"|throw new Error\(\s*[\"']Not implemented"
    r"|TODO:\s*implement|FIXME:\s*implement"
    r"|except[^:]*:\s*pass\s*$|catch\s*\([^)]*\)\s*\{\s*\}\s*$",
    re.I,
)
ASSERTION = re.compile(
    r"^\s*(assert\b|self\.assert|assertThat\(|assert_eq!|assertEqual\(|expect\(|require\.)"
)
TEST_FILE = re.compile(
    r"(^|/)(tests?|__tests__|specs?|e2e)/|(^|/)test_[^/]*\.py$"
    r"|(_test|\.test|\.spec|_spec)\.[A-Za-z0-9]+$"
)
DIFF_FILE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
SEPARATOR = re.compile(r":?-{2,}:?")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class Line:
    """Строка диффа: путь от корня репозитория, номер в новой или старой версии."""

    path: str
    number: int
    text: str


@dataclass
class Diff:
    added: list[Line] = field(default_factory=list)
    removed: list[Line] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


@dataclass
class Bar:
    """Разобранный CONSTRAINTS.md: секции, floor, измерения, ратчет, исключения."""

    floor: list[str] = field(default_factory=list)
    metrics: dict[str, tuple[str, str]] = field(default_factory=dict)
    ratchet: dict[str, tuple[str, str]] = field(default_factory=dict)
    exceptions: dict[str, list[str]] = field(default_factory=dict)
    exceptions_header: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)


def git(root: Path, *args: str) -> str | None:
    """Вывод git или None, если команда не выполнилась."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def repo_toplevel(root: Path) -> Path | None:
    out = git(root, "rev-parse", "--show-toplevel")
    return Path(out.strip()) if out else None


def has_head(top: Path) -> bool:
    return git(top, "rev-parse", "--verify", "--quiet", "HEAD") is not None


def parse_diff(text: str) -> Diff:
    diff = Diff()
    path = ""
    old = new = 0
    for raw in text.splitlines():
        match = DIFF_FILE.match(raw)
        if match:
            path = match.group(2)
            continue
        if raw.startswith("deleted file mode"):
            if path:
                diff.deleted.append(path)
            continue
        if raw.startswith("--- ") or raw.startswith("index "):
            continue
        if raw.startswith("+++ b/") or raw.startswith("+++ /dev/null"):
            continue
        match = HUNK.match(raw)
        if match:
            old, new = int(match.group(1)), int(match.group(2))
            continue
        if not path:
            continue
        if raw.startswith("+"):
            diff.added.append(Line(path, new, raw[1:]))
            new += 1
        elif raw.startswith("-"):
            diff.removed.append(Line(path, old, raw[1:]))
            old += 1
    return diff


def untracked_lines(top: Path) -> list[Line]:
    """Неотслеживаемые файлы: git diff их не видит, а ослабление живёт и там."""
    out = git(top, "ls-files", "--others", "--exclude-standard")
    if not out:
        return []
    lines: list[Line] = []
    for rel in out.splitlines():
        path = top / rel
        try:
            if path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        if "\x00" in text:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            lines.append(Line(rel, number, line))
    return lines


def split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    return sections


def find_section(sections: dict[str, list[str]], pattern: str) -> list[str] | None:
    for title, lines in sections.items():
        if re.match(pattern, title.lower()):
            return lines
    return None


def parse_table(lines: list[str]) -> tuple[list[str], list[list[str]]]:
    header: list[str] = []
    rows: list[list[str]] = []
    for line in lines:
        text = line.strip()
        if not text.startswith("|"):
            continue
        cells = [cell.strip() for cell in text.strip("|").split("|")]
        if not header:
            header = cells
            continue
        if cells and all(SEPARATOR.fullmatch(cell) for cell in cells if cell):
            continue
        if any(cells):
            rows.append(cells)
    return header, rows


def column(header: list[str], *needles: str) -> int | None:
    for index, title in enumerate(header):
        lowered = title.lower()
        if any(needle in lowered for needle in needles):
            return index
    return None


def cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index]


def parse_bar(text: str) -> Bar:
    sections = split_sections(text)
    bar = Bar(sections=list(sections))
    floor = find_section(sections, r"^floor\b")
    if floor is not None:
        bar.floor = [
            line.strip() for line in floor if line.strip().startswith(("- ", "* "))
        ]
    measurements = find_section(sections, r"^измерения\b")
    if measurements is not None:
        header, rows = parse_table(measurements)
        check = column(header, "провер")
        for row in rows:
            name = cell(row, 0).strip("`* ").lower()
            if name:
                bar.metrics[name] = (cell(row, 1), cell(row, check))
    ratchet = find_section(sections, r"^измерено\b")
    if ratchet is not None:
        header, rows = parse_table(ratchet)
        for row in rows:
            name = cell(row, 0).strip("`* ").lower()
            if name:
                bar.ratchet[name] = (cell(row, 1), cell(row, 2))
    exceptions = find_section(sections, r"^исключения\b")
    if exceptions is not None:
        header, rows = parse_table(exceptions)
        bar.exceptions_header = header
        for row in rows:
            ident = cell(row, 0).strip("`* ").upper()
            if ident:
                bar.exceptions[ident] = row
    return bar


def check_format(bar: Bar) -> list[str]:
    problems: list[str] = []
    titles = [title.lower() for title in bar.sections]
    required = (
        ("Floor", r"^floor\b"),
        ("Измерения с числами", r"^измерения\b"),
        ("Исключения", r"^исключения\b"),
        ("Как гонять", r"^как гонять\b"),
    )
    for label, pattern in required:
        if not any(re.match(pattern, title) for title in titles):
            problems.append(f"в {CONSTRAINTS} нет раздела «{label}»")
    if not bar.metrics:
        problems.append(f"в {CONSTRAINTS} нет ни одного измерения")
    for name, (_rule, command) in bar.metrics.items():
        if not command.strip():
            problems.append(
                f"у измерения «{name}» нет команды в колонке «Чем проверяется» — "
                f"это аспирация, а не ограничение"
            )
    owner = column(bar.exceptions_header, "владел")
    expiry = column(bar.exceptions_header, "истек", "срок")
    for ident, row in bar.exceptions.items():
        if cell(row, owner).strip(" -—") == "":
            problems.append(f"у исключения «{ident}» нет владельца")
        if cell(row, expiry).strip(" -—") == "":
            problems.append(f"у исключения «{ident}» нет срока")
    return problems


def number(text: str) -> float | None:
    match = NUMBER.search(text)
    return float(match.group(0).replace(",", ".")) if match else None


def show(value: float) -> str:
    return f"{value:g}"


def shorten(text: str, limit: int = 70) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def compare_bars(old: Bar, new: Bar) -> list[str]:
    findings: list[str] = []
    new_floor = {item.lstrip("-* ").strip() for item in new.floor}
    for item in old.floor:
        label = item.lstrip("-* ").strip()
        if label not in new_floor:
            findings.append(
                f"{CONSTRAINTS}: floor ослаблен — убрано правило «{shorten(label)}»"
            )
    for name, (old_rule, old_command) in old.metrics.items():
        if name not in new.metrics:
            findings.append(f"{CONSTRAINTS}: измерение «{name}» убрано")
            continue
        new_rule, new_command = new.metrics[name]
        old_value, new_value = number(old_rule), number(new_rule)
        if old_value is not None and new_value is not None and new_value < old_value:
            findings.append(
                f"{CONSTRAINTS}: порог ослаблен — «{name}», "
                f"было {show(old_value)}, стало {show(new_value)}"
            )
        if old_command.strip() and not new_command.strip():
            findings.append(f"{CONSTRAINTS}: у измерения «{name}» убрана команда проверки")
    for name, (old_today, old_direction) in old.ratchet.items():
        if name not in new.ratchet:
            findings.append(f"{CONSTRAINTS}: ратчет «{name}» убран")
            continue
        new_today, new_direction = new.ratchet[name]
        old_value, new_value = number(old_today), number(new_today)
        falling = "не пад" in (old_direction + " " + new_direction).lower()
        if falling and old_value is not None and new_value is not None:
            if new_value < old_value:
                findings.append(
                    f"{CONSTRAINTS}: ратчет ослаблен — «{name}», "
                    f"было {show(old_value)}, стало {show(new_value)}"
                )
    for ident in sorted(set(new.exceptions) - set(old.exceptions)):
        findings.append(
            f"{CONSTRAINTS}: новое исключение «{ident}» — назвать в отчёте, "
            f"иначе это отмена правила"
        )
    return findings


def scan_diff(diff: Diff) -> list[str]:
    findings: list[str] = []
    for line in diff.added:
        if line.path.endswith(DOC_SUFFIXES):
            continue
        if SUPPRESSIONS.search(line.text):
            findings.append(
                f"{line.path}:{line.number}: новая суппрессия проверки — "
                f"обосновать строкой и записать исключение"
            )
        elif TEST_FILE.search(line.path) and TEST_SOFTEN.search(line.text):
            findings.append(
                f"{line.path}:{line.number}: тест ослаблен — причина в сообщении коммита"
            )
        elif STUB.search(line.text):
            findings.append(
                f"{line.path}:{line.number}: работа недоделана — стаб или глушитель ошибки"
            )
    for line in diff.removed:
        if line.path.endswith(DOC_SUFFIXES):
            continue
        if TEST_FILE.search(line.path) and ASSERTION.match(line.text):
            findings.append(f"{line.path}:{line.number}: из теста удалена проверка")
    for path in diff.deleted:
        if TEST_FILE.search(path):
            findings.append(f"{path}: удалён тест — причина в сообщении коммита")
    return findings


def read_head_file(top: Path, path: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(top).as_posix()
    except ValueError:
        return None
    return git(top, "show", f"HEAD:{rel}")


def diff_command(top: Path, staged: bool) -> str | None:
    args = ["diff", "--unified=0", "--no-color", "--no-ext-diff"]
    args += ["--cached", "HEAD"] if staged else ["HEAD"]
    return git(top, *args)


def run(root: Path, staged: bool, constraints: Path) -> int:
    top = repo_toplevel(root)
    if top is None:
        print("гард планки: каталог не git-репозиторий — дифф проверить нечем (код 2)")
        return 2
    if not has_head(top):
        print("гард планки: в репозитории нет HEAD — сравнивать не с чем (код 2)")
        return 2
    if not constraints.is_file():
        print(f"гард планки: нет {CONSTRAINTS} — планка не записана (код 2)")
        return 2
    bar = parse_bar(constraints.read_text(errors="ignore"))
    findings = check_format(bar)
    if not staged:
        old_text = read_head_file(top, constraints)
        if old_text is not None:
            findings.extend(compare_bars(parse_bar(old_text), bar))
    raw = diff_command(top, staged)
    if raw is None:
        print("гард планки: git diff не выполнился (код 2)")
        return 2
    findings.extend(scan_diff(parse_diff(raw)))
    if not staged:
        findings.extend(scan_diff(Diff(added=untracked_lines(top))))
    mode = "проиндексированное" if staged else "рабочее дерево"
    print(f"гард планки: {CONSTRAINTS}, режим: {mode}")
    for finding in findings:
        print(f"нарушение: {finding}")
    if findings:
        print(f"итог: нарушений {len(findings)} → код 1")
        return 1
    print("итог: ослаблений нет → код 0")
    return 0


CLEAN_CONSTRAINTS = """# Ограничения проекта

## Floor — запреты, всегда

- Новых суппрессий без записи в исключениях.
- Стабов и пустых catch.

## Измерения с числами

| Измерение | Правило | Чем проверяется | Когда гоняется |
|---|---|---|---|
| Типы | ноль ошибок | `tsc --noEmit` | каждое изменение |
| Покрытие изменённых строк | ≥ 80% | `vitest run --coverage` | конец задачи |

## Измерено, но пока не форсится

| Метрика | Сегодня | Направление |
|---|---|---|
| Покрытие проекта | 62,4% | не падать |

## Исключения

| ID | Правило | Путь | Причина | Владелец | Истекает |
|---|---|---|---|---|---|

## Как гонять

- BUILD: `make check-fast`
"""

CLEAN_TEST_FILE = "def test_add():\n    assert 1 + 1 == 2\n"


def write_constraints(repo: Path, text: str) -> None:
    (repo / CONSTRAINTS).write_text(text, encoding="utf-8")


def mutate_clean(repo: Path) -> None:
    return None


def mutate_suppression(repo: Path) -> None:
    path = repo / "src" / "app.ts"
    path.write_text(path.read_text(encoding="utf-8") + "// @ts-ignore\n", encoding="utf-8")


def mutate_test_skip(repo: Path) -> None:
    path = repo / "tests" / "test_app.py"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n\n@pytest.mark.skip\ndef test_legacy():\n    pass\n",
        encoding="utf-8",
    )


def mutate_stub(repo: Path) -> None:
    (repo / "src" / "stub.py").write_text(
        "def todo():\n    raise NotImplementedError\n", encoding="utf-8"
    )


def mutate_threshold(repo: Path) -> None:
    write_constraints(repo, CLEAN_CONSTRAINTS.replace("≥ 80%", "≥ 60%"))


def mutate_exception(repo: Path) -> None:
    text = CLEAN_CONSTRAINTS.replace(
        "|---|---|---|---|---|---|",
        "|---|---|---|---|---|---|\n"
        "| W2 | `no-any` | `src/legacy/**` | переписываем | owner | 2027-01-01 |",
    )
    write_constraints(repo, text)


def mutate_floor_removed(repo: Path) -> None:
    text = CLEAN_CONSTRAINTS.replace("- Стабов и пустых catch.\n", "")
    write_constraints(repo, text)


def mutate_no_command(repo: Path) -> None:
    text = CLEAN_CONSTRAINTS.replace(
        "| Типы | ноль ошибок | `tsc --noEmit` | каждое изменение |",
        "| Типы | ноль ошибок |  | каждое изменение |",
    )
    write_constraints(repo, text)


def mutate_missing_file(repo: Path) -> None:
    (repo / CONSTRAINTS).unlink()


def self_test() -> int:
    checks: list[tuple[str, bool]] = []
    base = Path(tempfile.mkdtemp(prefix="quality-bar-"))
    repo = base / "repo"
    repo.mkdir(parents=True)
    try:
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=False, capture_output=True)
        for key, value in (
            ("user.email", "self-test@example.com"),
            ("user.name", "self-test"),
        ):
            subprocess.run(
                ["git", "-C", str(repo), "config", key, value],
                check=False,
                capture_output=True,
            )
        (repo / "src").mkdir()
        (repo / "tests").mkdir()
        (repo / "src" / "app.ts").write_text(
            "export const add = (a: number, b: number): number => a + b;\n",
            encoding="utf-8",
        )
        (repo / "tests" / "test_app.py").write_text(CLEAN_TEST_FILE, encoding="utf-8")
        write_constraints(repo, CLEAN_CONSTRAINTS)
        subprocess.run(
            ["git", "-C", str(repo), "add", "-A"], check=False, capture_output=True
        )
        first = subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "init"],
            check=False,
            capture_output=True,
        )
        if first.returncode != 0:
            print("self-test: не удалось создать временный репозиторий")
            return 2

        cases = (
            ("чистый контроль", mutate_clean, 0),
            ("новая суппрессия", mutate_suppression, 1),
            ("тест ослаблен", mutate_test_skip, 1),
            ("стаб в новом файле", mutate_stub, 1),
            ("порог снижен", mutate_threshold, 1),
            ("новое исключение", mutate_exception, 1),
            ("floor убран", mutate_floor_removed, 1),
            ("число без команды", mutate_no_command, 1),
            ("нет CONSTRAINTS.md", mutate_missing_file, 2),
            ("чистый контроль после правок", mutate_clean, 0),
        )
        for name, mutate, expected in cases:
            reset_repo(repo)
            mutate(repo)
            code, output = run_cli(repo)
            ok = code == expected
            checks.append((name, ok))
            print(f"{'ok  ' if ok else 'FAIL'} {name}: код {code}, ожидался {expected}")
            if not ok:
                for line in output.splitlines():
                    print(f"     {line}")
        code, _output = run_cli(base)
        checks.append(("не git-репозиторий", code == 2))
        print(f"{'ok  ' if code == 2 else 'FAIL'} не git-репозиторий: код {code}, ожидался 2")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    failed = [name for name, ok in checks if not ok]
    print(f"self-test: {len(checks) - len(failed)}/{len(checks)}")
    if failed:
        print("провалено: " + ", ".join(failed))
        return 1
    return 0


def reset_repo(repo: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "--", "."], check=False, capture_output=True
    )
    out = git(repo, "ls-files", "--others", "--exclude-standard")
    for rel in (out or "").splitlines():
        target = repo / rel
        if target.is_file():
            target.unlink()


def run_cli(root: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Гард планки: ищет в диффе ослабление проверок проекта."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="корень проекта (по умолчанию — текущий каталог)",
    )
    parser.add_argument(
        "--constraints",
        type=Path,
        default=None,
        help=f"путь к {CONSTRAINTS} (по умолчанию — в корне проекта)",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="проверять только проиндексированное (для pre-commit)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="прогнать гард на временном репозитории: пять ослаблений и чистый контроль",
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    root = args.root.resolve()
    constraints = args.constraints or (root / CONSTRAINTS)
    return run(root, args.staged, constraints)


if __name__ == "__main__":
    sys.exit(main())
