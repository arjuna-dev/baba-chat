import {
  accessSync,
  closeSync,
  constants,
  openSync,
  readdirSync,
  readSync,
  statSync,
} from 'node:fs';
import { realpath, stat } from 'node:fs/promises';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import type { IPty, spawn as spawnPty } from 'node-pty';

const DEFAULT_COLS = 100;
const DEFAULT_ROWS = 30;
const MIN_COLS = 2;
const MAX_COLS = 500;
const MIN_ROWS = 1;
const MAX_ROWS = 200;
const MAX_INPUT_LENGTH = 128 * 1024;
const MAX_ACTIVE_SESSIONS = 4;
const TERMINAL_ID_PATTERN = /^term_[a-f0-9]{32}$/;
const CODEX_SESSION_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CODEX_SESSION_DISCOVERY_ATTEMPTS = 300;
const CODEX_SESSION_DISCOVERY_DELAY_MS = 100;

type NodePtyApi = {
  spawn: typeof spawnPty;
};

type NodePtyExports = {
  spawn?: typeof spawnPty;
  default?: NodePtyApi;
};

type TerminalProcessState = 'starting' | 'running' | 'exited' | 'killed' | 'error';

export interface EmbeddedTerminalCreateInput {
  cwd: string;
  cols?: number;
  rows?: number;
  resumeSessionId?: string;
}

export interface EmbeddedTerminalStatus {
  terminalId: string;
  state: TerminalProcessState;
  cwd: string;
  codexSessionId?: string;
  pid?: number;
  exitCode?: number;
  signal?: number;
  message?: string;
}

export interface EmbeddedTerminalAvailability {
  available: boolean;
  message?: string;
}

export interface EmbeddedTerminalOutputEvent {
  terminalId: string;
  data: string;
}

type TerminalStatusListener = (status: EmbeddedTerminalStatus) => void;
type TerminalOutputListener = (output: EmbeddedTerminalOutputEvent) => void;

interface TerminalSession {
  terminalId: string;
  cwd: string;
  codexSessionId: string | undefined;
  pty: IPty | undefined;
  state: TerminalProcessState;
  pid: number | undefined;
  exitCode: number | undefined;
  signal: number | undefined;
  message: string | undefined;
  stopRequested: boolean;
}

const nodeRequire = createRequire(import.meta.url);
let nodePty: NodePtyApi | null | undefined;
let nodePtyLoadError: string | undefined;

/**
 * Owns all interactive Codex PTYs. This module is intentionally usable from
 * Electron main only. The renderer receives opaque session IDs and output
 * events through the preload bridge.
 */
export class EmbeddedTerminalManager {
  private readonly sessions = new Map<string, TerminalSession>();
  private readonly statusListeners = new Set<TerminalStatusListener>();
  private readonly outputListeners = new Set<TerminalOutputListener>();

  onStatus(listener: TerminalStatusListener): () => void {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }

  onOutput(listener: TerminalOutputListener): () => void {
    this.outputListeners.add(listener);
    return () => this.outputListeners.delete(listener);
  }

  availability(): EmbeddedTerminalAvailability {
    const api = loadNodePty();
    if (!api) {
      return {
        available: false,
        message:
          nodePtyLoadError ??
          'The embedded terminal native module could not be loaded. Rebuild node-pty for this Electron version.',
      };
    }

    if (!resolveCodexExecutable()) {
      return {
        available: false,
        message:
          'The Codex CLI was not found. Install Codex or set CODEX_APP_BIN to its executable path.',
      };
    }

    return { available: true };
  }

