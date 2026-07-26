#!/usr/bin/env node

import { resolve } from 'node:path'
import readline from 'node:readline/promises'

import {
  buildStoredConfig,
  clearConfig,
  describeConfig,
  getConfigPath,
  readConfig,
  resolveRefreshToken,
  writeConfig,
} from './lib/config.mjs'
import { extractPixivNovelId, formatTimestampForDir, slugifyTitle } from './lib/input.mjs'
import { writeOutputs } from './lib/output-files.mjs'
import { getManagedOutputBaseDir, resolveManagedOutputDir } from './lib/output-paths.mjs'
import { exchangeRefreshToken, fetchNovelRecommendations, fetchPublicNovel } from './lib/pixiv-api.mjs'
import { createOutputPayloads } from './lib/render.mjs'

const VALID_FORMATS = new Set(['md', 'json', 'both'])

function printUsage() {
  console.log(`Pixiv Novel Extractor

Usage:
  node scripts/pixiv-novel.mjs extract <url-or-id> [--format md|json|both] [-o <dir>]
  node scripts/pixiv-novel.mjs auth [--verify|--show|--clear|--token-stdin]
  node scripts/pixiv-novel.mjs recommended [--format md|json|both] [--token-stdin] [-o <dir>]
`)
}

function parseArgs(args) {
  const options = {
    format: 'md',
    output: null,
    tokenStdin: false,
    verify: false,
    show: false,
    clear: false,
    help: false,
    positionals: [],
  }

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index]

    if (arg === '-h' || arg === '--help') {
      options.help = true
      continue
    }

    if (arg === '--token-stdin') {
      options.tokenStdin = true
      continue
    }

    if (arg === '--verify') {
      options.verify = true
      continue
    }

    if (arg === '--show') {
      options.show = true
      continue
    }

    if (arg === '--clear') {
      options.clear = true
      continue
    }

    if (arg === '--format' || arg === '-f') {
      const next = args[index + 1]
      if (!next) throw new Error('Missing value for --format')
      options.format = next
      index += 1
      continue
    }

    if (arg.startsWith('--format=')) {
      options.format = arg.slice('--format='.length)
      continue
    }

    if (arg === '--output' || arg === '-o') {
      const next = args[index + 1]
      if (!next) throw new Error('Missing value for --output')
      options.output = next
      index += 1
      continue
    }

    if (arg.startsWith('--output=')) {
      options.output = arg.slice('--output='.length)
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

function getDefaultNovelOutputDir(novel, { cwd = process.cwd(), env = process.env } = {}) {
  return resolve(
    getManagedOutputBaseDir({ cwd, env }),
    'Pixiv-Novel-Skill',
    `${novel.id}_${slugifyTitle(novel.title)}`
  )
}

function getDefaultRecommendedOutputDir({ cwd = process.cwd(), env = process.env } = {}) {
  return resolve(
    getManagedOutputBaseDir({ cwd, env }),
    'Pixiv-Novel-Skill',
    `recommended_${formatTimestampForDir()}`
  )
}

async function runExtract(args) {
  const options = parseArgs(args)
  if (options.help) {
    printUsage()
    return
  }

  const input = options.positionals[0]
  if (!input || options.positionals.length !== 1) {
    throw new Error('extract requires exactly one Pixiv novel URL or ID')
  }

  const novelId = extractPixivNovelId(input)
  if (!novelId) {
    throw new Error('Could not extract a Pixiv novel ID from the provided input')
  }

  const novel = await fetchPublicNovel(novelId)
  const outputDir = options.output
    ? resolveManagedOutputDir(options.output, { cwd: process.cwd(), env: process.env })
    : getDefaultNovelOutputDir(novel, { cwd: process.cwd(), env: process.env })
  const payloads = createOutputPayloads('novel', novel)
  const writtenFiles = await writeOutputs('novel', payloads, { format: options.format, outputDir, data: novel })

  console.log(`Saved Pixiv novel "${novel.title}" (${novel.id})`)
  writtenFiles.forEach(file => console.log(file))
}

async function promptForToken() {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  })

  try {
    const token = (await rl.question('Paste Pixiv refresh_token: ')).trim()
    if (!token) throw new Error('No Pixiv refresh token provided')
    return token
  } finally {
    rl.close()
  }
}

function validateSingleAuthMode(options) {
  const enabled = [options.verify, options.show, options.clear].filter(Boolean).length
  if (enabled > 1) {
    throw new Error('Use only one of --verify, --show, or --clear at a time')
  }
}

async function runAuth(args) {
  const options = parseArgs(args)
  validateSingleAuthMode(options)

  if (options.help) {
    printUsage()
    return
  }

  const configPath = getConfigPath()

  if (options.clear) {
    await clearConfig()
    console.log(`Cleared Pixiv token config at ${configPath}`)
    return
  }

  if (options.show) {
    const config = await readConfig()
    if (!config?.refreshToken) {
      throw new Error(`No Pixiv token config found at ${configPath}`)
    }

    const details = describeConfig(config, { configPath })
    console.log(JSON.stringify(details, null, 2))
    return
  }

  if (options.verify) {
    const config = await readConfig()
    const token = typeof config?.refreshToken === 'string' ? config.refreshToken.trim() : ''
    if (!token) {
      throw new Error(`No Pixiv token config found at ${configPath}`)
    }

    const authInfo = await exchangeRefreshToken(token)
    const updatedConfig = buildStoredConfig({
      refreshToken: token,
      authInfo,
      existingConfig: config,
      now: new Date().toISOString(),
    })
    await writeConfig(updatedConfig)
    console.log(`Verified Pixiv token and updated ${configPath}`)
    return
  }

  const token = options.tokenStdin
    ? (await resolveRefreshToken({ tokenStdin: true })).token
    : await promptForToken()
  const authInfo = await exchangeRefreshToken(token)
  const config = buildStoredConfig({
    refreshToken: token,
    authInfo,
    now: new Date().toISOString(),
  })
  await writeConfig(config)
  console.log(`Saved verified Pixiv token to ${configPath}`)
}

async function runRecommended(args) {
  const options = parseArgs(args)
  if (options.help) {
    printUsage()
    return
  }

  const { token, source } = await resolveRefreshToken({
    tokenStdin: options.tokenStdin,
  })
  if (!token) {
    throw new Error('No Pixiv refresh token found. Run auth first, set PIXIV_REFRESH_TOKEN, or use --token-stdin.')
  }

  const novels = await fetchNovelRecommendations(token)
  const outputDir = options.output
    ? resolveManagedOutputDir(options.output, { cwd: process.cwd(), env: process.env })
    : getDefaultRecommendedOutputDir({ cwd: process.cwd(), env: process.env })
  const payloads = createOutputPayloads('recommended', novels)
  const writtenFiles = await writeOutputs('recommended', payloads, { format: options.format, outputDir, data: novels })

  console.log(`Saved ${novels.length} Pixiv recommendations (token source: ${source})`)
  writtenFiles.forEach(file => console.log(file))
}

async function main() {
  const [command, ...rest] = process.argv.slice(2)

  if (!command || command === '-h' || command === '--help') {
    printUsage()
    return
  }

  if (command === 'extract') {
    await runExtract(rest)
    return
  }

  if (command === 'auth') {
    await runAuth(rest)
    return
  }

  if (command === 'recommended') {
    await runRecommended(rest)
    return
  }

  throw new Error(`Unknown command: ${command}`)
}

main().catch(error => {
  console.error(error.message)
  process.exitCode = 1
})
