#!/usr/bin/env bash
# Раскладка навыков репозитория по каталогам агента.
#   ./scripts/install.sh --target list
#   ./scripts/install.sh --target all [--pack core,code] [--force] [--dry-run]
#   ./scripts/install.sh --target claude|opencode|dsh|codex|gemini|cursor|copilot|kiro|windsurf
#   ./scripts/install.sh --target /абсолютный/путь [--mode copy|link] [--pack …] [--force] [--dry-run]
#   ./scripts/install.sh --target <цель> --verify [--dry-run]
# По умолчанию копирует: поиск навыков идёт обходом каталога, а символические
# ссылки на каталоги такой обход не видит — ни дерево, ни отдельный навык.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS="$REPO/skills"
TARGET=""
MODE="copy"
FORCE=0
DRY=0
PACK="all"
VERIFY=0
VERIFY_OK=1
TOTAL=0
conflicts=0

usage() {
  cat <<'EOF'
Использование: ./scripts/install.sh --target <цель> [флаги]

Цели:
  list        таблица известных целей: путь к каталогу навыков, есть ли он, и
              группы навыков с числом навыков в каждой
  all         установить во все существующие каталоги хостов (новые не создаёт)
  claude      ~/.claude/skills/<навык> (каталог создаётся)
  opencode    ~/.config/opencode/skill/<навык> (каталог создаётся)
  dsh         $DSH_HOME/skills/<навык>, по умолчанию ~/.dsh/skills
              (каталог создаётся; для DSH предпочтительнее пакет-бандл,
              см. README — тогда копия не нужна)
  codex       ~/.codex/skills/<навык> (каталог должен существовать)
  gemini      ~/.gemini/skills/<навык> (каталог должен существовать)
  cursor      .cursor/skills/<навык> в репозитории (проектный, должен существовать)
  copilot     .github/skills/<навык> в репозитории (проектный, должен существовать)
  kiro        .kiro/skills/<навык> в репозитории (проектный, должен существовать)
  windsurf    нет нативного каталога навыков: правила задаются настройками хоста
  <каталог>   произвольный каталог навыков (абсолютный путь)

Флаги:
  --mode copy|link   копии (по умолчанию) или символические ссылки.
                     link годится только для инструментов, которые обходят
                     каталог по ссылкам
  --pack <группы>    подмножество навыков по группам: core, core,code,git или
                     all (по умолчанию — все группы). Неизвестная группа —
                     ошибка с их списком
  --force            перезаписать уже существующий навык (репозиторий —
                     источник истины, поэтому перезапись ожидаема)
  --dry-run          показать план, ничего не менять
  --verify           после установки запустить scripts/verify_install.py для этой
                     цели (или отдельным вызовом без установки). С --target all
                     проверяет все существующие каталоги; с --dry-run только
                     печатает, что проверит
  -h, --help         эта справка
EOF
}

target_path() {
  case "$1" in
    claude)   echo "$HOME/.claude/skills" ;;
    opencode) echo "$HOME/.config/opencode/skill" ;;
    dsh)      echo "${DSH_HOME:-$HOME/.dsh}/skills" ;;
    codex)    echo "$HOME/.codex/skills" ;;
    gemini)   echo "$HOME/.gemini/skills" ;;
    cursor)   echo "$REPO/.cursor/skills" ;;
    copilot)  echo "$REPO/.github/skills" ;;
    kiro)     echo "$REPO/.kiro/skills" ;;
    *)        echo "" ;;
  esac
}

# Каталоги, которые исторически создаются самим install.sh: claude, opencode, dsh.
# Остальные именованные цели требуют существующего каталога.

pretty_path() {
  case "$1" in
    "$REPO"/*) echo "${1#"$REPO"/}" ;;
    "$HOME"/*) echo "~${1#"$HOME"}" ;;
    *) echo "$1" ;;
  esac
}

show_groups() {
  local group dir count total=0 joined=""
  for group in "${groups[@]}"; do
    count=0
    for dir in "$SKILLS/$group"/*/; do
      [ -f "${dir}SKILL.md" ] && count=$((count + 1))
    done
    joined+="${group} (${count}), "
    total=$((total + count))
  done
  echo
  echo "группы (${total} навыков): ${joined%, }"
}

