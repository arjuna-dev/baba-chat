<template>
  <section class="codex-terminal" aria-labelledby="codex-terminal-title">
    <header class="codex-terminal__header">
      <div>
        <h2 id="codex-terminal-title" class="codex-terminal__eyebrow">Interactive terminal</h2>
      </div>

      <div class="codex-terminal__actions">
        <button
          class="codex-terminal__button codex-terminal__button--quiet"
          type="button"
          :disabled="!hasOutput"
          aria-label="Clear terminal output"
          @click="clearTerminal"
        >
          Clear
        </button>
        <button
          v-if="isActive"
          class="codex-terminal__button codex-terminal__button--danger"
          type="button"
          :disabled="isStopping"
          aria-label="Stop terminal"
          @click="stopTerminal"
        >
          {{ isStopping ? 'Stopping...' : 'Stop' }}
        </button>
        <button
          v-else
          class="codex-terminal__button codex-terminal__button--primary"
          type="button"
          :disabled="!canStart"
          aria-label="Start interactive terminal"
          @click="startTerminal"
        >
          {{
            terminalState === 'error' || terminalState === 'exited' ? 'Restart' : 'Start terminal'
          }}
        </button>
      </div>
    </header>

    <p v-if="!cwd" class="codex-terminal__notice" role="note">
      Select a working directory before starting the terminal.
    </p>
    <p
      v-else-if="availability && !availability.available"
      class="codex-terminal__notice"
      role="note"
    >
      {{ availability.message }}
    </p>

    <div
      ref="terminalContainer"
      class="codex-terminal__screen"
      role="application"
      aria-label="Interactive terminal"
      tabindex="0"
      @click="focusTerminal"
    ></div>

    <p v-if="errorText" class="codex-terminal__error" role="alert">{{ errorText }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';

interface Props {
  cwd?: string | null;
  initialCols?: number;
  initialRows?: number;
  initialTranscript?: string;
  resumeSessionId?: string | null;
  autoStart?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  cwd: null,
  initialCols: 100,
  initialRows: 30,
  initialTranscript: '',
  resumeSessionId: null,
  autoStart: false,
});

const emit = defineEmits<{
  (event: 'started', terminalId: string): void;
  (event: 'stopped'): void;
  (event: 'status', status: EmbeddedTerminalStatusPayload): void;
  (event: 'input', data: string): void;
  (event: 'output', data: string): void;
  (event: 'cleared'): void;
}>();

const terminalApi = window.directorsCodex?.embeddedTerminal;
const terminalContainer = ref<HTMLDivElement | null>(null);
const availability = ref<EmbeddedTerminalAvailabilityPayload | null>(null);
const terminalState = ref<'idle' | EmbeddedTerminalState>('idle');
const terminalId = ref<string | null>(null);
const errorText = ref('');
const hasOutput = ref(false);
const isStopping = ref(false);

let terminal: Terminal | null = null;
let fitAddon: FitAddon | null = null;
let resizeObserver: ResizeObserver | null = null;
let resizeTimer: ReturnType<typeof setTimeout> | null = null;
let unsubscribeOutput: (() => void) | undefined;
let unsubscribeStatus: (() => void) | undefined;
let disposed = false;
let startGeneration = 0;
let earlyOutput: EmbeddedTerminalOutputPayload[] = [];

const isActive = computed(
  () => terminalState.value === 'starting' || terminalState.value === 'running',
);

const canStart = computed(
  () =>
    Boolean(props.cwd) &&
    Boolean(terminalApi) &&
    availability.value?.available !== false &&
    !isActive.value,
);

onMounted(async () => {
  setupTerminal();
  if (props.initialTranscript) {
    writeOutput(props.initialTranscript);
  }
  unsubscribeOutput = terminalApi?.onOutput(handleOutput);
  unsubscribeStatus = terminalApi?.onStatus(handleStatus);
  await checkAvailability();
  if (props.autoStart) {
    await startTerminal();
  }
});

onUnmounted(() => {
  disposed = true;
  startGeneration += 1;

  if (resizeTimer) {
    clearTimeout(resizeTimer);
  }
  resizeObserver?.disconnect();
  unsubscribeOutput?.();
  unsubscribeStatus?.();

  const activeTerminalId = terminalId.value;
  if (activeTerminalId && terminalApi) {
    void terminalApi.kill(activeTerminalId).catch(() => undefined);
  }

  terminal?.dispose();
});

