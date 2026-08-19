# Embedded Codex terminal

This feature is an optional terminal surface for Baba Chat. It preserves the existing app-server chat UI and starts the real `codex` CLI only after the user presses **Start terminal**.

## Runtime design

The Electron main process owns an `EmbeddedTerminalManager`. It launches one Codex CLI process per session through `node-pty`, using the selected working directory as the PTY cwd. The preload script exposes only the following renderer API:

- `create({ cwd, cols, rows })`
- `input(terminalId, data)`
- `resize(terminalId, cols, rows)`
- `kill(terminalId)`
- `status(terminalId?)`
- `onOutput(handler)`
- `onStatus(handler)`

Terminal IDs are opaque and validated in the main process. Working directories must be existing absolute directories. PTY dimensions are bounded, input is limited to 128 KiB per write, and at most four sessions may run at once. IPC requests are accepted only from the active application window.

`CodexTerminal.vue` owns the xterm.js instance, fit and resize handling, keyboard input forwarding, accessible labels, status announcements, and cleanup. It does not start a process on mount. Unmounting the component kills its session, and Electron kills all remaining sessions when the window or app tears down.

## Host integration

`IndexPage.vue` renders the component in an optional central workspace. The Terminal mode control mounts that workspace in place of the message list and composer, then restores the normal chat interface when switched off. This gives the PTY enough usable height in a desktop window without discarding the reader-friendly chat. Keep the component's `cwd` prop connected to the selected directory. A missing cwd disables Start and does not launch a fallback shell.

Unmounting the panel stops its PTY. Reopening it returns to the inactive state, so Codex never continues invisibly after the reader closes Terminal mode.

## Codex executable lookup

The main process checks `CODEX_APP_BIN`, `CODEX_BIN`, the inherited `PATH`, and common Volta, npm-global, Homebrew, `/usr/local/bin`, Codex app, and nvm locations. Set `CODEX_APP_BIN` to an absolute executable path when the packaged app cannot see the user shell PATH.

The default working directory is selected by looking for the bundled search executable:

```text
tools/baba-search/baba-search
```

Development candidates are checked first during development. In a packaged build, `process.resourcesPath` candidates are checked first, with `~/Documents` as the final fallback. This lets the chat and terminal locate the packaged retrieval resources without shipping development instructions.

## Native module and packaging notes

`node-pty` contains native code and must be rebuilt for the Electron version used by this project. Run:

```bash
npm install
npm run rebuild:native
npm run build:electron
```

The `rebuild:native` script uses `@electron/rebuild` and targets `node-pty`. Re-run it after changing the Electron version, switching architectures, or installing dependencies on another machine. The packager must include `node-pty` and its compiled `.node` binary in the application resources. The dynamic main-process loader keeps the native dependency out of the renderer bundle.

The packaged resource layout is expected to include the project retrieval resources at the resource root:

```text
resources/
  tools/baba-search/baba-search
  corpus/
  SKILLS/
```

`resolveEmbeddedSkillsDirectory()` checks `process.resourcesPath/SKILLS` in addition to development locations. The host packager should copy `tools/`, `corpus/`, and `src-electron/SKILLS` as packaged resources.

If `node-pty` cannot load, the app remains usable. `status()` reports `available: false`, the component shows the reason, and no child process is started. If `node-pty` loads but the Codex executable is missing, the same unavailable state is shown. This is a terminal-only fallback: the existing app-server chat continues to use its own process path.

## Manual smoke test

1. Start the Electron app.
2. Select a directory containing `tools/baba-search/baba-search`, or pass that directory as the component `cwd`.
3. Enable Terminal mode and confirm it initially says `Ready to start` without a child process.
4. Press **Start terminal** and confirm the interactive Codex prompt appears.
5. Type into the xterm surface, resize the window, and confirm the PTY receives both input and resize events.
6. Press **Stop** or close the app and confirm the Codex CLI exits.
