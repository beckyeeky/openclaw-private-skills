const NOVEL_ID_PATTERN = /^\d+$/
const NOVEL_ID_QUERY_PATTERN = /(?:[?&]|&amp;)id\s*=\s*(\d+)/i
const PIXIV_NOVEL_PATH_PATTERN = /(?:https?:\/\/)?(?:www\.)?pixiv\.net\/novel\/show\.php[^\s]*/gi

export function decodeClipboardValue(value) {
  let decoded = value

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const next = decodeURIComponent(decoded)
      if (next === decoded) break
      decoded = next
    } catch {
      break
    }
  }

  return decoded
}

export function extractPixivNovelId(value) {
  const trimmed = value.trim()
  if (!trimmed) return null
  if (NOVEL_ID_PATTERN.test(trimmed)) return trimmed

  const candidates = [trimmed, decodeClipboardValue(trimmed)]
  for (const candidate of candidates) {
    const pixivUrls = candidate.match(PIXIV_NOVEL_PATH_PATTERN) ?? []
    for (const pixivUrl of pixivUrls) {
      const match = pixivUrl.match(NOVEL_ID_QUERY_PATTERN)
      if (match) return match[1]
    }

    const queryMatch = candidate.match(NOVEL_ID_QUERY_PATTERN)
    if (queryMatch) return queryMatch[1]
  }

  return null
}

export function slugifyTitle(value, maxLength = 60) {
  const normalized = (value ?? '')
    .normalize('NFKC')
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

  if (!normalized) return 'untitled'

  const slug = normalized
    .replace(/\s+/g, '-')
    .replace(/[. ]+$/g, '')
    .slice(0, maxLength)
    .replace(/-+$/g, '')

  return slug || 'untitled'
}

export function formatTimestampForDir(date = new Date()) {
  const parts = {
    year: date.getFullYear(),
    month: String(date.getMonth() + 1).padStart(2, '0'),
    day: String(date.getDate()).padStart(2, '0'),
    hour: String(date.getHours()).padStart(2, '0'),
    minute: String(date.getMinutes()).padStart(2, '0'),
    second: String(date.getSeconds()).padStart(2, '0'),
  }

  return `${parts.year}${parts.month}${parts.day}_${parts.hour}${parts.minute}${parts.second}`
}

export function maskToken(token) {
  const trimmed = (token ?? '').trim()
  if (!trimmed) return ''
  if (trimmed.length <= 8) return `${trimmed.slice(0, 2)}***${trimmed.slice(-2)}`
  return `${trimmed.slice(0, 4)}...${trimmed.slice(-4)}`
}
