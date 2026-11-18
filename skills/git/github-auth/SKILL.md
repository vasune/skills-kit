---
name: github-auth
description: "Открывать, когда настраивается доступ к GitHub."
version: 1.2.0
author: fhfqndj
license: MIT
platforms: [linux, macos, windows]
metadata:
  tags: [GitHub, Authentication, Git, gh-cli, SSH, Setup]
  related_skills: [github-pr-workflow, github-code-review, github-issues, github-repo-management]
---

# Настройка доступа к GitHub

Навык про то, как выдать агенту доступ к репозиториям GitHub, PR, issues и CI. Два пути:

- **`git` (есть всегда)** — HTTPS-токен (personal access token) или SSH-ключ;
- **`gh` CLI (если установлен)** — более широкий доступ к API GitHub и проще с авторизацией.

## С чего начать: проверка

Когда просят работать с GitHub, сначала прогнать:

```bash
# Check what's available
git --version
gh --version 2>/dev/null || echo "gh not installed"

# Check if already authenticated
gh auth status 2>/dev/null || echo "gh not authenticated"
git config --global credential.helper 2>/dev/null || echo "no git credential helper"
```

**Дерево решений:**

1. `gh auth status` показывает авторизацию → всё готово, дальше использовать `gh`.
2. `gh` установлен, но не авторизован → метод «gh auth» ниже.
3. `gh` не установлен → метод «только git» ниже (sudo не нужен).

---

## Метод 1: только git (без gh и без sudo)

Работает на любой машине, где есть `git`. Права root не нужны.

### Вариант A: HTTPS с personal access token (рекомендуется)

Самый переносимый способ: работает везде, настройка SSH не нужна.

**Шаг 1. Создать personal access token**

Пользователь открывает **https://github.com/settings/tokens**:

- «Generate new token (classic)»;
- имя, например «agent-<имя-машины>»;
- scopes:
  - `repo` (полный доступ к репозиторию — чтение, запись, push, PR);
  - `workflow` (запуск и управление GitHub Actions);
  - `read:org` (если работа идёт с репозиториями организации);
- срок жизни (90 дней — разумное умолчание);
- скопировать токен: второй раз он не показывается.

**Шаг 2. Настроить хранение токена в git**

```bash
# Set up the credential helper to cache credentials
# "store" saves to ~/.git-credentials in plaintext (simple, persistent)
git config --global credential.helper store

# Now do a test operation that triggers auth — git will prompt for credentials
# Username: <their-github-username>
# Password: <paste the personal access token, NOT their GitHub password>
git ls-remote https://github.com/<their-username>/<any-repo>.git
```

После одного ввода креды сохраняются и используются дальше.

**Альтернатива: helper `cache` (креды живут в памяти)**

```bash
# Cache in memory for 8 hours (28800 seconds) instead of saving to disk
git config --global credential.helper 'cache --timeout=28800'
```

**Альтернатива: токен прямо в URL remote (для одного репозитория)**

```bash
# Embed token in the remote URL (avoids credential prompts entirely)
git remote set-url origin https://<username>:<token>@github.com/<owner>/<repo>.git
```

**Шаг 3. Настроить идентичность git**

```bash
# Required for commits — set name and email
git config --global user.name "Their Name"
git config --global user.email "their-email@example.com"
```

**Шаг 4. Проверить**

```bash
# Test push access (this should work without any prompts now)
git ls-remote https://github.com/<their-username>/<any-repo>.git

# Verify identity
git config --global user.name
git config --global user.email
```

### Вариант B: доступ по SSH-ключу

Годится, когда пользователь предпочитает SSH или ключи уже заведены.

**Шаг 1. Проверить, есть ли ключи**

```bash
ls -la ~/.ssh/id_*.pub 2>/dev/null || echo "No SSH keys found"
```

**Шаг 2. Создать ключ, если его нет**

```bash
# Generate an ed25519 key (modern, secure, fast)
ssh-keygen -t ed25519 -C "their-email@example.com" -f ~/.ssh/id_ed25519 -N ""

# Display the public key for them to add to GitHub
cat ~/.ssh/id_ed25519.pub
```

