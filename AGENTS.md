# Repository guide

This repository is an installable collection of Agent Skills. Keep public,
installable skills below `skills/` so the `skills` CLI can find them with its
default discovery rules.

## Layout contract

```text
skills/<skill-name>/SKILL.md
```

- Name the directory exactly after the skill's `name` frontmatter value.
- Keep `SKILL.md` at that directory's root. Its YAML frontmatter must contain
  a lowercase-hyphenated `name` and a clear `description` that says both what
  the skill does and when it should trigger.
- Keep executable helpers in `scripts/`, agent-readable details in
  `references/`, and reusable output files in `templates/` or `assets/`.
- Resolve files relative to `{baseDir}` in Agent instructions. Never assume a
  fixed checkout path such as `/root/.hermes/...`.
- Do not store credentials, generated user data, caches, or fetched source
  material in this repository. Put runtime state in the skill's documented
  user-level data directory.

## Changing a skill

1. Update its `SKILL.md` and only the resources required by the workflow.
2. Preserve the existing runtime contracts unless the change explicitly
   migrates them.
3. Update this repository README if the skill list, install process, or a
   shared requirement changes.
4. Run the narrowest relevant tests for changed scripts.
5. Verify that the CLI discovers the intended skills:

   ```bash
   npx skills@latest add . --list
   ```

Use `npx skills@latest add . --list` as a discovery check only; it must not be
used to alter a user's installed skills during repository development.
