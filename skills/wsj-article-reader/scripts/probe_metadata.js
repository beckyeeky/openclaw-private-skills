/* Strict, path-scoped browser metadata probe for the WSJ article reader.
 *
 * Verified live shape (2026-10) of the article page's embedded payload:
 *
 *   <script id="__NEXT_DATA__" type="application/json">
 *     .props.pageProps.articleData
 *        .originId                          -> "WP-WSJ-0003975946"
 *        .articleTrackingMeta.articleId     -> same value as originId
 *        .sourceUrl / .canonicalUrl         -> canonical path of that article
 *
 * Only that dedicated object is read. There is no recursion through the page
 * tree, no whole-page regex, and no scan of other script tags: ids that belong
 * to related/recommended stories are never candidates. If the dedicated object
 * is missing the probe reports ok:false and the caller must refuse to attribute
 * an id - guessing is never allowed.
 *
 * This body is executed unchanged in two places:
 *   - in the browser, through `minis-browser-use execute_js` (async wrapper,
 *     top-level `return` supported);
 *   - offline in node, wrapped by the test harness with
 *     `new Function("document", "location", body)`.
 * Keep it a plain script body: no imports, no exports, no top-level await.
 */
const requestedUrl = (location && location.href) || "";
const pagePath = (location && location.pathname) || "";

function probeFailure(code, detail) {
  return {
    ok: false,
    code: code,
    detail: detail,
    requestedUrl: requestedUrl,
    pagePath: pagePath,
  };
}

let nextDataEl = null;
try {
  nextDataEl = document.getElementById ? document.getElementById("__NEXT_DATA__") : null;
} catch (e) {
  nextDataEl = null;
}
if (!nextDataEl && document.querySelector) {
  try {
    nextDataEl = document.querySelector('script#__NEXT_DATA__');
  } catch (e) {
    nextDataEl = null;
  }
}
if (!nextDataEl) {
  return probeFailure("missing_next_data", "no #__NEXT_DATA__ element on the page");
}

let nextData = null;
try {
  nextData = JSON.parse(nextDataEl.textContent || "");
} catch (e) {
  return probeFailure("unparsable_next_data", "the #__NEXT_DATA__ payload was not valid JSON");
}
if (!nextData || typeof nextData !== "object" || Array.isArray(nextData)) {
  return probeFailure("unparsable_next_data", "the #__NEXT_DATA__ payload was not a JSON object");
}

const props = nextData.props;
const pageProps = props && typeof props === "object" ? props.pageProps : null;
const articleData =
  pageProps && typeof pageProps === "object" && !Array.isArray(pageProps)
    ? pageProps.articleData
    : null;
if (!articleData || typeof articleData !== "object" || Array.isArray(articleData)) {
  return probeFailure(
    "missing_article_data",
    "props.pageProps.articleData is absent; no id may be taken from anywhere else"
  );
}

const tracking = articleData.articleTrackingMeta;
const text = function (value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
};

return {
  ok: true,
  code: "ok",
  requestedUrl: requestedUrl,
  pagePath: pagePath,
  hasArticleData: true,
  originId: text(articleData.originId),
  trackingArticleId: tracking && typeof tracking === "object" ? text(tracking.articleId) : null,
  sourceUrl: text(articleData.sourceUrl),
  canonicalUrl: text(articleData.canonicalUrl),
};
