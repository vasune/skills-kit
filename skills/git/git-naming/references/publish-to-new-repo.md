# Публикация проекта в новый репозиторий (копия под новым именем)

Случай: есть рабочая копия проекта (часто «демо»), нужно опубликовать его в новом репозитории с другим именем, чистой историей и постоянной локальной папкой. Путь `--orphan` из SKILL.md — для случая, когда репозиторий остаётся тем же деревом; здесь дерево копируется.

## 0. Решения до команд

Все вопросы человеку — одним списком сразу:

- имя репозитория (кандидаты формулировать за владельца, с рекомендацией);
- приватный/публичный;
- история: один `initial commit` или перенос прежних коммитов;
- путь локальной копии (рядом с остальными проектами владельца — обычно `<projects>/<имя>`);
- судьба старого репозитория: оставить / архивировать / удалить.

## 1. Осмотр источника

```bash
grep -rn "<старое-имя>" --include="*.ts" --include="*.tsx" --include="*.json" \
  --include="*.md" --include="*.yml" . --exclude-dir=node_modules --exclude-dir=dist --exclude=package-lock.json
git ls-files | wc -l
git ls-files | grep -iE 'deploy\.md|(^|/)\.env|dist/'
```

README, `package.json`, `docker-compose.yml` — главные места самоупоминаний.

## 2. Копия и переименование

```bash
SRC=<старое-дерево>; DST=<projects>/<новое-имя>
mkdir -p "$DST"
rsync -a --exclude '.git' --exclude 'node_modules' --exclude 'dist' "$SRC/" "$DST/"
cd "$DST"
sed -i '' 's/<старое-имя>/<новое-имя>/g' package.json docker-compose.yml README.md
printf '\n# Local env\n.env\n.env.*\n!.env.example\n' >> .gitignore
```

## 3. Проверки до коммита

```bash
npm ci
npm run lint
npm run typecheck
npm run build
```

Каждый вывод смотреть целиком: `tail` скрывает первую ошибку в списке, а exit-код после пайпа показывает код `tail`, не `npm`.

## 4. Локальный репозиторий

```bash
git init -b master -q
git config --local user.name "<аккаунт-владельца>"
git config --local user.email "<email коммитов>"
git add -A
git diff --cached --name-only | grep -iE 'node_modules|dist/|(^|/)\.env$' || echo "suspicious: none"
git commit -m "initial commit"     # ровно текст владельца
git log --oneline
git status --short --branch
```

## 5. Удалённый репозиторий

```bash
gh repo create <имя> --private \
  --description "<описание проекта>" \
  --source . --remote origin --push

gh api -X PATCH repos/<owner>/<repo> -f default_branch=master --jq '.default_branch'

# topics задаются одним вызовом и заменяют весь список
gh api --method PUT repos/<owner>/<repo>/topics \
  -f "names[]=react" -f "names[]=vite" -f "names[]=typescript" --jq '.names'
```

`gh repo edit --add-topic` делает то же самое, но длинный список флагов иногда отклоняется до запуска как «долгоживущий процесс» — API-форма идемпотентна и проходит одной командой.

## 6. Проверка результата по API

```bash
gh repo view <owner>/<repo> --json name,owner,visibility,defaultBranchRef,description,url \
  --jq '{name,owner:.owner.login,visibility,default:.defaultBranchRef.name,url}'
gh api "repos/<owner>/<repo>/git/trees/master?recursive=1" --jq '[.tree[]|select(.type=="blob")]|length'
gh api repos/<owner>/<repo>/commits --jq 'length'
git rev-parse HEAD origin/master   # хеши должны совпасть
```

Число блобов сверить с `git ls-files | wc -l` в локальной папке.

## 7. Документация

- Переименовать файл заметки проекта под новое имя, поправить `[[ссылку]]` в индексной заметке раздела, обновить путь запуска, remote, идентичность коммитов.
- Старый репозиторий оставить в заметке отдельной строкой: он остаётся историей разработки.
- Исторические блоки «что проверено» не переписывать — они датированы и описывают прежнее состояние.