Публичный ключ добавляется на **https://github.com/settings/keys**:

- «New SSH key»;
- вставить содержимое публичного ключа;
- заголовок вроде «agent-<имя-машины>».

**Шаг 3. Проверить соединение**

```bash
ssh -T git@github.com
# Expected: "Hi <username>! You've successfully authenticated..."
```

**Шаг 4. Переключить git на SSH для GitHub**

```bash
# Rewrite HTTPS GitHub URLs to SSH automatically
git config --global url."git@github.com:".insteadOf "https://github.com/"
```

**Шаг 5. Настроить идентичность git**

```bash
git config --global user.name "Their Name"
git config --global user.email "their-email@example.com"
```

---

## Метод 2: авторизация через gh CLI

Если `gh` установлен, он закрывает и API, и креды git одним шагом.

### Интерактивный вход через браузер (десктоп)

> **ГРАБЛИ (сессии, где агент ведёт gh на Windows):** когда `gh auth login` идёт через pty в фоновом процессе, ответы подавать через `process(submit)` и никогда через `process(write)` с одиноким `\n`. Enter в Windows-PTY (ConPTY/pywinpty) — это возврат каретки; один `\n` терминатором строки не считается, поэтому вопрос gh «Press Enter to open the browser» (блокирующее чтение строки) молча не завершается и вход виснет. Учесть и то, что браузер из фоновой сессии может не открыться на десктопе пользователя: тогда переходить к device flow ниже.

```bash
gh auth login
# Select: GitHub.com
# Select: HTTPS
# Authenticate via browser
```

### Ручной OAuth device flow (TTY не нужен — проверено)

Запасной путь, когда интерактивный вход невозможен (сессия ведётся агентом, браузера нет, headless). Используется публичный client id gh; пользователь вводит код на github.com/login/device. Документированный минимум для `gh auth login --with-token` — scopes `repo,read:org,gist`; `,workflow` добавлять только если надо пушить файлы workflow.

```bash
# 1. Request a device code (gh's official client_id)
RESP=$(curl -s -X POST -H "Accept: application/json" \
  -d "client_id=178c6fc778ccc68e1d6a&scope=repo,read:org,gist" \
  https://github.com/login/device/code)
DEVICE_CODE=$(echo "$RESP" | sed 's/.*"device_code":"\([^"]*\)".*/\1/')
USER_CODE=$(echo "$RESP" | sed 's/.*"user_code":"\([^"]*\)".*/\1/')
INTERVAL=$(echo "$RESP" | sed 's/.*"interval":\([0-9]*\).*/\1/'); INTERVAL=${INTERVAL:-5}
echo "Tell the user: go to https://github.com/login/device and enter code: $USER_CODE"

# 2. Poll for the token (respect interval; +5s on slow_down; ~15 min expiry).
#    Run this loop as a background process and show the user the code first.
while true; do
  sleep "$INTERVAL"
  POLL=$(curl -s -X POST -H "Accept: application/json" \
    -d "client_id=178c6fc778ccc68e1d6a&device_code=${DEVICE_CODE}&grant_type=urn:ietf:params:oauth:grant-type:device_code" \
    https://github.com/login/oauth/access_token)
  case "$POLL" in
    *access_token*)
      # Never echo the token; pipe it straight into gh.
      # timeout guards the headless-keyring hang (see pitfall below) —
      # on exit 124, fall back to writing ~/.config/gh/hosts.yml directly.
      echo "$POLL" | sed 's/.*"access_token":"\([^"]*\)".*/\1/' | timeout 20 gh auth login --with-token \
        || { echo "WITH_TOKEN_HUNG_OR_FAILED — use the hosts.yml fallback below"; exit 1; }
      gh auth setup-git
      gh auth status
      echo "LOGIN_COMPLETE"; break ;;
    *authorization_pending*) ;;                      # keep polling
    *slow_down*) INTERVAL=$((INTERVAL + 5)) ;;       # back off per GitHub docs
    *expired_token*) echo "CODE_EXPIRED — restart the flow"; exit 1 ;;
    *access_denied*) echo "USER_DENIED"; exit 1 ;;
    *) echo "UNEXPECTED: $POLL"; exit 1 ;;
  esac
done
```

