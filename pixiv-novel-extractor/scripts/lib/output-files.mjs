import { access, mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

import { formatTimestampForDir, slugifyTitle } from './input.mjs'

export async function ensureDir(path) {
  await mkdir(path, { recursive: true })
}

export function getRequestedExtensions(format) {
  const extensions = []

  if (format === 'md' || format === 'both') {
    extensions.push('md')
  }

  if (format === 'json' || format === 'both') {
    extensions.push('json')
  }

  return extensions
}

export async function pathExists(path) {
  try {
    await access(path)
    return true
  } catch (error) {
    if (error?.code === 'ENOENT') return false
    throw error
  }
}

export async function findAvailableBaseName(outputDir, baseName, extensions) {
  let candidate = baseName
  let counter = 2

  while (true) {
    const occupied = await Promise.all(
      extensions.map(extension => pathExists(resolve(outputDir, `${candidate}.${extension}`)))
    )

    if (!occupied.some(Boolean)) {
      return candidate
    }

    candidate = `${baseName}-${counter}`
    counter += 1
  }
}

export function getOutputBaseName(kind, data) {
  if (kind === 'novel') {
    return slugifyTitle(data?.title || `pixiv-novel-${data?.id ?? 'unknown'}`)
  }

  return `recommended_${formatTimestampForDir()}`
}

export async function writeOutputs(kind, payloads, { format, outputDir, data }) {
  await ensureDir(outputDir)
  const writtenFiles = []
  const extensions = getRequestedExtensions(format)
  const baseName = await findAvailableBaseName(outputDir, getOutputBaseName(kind, data), extensions)

  if (format === 'md' || format === 'both') {
    const markdownPath = resolve(outputDir, `${baseName}.md`)
    await writeFile(markdownPath, payloads.markdown, 'utf8')
    writtenFiles.push(markdownPath)
  }

  if (format === 'json' || format === 'both') {
    const jsonPath = resolve(outputDir, `${baseName}.json`)
    await writeFile(jsonPath, payloads.json, 'utf8')
    writtenFiles.push(jsonPath)
  }

  return writtenFiles
}
