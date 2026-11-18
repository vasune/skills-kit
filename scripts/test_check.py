#!/usr/bin/env python3
"""Тесты валидатора check.py на временных репозиториях.

    python3 ./scripts/test_check.py

Тесты не трогают настоящий каталог: каждый собирает одноразовый репозиторий в
tempfile. Кроме отдельных правил есть «ловушка на ложное зелёное»: чистый
репозиторий обязан быть зелёным, а каждое подложенное нарушение — покраснеть.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import check  # noqa: E402

CHECK_PY = SCRIPTS / "check.py"

ALPHA_DESCRIPTION = "Открывать, когда нужен первый пример."
BETA_DESCRIPTION = "Открывать, когда нужен второй пример."


# --- сборка временного репозитория ----------------------------------------


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def skill_text(
    name: str,
    description: str = ALPHA_DESCRIPTION,
    version: str = "1.0.0",
    frontmatter_extra: tuple[str, ...] = (),
    body: str = "",
) -> str:
    frontmatter = [
        "---",
        f"name: {name}",
        f"description: {description}",
        f"version: {version}",
        "author: test",
        "license: MIT",
        *frontmatter_extra,
        "---",
    ]
    return (
        "\n".join(frontmatter)
        + f"\n\n# {name}\n\n## Когда открывать\n\n- пример.\n{body}"
    )


def role_text(name: str = "helper", extra: str = "") -> str:
    return textwrap.dedent(
        f"""\
        ---
        name: {name}
        description: Тестовая роль без двоеточий
        mode: subagent
        tools: read-only
        model: inherit
        ---

        # {name}

        ## Что дать в `context`

        - бриф.

        ## Что делает

        1. Делает.

        ## Формат ответа

        ```text
        ## Находки
        ```

        ## Чего не делает

        - Ничего.

        ## Composition

        - Напрямую: тест.
        """
    ) + extra


def related_extra(*refs: str) -> tuple[str, ...]:
    """Вложенный frontmatter `metadata.related_skills` для тестов.

    Отступные строки парсер навыка пропускает, а RELATED_SKILLS ищет по всему
    тексту — поэтому блок можно подставить и так.
    """
    return ("metadata:", f"  related_skills: [{', '.join(refs)}]")


def default_skills() -> list[dict]:
    return [
        {"group": "core", "name": "alpha", "description": ALPHA_DESCRIPTION, "level": "L1"},
        {"group": "code", "name": "beta", "description": BETA_DESCRIPTION, "level": "L2"},
    ]


def build_repo(
    root: Path,
    skills: list[dict] | None = None,
    roles: list[str] | None = None,
    summary: str | None = None,
    readme_groups: list[str] | None = None,
    role_rows: list[str] | None = None,
) -> None:
    """Собирает минимальный целостный репозиторий; параметры ломают parity."""
    skills = default_skills() if skills is None else skills
    roles = ["helper"] if roles is None else roles
    for item in skills:
        text = item.get("text") or skill_text(
            item["name"],
            item.get("description", ALPHA_DESCRIPTION),
            item.get("version", "1.0.0"),
            item.get("frontmatter_extra", ()),
            item.get("body", ""),
        )
        write(root / "skills" / item["group"] / item["name"] / "SKILL.md", text)
    for name in roles:
        write(root / "subagents" / f"{name}.md", role_text(name))

    rows = "\n".join(
        f"| [`{s['name']}`](skills/{s['group']}/{s['name']}/SKILL.md) "
        f"| {s['level']} | когда | {s.get('files', 1)} |"
        for s in skills
    )
    l1 = sum(1 for s in skills if s["level"] == "L1")
    l2 = sum(1 for s in skills if s["level"] == "L2")
    if summary is None:
        summary = f"Всего навыков: **{len(skills)}** — L1: **{l1}**, L2: **{l2}**."
    index = "# Каталог навыков\n\n| Навык | Ур. | Когда | Файлов |\n|---|---|---|---|\n"
    index += rows + "\n\n"
    if summary:
        index += summary + "\n"
    write(root / "INDEX.md", index)

    groups = (
        sorted({s["group"] for s in skills})
        if readme_groups is None
        else readme_groups
    )
    tree = "\n".join(
        f"│   {'└──' if i == len(groups) - 1 else '├──'} {group}/              тест"
        for i, group in enumerate(groups)
    )
    write(
        root / "README.md",
        "# skills-kit\n\n## Архитектура\n\n```text\n"
        "skills-kit/\n├── skills/                   навыки\n"
        f"{tree}\n└── subagents/                роли\n```\n\n## Как добавить навык\n",
    )

    listed = roles if role_rows is None else role_rows
    table = "\n".join(
        f"| [`{name}.md`]({name}.md) | тест | read-only | всегда |" for name in listed
    )
    write(
        root / "subagents" / "README.md",
        "# Субагенты\n\n## Роли\n\n| Файл | Роль | Права | Когда |\n|---|---|---|---|\n"
        + table
        + "\n",
    )


def rewrite_skill(root: Path, group: str, name: str, text: str) -> None:
    write(root / "skills" / group / name / "SKILL.md", text)


def rewrite_role(root: Path, name: str, text: str) -> None:
    write(root / "subagents" / f"{name}.md", text)


def write_index(root: Path, text: str) -> None:
    write(root / "INDEX.md", text)


def read_index(root: Path) -> str:
    return (root / "INDEX.md").read_text(encoding="utf-8")


# --- манифесты установки ----------------------------------------------------


def write_manifest(root: Path, rel: str, data: dict | str) -> None:
    text = data if isinstance(data, str) else json.dumps(data, indent=2) + "\n"
    write(root / rel, text)


def plugin_manifest(
    version: str = "1.0.0", skills: str = "./skills", name: str = "skills-kit"
) -> dict:
    return {"name": name, "version": version, "skills": skills}


def marketplace_manifest(version: str = "1.0.0", path: str | None = None) -> dict:
    source: dict = {"source": "github", "repo": "fhfqndj/skills-kit"}
    if path is not None:
        source = {"source": "local", "path": path}
    return {
        "name": "skills-kit",
        "plugins": [{"name": "skills-kit", "version": version, "source": source}],
    }


def errors_text(report: check.Report) -> str:
    return "\n".join(report.errors)


def warnings_text(report: check.Report) -> str:
    return "\n".join(report.warnings)


class RepoTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        build_repo(self.repo)
        self.addCleanup(self._tmp.cleanup)

    def report(self) -> check.Report:
        return check.run(self.repo)


# --- чистые функции --------------------------------------------------------


class PureRuleTests(unittest.TestCase):
    def test_split_frontmatter(self) -> None:
        lines, body = check.split_frontmatter("---\nname: x\n---\n# X\n")
        self.assertEqual(lines, ["name: x"])
        self.assertEqual(body, "# X")
        self.assertEqual(check.split_frontmatter("# без frontmatter"), (None, "# без frontmatter"))
        self.assertEqual(check.split_frontmatter("---\nname: x\n"), (None, "---\nname: x\n"))

    def test_parse_frontmatter_good(self) -> None:
        meta, errors = check.parse_frontmatter(
            '---\nname: x\ndescription: "Открывать, когда нужно: пример."\n---\n'
        )
        self.assertEqual(errors, [])
        self.assertEqual(meta["description"], "Открывать, когда нужно: пример.")

    def test_parse_frontmatter_bad(self) -> None:
        _, errors = check.parse_frontmatter(
            "---\nname: x\nname: y\n\tversion: 1\ndescription: \"без конца\n---\n"
        )
        text = "\n".join(errors)
        self.assertIn("дубль ключа name", text)
        self.assertIn("таб", text)
        self.assertIn("незакрытая кавычка", text)

    def test_description_tokens_strip_trigger_and_stopwords(self) -> None:
        tokens = check.description_tokens("Открывать, когда пишется отчёт для руководства.")
        self.assertNotIn("открывать", tokens)
        self.assertNotIn("когда", tokens)
        self.assertNotIn("для", tokens)
        self.assertEqual(tokens, {"пишется", "отчет", "руководства"})

    def test_jaccard(self) -> None:
        self.assertEqual(check.jaccard({"a", "b"}, {"a", "b"}), 1.0)
        self.assertEqual(check.jaccard({"a", "b"}, {"b", "c"}), 1 / 3)
        self.assertEqual(check.jaccard(set(), set()), 0.0)


# --- frontmatter -----------------------------------------------------------


class FrontmatterTests(RepoTestCase):
    def test_good_repo_is_green(self) -> None:
        report = self.report()
        self.assertEqual(report.errors, [])
        self.assertEqual(report.skills, 2)

    def test_missing_required_version(self) -> None:
        rewrite_skill(
            self.repo,
            "core",
            "alpha",
            "---\nname: alpha\ndescription: Открывать, когда нужен пример.\n---\n\n# A\n",
        )
        self.assertIn("пустое обязательное поле version", errors_text(self.report()))

    def test_unknown_frontmatter_key(self) -> None:
        rewrite_skill(
            self.repo,
            "core",
            "alpha",
            skill_text("alpha", frontmatter_extra=("owner: test",)),
        )
        self.assertIn("недопустимый ключ frontmatter: owner", errors_text(self.report()))

    def test_name_must_be_kebab_and_match_directory(self) -> None:
        rewrite_skill(self.repo, "core", "alpha", skill_text("Alpha"))
        text = errors_text(self.report())
        self.assertIn("не kebab-case", text)
        self.assertIn("не совпадает с каталогом alpha", text)

    def test_version_must_be_semver(self) -> None:
        rewrite_skill(self.repo, "core", "alpha", skill_text("alpha", version="1.0"))
        self.assertIn("не semver", errors_text(self.report()))

    def test_duplicate_key(self) -> None:
        text = skill_text("alpha").replace("name: alpha", "name: alpha\nname: alpha")
        rewrite_skill(self.repo, "core", "alpha", text)
        self.assertIn("дубль ключа name", errors_text(self.report()))

    def test_tab_in_yaml(self) -> None:
        text = skill_text("alpha").replace("license: MIT", "\tlicense: MIT")
        rewrite_skill(self.repo, "core", "alpha", text)
        self.assertIn("таб в YAML-frontmatter", errors_text(self.report()))

    def test_unclosed_quote(self) -> None:
        text = skill_text("alpha").replace(
            "description: " + ALPHA_DESCRIPTION,
            'description: "Открывать, когда нужен пример.',
        )
        rewrite_skill(self.repo, "core", "alpha", text)
        self.assertIn("незакрытая кавычка", errors_text(self.report()))

    def test_unquoted_colon_in_value(self) -> None:
        text = skill_text("alpha").replace(
            "description: " + ALPHA_DESCRIPTION,
            "description: Открывать: когда нужен пример.",
        )
        rewrite_skill(self.repo, "core", "alpha", text)
        self.assertIn("двоеточие с пробелом", errors_text(self.report()))

    def test_description_length(self) -> None:
        rewrite_skill(
            self.repo, "core", "alpha", skill_text("alpha", description="Открывать, когда " + "очень " * 12 + "нужно.")
        )
        self.assertIn("длиннее 60 символов", errors_text(self.report()))


# --- description -----------------------------------------------------------


class DescriptionTests(RepoTestCase):
    def test_near_duplicate_is_error(self) -> None:
        rewrite_skill(self.repo, "core", "alpha", skill_text("alpha", "Открывать, когда пишется отчёт."))
        rewrite_skill(self.repo, "code", "beta", skill_text("beta", "Use when пишется отчёт."))
        self.assertIn("почти дублируются", errors_text(self.report()))

    def test_distinct_descriptions_stay_green(self) -> None:
        self.assertEqual(self.report().errors, [])

    def test_trigger_warning_for_new_skill(self) -> None:
        rewrite_skill(
            self.repo,
            "core",
            "alpha",
            skill_text("alpha", "Exploratory QA of web apps: find bugs."),
        )
        self.assertIn("не начинается с триггера", warnings_text(self.report()))

    def test_trigger_baseline_is_empty(self) -> None:
        self.assertEqual(check.TRIGGER_BASELINE, frozenset())
        self.assertEqual(check.WHEN_SECTION_BASELINE, frozenset())

    def test_trigger_baseline_still_silences_listed_skill(self) -> None:
        build_repo(
            self.repo,
            skills=[
                {
                    "group": "core",
                    "name": "plan",
                    "description": "Exploratory QA of web apps.",
                    "level": "L1",
                },
                {
                    "group": "code",
                    "name": "beta",
                    "description": BETA_DESCRIPTION,
                    "level": "L2",
                },
            ],
        )
        saved = check.TRIGGER_BASELINE
        check.TRIGGER_BASELINE = frozenset({"plan"})
        try:
            report = self.report()
            self.assertNotIn("не начинается с триггера", warnings_text(report))
            self.assertEqual(report.baseline["description без триггера"], 1)
        finally:
            check.TRIGGER_BASELINE = saved

    def test_when_section_warning(self) -> None:
        text = skill_text("alpha").replace("## Когда открывать", "## Обзор")
        rewrite_skill(self.repo, "core", "alpha", text)
        self.assertIn("нет раздела «Когда открывать»", warnings_text(self.report()))

    def test_line_budget_warning(self) -> None:
        body = "\n".join(f"- строка {i}" for i in range(310))
        rewrite_skill(self.repo, "core", "alpha", skill_text("alpha", body=body))
        self.assertIn("> 300", warnings_text(self.report()))

    def test_body_over_char_cap_is_error(self) -> None:
        body = "х" * (check.SKILL_CHARS_MAX + 1)
        rewrite_skill(self.repo, "core", "alpha", skill_text("alpha", body=body))
        report = self.report()
        self.assertIn("символов (> 24000)", errors_text(report))

    def test_body_at_char_cap_is_green(self) -> None:
        body = "х" * (check.SKILL_CHARS_MAX - 200)
        rewrite_skill(self.repo, "core", "alpha", skill_text("alpha", body=body))
        self.assertEqual(self.report().errors, [])

    def test_orphan_reference_warning(self) -> None:
        write(self.repo / "skills/core/alpha/references/unused.md", "# Не используется\n")
        report = self.report()
        self.assertIn("unused.md недостижим из SKILL.md", warnings_text(report))

    def test_linked_reference_is_not_orphan(self) -> None:
        write(self.repo / "skills/core/alpha/references/used.md", "# Используется\n")
        rewrite_skill(
            self.repo,
            "core",
            "alpha",
            skill_text("alpha", body="- `references/used.md` — детали.\n"),
        )
        self.assertNotIn("недостижим", warnings_text(self.report()))

    def test_reference_directory_link_covers_nested_files(self) -> None:
        write(self.repo / "skills/core/alpha/references/sub/one.md", "# Один\n")
        rewrite_skill(
            self.repo,
            "core",
            "alpha",
            skill_text("alpha", body="- `references/sub/` — разборы.\n"),
        )
        self.assertNotIn("недостижим", warnings_text(self.report()))


# --- мусор и имена файлов --------------------------------------------------


class HygieneTests(RepoTestCase):
    def test_absolute_path(self) -> None:
        rewrite_skill(
            self.repo, "core", "alpha", skill_text("alpha", body="Смотри /Users/test/file.txt\n")
        )
        self.assertIn("абсолютный путь", errors_text(self.report()))

    def test_secret(self) -> None:
        rewrite_skill(
            self.repo,
            "core",
            "alpha",
            skill_text("alpha", body="token ghp_" + "x" * 24 + "\n"),
        )
        self.assertIn("похоже на секрет", errors_text(self.report()))

    def test_broken_link(self) -> None:
        rewrite_skill(
            self.repo, "core", "alpha", skill_text("alpha", body="[x](missing.md)\n")
        )
        self.assertIn("битая ссылка missing.md", errors_text(self.report()))

    def test_pycache_directory(self) -> None:
        write(self.repo / "skills/core/alpha/scripts/__pycache__/x.pyc", "junk")
        text = errors_text(self.report())
        self.assertIn("мусорный каталог __pycache__/", text)

    def test_pyc_file(self) -> None:
        write(self.repo / "skills/core/alpha/scripts/tool.pyc", "junk")
        self.assertIn("мусорный файл", errors_text(self.report()))

    def test_empty_directory(self) -> None:
        (self.repo / "skills/core/alpha/templates").mkdir(parents=True)
        self.assertIn("пустой каталог", errors_text(self.report()))

    def test_aux_name_with_underscore(self) -> None:
        write(self.repo / "skills/core/alpha/references/my_notes.md", "# notes\n")
        rewrite_skill(
            self.repo,
            "core",
            "alpha",
            skill_text("alpha", body="- `references/my_notes.md`\n"),
        )
        self.assertIn("имя вспомогательного файла", errors_text(self.report()))

    def test_examples_name_is_allowed(self) -> None:
        write(self.repo / "skills/core/alpha/references/EXAMPLES.md", "# examples\n")
        rewrite_skill(
            self.repo,
            "core",
            "alpha",
            skill_text("alpha", body="- `references/EXAMPLES.md`\n"),
        )
        self.assertNotIn("имя вспомогательного файла", errors_text(self.report()))

    def test_ds_store(self) -> None:
        write(self.repo / "skills/core/alpha/.DS_Store", "junk")
        self.assertIn("мусорный файл", errors_text(self.report()))


# --- роли subagents --------------------------------------------------------


class RoleTests(RepoTestCase):
    def test_good_role_is_green(self) -> None:
        self.assertEqual(self.report().errors, [])

    def test_role_without_composition(self) -> None:
        text = role_text().replace("## Composition", "## Другое")
        rewrite_role(self.repo, "helper", text)
        self.assertIn("нет раздела «Composition»", errors_text(self.report()))

    def test_composition_must_be_last(self) -> None:
        rewrite_role(self.repo, "helper", role_text(extra="\n## Хвост\n\n- лишнее.\n"))
        self.assertIn("последним разделом", errors_text(self.report()))

    def test_role_required_section(self) -> None:
        text = role_text().replace("## Чего не делает", "## Другое")
        rewrite_role(self.repo, "helper", text)
        self.assertIn("нет раздела «Чего не делает»", errors_text(self.report()))

    def test_role_name_matches_file(self) -> None:
        rewrite_role(self.repo, "helper", role_text("other"))
        self.assertIn("не совпадает с файлом helper.md", errors_text(self.report()))

    def test_role_broken_link(self) -> None:
        rewrite_role(self.repo, "helper", role_text(extra="\n[битая](missing.md)\n"))
        self.assertIn("битая ссылка missing.md", errors_text(self.report()))

    def test_role_without_frontmatter(self) -> None:
        rewrite_role(self.repo, "helper", "# helper\n\n## Что делает\n\n- Делает.\n")
        self.assertIn("нет YAML-frontmatter", errors_text(self.report()))


# --- parity INDEX / README / subagents ------------------------------------


class ParityTests(RepoTestCase):
    def test_summary_total_mismatch(self) -> None:
        build_repo(
            self.repo,
            summary="Всего навыков: **3** — L1: **1**, L2: **2**.",
        )
        self.assertIn("а навыков на диске 2", errors_text(self.report()))

    def test_summary_levels_mismatch(self) -> None:
        build_repo(
            self.repo,
            summary="Всего навыков: **2** — L1: **2**, L2: **0**.",
        )
        self.assertIn("в таблице L1 1/L2 1", errors_text(self.report()))

    def test_summary_missing(self) -> None:
        build_repo(self.repo, summary="")
        self.assertIn("нет итоговой строки", errors_text(self.report()))

    def test_readme_missing_group(self) -> None:
        build_repo(self.repo, readme_groups=["core"])
        self.assertIn("группа code/ есть на диске", errors_text(self.report()))

    def test_readme_extra_group(self) -> None:
        build_repo(self.repo, readme_groups=["core", "code", "ghost"])
        self.assertIn("в дереве группа ghost/", errors_text(self.report()))

    def test_role_table_missing_row(self) -> None:
        build_repo(self.repo, role_rows=[])
        self.assertIn("роль helper.md не описана", errors_text(self.report()))

    def test_role_table_phantom_row(self) -> None:
        build_repo(self.repo, role_rows=["helper", "ghost"])
        self.assertIn("строка про ghost.md", errors_text(self.report()))


# --- счётчик «Файлов» в INDEX ----------------------------------------------


class IndexFileCountTests(RepoTestCase):
    def test_default_repo_counts_match(self) -> None:
        self.assertEqual(self.report().errors, [])

    def test_shifted_count_is_error(self) -> None:
        write(self.repo / "skills/core/alpha/references/extra.md", "# Extra\n")
        rewrite_skill(
            self.repo,
            "core",
            "alpha",
            skill_text("alpha", body="- `references/extra.md`\n"),
        )
        self.assertIn(
            "INDEX.md: alpha: в колонке «Файлов» 1, фактически 2",
            errors_text(self.report()),
        )

    def test_corrected_count_is_green(self) -> None:
        build_repo(
            self.repo,
            skills=[
                {
                    "group": "core",
                    "name": "alpha",
                    "description": ALPHA_DESCRIPTION,
                    "level": "L1",
                    "files": 2,
                },
                {
                    "group": "code",
                    "name": "beta",
                    "description": BETA_DESCRIPTION,
                    "level": "L2",
                },
            ],
        )
        write(self.repo / "skills/core/alpha/references/extra.md", "# Extra\n")
        rewrite_skill(
            self.repo,
            "core",
            "alpha",
            skill_text("alpha", body="- `references/extra.md`\n"),
        )
        self.assertNotIn("в колонке «Файлов»", errors_text(self.report()))

    def test_nested_files_counted_recursively(self) -> None:
        write(self.repo / "skills/core/alpha/references/sub/one.md", "# One\n")
        write(self.repo / "skills/core/alpha/templates/doc.md", "# Doc\n")
        rewrite_skill(
            self.repo,
            "core",
            "alpha",
            skill_text("alpha", body="- `references/sub/`\n"),
        )
        self.assertIn(
            "INDEX.md: alpha: в колонке «Файлов» 1, фактически 3",
            errors_text(self.report()),
        )

    def test_junk_is_not_counted(self) -> None:
        write(self.repo / "skills/core/alpha/references/.DS_Store", "junk")
        text = errors_text(self.report())
        self.assertIn("мусорный файл", text)
        self.assertNotIn("в колонке «Файлов»", text)

    def test_missing_count_cell_is_error(self) -> None:
        text = read_index(self.repo).replace("| когда | 1 |", "| когда | — |", 1)
        write_index(self.repo, text)
        self.assertIn("в колонке «Файлов» не число", errors_text(self.report()))


# --- related_skills: односторонние — норма, не ошибка --------------------


class RelatedSkillsTests(RepoTestCase):
    def build_related(self, alpha_refs: tuple[str, ...] = (), beta_refs: tuple[str, ...] = ()) -> None:
        build_repo(
            self.repo,
            skills=[
                {
                    "group": "core",
                    "name": "alpha",
                    "description": ALPHA_DESCRIPTION,
                    "level": "L1",
                    "frontmatter_extra": related_extra(*alpha_refs),
                },
                {
                    "group": "code",
                    "name": "beta",
                    "description": BETA_DESCRIPTION,
                    "level": "L2",
                    "frontmatter_extra": related_extra(*beta_refs),
                },
            ],
        )

    def test_mutual_links_are_green(self) -> None:
        self.build_related(("beta",), ("alpha",))
        report = self.report()
        self.assertEqual(report.errors, [])
        self.assertFalse(any("односторонних" in n for n in report.notes))

    def test_one_way_link_is_noted_not_warned(self) -> None:
        self.build_related(("beta",), ())
        report = self.report()
        self.assertTrue(
            any("односторонних ссылок 1" in note for note in report.notes)
        )
        self.assertNotIn("односторонних", warnings_text(report))
        self.assertIn("alpha → beta", "\n".join(report.details))

    def test_self_link_is_ignored(self) -> None:
        self.build_related(("alpha",), ())
        report = self.report()
        self.assertEqual(report.errors, [])
        self.assertFalse(any("односторонних" in n for n in report.notes))

    def test_unknown_link_is_error_not_warning(self) -> None:
        self.build_related(("ghost",), ())
        report = self.report()
        self.assertIn("которого нет", errors_text(report))
        self.assertFalse(any("односторонних" in n for n in report.notes))


# --- покрытие routing-кейсами ---------------------------------------------


class RoutingCoverageTests(RepoTestCase):
    def test_missing_cases_note(self) -> None:
        self.assertIn("routing-кейсов нет: 2 (из 2)", self.report().notes)

    def test_partial_coverage_note(self) -> None:
        write(self.repo / "evals/routing/alpha.json", '{"skill": "alpha"}\n')
        self.assertIn("routing-кейсов нет: 1 (из 2)", self.report().notes)

    def test_full_coverage_has_no_note(self) -> None:
        write(self.repo / "evals/routing/alpha.json", '{"skill": "alpha"}\n')
        write(self.repo / "evals/routing/beta.json", '{"skill": "beta"}\n')
        self.assertEqual(self.report().notes, [])

    def test_note_is_not_a_warning(self) -> None:
        self.assertNotIn("routing-кейсов нет", warnings_text(self.report()))


# --- parity манифестов установки ------------------------------------------


class ManifestParityTests(RepoTestCase):
    def test_no_manifests_rule_not_applied(self) -> None:
        self.assertEqual(self.report().errors, [])

    def test_matching_manifests_are_green(self) -> None:
        write_manifest(self.repo, "plugin.json", plugin_manifest())
        write_manifest(self.repo, ".claude-plugin/plugin.json", plugin_manifest())
        write_manifest(
            self.repo, ".claude-plugin/marketplace.json", marketplace_manifest()
        )
        write_manifest(self.repo, ".codex-plugin/plugin.json", plugin_manifest())
        write_manifest(
            self.repo, ".agents/plugins/marketplace.json", marketplace_manifest()
        )
        self.assertEqual(self.report().errors, [])

    def test_shifted_version_is_error(self) -> None:
        write_manifest(self.repo, "plugin.json", plugin_manifest("1.0.0"))
        write_manifest(self.repo, ".codex-plugin/plugin.json", plugin_manifest("1.0.1"))
        self.assertIn(
            ".codex-plugin/plugin.json: version=1.0.1, а в plugin.json 1.0.0",
            errors_text(self.report()),
        )

    def test_marketplace_version_is_checked(self) -> None:
        write_manifest(self.repo, "plugin.json", plugin_manifest("1.0.0"))
        write_manifest(
            self.repo, ".claude-plugin/marketplace.json", marketplace_manifest("2.0.0")
        )
        self.assertIn(
            ".claude-plugin/marketplace.json: version=2.0.0",
            errors_text(self.report()),
        )

    def test_broken_json_is_error(self) -> None:
        write_manifest(self.repo, "plugin.json", plugin_manifest())
        write_manifest(self.repo, ".claude-plugin/plugin.json", "{ broken")
        self.assertIn("битый JSON", errors_text(self.report()))

    def test_missing_skills_dir_is_error(self) -> None:
        write_manifest(self.repo, "plugin.json", plugin_manifest(skills="./nope"))
        self.assertIn(
            "путь к навыкам './nope' не существует", errors_text(self.report())
        )

    def test_root_version_must_be_semver(self) -> None:
        write_manifest(self.repo, "plugin.json", plugin_manifest("1.0"))
        self.assertIn("не semver", errors_text(self.report()))

    def test_empty_name_is_error(self) -> None:
        write_manifest(self.repo, "plugin.json", plugin_manifest(name=""))
        self.assertIn("пустое поле name", errors_text(self.report()))

    def test_rule_skipped_without_root_manifest(self) -> None:
        write_manifest(self.repo, ".claude-plugin/plugin.json", plugin_manifest("9.9.9"))
        self.assertEqual(self.report().errors, [])

    def test_local_marketplace_source_path_root_is_green(self) -> None:
        write_manifest(self.repo, "plugin.json", plugin_manifest())
        write_manifest(
            self.repo,
            ".agents/plugins/marketplace.json",
            {
                "name": "skills-kit",
                "plugins": [
                    {
                        "name": "skills-kit",
                        "version": "1.0.0",
                        "source": {"source": "local", "path": "./"},
                    }
                ],
            },
        )
        self.assertEqual(self.report().errors, [])

    def test_marketplace_source_path_missing_is_error(self) -> None:
        write_manifest(self.repo, "plugin.json", plugin_manifest())
        write_manifest(
            self.repo,
            ".agents/plugins/marketplace.json",
            {
                "name": "skills-kit",
                "plugins": [
                    {
                        "name": "skills-kit",
                        "version": "1.0.0",
                        "source": {"source": "local", "path": "./ghost"},
                    }
                ],
            },
        )
        self.assertIn(
            "путь плагина './ghost' не существует", errors_text(self.report())
        )

    def test_plugin_root_without_plugin_json_or_skills_is_error(self) -> None:
        empty = self.repo / "plug"
        empty.mkdir()
        write_manifest(self.repo, "plugin.json", plugin_manifest())
        write_manifest(
            self.repo,
            ".agents/plugins/marketplace.json",
            {
                "name": "skills-kit",
                "plugins": [
                    {
                        "name": "skills-kit",
                        "version": "1.0.0",
                        "source": {"source": "local", "path": "./plug"},
                    }
                ],
            },
        )
        self.assertIn(
            "нет ни plugin.json, ни skills/", errors_text(self.report())
        )

    def test_skills_dir_without_skill_md_is_error(self) -> None:
        (self.repo / "empty-skills").mkdir()
        write_manifest(self.repo, "plugin.json", plugin_manifest(skills="./empty-skills"))
        self.assertIn(
            "нет ни одного SKILL.md", errors_text(self.report())
        )


# --- связка DSH-бандла -----------------------------------------------------


class DshBundleTests(RepoTestCase):
    patch = "- insert:\n    - id: skills-kit\n      name: './dsh-plugin.js'\n"

    def bundle(self, patch: str | None = None, module: bool = True) -> None:
        write_manifest(
            self.repo,
            "package.json",
            {
                "name": "skills-kit",
                "version": "1.0.0",
                "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
            },
        )
        write(self.repo / "cordis.patch.yml", patch or self.patch)
        if module:
            write(self.repo / "dsh-plugin.js", "export function apply() {}\n")

    def test_wired_bundle_is_green(self) -> None:
        self.bundle()
        self.assertEqual(self.report().errors, [])

    def test_missing_patch_is_error(self) -> None:
        self.bundle(module=False)
        (self.repo / "cordis.patch.yml").unlink()
        self.assertIn("не существует", errors_text(self.report()))

    def test_missing_module_is_error(self) -> None:
        self.bundle(module=False)
        self.assertIn("модуль './dsh-plugin.js' не существует", errors_text(self.report()))

    def test_patch_without_relative_module_is_error(self) -> None:
        self.bundle(patch="- insert:\n    - id: x\n      name: 'skills-kit'\n")
        self.assertIn(
            "ни одна строка не подключает модуль рядом с патчем",
            errors_text(self.report()),
        )

    def test_dropped_declaration_next_to_patch_is_error(self) -> None:
        write_manifest(self.repo, "package.json", {"name": "skills-kit", "version": "1.0.0"})
        write(self.repo / "cordis.patch.yml", self.patch)
        write(self.repo / "dsh-plugin.js", "export function apply() {}\n")
        self.assertIn("нет dsh.bundle.patch", errors_text(self.report()))

    def test_package_without_bundle_files_is_ignored(self) -> None:
        write_manifest(self.repo, "package.json", {"name": "not-a-bundle", "version": "1.0.0"})
        self.assertEqual(self.report().errors, [])

    def test_version_parity_with_root_manifest(self) -> None:
        write_manifest(self.repo, "plugin.json", plugin_manifest("1.0.0"))
        self.bundle()
        self.assertEqual(self.report().errors, [])
        write_manifest(
            self.repo,
            "package.json",
            {
                "name": "skills-kit",
                "version": "1.0.1",
                "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
            },
        )
        self.assertIn(
            "package.json: version=1.0.1, а в plugin.json 1.0.0",
            errors_text(self.report()),
        )


# --- CLI -------------------------------------------------------------------


class CliTests(RepoTestCase):
    def cli(self, repo: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CHECK_PY), "--repo", str(repo)],
            capture_output=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            check=False,
        )

    def test_clean_repo_exit_zero(self) -> None:
        result = self.cli(self.repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ошибок: 0", result.stdout)
        self.assertIn("проверка пройдена", result.stdout)

    def test_broken_repo_exit_one(self) -> None:
        write(self.repo / "skills/core/alpha/scripts/__pycache__/x.pyc", "junk")
        result = self.cli(self.repo)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ошибок: 1", result.stdout)
        self.assertIn("мусорный каталог __pycache__/", result.stdout)

    def test_verbose_shows_baseline(self) -> None:
        write(
            self.repo / "skills/core/plan/SKILL.md",
            skill_text("plan", "Exploratory QA of web apps."),
        )
        result = subprocess.run(
            [sys.executable, str(CHECK_PY), "--repo", str(self.repo), "-v"],
            capture_output=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            check=False,
        )
        self.assertIn("baseline", result.stdout)


# --- ловушка на ложное зелёное --------------------------------------------


def _inject_bad_frontmatter(root: Path) -> None:
    rewrite_skill(root, "core", "alpha", skill_text("alpha", version="1"))


def _inject_near_duplicate(root: Path) -> None:
    rewrite_skill(root, "core", "alpha", skill_text("alpha", "Открывать, когда пишется отчёт."))
    rewrite_skill(root, "code", "beta", skill_text("beta", "Use when пишется отчёт."))


def _inject_absolute_path(root: Path) -> None:
    rewrite_skill(root, "core", "alpha", skill_text("alpha", body="/Users/test/x\n"))


def _inject_secret(root: Path) -> None:
    rewrite_skill(root, "core", "alpha", skill_text("alpha", body="ghp_" + "z" * 24 + "\n"))


def _inject_broken_link(root: Path) -> None:
    rewrite_skill(root, "core", "alpha", skill_text("alpha", body="[x](missing.md)\n"))


def _inject_pycache(root: Path) -> None:
    write(root / "skills/core/alpha/scripts/__pycache__/x.pyc", "junk")


def _inject_role_without_composition(root: Path) -> None:
    rewrite_role(root, "helper", role_text().replace("## Composition", "## Другое"))


def _inject_parity_mismatch(root: Path) -> None:
    build_repo(root, summary="Всего навыков: **5** — L1: **1**, L2: **2**.")


def _inject_index_file_count(root: Path) -> None:
    write(root / "skills/core/alpha/references/extra.md", "# Extra\n")
    rewrite_skill(
        root,
        "core",
        "alpha",
        skill_text("alpha", body="- `references/extra.md`\n"),
    )


def _inject_manifest_version(root: Path) -> None:
    write_manifest(root, "plugin.json", plugin_manifest("1.0.0"))
    write_manifest(root, ".codex-plugin/plugin.json", plugin_manifest("1.0.1"))


INJECTIONS = {
    "frontmatter": _inject_bad_frontmatter,
    "description near-duplicate": _inject_near_duplicate,
    "absolute path": _inject_absolute_path,
    "secret": _inject_secret,
    "broken link": _inject_broken_link,
    "__pycache__": _inject_pycache,
    "role without Composition": _inject_role_without_composition,
    "parity L1/L2": _inject_parity_mismatch,
    "INDEX file count": _inject_index_file_count,
    "manifest version": _inject_manifest_version,
}


class FalseGreenTrapTests(unittest.TestCase):
    def test_clean_repo_is_green_then_every_injection_turns_red(self) -> None:
        for label, inject in INJECTIONS.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as tmp:
                    repo = Path(tmp)
                    build_repo(repo)
                    clean = check.run(repo)
                    self.assertEqual(clean.errors, [], f"{label}: чистый репозиторий не зелёный")
                    inject(repo)
                    broken = check.run(repo)
                    self.assertTrue(
                        broken.errors,
                        f"{label}: подложенное нарушение не поймано (ложное зелёное)",
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
