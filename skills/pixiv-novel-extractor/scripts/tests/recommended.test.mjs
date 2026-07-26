import assert from 'node:assert/strict'
import test from 'node:test'

import { fetchNovelRecommendations } from '../lib/pixiv-api.mjs'
import { renderRecommendedMarkdown } from '../lib/render.mjs'

function createJsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return body
    },
  }
}

test('fetchNovelRecommendations exchanges refresh token and maps novels', async () => {
  const calls = []
  const fetchImpl = async (url) => {
    calls.push(url)
    if (String(url).includes('/auth/token')) {
      return createJsonResponse({
        response: {
          access_token: 'access-token',
          user: { id: '42', name: 'User', account: 'pixiv-user' },
        },
      })
    }

    return createJsonResponse({
      novels: [
        {
          id: 100,
          title: '推荐小说',
          caption: '推荐简介',
          total_bookmarks: 12,
          total_view: 34,
          text_length: 5678,
          user: { id: 9, name: '作者' },
        },
      ],
    })
  }

  const novels = await fetchNovelRecommendations('refresh-token', { fetchImpl })

  assert.equal(calls.length, 2)
  assert.equal(novels[0].id, 100)
  assert.equal(novels[0].author, '作者')
  assert.equal(novels[0].totalBookmarks, 12)
  assert.equal(novels[0].textLength, 5678)
  assert.match(novels[0].sourceUrl, /id=100/)
})

test('renderRecommendedMarkdown outputs linked recommendations', () => {
  const markdown = renderRecommendedMarkdown([
    {
      id: 100,
      title: '推荐小说',
      caption: '推荐简介',
      author: '作者',
      totalBookmarks: 12,
      totalView: 34,
      textLength: 5678,
      sourceUrl: 'https://www.pixiv.net/novel/show.php?id=100',
    },
  ], { extractedAt: '2026-06-25T00:00:00.000Z' })

  assert.match(markdown, /^# Pixiv Novel Recommendations/m)
  assert.match(markdown, /\[推荐小说\]\(https:\/\/www\.pixiv\.net\/novel\/show\.php\?id=100\)/)
  assert.match(markdown, /Bookmarks: 12/)
  assert.match(markdown, /Length: 5678 chars/)
})
