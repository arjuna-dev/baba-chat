import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  shell,
  screen,
  safeStorage,
  type OpenDialogOptions,
  type Rectangle,
} from 'electron';
import path from 'path';
import os from 'os';
import { fileURLToPath } from 'url';
import { execFile } from 'node:child_process';
import { access, readFile, readdir, unlink, writeFile } from 'fs/promises';
import { accessSync, constants, statSync } from 'fs';
import { promisify } from 'node:util';
import {
  CodexAppServer,
  type ServerRequestResponse,
  type StartThreadInput,
  type StartTurnInput,
} from './codex-app-server';
import { EmbeddedTerminalManager } from './embedded-terminal';
import { HybridApiClient, type HybridApiRequestInput, type HybridProvider } from './hybrid-api';

// needed in case process is undefined under Linux
const platform = process.platform || os.platform();

const currentDir = fileURLToPath(new URL('.', import.meta.url));
const execFileAsync = promisify(execFile);

let mainWindow: BrowserWindow | undefined;
type NormalWindowState = {
  bounds: Rectangle;
  minimumSize: [number, number];
  resizable: boolean;
  movable: boolean;
  minimizable: boolean;
  maximizable: boolean;
  hasShadow: boolean;
  alwaysOnTop: boolean;
  maximized: boolean;
  fullScreen: boolean;
};

let normalWindowState: NormalWindowState | undefined;
let widgetModeActive = false;
let widgetCollapsedState = false;
let widgetClickThroughEnabled = false;
let displayListenersRegistered = false;
const hybridApi = new HybridApiClient({
  resolveSearchExecutable: resolveBabaSearchExecutable,
  getApiKey: readHybridApiKey,
  getResearchSkill: async () => {
    const skillsDir = await resolveEmbeddedSkillsDirectory();
    return readFile(path.join(skillsDir, 'baba-chat', 'SKILL.md'), 'utf8');
  },
  getDefaultProvider: (): HybridProvider =>
    process.env.BABA_LLM_PROVIDER === 'openai-compatible' ? 'openai-compatible' : 'deepseek',
  getDefaultModel: () => process.env.BABA_LLM_MODEL || '',
  getBaseUrl: () => process.env.BABA_LLM_BASE_URL || '',
});
const codex = new CodexAppServer();
const embeddedTerminal = new EmbeddedTerminalManager();
const widgetExpandedSize = {
  width: 760,
  height: 700,
};
const widgetCollapsedSize = {
  // The renderer's collapsed launcher is 92px square and its restore control
  // sits above it. Keep a transparent safety margin around both controls.
  width: 148,
  height: 148,
};
const widgetOrbCenterFromRight = 67;
const widgetOrbCenterFromBottom = 63;

interface DirectoryEntry {
  name: string;
  path: string;
  type: 'directory' | 'file';
}

interface DirectoryListing {
  path: string;
  name: string;
  entries: DirectoryEntry[];
  total: number;
}

interface SkillEntry {
  name: string;
  directory: string;
  skillFile: string;
  summary: string;
  content: string;
}

interface SkillCatalog {
  embeddedSkillsDir: string;
  codexSkillsDir: string;
  embeddedSkills: SkillEntry[];
  codexSkills: SkillEntry[];
}

codex.on('event', (event) => {
  if (mainWindow && !mainWindow.webContents.isDestroyed()) {
    mainWindow.webContents.send('codex:event', event);
  }
});

embeddedTerminal.onOutput((output) => {
  if (mainWindow && !mainWindow.webContents.isDestroyed()) {
    mainWindow.webContents.send('embedded-terminal:output', output);
  }
});

embeddedTerminal.onStatus((status) => {
  if (mainWindow && !mainWindow.webContents.isDestroyed()) {
    mainWindow.webContents.send('embedded-terminal:status', status);
  }
});

/**
 * Wraps an IPC handler so any thrown error is converted to a plain Error
 * before Electron tries to structured-clone it back to the renderer.
 * Complex SDK error objects (circular refs, custom prototypes) cause
 * "An object could not be cloned" if sent as-is.
 */
