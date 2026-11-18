#!/usr/bin/env python3
"""Проверка целостности skills-kit. Запуск: ./scripts/check.py [-v] [--repo PATH]

Проверяет: YAML-frontmatter навыков (allowed-keys, обязательные поля, semver,
kebab-case, дубли ключей), дубли имён и near-дубли description, мусор и пустые
каталоги внутри skills/, имена вспомогательных файлов, линт ролей subagents/,
битые внутренние ссылки, абсолютные пути и секреты, полноту INDEX.md, parity
INDEX↔диск↔README↔subagents, счётчик «Файлов» в INDEX, двусторонность
related_skills, покрытие навыков routing-кейсами, parity манифестов установки.
Код выхода 1 при ошибках.

Правила — чистые функции ниже; CLI только собирает файлы и печатает отчёт.
Пороги и baseline редакционного долга — константами здесь, а не в навыках:
автор навыка не должен сам себе выдавать исключение.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

TEXT_EXT = {".md", ".py", ".sh", ".txt", ".json", ".yaml", ".yml"}

# Мусор, который не должен попадать в репозиторий: каталоги кэшей и их файлы.
JUNK_NAMES = {".DS_Store", "Thumbs.db"}
JUNK_DIRS = {"__pycache__", ".pytest_cache", "node_modules"}
JUNK_SUFFIXES = {".pyc", ".pyo", ".pyd"}

ABS_PATH = re.compile(r"(?<![\w~])/(?:Users|home)/[A-Za-z0-9._-]+")
SECRETS = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

# Контракт frontmatter навыка: поля Agent Skills, всё остальное — ошибка.
ALLOWED_FRONTMATTER_KEYS = frozenset(
    {"name", "description", "version", "author", "license", "platforms", "metadata"}
)
REQUIRED_FRONTMATTER_KEYS = ("name", "description", "version")
KEBAB_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
MAX_DESCRIPTION = 60

# Имена вспомогательных *.md: строчные латинские, цифры, точки, дефисы — так
# ГОСТ-файлы вида references-7.0.5.md остаются легальными. README/SKILL/EXAMPLES
# — конвенциональные имена документов, менять их ради правила не нужно.
AUX_MD_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]*\.md$")
AUX_MD_ALLOW = frozenset({"EXAMPLES.md"})

# Нормализация description для поиска near-дублей: триггер и служебные слова
# дают общий префикс почти всем описаниям, без снятия они искажают Jaccard.
TRIGGER_TOKENS = frozenset(
    {
        "открывать",
        "открывается",
        "открыть",
        "когда",
        "применять",
        "применяется",
        "use",
        "when",
        "using",
        "использовать",
        "используй",
    }
)
STOPWORDS = frozenset(
    {
        "и", "в", "во", "на", "для", "по", "с", "со", "что", "как", "не", "а",
        "из", "при", "это", "или", "о", "об", "от", "до", "у", "к", "же", "ли",
        "то", "нужно", "нужен", "надо", "его", "её", "их", "который", "которая",
        "которые", "если", "чем", "над", "под", "без", "через", "между", "также",
        "уже", "есть",
        "the", "a", "an", "of", "for", "to", "and", "or", "in", "on", "with",
        "use", "using", "this", "that", "it", "is", "are", "be", "by", "as",
        "at", "from", "into", "your", "you",
    }
)
DESCRIPTION_ERROR_JACCARD = 0.85
DESCRIPTION_WARN_JACCARD = 0.60

TRIGGER_PREFIX = re.compile(
    r"^(открывать|открывается|использовать|используй|применять|применяется|use when|use|перед|если|когда)\b",
    re.I,
)
WHEN_SECTION = re.compile(
    r"^#{1,4}\s+(?:когда открывать|when to use|когда применять)\b", re.I | re.M
)
SKILL_LINE_BUDGET = 300
# Жёсткий потолок: весь SKILL.md уезжает в контекст одним куском при загрузке
# навыка, поэтому длинное тело — ошибка, а не предупреждение. Долг закрыт:
# самый большой навык (~22 КБ) ниже порога, остальное живёт в references/.
SKILL_CHARS_MAX = 24000

# Baseline редакционного долга: эти нарушения уже есть у легаси-навыков, поэтому
# не топят гейт, но новые нарушения того же класса ловятся. Список сокращается
# по мере починки навыков; исключение живёт в валидаторе, а не в файле навыка.
# Триггер и раздел «когда открывать» вычищены у всех навыков: наборы пусты, и
# правило действует на каждый навык без исключений.
TRIGGER_BASELINE: frozenset[str] = frozenset()
WHEN_SECTION_BASELINE: frozenset[str] = frozenset()
LINE_BUDGET_BASELINE = frozenset(
    {
        "requesting-code-review",
        "systematic-debugging",
        "test-driven-development",
        "plan",
        "git-naming",
        "github-auth",
        "github-code-review",
        "github-issues",
        "github-pr-workflow",
        "github-repo-management",
    }
)
# Пути относительно skills/: файл лежит в references/, но SKILL.md на него не
# ссылается. Починка — содержательная правка навыка, поэтому пока baseline.
REFERENCE_ORPHAN_BASELINE = frozenset(
    {
        "git/github-pr-workflow/references/ci-troubleshooting.md",
        "git/github-pr-workflow/references/conventional-commits.md",
        "git/github-repo-management/references/github-api-cheatsheet.md",
    }
)

INDEX_SUMMARY = re.compile(
    r"Всего навыков:\s*\*\*(\d+)\*\*\s*[—–-]\s*L1:\s*\*\*(\d+)\*\*\s*,\s*L2:\s*\*\*(\d+)\*\*"
)
INDEX_ROW = re.compile(
    r"^\|\s*\[`([^`]+)`\]\(skills/([a-z0-9-]+)/\1/SKILL\.md\)\s*\|\s*(L[12])\s*\|",
    re.M,
)
# Та же строка с колонкой «Файлов»: число в последней ячейке. Ячейка «когда
# открывать» не содержит `|`, иначе строка не должна считаться строкой навыка.
INDEX_ROW_FILES = re.compile(
    r"^\|\s*\[`([^`]+)`\]\(skills/([a-z0-9-]+)/\1/SKILL\.md\)\s*\|"
    r"\s*L[12]\s*\|[^|\n]*\|\s*(\d+)\s*\|\s*$",
    re.M,
)
README_GROUP = re.compile(r"^│\s+[├└]── ([a-z0-9-]+)/\s", re.M)
ROLE_TABLE_ROW = re.compile(
    r"^\|\s*\[`([a-z0-9-]+)\.md`\]\(([a-z0-9-]+)\.md\)", re.M
)
LINK_TARGET = re.compile(r"\]\(([^)#:]+)\)")
RELATED_SKILLS = re.compile(r"related_skills:\s*\[(.*?)\]", re.S)

ROLE_REQUIRED_SECTIONS = (
    ("Что делает", re.compile(r"\bчто делает\b")),
    ("Что дать в `context`", re.compile(r"\bчто дать в context\b")),
    ("Формат ответа", re.compile(r"\bформат ответа\b")),
    ("Чего не делает", re.compile(r"\bчего не делает\b")),
)

# Манифесты установки: корневой — эталон версии, остальные обязаны совпадать.
# Правило применяется только при наличии корневого plugin.json: дерево без
# упаковки (временное, тестовое) остаётся зелёным.
ROOT_MANIFEST = "plugin.json"
OTHER_MANIFESTS = (
    "package.json",
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    ".codex-plugin/plugin.json",
    ".agents/plugins/marketplace.json",
)
MARKETPLACE_MANIFESTS = frozenset(
    {".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"}
)


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skills: int = 0
    baseline: Counter[str] = field(default_factory=Counter)
    baseline_items: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)


# --- frontmatter -----------------------------------------------------------


def split_frontmatter(text: str) -> tuple[list[str] | None, str]:
    """Строки YAML-блока и тело документа; (None, text), если блока нет."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1 :])
    return None, text


