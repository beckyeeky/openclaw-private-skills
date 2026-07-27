# WSJ Article Reader behavior policy

This policy applies to retrieval through a user's own authorized WSJ/Dow Jones
account. Its purpose is to keep the tool a deliberate, low-volume reading aid,
not a crawler.

## Default operating mode

- Fetch only an article URL or origin ID explicitly supplied by the user.
- Fetch one article per invocation; no prefetch, recommendation expansion,
  pagination, search harvesting, or concurrent requests.
- Preserve publisher access decisions. A `401`, `403`, entitlement denial, or
  paywall response ends the run immediately.
- Do not call analytics, advertising, experimentation, push, or personalization
  services merely to imitate a mobile app.

## Rate limits

The fetcher enforces these conservative local limits:

| Limit | Default |
|---|---:|
| Concurrent article requests | 1 |
| Minimum time between successful/attempted requests | 15 minutes |
| Maximum requests per rolling hour | 6 |
| Maximum requests per rolling day | 20 |
| Automatic retries after 401/403/429/5xx | 0 |

A user may explicitly lower a waiting period for one interactive request, but
must not disable the hourly/day limits or use the tool for bulk retrieval.

## Timing

When a request is allowed, the script chooses one small randomized preflight
wait (default 2–6 seconds). It uses no fixed polling loop, no burst, and no
parallelism. This is pacing, not an attempt to evade publisher controls.

## Local state and privacy

Runtime files live outside the skill repository:

```text
~/.openclaw/wsj-article-reader/
  template.json       # non-secret GraphQL request shape
  state.json          # timestamps/status only
  articles/           # user-authorized exports
```

`state.json` stores only UTC timestamps, a short article identifier, and HTTP
status. It never stores Authorization values, cookies, full request URLs,
response bodies, titles, or article text.

## Stop conditions

Stop without retrying when any of these occur:

- `401`, `403`, access/entitlement denial, or a publisher paywall result;
- `429` rate limit;
- an unknown persisted-query or schema failure;
- network/server failure (record one failed attempt and report it);
- local rate limit reached.

On an authorization or template failure, ask the user to refresh their own WSJ
App session and generate a new local non-secret template. Never alter, decode,
or attempt to refresh the authorization token.
