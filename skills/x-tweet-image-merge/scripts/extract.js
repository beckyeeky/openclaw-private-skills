/* Returns only numbered photos belonging to the requested post. */
function extractTweetPhotos(root, id) {
  const photos = new Map();
  const articles = Array.from(root.querySelectorAll('article'));
  let found = false, video = false;
  for (const article of articles) {
    const links = Array.from(article.querySelectorAll('a[href]'));
    const belongs = links.some(a => {
      const m = new URL(a.href, 'https://x.com').pathname.match(/\/status\/(\d+)(?:\/|$)/);
      return m && m[1] === id;
    });
    if (!belongs) continue;
    found = true;
    video ||= !!article.querySelector('[data-testid="videoPlayer"]');
    // New X markup omits tweetPhoto; numbered photo anchors remain scoped.
    for (const node of article.querySelectorAll('[data-testid="tweetPhoto"], a[href*="/photo/"]')) {
      const a = node.closest('a[href]') || node.querySelector('a[href]');
      if (!a) continue;
      const match = new URL(a.href, 'https://x.com').pathname.match(/\/status\/(\d+)\/photo\/(\d+)\/?$/);
      if (!match || match[1] !== id) continue;
      const img = node.querySelector('img');
      if (!img) continue;
      const url = new URL(img.currentSrc || img.src, 'https://x.com');
      if (url.hostname !== 'pbs.twimg.com' || !url.pathname.startsWith('/media/')) continue;
      // X's resized WebP variants may not have an orig endpoint; JPEG orig does.
      if (url.searchParams.get('format') === 'webp') url.searchParams.set('format', 'jpg');
      url.searchParams.set('name', 'orig');
      photos.set(Number(match[2]), {index: Number(match[2]), url: url.href});
    }
  }
  const seen = new Set();
  const ordered = [...photos.values()].sort((a,b) => a.index-b.index).filter(p => {
    const key = new URL(p.url).pathname;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  });
  return {tweet_id:id, found, video, photos:ordered,
    contiguous:ordered.every((p,i) => p.index === i+1),
    completeness:'DOM-visible only; trailing virtualized photos cannot be ruled out'};
}
if (typeof module !== 'undefined') module.exports = extractTweetPhotos;
