#!/usr/bin/env node
/**
 * R-18 / login-gated Pixiv novel body extractor via App webview HTML.
 * Use when scripts/pixiv-novel.mjs extract returns empty content.
 *
 * Usage:
 *   node scripts/extract-r18-webview.mjs <url-or-id> [--format md|json|both] [-o <dir>] [--token-stdin]
 *
 * Security: the webview HTML is parsed by lib/js-literal.mjs, a strict literal
 * parser that never evaluates remote content (no Function/eval). Any payload
 * outside that grammar fails loudly instead of executing.
 *
 * Output: this script reuses the same managed output directory rules, overwrite
 * protection, and Markdown renderer as `pixiv-novel.mjs extract`.
 */
import { realpathSync } from 'node:fs'
import { homedir } from 'node:os'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { resolveRefreshToken } from './lib/config.mjs'
import { extractPixivNovelId, slugifyTitle } from './lib/input.mjs'
import { extractPixivValueFromHtml } from './lib/js-literal.mjs'
import { writeOutputs } from './lib/output-files.mjs'
import { getManagedOutputBaseDir, resolveManagedOutputDir } from './lib/output-paths.mjs'
import {
  cleanPixivText,
  exchangeRefreshToken,
  getNovelUrl,
  parseContent,
  resolveImagesFromEmbeddedData,
} from './lib/pixiv-api.mjs'
import { createOutputPayloads } from './lib/render.mjs'

const VALID_FORMATS = new Set(['md', 'json', 'both'])

const DEFAULT_APP_OS = 'ios'
const DEFAULT_APP_OS_VERSION = '14.6'
const DEFAULT_USER_AGENT = 'PixivIOSApp/7.13.3 (iOS 14.6; iPhone13,2)'

export const USAGE =
  'Usage: node scripts/extract-r18-webview.mjs <url-or-id> [--format md|json|both] [-o <dir>] [--token-stdin]'

function appHeaders(accessToken, env = process.env) {
  return {
    Authorization: `Bearer ${accessToken}`,
    'app-os': env.PIXIV_APP_OS || DEFAULT_APP_OS,
    'app-os-version': env.PIXIV_APP_OS_VERSION || DEFAULT_APP_OS_VERSION,
    'user-agent': env.PIXIV_USER_AGENT || DEFAULT_USER_AGENT,
  }
}

/**
 * Validate an `-o` / `--output` value with the same strength as `--format`:
 * an empty value is rejected, and a value that looks like another option
 * (leading `-`) is rejected instead of being silently used as a directory name.
 * A path that genuinely starts with `-` is still expressible as `./-name`.
 */
function validateOutputValue(value) {
  if (!value) {
    throw new Error('Invalid output path: value must not be empty (use -o <dir>)')
  }
  if (value.startsWith('-')) {
    throw new Error(
      `Invalid output path "${value}": a leading "-" is not accepted. Prefix a literal leading-dash path with ./ (e.g. -o ./-name).`
    )
  }
  return value
}

/**
 * Parse and validate CLI arguments. Throws on unknown options, missing option
 * values, unsupported `--format` values, and invalid `-o`/`--output` values so
 * callers get a non-zero exit before any network request happens.
 */
export function parseArgs(argv) {
  const options = {
    format: 'both',
    output: null,
    tokenStdin: false,
    help: false,
    positionals: [],
  }

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]

    if (arg === '-h' || arg === '--help') {
      options.help = true
      continue
    }

    if (arg === '--token-stdin') {
      options.tokenStdin = true
      continue
    }

    if (arg === '--format' || arg === '-f') {
      const next = argv[index + 1]
      if (!next || next.startsWith('-')) {
        throw new Error('Missing value for --format. Use md, json, or both.')
      }
      options.format = next
      index += 1
      continue
    }

    if (arg.startsWith('--format=')) {
      options.format = arg.slice('--format='.length)
      continue
    }

    if (arg === '-o' || arg === '--output') {
      const next = argv[index + 1]
      if (next === undefined) throw new Error('Missing value for --output. Use -o <dir>.')
      options.output = validateOutputValue(next)
      index += 1
      continue
    }

    if (arg.startsWith('--output=')) {
      options.output = validateOutputValue(arg.slice('--output='.length))
      continue
    }

    if (arg.startsWith('-')) {
      throw new Error(`Unknown option: ${arg}`)
    }

    options.positionals.push(arg)
  }

  if (!VALID_FORMATS.has(options.format)) {
    throw new Error(`Invalid format "${options.format}". Use md, json, or both.`)
  }

  return options
}

function normalizeTags(tags) {
  if (!Array.isArray(tags)) return []
  return tags
    .map(tag => (typeof tag === 'string' ? tag : (tag?.tag ?? tag?.name ?? null)))
    .filter(tag => typeof tag === 'string' && tag.length > 0)
}

