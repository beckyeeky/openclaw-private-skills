# Codex CLI Device Auth Walkthrough

Use this when ALL 11 strategies return 401 ("http_401") and `codex login status`
says "Logged in" but the refresh chain is stale.

## Detection

- Every single retry strategy starts with `Token expired. Refreshing via Codex CLI...`
- Every strategy ends with `→ no image (status=http_401)`
- `last_refresh` in `~/.codex/auth.json` is days old (e.g. 10+ days)
- `codex login status` reports "Logged in using ChatGPT" — THIS IS A LIE
  It only confirms a stored refresh token file exists, NOT that the token is valid.

## Quick Check: Passive Recovery

Before starting a new device auth flow, **check if one is already in progress**:

```bash
ps aux | grep "codex login" | grep -v grep
```

If a `codex login --device-auth` process is already running (from a prior session), **don't** start another one. Wait 30-60 seconds, then recheck the token:

```bash
python3 -c "
import json, time, base64, pathlib
auth_path = pathlib.Path.home() / '.codex' / 'auth.json'
data = json.loads(auth_path.read_text())
token = data['tokens']['access_token']
parts = token.split('.')
seg = parts[1]
padding = 4 - len(seg) % 4
if padding != 4: seg += '=' * padding
payload = json.loads(base64.urlsafe_b64decode(seg))
exp = payload.get('exp', 0)
print(f'Token valid: {time.time() < exp}, expires: {time.strftime(\"%Y-%m-%d %H:%M:%S\", time.gmtime(exp))}')
print(f'last_refresh: {data.get(\"last_refresh\", \"N/A\")}')
"
```

If the token is now valid and `last_refresh` updated, the stale process completed authentication — retry generate.py directly.

## Procedure (fresh auth)

1. **Run device auth with pty=true**:
   ```bash
   terminal(command="codex login --device-auth", pty=true, background=true, timeout=600, notify_on_complete=true)
   ```

2. **Capture the device code** from the process output (poll the process after 2s):
   - URL: `https://auth.openai.com/codex/device`
   - One-time code: `XXXX-XXXXX` (expires in 15 minutes)

3. **Send both to user** and ask them to complete in browser.

4. **DO NOT kill the process** — the user needs it alive to receive the auth callback.

5. **After user confirms completion**, verify auth succeeded:
   ```bash
   cat ~/.codex/auth.json | python3 -c "import json,sys; d=json.load(sys.stdin); print('last_refresh:', d.get('last_refresh'))"
   ```
   If `last_refresh` shows current time (within minutes), auth succeeded.
   If still showing old date, auth didn't take — retry from step 1.

6. **Kill the auth process** (it hangs after auth callback anyway).

7. **Retry generate.py** — the fresh token should now work.

## Context

The script at `_load_token()` in generate.py:
1. Reads access_token from `~/.codex/auth.json`
2. If expired or within 5 min of expiry, calls `codex login status` to trigger JWT refresh
3. Re-reads the file

But `codex login status` refreshes the access_token JWT from the stored refresh_token.
If the refresh_token itself is stale (typically 10-30 day expiry, depends on OpenAI policy),
the refresh chain fails silently — status says "Logged in" but the access token can't
be renewed. The script gets 401 on every API call.

Device auth (`codex login --device-auth`) obtains a fresh refresh_token + access_token
pair from the OAuth endpoint, fixing the broken chain.