function safeIpc(
  channel: string,
  handler: (event: Electron.IpcMainInvokeEvent, ...args: unknown[]) => unknown,
) {
  ipcMain.handle(channel, async (event, ...args) => {
    try {
      return await handler(event, ...args);
    } catch (error: unknown) {
      const message =
        error instanceof Error
          ? error.message
          : typeof error === 'string'
            ? error
            : JSON.stringify(error);
      throw new Error(message);
    }
  });
}

function assertMainWindowSender(event: Electron.IpcMainInvokeEvent): void {
  if (!mainWindow || event.sender !== mainWindow.webContents) {
    throw new Error('This IPC request is not associated with the active application window.');
  }
}

safeIpc('codex:account-read', (_event, ...args) => {
  return codex.accountRead(Boolean(args[0]));
});

safeIpc('codex:account-rate-limits-read', () => {
  return codex.accountRateLimitsRead();
});

safeIpc('codex:login-chatgpt', async () => {
  const result = await codex.loginWithChatGpt();
  const authUrl = getAuthUrl(result);

  if (authUrl) {
    await shell.openExternal(authUrl);
  }

  return result;
});

safeIpc('codex:login-api-key', (_event, ...args) => {
  return codex.loginWithApiKey(args[0] as string);
});

safeIpc('codex:logout', () => {
  return codex.logout();
});

safeIpc('codex:model-list', () => {
  return codex.listModels();
});

safeIpc('codex:thread-list', (_event, ...args) => {
  return codex.listThreads(args[0] as string | undefined);
});

safeIpc('codex:thread-start', (_event, ...args) => {
  return codex.startThread(args[0] as StartThreadInput);
});

safeIpc('codex:turn-start', (_event, ...args) => {
  return codex.startTurn(args[0] as StartTurnInput);
});

safeIpc('codex:turn-interrupt', (_event, ...args) => {
  return codex.interruptTurn(args[0] as string, args[1] as string);
});

safeIpc('codex:server-request-respond', (_event, ...args) => {
  codex.respondToServerRequest(args[0] as ServerRequestResponse);
});

safeIpc('hybrid:status', (event) => {
  assertMainWindowSender(event);
  return hybridApi.status();
});

safeIpc('hybrid:api-key-save', async (event, ...args) => {
  assertMainWindowSender(event);
  await saveHybridApiKey(args[0]);
  return hybridApi.status();
});

safeIpc('hybrid:api-key-clear', async (event) => {
  assertMainWindowSender(event);
  await clearHybridApiKey();
  return hybridApi.status();
});

safeIpc('hybrid:complete', (event, ...args) => {
  assertMainWindowSender(event);
  return hybridApi.complete(args[0] as HybridApiRequestInput);
});

safeIpc('hybrid:cancel', (event, ...args) => {
  assertMainWindowSender(event);
  return hybridApi.cancel(args[0]);
});

safeIpc('app:get-current-directory', () => {
  return readDirectoryListing(getDefaultDirectory());
});

safeIpc('app:choose-directory', async () => {
  const options: OpenDialogOptions = {
    properties: ['openDirectory', 'createDirectory'],
  };
  const result = mainWindow
    ? await dialog.showOpenDialog(mainWindow, options)
    : await dialog.showOpenDialog(options);

  if (result.canceled || !result.filePaths[0]) {
    return null;
  }

  return readDirectoryListing(result.filePaths[0]);
});

safeIpc('app:read-directory', (_event, ...args) => {
  return readDirectoryListing(args[0] as string);
});

safeIpc('app:read-source', async (event, ...args) => {
  assertMainWindowSender(event);
  return readSourceCitation(args[0]);
});

safeIpc('app:open-source', async (event, ...args) => {
  assertMainWindowSender(event);
  const payload = await readSourceCitation(args[0]);
  const sourcePath = typeof payload.source_path === 'string' ? payload.source_path : '';
  if (!sourcePath || !path.isAbsolute(sourcePath)) {
    throw new Error('The original source file path is unavailable.');
  }

  const openError = await shell.openPath(sourcePath);
  if (openError) {
    throw new Error(openError);
  }

  return { ok: true };
});

