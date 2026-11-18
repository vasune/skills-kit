#!/usr/bin/env python3
"""Плоская поставка навыков для любого агента.

    python3 scripts/pack.py [--out dist] [--clean]
    python3 scripts/pack.py --release [--out dist] [--clean] [--allow-dirty]

Собирает dist/skills/<имя>/ — каталог навыка целиком (SKILL.md плюс references/,
scripts/, templates/ рядом), а не skills/<группа>/<навык>/. Такую раскладку
понимают инструменты, которые ищут навык по каталогу (в том числе
`npx skills add`-подобный импорт). Рядом кладутся dist/README.md со списком
навыков и dist/INDEX.md с путями и триггерами из корневого INDEX.md.

`--release` собирает поставку из **закоммиченного** дерева (`git archive HEAD`):
грязное рабочее дерево останавливает сборку, обойти можно флагом `--allow-dirty`
(всё равно соберётся HEAD). Без git — как раньше, из текущего дерева.
Дополнительно копируются пять манифестов плагина, версии сверяются с
plugin.json, всё упаковывается в dist/skills-kit-<version>.zip. Последней
строкой в stdout печатается путь к zip — его берёт release-workflow.

Единственный источник версии — plugin.json в корне. dist/ не коммитится
(см. .gitignore): это артефакт поставки, а не источник.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
INDEX = REPO / "INDEX.md"
JUNK = {"__pycache__", ".DS_Store", ".pytest_cache", ".git"}
JUNK_SUFFIXES = (".pyc",)

# Манифесты, которые едут в релиз. Первый — источник версии.
MANIFESTS = (
    Path("plugin.json"),
    Path(".claude-plugin/plugin.json"),
    Path(".claude-plugin/marketplace.json"),
    Path(".codex-plugin/plugin.json"),
    Path(".agents/plugins/marketplace.json"),
)

INDEX_ROW = re.compile(
    r"^\|\s*\[`([a-z0-9-]+)`\]\(skills/[a-z0-9-]+/[a-z0-9-]+/SKILL\.md\)"
    r"\s*\|\s*(L[12])\s*\|\s*(.*?)\s*\|\s*\d+\s*\|",
    re.M,
)


def frontmatter_field(text: str, field: str) -> str:
    """Значение поля из YAML-frontmatter; пустая строка, если поля нет."""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end < 0:
        return ""
    for line in text[3:end].splitlines():
        if line.startswith(f"{field}:"):
            value = line.split(":", 1)[1].strip()
            return value.strip("\"'")
    return ""


def git_run(*args: str) -> subprocess.CompletedProcess[str] | None:
    """git в корне репозитория; None — git или сам репозиторий недоступны."""
    try:
        return subprocess.run(
            ["git", "-C", str(REPO), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None


def is_git_repo() -> bool:
    result = git_run("rev-parse", "--is-inside-work-tree")
    return (
        result is not None
        and result.returncode == 0
        and result.stdout.strip() == "true"
    )


def dirty_entries() -> list[str]:
    """Изменённые и неотслеживаемые пути рабочего дерева."""
    result = git_run("status", "--porcelain")
    if result is None or result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def archive_head(dest: Path) -> Path:
    """Распаковать закоммиченные skills, INDEX и манифесты; вернуть корень дерева."""
    tar_path = dest / "head.tar"
    paths = ["skills", "INDEX.md", *(rel.as_posix() for rel in MANIFESTS)]
    result = git_run(
        "archive", "--format=tar", "-o", str(tar_path), "HEAD", "--", *paths
    )
    if result is None or result.returncode != 0:
        message = result.stderr.strip() if result else "git недоступен"
        raise SystemExit(f"git archive HEAD не удался: {message}")
    tree = dest / "tree"
    tree.mkdir()
    root = tree.resolve()
    with tarfile.open(tar_path) as archive:
        for member in archive.getmembers():
            target = (tree / member.name).resolve()
            if target != root and root not in target.parents:
                raise SystemExit(f"git archive: неожиданный путь {member.name}")
        archive.extractall(tree)
    return tree


def discover(root: Path = SKILLS) -> list[tuple[str, str, Path]]:
    """[(имя, группа, каталог)] по skills/<группа>/<навык>/SKILL.md."""
    found: list[tuple[str, str, Path]] = []
    seen: dict[str, Path] = {}
    for skill_md in sorted(root.glob("*/*/SKILL.md")):
        skill_dir = skill_md.parent
        group = skill_dir.parent.name
        name = skill_dir.name
        if name in seen:
            raise SystemExit(
                f"дубль имени навыка: {name} ({seen[name]} и {skill_dir})"
            )
        seen[name] = skill_dir
        found.append((name, group, skill_dir))
    return found


def index_meta(index: Path = INDEX) -> dict[str, tuple[str, str]]:
    """{имя: (уровень, когда открывать)} из корневого INDEX.md."""
    if not index.is_file():
        return {}
    text = index.read_text(encoding="utf-8")
    return {name: (level, when) for name, level, when in INDEX_ROW.findall(text)}


def ignore_junk(_dir: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in JUNK or name.endswith(JUNK_SUFFIXES)
    }


def cell(text: str) -> str:
    """Экранировать pipe и переводы строк для markdown-таблицы."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def write_readme(out: Path, rows: list[tuple[str, str]]) -> None:
    lines = [
        "# skills-kit — плоский набор навыков",
        "",
        "Сгенерировано `scripts/pack.py`. Каждый навык — каталог `skills/<имя>/` с",
        "`SKILL.md` и вспомогательными файлами рядом: такую раскладку понимают",
        "агенты и импортёры, которые ищут навык по каталогу.",
        "",
        f"Навыков: {len(rows)}. Уровни и триггеры — в [INDEX.md](INDEX.md).",
        "",
        "| Навык | Описание |",
        "|---|---|",
    ]
    for name, description in rows:
        lines.append(
            f"| [`{name}`](skills/{name}/SKILL.md) | {cell(description)} |"
        )
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_index(
    out: Path, rows: list[tuple[str, str, str]]
) -> None:
    lines = [
        "# Каталог навыков — поставка",
        "",
        "Плоская раскладка: каждый навык лежит в `skills/<имя>/`, точка входа —",
        "`SKILL.md`. Уровни: `L1` — авторская методология, `L2` — проверенная",
        "практика.",
        "",
        "| Навык | Ур. | Когда открывать | Путь |",
        "|---|---|---|---|",
    ]
    for name, level, when in rows:
        lines.append(
            f"| [`{name}`](skills/{name}/SKILL.md) | {level} | {cell(when)} "
            f"| `skills/{name}/SKILL.md` |"
        )
    (out / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    """Прочитать JSON-манифест; любая ошибка — понятное сообщение и выход."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"нет манифеста: {path}") from None
    except json.JSONDecodeError as error:
        raise SystemExit(f"{path}: невалидный JSON ({error})") from None
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: ожидался JSON-объект")
    return data


def declared_versions(data: dict) -> list[str]:
    """Все версии манифеста: своя и у вложенных плагинов marketplace."""
    versions: list[str] = []
    if "version" in data:
        versions.append(str(data["version"]))
    for plugin in data.get("plugins", []):
        if isinstance(plugin, dict) and "version" in plugin:
            versions.append(str(plugin["version"]))
    return versions


def release_version(root: Path = REPO) -> str:
    """Версия из plugin.json — единственный источник для релиза."""
    data = read_json(root / MANIFESTS[0])
    version = str(data.get("version", "")).strip()
    if not version:
        raise SystemExit(
            f"{MANIFESTS[0]}: пустое поле version — источник версии для релиза"
        )
    return version


def check_manifest_versions(version: str, root: Path = REPO) -> None:
    """Остановиться, если версия в любом манифесте не равна version."""
    errors: list[str] = []
    for rel in MANIFESTS:
        data = read_json(root / rel)
        declared = declared_versions(data)
        if not declared:
            errors.append(f"{rel}: нет поля version")
        for value in declared:
            if value != version:
                errors.append(
                    f"{rel}: version={value}, а в {MANIFESTS[0].as_posix()} {version}"
                )
    if errors:
        raise SystemExit("версии манифестов расходятся:\n  " + "\n  ".join(errors))


def copy_manifests(out: Path, root: Path = REPO) -> None:
    """Пять манифестов — в корень поставки с сохранением относительных путей."""
    for rel in MANIFESTS:
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dest)
        dest.chmod(0o644)  # в архиве не нужны права «только владельцу»


def make_zip(out: Path, version: str) -> Path:
    """Упаковать поставку в skills-kit-<version>.zip; повторный прогон — перезапись."""
    zip_path = out / f"skills-kit-{version}.zip"
    for old in out.glob("skills-kit-*.zip"):
        old.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out.rglob("*")):
            if path.is_file() and path != zip_path:
                archive.write(path, path.relative_to(out).as_posix())
    return zip_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Плоская поставка навыков: dist/skills/<имя>/SKILL.md"
    )
    parser.add_argument(
        "--out",
        default=str(REPO / "dist"),
        help="каталог поставки (по умолчанию dist/ в корне репозитория)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="удалить каталог поставки перед сборкой",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="добавить манифесты плагина и упаковать dist/skills-kit-<version>.zip",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="собрать release из HEAD, даже если рабочее дерево изменено",
    )
    args = parser.parse_args(argv)

    src_root = REPO
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if args.release:
        if is_git_repo():
            dirty = dirty_entries()
            if dirty and not args.allow_dirty:
                shown = "\n  ".join(dirty[:10])
                tail = f"\n  … ещё {len(dirty) - 10}" if len(dirty) > 10 else ""
                print(
                    "release собирает только закоммиченное дерево, а рабочее изменено:\n"
                    f"  {shown}{tail}\n"
                    "Закоммить изменения или запусти с --allow-dirty — тогда соберётся HEAD.",
                    file=sys.stderr,
                )
                return 2
            if dirty:
                print(
                    f"внимание: дерево изменено ({len(dirty)} путей) — release собирается из HEAD",
                    file=sys.stderr,
                )
            temp_dir = tempfile.TemporaryDirectory(prefix="skills-kit-release-")
            src_root = archive_head(Path(temp_dir.name))
        else:
            print(
                "внимание: git недоступен — release собирается из текущего дерева",
                file=sys.stderr,
            )

    try:
        return build(args, src_root)
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def build(args: argparse.Namespace, src_root: Path) -> int:
    """Собрать поставку из src_root (рабочее дерево или распакованный HEAD)."""
    source_skills = src_root / "skills"
    if not source_skills.is_dir():
        print(f"нет каталога {source_skills}", file=sys.stderr)
        return 1

    skills = discover(source_skills)
    if not skills:
        print(f"в {source_skills} не найдено ни одного навыка", file=sys.stderr)
        return 1

    # Версии проверяются до очистки dist: рассинхрон не должен оставить пустой артефакт.
    version = ""
    if args.release:
        version = release_version(src_root)
        check_manifest_versions(version, src_root)

    out = Path(args.out).expanduser().resolve()
    if out == source_skills or source_skills in out.parents:
        print(f"--out не может быть внутри {source_skills}: это перемешает источник и поставку", file=sys.stderr)
        return 2
    if args.clean and out.exists():
        shutil.rmtree(out)
        print(f"очищено: {out}")
    target = out / "skills"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    meta = index_meta(src_root / "INDEX.md")
    owner_by_name = {name for name, _group, _dir in skills}
    readme_rows: list[tuple[str, str]] = []
    index_rows: list[tuple[str, str, str]] = []
    missing: list[str] = []
    for name, _group, skill_dir in skills:
        shutil.copytree(skill_dir, target / name, ignore=ignore_junk)
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        description = frontmatter_field(text, "description")
        if not description:
            description = "описание — в SKILL.md"
            missing.append(name)
        level, when = meta.get(name, ("—", "—"))
        if name not in meta:
            missing.append(name)
        readme_rows.append((name, description))
        index_rows.append((name, level, when))

    write_readme(out, readme_rows)
    write_index(out, index_rows)
    unknown = sorted(set(meta) - owner_by_name)
    if unknown:
        print(
            f"в INDEX.md есть строки без навыка: {', '.join(unknown)}",
            file=sys.stderr,
        )
    print(f"навыков: {len(skills)} → {out}")
    print(f"  {out / 'README.md'}")
    print(f"  {out / 'INDEX.md'}")
    if missing:
        print(
            f"  без описания или строки в INDEX.md: {', '.join(sorted(set(missing)))}",
            file=sys.stderr,
        )

    if args.release:
        copy_manifests(out, src_root)
        zip_path = make_zip(out, version)
        size = zip_path.stat().st_size
        print(f"версия: {version}")
        print(f"манифестов: {len(MANIFESTS)} → {out}")
        print(f"zip: {size} байт ({size / 1024:.1f} КБ)")
        print(zip_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
