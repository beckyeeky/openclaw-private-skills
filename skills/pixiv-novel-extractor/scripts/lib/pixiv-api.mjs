const DEFAULT_CLIENT_ID = 'MOBrBDS8blbauoSck0ZfDbtuzpyT'
const DEFAULT_CLIENT_SECRET = 'lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj'
const DEFAULT_APP_OS = 'ios'
const DEFAULT_APP_OS_VERSION = '14.6'
const DEFAULT_USER_AGENT = 'PixivIOSApp/7.13.3 (iOS 14.6; iPhone13,2)'
const PUBLIC_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36'

function htmlToText(value) {
  return (value ?? '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>\s*<p>/gi, '\n\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .trim()
}

function buildOAuthErrorMessage(data, fallback) {
  return data?.errors?.system?.message ?? data?.error_description ?? data?.error ?? fallback
}

function getOAuthHeaders(env = process.env) {
  return {
    'content-type': 'application/x-www-form-urlencoded',
    'app-os': env.PIXIV_APP_OS || DEFAULT_APP_OS,
    'app-os-version': env.PIXIV_APP_OS_VERSION || DEFAULT_APP_OS_VERSION,
    'user-agent': env.PIXIV_USER_AGENT || DEFAULT_USER_AGENT,
  }
}

function getAppApiHeaders(accessToken, env = process.env) {
  return {
    Authorization: `Bearer ${accessToken}`,
    'app-os': env.PIXIV_APP_OS || DEFAULT_APP_OS,
    'app-os-version': env.PIXIV_APP_OS_VERSION || DEFAULT_APP_OS_VERSION,
    'user-agent': env.PIXIV_USER_AGENT || DEFAULT_USER_AGENT,
  }
}

export function getNovelUrl(novelId) {
  return `https://www.pixiv.net/novel/show.php?id=${novelId}`
}

export function cleanPixivText(text) {
  return (text ?? '')
    .replace(/\r\n?/g, '\n')
    .replace(/\[\[rb:(.*?)\s*>\s*.*?\]\]/g, '$1')
    .replace(/\[\[jumpuri:(.*?)\s*>\s*(https?:\/\/[^\]]+)\]\]/g, (_, label, url) => `[${label.trim()}](${url.trim()})`)
    .replace(/\[\[jumpuri:(https?:\/\/[^\]]+)\]\]/g, (_, url) => url.trim())
    .replace(/\[newpage\]/g, '\n\n---\n\n')
    .replace(/\[\[.*?\]\]/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

export function parseContent(content) {
  const images = []
  const parts = []
  const imageTagRegex = /\[(?:uploadedimage|pixivimage):([\w-]+)\]/g

  let lastIndex = 0
  let match
  while ((match = imageTagRegex.exec(content ?? '')) !== null) {
    const textBefore = cleanPixivText((content ?? '').slice(lastIndex, match.index))
    if (textBefore) {
      parts.push({ type: 'text', content: textBefore })
    }

    const imageId = match[1]
    images.push({ id: imageId })
    parts.push({ type: 'image', imageId })
    lastIndex = match.index + match[0].length
  }

  const remaining = cleanPixivText((content ?? '').slice(lastIndex))
  if (remaining) {
    parts.push({ type: 'text', content: remaining })
  }

  return { parts, images }
}

function toPixivProxyUrl(url) {
  if (!url) return undefined
  return url
    .replace('https://i.pximg.net', 'https://i.pixiv.cat')
    .replace('http://i.pximg.net', 'https://i.pixiv.cat')
}

function parseArtworkReference(value) {
  if (!value) return undefined
  const match = value.match(/^(\d+)(?:[-_](\d+))?$/)
  if (!match) return undefined
  return {
    artworkId: match[1],
    page: Number(match[2] ?? 0),
  }
}

function parseArtworkReferenceFromUrl(url) {
  if (!url) return undefined
  const match = url.match(/\/(\d+)_p(\d+)\.[a-z0-9]+(?:$|[?#])/i)
  if (!match) return undefined
  return {
    artworkId: match[1],
    page: Number(match[2] ?? 0),
  }
}

function toPixivCatArtworkUrl(artworkId, page = 0, extension = 'jpg', domain = 'pixiv.cat') {
  if (!artworkId || !/^\d+$/.test(artworkId)) return undefined
  return page > 0
    ? `https://${domain}/${artworkId}-${page}.${extension}`
    : `https://${domain}/${artworkId}.${extension}`
}

function getImageFallbackUrls(imageId, artworkId, originalUrl) {
  const references = [
    parseArtworkReference(artworkId),
    parseArtworkReference(imageId),
    parseArtworkReferenceFromUrl(originalUrl),
  ].filter(Boolean)

  const candidates = references.flatMap(reference =>
    ['pixiv.cat', 'pixiv.re', 'pixiv.nl'].flatMap(domain =>
      ['jpg', 'png', 'gif'].map(extension =>
        toPixivCatArtworkUrl(reference.artworkId, reference.page, extension, domain)
      )
    )
  )

  return Array.from(new Set(candidates.filter(Boolean)))
}

function resolveImagesFromEmbeddedData(images, embeddedData) {
  if (!embeddedData || !images.length) {
    return images.map(image => ({
      ...image,
      fallbackUrls: getImageFallbackUrls(image.id, undefined, image.url),
    }))
  }

  return images.map(image => {
    const data = embeddedData?.[image.id]
    const originalUrl = data?.urls?.original ?? image.url
    const fallbackUrls = getImageFallbackUrls(image.id, data?.novelImageId, originalUrl)

    return {
      ...image,
      url: toPixivProxyUrl(originalUrl) ?? fallbackUrls[0],
      fallbackUrls,
    }
  })
}

function normalizeSeries(seriesNavData) {
  if (!seriesNavData) return null

  const mapNav = item => item ? { id: item.id, title: item.title } : null

  return {
    id: seriesNavData.seriesId ?? null,
    title: seriesNavData.title ?? null,
    prev: mapNav(seriesNavData.prev),
    next: mapNav(seriesNavData.next),
  }
}

export async function fetchPublicNovel(novelId, { fetchImpl = fetch } = {}) {
  const url = `https://www.pixiv.net/ajax/novel/${novelId}`
  const response = await fetchImpl(url, {
    headers: {
      accept: 'application/json',
      referer: getNovelUrl(novelId),
      'user-agent': PUBLIC_USER_AGENT,
    },
  })

  if (!response.ok) {
    throw new Error(`Pixiv public novel request failed with status ${response.status}`)
  }

  const data = await response.json()
  if (!data || data.error || !data.body) {
    const message = data?.message || 'Pixiv public novel not found'
    throw new Error(message)
  }

  const body = data.body
  const { parts, images } = parseContent(body.content ?? '')
  const resolvedImages = resolveImagesFromEmbeddedData(images, body.textEmbeddedImages)
  const content = parts
    .filter(part => part.type === 'text')
    .map(part => part.content)
    .join('\n\n')
    .trim()

  return {
    id: Number(body.id ?? novelId),
    title: body.title ?? `Pixiv Novel ${novelId}`,
    author: body.userName ?? 'Unknown',
    description: htmlToText(body.description),
    tags: Array.isArray(body?.tags?.tags) ? body.tags.tags.map(item => item.tag).filter(Boolean) : [],
    content,
    contentParts: parts.map(part => {
      if (part.type === 'image') {
        const image = resolvedImages.find(candidate => candidate.id === part.imageId)
        return { ...part, image }
      }
      return part
    }),
    images: resolvedImages,
    series: normalizeSeries(body.seriesNavData),
    sourceUrl: getNovelUrl(body.id ?? novelId),
  }
}

export async function exchangeRefreshToken(refreshToken, { fetchImpl = fetch, env = process.env } = {}) {
  const payload = new URLSearchParams({
    grant_type: 'refresh_token',
    refresh_token: refreshToken,
    client_id: env.PIXIV_CLIENT_ID || DEFAULT_CLIENT_ID,
    client_secret: env.PIXIV_CLIENT_SECRET || DEFAULT_CLIENT_SECRET,
    include_policy: 'true',
  })

  const response = await fetchImpl('https://oauth.secure.pixiv.net/auth/token', {
    method: 'POST',
    headers: getOAuthHeaders(env),
    body: payload.toString(),
  })

  const data = await response.json()
  if (!response.ok || data?.has_error || !data?.response) {
    const detail = buildOAuthErrorMessage(data, 'Pixiv token exchange failed')
    throw new Error(`Pixiv OAuth error: ${detail}`)
  }

  return data.response
}

export async function fetchNovelRecommendations(refreshToken, { fetchImpl = fetch, env = process.env } = {}) {
  const authInfo = await exchangeRefreshToken(refreshToken, { fetchImpl, env })
  const accessToken = authInfo?.access_token
  if (!accessToken) {
    throw new Error('Pixiv OAuth error: missing access token in response')
  }

  const params = new URLSearchParams({
    filter: 'for_ios',
    include_ranking_label: 'true',
    include_privacy_policy: 'true',
  })

  const response = await fetchImpl(`https://app-api.pixiv.net/v1/novel/recommended?${params.toString()}`, {
    headers: getAppApiHeaders(accessToken, env),
  })

  const data = await response.json()
  if (!response.ok || data?.error) {
    throw new Error(data?.message || 'Failed to fetch recommendations')
  }

  const novels = Array.isArray(data?.novels) ? data.novels : []

  return novels.map(item => ({
    id: item.id,
    title: item.title,
    caption: htmlToText(item.caption),
    author: item.user?.name ?? null,
    userId: item.user?.id ?? null,
    totalBookmarks: item.total_bookmarks ?? null,
    totalView: item.total_view ?? null,
    textLength:
      typeof item.text_length === 'number'
        ? item.text_length
        : typeof item.textLength === 'number'
          ? item.textLength
          : typeof item.total_text_length === 'number'
            ? item.total_text_length
            : null,
    sourceUrl: getNovelUrl(item.id),
  }))
}