  async create(input: unknown): Promise<EmbeddedTerminalStatus> {
    const parsedInput = parseCreateInput(input);
    const cwd = await validateWorkingDirectory(parsedInput.cwd);
    const knownSessionFiles = parsedInput.resumeSessionId
      ? new Set<string>()
      : listCodexSessionFiles();
    const activeSessions = [...this.sessions.values()].filter(
      (session) => session.state === 'starting' || session.state === 'running',
    ).length;

    if (activeSessions >= MAX_ACTIVE_SESSIONS) {
      throw new Error(`Too many active embedded terminals. Close one before starting another.`);
    }

    const api = loadNodePty();
    if (!api) {
      throw new Error(
        nodePtyLoadError ??
          'The embedded terminal native module could not be loaded. Rebuild node-pty for this Electron version.',
      );
    }

    const codexPath = resolveCodexExecutable();
    if (!codexPath) {
      throw new Error(
        'Could not find the Codex CLI. Install it or set CODEX_APP_BIN to the Codex executable path.',
      );
    }

    const terminalId = `term_${randomUUID().replaceAll('-', '')}`;
    const session: TerminalSession = {
      terminalId,
      cwd,
      codexSessionId: parsedInput.resumeSessionId,
      pty: undefined,
      state: 'starting',
      pid: undefined,
      exitCode: undefined,
      signal: undefined,
      message: undefined,
      stopRequested: false,
    };
    this.sessions.set(terminalId, session);
    this.publishStatus(session);

    try {
      const codexArgs = parsedInput.resumeSessionId ? ['resume', parsedInput.resumeSessionId] : [];
      const terminal = api.spawn(codexPath, codexArgs, {
        name: 'xterm-256color',
        cols: parsedInput.cols,
        rows: parsedInput.rows,
        cwd,
        encoding: 'utf8',
        env: {
          ...process.env,
          PATH: prependPath(path.dirname(codexPath), process.env.PATH),
          TERM: 'xterm-256color',
          COLORTERM: 'truecolor',
        },
      });

      session.pty = terminal;
      session.pid = terminal.pid;
      session.state = 'running';

      terminal.onData((data) => {
        this.publishOutput({ terminalId, data });
      });

      terminal.onExit(({ exitCode, signal }) => {
        session.pty = undefined;
        session.exitCode = exitCode;
        session.signal = signal;
        session.state = session.stopRequested ? 'killed' : 'exited';
        this.publishStatus(session);
      });

      this.publishStatus(session);
      if (!parsedInput.resumeSessionId) {
        void this.discoverCodexSessionId(session, knownSessionFiles);
      }
      return toStatus(session);
    } catch (error: unknown) {
      session.state = 'error';
      session.message = errorMessage(error);
      this.publishStatus(session);
      this.sessions.delete(terminalId);
      throw new Error(`Failed to start the Codex CLI: ${session.message}`);
    }
  }

  input(terminalId: unknown, data: unknown): EmbeddedTerminalStatus {
    const session = this.getSession(terminalId);
    const input = parseTerminalInput(data);

    if (!session.pty || session.state !== 'running') {
      throw new Error(`Embedded terminal ${session.terminalId} is not running.`);
    }

    session.pty.write(input);
    return toStatus(session);
  }

  resize(terminalId: unknown, cols: unknown, rows: unknown): EmbeddedTerminalStatus {
    const session = this.getSession(terminalId);
    const parsedCols = parseDimension(cols, 'columns', MIN_COLS, MAX_COLS);
    const parsedRows = parseDimension(rows, 'rows', MIN_ROWS, MAX_ROWS);

    if (session.pty && session.state === 'running') {
      session.pty.resize(parsedCols, parsedRows);
    }

    return toStatus(session);
  }

  kill(terminalId: unknown): EmbeddedTerminalStatus {
    const session = this.getSession(terminalId);

    if (!session.pty || session.state === 'exited' || session.state === 'killed') {
      return toStatus(session);
    }

    session.stopRequested = true;
    session.state = 'killed';
    this.publishStatus(session);

    try {
      session.pty.kill();
    } catch (error: unknown) {
      session.message = errorMessage(error);
      this.publishStatus(session);
    }

    return toStatus(session);
  }

  status(terminalId?: unknown): EmbeddedTerminalStatus | EmbeddedTerminalAvailability {
    if (terminalId === undefined) {
      return this.availability();
    }

    return toStatus(this.getSession(terminalId));
  }

  killAll(): void {
    for (const session of this.sessions.values()) {
      if (!session.pty || session.state === 'exited' || session.state === 'killed') {
        continue;
      }

      session.stopRequested = true;
      session.state = 'killed';
      try {
        session.pty.kill();
      } catch {
        // Teardown must continue even when an already-closing PTY rejects kill.
      }
    }
  }

  private getSession(terminalId: unknown): TerminalSession {
    const parsedTerminalId = parseTerminalId(terminalId);
    const session = this.sessions.get(parsedTerminalId);
    if (!session) {
      throw new Error(`Unknown embedded terminal ID: ${parsedTerminalId}.`);
    }

    return session;
  }

  private publishStatus(session: TerminalSession): void {
    const status = toStatus(session);
    for (const listener of this.statusListeners) {
      listener(status);
    }
  }

  private publishOutput(output: EmbeddedTerminalOutputEvent): void {
    for (const listener of this.outputListeners) {
      listener(output);
    }
  }

  private async discoverCodexSessionId(
    session: TerminalSession,
    knownSessionFiles: Set<string>,
  ): Promise<void> {
    for (let attempt = 0; attempt < CODEX_SESSION_DISCOVERY_ATTEMPTS; attempt += 1) {
      if (session.state === 'killed') {
        return;
      }

      const sessionId = findNewCodexSessionId(knownSessionFiles, session.cwd);
      if (sessionId) {
        session.codexSessionId = sessionId;
        this.publishStatus(session);
        return;
      }

      await wait(CODEX_SESSION_DISCOVERY_DELAY_MS);
    }
  }
}