safeIpc('app:list-skills', () => {
  return listSkills();
});

safeIpc('app:save-embedded-skill', (_event, ...args) => {
  return saveEmbeddedSkill(args[0] as string, args[1] as string);
});

safeIpc('embedded-terminal:create', (event, ...args) => {
  assertMainWindowSender(event);
  return embeddedTerminal.create(args[0]);
});

safeIpc('embedded-terminal:input', (event, ...args) => {
  assertMainWindowSender(event);
  return embeddedTerminal.input(args[0], args[1]);
});

safeIpc('embedded-terminal:resize', (event, ...args) => {
  assertMainWindowSender(event);
  return embeddedTerminal.resize(args[0], args[1], args[2]);
});

safeIpc('embedded-terminal:kill', (event, ...args) => {
  assertMainWindowSender(event);
  return embeddedTerminal.kill(args[0]);
});

safeIpc('embedded-terminal:status', (event, ...args) => {
  assertMainWindowSender(event);
  return embeddedTerminal.status(args[0]);
});

safeIpc('app:store-read', async (_event, key: unknown) => {
  if (typeof key !== 'string' || !/^[\w-]+$/.test(key)) {
    return null;
  }
  const storePath = path.join(app.getPath('userData'), `${key}.json`);
  try {
    const content = await readFile(storePath, 'utf8');
    return JSON.parse(content) as unknown;
  } catch {
    return null;
  }
});

safeIpc('app:store-write', async (_event, key: unknown, data: unknown) => {
  if (typeof key !== 'string' || !/^[\w-]+$/.test(key)) {
    throw new Error('Invalid store key.');
  }
  const storePath = path.join(app.getPath('userData'), `${key}.json`);
  await writeFile(storePath, JSON.stringify(data), 'utf8');
  return { ok: true };
});

ipcMain.handle('app:set-widget-mode', (_event, enabled: boolean) => {
  setWidgetMode(Boolean(enabled));
});

ipcMain.handle('app:set-widget-collapsed', (_event, collapsed: boolean) => {
  setWidgetCollapsed(Boolean(collapsed));
});

ipcMain.handle('app:window-action', (_event, action: string) => {
  handleWindowAction(action);
});

ipcMain.handle('app:set-widget-click-through', (_event, enabled: boolean) => {
  setWidgetClickThrough(Boolean(enabled));
});

ipcMain.on('app:move-window-by', (_event, deltaX: number, deltaY: number) => {
  moveWindowBy(deltaX, deltaY);
});

async function readDirectoryListing(directoryPath: string): Promise<DirectoryListing> {
  const entries = await readdir(directoryPath, { withFileTypes: true });
  const sortedEntries = entries
    .filter((entry) => !entry.name.startsWith('.'))
    .sort((left, right) => {
      if (left.isDirectory() !== right.isDirectory()) {
        return left.isDirectory() ? -1 : 1;
      }

      return left.name.localeCompare(right.name);
    })
    .map((entry) => ({
      name: entry.name,
      path: path.join(directoryPath, entry.name),
      type: entry.isDirectory() ? ('directory' as const) : ('file' as const),
    }));

  return {
    path: directoryPath,
    name: path.basename(directoryPath) || directoryPath,
    entries: sortedEntries,
    total: sortedEntries.length,
  };
}

function getDefaultDirectory(): string {
  const packagedCandidates = [
    process.resourcesPath,
    path.join(process.resourcesPath, 'app'),
    path.join(process.resourcesPath, 'baba-chat'),
  ];
  const developmentCandidates = [
    process.cwd(),
    path.resolve(currentDir, '..'),
    path.resolve(currentDir, '../..'),
    app.getAppPath(),
  ];
  const candidates = app.isPackaged
    ? [...packagedCandidates, ...developmentCandidates]
    : [...developmentCandidates, ...packagedCandidates];

  return findBabaProjectRoot(candidates) ?? path.join(os.homedir(), 'Documents');
}

