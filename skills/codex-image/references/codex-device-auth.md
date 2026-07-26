# Codex Device Auth

When ALL retries return 401 and `codex login status` says "Logged in" but the token won't refresh.

## Detection

- Every attempt prints `http_401`
- `last_refresh` in `~/.codex/auth.json` is days/weeks old
- `codex login status` says "Logged in" — this only checks the file exists, not that the token is valid

## Fix

```bash
# Check if already running
ps aux | grep "codex login" | grep -v grep

# Start device auth (use pty=true)
codex login --device-auth
# → Opens a URL + one-time code

# After user completes in browser, verify:
python3 -c "
import json, time, base64, pathlib
data = json.loads(pathlib.Path.home().joinpath('.codex','auth.json').read_text())
print('last_refresh:', data.get('last_refresh'))
"
```

If `last_refresh` shows current time → auth succeeded. Retry generate.py.
