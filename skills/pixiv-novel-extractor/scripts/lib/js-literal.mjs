/**
 * Strict, non-executing parser for the tiny JavaScript literal subset used by
 * the Pixiv App webview bootstrap (`window.pixiv = { … }`).
 *
 * Security contract: this module NEVER evaluates its input. It does not use
 * `Function`, `eval`, `vm`, `JSON.parse` revivers, or any other construct that
 * can run code. Anything outside the supported grammar
 * (object / array / string / number / true / false / null literals, plus
 * unquoted identifier-like keys, decimal numeric keys, and trailing commas) is
 * rejected with an error, so a tampered webview response fails loudly instead
 * of executing locally.
 *
 * Deliberately NOT supported (all hard errors): function calls, member access,
 * operators, template literals, comments, spread, `new`, arrow functions,
 * identifiers as values, hexadecimal/`.5`/`+1`/`1n` numbers, unknown escapes.
 * If Pixiv ever changes the webview payload to such a shape, the extraction
 * fails with a clear message; extend the grammar here rather than restoring any
 * form of evaluation.
 *
 * Size limits are enforced in UTF-8 **bytes** (not UTF-16 code units) so the
 * error text and the real budget agree:
 *   - `MAX_LITERAL_LENGTH` (4 MiB) bounds the payload literal that is parsed.
 *   - `MAX_HTML_LENGTH` (16 MiB) is a deliberately wider, separate budget for
 *     the whole page so that a page carrying unrelated inline chrome is not
 *     rejected before the payload is even located. Location runs only after
 *     this check, so the scan is bounded.
 * These are budgets, not a promise that every real-world novel page fits; an
 * unusually large page still fails closed.
 */

/** UTF-8 byte budget for the payload literal handed to `parseJsLiteral`. */
export const MAX_LITERAL_LENGTH = 4 * 1024 * 1024
/** Wider, separate UTF-8 byte budget for the raw webview HTML document. */
export const MAX_HTML_LENGTH = 16 * 1024 * 1024

const WHITESPACE = new Set([' ', '\t', '\n', '\r', '\f', '\v', '\u00a0', '\ufeff'])
const KEY_START = /[A-Za-z_$]/
const KEY_CHAR = /[A-Za-z0-9_$]/
const NUMBER_PATTERN = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/
const SCRIPT_PATTERN = /<script\b[^>]*>([\s\S]*?)<\/script\s*>/gi
const SIMPLE_ESCAPES = {
  n: '\n',
  r: '\r',
  t: '\t',
  b: '\b',
  f: '\f',
  v: '\v',
  0: '\0',
  "'": "'",
  '"': '"',
  '\\': '\\',
  '/': '/',
}

/**
 * Build a parse error that reports the byte offset and a description of the
 * offending construct, but **never** echoes the surrounding source text. The
 * webview payload may contain private / R-18 novel body, and stderr from this
 * skill is collected into host logs, so remote bytes must not leak into
 * messages.
 */
function syntaxError(index, message) {
  const error = new Error(`Malformed window.pixiv payload at offset ${index}: ${message}`)
  error.name = 'PixivLiteralSyntaxError'
  return error
}

class LiteralParser {
  constructor(source) {
    this.source = source
    this.index = 0
  }

  atEnd() {
    return this.index >= this.source.length
  }

  fail(message) {
    throw syntaxError(this.index, message)
  }

  peek() {
    return this.source[this.index]
  }

  skipWhitespace() {
    while (this.index < this.source.length && WHITESPACE.has(this.source[this.index])) {
      this.index += 1
    }
  }

  parseValue() {
    this.skipWhitespace()
    if (this.atEnd()) this.fail('unexpected end of input')

    const ch = this.peek()
    if (ch === '{') return this.parseObject()
    if (ch === '[') return this.parseArray()
    if (ch === '"' || ch === "'") return this.parseString()
    if (ch === '-' || (ch >= '0' && ch <= '9')) return this.parseNumber()
    if (ch === 't') return this.parseKeyword('true', true)
    if (ch === 'f') return this.parseKeyword('false', false)
    if (ch === 'n') return this.parseKeyword('null', null)
    if (ch === '`') this.fail('template literals are not allowed')
    if (ch === '(') this.fail('grouped or called expressions are not allowed')
    if (ch === '.') this.fail('member access is not allowed')
    if (ch === '+' || ch === '*' || ch === '/' || ch === '%' || ch === '=' || ch === '!' || ch === '&' || ch === '|' || ch === '?' || ch === ':' || ch === ';' || ch === '<' || ch === '>') {
      this.fail(`operator ${JSON.stringify(ch)} is not allowed`)
    }
    this.fail(`unsupported value starting with ${JSON.stringify(ch)}; only literals are accepted`)
  }