function buildNovelPayload({ data, novel, novelId }) {
  const rawText = novel.text
  const { parts, images } = parseContent(rawText)
  const resolvedImages = resolveImagesFromEmbeddedData(
    images,
    novel.textEmbeddedImages ?? data?.textEmbeddedImages ?? null
  )
  const contentParts = parts.map(part => {
    if (part.type === 'image') {
      return { ...part, image: resolvedImages.find(candidate => candidate.id === part.imageId) }
    }
    return part
  })
  const content = contentParts
    .filter(part => part.type === 'text')
    .map(part => part.content)
    .join('\n\n')
    .trim()

  const title = novel.title || `Pixiv Novel ${novelId}`
  const author =
    data?.authorDetails?.userName ||
    data?.authorDetails?.name ||
    novel.userName ||
    'Unknown'

  return {
    id: Number(novelId),
    title,
    author,
    description: cleanPixivText(
      String(novel.caption || '')
        .replace(/<br\s*\/?>/gi, '\n')
        .replace(/<[^>]+>/g, '')
    ),
    tags: normalizeTags(novel.tags),
    content,
    contentParts,
    images: resolvedImages,
    series: novel.seriesId
      ? { id: novel.seriesId, title: novel.seriesTitle || null, prev: null, next: null }
      : null,
    sourceUrl: getNovelUrl(novelId),
    xRestrict: novel.rating?.xRestrict ?? novel.xRestrict ?? 1,
    via: 'app-webview-v2',
  }
}

/**
 * Run one R-18 extraction. All I/O boundaries are injectable so tests can run
 * fully offline (no network, no real credentials).
 */
export async function runR18Extraction({
  argv = process.argv.slice(2),
  fetchImpl = fetch,
  env = process.env,
  cwd = process.cwd(),
  homeDir = homedir(),
  stdout = process.stdout,
} = {}) {
  // 1. Argument validation happens before any network access.
  const options = parseArgs(argv)

  if (options.help) {
    stdout.write(`${USAGE}\n`)
    return { help: true }
  }

  if (options.positionals.length !== 1) {
    throw new Error('extract-r18-webview requires exactly one Pixiv novel URL or ID')
  }

  const novelId = extractPixivNovelId(options.positionals[0])
  if (!novelId) {
    throw new Error(`Could not parse novel id from: ${options.positionals[0]}`)
  }

  const requestedOutputDir = options.output
    ? resolveManagedOutputDir(options.output, { cwd, env })
    : null

  // 2. Credentials + network.
  const resolved = await resolveRefreshToken({ tokenStdin: options.tokenStdin, env, homeDir })
  const refreshToken = resolved?.token
  if (!refreshToken) {
    throw new Error(
      'No refresh_token. Run: node scripts/pixiv-novel.mjs auth  (or set PIXIV_REFRESH_TOKEN / --token-stdin)'
    )
  }

  const auth = await exchangeRefreshToken(refreshToken, { fetchImpl, env })
  const accessToken = auth?.access_token
  if (!accessToken) throw new Error('OAuth response missing access_token')

  const url = `https://app-api.pixiv.net/webview/v2/novel?id=${novelId}`
  const response = await fetchImpl(url, { headers: appHeaders(accessToken, env) })
  if (!response.ok) throw new Error(`webview request failed: HTTP ${response.status}`)

  const html = await response.text()

  // 3. Strict, non-executing parse of the remote payload.
  const data = extractPixivValueFromHtml(html)
  const novel = data?.novel
  if (!novel?.text) {
    // The payload was located and parsed, but there is no body text. Do not
    // guess why: this is not necessarily a private/deleted novel.
    throw new Error(
      'webview payload has no novel.text: cause not determined (this is not proof that the novel is private or deleted)'
    )
  }

  const payload = buildNovelPayload({ data, novel, novelId })

  // 4. Same managed output directory + overwrite protection as `extract`.
  const outputDir =
    requestedOutputDir ??
    resolve(
      getManagedOutputBaseDir({ cwd, env }),
      'Pixiv-Novel-Skill',
      `${novelId}_${slugifyTitle(payload.title)}`
    )

  const payloads = createOutputPayloads('novel', payload)
  const writtenFiles = await writeOutputs('novel', payloads, {
    format: options.format,
    outputDir,
    data: payload,
  })

  stdout.write(`Saved R-18/auth novel "${payload.title}" (${novelId}) chars=${payload.content.length}\n`)
  writtenFiles.forEach(file => stdout.write(`${file}\n`))

  return {
    novelId,
    title: payload.title,
    outputDir,
    format: options.format,
    files: writtenFiles,
  }
}

/**
 * Format the single-line error that the CLI prints on failure. Kept as an
 * exported helper so tests can assert that remote payload bytes never reach the
 * message (and therefore never reach the host log via stderr).
 */
export function formatCliError(error) {
  return error?.message || String(error)
}

function isDirectRun() {
  const entry = process.argv[1]
  if (!entry) return false
  try {
    return realpathSync(entry) === realpathSync(fileURLToPath(import.meta.url))
  } catch {
    return resolve(entry) === fileURLToPath(import.meta.url)
  }
}

if (isDirectRun()) {
  runR18Extraction().catch(error => {
    console.error(formatCliError(error))
    process.exitCode = 1
  })
}
