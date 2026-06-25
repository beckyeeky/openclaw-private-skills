export function renderNovelMarkdown(novel, { extractedAt = new Date().toISOString() } = {}) {
  const lines = [
    `# ${novel.title}`,
    '',
    `- Source: [Pixiv Novel](${novel.sourceUrl})`,
    `- Novel ID: \`${novel.id}\``,
    `- Author: ${novel.author}`,
    `- Tags: ${novel.tags.length ? novel.tags.map(tag => `#${tag}`).join(' ') : '(none)'}`,
    `- Extracted At: ${extractedAt}`,
  ]

  if (novel.series?.id || novel.series?.title) {
    lines.push(`- Series: ${novel.series.title ?? '(untitled)'}${novel.series.id ? ` (\`${novel.series.id}\`)` : ''}`)
  }
  if (novel.series?.prev) {
    lines.push(`- Previous In Series: [${novel.series.prev.title}](${buildNovelUrl(novel.series.prev.id)})`)
  }
  if (novel.series?.next) {
    lines.push(`- Next In Series: [${novel.series.next.title}](${buildNovelUrl(novel.series.next.id)})`)
  }

  lines.push('')
  lines.push('## Description')
  lines.push('')
  lines.push(novel.description || '_No description provided._')
  lines.push('')
  lines.push('## Content')
  lines.push('')

  for (const part of novel.contentParts) {
    if (part.type === 'text') {
      lines.push(part.content)
      lines.push('')
      continue
    }

    lines.push(renderImagePlaceholder(part.image ?? { id: part.imageId }))
    lines.push('')
  }

  return lines.join('\n').trimEnd() + '\n'
}

function buildNovelUrl(novelId) {
  return `https://www.pixiv.net/novel/show.php?id=${novelId}`
}

function renderImagePlaceholder(image) {
  const preferredUrl = image?.url ?? image?.fallbackUrls?.[0] ?? null
  const altText = `Pixiv embedded image ${image?.id ?? 'unknown'}`

  if (!preferredUrl) {
    return `> ${altText}`
  }

  const alternateLinks = (image?.fallbackUrls ?? [])
    .filter(url => url !== preferredUrl)
    .slice(0, 3)
    .map((url, index) => `[${index + 1}](${url})`)
    .join(' ')

  if (!alternateLinks) {
    return `![${altText}](${preferredUrl})`
  }

  return `![${altText}](${preferredUrl})\n\n_Alternate URLs: ${alternateLinks}_`
}

export function renderRecommendedMarkdown(novels, { extractedAt = new Date().toISOString() } = {}) {
  const lines = [
    '# Pixiv Novel Recommendations',
    '',
    `- Count: ${novels.length}`,
    `- Extracted At: ${extractedAt}`,
    '',
  ]

  novels.forEach((novel, index) => {
    lines.push(`## ${index + 1}. [${novel.title}](${novel.sourceUrl})`)
    lines.push('')
    lines.push(`- Author: ${novel.author ?? '(unknown)'}`)
    if (novel.totalView != null) lines.push(`- Views: ${novel.totalView}`)
    if (novel.totalBookmarks != null) lines.push(`- Bookmarks: ${novel.totalBookmarks}`)
    if (novel.textLength != null) lines.push(`- Length: ${novel.textLength} chars`)
    if (novel.caption) lines.push(`- Caption: ${novel.caption}`)
    lines.push('')
  })

  return lines.join('\n').trimEnd() + '\n'
}

export function createOutputPayloads(kind, data, { extractedAt = new Date().toISOString() } = {}) {
  if (kind === 'novel') {
    return {
      markdown: renderNovelMarkdown(data, { extractedAt }),
      json: `${JSON.stringify(data, null, 2)}\n`,
    }
  }

  if (kind === 'recommended') {
    return {
      markdown: renderRecommendedMarkdown(data, { extractedAt }),
      json: `${JSON.stringify({ extractedAt, novels: data }, null, 2)}\n`,
    }
  }

  throw new Error(`Unknown output kind: ${kind}`)
}