watch(
  () => props.cwd,
  (nextCwd, previousCwd) => {
    if (nextCwd === previousCwd) {
      return;
    }

    startGeneration += 1;
    if (terminalId.value && terminalApi) {
      void stopTerminal();
    }
    errorText.value = '';
  },
);

watch(
  () => props.initialTranscript,
  (nextTranscript, previousTranscript) => {
    if (nextTranscript === previousTranscript || terminalId.value || !terminal || !nextTranscript) {
      return;
    }

    terminal.reset();
    writeOutput(nextTranscript);
  },
);

async function checkAvailability() {
  if (!terminalApi) {
    return;
  }

  try {
    const result = await terminalApi.status();
    if (isAvailability(result)) {
      availability.value = result;
    }
  } catch (error: unknown) {
    availability.value = {
      available: false,
      message: errorMessage(error),
    };
  }
}

function setupTerminal() {
  const container = terminalContainer.value;
  if (!container) {
    return;
  }

  Terminal.strings.promptLabel = 'Interactive terminal input';
  terminal = new Terminal({
    cursorBlink: true,
    cursorStyle: 'bar',
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
    fontSize: 13,
    scrollback: 10_000,
    screenReaderMode: true,
    theme: {
      background: '#191612',
      foreground: '#f4ecdf',
      cursor: '#d58a50',
      selectionBackground: '#63351f',
    },
  });
  fitAddon = new FitAddon();
  terminal.loadAddon(fitAddon);
  terminal.open(container);
  terminal.textarea?.setAttribute('aria-label', 'Interactive terminal input');

  terminal.onData((data) => {
    const activeTerminalId = terminalId.value;
    if (!activeTerminalId || terminalState.value !== 'running' || !terminalApi) {
      return;
    }

    emit('input', data);
    void terminalApi.input(activeTerminalId, data).catch((error: unknown) => {
      errorText.value = errorMessage(error);
    });
  });

  resizeObserver = new ResizeObserver(scheduleResize);
  resizeObserver.observe(container);
  fitTerminal();
}

function scheduleResize() {
  if (resizeTimer) {
    clearTimeout(resizeTimer);
  }

  resizeTimer = setTimeout(() => {
    resizeTimer = null;
    fitTerminal();

    const activeTerminalId = terminalId.value;
    if (!activeTerminalId || terminalState.value !== 'running' || !terminalApi || !terminal) {
      return;
    }

    void terminalApi
      .resize(activeTerminalId, terminal.cols, terminal.rows)
      .catch((error: unknown) => {
        errorText.value = errorMessage(error);
      });
  }, 80);
}

function fitTerminal() {
  if (!terminal || !fitAddon || !terminalContainer.value) {
    return;
  }

  if (terminalContainer.value.clientWidth <= 0 || terminalContainer.value.clientHeight <= 0) {
    return;
  }

  try {
    fitAddon.fit();
  } catch (error: unknown) {
    errorText.value = errorMessage(error);
  }
}

async function startTerminal() {
  if (!canStart.value || !props.cwd || !terminalApi) {
    return;
  }

  const generation = ++startGeneration;
  const preserveTranscript = Boolean(props.initialTranscript && !props.resumeSessionId);
  errorText.value = '';
  terminalId.value = null;
  terminalState.value = 'starting';
  if (!preserveTranscript) {
    hasOutput.value = false;
    terminal?.reset();
  }
  earlyOutput = [];
  await nextTick();
  fitTerminal();

  try {
    const result = await terminalApi.create({
      cwd: props.cwd,
      cols: terminal?.cols || safeDimension(props.initialCols, 2, 500, 100),
      rows: terminal?.rows || safeDimension(props.initialRows, 1, 200, 30),
      ...(props.resumeSessionId ? { resumeSessionId: props.resumeSessionId } : {}),
    });

    if (disposed || generation !== startGeneration) {
      await terminalApi.kill(result.terminalId).catch(() => undefined);
      return;
    }

    terminalId.value = result.terminalId;
    terminalState.value = result.state;
    emit('started', result.terminalId);
    for (const output of earlyOutput) {
      if (output.terminalId === result.terminalId) {
        writeOutput(output.data);
        emit('output', output.data);
      }
    }
    earlyOutput = [];
    terminal?.focus();
  } catch (error: unknown) {
    if (disposed || generation !== startGeneration) {
      return;
    }

    terminalState.value = 'error';
    errorText.value = errorMessage(error);
  }
}

