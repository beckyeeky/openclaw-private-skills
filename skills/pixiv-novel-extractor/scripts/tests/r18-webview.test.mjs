import assert from 'node:assert/strict'
import { existsSync, rmSync, statSync } from 'node:fs'
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve, sep } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { formatCliError, parseArgs, runR18Extraction, USAGE } from '../extract-r18-webview.mjs'
import {
  extractPixivValueFromHtml,
  MAX_HTML_LENGTH,
  MAX_LITERAL_LENGTH,
  parseJsLiteral,
} from '../lib/js-literal.mjs'

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const SKILL_ROOT = resolve(SCRIPT_DIR, '..', '..')

const FAKE_REFRESH_TOKEN = 'DUMMY_REFRESH_TOKEN_NOT_REAL'
const PROBE_FILE = '/tmp/pixiv_r18_probe_should_not_exist'

function buildWebviewHtml(novelOverrides = {}) {
  const novel = {
    id: 23924083,
    title: 'R18 测试小说',
    userName: '作者名',
    caption: '第一段<br>第二段',
    tags: ['tag-a', { tag: 'tag-b' }],
    text: '开头段落[newpage]中段[uploadedimage:123456789]结尾 [[jumpuri:示例 > https://example.com]]',
    seriesId: 7788,
    seriesTitle: '系列名',
    xRestrict: 1,
    textEmbeddedImages: {
      123456789: {
        novelImageId: '123456789-0',
        urls: {
          original:
            'https://i.pximg.net/img-original/img/2024/01/01/00/00/00/123456789_p0.jpg',
        },
      },
    },
    ...novelOverrides,
  }

  return [
    '<!doctype html><html><head><title>pixiv</title></head><body>',
    '<script>',
    'window.pixiv = {',
    '  value: {',
    `    novel: ${JSON.stringify(novel)},`,
    '    authorDetails: { userName: "作者名" },',
    '  },',
    '};',
    '</script>',
    '</body></html>',
  ].join('\n')
}

function buildRawWebviewHtml(textExpression) {
  return [
    '<!doctype html><html><body><script>',
    'window.pixiv = {',
    '  value: {',
    `    novel: { id: 23924083, title: "evil", userName: "作者", caption: "", tags: [], text: ${textExpression} },`,
    '  },',
    '};',
    '</script></body></html>',
  ].join('\n')
}

function createStubFetch(html, { webviewStatus = 200, jsonBody = null } = {}) {
  const calls = []

  const fetchImpl = async (url, init = {}) => {
    const target = String(url)
    calls.push({ url: target, init })

    if (target.includes('/auth/token')) {
      return {
        ok: true,
        status: 200,
        async json() {
          return jsonBody ?? { response: { access_token: 'FAKE_ACCESS_TOKEN' } }
        },
        async text() {
          return ''
        },
      }
    }

    return {
      ok: webviewStatus >= 200 && webviewStatus < 300,
      status: webviewStatus,
      async json() {
        return {}
      },
      async text() {
        return html
      },
    }
  }

  return { fetchImpl, calls }
}

function createStdout() {
  const chunks = []
  return {
    chunks,
    write(chunk) {
      chunks.push(String(chunk))
      return true
    },
    text() {
      return chunks.join('')
    },
  }
}

async function makeContext() {
  const root = await mkdtemp(join(tmpdir(), 'pixiv-r18-'))
  const homeDir = join(root, 'home')
  const workspaceDir = join(root, 'workspace')
  const outputDir = join(root, 'explicit-out')
  return { root, homeDir, workspaceDir, outputDir }
}

async function runWithStub(stub, { argv, workspaceDir, homeDir }) {
  const stdout = createStdout()
  const result = await runR18Extraction({
    argv,
    fetchImpl: stub.fetchImpl,
    env: { PIXIV_REFRESH_TOKEN: FAKE_REFRESH_TOKEN },
    cwd: workspaceDir,
    homeDir,
    stdout,
  })
  return { result, stdout }
}

