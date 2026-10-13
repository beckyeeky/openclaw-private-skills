import { chmod, mkdir, readFile, rm, rmdir, stat, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'

import { maskToken } from './input.mjs'

const CONFIG_DIRNAME = '.pixiv-novel-extractor'
const CONFIG_FILENAME = 'config.json'

// The config file holds a long-lived Pixiv refresh_token, so it must never be
// group- or world-readable.
export const CONFIG_DIR_MODE = 0o700
export const CONFIG_FILE_MODE = 0o600

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

/**
 * Force `mode` on a credential path and verify it actually took effect.
 *
 * `writeFile(..., { mode })` and `mkdir(..., { mode })` only apply at creation
 * time and are masked by umask, so an existing 0644 config file would silently
 * stay world-readable. This helper never swallows a failure: if the mode cannot
 * be set or cannot be verified, it throws so the caller can never report a
 * successful "saved" while the token is exposed.
 */
async function restrictPermissions(targetPath, mode, label, { chmodImpl = chmod, statImpl = stat } = {}) {
  try {
    await chmodImpl(targetPath, mode)
  } catch (error) {
    const detail = error?.code || error?.message || error
    throw new Error(
      `Refusing to store Pixiv credentials: could not restrict permissions of ${label} ${targetPath} to ${mode.toString(8)} (${detail}). The file permissions are NOT secured, so the refresh_token could be readable by other local users.`
    )
  }

  let info
  try {
    info = await statImpl(targetPath)
  } catch (error) {
    const detail = error?.code || error?.message || error
    throw new Error(`Refusing to store Pixiv credentials: could not verify permissions of ${label} ${targetPath} (${detail})`)
  }

  const actualMode = info.mode & 0o777
  if (actualMode !== mode) {
    throw new Error(
      `Refusing to store Pixiv credentials: ${label} ${targetPath} has mode ${actualMode.toString(8)} instead of ${mode.toString(8)}`
    )
  }
}

export async function writeConfig(
  config,
  { homeDir = homedir(), chmodImpl = chmod, statImpl = stat } = {}
) {
  const configPath = getConfigPath(homeDir)
  const configDir = dirname(configPath)
  const fsOverrides = { chmodImpl, statImpl }

  await mkdir(configDir, { recursive: true, mode: CONFIG_DIR_MODE })
  await restrictPermissions(configDir, CONFIG_DIR_MODE, 'config directory', fsOverrides)

  // Detect an existing file before writing: `mode` at write time does not
  // change permission bits of a file that already exists.
  let exists = true
  try {
    await statImpl(configPath)
  } catch (error) {
    if (error?.code === 'ENOENT') {
      exists = false
    } else {
      throw new Error(`Failed to inspect Pixiv config: ${error?.message || error}`)
    }
  }

  if (exists) {
    // Tighten before the new secret is written; a failure aborts the write.
    await restrictPermissions(configPath, CONFIG_FILE_MODE, 'existing config file', fsOverrides)
  }

  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`, {
    encoding: 'utf8',
    mode: CONFIG_FILE_MODE,
  })
  await restrictPermissions(configPath, CONFIG_FILE_MODE, 'config file', fsOverrides)

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