function findBabaProjectRoot(candidates: string[]): string | null {
  const seen = new Set<string>();

  for (const candidate of candidates) {
    const normalizedCandidate = path.resolve(candidate);
    if (seen.has(normalizedCandidate)) {
      continue;
    }
    seen.add(normalizedCandidate);

    if (isBabaProjectRoot(normalizedCandidate)) {
      return normalizedCandidate;
    }
  }

  return null;
}

function isBabaProjectRoot(directoryPath: string): boolean {
  const searchToolPath = path.join(directoryPath, 'tools', 'baba-search', 'baba-search');

  try {
    if (!statSync(searchToolPath).isFile()) {
      return false;
    }

    if (process.platform !== 'win32') {
      accessSync(searchToolPath, constants.X_OK);
    }

    return true;
  } catch {
    return false;
  }
}

function resolveBabaSearchExecutable(cwd: string): string | null {
  const candidates = [
    path.join(cwd, 'tools', 'baba-search', 'baba-search'),
    path.join(process.resourcesPath, 'tools', 'baba-search', 'baba-search'),
    path.join(process.resourcesPath, 'app', 'tools', 'baba-search', 'baba-search'),
    path.join(app.getAppPath(), 'tools', 'baba-search', 'baba-search'),
    path.resolve(currentDir, '../tools/baba-search/baba-search'),
    path.resolve(currentDir, '../../tools/baba-search/baba-search'),
  ];

  const seen = new Set<string>();
  for (const candidate of candidates) {
    const normalizedCandidate = path.resolve(candidate);
    if (seen.has(normalizedCandidate)) {
      continue;
    }
    seen.add(normalizedCandidate);

    try {
      if (!statSync(normalizedCandidate).isFile()) {
        continue;
      }
      if (process.platform !== 'win32') {
        accessSync(normalizedCandidate, constants.X_OK);
      }
      return normalizedCandidate;
    } catch {
      // Keep trying the packaged and development locations.
    }
  }

  return null;
}

async function readSourceCitation(value: unknown): Promise<Record<string, unknown>> {
  const request = sourceCitationRequest(value);
  const executable = resolveBabaSearchExecutable(request.cwd);
  if (!executable) {
    throw new Error('The Baba search executable could not be found for this workspace.');
  }

  const result = await execFileAsync(
    executable,
    [
      'passage',
      '--citation',
      request.citation,
      '--context-passages',
      '4',
      '--json',
    ],
    {
      cwd: request.cwd,
      timeout: 20_000,
      maxBuffer: 2_000_000,
      windowsHide: true,
    },
  );

  let payload: unknown;
  try {
    payload = JSON.parse(result.stdout);
  } catch {
    throw new Error('The Baba source reader returned invalid JSON.');
  }

  if (!isRecord(payload) || !Array.isArray(payload.passages)) {
    throw new Error('The Baba source reader returned an invalid passage.');
  }

  return payload;
}