function loadNodePty(): NodePtyApi | null {
  if (nodePty !== undefined) {
    return nodePty;
  }

  try {
    const loaded = nodeRequire('node-pty') as NodePtyExports;
    const candidate = loaded.default ?? loaded;
    if (typeof candidate.spawn !== 'function') {
      throw new Error('node-pty does not export a spawn function.');
    }

    nodePty = { spawn: candidate.spawn };
  } catch (error: unknown) {
    nodePtyLoadError = errorMessage(error);
    nodePty = null;
  }

  return nodePty;
}

type ParsedEmbeddedTerminalCreateInput = {
  cwd: string;
  cols: number;
  rows: number;
  resumeSessionId?: string;
};

function parseCreateInput(value: unknown): ParsedEmbeddedTerminalCreateInput {
  if (!isRecord(value) || typeof value.cwd !== 'string') {
    throw new Error('Embedded terminal create input must include a cwd string.');
  }

  const resumeSessionId = parseOptionalCodexSessionId(value.resumeSessionId);

  return {
    cwd: value.cwd,
    cols:
      value.cols === undefined
        ? DEFAULT_COLS
        : parseDimension(value.cols, 'columns', MIN_COLS, MAX_COLS),
    rows:
      value.rows === undefined
        ? DEFAULT_ROWS
        : parseDimension(value.rows, 'rows', MIN_ROWS, MAX_ROWS),
    ...(resumeSessionId ? { resumeSessionId } : {}),
  };
}

function parseOptionalCodexSessionId(value: unknown): string | undefined {
  if (value === undefined) {
    return undefined;
  }

  if (typeof value !== 'string' || !CODEX_SESSION_ID_PATTERN.test(value)) {
    throw new Error('Embedded terminal resumeSessionId must be a Codex session UUID.');
  }

  return value;
}

function parseTerminalInput(value: unknown): string {
  if (typeof value !== 'string') {
    throw new Error('Embedded terminal input must be a string.');
  }

  if (value.length > MAX_INPUT_LENGTH) {
    throw new Error(`Embedded terminal input is limited to ${MAX_INPUT_LENGTH} characters.`);
  }

  return value;
}

function parseTerminalId(value: unknown): string {
  if (typeof value !== 'string' || !TERMINAL_ID_PATTERN.test(value)) {
    throw new Error('Invalid embedded terminal ID.');
  }

  return value;
}

function parseDimension(value: unknown, label: string, minimum: number, maximum: number): number {
  if (
    typeof value !== 'number' ||
    !Number.isSafeInteger(value) ||
    value < minimum ||
    value > maximum
  ) {
    throw new Error(`Terminal ${label} must be an integer between ${minimum} and ${maximum}.`);
  }

  return value;
}

async function validateWorkingDirectory(directoryPath: string): Promise<string> {
  if (!directoryPath || !path.isAbsolute(directoryPath)) {
    throw new Error('The terminal working directory must be an absolute path.');
  }

  try {
    const resolvedPath = await realpath(directoryPath);
    const directoryStat = await stat(resolvedPath);
    if (!directoryStat.isDirectory()) {
      throw new Error('The terminal working directory is not a directory.');
    }

    return resolvedPath;
  } catch (error: unknown) {
    if (error instanceof Error && error.message.includes('not a directory')) {
      throw error;
    }

    throw new Error('The terminal working directory must be an existing directory.');
  }
}

function toStatus(session: TerminalSession): EmbeddedTerminalStatus {
  return {
    terminalId: session.terminalId,
    state: session.state,
    cwd: session.cwd,
    ...(session.codexSessionId === undefined ? {} : { codexSessionId: session.codexSessionId }),
    ...(session.pid === undefined ? {} : { pid: session.pid }),
    ...(session.exitCode === undefined ? {} : { exitCode: session.exitCode }),
    ...(session.signal === undefined ? {} : { signal: session.signal }),
    ...(session.message === undefined ? {} : { message: session.message }),
  };
}

function listCodexSessionFiles(): Set<string> {
  const codexHome = process.env.CODEX_HOME || path.join(os.homedir(), '.codex');
  const sessionRoot = path.join(codexHome, 'sessions');
  const files = new Set<string>();
  collectCodexSessionFiles(sessionRoot, 0, files);
  return files;
}

function collectCodexSessionFiles(directory: string, depth: number, files: Set<string>): void {
  if (depth > 3) {
    return;
  }

  try {
    const entries = readdirSync(directory, { withFileTypes: true, encoding: 'utf8' });
    for (const entry of entries) {
      const entryPath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        collectCodexSessionFiles(entryPath, depth + 1, files);
      } else if (entry.isFile() && entry.name.startsWith('rollout-')) {
        files.add(entryPath);
      }
    }
  } catch {
    return;
  }
}