test('parseArgs validates format values and rejects unknown options', () => {
  assert.equal(parseArgs(['23924083']).format, 'both')
  assert.equal(parseArgs(['23924083', '--format', 'md']).format, 'md')
  assert.equal(parseArgs(['23924083', '--format=json']).format, 'json')
  assert.equal(parseArgs(['23924083', '-o', '/tmp/x']).output, '/tmp/x')

  assert.throws(() => parseArgs(['23924083', '--format']), /Missing value for --format/)
  assert.throws(() => parseArgs(['23924083', '--format', 'bogus']), /Invalid format "bogus"/)
  assert.throws(() => parseArgs(['23924083', '--nope']), /Unknown option: --nope/)
  assert.throws(() => parseArgs(['23924083', '-o']), /Missing value for --output/)
})

test('parseJsLiteral parses benign literals without executing them', () => {
  const value = parseJsLiteral("{ a: 'x', b: [1, 2,], c: true, d: null, e: -1.5e3, f: \"q\\nu\", g: '\\u4e2d' }")
  assert.equal(value.a, 'x')
  assert.deepEqual(value.b, [1, 2])
  assert.equal(value.c, true)
  assert.equal(value.d, null)
  assert.equal(value.e, -1500)
  assert.equal(value.f, 'q\nu')
  assert.equal(value.g, '中')
  assert.equal(Object.getPrototypeOf(value), null)
})

test('parseJsLiteral rejects every executable construct tried', () => {
  const rejected = [
    "{ a: (globalThis.__pixivProbe = true) }",
    "{ a: import('node:fs') }",
    "{ a: require('node:fs') }",
    "{ a: function () { return 1 } }",
    "{ a: () => 1 }",
    "{ a: new Date() }",
    '{ a: `tpl` }',
    '{ a: `tpl${1}` }',
    '{ a: 1 + 2 }',
    '{ a: [1, (2)] }',
    "{ a: process.env.PIXIV_REFRESH_TOKEN }",
    "{ a: 0x10 }",
    "{ a: 1n }",
    "{ a: { get b() { return 1 } } }",
    '[1, 2',
    '{ a: 1 }}',
  ]

  for (const source of rejected) {
    assert.throws(() => parseJsLiteral(source), /offset|literal|not allowed|unexpected/i, source)
  }

  assert.equal(globalThis.__pixivProbe, undefined)
})

test('parseJsLiteral cannot prototype-pollute the caller', () => {
  const value = parseJsLiteral('{ "__proto__": { "polluted": true }, "__proto__x": 1 }')
  assert.equal({}.polluted, undefined)
  assert.equal(Object.getPrototypeOf(value), null)
})

test('extractPixivValueFromHtml reads the pixiv bootstrap object', () => {
  const data = extractPixivValueFromHtml(buildWebviewHtml())
  assert.equal(data.novel.id, 23924083)
  assert.equal(data.novel.title, 'R18 测试小说')
  assert.equal(data.authorDetails.userName, '作者名')

  assert.throws(() => extractPixivValueFromHtml('<html>nothing here</html>'), /missing window\.pixiv/)

  // Alternate bootstrap shapes still resolve to the payload object.
  const direct = extractPixivValueFromHtml('<script>window.pixiv={novel:{text:"x"}}</script>')
  assert.equal(direct.novel.text, 'x')
  const marked = extractPixivValueFromHtml('<script>var a = 1; value: { novel: { text: "y" } };</script>')
  assert.equal(marked.novel.text, 'y')
})

