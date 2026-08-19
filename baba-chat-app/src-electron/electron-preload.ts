import { contextBridge, ipcRenderer, webUtils } from 'electron';

type CodexEventHandler = (event: unknown) => void;
type EmbeddedTerminalOutputHandler = (event: unknown) => void;
type EmbeddedTerminalStatusHandler = (event: unknown) => void;

contextBridge.exposeInMainWorld('directorsCodex', {
  accountRead: (refreshToken?: boolean) => ipcRenderer.invoke('codex:account-read', refreshToken),
  accountRateLimitsRead: () => ipcRenderer.invoke('codex:account-rate-limits-read'),
  loginWithChatGpt: () => ipcRenderer.invoke('codex:login-chatgpt'),
  loginWithApiKey: (apiKey: string) => ipcRenderer.invoke('codex:login-api-key', apiKey),
  logout: () => ipcRenderer.invoke('codex:logout'),
  listModels: () => ipcRenderer.invoke('codex:model-list'),
  listThreads: (cwd?: string) => ipcRenderer.invoke('codex:thread-list', cwd),
  startThread: (input: unknown) => ipcRenderer.invoke('codex:thread-start', input),
  startTurn: (input: unknown) => ipcRenderer.invoke('codex:turn-start', input),
  interruptTurn: (threadId: string, turnId: string) =>
    ipcRenderer.invoke('codex:turn-interrupt', threadId, turnId),
  respondToServerRequest: (response: unknown) =>
    ipcRenderer.invoke('codex:server-request-respond', response),
  hybridStatus: () => ipcRenderer.invoke('hybrid:status'),
  saveHybridApiKey: (apiKey: string) => ipcRenderer.invoke('hybrid:api-key-save', apiKey),
  clearHybridApiKey: () => ipcRenderer.invoke('hybrid:api-key-clear'),
  completeHybrid: (input: unknown) => ipcRenderer.invoke('hybrid:complete', input),
  cancelHybrid: (requestId: string) => ipcRenderer.invoke('hybrid:cancel', requestId),
  getCurrentDirectory: () => ipcRenderer.invoke('app:get-current-directory'),
  chooseDirectory: () => ipcRenderer.invoke('app:choose-directory'),
  readDirectory: (directoryPath: string) => ipcRenderer.invoke('app:read-directory', directoryPath),
  readSource: (input: unknown) => ipcRenderer.invoke('app:read-source', input),
  openSource: (input: unknown) => ipcRenderer.invoke('app:open-source', input),
  listSkills: () => ipcRenderer.invoke('app:list-skills'),
  saveEmbeddedSkill: (skillFile: string, content: string) =>
    ipcRenderer.invoke('app:save-embedded-skill', skillFile, content),
  embeddedTerminal: {
    create: (input: unknown) => ipcRenderer.invoke('embedded-terminal:create', input),
    input: (terminalId: string, data: string) =>
      ipcRenderer.invoke('embedded-terminal:input', terminalId, data),
    resize: (terminalId: string, cols: number, rows: number) =>
      ipcRenderer.invoke('embedded-terminal:resize', terminalId, cols, rows),
    kill: (terminalId: string) => ipcRenderer.invoke('embedded-terminal:kill', terminalId),
    status: (terminalId?: string) => ipcRenderer.invoke('embedded-terminal:status', terminalId),
    onOutput: (handler: EmbeddedTerminalOutputHandler) => {
      const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => {
        handler(payload);
      };

      ipcRenderer.on('embedded-terminal:output', listener);
      return () => {
        ipcRenderer.removeListener('embedded-terminal:output', listener);
      };
    },
    onStatus: (handler: EmbeddedTerminalStatusHandler) => {
      const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => {
        handler(payload);
      };

      ipcRenderer.on('embedded-terminal:status', listener);
      return () => {
        ipcRenderer.removeListener('embedded-terminal:status', listener);
      };
    },
  },
  setWidgetMode: (enabled: boolean) => ipcRenderer.invoke('app:set-widget-mode', enabled),
  setWidgetCollapsed: (collapsed: boolean) =>
    ipcRenderer.invoke('app:set-widget-collapsed', collapsed),
  setWidgetClickThrough: (enabled: boolean) =>
    ipcRenderer.invoke('app:set-widget-click-through', enabled),
  windowAction: (action: string) => ipcRenderer.invoke('app:window-action', action),
  moveWindowBy: (deltaX: number, deltaY: number) =>
    ipcRenderer.send('app:move-window-by', deltaX, deltaY),
  filePathForDroppedFile: (file: File) => webUtils.getPathForFile(file),
  storeRead: (key: string) => ipcRenderer.invoke('app:store-read', key),
  storeWrite: (key: string, data: unknown) => ipcRenderer.invoke('app:store-write', key, data),
  onEvent: (handler: CodexEventHandler) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => {
      handler(payload);
    };

    ipcRenderer.on('codex:event', listener);
    return () => {
      ipcRenderer.removeListener('codex:event', listener);
    };
  },
});
