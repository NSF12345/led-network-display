# Workflows

## `docker-publish.yml` - build & publish the image

Triggers:
- Push to `main` (untagged) -> `:main`, `:sha-<short>`
- Push a `v*.*.*` tag -> `:X.Y.Z`, `:X.Y`, `:sha-<short>`, `:latest`
- Manual run on any branch -> `:<branch-name>`, `:sha-<short>`

`:latest` only ever moves on a tagged release (via `flavor: latest=auto`) - never on a plain branch/main push.

`APP_VERSION` (shown in the web preview's footer / `/api/info`) is baked into the image at build time: the git tag if one triggered the build, otherwise `sha-<short>`.

## `release.yml` - cut a release

Manual only, and only runs from `main` (fails immediately otherwise). Give it a version like `0.1.0`; it tags `v0.1.0` and pushes it, which then triggers `docker-publish.yml` to actually build and publish that release.

## Doing a release

1. Merge your changes into `main`
2. Actions tab -> **Create release tag** -> run workflow, enter version (e.g. `0.1.0`)
3. That pushes the tag, which kicks off **Build and publish Docker image** automatically
