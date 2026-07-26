import assert from 'node:assert/strict'
import test from 'node:test'

import { extractPixivNovelId } from '../lib/input.mjs'

test('extractPixivNovelId reads a bare novel ID', () => {
  assert.equal(extractPixivNovelId(' 28063332 '), '28063332')
})

test('extractPixivNovelId reads the standard Pixiv novel URL', () => {
  assert.equal(
    extractPixivNovelId('https://www.pixiv.net/novel/show.php?id=28063332'),
    '28063332',
  )
})

test('extractPixivNovelId reads a URL embedded in share text', () => {
  assert.equal(
    extractPixivNovelId('作品标题\nhttps://www.pixiv.net/novel/show.php?id=28063332\n'),
    '28063332',
  )
})

test('extractPixivNovelId reads an encoded Pixiv novel URL', () => {
  assert.equal(
    extractPixivNovelId('https%3A%2F%2Fwww.pixiv.net%2Fnovel%2Fshow.php%3Fid%3D28063332'),
    '28063332',
  )
})

test('extractPixivNovelId rejects unrelated text', () => {
  assert.equal(extractPixivNovelId('Pixiv novel without a link'), null)
})