Замечание: при установке через winget на Windows gh лежит в `/c/Program Files/GitHub CLI` — добавить в PATH в той же оболочке: `export PATH="$PATH:/c/Program Files/GitHub CLI"`.

> **ГРАБЛИ (headless Linux): `gh auth login --with-token` может висеть бесконечно.**
> На машинах без keyring (VPS, контейнеры, нет сессии dbus) хранилище кредов gh
> может ждать секрет-сервис без конца — даже с `--insecure-storage` и без вывода.
> Если команда не вернулась примерно за 20 секунд (оборачивать в `timeout 20 …`,
> чтобы это увидеть), пропускай механизм входа gh и запиши хранилище напрямую:
>
> ```bash
> # $TOKEN = the access token from the device flow above (never echo it)
> mkdir -p ~/.config/gh
> LOGIN=$(curl -s -H "Authorization: token ***" https://api.github.com/user \
>   | sed 's/.*"login": *"\([^"]*\)".*/\1/')
> printf 'github.com:\n    users:\n        %s:\n            oauth_token: %s\n    git_protocol: https\n    oauth_token: %s\n    user: %s\n' \
>   "$LOGIN" "$TOKEN" "$TOKEN" "$LOGIN" > ~/.config/gh/hosts.yml
> chmod 600 ~/.config/gh/hosts.yml
> gh auth status          # reads hosts.yml directly — verifies without the keyring
> gh auth setup-git       # wires the git credential helper (does not hang)
> ```
>
> `gh auth status` и `setup-git` читают файловое хранилище, keyring не трогают,
> поэтому работают сразу. Проверено на headless x86_64 VPS (gh 2.97.0, август
> 2026) после двух зависаний `--with-token`.

### Вход по токену (headless и SSH-серверы)

```bash
echo "<THEIR_TOKEN>" | gh auth login --with-token

# Set up git credentials through gh
gh auth setup-git
```

Если `--with-token` зависает и здесь, использовать запасной путь через `hosts.yml` из граблей выше.

### Проверка

```bash
gh auth status
```

---

## Метод 3: доступ с сервера выката (клон + приватный реестр)

Два разных доступа, их не путать: **deploy-ключ** даёт серверу `git` (read-only), **PAT** даёт тянуть
приватные образы из GHCR. Ни один не должен лежать в репозитории или в истории чата.

### git на сервере — deploy-ключ

```bash
# на сервере
ssh-keygen -t ed25519 -N "" -f ~/.ssh/gh_deploy
cat ~/.ssh/gh_deploy.pub

# на машине агента: добавить ключ в репозиторий, только на чтение
gh api -X POST /repos/<owner>/<repo>/keys -f title=deploy-key \
  -f key="$(cat key.pub)" -F read_only=true

# на сервере: без этого файла `git fetch` в CI-шаге падает,
# хотя разовое клонирование с GIT_SSH_COMMAND работало
printf 'Host github.com\n  IdentityFile ~/.ssh/gh_deploy\n  StrictHostKeyChecking accept-new\n' > ~/.ssh/config
chmod 600 ~/.ssh/config
```

### Приватные образы — GHCR

Нужен **classic PAT с единственным scope `read:packages`** (fine-grained для пакетов не подходит).
`-u` — это логин **владельца токена**, а не название организации.

```bash
echo "$GHCR_PULL_TOKEN" | docker login ghcr.io -u "$GHCR_PULL_USER" --password-stdin
# ... деплой ...
docker logout ghcr.io        # не оставлять креды на машине
```

В CI токен хранится секретом репозитория (`gh secret set GHCR_PULL_TOKEN < файл`), а сервер получает его только на время
выката; значение не печатать в чат.

**Проверка, что образ именно скачан, а не собран локально:**

```bash
docker images --digests | grep "$TAG"     # RepoDigest sha256:… заполнен → скачан; пусто → собран
```

Права на пуши в GHCR выдаёт `permissions: packages: write` в workflow; `GITHUB_TOKEN` для этого
достаточно, отдельный PAT нужен только читающей стороне.

