# Baba Chat

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
