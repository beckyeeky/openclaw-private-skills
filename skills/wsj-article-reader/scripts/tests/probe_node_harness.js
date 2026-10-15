#!/usr/bin/env node
/* Offline test harness: runs the real browser probe (scripts/probe_metadata.js)
 * against a static page fixture, so the attribute/attribution logic is verified
 * without a browser and without any network access.
 *
 * The DOM is a deliberately minimal test double that keeps the real browser
 * interface used by the probe:
 *   document.getElementById(id)        -> element with .textContent (script tag)
 *   document.querySelector("script#…")  -> same
 *   document.querySelector('link[rel="canonical"]') -> {href}
 *   document.querySelectorAll("script") -> every <script> element (for the
 *                                        pre-patch probe shape, kept so the
 *                                        defect is reproducible offline)
 *   document.title, location.href, location.pathname
 *
 * What it does NOT cover: real rendering, Next.js hydration, CSP behaviour, and
 * anything the live page does after hydration. It only proves what the probe
 * script does with the payload it is given.
 *
 * usage: node probe_node_harness.js <probe.js> <fixture.html> <requestedPath>
 * prints the probe result as JSON on stdout (never throws for probe errors).
 */
const fs = require("fs");

const probePath = process.argv[2];
const fixturePath = process.argv[3];
const requestedPath = process.argv[4] || "/";

function parseScripts(html) {
  const scripts = [];
  const re = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(html)) !== null) {
    const attrs = m[1] || "";
    const id = /\bid\s*=\s*"([^"]*)"/i.exec(attrs);
    const type = /\btype\s*=\s*"([^"]*)"/i.exec(attrs);
    scripts.push({
      id: id ? id[1] : "",
      type: type ? type[1] : "",
      textContent: m[2],
    });
  }
  return scripts;
}

function parseLinks(html) {
  const links = [];
  const re = /<link\b([^>]*)\/?>/gi;
  let m;
  while ((m = re.exec(html)) !== null) {
    const attrs = m[1] || "";
    const rel = /\brel\s*=\s*"([^"]*)"/i.exec(attrs);
    const href = /\bhref\s*=\s*"([^"]*)"/i.exec(attrs);
    if (href) links.push({ rel: rel ? rel[1] : "", href: href[1] });
  }
  return links;
}

function makeDocument(html) {
  const scripts = parseScripts(html);
  const links = parseLinks(html);
  return {
    title: (html.match(/<title>([\s\S]*?)<\/title>/i) || [])[1] || "fixture",
    getElementById: function (id) {
      for (const s of scripts) if (s.id === id) return s;
      return null;
    },
    querySelectorAll: function (selector) {
      return String(selector).indexOf("script") === 0 ? scripts.slice() : [];
    },
    querySelector: function (selector) {
      const sel = String(selector);
      if (sel.indexOf("script#") === 0) {
        return this.getElementById(sel.slice("script#".length));
      }
      const idAttr = /script\[id\s*=\s*"([^"]*)"\]/.exec(sel);
      if (idAttr) return this.getElementById(idAttr[1]);
      if (sel.indexOf("link") === 0) {
        const rel = /rel\s*=\s*"([^"]*)"/.exec(sel);
        for (const link of links) {
          if (!rel || link.rel === rel[1]) return { href: link.href };
        }
        return null;
      }
      return null;
    },
  };
}

const documentStub = makeDocument(fs.readFileSync(fixturePath, "utf8"));
const locationStub = {
  href: "https://www.wsj.com" + requestedPath,
  pathname: requestedPath,
  hostname: "www.wsj.com",
};

let result;
try {
  const body = fs.readFileSync(probePath, "utf8");
  const fn = new Function("document", "location", body);
  result = fn(documentStub, locationStub);
} catch (err) {
  result = {
    ok: false,
    code: "probe_threw",
    detail: String((err && err.message) || err),
    requestedUrl: locationStub.href,
    pagePath: requestedPath,
  };
}
process.stdout.write(JSON.stringify(result === undefined ? null : result));