---

## API GitHub без gh

Когда `gh` недоступен, полный API GitHub доступен через `curl` с personal access token. Так сделаны
запасные пути в остальных навыках про GitHub.

### Токен для вызовов API

```bash
# Option 1: Export as env var (preferred — keeps it out of commands)
export GITHUB_TOKEN="<token>"

# Then use in curl calls:
curl -s -H "Authorization: token ***" \
  https://api.github.com/user
```

### Достать токен из кредов git

Если креды git уже настроены (через `credential.helper store`), токен можно вытащить:

```bash
# Read from the git credential store
printf 'protocol=https\nhost=github.com\n' | GIT_TERMINAL_PROMPT=0 git credential fill | sed -n 's/^password=//p'
```

Если токен лежит в окружении или файле хоста (а не в git-кредедах), способ его взять — по инструкции своего хоста.

### Помощник: определить способ доступа

Этот блок ставится в начало любого рабочего процесса с GitHub:

```bash
# Try gh first, fall back to git + curl
if command -v gh &>/dev/null && gh auth status &>/dev/null; then
  echo "AUTH_METHOD=gh"
elif [ -n "$GITHUB_TOKEN" ]; then
  echo "AUTH_METHOD=curl"
elif GITHUB_TOKEN=$(printf 'protocol=https\nhost=github.com\n' | GIT_TERMINAL_PROMPT=0 git credential fill 2>/dev/null | sed -n 's/^password=//p') && [ -n "$GITHUB_TOKEN" ]; then
  export GITHUB_TOKEN
  echo "AUTH_METHOD=curl"
else
  echo "AUTH_METHOD=none"
  echo "Need to set up authentication first"
fi
```

---

## Если не работает

| Проблема | Что делать |
|---------|----------|
| `git push` спрашивает пароль | GitHub отключил вход по паролю. В поле пароля — personal access token либо переход на SSH |
| `remote: Permission to X denied` | У токена нет scope `repo` — перевыпустить с нужными scopes |
| `fatal: Authentication failed` | Сохранённые креды устарели — `git credential reject`, затем авторизоваться заново |
| `ssh: connect to host github.com port 22: Connection refused` | Попробовать SSH через порт HTTPS: добавить в `~/.ssh/config` `Host github.com` с `Port 443` и `Hostname ssh.github.com` |
| Креды не сохраняются | Проверить `git config --global credential.helper` — там должно быть `store` или `cache` |
| Несколько аккаунтов GitHub | SSH с разными ключами по алиасам хоста в `~/.ssh/config` либо креды в URL на уровне репозитория |
| `gh` отдаёт `HTTP 404: Not Found` на существующий приватный репозиторий организации | `gh` ходит в API от **активного** аккаунта, а у него может не быть доступа к организации, тогда как git пушит токеном другого аккаунта из helper. Ограничить одну команду: `GH_TOKEN=$(gh auth token --user <account>) gh run list` (тот же префикс для `view`/`watch`/`download`). Токен не печатать; какой аккаунт использует git — смотреть через `printf 'protocol=https\nhost=github.com\n\n' \| GIT_TERMINAL_PROMPT=0 git credential fill` |
| `gh repo view owner/repo` говорит GraphQL `Could not resolve to a Repository`, хотя репозиторий есть (приватный, принадлежит другому залогиненному аккаунту) | Та же причина: активный аккаунт его не видит. Когда следующие команды относятся к тому владельцу, переключить всю сессию: `gh auth switch --user <owner>`; для одной команды — префикс `GH_TOKEN=...` |
| Push или клон приватного репозитория другого аккаунта отвечает 404, хотя токен активного аккаунта рабочий | Прибить локальный helper репозитория к токену владельца: `git config --local credential.helper '!f() { test "$1" = get && printf "username=x-access-token\npassword=%s\n" "$(gh auth token --user <owner>)"; }; f'` — глобальный helper gh следует за активным аккаунтом и молча переключается под тобой |
| `gh: command not found`, sudo нет | Использовать метод 1 (только git) — установка не нужна |
