import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import test from 'node:test'

import { getManagedOutputBaseDir, resolveManagedOutputDir } from '../lib/output-paths.mjs'

test('getManagedOutputBaseDir prefers workspace cwd when outside the skill root', () => {
  const baseDir = getManagedOutputBaseDir({
    cwd: 'C:\\workspace\\project',
    tempRoot: 'C:\\temp-root',
    skillRootPath: 'C:\\skills\\pixiv-novel-extractor',
    env: {},
  })

  assert.equal(baseDir, resolve('C:\\workspace\\project'))
})

test('getManagedOutputBaseDir falls back to temp when cwd is inside the skill root', () => {
  const baseDir = getManagedOutputBaseDir({
    cwd: 'C:\\skills\\pixiv-novel-extractor',
    tempRoot: 'C:\\temp-root',
    skillRootPath: 'C:\\skills\\pixiv-novel-extractor',
    env: {},
  })

  assert.equal(baseDir, resolve('C:\\temp-root'))
})

test('resolveManagedOutputDir anchors relative paths under the managed base dir', () => {
  const outputDir = resolveManagedOutputDir('novel-out', {
    cwd: 'C:\\workspace\\project',
    tempRoot: 'C:\\temp-root',
    skillRootPath: 'C:\\skills\\pixiv-novel-extractor',
    env: {},
  })

  assert.equal(outputDir, resolve('C:\\workspace\\project', 'novel-out'))
})

test('resolveManagedOutputDir respects PIXIV_NOVEL_OUTPUT_DIR when provided', () => {
  const outputDir = resolveManagedOutputDir('novel-out', {
    cwd: 'C:\\skills\\pixiv-novel-extractor',
    tempRoot: 'C:\\temp-root',
    skillRootPath: 'C:\\skills\\pixiv-novel-extractor',
    env: {
      PIXIV_NOVEL_OUTPUT_DIR: 'D:\\pixiv-output',
    },
  })

  assert.equal(outputDir, resolve('D:\\pixiv-output', 'novel-out'))
})