  parseKeyword(word, value) {
    if (this.source.slice(this.index, this.index + word.length) !== word) {
      this.fail('unsupported identifier; only literals (true, false, null) are accepted as values')
    }
    this.index += word.length
    return value
  }

  parseObject() {
    this.index += 1 // consume '{'
    const result = Object.create(null)
    this.skipWhitespace()
    if (this.peek() === '}') {
      this.index += 1
      return result
    }

    while (true) {
      this.skipWhitespace()
      const key = this.parseKey()
      this.skipWhitespace()
      if (this.peek() !== ':') this.fail('expected ":" after object key')
      this.index += 1
      result[key] = this.parseValue()
      this.skipWhitespace()
      const ch = this.peek()
      if (ch === ',') {
        this.index += 1
        this.skipWhitespace()
        if (this.peek() === '}') {
          this.index += 1
          return result
        }
        continue
      }
      if (ch === '}') {
        this.index += 1
        return result
      }
      this.fail('expected "," or "}" in object literal')
    }
  }

  parseArray() {
    this.index += 1 // consume '['
    const result = []
    this.skipWhitespace()
    if (this.peek() === ']') {
      this.index += 1
      return result
    }

    while (true) {
      result.push(this.parseValue())
      this.skipWhitespace()
      const ch = this.peek()
      if (ch === ',') {
        this.index += 1
        this.skipWhitespace()
        if (this.peek() === ']') {
          this.index += 1
          return result
        }
        continue
      }
      if (ch === ']') {
        this.index += 1
        return result
      }
      this.fail('expected "," or "]" in array literal')
    }
  }

  parseKey() {
    const ch = this.peek()

    if (ch === '"' || ch === "'") return this.parseString()

    // Decimal numeric keys are legal JS object keys and are used by Pixiv for
    // embedded-image maps (`textEmbeddedImages: { 123456789: { … } }`). Only a
    // plain non-negative number literal is accepted here; anything else (e.g.
    // `1 + 2:`) leaves a non-`:` character next and is rejected by the caller.
    if (typeof ch === 'string' && ch >= '0' && ch <= '9') {
      const match = NUMBER_PATTERN.exec(this.source.slice(this.index))
      if (!match || match[0].length === 0) this.fail('malformed numeric object key')
      this.index += match[0].length
      return String(Number(match[0]))
    }

    if (typeof ch !== 'string' || !KEY_START.test(ch)) {
      this.fail('expected an object key (quoted string, identifier, or decimal number)')
    }

    const start = this.index
    while (this.index < this.source.length && KEY_CHAR.test(this.source[this.index])) {
      this.index += 1
    }
    return this.source.slice(start, this.index)
  }

  parseString() {
    const quote = this.peek()
    this.index += 1
    let value = ''

    while (true) {
      if (this.atEnd()) this.fail('unterminated string literal')
      const ch = this.source[this.index]
      if (ch === quote) {
        this.index += 1
        return value
      }
      if (ch === '\\') {
        value += this.parseEscape()
        continue
      }
      value += ch
      this.index += 1
    }
  }

  parseEscape() {
    this.index += 1 // consume '\'
    if (this.atEnd()) this.fail('unterminated escape sequence')
    const ch = this.source[this.index]

    if (Object.prototype.hasOwnProperty.call(SIMPLE_ESCAPES, ch)) {
      this.index += 1
      return SIMPLE_ESCAPES[ch]
    }

    if (ch === 'u') {
      this.index += 1
      const hex = this.source.slice(this.index, this.index + 4)
      if (!/^[0-9a-fA-F]{4}$/.test(hex)) this.fail('invalid \\u escape')
      this.index += 4
      return String.fromCharCode(parseInt(hex, 16))
    }

    if (ch === 'x') {
      this.index += 1
      const hex = this.source.slice(this.index, this.index + 2)
      if (!/^[0-9a-fA-F]{2}$/.test(hex)) this.fail('invalid \\x escape')
      this.index += 2
      return String.fromCharCode(parseInt(hex, 16))
    }

    this.fail(`unsupported escape sequence \\${ch}`)
  }

