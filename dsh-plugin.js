/**
 * Пакет навыков для DeepSeek Harness.
 *
 * Регистрирует `skills/<группа>/<навык>/SKILL.md` как bundled-провайдер
 * реестра навыков: каталог сессии показывает все навыки репозитория, а тело
 * грузится по запросу. Файлы читаются из установленного пакета, поэтому
 * каталог навыков, патч и этот модуль едут вместе.
 *
 * Провайдер ничего не импортирует из DSH: контракт — `list()` и `get()`,
 * поля кандидата и определения описаны в `@deepseek-ai/dsh-skill`.
 */

import { readFile, readdir } from 'node:fs/promises'
import { join, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('.', import.meta.url))
const GROUPS = ['core', 'git', 'code']
const PROVIDER = 'skills-kit'
/** Ранг bundled-провайдеров DSH: ниже локальных проектных и пользовательских корней. */
const RANK = 600
const INVOCATION = Object.freeze({ modelInvocable: true, userInvocable: true })
const SKILL_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/

/**
 * Разобрать YAML-frontmatter навыка.
 * @param {string} text полный текст `SKILL.md`.
 * @returns {{fields: Record<string, string>, body: string} | null} поля и тело без блока; null — блока нет.
 */
function parseFrontmatter(text) {
  const match = FRONTMATTER.exec(text)
  if (match === null) return null
  const fields = {}
  for (const line of match[1].split(/\r?\n/)) {
    if (line.startsWith(' ') || line.startsWith('\t') || line.startsWith('-')) continue
    const colon = line.indexOf(':')
    if (colon < 1) continue
    fields[line.slice(0, colon).trim()] = unquote(line.slice(colon + 1).trim())
  }
  return { fields, body: text.slice(match[0].length) }
}

/**
 * Снять кавычки YAML-скаляра.
 * @param {string} value значение как в файле.
 * @returns {string} значение без обрамляющих кавычек.
 */
function unquote(value) {
  if (value.length < 2) return value
  const quote = value[0]
  if ((quote !== '"' && quote !== "'") || !value.endsWith(quote)) return value
  const inner = value.slice(1, -1)
  return quote === '"' ? inner.replace(/\\"/g, '"') : inner.replace(/''/g, "'")
}

/**
 * Кандидат каталога по одному навыку; null — навык пропускается.
 * @param {string} group группа навыков.
 * @param {string} name имя навыка (оно же имя каталога).
 * @returns {Promise<object | null>} кандидат реестра или null.
 */
async function describe(group, name) {
  const dir = join(ROOT, 'skills', group, name)
  const file = join(dir, 'SKILL.md')
  let parsed
  try {
    parsed = parseFrontmatter(await readFile(file, 'utf8'))
  } catch {
    return null
  }
  if (parsed === null) return null
  if (parsed.fields.name !== undefined && parsed.fields.name !== name) return null
  const description = parsed.fields.description?.trim()
  if (!description) return null
  return {
    name,
    description,
    invocation: INVOCATION,
    provider: PROVIDER,
    source: 'bundled',
    path: file,
    resourceBase: { kind: 'directory', path: dir + sep },
    rank: RANK,
    locator: { file },
  }
}

/**
 * Собрать каталог по всем группам.
 * @returns {Promise<object[]>} кандидаты в порядке имён.
 */
async function discover() {
  const candidates = []
  for (const group of GROUPS) {
    let entries
    try {
      entries = await readdir(join(ROOT, 'skills', group), { withFileTypes: true })
    } catch {
      continue
    }
    for (const entry of entries) {
      if (!entry.isDirectory() || !SKILL_NAME.test(entry.name)) continue
      const candidate = await describe(group, entry.name)
      if (candidate !== null) candidates.push(candidate)
    }
  }
  return candidates.sort((left, right) => left.name.localeCompare(right.name))
}

/** Провайдер реестра навыков. */
const provider = {
  name: PROVIDER,
  list: () => discover(),
  /**
   * Тело навыка без frontmatter: модель получает только инструкции.
   * @param {object} candidate кандидат, выданный `list()`.
   * @returns {Promise<object>} определение навыка.
   */
  async get(candidate) {
    const text = await readFile(candidate.locator.file, 'utf8')
    const parsed = parseFrontmatter(text)
    return {
      name: candidate.name,
      description: candidate.description,
      invocation: candidate.invocation,
      provider: PROVIDER,
      source: 'bundled',
      resourceBase: candidate.resourceBase,
      content: parsed === null ? text : parsed.body,
    }
  },
}

/** Имя плагина в Loader. */
export const name = 'skills-kit'
/** Сервис, который нужен провайдеру. */
export const inject = ['skills']

/**
 * Зарегистрировать провайдер в реестре навыков.
 * @param {object} ctx контекст плагина.
 */
export function apply(ctx) {
  ctx.skills.registerProvider(() => provider)
}
