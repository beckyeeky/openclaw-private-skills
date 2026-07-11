/**
 * Loon http-request skeleton
 * Argument: mode = scrub | origin
 * Store keys: prefix with your plugin name to avoid clashes.
 */

const STORE_MODE = "example_mode";
const VALID = new Set(["scrub", "origin"]);

function readMode() {
  try {
    if (typeof $argument !== "undefined" && $argument != null) {
      if (typeof $argument === "object" && $argument.mode != null) {
        const m = String($argument.mode).trim().toLowerCase();
        if (VALID.has(m)) return m;
      }
      if (typeof $argument === "string" && $argument) {
        const m = $argument.match(/(?:^|[?&])mode=([^&]+)/i);
        if (m) {
          const v = decodeURIComponent(m[1]).trim().toLowerCase();
          if (VALID.has(v)) return v;
        }
      }
    }
  } catch (e) {}
  const stored = ($persistentStore.read(STORE_MODE) || "").trim().toLowerCase();
  if (VALID.has(stored)) return stored;
  return "scrub";
}

function scrubCookie(headers) {
  const out = {};
  for (const k of Object.keys(headers || {})) {
    out[k] = headers[k];
  }
  // Case-insensitive Cookie clear (example: pure scrub)
  for (const k of Object.keys(out)) {
    if (k.toLowerCase() === "cookie") {
      delete out[k];
    }
  }
  return out;
}

(function main() {
  const mode = readMode();
  $persistentStore.write(mode, STORE_MODE);

  if (mode === "origin") {
    console.log("[Example] request origin passthrough");
    $done({});
    return;
  }

  const headers = scrubCookie(($request && $request.headers) || {});
  console.log("[Example] request scrub cookie");
  $done({ headers });
})();
