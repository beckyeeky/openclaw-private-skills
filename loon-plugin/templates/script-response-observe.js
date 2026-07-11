/**
 * Loon http-response observe-only skeleton
 * Does NOT modify body. Optional throttled notify on bad business codes.
 * Argument: notify = true|false
 */

const STORE_LAST_TS = "example_risk_last_notify";
const STORE_LAST_KEY = "example_risk_last_key";
const THROTTLE_MS = 30 * 60 * 1000;

function argFlag(name, defaultValue) {
  try {
    if (typeof $argument === "undefined" || $argument == null) return defaultValue;
    if (typeof $argument === "object" && $argument[name] != null) {
      const v = $argument[name];
      if (typeof v === "boolean") return v;
      const s = String(v).trim().toLowerCase();
      if (["true", "1", "on", "yes"].includes(s)) return true;
      if (["false", "0", "off", "no"].includes(s)) return false;
    }
    if (typeof $argument === "string" && $argument) {
      const re = new RegExp("(?:^|[?&])" + name + "=([^&]+)", "i");
      const m = $argument.match(re);
      if (m) {
        const s = decodeURIComponent(m[1]).trim().toLowerCase();
        if (["true", "1", "on"].includes(s)) return true;
        if (["false", "0", "off"].includes(s)) return false;
      }
    }
  } catch (e) {}
  return defaultValue;
}

function parseBody(body) {
  if (body == null) return null;
  if (typeof body === "object") return body;
  if (typeof body !== "string") return null;
  const t = body.trim();
  if (!t) return null;
  try {
    return JSON.parse(t);
  } catch (e) {
    return null;
  }
}

function shouldNotify(key) {
  const now = Date.now();
  const lastTs = parseInt($persistentStore.read(STORE_LAST_TS) || "0", 10) || 0;
  const lastKey = $persistentStore.read(STORE_LAST_KEY) || "";
  if (lastKey === key && now - lastTs < THROTTLE_MS) return false;
  $persistentStore.write(String(now), STORE_LAST_TS);
  $persistentStore.write(key, STORE_LAST_KEY);
  return true;
}

(function main() {
  const notifyOn = argFlag("notify", true);
  const raw =
    $response && ($response.body != null ? $response.body : null);
  const json = parseBody(typeof raw === "string" ? raw : null);

  if (!json) {
    console.log("[Example] response no-json (skip; gzip/non-json?)");
    $done({});
    return;
  }

  const code = json.code;
  const n =
    (json.data && Array.isArray(json.data.item) && json.data.item.length) ||
    (json.data && Array.isArray(json.data.items) && json.data.items.length) ||
    0;

  let kind = "other";
  if (code === 0 && n > 0) kind = "ok";
  else if (code === -352) kind = "risk352";
  else if (code === 0 && n === 0) kind = "empty";

  console.log(`[Example] response kind=${kind} code=${code} items=${n}`);

  if (notifyOn && kind !== "ok" && shouldNotify(`${kind}:${code}`)) {
    try {
      $notification.post(
        "Example 探针",
        `code=${code}`,
        kind === "risk352"
          ? "业务码 -352：本次请求可能被风控（不代表账号全局封禁）"
          : `kind=${kind} items=${n}`
      );
    } catch (e) {
      console.log("[Example] notify fail " + e);
    }
  }

  // observe only
  $done({});
})();
