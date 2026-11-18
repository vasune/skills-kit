#!/usr/bin/env python3
"""Поиск навыка по живой фразе: TF-IDF и косинус из `routing_eval.py`.

    python3 ./scripts/find_skill.py "<фраза>" [--top 5] [--json] [--repo PATH]
    python3 ./scripts/find_skill.py --list [--repo PATH]

Нужен, когда имя навыка неизвестно: человек впервые видит библиотеку или хост не
умеет искать навыки сам. Ранжирует `name` + `description` всех `skills/*/*/SKILL.md`
(имя с весом ×2, RU↔EN алиасы — как в роутинг-эвале). Поиск не гейт: если лучший
score ниже порога, печатает «похожего навыка нет» и ближайшие, код возврата 0.
Код возврата 2 — нет фразы и нет `--list`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from routing_eval import (  # noqa: E402
    REPO,
    STOPWORDS,
    TRIGGER_WORDS,
    build_index,
    load_skills,
    rank,
    stem,
    tokenize,
)

# Ниже порога считаем, что похожего навыка нет: на пилоте корректные фразы дают
# 0.20+, а случайный текст — 0.00. Порог не гейт, а подсказка «уточните фразу».
MIN_SCORE = 0.10
DEFAULT_TOP = 5
DESCRIPTION_WIDTH = 70

# Синонимы слоя поиска: их нет в эвале, потому что там живёт контролируемый
# словарь кейсов, а здесь — живые формулировки человека. Только расширение
# запроса; документы и TF-IDF не меняются.
SEARCH_ALIASES = {
    "автозапуск": "autostart",
    "мак": "macos",
    "макос": "macos",
    "сервис": "service",
    "служб": "service",
    "установк": "install",
    "постав": "install",
}

INDEX_ROW = re.compile(
    r"^\|\s*\[`([^`]+)`\]\(skills/([a-z0-9-]+)/\1/SKILL\.md\)\s*\|\s*(L[12])\s*\|",
    re.M,
)


def load_levels(repo: Path) -> dict[str, str]:
    index = repo / "INDEX.md"
    if not index.is_file():
        return {}
    return {
        name: level
        for name, _group, level in INDEX_ROW.findall(index.read_text(errors="ignore"))
    }


def load_paths(repo: Path) -> dict[str, str]:
    paths: dict[str, str] = {}
    for skill_md in sorted((repo / "skills").glob("*/*/SKILL.md")):
        paths[skill_md.parent.name] = skill_md.relative_to(repo).as_posix()
    return paths


def expand_query(prompt: str) -> str:
    """Схлопывает поисковые синонимы до ранжирования (TF-IDF — в routing_eval)."""
    tokens: list[str] = []
    for raw in tokenize(prompt):
        if raw in STOPWORDS or raw in TRIGGER_WORDS:
            continue
        token = stem(raw)
        tokens.append(SEARCH_ALIASES.get(token, token))
    return " ".join(tokens)


def short_description(description: str, width: int = DESCRIPTION_WIDTH) -> str:
    description = " ".join(description.split())
    if len(description) <= width:
        return description
    return description[: width - 1].rstrip() + "…"


def result_rows(
    ranked: list[tuple[str, float]],
    skills: dict,
    levels: dict[str, str],
    paths: dict[str, str],
) -> list[dict]:
    rows = []
    for name, score in ranked:
        rows.append(
            {
                "name": name,
                "level": levels.get(name, "—"),
                "path": paths.get(name, f"skills/?/{name}/SKILL.md"),
                "score": round(score, 3),
                "description": skills[name].description,
            }
        )
    return rows


def print_table(rows: list[dict]) -> None:
    name_width = max((len(row["name"]) for row in rows), default=len("навык"))
    name_width = max(name_width, len("навык"))
    print(f"{'score':>5}  {'ур.':<3}  {'навык':<{name_width}}  путь")
    for row in rows:
        print(
            f"{row['score']:5.3f}  {row['level']:<3}  "
            f"{row['name']:<{name_width}}  {row['path']}"
        )
        print(f"{'':5}  {'':3}  {short_description(row['description'])}")


def print_list(rows: list[dict]) -> None:
    name_width = max((len(row["name"]) for row in rows), default=len("навык"))
    name_width = max(name_width, len("навык"))
    print(f"{'навык':<{name_width}}  {'ур.':<3}  путь")
    for row in rows:
        print(f"{row['name']:<{name_width}}  {row['level']:<3}  {row['path']}")
    print(f"\nвсего навыков: {len(rows)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Найти навык по фразе: TF-IDF по name + description."
    )
    parser.add_argument("query", nargs="?", help="живая фраза пользователя")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help="сколько навыков показать")
    parser.add_argument("--json", action="store_true", help="машинный вывод: JSON-массив")
    parser.add_argument(
        "--repo",
        type=Path,
        default=REPO,
        help="корень репозитория (по умолчанию — корень этого скрипта)",
    )
    parser.add_argument("--list", action="store_true", help="перечислить все навыки")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    skills, errors = load_skills(repo)
    for error in errors:
        print(f"ошибка: {error}", file=sys.stderr)
    if errors:
        return 1
    levels = load_levels(repo)
    paths = load_paths(repo)

    if args.list:
        rows = result_rows(
            sorted((name, 0.0) for name in skills), skills, levels, paths
        )
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            print_list(rows)
        return 0

    if not args.query or not args.query.strip():
        parser.print_usage(sys.stderr)
        return 2
    if args.top < 1:
        parser.error("--top должен быть ≥ 1")

    index = build_index(skills)
    ranked = rank(index, expand_query(args.query))[: args.top]
    rows = result_rows(ranked, skills, levels, paths)
    best = rows[0]["score"] if rows else 0.0
    found = bool(rows) and best >= MIN_SCORE

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        if not found:
            nearest = rows[: min(args.top, 3)]
            print(
                f"похожего навыка нет (лучший score {best:.3f} < {MIN_SCORE:.2f}); "
                f"ближайшие:"
            )
            print_table(nearest)
        else:
            print_table(rows)
    if not found and args.json:
        # stdout должен остаться валидным JSON; человеку сообщение уже напечатано.
        print(
            f"похожего навыка нет (лучший score {best:.3f} < {MIN_SCORE:.2f})",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