def _unquote(value: str) -> tuple[str, str | None]:
    """Снимает кавычки и проверяет простую YAML-строгость значения."""
    if not value:
        return "", None
    quote = value[0]
    if quote in "\"'":
        if len(value) < 2 or not value.endswith(quote):
            return value, "незакрытая кавычка"
        return value[1:-1], None
    if ": " in value:
        return value, "двоеточие с пробелом в значении без кавычек"
    return value, None


def parse_frontmatter(
    text: str,
    allowed_keys: frozenset[str] | None = None,
    strict_values: bool = True,
) -> tuple[dict[str, str], list[str]]:
    """Разбирает top-level YAML навыка и возвращает (meta, ошибки).

    strict_values — контракт навыка (кавычки, двоеточие в значении); у ролей
    проверяются только структура, дубли и name, чтобы линт не переписывал их
    frontmatter.
    """
    lines, _ = split_frontmatter(text)
    if lines is None:
        return {}, ["нет YAML-frontmatter"]
    meta: dict[str, str] = {}
    errors: list[str] = []
    for raw in lines:
        if "\t" in raw:
            errors.append("таб в YAML-frontmatter (нужны пробелы)")
            continue
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith((" ", "-")):
            continue  # вложенный mapping или список
        if ":" not in raw:
            errors.append(f"строка YAML без key: value — {raw.strip()!r}")
            continue
        key, value = raw.split(":", 1)
        key, value = key.strip(), value.strip()
        if not key:
            errors.append("пустой ключ в YAML-frontmatter")
            continue
        if key in meta:
            errors.append(f"дубль ключа {key} в YAML-frontmatter")
            continue
        if allowed_keys is not None and key not in allowed_keys:
            errors.append(f"недопустимый ключ frontmatter: {key}")
        if strict_values:
            cleaned, quote_error = _unquote(value)
            if quote_error:
                errors.append(f"{key}: {quote_error}")
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            cleaned = value[1:-1]
        else:
            cleaned = value
        meta[key] = cleaned
    return meta, errors


