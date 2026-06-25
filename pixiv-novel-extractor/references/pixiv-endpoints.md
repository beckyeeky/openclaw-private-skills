# Pixiv Endpoints Used by This Skill

This skill relies on three external Pixiv endpoints.

## 1. Public novel AJAX

- Endpoint: `https://www.pixiv.net/ajax/novel/{id}`
- Purpose: Fetch public novel metadata,正文, tags, series navigation, and embedded image data.
- Authentication: None for public novels.
- Notes: v1 only supports public novels that this endpoint returns successfully.

## 2. Pixiv OAuth token exchange

- Endpoint: `https://oauth.secure.pixiv.net/auth/token`
- Purpose: Validate a Pixiv App `refresh_token` and exchange it for a short-lived `access_token`.
- Authentication: Requires `refresh_token` plus Pixiv App client metadata.
- Notes: The skill verifies the token before saving it and never stores the returned `access_token`.

## 3. Pixiv App recommendations

- Endpoint: `https://app-api.pixiv.net/v1/novel/recommended`
- Purpose: Fetch recommended novels for a verified Pixiv App account.
- Authentication: Requires a valid `access_token` obtained from the OAuth exchange.
- Notes: `recommended` resolves the token from stdin, env, or local config in that order.