function sourceCitationRequest(value: unknown): { cwd: string; citation: string } {
  if (!isRecord(value)) {
    throw new Error('Source reader request must be an object.');
  }

  const cwd = typeof value.cwd === 'string' ? value.cwd.trim() : '';
  const citation = typeof value.citation === 'string' ? value.citation.trim() : '';
  if (!cwd || !path.isAbsolute(cwd)) {
    throw new Error('Source reader request must include an absolute workspace directory.');
  }
  if (!/^(?:Discourses|Stories|Other-Spiritual-Books|Acharya-Philosophy)\/[^\n#]+#[^\n#]+$/.test(citation)) {
    throw new Error('Source reader citation is invalid.');
  }

  return { cwd, citation };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

async function listSkills(): Promise<SkillCatalog> {
  const embeddedSkillsDir = await resolveEmbeddedSkillsDirectory();
  const codexSkillsDir = path.join(os.homedir(), '.codex', 'skills');

  const [embeddedSkills, codexSkills] = await Promise.all([
    readSkillEntries(embeddedSkillsDir),
    readSkillEntries(codexSkillsDir),
  ]);

  return {
    embeddedSkillsDir,
    codexSkillsDir,
    embeddedSkills,
    codexSkills,
  };
}

async function resolveEmbeddedSkillsDirectory() {
  const candidates = [
    path.join(app.getAppPath(), 'src-electron', 'SKILLS'),
    path.join(process.resourcesPath, 'SKILLS'),
    path.join(currentDir, 'SKILLS'),
    path.join(process.cwd(), 'src-electron', 'SKILLS'),
  ];

  for (const candidate of candidates) {
    if (await pathExists(candidate)) {
      return candidate;
    }
  }

  return candidates[0] ?? path.join(process.cwd(), 'src-electron', 'SKILLS');
}

async function readSkillEntries(rootDir: string): Promise<SkillEntry[]> {
  if (!(await pathExists(rootDir))) {
    return [];
  }

  const skillFiles = await findSkillFiles(rootDir, 2);
  const entries = await Promise.all(
    skillFiles.map(async (skillFile) => {
      const summary = await readSkillSummary(skillFile);
      const content = await readSkillContent(skillFile);
      const directory = path.dirname(skillFile);
      return {
        name: path.basename(directory),
        directory,
        skillFile,
        summary,
        content,
      };
    }),
  );

  return entries.sort((left, right) => left.name.localeCompare(right.name));
}

async function findSkillFiles(directoryPath: string, depth: number): Promise<string[]> {
  if (depth < 0) {
    return [];
  }

  const directoryEntries = await readdir(directoryPath, { withFileTypes: true });
  const found: string[] = [];

  for (const entry of directoryEntries) {
    const fullPath = path.join(directoryPath, entry.name);

    if (entry.isDirectory()) {
      found.push(...(await findSkillFiles(fullPath, depth - 1)));
      continue;
    }

    if (entry.isFile() && entry.name === 'SKILL.md') {
      found.push(fullPath);
    }
  }

  return found;
}

async function readSkillSummary(skillFile: string): Promise<string> {
  try {
    const content = await readSkillContent(skillFile);
    const lines = content
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);

    const summaryLine = lines.find((line) => !line.startsWith('#'));
    return summaryLine ?? 'No summary available.';
  } catch {
    return 'No summary available.';
  }
}

async function readSkillContent(skillFile: string): Promise<string> {
  try {
    return await readFile(skillFile, 'utf8');
  } catch {
    return '';
  }
}

async function saveEmbeddedSkill(skillFile: string, content: string) {
  const embeddedSkillsDir = await resolveEmbeddedSkillsDirectory();
  const normalizedRoot = path.resolve(embeddedSkillsDir);
  const normalizedSkillFile = path.resolve(skillFile);

  if (!normalizedSkillFile.startsWith(`${normalizedRoot}${path.sep}`)) {
    throw new Error('Only embedded app skills can be edited here.');
  }

  await writeFile(normalizedSkillFile, content, 'utf8');

  return {
    ok: true,
    skillFile: normalizedSkillFile,
  };
}

async function pathExists(targetPath: string): Promise<boolean> {
  try {
    await access(targetPath);
    return true;
  } catch {
    return false;
  }
}

function getAuthUrl(value: unknown): string | null {
  if (
    value &&
    typeof value === 'object' &&
    'authUrl' in value &&
    typeof value.authUrl === 'string'
  ) {
    return value.authUrl;
  }

  return null;
}

const HYBRID_CREDENTIALS_FILE = 'baba-chat-hybrid-credentials.json';

async function readHybridApiKey(): Promise<string | null> {
  const credentialsPath = path.join(app.getPath('userData'), HYBRID_CREDENTIALS_FILE);

  try {
    const content = await readFile(credentialsPath, 'utf8');
    const record = JSON.parse(content) as { encryptedApiKey?: unknown };
    if (typeof record.encryptedApiKey === 'string' && safeStorage.isEncryptionAvailable()) {
      const encrypted = Buffer.from(record.encryptedApiKey, 'base64');
      const value = safeStorage.decryptString(encrypted).trim();
      if (value) {
        return value;
      }
    }
  } catch {
    // Fall back to the explicit development environment variable below.
  }

  const environmentKey = process.env.BABA_LLM_API_KEY?.trim();
  return environmentKey || null;
}

async function saveHybridApiKey(value: unknown): Promise<void> {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error('Enter an API key before saving it.');
  }

  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('The operating system secure storage is unavailable in this session.');
  }

  const encrypted = safeStorage.encryptString(value.trim());
  const credentialsPath = path.join(app.getPath('userData'), HYBRID_CREDENTIALS_FILE);
  await writeFile(
    credentialsPath,
    JSON.stringify({ version: 1, encryptedApiKey: encrypted.toString('base64') }),
    { encoding: 'utf8', mode: 0o600 },
  );
}