async function stopTerminal() {
  const activeTerminalId = terminalId.value;
  startGeneration += 1;
  if (!activeTerminalId || !terminalApi) {
    terminalState.value = 'idle';
    return;
  }

  isStopping.value = true;
  errorText.value = '';
  try {
    const result = await terminalApi.kill(activeTerminalId);
    terminalState.value = result.state;
    emit('stopped');
  } catch (error: unknown) {
    errorText.value = errorMessage(error);
  } finally {
    isStopping.value = false;
  }
}

function clearTerminal() {
  terminal?.reset();
  hasOutput.value = false;
  emit('cleared');
}

function focusTerminal() {
  terminal?.focus();
}

function handleOutput(output: EmbeddedTerminalOutputPayload) {
  if (terminalId.value === output.terminalId) {
    writeOutput(output.data);
    emit('output', output.data);
    return;
  }

  if (terminalState.value === 'starting' && !terminalId.value) {
    earlyOutput.push(output);
  }
}

function handleStatus(status: EmbeddedTerminalStatusPayload) {
  if (terminalId.value !== status.terminalId) {
    return;
  }

  terminalState.value = status.state;
  if (status.message) {
    errorText.value = status.message;
  }
  emit('status', status);
}

function writeOutput(data: string) {
  terminal?.write(data);
  hasOutput.value = true;
}

function isAvailability(
  value: EmbeddedTerminalStatusPayload | EmbeddedTerminalAvailabilityPayload,
): value is EmbeddedTerminalAvailabilityPayload {
  return 'available' in value;
}

function safeDimension(value: number, minimum: number, maximum: number, fallback: number): number {
  if (!Number.isSafeInteger(value)) {
    return fallback;
  }

  return Math.min(Math.max(value, minimum), maximum);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
</script>

<style scoped>
.codex-terminal {
  box-sizing: border-box;
  display: flex;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem;
  border: 1px solid rgba(214, 188, 153, 0.28);
  border-radius: 0.45rem;
  background: #221d18;
  color: #f7efe3;
}

.codex-terminal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.codex-terminal__eyebrow {
  margin: 0;
  color: #d58a50;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.codex-terminal__notice,
.codex-terminal__error {
  margin: 0;
  color: #d4c7b6;
  font-size: 0.78rem;
  line-height: 1.45;
}

.codex-terminal__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.35rem;
}

.codex-terminal__button {
  border: 1px solid transparent;
  border-radius: 0.4rem;
  cursor: pointer;
  font: inherit;
  font-size: 0.72rem;
  font-weight: 700;
  transition:
    background 120ms ease,
    border-color 120ms ease,
    opacity 120ms ease;
}

.codex-terminal__button {
  min-height: 28px;
  padding: 0.24rem 0.58rem;
}

.codex-terminal__button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.codex-terminal__button--primary {
  border-color: #c57438;
  background: #a85e2d;
  color: white;
}

.codex-terminal__button--primary:hover:not(:disabled) {
  background: #b96c34;
}

.codex-terminal__button--danger {
  border-color: rgba(248, 113, 113, 0.5);
  background: rgba(127, 29, 29, 0.65);
  color: #fecaca;
}

.codex-terminal__button--quiet {
  border-color: rgba(214, 188, 153, 0.3);
  background: #302821;
  color: #d4c7b6;
}

.codex-terminal__button--quiet:hover:not(:disabled) {
  border-color: rgba(213, 138, 80, 0.65);
  color: white;
}

.codex-terminal__screen {
  position: relative;
  min-height: 5rem;
  flex: 1 1 auto;
  overflow: hidden;
  border: 1px solid rgba(214, 188, 153, 0.22);
  border-radius: 0.7rem;
  outline: none;
  background: #191612;
  box-shadow: inset 0 0 0 1px rgba(10, 8, 6, 0.8);
}

.codex-terminal__screen:focus-visible {
  border-color: #d58a50;
  box-shadow: 0 0 0 3px rgba(197, 116, 56, 0.22);
}

.codex-terminal__screen :deep(.xterm) {
  height: 100%;
  padding: 0.55rem;
}

.codex-terminal__screen :deep(.xterm-viewport) {
  background: #191612 !important;
}

.codex-terminal__notice {
  padding: 0.6rem 0.7rem;
  border-left: 3px solid #d58a50;
  background: rgba(197, 116, 56, 0.12);
}

.codex-terminal__error {
  color: #fecaca;
}

@media (max-width: 600px) {
  .codex-terminal__header {
    align-items: flex-start;
    flex-direction: column;
  }

  .codex-terminal__actions {
    justify-content: flex-start;
  }
}
</style>
