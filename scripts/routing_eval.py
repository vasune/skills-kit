#!/usr/bin/env python3
"""Роутинг навыков: попадает ли фраза пользователя в свой навык.

    python3 ./scripts/routing_eval.py [--repo PATH] [--top 3] \
        [--min-rank1 90] [--collision-warn 0.60] [--no-aliases] [--verbose]

Без сети и LLM: TF-IDF по `name` + `description` всех навыков (имя с весом ×2),
косинус запроса с навыком. Двуязычные алиасы (план↔plan, тест↔test, …) схлопывают
RU/EN доменные слова до TF-IDF, поэтому английское описание ловит русский запрос и
наоборот; `--no-aliases` выключает их для диагностики. Кейсы —
`evals/routing/<skill>.json`:

    {"skill": "plan",
     "positive": ["напиши план на задачу", ...],
     "negative": [{"prompt": "что строить, если требований нет", "owner": "brainstorming"}],
     "known_miss": "почему провал осознан"}

Метрики: rank-1 и top-k по positive; negative не должен уводить к чужому навыку,
а с `owner` — обязан попадать во владельца; матрица коллизий описаний. Провалы
positive из кейса с `known_miss` печатаются отдельно и не входят в floor. Падение
floor rank-1 или ошибка negative — код возврата 1. Провал кейса почти всегда
значит «чинить description», а не сам eval.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CASES_DIR = Path("evals") / "routing"
DEFAULT_FLOOR = 90
DEFAULT_TOP = 3
DEFAULT_COLLISION_WARN = 0.60

TOKEN = re.compile(r"[a-zа-я0-9]+")
CYRILLIC = re.compile(r"^[а-я]+$")
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---", re.S)

# Служебные слова и слова-триггеры: они есть почти в каждом description и в
# каждой фразе, поэтому в TF-IDF только шумят. «Открывать, когда», «use when»
# снимаются здесь, а не в навыках.
STOPWORDS = frozenset(
    {
        "и", "в", "во", "на", "для", "по", "с", "со", "что", "как", "не", "а",
        "из", "при", "это", "или", "о", "об", "от", "до", "у", "к", "же", "ли",
        "то", "нужно", "нужен", "надо", "его", "её", "их", "который", "которая",
        "которые", "если", "чем", "над", "под", "без", "через", "между", "также",
        "уже", "есть", "бы", "был", "была", "были", "будет", "можно", "мне",
        "меня", "мы", "вы", "он", "она", "они", "этот", "эта", "эти", "так",
        "там", "тут", "вот", "где", "чего", "чему", "свой", "свои", "наш",
        "наша", "наши", "очень", "просто", "надо", "давай", "пожалуйста",
        "the", "a", "an", "of", "for", "to", "and", "or", "in", "on", "with",
        "this", "that", "it", "is", "are", "be", "by", "as", "at", "from",
        "into", "your", "you", "my", "we", "our", "me", "i", "do", "does",
        "should", "would", "can", "could", "not", "no", "yes", "there",
    }
)
TRIGGER_WORDS = frozenset(
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

# Двуязычные алиасы: английское описание должно ловить русский запрос и наоборот.
# Ключ — токен после стеммера, значение — каноническая форма; применяется и к
# документам, и к запросу, поэтому TF-IDF и косинус остаются симметричными.
ALIASES = {
    "план": "plan", "планиров": "plan", "plan": "plan", "plans": "plan",
    "тест": "test", "тестир": "test", "test": "test", "tests": "test",
    "ревь": "review", "review": "review", "reviews": "review",
    "деплой": "deploy", "deploy": "deploy", "deploys": "deploy",
    "deployment": "deploy",
    "док": "doc", "документ": "doc", "документац": "doc", "doc": "doc",
    "docs": "doc", "document": "doc", "documents": "doc",
    "documentation": "doc",
    "ошибк": "bug", "ошибок": "bug", "баг": "bug", "bug": "bug",
    "bugs": "bug", "error": "bug", "errors": "bug",
    "миграц": "migration", "migration": "migration", "migrations": "migration",
    "лиценз": "license", "license": "license", "licenses": "license",
    "licence": "license",
    "конфиг": "config", "конфигурац": "config", "config": "config",
    "configs": "config", "configuration": "config",
    "лог": "log", "log": "log", "logs": "log",
    "безопасн": "security", "security": "security",
    "производительн": "performance", "performance": "performance",
    "коммит": "commit", "commit": "commit", "commits": "commit",
    "ветк": "branch", "веток": "branch", "branch": "branch",
    "branches": "branch",
    "пр": "pr", "pr": "pr",
    "метрик": "metric", "metric": "metric", "metrics": "metric",
    "навык": "skill", "скилл": "skill", "skill": "skill", "skills": "skill",
}

# Лёгкий стеммер: снимает только окончания, оставляя основу не короче 4 букв.
# Этого хватает на «навык/навыки/навыков → навык», но не превращает термины в
# бессмысленные обрубки.
RU_SUFFIXES = tuple(
    sorted(
        {
            "ование", "ание", "ение", "ость", "ости", "ется", "ются", "ать",
            "ять", "ить", "еть", "ами", "ями", "ов", "ев", "ий", "ый", "ая",
            "ое", "ые", "ых", "ам", "ям", "ом", "ем", "ах", "ях", "ую", "юю",
            "ия", "ии", "ию", "ей", "ой", "а", "я", "ы", "и", "о", "е", "у",
            "ю", "ь",
        },
        key=len,
        reverse=True,
    )
)


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower().replace("ё", "е"))


def stem(token: str) -> str:
    if not CYRILLIC.match(token):
        return token
    for suffix in RU_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def normalize(text: str, aliases: bool = True) -> list[str]:
    tokens: list[str] = []
    for token in tokenize(text):
        if token in STOPWORDS or token in TRIGGER_WORDS or len(token) < 2:
            continue
        token = stem(token)
        tokens.append(ALIASES.get(token, token) if aliases else token)
    return tokens


@dataclass(frozen=True)
class Skill:
    name: str
    description: str


@dataclass(frozen=True)
class Negative:
    prompt: str
    owner: str | None = None


@dataclass(frozen=True)
class Case:
    skill: str
    positives: tuple[str, ...]
    negatives: tuple[Negative, ...]
    known_miss: str | None = None


@dataclass
class SkillStat:
    positives: int = 0
    rank1: int = 0
    topk: int = 0


@dataclass
class Result:
    per_skill: dict[str, SkillStat] = field(default_factory=dict)
    positive_total: int = 0
    rank1_hits: int = 0
    topk_hits: int = 0
    negative_total: int = 0
    negative_errors: list[str] = field(default_factory=list)
    positive_failures: list[str] = field(default_factory=list)
    known_miss_total: int = 0
    known_miss_failures: list[str] = field(default_factory=list)
    collisions: list[tuple[str, str, float]] = field(default_factory=list)

    @property
    def audited_total(self) -> int:
        """Фразы, которые зачитываются в floor: known_miss из него исключены."""
        return self.positive_total - self.known_miss_total

    @property
    def rank1_rate(self) -> float:
        if not self.audited_total:
            return 100.0 if self.positive_total else 0.0
        return 100.0 * self.rank1_hits / self.audited_total

    @property
    def topk_rate(self) -> float:
        return 100.0 * self.topk_hits / self.positive_total if self.positive_total else 0.0


@dataclass
class Index:
    skills: dict[str, Skill]
    idf: dict[str, float]
    vectors: dict[str, dict[str, float]]
    description_vectors: dict[str, dict[str, float]]
    aliases: bool = True


def frontmatter_description(text: str) -> str:
    match = FRONTMATTER.match(text)
    if not match:
        return ""
    for line in match.group(1).splitlines():
        if line.startswith("description:"):
            value = line.split(":", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
    return ""


def load_skills(repo: Path) -> tuple[dict[str, Skill], list[str]]:
    skills_root = repo / "skills"
    errors: list[str] = []
    skills: dict[str, Skill] = {}
    if not skills_root.is_dir():
        return {}, [f"нет каталога {skills_root}"]
    for path in sorted(skills_root.glob("*/*/SKILL.md")):
        name = path.parent.name
        description = frontmatter_description(
            path.read_text(encoding="utf-8", errors="ignore")
        )
        if not description:
            errors.append(f"{path.relative_to(repo)}: нет description")
            continue
        if name in skills:
            errors.append(f"дубль навыка {name}")
            continue
        skills[name] = Skill(name, description)
    return skills, errors


def _string_list(value: object) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return value


def load_cases(repo: Path, skills: dict[str, Skill]) -> tuple[list[Case], list[str]]:
    cases_dir = repo / CASES_DIR
    errors: list[str] = []
    cases: list[Case] = []
    if not cases_dir.is_dir():
        return [], [f"нет каталога {CASES_DIR}/"]
    seen_positives: set[str] = set()
    negative_owners: dict[str, str | None] = {}
    for path in sorted(cases_dir.glob("*.json")):
        rel = path.relative_to(repo)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            errors.append(f"{rel}: не JSON — {error.msg}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{rel}: кейс должен быть объектом")
            continue
        skill = data.get("skill")
        if not isinstance(skill, str) or not skill:
            errors.append(f"{rel}: нет поля skill")
            continue
        if skill not in skills:
            errors.append(f"{rel}: навыка {skill} нет в skills/")
            continue
        if path.stem != skill:
            errors.append(f"{rel}: имя файла должно совпадать с skill={skill}")
        positives = _string_list(data.get("positive"))
        if positives is None:
            errors.append(f"{rel}: positive должен быть списком строк")
            continue
        if not positives:
            errors.append(f"{rel}: пустой positive")
        negative_rows = data.get("negative", [])
        if not isinstance(negative_rows, list):
            errors.append(f"{rel}: negative должен быть списком")
            continue
        negatives: list[Negative] = []
        for row in negative_rows:
            if not isinstance(row, dict):
                errors.append(f"{rel}: negative-элемент должен быть объектом")
                continue
            prompt = row.get("prompt")
            owner = row.get("owner")
            if not isinstance(prompt, str) or not prompt.strip():
                errors.append(f"{rel}: negative без prompt")
                continue
            if owner is not None and not isinstance(owner, str):
                errors.append(f"{rel}: negative owner должен быть строкой")
                continue
            if owner and owner not in skills:
                errors.append(f"{rel}: negative owner={owner} нет в skills/")
                continue
            negatives.append(Negative(prompt.strip(), owner or None))
        for prompt in positives:
            if prompt in seen_positives:
                errors.append(f"{rel}: positive повторяется в кейсах — {prompt!r}")
            seen_positives.add(prompt)
        # Одна и та же фраза может быть positive владельца и negative чужого
        # кейса — это осмысленно. Конфликт — только разные owner у одной фразы.
        for negative in negatives:
            if negative.prompt in negative_owners and negative_owners[negative.prompt] != negative.owner:
                errors.append(
                    f"{rel}: negative {negative.prompt!r} уже объявлен "
                    f"с owner={negative_owners[negative.prompt]}"
                )
            negative_owners[negative.prompt] = negative.owner
        known_miss = data.get("known_miss")
        if known_miss is not None and (
            not isinstance(known_miss, str) or not known_miss.strip()
        ):
            errors.append(f"{rel}: known_miss должен быть непустой строкой")
            known_miss = None
        cases.append(
            Case(
                skill,
                tuple(prompt for prompt in positives if prompt.strip()),
                tuple(negatives),
                known_miss.strip() if known_miss else None,
            )
        )
    return cases, errors


def build_index(skills: dict[str, Skill], aliases: bool = True) -> Index:
    documents: dict[str, list[str]] = {}
    for name, skill in skills.items():
        name_tokens = normalize(name.replace("-", " "), aliases)
        documents[name] = name_tokens * 2 + normalize(skill.description, aliases)
    document_frequency: Counter[str] = Counter()
    for tokens in documents.values():
        document_frequency.update(set(tokens))
    total = len(documents)
    idf = {
        token: math.log((total + 1) / (frequency + 1)) + 1
        for token, frequency in document_frequency.items()
    }
    vectors: dict[str, dict[str, float]] = {}
    description_vectors: dict[str, dict[str, float]] = {}
    for name, tokens in documents.items():
        counts = Counter(tokens)
        length = len(tokens) or 1
        vectors[name] = _normalize_vector(
            {token: (count / length) * idf[token] for token, count in counts.items()}
        )
        description_tokens = normalize(skills[name].description, aliases)
        counts = Counter(description_tokens)
        length = len(description_tokens) or 1
        # Коллизии считаются по описаниям, без веса имени: иначе уникальное имя
        # разбавляет общий текст и две одинаковые description не выглядят похожими.
        description_vectors[name] = _normalize_vector(
            {token: (count / length) * idf[token] for token, count in counts.items()}
        )
    return Index(skills, idf, vectors, description_vectors, aliases)


def _normalize_vector(vector: dict[str, float]) -> dict[str, float]:
    norm = math.sqrt(sum(value * value for value in vector.values()))
    if not norm:
        return {}
    return {token: value / norm for token, value in vector.items()}


def query_vector(index: Index, prompt: str) -> dict[str, float]:
    tokens = [
        token for token in normalize(prompt, index.aliases) if token in index.idf
    ]
    if not tokens:
        return {}
    counts = Counter(tokens)
    length = len(tokens)
    vector = {
        token: (count / length) * index.idf[token]
        for token, count in counts.items()
    }
    return _normalize_vector(vector)


def cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(token, 0.0) for token, value in left.items())


def rank(index: Index, prompt: str) -> list[tuple[str, float]]:
    vector = query_vector(index, prompt)
    if not vector:
        return [(name, 0.0) for name in sorted(index.skills)]
    scores = {
        name: cosine(vector, skill_vector)
        for name, skill_vector in index.vectors.items()
    }
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def description_collisions(
    index: Index, threshold: float = DEFAULT_COLLISION_WARN
) -> list[tuple[str, str, float]]:
    collisions: list[tuple[str, str, float]] = []
    names = sorted(index.description_vectors)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            score = cosine(index.description_vectors[left], index.description_vectors[right])
            if score >= threshold:
                collisions.append((left, right, score))
    return sorted(collisions, key=lambda item: -item[2])


def evaluate(
    repo: Path,
    top: int = DEFAULT_TOP,
    collision_threshold: float = DEFAULT_COLLISION_WARN,
    aliases: bool = True,
) -> tuple[Result, list[str]]:
    skills, skill_errors = load_skills(repo)
    result = Result()
    if skill_errors:
        return result, skill_errors
    cases, case_errors = load_cases(repo, skills)
    if case_errors:
        return result, case_errors
    index = build_index(skills, aliases)

    for case in cases:
        stat = result.per_skill.setdefault(case.skill, SkillStat())
        for prompt in case.positives:
            ranked = rank(index, prompt)
            names = [name for name, _ in ranked]
            position = names.index(case.skill) + 1 if case.skill in names else 0
            stat.positives += 1
            result.positive_total += 1
            if position == 1:
                stat.rank1 += 1
                result.rank1_hits += 1
            if position and position <= top:
                stat.topk += 1
                result.topk_hits += 1
            if position != 1:
                predicted = ranked[0][0] if ranked else "—"
                detail = (
                    f"{case.skill}: {prompt!r} → {predicted} "
                    f"(свой навык на месте {position or '—'})"
                )
                # known_miss — осознанное ограничение лексического Tier-2:
                # провал виден в сводке, но не роняет floor.
                if case.known_miss:
                    result.known_miss_total += 1
                    result.known_miss_failures.append(
                        f"{detail} — known_miss: {case.known_miss}"
                    )
                else:
                    result.positive_failures.append(detail)
        for negative in case.negatives:
            result.negative_total += 1
            ranked = rank(index, negative.prompt)
            predicted = ranked[0][0] if ranked else "—"
            if negative.owner:
                if predicted != negative.owner:
                    result.negative_errors.append(
                        f"{case.skill}: negative {negative.prompt!r} должен уйти "
                        f"в {negative.owner}, а ушёл в {predicted}"
                    )
            elif predicted == case.skill:
                result.negative_errors.append(
                    f"{case.skill}: negative {negative.prompt!r} не должен "
                    f"открывать этот навык, а открыл"
                )

    result.collisions = description_collisions(index, collision_threshold)
    return result, []


def print_report(result: Result) -> None:
    header = f"{'навык':36} {'фраз':>5} {'rank-1':>7} {'top-k':>6}"
    print(header)
    for name in sorted(result.per_skill):
        stat = result.per_skill[name]
        print(
            f"{name:36} {stat.positives:5} {stat.rank1:7} {stat.topk:6}"
        )
    print()
    print(
        f"положительных: {result.positive_total}, "
        f"rank-1: {result.rank1_rate:.0f}% "
        f"({result.rank1_hits}/{result.positive_total}), "
        f"top-k: {result.topk_rate:.0f}% "
        f"({result.topk_hits}/{result.positive_total})"
    )
    if result.known_miss_total:
        print(
            f"known_miss (не влияет на floor): {result.known_miss_total} "
            f"из {result.positive_total}; зачтено: {result.audited_total}"
        )
    print(
        f"negative: {result.negative_total}, "
        f"ошибок: {len(result.negative_errors)}"
    )
    print(f"коллизии описаний (cosine ≥ порога): {len(result.collisions)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo",
        type=Path,
        default=REPO,
        help="корень репозитория (по умолчанию — корень этого скрипта)",
    )
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help="top-k, по умолчанию 3")
    parser.add_argument(
        "--min-rank1",
        type=float,
        default=DEFAULT_FLOOR,
        help=f"минимальный rank-1 в процентах, по умолчанию {DEFAULT_FLOOR}",
    )
    parser.add_argument(
        "--collision-warn",
        type=float,
        default=DEFAULT_COLLISION_WARN,
        help=f"порог косинуса для коллизий, по умолчанию {DEFAULT_COLLISION_WARN}",
    )
    parser.add_argument("--verbose", action="store_true", help="показать провалы и коллизии")
    parser.add_argument(
        "--no-aliases",
        action="store_false",
        dest="aliases",
        help="не схлопывать RU/EN алиасы (диагностика: сравнить с лексикой как есть)",
    )
    args = parser.parse_args(argv)
    if args.top < 1:
        parser.error("--top должен быть ≥ 1")
    if not 0 <= args.min_rank1 <= 100:
        parser.error("--min-rank1 должен быть в диапазоне 0…100")
    if not 0 <= args.collision_warn <= 1:
        parser.error("--collision-warn должен быть в диапазоне 0…1")

    repo = args.repo.resolve()
    result, errors = evaluate(repo, args.top, args.collision_warn, args.aliases)
    for error in errors:
        print(f"ошибка кейса: {error}")
    if errors:
        return 1

    print_report(result)
    for failure in result.positive_failures:
        if args.verbose:
            print(f"провал: {failure}")
    for failure in result.known_miss_failures:
        if args.verbose:
            print(f"known_miss: {failure}")
    for error in result.negative_errors:
        print(f"ошибка negative: {error}")
    for left, right, score in result.collisions:
        if args.verbose:
            print(f"коллизия: {left} ↔ {right}: cosine {score:.2f}")

    failed = False
    if result.rank1_rate < args.min_rank1:
        print(
            f"провал: rank-1 {result.rank1_rate:.0f}% "
            f"< floor {args.min_rank1:.0f}%"
        )
        failed = True
    if result.negative_errors:
        failed = True
    if failed:
        return 1
    print(f"floor rank-1: {args.min_rank1:.0f}% — пройден")
    return 0


if __name__ == "__main__":
    sys.exit(main())