  parseNumber() {
    const match = NUMBER_PATTERN.exec(this.source.slice(this.index))
    if (!match || match[0].length === 0) this.fail('malformed number literal')
    this.index += match[0].length
    return Number(match[0])
  }
}

/**
 * Parse a JavaScript literal (object/array/string/number/boolean/null) without
 * executing any of it. Throws `PixivLiteralSyntaxError` on anything else.
 */
export function parseJsLiteral(source) {
  if (typeof source !== 'string') {
    throw new Error('parseJsLiteral expects a string')
  }
  const bytes = Buffer.byteLength(source, 'utf8')
  if (bytes > MAX_LITERAL_LENGTH) {
    throw new Error(
      `window.pixiv payload is too large to parse (${bytes} bytes; limit ${MAX_LITERAL_LENGTH} bytes)`
    )
  }

  const parser = new LiteralParser(source)
  const value = parser.parseValue()
  parser.skipWhitespace()
  if (!parser.atEnd()) parser.fail('unexpected trailing content after literal')
  return value
}

function isIdentifierStart(ch) {
  return typeof ch === 'string' && KEY_START.test(ch)
}

function isIdentifierChar(ch) {
  return typeof ch === 'string' && KEY_CHAR.test(ch)
}

/** Skip a quoted string / template literal, honouring backslash escapes. */
function skipQuoted(text, start) {
  const quote = text[start]
  let index = start + 1
  while (index < text.length) {
    const ch = text[index]
    if (ch === '\\') {
      index += 2
      continue
    }
    if (ch === quote) return index + 1
    index += 1
  }
  return text.length
}

/**
 * Walk a JavaScript-ish text region and record the positions of the obvious
 * bootstrap markers, skipping anything inside string literals. This is what
 * keeps a `value: {` that merely appears inside the novel body (which is served
 * as a JSON string) from being mistaken for the real member.
 *
 * Returns `{ memberBraces, windowBrace }` where the entries are the indices of
 * the opening `{` of each `value: { … }` member / of the `window.pixiv = { … }`
 * assignment.
 */
function scanBootstrapMarkers(text) {
  const memberBraces = []
  let windowBrace = null
  let index = 0

  while (index < text.length) {
    const ch = text[index]

    if (ch === '"' || ch === "'" || ch === '`') {
      index = skipQuoted(text, index)
      continue
    }

    if (!isIdentifierStart(ch)) {
      index += 1
      continue
    }

    let end = index + 1
    while (end < text.length && isIdentifierChar(text[end])) end += 1
    const token = text.slice(index, end)

    if (token === 'value') {
      let cursor = end
      while (cursor < text.length && WHITESPACE.has(text[cursor])) cursor += 1
      if (text[cursor] === ':') {
        cursor += 1
        while (cursor < text.length && WHITESPACE.has(text[cursor])) cursor += 1
        if (text[cursor] === '{') memberBraces.push(cursor)
      }
    } else if (token === 'window' && windowBrace === null) {
      let cursor = end
      while (cursor < text.length && WHITESPACE.has(text[cursor])) cursor += 1
      if (text[cursor] === '.') {
        cursor += 1
        while (cursor < text.length && WHITESPACE.has(text[cursor])) cursor += 1
        if (text.startsWith('pixiv', cursor)) {
          cursor += 'pixiv'.length
          while (cursor < text.length && WHITESPACE.has(text[cursor])) cursor += 1
          if (text[cursor] === '=') {
            cursor += 1
            while (cursor < text.length && WHITESPACE.has(text[cursor])) cursor += 1
            if (text[cursor] === '{') windowBrace = cursor
          }
        }
      }
    }

    index = end
  }

  return { memberBraces, windowBrace }
}

function collectScriptRegions(html) {
  const regions = []
  SCRIPT_PATTERN.lastIndex = 0
  let match
  while ((match = SCRIPT_PATTERN.exec(html)) !== null) {
    const open = match[0].indexOf('>')
    const close = match[0].lastIndexOf('</script')
    if (open >= 0 && close > open) {
      regions.push({ start: match.index + open + 1, end: match.index + close })
    }
  }
  return regions
}

