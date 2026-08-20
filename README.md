# Baba Chat

## One-command release

From the repository root, after the latest changes are ready, replace `1.0.1` with the next version and run:

```bash
release_version=1.0.1 && test -z "$(git status --porcelain)" && npm --prefix baba-chat-app version "$release_version" --no-git-tag-version && git add baba-chat-app/package.json baba-chat-app/package-lock.json && git commit -m "release: v$release_version" && git push origin master && git tag -a "v$release_version" -m "Baba Chat v$release_version" HEAD && git push origin "v$release_version"
```

This updates the app version, pushes `master`, creates the annotated version tag, and starts the cross-platform GitHub Release workflow.

Baba Chat is a desktop research assistant for the local Baba discourse and story corpus. The Electron application source is in [`baba-chat-app`](baba-chat-app), while the original source books remain at the repository root.

## Releases

Installers are published on the [GitHub Releases page](https://github.com/arjuna-dev/baba-chat/releases). Release builds are produced by GitHub Actions for:

- macOS Apple Silicon
- macOS Intel
- Windows x64
- Linux x64

Release binaries are intentionally not committed to the source tree. The generated search index and glossary are tracked with Git LFS because they are runtime data rather than source code and exceed GitHub's ordinary file-size limit.

## Development

```bash
cd baba-chat-app
npm ci
npm run dev:electron
```

To build a local Electron package, pass the platform and architecture supported by the current machine:

```bash
npm run build:electron -- --bundler builder --target darwin --arch arm64
```

Pushing a `v*` tag starts the cross-platform release workflow in [`.github/workflows/release.yml`](.github/workflows/release.yml).
