#!/usr/bin/env node
/**
 * R-18 / login-gated Pixiv novel body extractor via App webview HTML.
 * Use when scripts/pixiv-novel.mjs extract returns empty content.
 *
 * Usage:
 *   node scripts/extract-r18-webview.mjs <url-or-id> [--format md|json|both] [-o <dir>] [--token-stdin]
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

import { resolveRefreshToken } from './lib/config.mjs'
import { extractPixivNovelId, slugifyTitle } from './lib/input.mjs'
import {
  cleanPixivText,
  exchangeRefreshToken,
  getNovelUrl,
  parseContent,
} from './lib/pixiv-api.mjs'

const DEFAULT_APP_OS = 'ios'
const DEFAULT_APP_OS_VERSION = '14.6'
const DEFAULT_USER_AGENT = 'PixivIOSApp/7.13.3 (iOS 14.6; iPhone13,2)'

function appHeaders(accessToken) {
  return {
    Authorization: `Bearer ${accessToken}`,
    'app-os': process.env.PIXIV_APP_OS || DEFAULT_APP_OS,
    'app-os-version': process.env.PIXIV_APP_OS_VERSION || DEFAULT_APP_OS_VERSION,
    'user-agent': process.env.PIXIV_USER_AGENT || DEFAULT_USER_AGENT,
  }
}

function parseArgs(argv) {
  const options = {
    format: 'both',
    output: null,
    tokenStdin: false,
    help: false,
    positionals: [],
  }
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg === '--format' || arg === '-f') {
      options.format = argv[++i]
      continue
    }
    if (arg === '-o' || arg === '--output') {
      options.output = argv[++i]
      continue
    }
    if (arg === '--token-stdin') {
      options.tokenStdin = true
      continue
    }
    if (arg === '-h' || arg === '--help') {
      options.help = true
      continue
    }
    if (!arg.startsWith('-')) options.positionals.push(arg)
  }
  return options
}

function extractPixivValueObject(html) {
  const marker = 'value: {'
  const start = html.indexOf(marker)
  if (start < 0) throw new Error('webview HTML missing window.pixiv value object')
  const i = start + 'value: '.length
  let depth = 0
  let end = -1
  for (let p = i; p < html.length; p += 1) {
    const ch = html[p]
    if (ch === '{') depth += 1
    else if (ch === '}') {
      depth -= 1
      if (depth === 0) {
        end = p + 1
        break
      }
    }
  }
  if (end < 0) throw new Error('failed to balance braces for window.pixiv value')
  // webview embeds a JS object literal, not strict JSON
  // eslint-disable-next-line no-new-func
  return Function(`"use strict"; return (${html.slice(i, end)})`)()
}

function safeFilename(title, novelId) {
  return slugifyTitle(title || `novel-${novelId}`).replace(/[\\/:*?"<>|]/g, '-').slice(0, 80)
}

async function main() {
  const options = parseArgs(process.argv.slice(2))
  if (options.help || options.positionals.length === 0) {
    console.log(
      'Usage: node scripts/extract-r18-webview.mjs <url-or-id> [--format md|json|both] [-o dir] [--token-stdin]',
    )
    process.exit(options.help ? 0 : 1)
  }

  const novelId = extractPixivNovelId(options.positionals[0])
  if (!novelId) throw new Error(`Could not parse novel id from: ${options.positionals[0]}`)

  const resolved = await resolveRefreshToken({ tokenStdin: options.tokenStdin })
  const refreshToken = resolved?.token
  if (!refreshToken) {
    throw new Error(
      'No refresh_token. Run: node scripts/pixiv-novel.mjs auth  (or set PIXIV_REFRESH_TOKEN / --token-stdin)',
    )
  }

  const auth = await exchangeRefreshToken(refreshToken)
  const accessToken = auth?.access_token
  if (!accessToken) throw new Error('OAuth response missing access_token')

  const url = `https://app-api.pixiv.net/webview/v2/novel?id=${novelId}`
  const res = await fetch(url, { headers: appHeaders(accessToken) })
  if (!res.ok) throw new Error(`webview request failed: HTTP ${res.status}`)
  const html = await res.text()
  const data = extractPixivValueObject(html)
  const novel = data?.novel
  if (!novel?.text) throw new Error('webview payload missing novel.text (private/deleted?)')

  const rawText = novel.text
  const cleaned = cleanPixivText(rawText)
  const { parts, images } = parseContent(rawText)
  const tags = Array.isArray(novel.tags) ? novel.tags : []
  const title = novel.title || `Pixiv Novel ${novelId}`
  const author =
    data?.authorDetails?.userName ||
    data?.authorDetails?.name ||
    novel.userName ||
    'Unknown'
  const description = cleanPixivText(
    String(novel.caption || '')
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<[^>]+>/g, ''),
  )
  const sourceUrl = getNovelUrl(novelId)

  const payload = {
    id: Number(novelId),
    title,
    author,
    description,
    tags,
    content: cleaned,
    contentParts: parts,
    images,
    series: novel.seriesId
      ? { id: novel.seriesId, title: novel.seriesTitle || null }
      : null,
    sourceUrl,
    xRestrict: novel.rating?.xRestrict ?? novel.xRestrict ?? 1,
    via: 'app-webview-v2',
  }

  const base = safeFilename(title, novelId)
  const outDir = resolve(
    options.output || join(process.cwd(), 'Pixiv-Novel-Skill', `${novelId}_${base}`),
  )
  mkdirSync(outDir, { recursive: true })

  if (options.format === 'md' || options.format === 'both') {
    const md = [
      `# ${title}`,
      '',
      `- Source: [Pixiv Novel](${sourceUrl})`,
      `- Novel ID: \`${novelId}\``,
      `- Author: ${author}`,
      `- Tags: ${tags.map(t => `#${t}`).join(' ')}`,
      `- Via: app-webview-v2 (R-18/auth fallback)`,
      '',
      '## Description',
      '',
      description || '(none)',
      '',
      '## Content',
      '',
      cleaned,
      '',
    ].join('\n')
    const mdPath = join(outDir, `${base}.md`)
    writeFileSync(mdPath, md, 'utf8')
    console.log(mdPath)
  }

  if (options.format === 'json' || options.format === 'both') {
    const jsonPath = join(outDir, `${base}.json`)
    writeFileSync(jsonPath, JSON.stringify(payload, null, 2), 'utf8')
    console.log(jsonPath)
  }

  console.log(`Saved R-18/auth novel "${title}" (${novelId}) chars=${cleaned.length}`)
}

main().catch(err => {
  console.error(err?.stack || err?.message || err)
  process.exit(1)
})
