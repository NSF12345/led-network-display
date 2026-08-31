# Workflows

## `docker-publish.yml` - build & publish the image

Triggers:
- Push to `main` (untagged) -> `:sha-<short>` only - no floating `:main` tag, deliberately (nothing should track an untested branch HEAD automatically)
- Push a `v*.*.*` tag -> `:X.Y.Z`, `:X.Y`, `:sha-<short>`
- Manual run on any other branch -> `:<branch-name>`, `:sha-<short>`

`:latest` is never touched here - it's only ever moved by `promote.yml`, run manually. Tagging a release publishes it under its version, nothing more; it doesn't go "live" as `:latest` until you deliberately promote it.

`APP_VERSION` (shown in the web preview's footer / `/api/info`) is baked into the image at build time: the git tag if one triggered the build, otherwise `sha-<short>`.

## `release.yml` - cut a release

Manual only, and only runs from `main` (fails immediately otherwise). Pick a bump type - `major`/`minor`/`bugfix` auto-increments off the latest existing tag, or `manual` to type an exact version. Tags `vX.Y.Z` and pushes it, which triggers `docker-publish.yml` to build and publish that release (as `:X.Y.Z`, not yet `:latest`).

## `promote.yml` - go live

Manual only. Give it a version (e.g. `0.1.0`) already published by `docker-publish.yml`; it re-tags that exact image as `:latest` directly via the registry (no rebuild). This is the deliberate "approve and ship" step - nothing reaches `:latest` without someone explicitly running this after checking the release out.

## Doing a release

1. Merge your changes into `main`
2. Actions tab -> **Create release tag** -> run workflow, pick a bump (or `manual` + a version) - this builds and publishes `:X.Y.Z`
3. Check it out, make sure it's good
4. Actions tab -> **Promote a release to latest** -> run workflow, enter the same version - only now does `:latest` move
