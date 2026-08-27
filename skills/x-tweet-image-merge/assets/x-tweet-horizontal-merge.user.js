// ==UserScript==
// @name         X Tweet Images - Horizontal Merge & Download
// @namespace    https://x.com/
// @version      1.0.0
// @description  Merge every image in one X/Twitter post horizontally and download one PNG.
// @match        https://x.com/*
// @match        https://twitter.com/*
// @grant        GM_xmlhttpRequest
// @connect       pbs.twimg.com
// @run-at        document-idle
// ==/UserScript==

(() => {
  'use strict';

  const BUTTON_CLASS = 'x-horizontal-merge-download';
  const MAX_CANVAS_EDGE = 16_384;

  function isMediaUrl(value) {
    try {
      const url = new URL(value, location.href);
      return url.hostname === 'pbs.twimg.com' && url.pathname.startsWith('/media/');
    } catch (_) {
      return false;
    }
  }

  function originalUrl(value) {
    const url = new URL(value, location.href);
    url.searchParams.set('name', 'orig');
    return url.href;
  }

  function tweetImages(article) {
    const result = [];
    const seen = new Set();

    for (const image of article.querySelectorAll('[data-testid="tweetPhoto"] img')) {
      const photo = image.closest('[data-testid="tweetPhoto"]');
      // Do not accidentally merge an image from a quoted tweet.
      if (!photo || photo.closest('article') !== article) continue;

      const source = image.currentSrc || image.src;
      if (!isMediaUrl(source)) continue;

      const link = image.closest('a[href*="/status/"]');
      const match = link?.href.match(/\/status\/\d+\/photo\/(\d+)/);
      const url = originalUrl(source);
      const key = new URL(url).pathname;
      if (seen.has(key)) continue;
      seen.add(key);
      result.push({ url, order: Number(match?.[1]) || result.length + 1 });
    }

    return result.sort((a, b) => a.order - b.order);
  }

  function getTweetId(article) {
    const href = article.querySelector('a[href*="/status/"]')?.href || '';
    return href.match(/\/status\/(\d+)/)?.[1] || 'tweet';
  }

  function requestBlob(url) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: 'GET',
        url,
        responseType: 'blob',
        onload: ({ status, response }) => {
          if (status >= 200 && status < 300 && response instanceof Blob) resolve(response);
          else reject(new Error(`图片下载失败（HTTP ${status}）`));
        },
        onerror: () => reject(new Error('图片下载失败：网络请求被阻止。')),
        ontimeout: () => reject(new Error('图片下载超时。')),
      });
    });
  }

  function decodeImage(blob) {
    return new Promise((resolve, reject) => {
      const objectUrl = URL.createObjectURL(blob);
      const image = new Image();
      image.onload = () => resolve({ image, objectUrl });
      image.onerror = () => {
        URL.revokeObjectURL(objectUrl);
        reject(new Error('浏览器无法解码其中一张图片。'));
      };
      image.src = objectUrl;
    });
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.style.display = 'none';
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  function canvasBlob(canvas) {
    return new Promise((resolve, reject) => {
      canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('PNG 编码失败。')), 'image/png');
    });
  }

  async function mergeAndDownload(article, button) {
    const media = tweetImages(article);
    if (media.length < 2) {
      throw new Error('这条帖子暂未找到两张以上的图片。请先等待图片轮播加载完成。');
    }

    button.disabled = true;
    button.textContent = '正在合并…';
    try {
      const blobs = await Promise.all(media.map(({ url }) => requestBlob(url)));
      const decoded = await Promise.all(blobs.map(decodeImage));
      const totalWidth = decoded.reduce((sum, { image }) => sum + image.naturalWidth, 0);
      const maxHeight = Math.max(...decoded.map(({ image }) => image.naturalHeight));
      const scale = Math.min(1, MAX_CANVAS_EDGE / totalWidth, MAX_CANVAS_EDGE / maxHeight);
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.floor(totalWidth * scale));
      canvas.height = Math.max(1, Math.floor(maxHeight * scale));
      const context = canvas.getContext('2d');
      if (!context) throw new Error('无法创建图片画布。');

      let x = 0;
      for (const { image } of decoded) {
        const width = Math.floor(image.naturalWidth * scale);
        const height = Math.floor(image.naturalHeight * scale);
        context.drawImage(image, x, 0, width, height);
        x += width;
      }

      const output = await canvasBlob(canvas);
      downloadBlob(output, `x-${getTweetId(article)}-horizontal-merge.png`);
      if (scale < 1) {
        button.title = `原图总宽超出画布限制，已按 ${(scale * 100).toFixed(1)}% 缩小后下载。`;
      }
      decoded.forEach(({ objectUrl }) => URL.revokeObjectURL(objectUrl));
    } finally {
      button.disabled = false;
      button.textContent = '横向合并下载';
    }
  }

  function addButton(article) {
    if (article.querySelector(`.${BUTTON_CLASS}`) || tweetImages(article).length < 2) return;
    const host = article.querySelector('[data-testid="tweetPhoto"]');
    if (!host || host.closest('article') !== article) return;

    // Do not replace native left-click or ScrollSnap gestures.
    host.style.setProperty('position', 'relative');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = BUTTON_CLASS;
    button.textContent = '横向合并下载';
    button.title = '把本帖全部图片按原始比例横向拼接并下载 PNG';
    button.addEventListener('click', async (event) => {
      event.preventDefault();
      event.stopPropagation();
      try {
        await mergeAndDownload(article, button);
      } catch (error) {
        alert(error instanceof Error ? error.message : '图片合并失败。');
      }
    });
    host.append(button);
  }

  function scan() {
    document.querySelectorAll('article[data-testid="tweet"], article').forEach(addButton);
  }

  function installStyles() {
    const style = document.createElement('style');
    style.textContent = `
      .${BUTTON_CLASS} {
        position: absolute !important;
        right: 8px !important;
        bottom: 8px !important;
        z-index: 20 !important;
        border: 0 !important;
        border-radius: 999px !important;
        padding: 7px 10px !important;
        background: rgba(15, 20, 25, .88) !important;
        color: #fff !important;
        font: 600 13px/1 system-ui, sans-serif !important;
        cursor: pointer !important;
        box-shadow: 0 1px 5px rgba(0, 0, 0, .45) !important;
      }
      .${BUTTON_CLASS}:hover { background: #1d9bf0 !important; }
      .${BUTTON_CLASS}:disabled { opacity: .75 !important; cursor: wait !important; }
    `;
    (document.head || document.documentElement).append(style);
  }

  installStyles();
  scan();
  let pending;
  new MutationObserver(() => {
    clearTimeout(pending);
    pending = setTimeout(scan, 100);
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