test('R-18 extraction writes Markdown and JSON through the shared pipeline', async () => {
  const context = await makeContext()
  const stub = createStubFetch(buildWebviewHtml())
  const { result, stdout } = await runWithStub(stub, {
    argv: ['23924083', '--format', 'both', '-o', context.outputDir],
    workspaceDir: context.workspaceDir,
    homeDir: context.homeDir,
  })

  assert.equal(result.outputDir, resolve(context.outputDir))
  assert.deepEqual(
    result.files.map(file => file.split(sep).pop()).sort(),
    ['R18-测试小说.json', 'R18-测试小说.md']
  )

  const markdown = await readFile(join(context.outputDir, 'R18-测试小说.md'), 'utf8')
  assert.match(markdown, /^# R18 测试小说/m)
  assert.match(markdown, /- Source: \[Pixiv Novel\]\(https:\/\/www\.pixiv\.net\/novel\/show\.php\?id=23924083\)/)
  assert.match(markdown, /- Author: 作者名/)
  assert.match(markdown, /#tag-a #tag-b/)
  assert.match(markdown, /- Via: app-webview-v2/)
  assert.match(markdown, /- Series: 系列名/)
  assert.match(markdown, /!\[Pixiv embedded image 123456789\]\(https:\/\/i\.pixiv\.cat\//)
  assert.match(markdown, /Alternate URLs:/)
  assert.match(markdown, /\[示例\]\(https:\/\/example\.com\)/)
  assert.doesNotMatch(markdown, /\[uploadedimage:/)
  assert.match(markdown, /- Extracted At: /)

  const payload = JSON.parse(await readFile(join(context.outputDir, 'R18-测试小说.json'), 'utf8'))
  assert.equal(payload.id, 23924083)
  assert.equal(payload.via, 'app-webview-v2')
  assert.equal(payload.xRestrict, 1)
  assert.equal(payload.series.id, 7788)
  const imagePart = payload.contentParts.find(part => part.type === 'image')
  assert.equal(imagePart.image.id, '123456789')
  assert.match(imagePart.image.url, /^https:\/\/i\.pixiv\.cat\//)
  assert.ok(imagePart.image.fallbackUrls.some(url => url.startsWith('https://pixiv.re/')))
  assert.doesNotMatch(payload.content, /\[uploadedimage:/)

  assert.equal(stdout.text().match(/Saved R-18\/auth novel/g).length, 1)
  assert.equal(stdout.text().match(/R18-测试小说\.md/g).length, 1)

  assert.equal(stub.calls.length, 2)
  assert.match(stub.calls[0].url, /^https:\/\/oauth\.secure\.pixiv\.net\/auth\/token$/)
  assert.match(stub.calls[1].url, /^https:\/\/app-api\.pixiv\.net\/webview\/v2\/novel\?id=23924083$/)
  assert.equal(stub.calls[1].init.headers.Authorization, 'Bearer FAKE_ACCESS_TOKEN')

  await rm(context.root, { recursive: true, force: true })
})

test('default output dir follows the managed base dir when cwd is outside the skill root', async () => {
  const context = await makeContext()
  const stub = createStubFetch(buildWebviewHtml())

  const { result } = await runWithStub(stub, {
    argv: ['23924083', '--format', 'md'],
    workspaceDir: context.workspaceDir,
    homeDir: context.homeDir,
  })

  assert.equal(
    result.outputDir,
    resolve(context.workspaceDir, 'Pixiv-Novel-Skill', '23924083_R18-测试小说')
  )
  assert.ok(readdir(result.outputDir))

  await rm(context.root, { recursive: true, force: true })
})

test('default output dir never lands inside the skill folder when cwd is the skill root', async () => {
  const context = await makeContext()
  const stub = createStubFetch(buildWebviewHtml())

  const { result } = await runWithStub(stub, {
    argv: ['23924083', '--format', 'md'],
    workspaceDir: SKILL_ROOT,
    homeDir: context.homeDir,
  })

  assert.equal(resolve(result.outputDir), resolve(tmpdir(), 'Pixiv-Novel-Skill', '23924083_R18-测试小说'))
  assert.ok(!result.outputDir.startsWith(SKILL_ROOT + sep))
  assert.ok(!existsSync(join(SKILL_ROOT, 'Pixiv-Novel-Skill')))

  await rm(result.outputDir, { recursive: true, force: true })
  await rm(context.root, { recursive: true, force: true })
})

test('re-running into the same -o keeps the first export and appends -2', async () => {
  const context = await makeContext()
  const stub = createStubFetch(buildWebviewHtml())
  const argv = ['23924083', '--format', 'both', '-o', context.outputDir]

  const first = await runWithStub(stub, { argv, workspaceDir: context.workspaceDir, homeDir: context.homeDir })
  const originalMarkdown = await readFile(join(context.outputDir, 'R18-测试小说.md'), 'utf8')

  const second = await runWithStub(stub, { argv, workspaceDir: context.workspaceDir, homeDir: context.homeDir })

  assert.deepEqual(
    first.result.files.map(file => file.split(sep).pop()).sort(),
    ['R18-测试小说.json', 'R18-测试小说.md']
  )
  assert.deepEqual(
    second.result.files.map(file => file.split(sep).pop()).sort(),
    ['R18-测试小说-2.json', 'R18-测试小说-2.md']
  )

  const files = (await readdir(context.outputDir)).sort()
  assert.deepEqual(files, ['R18-测试小说-2.json', 'R18-测试小说-2.md', 'R18-测试小说.json', 'R18-测试小说.md'])
  assert.equal(await readFile(join(context.outputDir, 'R18-测试小说.md'), 'utf8'), originalMarkdown)

  await rm(context.root, { recursive: true, force: true })
})

test('invalid arguments fail before any network request and write nothing', async () => {
  const context = await makeContext()
  const stub = createStubFetch(buildWebviewHtml())

  const cases = [
    { argv: ['23924083', '--format'], error: /Missing value for --format/ },
    { argv: ['23924083', '--format', 'bogus'], error: /Invalid format "bogus"/ },
    { argv: ['23924083', '--format', ''], error: /Missing value for --format/ },
    { argv: ['23924083', '--nope', '-o', context.outputDir], error: /Unknown option: --nope/ },
    { argv: ['23924083', 'not-a-novel-id'], error: /exactly one Pixiv novel/ },
    { argv: ['not-a-novel-id', '-o', context.outputDir], error: /Could not parse novel id/ },
    { argv: ['-o', context.outputDir], error: /exactly one Pixiv novel/ },
    { argv: ['1', '2', '-o', context.outputDir], error: /exactly one Pixiv novel/ },
    { argv: ['23924083', '--output'], error: /Missing value for --output/ },
    { argv: ['23924083', '-o', ''], error: /Invalid output path/ },
    { argv: ['23924083', '--output='], error: /Invalid output path/ },
    { argv: ['23924083', '-o', '-x'], error: /Invalid output path/ },
    { argv: ['23924083', '--output', '--format'], error: /Invalid output path/ },
  ]

  for (const testCase of cases) {
    await assert.rejects(
      runWithStub(stub, { argv: testCase.argv, workspaceDir: context.workspaceDir, homeDir: context.homeDir }),
      testCase.error
    )
  }

  assert.equal(stub.calls.length, 0)
  assert.equal(existsSync(context.outputDir), false)

  await rm(context.root, { recursive: true, force: true })
})

test('--help prints usage without touching the network', async () => {
  const context = await makeContext()
  const stub = createStubFetch(buildWebviewHtml())

  const { result, stdout } = await runWithStub(stub, {
    argv: ['--help'],
    workspaceDir: context.workspaceDir,
    homeDir: context.homeDir,
  })

  assert.equal(result.help, true)
  assert.ok(stdout.text().includes(USAGE))
  assert.equal(stub.calls.length, 0)

  await rm(context.root, { recursive: true, force: true })
})

test('missing refresh token fails before the webview request', async () => {
  const context = await makeContext()
  const stub = createStubFetch(buildWebviewHtml())
  const stdout = createStdout()

  await assert.rejects(
    runR18Extraction({
      argv: ['23924083', '-o', context.outputDir],
      fetchImpl: stub.fetchImpl,
      env: {},
      cwd: context.workspaceDir,
      homeDir: context.homeDir,
      stdout,
    }),
    /No refresh_token/
  )

  assert.equal(stub.calls.length, 0)
  assert.equal(stdout.text(), '')
  assert.equal(existsSync(context.outputDir), false)

  await rm(context.root, { recursive: true, force: true })
})

test('HTTP failure writes no files and never reports success', async () => {
  const context = await makeContext()
  const stub = createStubFetch(buildWebviewHtml(), { webviewStatus: 404 })
  const stdout = createStdout()

  await assert.rejects(
    runR18Extraction({
      argv: ['23924083', '-o', context.outputDir],
      fetchImpl: stub.fetchImpl,
      env: { PIXIV_REFRESH_TOKEN: FAKE_REFRESH_TOKEN },
      cwd: context.workspaceDir,
      homeDir: context.homeDir,
      stdout,
    }),
    /HTTP 404/
  )

  assert.equal(stdout.text(), '')
  assert.equal(existsSync(context.outputDir), false)

  await rm(context.root, { recursive: true, force: true })
})

test('a tampered webview payload is rejected with zero side effects', async () => {
  rmSync(PROBE_FILE, { force: true })
  const context = await makeContext()

  const evilText =
    `(process.env.PWNED = (process.env.PIXIV_REFRESH_TOKEN ? 'token-readable' : 'no-token'), ` +
    `import('node:fs').then(m => m.writeFileSync(${JSON.stringify(PROBE_FILE)}, 'written')), 'body')`
  const evilHtml = buildRawWebviewHtml(evilText)
  const stub = createStubFetch(evilHtml)
  const stdout = createStdout()

  await assert.rejects(
    runR18Extraction({
      argv: ['23924083', '--format', 'md', '-o', context.outputDir],
      fetchImpl: stub.fetchImpl,
      env: { PIXIV_REFRESH_TOKEN: FAKE_REFRESH_TOKEN },
      cwd: context.workspaceDir,
      homeDir: context.homeDir,
      stdout,
    }),
    /Malformed window\.pixiv payload|not allowed/
  )

  assert.equal(process.env.PWNED, undefined)
  assert.equal(existsSync(PROBE_FILE), false)
  assert.equal(existsSync(context.outputDir), false)
  assert.equal(stdout.text(), '')
  assert.equal(stub.calls.length, 2)

  await rm(context.root, { recursive: true, force: true })
  rmSync(PROBE_FILE, { force: true })
})

test('the webview response is never evaluated as source code', async () => {
  const context = await makeContext()
  const evilHtml = buildWebviewHtml({
    text: 'safe body',
    injected: 'Function("return 1")()',
  })
  const stub = createStubFetch(evilHtml)

  const { result } = await runWithStub(stub, {
    argv: ['23924083', '--format', 'json', '-o', context.outputDir],
    workspaceDir: context.workspaceDir,
    homeDir: context.homeDir,
  })

  const parsed = extractPixivValueFromHtml(evilHtml)
  assert.equal(parsed.novel.injected, 'Function("return 1")()')

  const payload = JSON.parse(await readFile(result.files[0], 'utf8'))
  assert.equal(payload.content, 'safe body')
  assert.equal(payload.via, 'app-webview-v2')

  await rm(context.root, { recursive: true, force: true })
})

test('parseArgs validates --output values as strictly as --format', () => {
  assert.equal(parseArgs(['23924083', '-o', '/tmp/x']).output, '/tmp/x')
  assert.equal(parseArgs(['23924083', '--output', 'out']).output, 'out')
  assert.equal(parseArgs(['23924083', '--output=out']).output, 'out')
  // A path that genuinely starts with '-' is still expressible, but only via './'.
  assert.equal(parseArgs(['23924083', '-o', './-name']).output, './-name')
  assert.equal(parseArgs(['23924083', '--output=./-name']).output, './-name')

  assert.throws(() => parseArgs(['23924083', '-o']), /Missing value for --output/)
  assert.throws(() => parseArgs(['23924083', '-o', '']), /Invalid output path/)
  assert.throws(() => parseArgs(['23924083', '--output=']), /Invalid output path/)
  assert.throws(() => parseArgs(['23924083', '-o', '-x']), /Invalid output path/)
  assert.throws(() => parseArgs(['23924083', '--output', '--format']), /Invalid output path/)
  assert.throws(() => parseArgs(['23924083', '--output=-x']), /Invalid output path/)
})

test('payload location falls back to the whole document when no script region matches', () => {
  const html = '<div data-bootstrap>value: { novel: { text: "OUTSIDE" } }</div>'
  assert.equal(extractPixivValueFromHtml(html).novel.text, 'OUTSIDE')
})

test('an unlocatable bootstrap reports a location error, not private/deleted', async () => {
  const context = await makeContext()
  // Old implementation picked the `{}` from `window.pixiv || {}` and then
  // reported a bogus "private/deleted" diagnosis. It must now fail on location.
  const html = '<script>window.pixiv = window.pixiv || {}; window.pixiv.value = { novel: { text: "L" } };</script>'
  const stub = createStubFetch(html)
  const stdout = createStdout()

  let caught = null
  try {
    await runR18Extraction({
      argv: ['23924083', '-o', context.outputDir],
      fetchImpl: stub.fetchImpl,
      env: { PIXIV_REFRESH_TOKEN: FAKE_REFRESH_TOKEN },
      cwd: context.workspaceDir,
      homeDir: context.homeDir,
      stdout,
    })
  } catch (error) {
    caught = error
  }

  assert.ok(caught, 'expected the unlocatable bootstrap to fail')
  assert.match(caught.message, /missing window\.pixiv or value bootstrap object/)
  assert.doesNotMatch(caught.message, /private|deleted/i)
  assert.equal(existsSync(context.outputDir), false)
  assert.equal(stdout.text(), '')

  await rm(context.root, { recursive: true, force: true })
})

test('extractPixivValueFromHtml prefers the value member and tolerates a non-literal outer sibling', () => {
  // Regression: the old implementation selected the `value: { … }` member, so
  // an outer object carrying e.g. `kept: undefined` must not break extraction.
  const html =
    '<script>window.pixiv = { value: { novel: { text: "BODY" } }, kept: undefined };</script>'
  const data = extractPixivValueFromHtml(html)
  assert.equal(data.novel.text, 'BODY')
  assert.deepEqual(Object.keys(data), ['novel'])

  // Even an outer object that is not a literal at all (function expression) is fine.
  const withFunction =
    '<script>window.pixiv = { value: { novel: { text: "D" } }, fn: function () {} };</script>'
  assert.equal(extractPixivValueFromHtml(withFunction).novel.text, 'D')
})

test('payload location is string-aware and ignores a value: decoy inside a string', () => {
  const html = [
    `<script>var preamble = 'decoy value: { novel: { text: "DECOY" } }';</script>`,
    '<script>window.pixiv = { value: { novel: { text: "REAL" } } };</script>',
  ].join('\n')

  const data = extractPixivValueFromHtml(html)
  assert.equal(data.novel.text, 'REAL')
})

test('parseJsLiteral accepts decimal numeric keys but rejects key expressions', () => {
  const value = parseJsLiteral('{ textEmbeddedImages: { 123456789: { id: "123456789-0" }, 42: "x" } }')
  const keys = Object.keys(value.textEmbeddedImages)
  assert.deepEqual([...keys].sort(), ['123456789', '42'].sort())
  assert.equal(value.textEmbeddedImages['123456789'].id, '123456789-0')
  assert.equal(value.textEmbeddedImages['42'], 'x')

  assert.throws(() => parseJsLiteral('{ 1 + 2: 3 }'), /expected ":" after object key/)
  assert.throws(() => parseJsLiteral('{ 0x10: 1 }'), /expected ":" after object key/)
  assert.throws(() => parseJsLiteral('{ -1: 1 }'), /object key/)
})

test('errors never echo remote payload bytes into the CLI log', () => {
  const PRIVATE_SENTINEL = 'PRIVATE_SENTINEL_DO_NOT_LEAK'
  // Malformed immediately after the secret-looking text so that the removed
  // context snippet would have contained it.
  const html =
    `<script>window.pixiv = { value: { novel: { text: "${PRIVATE_SENTINEL}" + "x" } } };</script>`

  let caught = null
  try {
    extractPixivValueFromHtml(html)
  } catch (error) {
    caught = error
  }

  assert.ok(caught, 'expected the malformed payload to be rejected')
  const re = new RegExp(PRIVATE_SENTINEL)
  assert.doesNotMatch(caught.message, re)
  assert.doesNotMatch(formatCliError(caught), re)
  assert.doesNotMatch(String(caught.stack ?? ''), re)
  // Diagnostics are still useful: the offset is reported.
  assert.match(formatCliError(caught), /offset \d+/)
})

test('length budgets are UTF-8 bytes and HTML has a wider separate budget', () => {
  assert.ok(MAX_HTML_LENGTH > MAX_LITERAL_LENGTH)

  // 2,000,000 CJK characters = 6,000,000 UTF-8 bytes but only 2,000,000 code
  // units; the payload limit must be measured in bytes.
  assert.throws(
    () => parseJsLiteral('中'.repeat(2_000_000)),
    /window\.pixiv payload is too large to parse \(6000000 bytes; limit 4194304 bytes\)/
  )

  const oversizedHtml =
    '<script>window.pixiv = { value: { novel: { text: "x" } } }</script>' + 'a'.repeat(MAX_HTML_LENGTH + 1)
  assert.throws(
    () => extractPixivValueFromHtml(oversizedHtml),
    /webview HTML is too large to parse/
  )
})

test('a located payload without novel.text is reported without guessing private/deleted', async () => {
  const context = await makeContext()
  const html = '<script>window.pixiv = { value: { novel: { id: 1, title: "t" } } };</script>'
  const stub = createStubFetch(html)
  const stdout = createStdout()

  let caught = null
  try {
    await runR18Extraction({
      argv: ['23924083', '-o', context.outputDir],
      fetchImpl: stub.fetchImpl,
      env: { PIXIV_REFRESH_TOKEN: FAKE_REFRESH_TOKEN },
      cwd: context.workspaceDir,
      homeDir: context.homeDir,
      stdout,
    })
  } catch (error) {
    caught = error
  }

  assert.ok(caught, 'expected the missing body text to fail')
  assert.match(caught.message, /no novel\.text/)
  assert.match(caught.message, /cause not determined/)
  assert.doesNotMatch(caught.message, /private\/deleted\?/)
  assert.equal(existsSync(context.outputDir), false)
  assert.equal(stdout.text(), '')

  await rm(context.root, { recursive: true, force: true })
})

test('R-18 extraction still works when the outer window.pixiv object has a non-literal sibling', async () => {
  const context = await makeContext()
  const html = [
    '<!doctype html><html><body><script>',
    'window.pixiv = {',
    '  value: {',
    '    novel: { id: 23924083, title: "外层兼容", userName: "作者", caption: "", tags: [], text: "正文[newpage]结束" },',
    '  },',
    '  kept: undefined,',
    '};',
    '</script></body></html>',
  ].join('\n')
  const stub = createStubFetch(html)

  const { result, stdout } = await runWithStub(stub, {
    argv: ['23924083', '--format', 'md', '-o', context.outputDir],
    workspaceDir: context.workspaceDir,
    homeDir: context.homeDir,
  })

  assert.equal(result.title, '外层兼容')
  assert.deepEqual(result.files.map(file => file.split(sep).pop()), ['外层兼容.md'])
  assert.match(await readFile(result.files[0], 'utf8'), /- Via: app-webview-v2/)
  assert.match(stdout.text(), /Saved R-18\/auth novel/)
  assert.equal(stub.calls.length, 2)

  await rm(context.root, { recursive: true, force: true })
})
