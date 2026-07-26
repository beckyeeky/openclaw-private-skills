import assert from 'node:assert/strict'
import { mkdtemp } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
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
