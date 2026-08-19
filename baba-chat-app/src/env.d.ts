declare namespace NodeJS {
  interface ProcessEnv {
    NODE_ENV: string;
    VUE_ROUTER_MODE: 'hash' | 'history' | 'abstract' | undefined;
    VUE_ROUTER_BASE: string | undefined;
  }
}

type EmbeddedTerminalState = 'starting' | 'running' | 'exited' | 'killed' | 'error';

interface EmbeddedTerminalCreateInput {
  cwd: string;
  cols?: number;
  rows?: number;
  resumeSessionId?: string;
}

interface EmbeddedTerminalStatusPayload {
  terminalId: string;
  state: EmbeddedTerminalState;
  cwd: string;
  codexSessionId?: string;
  pid?: number;
  exitCode?: number;
  signal?: number;
  message?: string;
}

interface EmbeddedTerminalAvailabilityPayload {
  available: boolean;
  message?: string;
}

interface EmbeddedTerminalOutputPayload {
  terminalId: string;
  data: string;
}

interface EmbeddedTerminalApi {
  create(input: EmbeddedTerminalCreateInput): Promise<EmbeddedTerminalStatusPayload>;
  input(terminalId: string, data: string): Promise<EmbeddedTerminalStatusPayload>;
  resize(terminalId: string, cols: number, rows: number): Promise<EmbeddedTerminalStatusPayload>;
  kill(terminalId: string): Promise<EmbeddedTerminalStatusPayload>;
  status(
    terminalId?: string,
  ): Promise<EmbeddedTerminalStatusPayload | EmbeddedTerminalAvailabilityPayload>;
  onOutput(handler: (event: EmbeddedTerminalOutputPayload) => void): () => void;
  onStatus(handler: (event: EmbeddedTerminalStatusPayload) => void): () => void;
}

type HybridProvider = 'deepseek' | 'openai-compatible';

interface HybridApiStatus {
  configured: boolean;
  provider: HybridProvider;
  model: string;
  baseUrl: string;
  maxOutputTokens: number;
}

interface HybridContextMessage {
  role: 'user' | 'assistant';
  text: string;
}

interface HybridApiRequestInput {
  requestId: string;
  task: string;
  cwd: string;
  sourceScope: string;
  provider?: HybridProvider;
  apiBaseUrl?: string;
  apiModel?: string;
  maxOutputTokens?: number;
  basePrompt?: string;
  additionalPrompt?: string;
  history?: HybridContextMessage[];
}

interface HybridApiResult {
  status: 'ok' | 'error';
  answer?: string;
  evidenceCount?: number;
  queryCount?: number;
  error?: string;
  code?: string;
}

interface DirectorsCodexApi {
  accountRead(refreshToken?: boolean): Promise<unknown>;
  accountRateLimitsRead(): Promise<unknown>;
  loginWithChatGpt(): Promise<unknown>;
  loginWithApiKey(apiKey: string): Promise<unknown>;
  logout(): Promise<unknown>;
  listModels(): Promise<unknown>;
  listThreads(cwd?: string): Promise<unknown>;
  startThread(input: unknown): Promise<unknown>;
  startTurn(input: unknown): Promise<unknown>;
  interruptTurn(threadId: string, turnId: string): Promise<unknown>;
  respondToServerRequest(response: unknown): Promise<unknown>;
  hybridStatus(): Promise<HybridApiStatus>;
  saveHybridApiKey(apiKey: string): Promise<HybridApiStatus>;
  clearHybridApiKey(): Promise<HybridApiStatus>;
  completeHybrid(input: HybridApiRequestInput): Promise<HybridApiResult>;
  cancelHybrid(requestId: string): Promise<{ ok: boolean }>;
  getCurrentDirectory(): Promise<unknown>;
  chooseDirectory(): Promise<unknown>;
  readDirectory(directoryPath: string): Promise<unknown>;
  readSource(input: { cwd: string; citation: string }): Promise<unknown>;
  openSource(input: { cwd: string; citation: string }): Promise<{ ok: boolean }>;
  listSkills(): Promise<unknown>;
  saveEmbeddedSkill(skillFile: string, content: string): Promise<unknown>;
  embeddedTerminal: EmbeddedTerminalApi;
  setWidgetMode(enabled: boolean): Promise<unknown>;
  setWidgetCollapsed(collapsed: boolean): Promise<unknown>;
  setWidgetClickThrough(enabled: boolean): Promise<unknown>;
  windowAction(action: 'minimize' | 'maximize' | 'close'): Promise<unknown>;
  moveWindowBy(deltaX: number, deltaY: number): void;
  filePathForDroppedFile(file: File): string;
  storeRead(key: string): Promise<unknown>;
  storeWrite(key: string, data: unknown): Promise<unknown>;
  onEvent(handler: (event: unknown) => void): () => void;
}

interface Window {
  directorsCodex?: DirectorsCodexApi;
}
