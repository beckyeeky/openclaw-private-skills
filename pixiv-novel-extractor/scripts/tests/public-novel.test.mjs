import assert from 'node:assert/strict'
import { mkdtemp, readdir, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { fetchPublicNovel } from '../lib/pixiv-api.mjs'
import { renderNovelMarkdown } from '../lib/render.mjs'
import { writeOutputs } from '../lib/output-files.mjs'

function createJsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return body
    },
  }
}

test('fetchPublicNovel parses content, series metadata, and embedded images', async () => {
  const fetchImpl = async () =>
    createJsonResponse({
      error: false,
      body: {
        id: 28063332,
        userName: 'beckyeeky',
        title: '测试小说',
        description: '第一段<br>第二段',
        tags: {
          tags: [{ tag: 'tag-a' }, { tag: 'tag-b' }],
        },
        content: '开头段落[newpage][uploadedimage:123456789]结尾 [[jumpuri:示例 > https://example.com]]',
        textEmbeddedImages: {
          '123456789': {
            novelImageId: '123456789-0',
            urls: {
              original: 'https://i.pximg.net/img-original/img/2024/01/01/00/00/00/123456789_p0.jpg',
            },
          },
        },
        seriesNavData: {
          seriesId: 5566,
          title: '系列标题',
          prev: { id: 1, title: '上一章' },
          next: { id: 3, title: '下一章' },
        },
      },
    })

  const novel = await fetchPublicNovel('28063332', { fetchImpl })

  assert.equal(novel.id, 28063332)
  assert.equal(novel.author, 'beckyeeky')
  assert.equal(novel.description, '第一段\n第二段')
  assert.deepEqual(novel.tags, ['tag-a', 'tag-b'])
  assert.equal(novel.series.id, 5566)
  assert.equal(novel.contentParts[1].type, 'image')
  assert.match(novel.contentParts[1].image.url, /^https:\/\/i\.pixiv\.cat\//)
  assert.match(novel.content, /---/)
})

test('renderNovelMarkdown keeps image placeholders and series links', () => {
  const markdown = renderNovelMarkdown({
    id: 28063332,
    title: '测试小说',
    author: 'beckyeeky',
    description: '简介',
    tags: ['tag-a'],
    sourceUrl: 'https://www.pixiv.net/novel/show.php?id=28063332',
    series: {
      id: 5566,
      title: '系列标题',
      prev: { id: 1, title: '上一章' },
      next: { id: 3, title: '下一章' },
    },
    contentParts: [
      { type: 'text', content: '第一段' },
      {
        type: 'image',
        image: {
          id: '123',
          url: 'https://i.pixiv.cat/example.jpg',
          fallbackUrls: ['https://i.pixiv.cat/example.jpg', 'https://pixiv.re/example.jpg'],
        },
      },
    ],
  }, { extractedAt: '2026-06-25T00:00:00.000Z' })

  assert.match(markdown, /^# 测试小说/m)
  assert.match(markdown, /Series: 系列标题/)
  assert.match(markdown, /!\[Pixiv embedded image 123\]\(https:\/\/i\.pixiv\.cat\/example\.jpg\)/)
  assert.match(markdown, /Alternate URLs: \[1\]\(https:\/\/pixiv\.re\/example\.jpg\)/)
})

test('extract output uses title-based filenames and avoids overwrite', async () => {
  const outputDir = await mkdtemp(join(tmpdir(), 'pixiv-output-'))
  await writeFile(join(outputDir, '测试小说.md'), 'existing\n', 'utf8')

  await writeOutputs('novel', {
    markdown: '# 测试小说\n',
    json: '{\n  "title": "测试小说"\n}\n',
  }, {
    format: 'both',
    outputDir,
    data: {
      id: 28063332,
      title: '测试小说',
    },
  })

  const files = await readdir(outputDir)
  assert.ok(files.includes('测试小说.md'))
  assert.ok(files.includes('测试小说-2.md'))
  assert.ok(files.includes('测试小说-2.json'))
})
