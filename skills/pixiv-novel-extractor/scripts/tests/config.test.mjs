import assert from 'node:assert/strict'
import { chmod, mkdir, mkdtemp, readFile, stat, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { Readable } from 'node:stream'
import test from 'node:test'

import {
  buildStoredConfig,
  clearConfig,
  describeConfig,
  getConfigPath,
  readConfig,
  resolveRefreshToken,
  writeConfig,
} from '../lib/config.mjs'

test('config round trip writes, reads, and clears saved token data', async () => {
  const homeDir = await mkdtemp(join(tmpdir(), 'pixiv-config-'))
  const config = buildStoredConfig({
    refreshToken: 'refresh-token-123',
    authInfo: {
      user: {
        id: '42',
        name: 'User',
        account: 'pixiv-account',
      },
    },
    now: '2026-06-25T00:00:00.000Z',
  })

  const configPath = await writeConfig(config, { homeDir })
  assert.equal(configPath, getConfigPath(homeDir))

  const loaded = await readConfig({ homeDir })
  assert.equal(loaded.refreshToken, 'refresh-token-123')
  assert.equal(loaded.user.account, 'pixiv-account')

  const described = describeConfig(loaded, { configPath })
  assert.equal(described.token, 'refr...-123')

  await clearConfig({ homeDir })
  const afterClear = await readConfig({ homeDir })
  assert.equal(afterClear, null)
})

test('resolveRefreshToken prefers stdin, then env, then config', async () => {
  const homeDir = await mkdtemp(join(tmpdir(), 'pixiv-token-source-'))
  await writeConfig({
    refreshToken: 'config-token',
    savedAt: '2026-06-25T00:00:00.000Z',
    verifiedAt: '2026-06-25T00:00:00.000Z',
    user: null,
  }, { homeDir })

  const stdinResult = await resolveRefreshToken({
    tokenStdin: true,
    stdin: Readable.from(['stdin-token']),
    env: {},
    homeDir,
  })
  assert.equal(stdinResult.token, 'stdin-token')
  assert.equal(stdinResult.source, 'stdin')

  const envResult = await resolveRefreshToken({
    env: { PIXIV_REFRESH_TOKEN: 'env-token' },
    homeDir,
  })
  assert.equal(envResult.token, 'env-token')
  assert.equal(envResult.source, 'env')

  const configResult = await resolveRefreshToken({
    env: {},
    homeDir,
  })
  assert.equal(configResult.token, 'config-token')
  assert.equal(configResult.source, 'config')
})

test('writeConfig stores the token with a 0700 directory and 0600 file', async () => {
  const homeDir = await mkdtemp(join(tmpdir(), 'pixiv-config-mode-'))
  const configPath = await writeConfig({
    refreshToken: 'refresh-token-mode',
    savedAt: '2026-06-25T00:00:00.000Z',
    verifiedAt: '2026-06-25T00:00:00.000Z',
    user: null,
  }, { homeDir })

  const fileMode = (await stat(configPath)).mode & 0o777
  const dirMode = (await stat(dirname(configPath))).mode & 0o777

  assert.equal(fileMode, 0o600)
  assert.equal(dirMode, 0o700)
})

test('writeConfig tightens an existing world-readable config file', async () => {
  const homeDir = await mkdtemp(join(tmpdir(), 'pixiv-config-tighten-'))
  const configPath = getConfigPath(homeDir)
  await mkdir(dirname(configPath), { recursive: true, mode: 0o755 })
  await writeFile(configPath, '{"refreshToken":"old-token"}\n', 'utf8')
  await chmod(configPath, 0o644)
  await chmod(dirname(configPath), 0o755)

  assert.equal((await stat(configPath)).mode & 0o777, 0o644)

  await writeConfig({ refreshToken: 'new-token' }, { homeDir })

  assert.equal((await stat(configPath)).mode & 0o777, 0o600)
  assert.equal((await stat(dirname(configPath))).mode & 0o777, 0o700)
  assert.match(await readFile(configPath, 'utf8'), /new-token/)
})

test('writeConfig refuses to write when an existing file cannot be restricted', async () => {
  const homeDir = await mkdtemp(join(tmpdir(), 'pixiv-config-chmod-'))
  const configPath = getConfigPath(homeDir)
  await mkdir(dirname(configPath), { recursive: true })
  await writeFile(configPath, '{"refreshToken":"old-token"}\n', 'utf8')
  await chmod(configPath, 0o644)

  const failingChmod = async (target, mode) => {
    if (resolve(target) === resolve(configPath)) {
      const error = new Error('EPERM: operation not permitted')
      error.code = 'EPERM'
      throw error
    }
    return chmod(target, mode)
  }

  await assert.rejects(
    writeConfig({ refreshToken: 'SECRET-NEW-TOKEN' }, { homeDir, chmodImpl: failingChmod }),
    /Refusing to store Pixiv credentials/
  )

  // The new secret must never land in a file whose permissions could not be secured.
  const raw = await readFile(configPath, 'utf8')
  assert.doesNotMatch(raw, /SECRET-NEW-TOKEN/)
  assert.equal((await stat(configPath)).mode & 0o777, 0o644)
})

test('writeConfig reports a config file whose mode cannot be verified', async () => {
  const homeDir = await mkdtemp(join(tmpdir(), 'pixiv-config-verify-'))
  const configPath = getConfigPath(homeDir)
  const realStat = stat

  const lyingStat = async target => {
    const info = await realStat(target)
    return resolve(target) === resolve(configPath) ? { ...info, mode: 0o100644 } : info
  }

  await assert.rejects(
    writeConfig({ refreshToken: 'refresh-token' }, { homeDir, statImpl: lyingStat }),
    /has mode 644 instead of 600/
  )
})