show_targets() {
  local name path state
  printf '%s\n' "цель | путь | состояние"
  for name in claude opencode dsh codex gemini cursor copilot kiro; do
    path="$(target_path "$name")"
    if [ -d "$path" ]; then
      state="каталог есть"
    else
      state="каталога нет"
    fi
    case "$name" in
      claude|opencode|dsh) state="$state, install создаст" ;;
      cursor|copilot|kiro) state="$state, проектный, не создаётся" ;;
      *)               state="$state, не создаётся" ;;
    esac
    printf '%s | %s | %s\n' "$name" "$(pretty_path "$path")" "$state"
  done
  printf '%s | %s | %s\n' "windsurf" "—" "нет нативного каталога навыков, см. README"
  echo
  echo "all ставит только в существующие каталоги; произвольный каталог можно"
  echo "задать явно абсолютным путём: --target /path/to/skills."
  show_groups
}

run() {
  if [ "$DRY" -eq 1 ]; then echo "  [dry-run] $*"; else "$@"; fi
}

require_dir() {
  local name="$1" path="$2"
  if [ -d "$path" ]; then
    return 0
  fi
  echo "нет каталога $(pretty_path "$path") для цели $name." >&2
  echo "Создай его сам или укажи каталог явно абсолютным путём:" >&2
  echo "  ./scripts/install.sh --target /path/to/skills" >&2
  exit 1
}