def check_skill_frontmatter(
    rel: str, dirname: str, text: str
) -> tuple[dict[str, str], list[str]]:
    """Правила frontmatter одного навыка; rel — путь относительно skills/."""
    meta, raw_errors = parse_frontmatter(text, ALLOWED_FRONTMATTER_KEYS)
    errors = [f"{rel}: {error}" for error in raw_errors]
    if not meta:
        return meta, errors
    for key in REQUIRED_FRONTMATTER_KEYS:
        if not meta.get(key):
            errors.append(f"{rel}: пустое обязательное поле {key}")
    name = meta.get("name", "")
    if name:
        if not KEBAB_NAME.match(name):
            errors.append(f"{rel}: name={name} не kebab-case")
        if name != dirname:
            errors.append(f"{rel}: name={name} не совпадает с каталогом {dirname}")
    version = meta.get("version", "")
    if version and not SEMVER.match(version):
        errors.append(f"{rel}: version={version} не semver (нужно x.y.z)")
    description = meta.get("description", "")
    if description and len(description) > MAX_DESCRIPTION:
        errors.append(
            f"{rel}: description длиннее {MAX_DESCRIPTION} символов "
            f"({len(description)}) — он уходит в системный промпт"
        )
    return meta, errors


# --- description -----------------------------------------------------------


def description_tokens(description: str) -> set[str]:
    text = description.strip().strip("\"'").lower().replace("ё", "е")
    tokens = re.findall(r"[a-zа-я0-9]+", text)
    return {
        token
        for token in tokens
        if token not in TRIGGER_TOKENS
        and token not in STOPWORDS
        and len(token) >= 3
    }


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def description_collisions(
    descriptions: dict[str, str],
) -> tuple[list[str], list[str]]:
    """(ошибки near-дублей, предупреждения) по нормализованным токенам."""
    errors: list[str] = []
    warnings: list[str] = []
    tokens = {name: description_tokens(desc) for name, desc in descriptions.items()}
    for left, right in combinations(sorted(tokens), 2):
        score = jaccard(tokens[left], tokens[right])
        if score >= DESCRIPTION_ERROR_JACCARD:
            errors.append(
                f"{left} и {right}: description почти дублируются "
                f"(Jaccard {score:.2f}) — развести триггеры"
            )
        elif score >= DESCRIPTION_WARN_JACCARD:
            warnings.append(
                f"{left} и {right}: description похожи (Jaccard {score:.2f})"
            )
    return errors, warnings


def trigger_warning(rel: str, description: str) -> str | None:
    if TRIGGER_PREFIX.match(description.strip().strip("\"'")):
        return None
    first = description.strip().strip("\"'").split()
    return (
        f"{rel}: description не начинается с триггера "
        f"(«{first[0] if first else ''}») — агент не поймёт, когда открывать"
    )


# --- файлы и ссылки --------------------------------------------------------


def text_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in TEXT_EXT:
            yield path


def strip_code(text: str) -> str:
    """Текст без блоков и inline-кода: синтаксис примеров — не ссылка и не путь."""
    return re.sub(r"`[^`]*`", "", re.sub(r"```.*?```", "", text, flags=re.S))


def hygiene_errors(rel: str, text: str) -> list[str]:
    errors: list[str] = []
    for match in ABS_PATH.finditer(strip_code(text)):
        errors.append(f"{rel}: абсолютный путь {match.group(0)}")
    # секреты сканируем по всему тексту: ключ, вставленный в пример, остаётся ключом.
    for pattern in SECRETS:
        if pattern.search(text):
            errors.append(f"{rel}: похоже на секрет ({pattern.pattern[:24]}…)")
    return errors


def broken_link_errors(rel: str, path: Path, text: str) -> list[str]:
    errors: list[str] = []
    prose = strip_code(text)
    for target in LINK_TARGET.findall(prose):
        if target.startswith(("http", "mailto", "MEDIA")):
            continue
        if not (path.parent / target).resolve().exists():
            errors.append(f"{rel}: битая ссылка {target}")
    return errors


def junk_errors(repo: Path, skills: Path) -> list[str]:
    errors: list[str] = []
    for dirpath, dirnames, filenames in os.walk(skills):
        root = Path(dirpath)
        for name in sorted(dirnames):
            if name in JUNK_DIRS:
                path = root / name
                errors.append(f"{path.relative_to(repo)}: мусорный каталог {name}/")
        dirnames[:] = [name for name in dirnames if name not in JUNK_DIRS]
        for name in sorted(filenames):
            path = root / name
            if name in JUNK_NAMES or path.suffix in JUNK_SUFFIXES:
                errors.append(f"{path.relative_to(repo)}: мусорный файл")
    return errors


