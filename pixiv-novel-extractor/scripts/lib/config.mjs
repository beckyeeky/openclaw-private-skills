import { mkdir, readFile, rm, rmdir, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'

import { maskToken } from './input.mjs'

const CONFIG_DIRNAME = '.pixiv-novel-extractor'
const CONFIG_FILENAME = 'config.json'

export function getConfigPath(homeDir = homedir()) {
  return join(homeDir, CONFIG_DIRNAME, CONFIG_FILENAME)
}

export async function readConfig({ homeDir = homedir() } = {}) {
  const configPath = getConfigPath(homeDir)

  try {
    const raw = await readFile(configPath, 'utf8')
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') {
      throw new Error('Pixiv config must be a JSON object')
    }
    return parsed
  } catch (error) {
    if (error?.code === 'ENOENT') return null
    throw new Error(`Failed to read Pixiv config: ${error.message}`)
  }
}

export async function writeConfig(config, { homeDir = homedir() } = {}) {
  const configPath = getConfigPath(homeDir)
  await mkdir(dirname(configPath), { recursive: true })
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`, 'utf8')
  return configPath
}

export async function clearConfig({ homeDir = homedir() } = {}) {
  const configPath = getConfigPath(homeDir)
  const configDir = dirname(configPath)

  await rm(configPath, { force: true })
  try {
    await rmdir(configDir)
  } catch (error) {
    if (error?.code !== 'ENOTEMPTY' && error?.code !== 'ENOENT') throw error
  }

  return configPath
}

export function sanitizeUserInfo(authInfo) {
  const user = authInfo?.user
  if (!user || typeof user !== 'object') return null

  return {
    id: user.id ?? null,
    name: user.name ?? null,
    account: user.account ?? null,
  }
}

export function buildStoredConfig({ refreshToken, authInfo, now = new Date().toISOString(), existingConfig = null }) {
  return {
    refreshToken,
    savedAt: existingConfig?.savedAt ?? now,
    verifiedAt: now,
    user: sanitizeUserInfo(authInfo),
  }
}

export async function readTextFromStream(stream) {
  const chunks = []

  for await (const chunk of stream) {
    chunks.push(typeof chunk === 'string' ? chunk : Buffer.from(chunk).toString('utf8'))
  }

  return chunks.join('')
}

export async function resolveRefreshToken({
  tokenStdin = false,
  env = process.env,
  stdin = process.stdin,
  homeDir = homedir(),
} = {}) {
  if (tokenStdin) {
    const stdinToken = (await readTextFromStream(stdin)).trim()
    if (!stdinToken) {
      throw new Error('Expected a Pixiv refresh token on stdin')
    }
    return { token: stdinToken, source: 'stdin', config: null }
  }

  const envToken = typeof env.PIXIV_REFRESH_TOKEN === 'string' ? env.PIXIV_REFRESH_TOKEN.trim() : ''
  if (envToken) {
    return { token: envToken, source: 'env', config: null }
  }

  const config = await readConfig({ homeDir })
  const configToken = typeof config?.refreshToken === 'string' ? config.refreshToken.trim() : ''
  if (configToken) {
    return { token: configToken, source: 'config', config }
  }

  return { token: '', source: 'none', config }
}

export function describeConfig(config, { configPath }) {
  return {
    configPath,
    token: maskToken(config?.refreshToken ?? ''),
    savedAt: config?.savedAt ?? null,
    verifiedAt: config?.verifiedAt ?? null,
    user: config?.user ?? null,
  }
}