function findNewCodexSessionId(knownSessionFiles: Set<string>, cwd: string): string | null {
  const candidates = [...listCodexSessionFiles()]
    .filter((filePath) => !knownSessionFiles.has(filePath))
    .sort((left, right) => fileModificationTime(right) - fileModificationTime(left));

  for (const filePath of candidates) {
    const metadata = readCodexSessionMetadata(filePath);
    if (metadata?.cwd === cwd && isCodexSessionId(metadata.id)) {
      return metadata.id;
    }
  }

  return null;
}

function readCodexSessionMetadata(filePath: string): { id: string; cwd: string } | null {
  let fileDescriptor: number | undefined;
  try {
    fileDescriptor = openSync(filePath, 'r');
    const buffer = Buffer.alloc(4096);
    const bytesRead = readSync(fileDescriptor, buffer, 0, buffer.length, 0);
    const firstLine = buffer.toString('utf8', 0, bytesRead).split('\n', 1)[0] ?? '';
    const record = JSON.parse(firstLine) as unknown;
    const payload = isRecord(record) ? record.payload : null;
    const id = isRecord(payload) ? payload.id : undefined;
    const cwd = isRecord(payload) ? payload.cwd : undefined;

    return typeof id === 'string' && typeof cwd === 'string' ? { id, cwd } : null;
  } catch {
    return null;
  } finally {
    if (fileDescriptor !== undefined) {
      closeSync(fileDescriptor);
    }
  }
}

function fileModificationTime(filePath: string): number {
  try {
    return statSync(filePath).mtimeMs;
  } catch {
    return 0;
  }
}

function isCodexSessionId(value: string): boolean {
  return CODEX_SESSION_ID_PATTERN.test(value);
}

function wait(durationMs: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, durationMs));
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function resolveCodexExecutable(): string | null {
  const explicitPath = process.env.CODEX_APP_BIN || process.env.CODEX_BIN || '';

  if (isExecutableFile(explicitPath)) {
    return explicitPath;
  }

  const pathMatch = findOnPath('codex');
  if (pathMatch) {
    return pathMatch;
  }

  const candidates = [
    path.join(os.homedir(), '.volta/bin/codex'),
    path.join(os.homedir(), '.local/bin/codex'),
    path.join(os.homedir(), '.npm-global/bin/codex'),
    '/opt/homebrew/bin/codex',
    '/usr/local/bin/codex',
    '/Applications/Codex.app/Contents/Resources/codex',
    ...nvmCodexCandidates(),
  ];

  return candidates.find(isExecutableFile) ?? null;
}

function findOnPath(command: string): string | null {
  const pathValue = process.env.PATH || '';
  const pathEntries = pathValue.split(path.delimiter).filter(Boolean);
  const commandNames =
    process.platform === 'win32' ? [command, `${command}.cmd`, `${command}.exe`] : [command];

  for (const directory of pathEntries) {
    for (const commandName of commandNames) {
      const candidate = path.join(directory, commandName);
      if (isExecutableFile(candidate)) {
        return candidate;
      }
    }
  }

  return null;
}

function nvmCodexCandidates(): string[] {
  const nodeVersionsDir = path.join(os.homedir(), '.nvm/versions/node');

  try {
    return readdirSync(nodeVersionsDir)
      .filter((entry) => entry.startsWith('v'))
      .sort(compareNodeVersionsDesc)
      .map((entry) => path.join(nodeVersionsDir, entry, 'bin/codex'));
  } catch {
    return [];
  }
}

function compareNodeVersionsDesc(left: string, right: string): number {
  const leftParts = parseNodeVersion(left);
  const rightParts = parseNodeVersion(right);

  for (let index = 0; index < 3; index += 1) {
    const difference = (rightParts[index] ?? 0) - (leftParts[index] ?? 0);
    if (difference !== 0) {
      return difference;
    }
  }

  return 0;
}

function parseNodeVersion(version: string): [number, number, number] {
  const [, major = '0', minor = '0', patch = '0'] = /^v?(\d+)\.(\d+)\.(\d+)/.exec(version) ?? [];

  return [Number(major), Number(minor), Number(patch)];
}

function isExecutableFile(filePath: string): boolean {
  if (!filePath) {
    return false;
  }

  try {
    if (!statSync(filePath).isFile()) {
      return false;
    }

    if (process.platform !== 'win32') {
      accessSync(filePath, constants.X_OK);
    }

    return true;
  } catch {
    return false;
  }
}

function prependPath(directory: string, existingPath = ''): string {
  const parts = existingPath.split(path.delimiter).filter(Boolean);
  return [directory, ...parts.filter((part) => part !== directory)].join(path.delimiter);
}