/**
 * Locate candidate payload objects, **member-first**.
 *
 * Priority order is deliberate: the original implementation selected the
 * `value: { … }` member, and that member is a self-contained literal. Reading
 * the whole `window.pixiv = { … }` outer object instead would require every
 * sibling member to be a literal too, so an outer `{ value: { … }, kept:
 * undefined }` would break extraction that used to work. We therefore try the
 * `value` member first and only fall back to the outer object.
 *
 * Script regions are scanned before the whole document (the bootstrap is
 * JavaScript, so restricting the first pass keeps stray markup out of the way),
 * but a whole-document pass always follows so the previous behaviour of finding
 * the marker anywhere on the page is preserved. Both passes are string-aware,
 * so a `value: {` that only occurs inside the novel text is never selected.
 */
function locatePayloadCandidates(html) {
  const regions = collectScriptRegions(html)

  const candidates = []
  const seen = new Set()

  // `window.pixiv = { … }` found anywhere is remembered from the first pass
  // that saw it, but is always ranked after every `value: { … }` member.
  let windowBrace = null

  const collectFrom = scope => {
    const { memberBraces, windowBrace: brace } = scanBootstrapMarkers(scope.text)
    for (const local of memberBraces) {
      const start = scope.offset + local
      if (!seen.has(start)) {
        seen.add(start)
        candidates.push(start)
      }
    }
    if (brace !== null && windowBrace === null) windowBrace = scope.offset + brace
  }

  for (const region of regions) {
    collectFrom({ text: html.slice(region.start, region.end), offset: region.start })
  }

  // Whole-document pass, so a marker that lives outside any matched <script>
  // region (or on a page with no script tag at all) is still found — no
  // behaviour loss vs. the previous whole-page marker search. Duplicates are
  // filtered by `seen`.
  collectFrom({ text: html, offset: 0 })

  if (windowBrace !== null && !seen.has(windowBrace)) {
    seen.add(windowBrace)
    candidates.push(windowBrace)
  }

  return candidates
}

function findObjectEnd(html, start) {
  let depth = 0
  let quote = null

  for (let index = start; index < html.length; index += 1) {
    const ch = html[index]

    if (quote) {
      if (ch === '\\') {
        index += 1
        continue
      }
      if (ch === quote) quote = null
      continue
    }

    if (ch === '"' || ch === "'") {
      quote = ch
      continue
    }
    if (ch === '`') {
      throw syntaxError(index, 'template literals are not allowed')
    }
    if (ch === '{') {
      depth += 1
      continue
    }
    if (ch === '}') {
      depth -= 1
      if (depth === 0) return index + 1
    }
  }

  throw new Error('failed to balance braces for the window.pixiv payload')
}

/**
 * Unwrap the bootstrap shape. The interesting object is the `value` member
 * (`window.pixiv = { value: { novel: … } }`), but a direct
 * `window.pixiv = { novel: … }` object is returned as-is.
 */
function unwrapPayloadObject(parsed) {
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
  if (parsed.novel !== undefined) return parsed

  const inner = parsed.value
  if (inner && typeof inner === 'object' && !Array.isArray(inner)) return inner

  return parsed
}

/**
 * Extract the `window.pixiv` payload object from a webview HTML document.
 * The returned value is a freshly built, null-prototype object tree produced by
 * `parseJsLiteral`; no part of the HTML is ever evaluated.
 *
 * Throws a *location* error when the bootstrap object cannot be found at all,
 * and a *parse* error when the located literal is malformed. A located payload
 * that simply lacks `novel.text` is reported by the caller, not here.
 */
export function extractPixivValueFromHtml(html) {
  if (typeof html !== 'string') {
    throw new Error('webview HTML must be a string')
  }

  const bytes = Buffer.byteLength(html, 'utf8')
  if (bytes > MAX_HTML_LENGTH) {
    throw new Error(
      `webview HTML is too large to parse (${bytes} bytes; limit ${MAX_HTML_LENGTH} bytes)`
    )
  }

  const candidates = locatePayloadCandidates(html)
  if (candidates.length === 0) {
    throw new Error(
      'webview HTML missing window.pixiv or value bootstrap object (page shape may have changed)'
    )
  }

  let firstError = null
  let fallback = null

  for (const start of candidates) {
    let parsed
    try {
      const end = findObjectEnd(html, start)
      parsed = parseJsLiteral(html.slice(start, end))
    } catch (error) {
      if (!firstError) firstError = error
      continue
    }

    const unwrapped = unwrapPayloadObject(parsed)
    if (!unwrapped) continue
    if (unwrapped.novel !== undefined) return unwrapped
    if (!fallback) fallback = unwrapped
  }

  if (fallback) return fallback
  if (firstError) throw firstError
  throw new Error('window.pixiv payload is not an object literal')
}