# Плоская раскладка: инструменты ищут навык по имени каталога.
install_flat() {
  local root="$1"
  shift
  local count=0
  run mkdir -p "$root"
  for group in "$@"; do
    for dir in "$SKILLS/"$group/*/; do
      [ -f "${dir}SKILL.md" ] || continue
      local name dest
      name="$(basename "$dir")"
      dest="$root/$name"
      if [ -e "$dest" ] || [ -L "$dest" ]; then
        if [ "$FORCE" -eq 0 ]; then
          echo "  ! занято: $dest (перезаписать — с --force)" >&2
          conflicts=$((conflicts + 1)); continue
        fi
        run rm -rf "$dest"
      fi
      if [ "$MODE" = "link" ]; then
        run ln -s "${dir%/}" "$dest"
      else
        if [ "$DRY" -eq 1 ]; then echo "  [dry-run] cp -R ${dir%/} $dest"; else
          cp -R "${dir%/}" "$dest"
        fi
      fi
      count=$((count + 1))
    done
  done
  echo "  навыков: $count → $(pretty_path "$root") ($MODE)"
  TOTAL=$((TOTAL + count))
}

install_all() {
  local name path skipped=0
  for name in claude opencode dsh codex gemini cursor copilot kiro; do
    path="$(target_path "$name")"
    if [ ! -d "$path" ]; then
      echo "  - $name: $(pretty_path "$path") — каталога нет, пропущено"
      skipped=$((skipped + 1))
      continue
    fi
    echo "цель: $name → $(pretty_path "$path")"
    install_flat "$path" "${selected[@]}"
  done
  echo
  echo "цель: windsurf — нет нативного каталога навыков, см. README."
  if [ "$skipped" -gt 0 ]; then
    echo "пропущено целей: $skipped"
  fi
  echo "всего навыков разложено: $TOTAL"
}

verify_one() {
  local target="$1"
  if [ "$DRY" -eq 1 ]; then
    echo "  [dry-run] python3 scripts/verify_install.py --target $target --repo $REPO"
    return 0
  fi
  echo
  echo "проверка установки: $target"
  if ! python3 "$REPO/scripts/verify_install.py" --target "$target" --repo "$REPO"; then
    VERIFY_OK=0
  fi
}

verify_all() {
  local name path
  for name in claude opencode dsh codex gemini cursor copilot kiro; do
    path="$(target_path "$name")"
    [ -d "$path" ] || continue
    verify_one "$name"
  done
}

while [ $# -gt 0 ]; do
  case "$1" in
    --target)
      [ $# -ge 2 ] || { echo "после --target нужна цель" >&2; exit 2; }
      TARGET="$2"; shift 2 ;;
    --mode)
      [ $# -ge 2 ] || { echo "после --mode нужен режим" >&2; exit 2; }
      MODE="$2"; shift 2 ;;
    --pack)
      [ $# -ge 2 ] || { echo "после --pack нужен список групп" >&2; exit 2; }
      PACK="$2"; shift 2 ;;
    --force)  FORCE=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --verify) VERIFY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "неизвестный аргумент: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$TARGET" ] || { echo "не указан --target" >&2; usage >&2; exit 2; }
case "$MODE" in copy|link) ;; *) echo "--mode: только copy или link" >&2; exit 2 ;; esac
[ -d "$SKILLS" ] || { echo "нет каталога skills/ в $REPO" >&2; exit 1; }

groups=()
for d in "$SKILLS"/*/; do groups+=("$(basename "$d")"); done

# --pack: подмножество групп. Неизвестная группа — exit 2 со списком доступных;
# без флага ставим все группы, как раньше.
if [ "$PACK" = "all" ]; then
  selected=("${groups[@]}")
else
  selected=()
  requested=()
  IFS=',' read -r -a requested <<< "$PACK" || true
  if [ "${#requested[@]}" -eq 0 ]; then
    echo "--pack: пустой список групп" >&2; exit 2
  fi
  for raw in "${requested[@]}"; do
    name="$(printf '%s' "$raw" | tr -d '[:space:]')"
    [ -n "$name" ] || continue
    found=0
    for group in "${groups[@]}"; do
      [ "$group" = "$name" ] && { found=1; break; }
    done
    if [ "$found" -eq 0 ]; then
      available="$(printf '%s, ' "${groups[@]}")"
      echo "неизвестная группа: $name" >&2
      echo "доступные группы: ${available%, }" >&2
      exit 2
    fi
    selected+=("$name")
  done
  if [ "${#selected[@]}" -eq 0 ]; then
    echo "--pack: пустой список групп" >&2; exit 2
  fi
fi

echo "репозиторий: $REPO"
case "$TARGET" in
  list)     show_targets ;;
  claude|opencode|dsh)
    install_flat "$(target_path "$TARGET")" "${selected[@]}" ;;
  codex|gemini|cursor|copilot|kiro)
    require_dir "$TARGET" "$(target_path "$TARGET")"
    install_flat "$(target_path "$TARGET")" "${selected[@]}" ;;
  windsurf)
    echo "windsurf: нет нативного каталога навыков — правила задаются настройками"
    echo "хоста, а не папкой SKILL.md. Подробности — README, раздел «Подключение"
    echo "к другим агентам»." ;;
  all)      install_all ;;
  /*)       install_flat "$TARGET" "${selected[@]}" ;;
  *)
    echo "неизвестная цель: $TARGET" >&2
    echo "Цели: list, all, claude, opencode, dsh, codex, gemini, cursor," >&2
    echo "copilot, kiro, windsurf или абсолютный путь." >&2
    exit 2 ;;
esac

if [ "$VERIFY" -eq 1 ]; then
  case "$TARGET" in
    list|windsurf)
      echo "цель $TARGET не устанавливает навыки — проверка не нужна" ;;
    all) verify_all ;;
    *)   verify_one "$TARGET" ;;
  esac
  if [ "$VERIFY_OK" -eq 0 ]; then
    echo "проверка не прошла" >&2
    exit 1
  fi
fi

if [ "$conflicts" -gt 0 ]; then
  echo "конфликтов: $conflicts — занятые имена оставлены как есть" >&2
fi
echo "готово"