async function clearHybridApiKey(): Promise<void> {
  const credentialsPath = path.join(app.getPath('userData'), HYBRID_CREDENTIALS_FILE);
  try {
    await unlink(credentialsPath);
  } catch (error: unknown) {
    if (!isFileNotFoundError(error)) {
      throw error;
    }
  }
}

function isFileNotFoundError(error: unknown): boolean {
  return Boolean(error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT');
}

function registerDisplayListeners() {
  if (displayListenersRegistered) {
    return;
  }

  const keepWidgetWindowVisible = () => {
    if (!widgetModeActive || !mainWindow || mainWindow.isDestroyed()) {
      return;
    }

    const currentBounds = mainWindow.getBounds();
    const visibleBounds = clampBoundsToVisibleDisplay(currentBounds, true);
    if (!areBoundsEqual(currentBounds, visibleBounds)) {
      mainWindow.setBounds(visibleBounds);
    }

    applyWidgetMouseState();
  };

  screen.on('display-added', keepWidgetWindowVisible);
  screen.on('display-removed', keepWidgetWindowVisible);
  screen.on('display-metrics-changed', keepWidgetWindowVisible);
  displayListenersRegistered = true;
}

function clampBoundsToVisibleDisplay(bounds: Rectangle, fitSize: boolean): Rectangle {
  try {
    const display = screen.getDisplayMatching(bounds);
    const workArea = display.workArea;
    const width = fitSize ? Math.min(bounds.width, workArea.width) : bounds.width;
    const height = fitSize ? Math.min(bounds.height, workArea.height) : bounds.height;
    const maxX = workArea.x + Math.max(0, workArea.width - width);
    const maxY = workArea.y + Math.max(0, workArea.height - height);

    return {
      x: Math.min(Math.max(bounds.x, workArea.x), maxX),
      y: Math.min(Math.max(bounds.y, workArea.y), maxY),
      width,
      height,
    };
  } catch {
    // Display information is unavailable only during unusual app/display
    // transitions. Keep the requested bounds and let Electron retry later.
    return bounds;
  }
}

function areBoundsEqual(left: Rectangle, right: Rectangle): boolean {
  return (
    left.x === right.x &&
    left.y === right.y &&
    left.width === right.width &&
    left.height === right.height
  );
}

function applyWidgetMouseState() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }

  const ignoreMouseEvents = widgetModeActive && !widgetCollapsedState && widgetClickThroughEnabled;
  mainWindow.setIgnoreMouseEvents(
    ignoreMouseEvents,
    ignoreMouseEvents ? { forward: true } : undefined,
  );
}

async function createWindow() {
  /**
   * Initial window options
   */
  mainWindow = new BrowserWindow({
    icon: path.resolve(currentDir, 'icons/icon.png'), // tray icon
    width: 1000,
    height: 600,
    minWidth: 360,
    minHeight: 420,
    backgroundColor: '#00000000',
    frame: false,
    transparent: true,
    useContentSize: true,
    webPreferences: {
      contextIsolation: true,
      // More info: https://v2.quasar.dev/quasar-cli-vite/developing-electron-apps/electron-preload-script
      preload: path.resolve(
        currentDir,
        path.join(
          process.env.QUASAR_ELECTRON_PRELOAD_FOLDER,
          'electron-preload' + process.env.QUASAR_ELECTRON_PRELOAD_EXTENSION,
        ),
      ),
    },
  });

  if (process.env.DEV) {
    await mainWindow.loadURL(process.env.APP_URL);
  } else {
    await mainWindow.loadFile('index.html');
  }

  if (process.env.DEBUGGING) {
    // if on DEV or Production with debug enabled
    mainWindow.webContents.openDevTools();
  } else {
    // we're on production; no access to devtools pls
    mainWindow.webContents.on('devtools-opened', () => {
      mainWindow?.webContents.closeDevTools();
    });
  }

  mainWindow.on('closed', () => {
    embeddedTerminal.killAll();
    normalWindowState = undefined;
    widgetModeActive = false;
    widgetCollapsedState = false;
    widgetClickThroughEnabled = false;
    mainWindow = undefined;
  });

  registerDisplayListeners();
}

