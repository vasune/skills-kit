#!/usr/bin/env python3
"""Язык навыков: доля русского и английские фрагменты в прозе.

    ./scripts/lang_check.py                 # все навыки
    ./scripts/lang_check.py skills/core/plan [файл …]

Правило репозитория: если в навыке есть русский, весь навык — на русском; навык
без русского остаётся английским. Скрипт показывает, где осталась английская
проза: серии из RUN_WORDS латинских слов подряд вне кода и вне ссылок. Имена,
термины и команды короче серии не считаются (git, PR, frontmatter, TanStack
Query — это не проза).

Строка с маркером `<!-- lang: allow -->` не проверяется: так помечают цитаты
внешних источников, списки имён и термины, которые переводить нельзя.

Код возврата 1, если в навыке с русским остались английские серии.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"

RUN_WORDS = 5  # сколько латинских слов подряд считается английской прозой
ALLOW = "lang: allow"  # маркер строки: цитата, имена, термин — не проза
RUSSIAN_SHARE = 5  # % русских слов, при котором навык считается русским

LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
CYR_WORD = re.compile(r"[А-Яа-яЁё][А-Яа-яЁё'’-]*")
CODE_FENCE = re.compile(r"^```")
INLINE_CODE = re.compile(r"`[^`]*`")
URL = re.compile(r"https?://\S+|\[[^\]]*\]\([^)]*\)|\[\[[^\]]*\]\]")


def strip_noise(line: str) -> str:
    line = INLINE_CODE.sub(" ", line)
    line = URL.sub(" ", line)
    return line


def analyse(path: Path) -> tuple[int, list[tuple[int, str]], bool]:
    text = path.read_text(encoding="utf-8")
    in_code = False
    in_front = text.startswith("---")
    description_is_english = False
    latin = cyr = 0
    runs: list[tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        if in_front:
            if number > 1 and raw.strip() == "---":
                in_front = False
                continue
            if raw.startswith("description:") and not CYR_WORD.search(raw):
                description_is_english = True
            continue
        fence_line = raw.lstrip().lstrip(">").strip()  # блоки кода бывают внутри цитат
        if fence_line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if ALLOW in raw:
            continue
        line = strip_noise(raw)
        words = re.findall(r"[A-Za-zА-Яа-яЁё'’-]+", line)
        latin += sum(1 for w in words if LATIN_WORD.fullmatch(w))
        cyr += sum(1 for w in words if CYR_WORD.fullmatch(w))
        run: list[str] = []
        best: list[str] = []
        for w in words:
            if LATIN_WORD.fullmatch(w) and len(w) >= 3:
                run.append(w)
                if len(run) > len(best):
                    best = list(run)
            else:
                run = []
        if len(best) >= RUN_WORDS:
            runs.append((number, " ".join(best)))
    share = round(100 * cyr / max(1, cyr + latin))
    return share, runs, description_is_english


def skill_dirs(targets: list[str]) -> list[Path]:
    if targets:
        out = []
        for t in targets:
            p = Path(t).resolve()
            out.append(p if p.is_dir() else p.parent)
        return sorted(set(out))
    return sorted({p.parent for p in SKILLS.rglob("SKILL.md")})


def main(argv: list[str]) -> int:
    targets = [a for a in argv[1:] if not a.startswith("-")]
    failed = 0
    printed_header = False
    for skill in skill_dirs(targets):
        rows = []
        cyr_total = words_total = 0
        runs_total = 0
        desc_english = []
        for f in sorted(skill.rglob("*.md")):
            share, runs, desc_en = analyse(f)
            if desc_en:
                desc_english.append(f.relative_to(skill).as_posix())
            cyr_total += share
            words_total += 1
            if runs:
                rows.append((f.relative_to(skill).as_posix(), runs))
                runs_total += len(runs)
        share = round(cyr_total / max(1, words_total))
        is_russian = share >= RUSSIAN_SHARE
        status = "русский" if is_russian else "английский"
        bad = is_russian and runs_total
        if is_russian and desc_english:
            runs_total += 1
            bad = True
            rows.append(("·", [(0, "description: на английском")]))
        if bad:
            failed += 1
        if not printed_header:
            print(f"{'навык':44} {'язык':11} {'рус%':>5} {'англ.серий':>10}")
            printed_header = True
        name = f"{skill.parent.name}/{skill.name}"
        print(f"{name:44} {status:11} {share:5} {runs_total:10}{'  ⚠' if bad else ''}")
        if bad:
            for rel, runs in rows:
                for number, snippet in runs:
                    print(f"    {rel}:{number}: {snippet[:90]}")
    print()
    if failed:
        print(f"английская проза в русских навыках: {failed} — перевести")
        return 1
    print("язык в порядке")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