def empty_dir_errors(repo: Path, skills: Path) -> list[str]:
    errors: list[str] = []
    for dirpath, dirnames, filenames in os.walk(skills):
        path = Path(dirpath)
        if path == skills or path.name in JUNK_DIRS:
            continue
        if not dirnames and not filenames:
            errors.append(f"{path.relative_to(repo)}: пустой каталог")
    return errors


def aux_name_errors(repo: Path, skills: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted(skills.rglob("*.md")):
        if path.name in ("SKILL.md", *AUX_MD_ALLOW):
            continue
        if not AUX_MD_NAME.match(path.name):
            errors.append(
                f"{path.relative_to(repo)}: имя вспомогательного файла "
                f"{path.name} — строчные латинские, цифры, точки, дефисы"
            )
    return errors


# --- роли subagents --------------------------------------------------------


def role_headings(text: str) -> list[str]:
    """Заголовки ## вне блоков кода: в шаблонах ответа тоже бывают `## ...`."""
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    headings = re.findall(r"^##\s+(.+?)\s*$", prose, re.M)
    return [re.sub(r"[`*_]+", "", heading).strip().lower() for heading in headings]


def check_role(rel: str, stem: str, text: str) -> list[str]:
    """Контракт роли: name==файл, обязательные разделы, Composition последним."""
    meta, raw_errors = parse_frontmatter(text, strict_values=False)
    errors = [f"{rel}: {error}" for error in raw_errors]
    if meta:
        name = meta.get("name", "")
        if not name:
            errors.append(f"{rel}: пустое поле name")
        elif name != stem:
            errors.append(f"{rel}: name={name} не совпадает с файлом {stem}.md")
    headings = role_headings(text)
    for label, pattern in ROLE_REQUIRED_SECTIONS:
        if not any(pattern.search(heading) for heading in headings):
            errors.append(f"{rel}: нет раздела «{label}»")
    if not any(heading.startswith("composition") for heading in headings):
        errors.append(f"{rel}: нет раздела «Composition»")
    elif not headings[-1].startswith("composition"):
        errors.append(f"{rel}: «Composition» должен быть последним разделом")
    return errors


# --- INDEX / README / roles parity ----------------------------------------


def parity_errors(
    repo: Path,
    skill_names: set[str],
    index_text: str,
    readme_text: str,
    role_readme: str,
    role_names: set[str],
) -> list[str]:
    errors: list[str] = []
    summary = INDEX_SUMMARY.search(index_text)
    if not summary:
        errors.append("INDEX.md: нет итоговой строки «Всего навыков: N — L1: M, L2: K»")
    else:
        total, l1, l2 = (int(value) for value in summary.groups())
        if total != len(skill_names):
            errors.append(f"INDEX.md: всего {total}, а навыков на диске {len(skill_names)}")
        if l1 + l2 != total:
            errors.append(f"INDEX.md: L1 {l1} + L2 {l2} ≠ всего {total}")
        rows = INDEX_ROW.findall(index_text)
        actual_l1 = sum(1 for _, _, level in rows if level == "L1")
        actual_l2 = sum(1 for _, _, level in rows if level == "L2")
        if (actual_l1, actual_l2) != (l1, l2):
            errors.append(
                f"INDEX.md: в строке L1 {l1}/L2 {l2}, а в таблице "
                f"L1 {actual_l1}/L2 {actual_l2}"
            )

    actual_groups = sorted(
        path.name for path in (repo / "skills").iterdir() if path.is_dir()
    )
    readme_groups = sorted(set(README_GROUP.findall(readme_text)))
    for group in sorted(set(actual_groups) - set(readme_groups)):
        errors.append(f"README.md: группа {group}/ есть на диске, но нет в дереве")
    for group in sorted(set(readme_groups) - set(actual_groups)):
        errors.append(f"README.md: в дереве группа {group}/, а каталога нет")

    table_roles = {
        name for name, target in ROLE_TABLE_ROW.findall(role_readme) if name == target
    }
    for name in sorted(role_names - table_roles):
        errors.append(f"subagents/README.md: роль {name}.md не описана в таблице")
    for name in sorted(table_roles - role_names):
        errors.append(f"subagents/README.md: строка про {name}.md, а файла нет")
    return errors


# --- INDEX: колонка «Файлов» -----------------------------------------------


def plural(count: int, one: str, few: str, many: str) -> str:
    """Русская форма слова при числе: 1 пара, 2 пары, 5 пар."""
    if count % 10 == 1 and count % 100 != 11:
        return one
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return few
    return many


def skill_file_count(skill_dir: Path) -> int:
    """Файлы навыка рекурсивно, без мусора: ровно то, что едет при установке.

    Считаются SKILL.md, `references/`, `scripts/`, `templates/` и любые другие
    файлы каталога; кэши, `.pyc` и `.DS_Store` — нет, иначе счётчик в INDEX
    начнёт зависеть от локальных прогонов.
    """
    total = 0
    for path in skill_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.name in JUNK_NAMES or path.suffix in JUNK_SUFFIXES:
            continue
        if any(part in JUNK_DIRS for part in path.parts):
            continue
        total += 1
    return total


def file_count_errors(index_text: str, skill_dirs: dict[str, Path]) -> list[str]:
    """Число в колонке «Файлов» должно равняться фактическому числу файлов."""
    errors: list[str] = []
    counts = {
        match.group(1): int(match.group(3))
        for match in INDEX_ROW_FILES.finditer(index_text)
    }
    listed = {name for name, _, _ in INDEX_ROW.findall(index_text)}
    for name in sorted(listed - set(counts)):
        if name in skill_dirs:
            errors.append(
                f"INDEX.md: {name}: в колонке «Файлов» не число — "
                f"фактически {skill_file_count(skill_dirs[name])}"
            )
    for name, declared in sorted(counts.items()):
        if name not in skill_dirs:
            continue  # строка про несуществующий навык — отдельная ошибка
        actual = skill_file_count(skill_dirs[name])
        if actual != declared:
            errors.append(
                f"INDEX.md: {name}: в колонке «Файлов» {declared}, "
                f"фактически {actual}"
            )
    return errors


# --- related_skills и routing-кейсы ---------------------------------------


def one_way_related_pairs(
    related: dict[str, set[str]],
) -> list[tuple[str, str]]:
    """Пары A→B, где B существует, но не ссылается на A.

    Ссылки на себя и на несуществующие навыки не считаются: первая бессмысленна,
    вторая уже ошибка (не дублируем её предупреждением).
    """
    pairs: list[tuple[str, str]] = []
    for name, refs in related.items():
        for ref in refs:
            if ref == name or ref not in related:
                continue
            if name not in related[ref]:
                pairs.append((name, ref))
    return sorted(pairs)


def routing_coverage(repo: Path, skill_names: set[str], report: Report) -> None:
    """Сколько навыков без `evals/routing/<skill>.json` — одной сводкой."""
    cases_dir = repo / "evals" / "routing"
    covered = (
        {path.stem for path in cases_dir.glob("*.json") if path.is_file()}
        if cases_dir.is_dir()
        else set()
    )
    missing = sorted(skill_names - covered)
    if not missing:
        return
    report.notes.append(
        f"routing-кейсов нет: {len(missing)} (из {len(skill_names)})"
    )
    report.baseline_items.extend(
        f"routing-кейс отсутствует: {name}" for name in missing
    )


# --- манифесты установки ---------------------------------------------------


def load_manifest(path: Path) -> tuple[dict | None, str | None]:
    """(данные, ошибка): JSON-объект манифеста или причина, почему его нет."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        return None, f"не читается: {error}"
    except json.JSONDecodeError as error:
        return None, f"битый JSON: {error.msg} (строка {error.lineno})"
    if not isinstance(data, dict):
        return None, "на верхнем уровне ожидается JSON-объект"
    return data, None


def manifest_version(data: dict, rel: str) -> str | None:
    """Версия манифеста: поле version или plugins[0].version у marketplace."""
    if rel in MARKETPLACE_MANIFESTS:
        plugins = data.get("plugins")
        if isinstance(plugins, list) and plugins and isinstance(plugins[0], dict):
            version = plugins[0].get("version")
            return version if isinstance(version, str) else None
        return None
    version = data.get("version")
    return version if isinstance(version, str) else None


def manifest_skill_targets(data: dict) -> list[str]:
    """Поле skills: каталоги навыков, которые обещает манифест."""
    skills = data.get("skills")
    if isinstance(skills, str):
        return [skills]
    if isinstance(skills, list):
        return [item for item in skills if isinstance(item, str)]
    return []


def manifest_plugin_roots(data: dict, rel: str) -> list[str]:
    """source.path: корень плагина (в marketplace — plugins[0].source.path)."""
    targets: list[str] = []
    source = data.get("source")
    if isinstance(source, dict) and isinstance(source.get("path"), str):
        targets.append(source["path"])
    if rel in MARKETPLACE_MANIFESTS:
        plugins = data.get("plugins")
        if isinstance(plugins, list) and plugins and isinstance(plugins[0], dict):
            plugin_source = plugins[0].get("source")
            if isinstance(plugin_source, dict) and isinstance(
                plugin_source.get("path"), str
            ):
                targets.append(plugin_source["path"])
    return targets


def resolve_manifest_path(repo: Path, raw: str) -> tuple[Path | None, str | None]:
    """Относительный путь манифеста от корня репозитория; `./` — это корень."""
    if Path(raw).is_absolute():
        return None, f"путь {raw!r} — абсолютный, нужен относительный"
    normalized = raw.strip().removeprefix("./").rstrip("/") or "."
    return repo / normalized, None


def manifest_path_errors(repo: Path, rel: str, data: dict) -> list[str]:
    """Пути манифеста должны существовать и быть тем, чем названы.

    `skills` — каталог навыков: в нём есть хотя бы один `SKILL.md` (раскладка
    групповая, поэтому рекурсивно). `source.path` — корень плагина: каталог
    существует, и внутри него есть `plugin.json` или `skills/`; `./` легален.
    """
    errors: list[str] = []
    for raw in manifest_skill_targets(data):
        target, problem = resolve_manifest_path(repo, raw)
        if problem or target is None:
            errors.append(f"{rel}: {problem}")
            continue
        if not target.is_dir():
            errors.append(f"{rel}: путь к навыкам {raw!r} не существует")
        elif not any(target.rglob("SKILL.md")):
            errors.append(f"{rel}: в каталоге навыков {raw!r} нет ни одного SKILL.md")
    for raw in manifest_plugin_roots(data, rel):
        target, problem = resolve_manifest_path(repo, raw)
        if problem or target is None:
            errors.append(f"{rel}: {problem}")
            continue
        if not target.is_dir():
            errors.append(f"{rel}: путь плагина {raw!r} не существует")
        elif not (target / "plugin.json").is_file() and not (target / "skills").is_dir():
            errors.append(
                f"{rel}: в каталоге плагина {raw!r} нет ни plugin.json, ни skills/"
            )
    return errors


def manifest_errors(repo: Path) -> list[str]:
    """Parity манифестов: версии равны корневому plugin.json, пути живые.

    Без корневого манифеста правило не применяется — так временное дерево без
    упаковки остаётся зелёным, а ошибка появляется только вместе с эталоном.
    """
    root_path = repo / ROOT_MANIFEST
    if not root_path.is_file():
        return []
    root, load_error = load_manifest(root_path)
    if root is None:
        return [f"{ROOT_MANIFEST}: {load_error}"]
    errors: list[str] = []
    name = root.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{ROOT_MANIFEST}: пустое поле name")
    root_version = manifest_version(root, ROOT_MANIFEST)
    if not root_version:
        errors.append(f"{ROOT_MANIFEST}: пустое поле version")
    elif not SEMVER.match(root_version):
        errors.append(f"{ROOT_MANIFEST}: version={root_version} не semver (нужно x.y.z)")
    errors.extend(manifest_path_errors(repo, ROOT_MANIFEST, root))
    if not root_version:
        return errors  # без эталонной версии сравнивать не с чем
    for rel in OTHER_MANIFESTS:
        path = repo / rel
        if not path.is_file():
            continue
        data, sibling_error = load_manifest(path)
        if data is None:
            errors.append(f"{rel}: {sibling_error}")
            continue
        version = manifest_version(data, rel)
        if not version:
            errors.append(f"{rel}: нет версии (version или plugins[0].version)")
        elif version != root_version:
            errors.append(
                f"{rel}: version={version}, а в {ROOT_MANIFEST} {root_version}"
            )
        errors.extend(manifest_path_errors(repo, rel, data))
    return errors


def dsh_bundle_errors(repo: Path) -> list[str]:
    """Связка пакета DeepSeek Harness: пакет → патч → модуль рядом с патчем.

    Без DSH-пакета правило не применяется: дерево без бандла (временное,
    тестовое) остаётся зелёным. Проверяется то, что DSH читает при установке:
    `dsh.bundle.patch` в package.json, существование патча и каждого модуля,
    который патч подключает относительным путём.
    """
    package_path = repo / "package.json"
    if not package_path.is_file():
        return []
    data, problem = load_manifest(package_path)
    if data is None:
        return [f"package.json: {problem}"]
    patch_raw = None
    bundle = data.get("dsh")
    if isinstance(bundle, dict):
        declaration = bundle.get("bundle")
        if isinstance(declaration, dict) and isinstance(declaration.get("patch"), str):
            patch_raw = declaration["patch"]
    if not patch_raw:
        # package.json бывает и не для DSH; правило включается, когда рядом
        # лежит патч бандла — значит пакет задуман как DSH-бандл.
        if (repo / "cordis.patch.yml").is_file():
            return [
                "package.json: нет dsh.bundle.patch, а cordis.patch.yml есть — "
                "DSH не увидит пакет как бандл"
            ]
        return []
    if Path(patch_raw).is_absolute():
        return [f"package.json: dsh.bundle.patch={patch_raw!r} — абсолютный путь"]
    patch_path = repo / patch_raw.removeprefix("./")
    if not patch_path.is_file():
        return [f"package.json: dsh.bundle.patch={patch_raw!r} не существует"]
    text = patch_path.read_text(encoding="utf-8")
    modules = re.findall(r"^\s*name:\s*['\"]?(\./[^'\"\s]+)", text, re.MULTILINE)
    if not modules:
        return [
            f"{patch_raw}: ни одна строка не подключает модуль рядом с патчем"
        ]
    errors: list[str] = []
    for module in dict.fromkeys(modules):
        if not (patch_path.parent / module).is_file():
            errors.append(f"{patch_raw}: модуль {module!r} не существует")
    return errors


# --- редакционные предупреждения ------------------------------------------


def budget_warnings(
    rel: str, name: str, text: str, report: Report
) -> None:
    chars = len(text)
    if chars > SKILL_CHARS_MAX:
        report.errors.append(
            f"{rel}: SKILL.md {chars} символов (> {SKILL_CHARS_MAX}) — "
            f"разнести в references/: тело навыка читается в контекст целиком"
        )
        return
    lines = len(text.splitlines())
    if lines <= SKILL_LINE_BUDGET:
        return
    if name in LINE_BUDGET_BASELINE:
        report.baseline["SKILL.md >300 строк"] += 1
        report.baseline_items.append(f"SKILL.md >300: {name} ({lines} строк)")
        return
    report.warnings.append(
        f"{rel}: SKILL.md {lines} строк (> {SKILL_LINE_BUDGET}) — разрезать в references/"
    )


def reference_orphans(
    repo: Path, skill_dir: Path, text: str, report: Report
) -> None:
    references = skill_dir / "references"
    if not references.is_dir():
        return
    for path in sorted(references.rglob("*.md")):
        rel_in_skill = path.relative_to(skill_dir).as_posix()
        # Достаточно ссылки на файл или на его подкаталог: `references/dissertation/`
        # покрывает все файлы внутри. Голое `references/` не считается — иначе
        # упоминание любого файла делало бы достижимым весь каталог.
        parents = {
            parent.relative_to(skill_dir).as_posix() + "/"
            for parent in path.parents
            if parent != skill_dir
            and parent != references
            and references in parent.parents
        }
        reachable = path.name in text or rel_in_skill in text
        reachable = reachable or any(parent in text for parent in parents)
        if reachable:
            continue
        rel = path.relative_to(repo).as_posix()
        if rel.removeprefix("skills/") in REFERENCE_ORPHAN_BASELINE:
            report.baseline["недостижимых references"] += 1
            report.baseline_items.append(f"orphan reference: {rel}")
            continue
        report.warnings.append(f"{rel}: {rel_in_skill} недостижим из SKILL.md")


# --- сборка отчёта ---------------------------------------------------------


def run(repo: Path = REPO) -> Report:
    report = Report()
    skills = repo / "skills"
    if not skills.is_dir():
        report.errors.append("нет каталога skills/")
        return report
    readme = repo / "README.md"
    index = repo / "INDEX.md"
    subagents = repo / "subagents"

    skill_dirs: list[tuple[Path, Path]] = []
    skill_names: dict[str, Path] = {}
    for skill_md in sorted(skills.rglob("SKILL.md")):
        skill_dir = skill_md.parent
        rel = skill_dir.relative_to(skills)
        if len(rel.parts) != 2:
            report.errors.append(
                f"{rel}: навык должен лежать в skills/<группа>/<навык>/"
            )
            continue
        name = skill_dir.name
        if name in skill_names:
            report.errors.append(
                f"дубль имени навыка: {name} ({skill_names[name]} и {skill_dir})"
            )
        skill_names[name] = skill_dir
        skill_dirs.append((rel, skill_md))
    report.skills = len(skill_names)

    descriptions: dict[str, str] = {}
    related_map: dict[str, set[str]] = {}
    for rel, skill_md in skill_dirs:
        name = skill_md.parent.name
        text = skill_md.read_text(encoding="utf-8", errors="ignore")
        meta, errors = check_skill_frontmatter(rel.as_posix(), name, text)
        report.errors.extend(errors)
        if not meta:
            continue
        description = meta.get("description", "")
        if description:
            descriptions[name] = description
        related_map[name] = set()
        related = RELATED_SKILLS.search(text)
        if related:
            for ref in related.group(1).split(","):
                ref = ref.strip().strip("\"'")
                if not ref:
                    continue
                if ref not in skill_names:
                    report.errors.append(
                        f"{rel}: related_skills ссылается на {ref}, которого нет"
                    )
                elif ref != name:
                    related_map[name].add(ref)
        budget_warnings(rel.as_posix(), name, text, report)
        reference_orphans(repo, skill_md.parent, text, report)
        if description:
            if name in TRIGGER_BASELINE:
                report.baseline["description без триггера"] += 1
                report.baseline_items.append(f"description без триггера: {name}")
            else:
                warning = trigger_warning(rel.as_posix(), description)
                if warning:
                    report.warnings.append(warning)
        if not WHEN_SECTION.search(strip_code(text)):
            if name in WHEN_SECTION_BASELINE:
                report.baseline["без раздела «когда»"] += 1
                report.baseline_items.append(f"без раздела «когда»: {name}")
            else:
                report.warnings.append(
                    f"{rel}: нет раздела «Когда открывать»/«When to Use»/"
                    f"«Когда применять»"
                )

    collision_errors, collision_warnings = description_collisions(descriptions)
    report.errors.extend(collision_errors)
    report.warnings.extend(collision_warnings)

    # Односторонние related_skills — не ошибка: связь бывает иерархической
    # (A зависит от B, B про A не знает) и обратная ссылка не обязана
    # существовать. Поэтому это справка в сводке, а не предупреждение; полный
    # список пар — в `-v`, чтобы не печатать простыню каждый прогон.
    one_way = one_way_related_pairs(related_map)
    if one_way:
        report.notes.append(
            f"related_skills: односторонних ссылок {len(one_way)} "
            f"(норма; список — с -v)"
        )
        report.details.extend(
            f"related_skills: {a} → {b}, обратной ссылки нет" for a, b in one_way
        )

    # Тексты: paths, secrets, links. subagents/ проверяется тем же правилом.
    paths = list(text_files(skills))
    if readme.is_file():
        paths.append(readme)
    if index.is_file():
        paths.append(index)
    if subagents.is_dir():
        paths.extend(sorted(subagents.rglob("*.md")))
    for path in paths:
        if not path.is_file():
            continue
        rel = path.relative_to(repo)
        text = path.read_text(encoding="utf-8", errors="ignore")
        report.errors.extend(hygiene_errors(rel.as_posix(), text))
        if path.suffix == ".md":
            report.errors.extend(broken_link_errors(rel.as_posix(), path, text))

    report.errors.extend(junk_errors(repo, skills))
    report.errors.extend(empty_dir_errors(repo, skills))
    report.errors.extend(aux_name_errors(repo, skills))

    roles: list[Path] = []
    if not subagents.is_dir():
        report.errors.append("нет каталога subagents/")
    else:
        roles = sorted(path for path in subagents.glob("*.md") if path.name != "README.md")
        for path in roles:
            report.errors.extend(
                check_role(
                    path.relative_to(repo).as_posix(),
                    path.stem,
                    path.read_text(encoding="utf-8", errors="ignore"),
                )
            )
    role_readme = subagents / "README.md"
    if not role_readme.is_file():
        report.errors.append("нет subagents/README.md")
    role_names = {path.stem for path in roles}

    if not readme.is_file():
        report.errors.append("нет README.md")
    if not index.is_file():
        report.errors.append("нет INDEX.md")
    else:
        index_text = index.read_text(encoding="utf-8", errors="ignore")
        named = set(
            re.findall(r"\]\(skills/[a-z-]+/([a-z0-9-]+)/SKILL\.md\)", index_text)
        )
        for name in sorted(set(skill_names) - named):
            report.errors.append(f"INDEX.md: навык {name} не описан в каталоге")
        for name in sorted(named - set(skill_names)):
            report.errors.append(f"INDEX.md: строка про {name}, а навыка нет")
        for target in re.findall(
            r"\]\(((?:skills|docs|subagents)/[^)#]+)\)", index_text
        ):
            if not (repo / target).exists():
                report.errors.append(f"INDEX.md: битая ссылка {target}")
        report.errors.extend(file_count_errors(index_text, skill_names))
        if readme.is_file() and role_readme.is_file():
            report.errors.extend(
                parity_errors(
                    repo,
                    set(skill_names),
                    index_text,
                    readme.read_text(encoding="utf-8", errors="ignore"),
                    role_readme.read_text(encoding="utf-8", errors="ignore"),
                    role_names,
                )
            )
    routing_coverage(repo, set(skill_names), report)
    report.errors.extend(manifest_errors(repo))
    report.errors.extend(dsh_bundle_errors(repo))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo",
        type=Path,
        default=REPO,
        help="корень репозитория (по умолчанию — корень этого скрипта)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="показать baseline-нарушения, которые не считаются предупреждениями",
    )
    args = parser.parse_args(argv)
    report = run(args.repo.resolve())

    for warning in report.warnings:
        print(f"предупреждение: {warning}")
    for error in report.errors:
        print(f"ошибка: {error}")
    for note in report.notes:
        print(f"baseline: {note}")
    if report.baseline:
        summary = ", ".join(
            f"{label}: {count}" for label, count in sorted(report.baseline.items())
        )
        print(f"baseline (не входит в предупреждения): {summary}")
    if args.verbose:
        for item in report.baseline_items:
            print(f"  baseline: {item}")
        for item in report.details:
            print(f"  детали: {item}")
    print(
        f"\nнавыков: {report.skills}, ошибок: {len(report.errors)}, "
        f"предупреждений: {len(report.warnings)}"
    )
    if not report.errors:
        print("проверка пройдена")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