function setWidgetMode(enabled: boolean) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }

  if (enabled) {
    registerDisplayListeners();

    if (widgetModeActive) {
      // The renderer can replay this IPC call while restoring its own state.
      // Do not overwrite the normal-window snapshot or change collapse state.
      applyWidgetMouseState();
      const visibleBounds = clampBoundsToVisibleDisplay(mainWindow.getBounds(), true);
      if (!areBoundsEqual(mainWindow.getBounds(), visibleBounds)) {
        mainWindow.setBounds(visibleBounds);
      }
      return;
    }

    const minimumSize = mainWindow.getMinimumSize();
    const maximized = mainWindow.isMaximized();
    const fullScreen = mainWindow.isFullScreen();
    const nextNormalWindowState: NormalWindowState = {
      bounds: mainWindow.getNormalBounds(),
      minimumSize: [minimumSize[0] ?? 360, minimumSize[1] ?? 420] as [number, number],
      resizable: mainWindow.isResizable(),
      movable: mainWindow.isMovable(),
      minimizable: mainWindow.isMinimizable(),
      maximizable: mainWindow.isMaximizable(),
      hasShadow: mainWindow.hasShadow(),
      alwaysOnTop: mainWindow.isAlwaysOnTop(),
      maximized,
      fullScreen,
    };
    normalWindowState = nextNormalWindowState;
    widgetModeActive = true;
    widgetCollapsedState = false;
    widgetClickThroughEnabled = false;

    if (fullScreen) {
      mainWindow.setFullScreen(false);
    }
    if (maximized) {
      mainWindow.unmaximize();
    }

    mainWindow.setAlwaysOnTop(true, 'floating');
    mainWindow.setSkipTaskbar(true);
    mainWindow.setMinimumSize(widgetCollapsedSize.width, widgetCollapsedSize.height);
    mainWindow.setResizable(false);
    mainWindow.setMovable(true);
    mainWindow.setMinimizable(false);
    mainWindow.setMaximizable(false);
    mainWindow.setHasShadow(false);
    mainWindow.setBackgroundColor('#00000000');
    applyWidgetMouseState();
    mainWindow.setBounds(
      clampBoundsToVisibleDisplay(
        {
          width: widgetExpandedSize.width,
          height: widgetExpandedSize.height,
          x: nextNormalWindowState.bounds.x + nextNormalWindowState.bounds.width - 780,
          y: nextNormalWindowState.bounds.y + 40,
        },
        true,
      ),
    );
    mainWindow.show();
    return;
  }

  const savedWindowState = normalWindowState;
  widgetModeActive = false;
  widgetCollapsedState = false;
  widgetClickThroughEnabled = false;

  mainWindow.setAlwaysOnTop(false);
  mainWindow.setSkipTaskbar(false);
  mainWindow.setMinimumSize(
    savedWindowState?.minimumSize[0] ?? 360,
    savedWindowState?.minimumSize[1] ?? 420,
  );
  mainWindow.setResizable(savedWindowState?.resizable ?? true);
  mainWindow.setMovable(savedWindowState?.movable ?? true);
  mainWindow.setMinimizable(savedWindowState?.minimizable ?? true);
  mainWindow.setMaximizable(savedWindowState?.maximizable ?? true);
  mainWindow.setHasShadow(savedWindowState?.hasShadow ?? true);
  mainWindow.setBackgroundColor('#00000000');
  mainWindow.setIgnoreMouseEvents(false);

  if (savedWindowState) {
    mainWindow.setAlwaysOnTop(savedWindowState.alwaysOnTop);
    const restoredBounds = clampBoundsToVisibleDisplay(savedWindowState.bounds, false);
    mainWindow.setBounds(restoredBounds);
    mainWindow.show();

    if (savedWindowState.maximized && !savedWindowState.fullScreen) {
      mainWindow.maximize();
    }
    if (savedWindowState.fullScreen) {
      mainWindow.setFullScreen(true);
    }
  } else {
    mainWindow.show();
  }

  normalWindowState = undefined;
}

