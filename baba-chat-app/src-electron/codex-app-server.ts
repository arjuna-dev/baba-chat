import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { existsSync, readdirSync, statSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';

export type JsonValue =
  | null
  | string
  | number
  | boolean
  | JsonValue[]
  | { [key: string]: JsonValue };

/**
 * Reasoning effort values observed in the installed Codex app-server model
 * catalog. The wire protocol represents this as a string, but these are the
 * values currently exposed by model/list for the available models.
 */
export const CODEX_REASONING_EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max', 'ultra'] as const;

export type CodexReasoningEffort = (typeof CODEX_REASONING_EFFORTS)[number];

export interface CodexReasoningEffortOption {
  reasoningEffort: string;
  description: string;
}

export interface CodexModelServiceTier {
  id: string;
  name: string;
  description: string;
}

export interface CodexModel {
  id: string;
  model: string;
  upgrade: string | null;
  upgradeInfo: JsonValue | null;
  availabilityNux: { message: string } | null;
  displayName: string;
  description: string;
  hidden: boolean;
  supportedReasoningEfforts: CodexReasoningEffortOption[];
  defaultReasoningEffort: string;
  inputModalities: string[];
  supportsPersonality: boolean;
  additionalSpeedTiers: string[];
  serviceTiers: CodexModelServiceTier[];
  defaultServiceTier: string | null;
  isDefault: boolean;
}

export interface CodexModelListResponse {
  data: CodexModel[];
  nextCursor: string | null;
}

export type CodexRpcId = number | string;

export interface CodexRpcMessage {
  id?: CodexRpcId;
  method?: string;
  params?: JsonValue;
  result?: JsonValue;
  error?: {
    code: number;
    message: string;
    data?: JsonValue;
  };
}

export interface StartThreadInput {
  cwd?: string;
  model?: string;
}

export interface StartTurnInput {
  threadId: string;
  text: string;
  cwd?: string;
  model?: string;
  /** Renderer-facing name. It is mapped to the app-server's `effort` field. */
  reasoningEffort?: CodexReasoningEffort;
  /** Backward-compatible alias accepted from older renderers. */
  effort?: string;
}

export interface ServerRequestResponse {
  requestId: CodexRpcId;
  result?: JsonValue;
  error?: {
    code?: number;
    message: string;
    data?: JsonValue;
  };
}

interface PendingRequest {
  resolve: (value: JsonValue) => void;
  reject: (error: Error) => void;
  timeout: ReturnType<typeof setTimeout>;
}

const CODEX_CLIENT_INFO = {
  name: 'baba_chat',
  title: 'Baba Chat',
  version: '0.1.0',
};

const REQUEST_TIMEOUT_MS = 30_000;

export type CodexChildEnvironmentProvider = () => Record<string, string>;

export class CodexAppServer extends EventEmitter {
  private proc: ChildProcessWithoutNullStreams | null = null;
  private nextId = 1;
  private readonly pending = new Map<CodexRpcId, PendingRequest>();
  private initializePromise: Promise<void> | null = null;

  constructor(
    private readonly childEnvironmentProvider: CodexChildEnvironmentProvider = () => ({}),
  ) {
    super();
  }

  async ensureStarted(): Promise<void> {
    if (this.initializePromise) {
      return this.initializePromise;
    }

    this.initializePromise = this.start().catch((error: unknown) => {
      this.initializePromise = null;
      throw error;
    });
    return this.initializePromise;
  }

  async accountRead(refreshToken = false): Promise<JsonValue> {
    await this.ensureStarted();
    return this.request('account/read', { refreshToken });
  }

  async accountRateLimitsRead(): Promise<JsonValue> {
    await this.ensureStarted();
    return this.request('account/rateLimits/read', null);
  }

  async loginWithChatGpt(): Promise<JsonValue> {
    await this.ensureStarted();
    return this.request('account/login/start', { type: 'chatgpt' });
  }

  async loginWithApiKey(apiKey: string): Promise<JsonValue> {
    await this.ensureStarted();
    return this.request('account/login/start', { type: 'apiKey', apiKey });
  }

  async logout(): Promise<JsonValue> {
    await this.ensureStarted();
    return this.request('account/logout', {});
  }

  async listModels(): Promise<CodexModelListResponse> {
    await this.ensureStarted();
    return (await this.request('model/list', {
      limit: 50,
      includeHidden: false,
    })) as unknown as CodexModelListResponse;
  }

  async listThreads(cwd?: string): Promise<JsonValue> {
    await this.ensureStarted();
    return this.request('thread/list', {
      cursor: null,
      limit: 50,
      sortKey: 'updated_at',
      sourceKinds: ['appServer'],
      ...(cwd ? { cwd } : {}),
    });
  }

  async startThread(input: StartThreadInput): Promise<JsonValue> {
    await this.ensureStarted();

    const params: { [key: string]: JsonValue } = {
      serviceName: 'baba_chat',
      experimentalRawEvents: false,
      persistExtendedHistory: true,
    };

    if (input.cwd) {
      params.cwd = input.cwd;
    }

    if (input.model) {
      params.model = input.model;
    }

    return this.request('thread/start', params);
  }

  async startTurn(input: StartTurnInput): Promise<JsonValue> {
    await this.ensureStarted();

    const params: { [key: string]: JsonValue } = {
      threadId: input.threadId,
      input: [{ type: 'text', text: input.text, text_elements: [] }],
    };

    if (input.cwd) {
      params.cwd = input.cwd;
    }

    if (input.model) {
      params.model = input.model;
    }

    const reasoningEffort = normalizeReasoningEffort(input.reasoningEffort ?? input.effort);

    if (reasoningEffort) {
      // The installed app-server protocol calls this field `effort`. Do not
      // send the renderer-facing `reasoningEffort` name over the wire.
      params.effort = reasoningEffort;
    }

    return this.request('turn/start', params);
  }

  async interruptTurn(threadId: string, turnId: string): Promise<JsonValue> {
    await this.ensureStarted();
    return this.request('turn/interrupt', { threadId, turnId });
  }

  respondToServerRequest(response: ServerRequestResponse): void {
    if (!this.proc?.stdin.writable) {
      throw new Error('Codex app-server is not running.');
    }

    if (response.error) {
      const error: CodexRpcMessage['error'] = {
        code: response.error.code ?? -32000,
        message: response.error.message,
      };

      if (response.error.data !== undefined) {
        error.data = response.error.data;
      }

      this.write({
        id: response.requestId,
        error,
      });
      return;
    }

    this.write({
      id: response.requestId,
      result: response.result ?? {},
    });
  }

  stop(): void {
    this.rejectPending(new Error('Codex app-server stopped.'));
    this.proc?.kill();
    this.proc = null;
    this.initializePromise = null;
  }

  private async start(): Promise<void> {
    const codexPath = resolveCodexExecutable();

    if (!codexPath) {
      throw new Error(
        'Could not find the Codex CLI. Install it or set CODEX_APP_BIN to the codex executable path.',
      );
    }

    const codexDir = path.dirname(codexPath);
    this.proc = spawn(codexPath, ['app-server'], {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: {
        ...process.env,
        PATH: prependPath(codexDir, process.env.PATH),
        ...this.childEnvironmentProvider(),
      },
    });

    const proc = this.proc;
    const startupError = new Promise<never>((_resolve, reject) => {
      proc.once('error', (error) => {
        const wrapped = new Error(
          `Failed to start Codex app-server from ${codexPath}: ${error.message}`,
        );

        this.emit('event', {
          type: 'process/error',
          message: wrapped.message,
        });
        this.rejectPending(wrapped);
        this.proc = null;
        this.initializePromise = null;
        reject(wrapped);
      });
    });

    proc.once('exit', (code, signal) => {
      this.emit('event', {
        type: 'process/exited',
        code,
        signal,
      });
      this.stop();
    });

    proc.stderr.on('data', (chunk: Buffer) => {
      this.emit('event', {
        type: 'process/stderr',
        text: chunk.toString(),
      });
    });

    const rl = readline.createInterface({ input: proc.stdout });
    rl.on('line', (line) => this.handleLine(line));

    await Promise.race([
      this.request('initialize', {
        clientInfo: CODEX_CLIENT_INFO,
        capabilities: {
          experimentalApi: true,
        },
      }),
      startupError,
    ]);

    this.notify('initialized', {});
  }

  private request(method: string, params?: JsonValue): Promise<JsonValue> {
    if (!this.proc?.stdin.writable) {
      return Promise.reject(new Error('Codex app-server is not running.'));
    }

    const id = this.nextId++;
    const message: CodexRpcMessage = { id, method };
    if (params !== undefined) {
      message.params = params;
    }

    const promise = new Promise<JsonValue>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Codex app-server request timed out: ${method}`));
      }, REQUEST_TIMEOUT_MS);

      this.pending.set(id, { resolve, reject, timeout });
    });

    this.write(message);
    return promise;
  }

  private notify(method: string, params: JsonValue): void {
    this.write({ method, params });
  }

  private write(message: CodexRpcMessage): void {
    this.proc?.stdin.write(`${JSON.stringify(message)}\n`);
  }

  private rejectPending(error: Error): void {
    for (const [, pending] of this.pending) {
      clearTimeout(pending.timeout);
      pending.reject(error);
    }
    this.pending.clear();
  }

  private handleLine(line: string): void {
    let message: CodexRpcMessage;

    try {
      message = JSON.parse(line) as CodexRpcMessage;
    } catch {
      this.emit('event', {
        type: 'protocol/invalid-json',
        line,
      });
      return;
    }

    if (message.id !== undefined && message.method) {
      this.emit('event', {
        type: 'server/request',
        request: message,
      });
      return;
    }

    if (message.id !== undefined) {
      const pending = this.pending.get(message.id);
      if (!pending) {
        this.emit('event', {
          type: 'protocol/unhandled-response',
          message,
        });
        return;
      }

      this.pending.delete(message.id);
      clearTimeout(pending.timeout);
      if (message.error) {
        pending.reject(new Error(message.error.message));
      } else {
        pending.resolve(message.result ?? {});
      }
      return;
    }

    this.emit('event', message);
  }
}

/**
 * Normalize the renderer contract to a value accepted by the current model
 * catalog. Missing, blank, or unsupported values are omitted so older
 * callers continue to use the server default.
 */
export function normalizeReasoningEffort(value: unknown): CodexReasoningEffort | undefined {
  if (typeof value !== 'string') {
    return undefined;
  }

  const normalized = value.trim().toLowerCase();
  return (CODEX_REASONING_EFFORTS as readonly string[]).includes(normalized)
    ? (normalized as CodexReasoningEffort)
    : undefined;
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
    '/opt/homebrew/bin/codex',
    '/usr/local/bin/codex',
    '/Applications/Codex.app/Contents/Resources/codex',
    ...nvmCodexCandidates(),
  ];

  return candidates.find(isExecutableFile) ?? null;
}

function findOnPath(command: string): string | null {
  const pathValue = process.env.PATH || '';
  const paths = pathValue.split(path.delimiter).filter(Boolean);

  for (const dir of paths) {
    const candidate = path.join(dir, command);
    if (isExecutableFile(candidate)) {
      return candidate;
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
    const diff = (rightParts[index] ?? 0) - (leftParts[index] ?? 0);
    if (diff !== 0) {
      return diff;
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
    return statSync(filePath).isFile();
  } catch {
    return existsSync(filePath);
  }
}

function prependPath(directory: string, existingPath = ''): string {
  const parts = existingPath.split(path.delimiter).filter(Boolean);
  return [directory, ...parts.filter((part) => part !== directory)].join(path.delimiter);
}