function handleWindowAction(action: string) {
  if (!mainWindow) {
    return;
  }

  if (action === 'minimize') {
    mainWindow.minimize();
    return;
  }

  if (action === 'maximize') {
    if (mainWindow.isMaximized()) {
      mainWindow.unmaximize();
    } else {
      mainWindow.maximize();
    }
    return;
  }

  if (action === 'close') {
    mainWindow.close();
  }
}

function setWidgetCollapsed(collapsed: boolean) {
  if (!mainWindow || mainWindow.isDestroyed() || !widgetModeActive) {
    return;
  }

  widgetCollapsedState = collapsed;
  if (collapsed) {
    // Renderer pointer coordinates can arrive from the previous expanded
    // layout. The collapsed restore orb must remain interactive regardless.
    widgetClickThroughEnabled = false;
  }
  applyWidgetMouseState();

  const currentBounds = mainWindow.getBounds();
  const visibleCurrentBounds = clampBoundsToVisibleDisplay(currentBounds, true);
  if (!areBoundsEqual(currentBounds, visibleCurrentBounds)) {
    mainWindow.setBounds(visibleCurrentBounds);
  }

  const bounds = mainWindow.getBounds();
  const orbCenterX = bounds.x + bounds.width - widgetOrbCenterFromRight;
  const orbCenterY = bounds.y + bounds.height - widgetOrbCenterFromBottom;
  const targetSize = collapsed ? widgetCollapsedSize : widgetExpandedSize;

  mainWindow.setBounds(
    clampBoundsToVisibleDisplay(
      {
        width: targetSize.width,
        height: targetSize.height,
        x: Math.round(orbCenterX - targetSize.width + widgetOrbCenterFromRight),
        y: Math.round(orbCenterY - targetSize.height + widgetOrbCenterFromBottom),
      },
      true,
    ),
  );
  applyWidgetMouseState();
}

function moveWindowBy(deltaX: number, deltaY: number) {
  if (
    !mainWindow ||
    mainWindow.isDestroyed() ||
    !Number.isFinite(deltaX) ||
    !Number.isFinite(deltaY)
  ) {
    return;
  }

  if (widgetModeActive) {
    const bounds = mainWindow.getBounds();
    mainWindow.setBounds(
      clampBoundsToVisibleDisplay(
        {
          ...bounds,
          x: Math.round(bounds.x + deltaX),
          y: Math.round(bounds.y + deltaY),
        },
        true,
      ),
    );
    return;
  }

  const [x, y] = mainWindow.getPosition();
  if (x === undefined || y === undefined) {
    return;
  }

  mainWindow.setPosition(Math.round(x + deltaX), Math.round(y + deltaY));
}

function setWidgetClickThrough(enabled: boolean) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }

  // Click-through is an opt-in expanded-widget behavior. In particular, a
  // stale renderer mousemove/pointer event must never make the collapsed orb
  // unreachable.
  widgetClickThroughEnabled = Boolean(enabled) && widgetModeActive && !widgetCollapsedState;
  applyWidgetMouseState();
}

void app.whenReady().then(async () => {
  await createWindow();
});

app.on('window-all-closed', () => {
  if (platform !== 'darwin') {
    embeddedTerminal.killAll();
    codex.stop();
    app.quit();
  }
});

app.on('before-quit', () => {
  embeddedTerminal.killAll();
  codex.stop();
});

app.on('activate', () => {
  if (mainWindow === undefined) {
    void createWindow();
  }
});
