<template>
  <div
    class="app-shell"
    :class="{
      'app-shell--drawer-hidden': drawerHidden,
      'app-shell--nav-resizing': isNavResizing,
      'app-shell--widget': widgetMode,
      'app-shell--widget-collapsed': widgetMode && widgetCollapsed,
    }"
    :style="appShellStyle"
  >
    <header class="top-bar">
      <button
        class="menu-toggle"
        type="button"
        :aria-label="drawerHidden ? 'Show drawer' : 'Hide drawer'"
        @click="drawerHidden = !drawerHidden"
      >
        <Menu :size="20" />
      </button>
      <div class="top-brand-mark" aria-hidden="true">B</div>
      <div class="top-title-group">
        <div class="top-title">Baba Chat</div>
        <div class="top-subtitle">
          Conversational archive assistant for Baba's discourses, stories, and related books
        </div>
      </div>
      <div class="window-controls" aria-label="Window controls">
        <button
          class="window-control"
          type="button"
          aria-label="Minimize window"
          @click="windowAction('minimize')"
        >
          <Minus :size="15" />
        </button>
        <button
          class="window-control"
          type="button"
          aria-label="Maximize window"
          @click="windowAction('maximize')"
        >
          <Maximize2 :size="14" />
        </button>
        <button
          class="window-control window-control--close"
          type="button"
          aria-label="Close window"
          @click="windowAction('close')"
        >
          <X :size="15" />
        </button>
      </div>
    </header>

    <nav class="nav-rail" aria-label="Primary" :aria-hidden="drawerHidden">
      <div class="brand-lockup">
        <span class="brand-lockup__name">Baba Chat</span>
        <span class="brand-lockup__rule" aria-hidden="true"></span>
        <span class="brand-lockup__caption">Discourses &amp; stories</span>
      </div>
      <button
        class="nav-item"
        :class="{ 'nav-item--active': activeView === 'chat' }"
        type="button"
        aria-label="Open chat"
        @click="activeView = 'chat'"
      >
        <MessageCircle :size="20" />
        <span>Chat</span>
      </button>
      <button
        class="nav-item"
        :class="{ 'nav-item--active': activeView === 'settings' }"
        type="button"
        aria-label="Open settings"
        @click="activeView = 'settings'"
      >
        <Settings :size="20" />
        <span>Settings</span>
      </button>
      <button
        class="nav-item"
        :class="{ 'nav-item--active': activeView === 'skills' }"
        type="button"
        aria-label="Open skills"
        @click="activeView = 'skills'"
      >
        <Wrench :size="20" />
        <span>SKILLS</span>
      </button>
      <button
        class="nav-item"
        :class="{ 'nav-item--active': activeView === 'about' }"
        type="button"
        aria-label="Open About"
        @click="activeView = 'about'"
      >
        <Info :size="20" />
        <span>About</span>
      </button>

      <section class="drawer-section">
        <button
          class="drawer-dropdown nav-item"
          type="button"
          :aria-expanded="conversationsDrawerOpen ? 'true' : 'false'"
          @click="conversationsDrawerOpen = !conversationsDrawerOpen"
        >
          <span class="drawer-dropdown__label">
            <Clock :size="18" />
            <span>Conversations</span>
          </span>
          <ChevronUp v-if="conversationsDrawerOpen" :size="16" />
          <ChevronDown v-else :size="16" />
        </button>

        <div
          v-if="conversationsDrawerOpen"
          class="drawer-dropdown-panel drawer-dropdown-panel--plain"
        >
          <p v-if="conversationHistory.length === 0" class="empty-directory">
            No saved conversations yet.
          </p>
          <ul v-else class="conversation-list">
            <li
              v-for="conversation in conversationHistory"
              :key="conversation.id"
              class="conversation-list-item"
              :class="{ 'conversation-list-item--pinned': conversation.pinned }"
            >
              <button
                class="conversation-item"
                type="button"
                @click="restoreConversation(conversation)"
              >
                {{ conversation.mode === 'terminal' ? 'Terminal: ' : '' }}{{ conversation.title }}
              </button>
              <div class="conversation-item-actions">
                <button
                  class="conversation-item-action"
                  :class="{ 'conversation-item-action--active': conversation.pinned }"
                  type="button"
                  :aria-pressed="conversation.pinned ? 'true' : 'false'"
                  :aria-label="conversation.pinned ? 'Unpin conversation' : 'Pin conversation'"
                  :title="conversation.pinned ? 'Unpin conversation' : 'Pin conversation'"
                  @click.stop="toggleConversationPinned(conversation)"
                >
                  <Pin :size="14" />
                </button>
                <button
                  class="conversation-item-action conversation-item-action--danger"
                  type="button"
                  aria-label="Delete conversation"
                  title="Delete conversation"
                  @click.stop="deleteConversation(conversation)"
                >
                  <Trash2 :size="14" />
                </button>
              </div>
            </li>
          </ul>
        </div>
      </section>

      <div
        class="nav-resize-handle"
        role="separator"
        aria-label="Resize navigation bar"
        aria-orientation="vertical"
        :aria-valuemin="navWidthMin"
        :aria-valuemax="navWidthMax"
        :aria-valuenow="navWidth"
        tabindex="0"
        @pointerdown="handleNavResizeStart"
        @keydown="handleNavResizeKeydown"
      ></div>
    </nav>

    <main
      v-if="activeView === 'chat' && !widgetCollapsed"
      class="chat-area"
      :class="{ 'chat-area--terminal': terminalMode }"
    >
      <div class="chat-overlay-actions">
        <button
          class="terminal-mode-control"
          :class="{ 'terminal-mode-control--active': terminalMode }"
          type="button"
          :aria-pressed="terminalMode"
          aria-controls="terminal-placeholder"
          @click="toggleTerminalMode"
        >
          <span class="toggle-switch" :class="{ 'toggle-switch--active': terminalMode }" aria-hidden="true">
            <span class="toggle-switch__thumb"></span>
          </span>
          <span>Terminal mode</span>
        </button>
        <button
          v-if="!widgetMode"
          class="widget-mode-toggle"
          type="button"
          aria-label="Enter widget mode"
          @click="setWidgetMode(true)"
        >
          <Bot :size="18" />
        </button>
        <button
          class="chat-overlay-button"
          type="button"
          aria-label="Start new conversation"
          @click="startNewConversation"
        >
          <Plus :size="18" />
        </button>
      </div>
      <header class="chat-header">
        <div class="chat-header-copy">
          <h1>Baba Chat</h1>
        </div>
        <div class="chat-header-controls">
          <fieldset class="scope-picker">
            <legend>Search in</legend>
            <div class="scope-picker__options" role="group" aria-label="Source scope">
              <button
                v-for="option in sourceScopeOptions"
                :key="option.value"
                class="scope-option"
                :class="{ 'scope-option--active': isSourceScopeSelected(option.value) }"
                type="button"
                :data-source-scope="option.value"
                :aria-pressed="isSourceScopeSelected(option.value)"
                @click="toggleSourceScope(option.value)"
                @keydown="handleScopeKeydown($event, option.value)"
              >
                <span
                  class="toggle-switch scope-option__toggle"
                  :class="{ 'toggle-switch--active': isSourceScopeSelected(option.value) }"
                  aria-hidden="true"
                >
                  <span class="toggle-switch__thumb"></span>
                </span>
                <span>{{ option.label }}</span>
                <span
                  v-if="option.description"
                  class="info-button scope-option__info"
                  :data-tooltip="option.description"
                  :aria-label="`${option.label}: ${option.description}`"
                  :title="option.description"
                  role="img"
                  tabindex="0"
                  @click.stop
                  @keydown.stop="handleScopeInfoKeydown"
                >
                  <Info :size="12" aria-hidden="true" />
                </span>
              </button>
            </div>
          </fieldset>
        </div>
      </header>
      <div v-if="terminalMode" id="terminal-placeholder" class="terminal-panel">
        <CodexTerminal
          :cwd="directory?.path ?? null"
          :initial-transcript="terminalTranscript"
          :resume-session-id="terminalSessionId"
          :auto-start="terminalAutoStart"
          @cleared="handleTerminalCleared"
          @input="handleTerminalInput"
          @output="handleTerminalOutput"
          @started="handleTerminalStarted"
          @status="handleTerminalStatus"
          @stopped="handleTerminalStopped"
        />
      </div>
      <div
        v-else
        ref="messageList"
        class="messages"
        tabindex="0"
        aria-label="Conversation messages"
        @scroll="handleMessageScroll"
        @wheel="handleMessageWheel"
        @pointerdown="handleMessagePointerDown"
        @touchmove="handleMessageTouchMove"
        @keydown="handleMessageKeydown"
      >
        <div v-if="messages.length === 0" class="empty-state">
          <div class="empty-state__seal" aria-hidden="true">B</div>
          <p class="empty-state__description">Chat with Baba's discourses and stories, or choose another source category</p>
        </div>

        <article
          v-for="message in visibleMessages"
          :key="message.id"
          class="message"
          :class="`message--${message.role}`"
        >
          <div class="message-meta">
            <span class="message-role">{{ messageRoleLabel(message.role) }}</span>
          </div>
          <div class="message-body">
            <template v-for="part in messageParts(message.text)" :key="part.key">
              <template v-if="part.kind === 'text'">
                <template v-for="inlinePart in inlineMessageParts(part.text, part.key)" :key="inlinePart.key">
                  <strong v-if="inlinePart.kind === 'bold'">{{ inlinePart.text }}</strong>
                  <em v-else-if="inlinePart.kind === 'italic'">{{ inlinePart.text }}</em>
                  <span v-else class="message-text">{{ inlinePart.text }}</span>
                </template>
              </template>
              <button
                v-else
                class="source-link"
                type="button"
                :title="`Open ${part.citation.label}`"
                @click="openSource(part.citation.citation)"
              >
                <BookOpen :size="13" aria-hidden="true" />
                <span>{{ part.citation.label }}</span>
              </button>
            </template>
          </div>
        </article>

        <div v-if="showThinking" class="thinking" aria-live="polite">
          <span
            v-for="(letter, index) in thinkingLetters"
            :key="`${letter}-${index}`"
            ref="thinkingLetterRefs"
          >
            {{ letter }}
          </span>
        </div>
      </div>

      <div v-if="pendingRequests.length > 0" class="approval-strip">
        <article
          v-for="request in pendingRequests"
          :key="String(request.requestId)"
          class="approval"
        >
          <div>
            <strong>{{ request.title }}</strong>
            <p>{{ request.detail }}</p>
          </div>
          <div class="approval-actions">
            <Button size="sm" @click="answerRequest(request.requestId, 'accept')"> Approve </Button>
            <Button
              variant="destructive"
              size="sm"
              @click="answerRequest(request.requestId, 'decline')"
            >
              Decline
            </Button>
          </div>
        </article>
      </div>

      <p v-if="errorText" class="error-text" role="alert">{{ errorText }}</p>

      <form
        v-if="!terminalMode"
        class="composer"
        :class="{
          'composer--dragging': isDraggingFile,
          'composer--source-blocked': sourceScopeEmpty,
        }"
        @submit.prevent="sendPrompt"
        @dragenter.prevent="isDraggingFile = true"
        @dragover.prevent="isDraggingFile = true"
        @dragleave.prevent="isDraggingFile = false"
        @drop.prevent="handleFileDrop"
      >
        <div class="composer-input-wrap">
          <div v-if="attachedFiles.length > 0" class="file-chips">
            <span
              v-for="file in attachedFiles"
              :key="file.path"
              class="file-chip"
              :title="file.path"
            >
              {{ file.name }}
            </span>
          </div>
          <div class="composer-meta">
            <span v-if="sourceScopeEmpty" class="composer-meta__warning" role="status">
              Select at least one source to use chat.
            </span>
            <span v-else>Searching <strong>{{ scopeLabel(sourceScope) }}</strong></span>
            <span class="composer-meta__hint">
              {{ sourceScopeEmpty ? 'Toggle on a source above to continue' : 'Enter to send · Drop files to attach' }}
            </span>
          </div>
          <textarea
            v-model="prompt"
            class="composer-input"
            rows="1"
            :placeholder="
              sourceScopeEmpty
                ? 'Select a source above to start chatting...'
                : 'Ask Baba Chat about a passage...'
            "
            :disabled="turnActive || sourceScopeEmpty"
            @keydown.enter.exact.prevent="sendPrompt"
          />
        </div>
        <Button
          class="send-button"
          size="icon"
          :variant="turnActive ? 'destructive' : 'default'"
          :disabled="sendButtonDisabled"
          :aria-label="
            sourceScopeEmpty
              ? 'Select a source to send a message'
              : turnActive
                ? 'Stop Codex'
                : 'Send message'
          "
          @click="handleComposerAction"
        >
          <Square v-if="turnActive" :size="16" />
          <ArrowUp v-else :size="18" />
        </Button>
      </form>
    </main>

    <main v-else-if="activeView === 'settings' && !widgetCollapsed" class="settings-area">
      <section class="settings-panel">
        <div class="settings-card">
          <div class="settings-card-header">
            <h2>Settings</h2>
            <p class="settings-help">
              Choose the harness mode and conversation defaults for new turns.
            </p>
          </div>
          <div class="settings-field">
            <label class="label" for="chat-mode-settings">Runtime mode</label>
            <select id="chat-mode-settings" v-model="chatMode" class="select-control">
              <option value="codex">Codex native</option>
              <option value="api">API</option>
            </select>
            <p class="settings-help">
              API mode gives the configured API model the Baba research skill. The model requests
              local search tools when needed, and the app returns its full answer to this chat.
            </p>
          </div>
          <div v-if="chatMode === 'api'" class="hybrid-settings">
            <div class="settings-field">
              <label class="label" for="hybrid-provider-settings">API provider</label>
              <select
                id="hybrid-provider-settings"
                v-model="hybridProvider"
                class="select-control"
                @change="handleHybridProviderChange"
              >
                <option value="deepseek">DeepSeek</option>
                <option value="openai-compatible">OpenAI-compatible</option>
              </select>
            </div>
            <div class="settings-field">
              <label class="label" for="hybrid-model-settings">API model</label>
              <input
                id="hybrid-model-settings"
                v-model="hybridApiModel"
                class="text-control"
                type="text"
                autocomplete="off"
                spellcheck="false"
                placeholder="deepseek-v4-flash"
              />
            </div>
            <div class="settings-field">
              <label class="label" for="hybrid-base-url-settings">API base URL</label>
              <input
                id="hybrid-base-url-settings"
                v-model="hybridBaseUrl"
                class="text-control"
                type="url"
                autocomplete="off"
                spellcheck="false"
                placeholder="https://api.deepseek.com"
              />
            </div>
            <div class="settings-field">
              <label class="label" for="hybrid-output-tokens-settings">Max API output tokens</label>
              <input
                id="hybrid-output-tokens-settings"
                v-model.number="hybridMaxOutputTokens"
                class="text-control"
                type="number"
                min="256"
                max="2000"
                step="1"
              />
              <p class="settings-help">
                The default is 1100. Lower it to reduce delegated output cost.
              </p>
            </div>
            <div class="settings-field">
              <label class="label" for="hybrid-api-key-settings">API key</label>
              <input
                id="hybrid-api-key-settings"
                :value="hybridApiKeyDraft || (hybridConfigured ? hybridApiKeyMask : '')"
                class="text-control"
                type="password"
                autocomplete="new-password"
                placeholder="Paste a provider API key"
                @focus="selectHybridApiKeyCue"
                @input="handleHybridApiKeyInput"
              />
              <p class="settings-help">
                Stored in the operating system secure storage. Codex never receives this key.
              </p>
              <div class="settings-actions">
                <Button
                  :disabled="hybridSaving || !hybridApiKeyDraft.trim()"
                  @click="saveHybridApiKey"
                >
                  <Loader2 v-if="hybridSaving" class="spin" :size="15" />
                  Save API key
                </Button>
                <Button variant="secondary" :disabled="hybridSaving" @click="clearHybridApiKey">
                  Clear saved key
                </Button>
              </div>
              <p v-if="hybridStatusLoading" class="settings-status">Checking API key...</p>
              <p v-else-if="hybridConfigured" class="settings-status settings-status--success">
                API key configured
              </p>
              <p v-else class="settings-status">API key not configured</p>
            </div>
          </div>
          <template v-if="chatMode === 'codex'">
            <div class="settings-field">
              <label class="label" for="model-select-settings">Model</label>
              <select
                id="model-select-settings"
                v-model="selectedModel"
                class="select-control"
                :disabled="modelsLoading || modelOptions.length === 0"
              >
                <option v-if="modelsLoading" value="">Loading models...</option>
                <option v-else-if="modelOptions.length === 0" value="">Default model</option>
                <option v-for="model in modelOptions" :key="model.value" :value="model.value">
                  {{ model.label }}
                </option>
              </select>
            </div>
            <div class="settings-field">
              <label class="label" for="reasoning-effort-settings">Thinking effort</label>
              <select
                id="reasoning-effort-settings"
                v-model="reasoningEffort"
                class="select-control"
                :disabled="modelsLoading || reasoningEffortOptions.length === 0"
                aria-describedby="reasoning-effort-help"
              >
                <option
                  v-for="option in reasoningEffortOptions"
                  :key="option.value"
                  :value="option.value"
                >
                  {{ option.label }}
                </option>
              </select>
              <p id="reasoning-effort-help" class="settings-help">
                {{ reasoningEffortHelp }}
              </p>
            </div>
          </template>
        </div>

        <div class="settings-card">
          <div class="settings-card-header">
            <h3>Conversation prompts</h3>
            <p class="settings-help">
              Add guidance for new Baba Chat conversations. Your extra prompt is layered after the
              base prompt and is not repeated on every message.
            </p>
          </div>
          <div class="settings-field">
            <label class="label" for="additional-prompt">Additional Prompt</label>
            <textarea
              id="additional-prompt"
              v-model="additionalPrompt"
              class="settings-textarea"
              rows="5"
              maxlength="8000"
              placeholder="Add extra guidance for Baba Chat, such as the tone or focus you prefer..."
            />
            <p class="settings-help">
              This is your authored extra guidance. It is added after the Baba Chat Base Prompt when
              a new thread begins.
            </p>
          </div>
          <details class="advanced-section">
            <summary>
              <span>Advanced</span>
              <span class="advanced-section__summary">Baba Chat Base Prompt</span>
            </summary>
            <div class="advanced-section__body">
              <div class="settings-field">
                <label class="label" for="base-prompt">Baba Chat Base Prompt</label>
                <textarea
                  id="base-prompt"
                  v-model="basePrompt"
                  class="settings-textarea"
                  rows="8"
                  maxlength="12000"
                  placeholder="Add a default Baba Chat conversation directive..."
                />
                <p class="settings-help">
                  The base prompt is included once at the start of each new conversation. Keep it
                  focused on how Baba Chat should work.
                </p>
              </div>
              <div class="settings-actions">
                <Button variant="secondary" @click="resetBasePrompt">
                  Reset Baba Chat Base Prompt
                </Button>
              </div>
            </div>
          </details>
          <p v-if="basePromptSaveState === 'saving'" class="settings-status">Saving locally...</p>
          <p
            v-else-if="basePromptSaveState === 'saved'"
            class="settings-status settings-status--success"
          >
            Saved locally
          </p>
        </div>
      </section>

      <section class="settings-panel">
        <div class="settings-card">
          <div class="settings-card-header">
            <h3>Account</h3>
            <p class="settings-help">
              Refresh the Codex CLI account state after signing in, signing out, or switching OpenAI
              accounts outside this app.
            </p>
          </div>
          <dl class="account-details">
            <div>
              <dt>Provider</dt>
              <dd>{{ accountDetails.provider }}</dd>
            </div>
            <div>
              <dt>Email</dt>
              <dd>{{ accountDetails.email }}</dd>
            </div>
            <div>
              <dt>Plan</dt>
              <dd>{{ accountDetails.plan }}</dd>
            </div>
            <div>
              <dt>Usage remaining</dt>
              <dd v-if="accountUsageDetails.remainingPercent !== null">
                {{ accountUsageDetails.remainingPercent }}%
              </dd>
              <dd v-else>Not available</dd>
            </div>
          </dl>

          <div
            v-if="accountUsageDetails.remainingPercent !== null"
            class="account-usage"
            role="group"
            aria-label="Codex usage remaining"
          >
            <div class="account-usage__header">
              <span class="account-usage__label">Rolling usage window</span>
              <span class="account-usage__value">
                {{ accountUsageDetails.remainingPercent }}% left
              </span>
            </div>
            <div
              class="account-usage__track"
              role="progressbar"
              :aria-valuenow="accountUsageDetails.remainingPercent"
              aria-valuemin="0"
              aria-valuemax="100"
              :aria-label="`${accountUsageDetails.remainingPercent}% usage remaining`"
            >
              <span
                class="account-usage__fill"
                :style="{ width: `${accountUsageDetails.remainingPercent}%` }"
              ></span>
            </div>
            <p v-if="accountUsageDetails.resetLabel" class="account-usage__meta">
              Resets {{ accountUsageDetails.resetLabel }}
            </p>
          </div>

          <p class="settings-help">
            <button type="button" class="inline-link" @click="refreshAccount">
              Refresh account
            </button>
          </p>

          <div class="settings-actions">
            <Button v-if="!isLoggedIn" :disabled="authLoading" @click="loginWithOpenAI">
              <Loader2 v-if="authLoading" class="spin" :size="15" />
              Sign in with OpenAI
            </Button>
            <Button v-if="isLoggedIn" variant="destructive" @click="logout"> Log out </Button>
          </div>
        </div>
      </section>
    </main>

    <main v-else-if="activeView === 'skills' && !widgetCollapsed" class="settings-area">
      <section class="settings-panel">
        <div class="settings-card">
          <div class="settings-card-header">
            <h2>SKILLS</h2>
            <p class="settings-help">
              App-embedded skills are listed first from the Electron-specific directory. Standard
              Codex skills from macOS are listed below if found.
            </p>
          </div>
          <div class="skills-section">
            <div class="skills-section-header">
              <code>{{ embeddedSkillsDir }}</code>
            </div>
            <p v-if="skillsLoading" class="settings-help">Loading skills...</p>
            <p v-else-if="embeddedSkills.length === 0" class="settings-help">
              No embedded app skills found.
            </p>
            <ul v-else class="skills-list">
              <li v-for="skill in embeddedSkills" :key="skill.skillFile" class="skills-item">
                <strong>{{ skill.name }}</strong>
                <p>{{ skill.summary }}</p>
                <textarea
                  v-model="skill.content"
                  class="settings-textarea skills-editor"
                  rows="10"
                  spellcheck="false"
                />
                <div class="skills-item-actions">
                  <Button
                    variant="secondary"
                    :disabled="isEmbeddedSkillSaving(skill.skillFile)"
                    @click="saveEmbeddedSkillEntry(skill)"
                  >
                    <Loader2
                      v-if="isEmbeddedSkillSaving(skill.skillFile)"
                      class="spin"
                      :size="15"
                    />
                    <span v-else>Save skill</span>
                  </Button>
                  <span
                    v-if="embeddedSkillSaveState[skill.skillFile] === 'saved'"
                    class="settings-status settings-status--success"
                  >
                    Saved
                  </span>
                </div>
                <code>{{ skill.directory }}</code>
              </li>
            </ul>
          </div>
          <div class="skills-section">
            <div class="skills-section-header">
              <h3>Standard Codex skills</h3>
              <code>{{ codexSkillsDir }}</code>
            </div>
            <p v-if="skillsLoading" class="settings-help">Loading skills...</p>
            <p v-else-if="codexSkills.length === 0" class="settings-help">
              No standard Codex skills found.
            </p>
            <ul v-else class="skills-name-list">
              <li v-for="skill in codexSkills" :key="skill.skillFile" class="skills-name-item">
                {{ skill.name }}
              </li>
            </ul>
          </div>
        </div>
      </section>
    </main>

    <main v-else-if="activeView === 'about' && !widgetCollapsed" class="settings-area about-area">
      <section class="about-panel">
        <header class="about-header">
          <div class="about-header__mark" aria-hidden="true">
            <Info :size="24" />
          </div>
          <div>
            <p class="about-header__eyebrow">About the archive</p>
            <h1>What is in the source library?</h1>
            <p>
              Choose a source in Chat to control what Baba Chat searches. This page lists the books
              included in the supplemental collections.
            </p>
          </div>
        </header>

        <div class="about-source-list">
          <article
            v-for="source in aboutSourceCatalog"
            :key="source.value"
            class="about-source-card"
          >
            <header class="about-source-card__header">
              <div>
                <p class="about-source-card__eyebrow">
                  {{ source.books.length }} {{ source.books.length === 1 ? 'book' : 'books' }}
                </p>
                <h2>{{ source.label }}</h2>
              </div>
              <span class="about-source-card__mark" aria-hidden="true">
                <BookOpen :size="18" />
              </span>
            </header>
            <p class="about-source-card__description">{{ source.description }}</p>
            <ul class="about-book-list">
              <li v-for="book in source.books" :key="book">{{ book }}</li>
            </ul>
          </article>
        </div>
      </section>
    </main>

    <div
      v-if="widgetMode"
      ref="widgetLauncher"
      class="widget-launcher"
      :class="{ 'widget-launcher--collapsed': widgetCollapsed }"
    >
      <button
        class="widget-orb widget-orb--expand"
        type="button"
        :aria-label="widgetCollapsed ? 'Restore full Baba Chat window' : 'Return to normal mode'"
        :title="widgetCollapsed ? 'Restore full Baba Chat window' : 'Return to normal mode'"
        @click="setWidgetMode(false)"
      >
        <Maximize2 :size="12" />
      </button>

      <template v-if="!widgetCollapsed">
        <div v-if="widgetDrawerOpen" class="widget-nav-drawer">
          <button
            class="widget-nav-item"
            :class="{ 'widget-nav-item--active': activeView === 'chat' }"
            type="button"
            @click="openWidgetView('chat')"
          >
            <MessageCircle :size="15" />
            <span>Chat</span>
          </button>
          <button
            class="widget-nav-item"
            :class="{ 'widget-nav-item--active': activeView === 'settings' }"
            type="button"
            @click="openWidgetView('settings')"
          >
            <Settings :size="15" />
            <span>Settings</span>
          </button>
          <button
            class="widget-nav-item"
            :class="{ 'widget-nav-item--active': activeView === 'skills' }"
            type="button"
            @click="openWidgetView('skills')"
          >
            <Wrench :size="15" />
            <span>Skills</span>
          </button>
          <button
            class="widget-nav-item"
            :class="{ 'widget-nav-item--active': activeView === 'about' }"
            type="button"
            @click="openWidgetView('about')"
          >
            <Info :size="15" />
            <span>About</span>
          </button>
        </div>

        <button
          class="widget-orb widget-orb--menu"
          type="button"
          :aria-label="widgetDrawerOpen ? 'Close menu' : 'Open navigation menu'"
          @click="widgetDrawerOpen = !widgetDrawerOpen"
        >
          <Menu :size="16" />
        </button>
      </template>

      <button
        class="widget-orb widget-orb--main"
        type="button"
        :aria-label="widgetCollapsed ? 'Restore full Baba Chat' : 'Collapse Baba Chat widget'"
        :title="widgetCollapsed ? 'Restore full Baba Chat' : 'Collapse Baba Chat widget'"
        @click="handleWidgetOrbClick"
        @pointerdown="handleWidgetOrbPointerDown"
        @pointermove="handleWidgetOrbPointerMove"
        @pointerup="handleWidgetOrbPointerUp"
        @pointercancel="handleWidgetOrbPointerCancel"
      >
        <Bot :size="34" aria-hidden="true" />
      </button>
    </div>
    <div v-if="toastVisible" class="toast" role="status" aria-live="polite">
      <strong>{{ toastMessage }}</strong>
    </div>

    <div
      v-if="sourceReaderOpen"
      class="source-reader-backdrop"
      role="presentation"
      @click.self="closeSourceReader"
    >
      <section
        class="source-reader"
        role="dialog"
        aria-modal="true"
        aria-labelledby="source-reader-title"
        tabindex="-1"
        @keydown.esc="closeSourceReader"
      >
        <header class="source-reader__header">
          <div>
            <p class="source-reader__eyebrow">Source reader</p>
            <h2 id="source-reader-title">
              {{ sourceReader?.title || 'Opening source...' }}
            </h2>
            <p v-if="sourceReader" class="source-reader__meta">
              {{ sourceReader.book || sourceReader.file }}
              <span aria-hidden="true">·</span>
              {{ sourceLocationLabel(sourceReader.anchor, sourceReader.source) }}
            </p>
          </div>
          <button
            class="source-reader__close"
            type="button"
            aria-label="Close source reader"
            @click="closeSourceReader"
          >
            <X :size="18" />
          </button>
        </header>

        <div v-if="sourceReaderLoading" class="source-reader__state" aria-live="polite">
          <Loader2 class="spin" :size="18" />
          <span>Opening the cited source...</span>
        </div>
        <div v-else-if="sourceReaderError" class="source-reader__state source-reader__state--error">
          {{ sourceReaderError }}
        </div>
        <div v-else-if="sourceReader" class="source-reader__body">
          <div class="source-reader__notice">
            <BookOpen :size="16" aria-hidden="true" />
            <span>
              The cited {{ sourceReader.source === 'discourses' ? 'paragraph' : 'section' }} is
              highlighted below.
            </span>
          </div>
          <div class="source-passages">
            <article
              v-for="passage in sourceReader.passages"
              :key="`${passage.passageId}-${passage.anchor}`"
              class="source-passage"
              :class="{ 'source-passage--selected': passage.selected }"
            >
              <div class="source-passage__meta">
                {{ sourceLocationLabel(passage.anchor, sourceReader.source) }}
                <span v-if="passage.selected" class="source-passage__badge">Cited here</span>
              </div>
              <p>{{ passage.text }}</p>
            </article>
          </div>
        </div>

        <footer v-if="sourceReader" class="source-reader__footer">
          <span class="source-reader__path">{{ sourceReader.file }}</span>
          <button class="source-reader__open-original" type="button" @click="openOriginalSource">
            <ExternalLink :size="14" aria-hidden="true" />
            Open original file
          </button>
        </footer>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import gsap from 'gsap';
import {
  ArrowUp,
  Bot,
  BookOpen,
  ChevronDown,
  ChevronUp,
  Clock,
  ExternalLink,
  Info,
  Loader2,
  Maximize2,
  Menu,
  MessageCircle,
  Minus,
  Pin,
  Plus,
  Settings,
  Square,
  Trash2,
  Wrench,
  X,
} from 'lucide-vue-next';
import { Button } from 'components/ui/button';
import CodexTerminal from 'components/CodexTerminal.vue';

type JsonRecord = Record<string, unknown>;
type MessageRole = 'user' | 'assistant' | 'system' | 'tool';
type CorpusSource =
  | 'discourses'
  | 'stories'
  | 'other_spiritual_books'
  | 'acharya_philosophy';
type SourceScope = CorpusSource[];
type ConversationMode = 'chat' | 'terminal';
type ChatRuntimeMode = 'codex' | 'api';

interface SourceScopeOption {
  value: CorpusSource | 'all';
  label: string;
  description?: string;
}

interface AboutSourceCatalogEntry {
  value: CorpusSource;
  label: string;
  description: string;
  books: string[];
}

interface ChatMessage {
  id: string;
  role: MessageRole;
  text: string;
  sourceScope?: SourceScope;
}

interface SourceCitation {
  citation: string;
  source: CorpusSource;
  path: string;
  anchor: string;
  label: string;
}

type MessagePart =
  | { key: string; kind: 'text'; text: string }
  | { key: string; kind: 'citation'; citation: SourceCitation };

type InlineMessagePart = {
  key: string;
  kind: 'text' | 'bold' | 'italic';
  text: string;
};

interface SourceReaderPassage {
  passageId: number;
  anchor: string;
  ordinal: number;
  text: string;
  selected: boolean;
}

interface SourceReaderDocument {
  citation: string;
  source: CorpusSource;
  title: string;
  book: string;
  file: string;
  anchor: string;
  sourcePath: string;
  passages: SourceReaderPassage[];
}

interface ModelOption {
  label: string;
  value: string;
  raw: JsonRecord;
  reasoningEfforts: string[];
}

interface ReasoningEffortOption {
  label: string;
  value: string;
}

interface StoredAppSettings {
  version: number;
  selectedModel: string;
  reasoningEffort: string;
  chatMode: ChatRuntimeMode;
  hybridProvider: HybridProvider;
  hybridApiModel: string;
  hybridBaseUrl: string;
  hybridMaxOutputTokens: number;
  basePrompt: string;
  additionalPrompt: string;
}

interface PendingRequest {
  requestId: string | number;
  method: string;
  title: string;
  detail: string;
  params: JsonRecord | null;
}

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

interface AttachedFile {
  name: string;
  path: string;
}

interface SkillEntry {
  name: string;
  directory: string;
  skillFile: string;
  summary: string;
  content: string;
}

interface ConversationRecord {
  id: string;
  threadId: string;
  title: string;
  cwd: string;
  directoryName: string;
  updatedAt: number;
  mode?: ConversationMode;
  terminalTranscript?: string;
  terminalInputLines?: string[];
  terminalSessionId?: string;
  chatMode?: ChatRuntimeMode;
  sourceScope?: SourceScope;
  pinned?: boolean;
  messages: ChatMessage[];
}

const sourceScopeOptions: SourceScopeOption[] = [
  {
    value: 'discourses',
    label: 'Discourses',
    description: 'Discourses by Prabhat Ranjan Sarkar.',
  },
  {
    value: 'stories',
    label: 'Baba Stories',
    description: 'Stories of Baba.',
  },
  {
    value: 'other_spiritual_books',
    label: 'Spiritual Scriptures',
    description:
      'Ancient spiritual scriptures, including the Upanishads, the Bhagavad Gita, and the Brahma Sutras, alongside a small selection of spiritual biographies and related works.',
  },
  {
    value: 'acharya_philosophy',
    label: 'AM Philosophy by Acaryas',
    description: 'Philosophy and spiritual guidance by Ananda Marga Acaryas.',
  },
  { value: 'all', label: 'Everything' },
];
const corpusSourceOrder: readonly CorpusSource[] = [
  'discourses',
  'stories',
  'other_spiritual_books',
  'acharya_philosophy',
];
const defaultSourceScope: readonly CorpusSource[] = ['discourses', 'stories'];

const aboutSourceCatalog: AboutSourceCatalogEntry[] = [
  {
    value: 'stories',
    label: 'Baba Stories',
    description:
      'Personal accounts, recollections, and stories about Baba from the story collection.',
    books: [
      '101 Baba Stories',
      'Advent of a Mystery',
      'Ananda Katha - Acarya Nagina',
      'Anandamurtijii As I Knew Him',
      'Ashutosh Baba',
      'Baba in Maharlika',
      'Baba Loves All',
      "Baba's Love for South America",
      'Baba The Lord',
      'Bhagavan Anandamurti - Narada Muni',
      'Carnamrtam',
      'Glimpses of a Mystery',
      'Glories of Baba',
      'Historias de un Maestro Tantrico',
      'I Am Yours',
      'I Meet My Beloved, Dada Dharmavedananda',
      'I Meet My Beloved',
      'Living With Baba - Dada Tapeshvarananda',
      'Moving with Cosmic Will',
      'My Baba by Ac Parameshvarananda Avt',
      'My Days with Baba',
      'My Master The Supreme Guide',
      'My Spiritual Life With Baba',
      'My Time With Baba',
      'Namami Kalyanasundaram Part II',
      'Never Shall We Forget You, Dada Chandranath',
      'Sambhavami',
      'Shraddhainjali',
      'Stories of Baba',
      'Tantric Women Tell Their Stories',
      'The Jamalpur Days',
      'The Life & Teachings of Shrii Shrii Anandamurti',
      'The Supreme Friend',
      'Travels With the Mystic Master',
      'Walking With the Master',
      'With My Master',
      'You Are Never Alone - Vandananda',
      'Dada-Ik compiled stories',
    ],
  },
  {
    value: 'other_spiritual_books',
    label: 'Spiritual Scriptures',
    description:
      'Ancient spiritual scriptures and related works, including the Upanishads, the Bhagavad Gita, and the Brahma Sutras, alongside a small selection of spiritual biographies.',
    books: [
      'A Guide to Spiritual Life: Spiritual Teachings of Swami Brahmananda',
      'Aghora III: The Law of Karma',
      'Aghora: At the Left Hand of God',
      'Aghora II: Kundalini',
      'Aparokshanubhuti',
      'Autobiography of a Yogi',
      'Avadhuta Gita',
      'BE: Beyond Enlightenment',
      'Bhagavad Gita With the Commentary of Adi Shankaracharya',
      'Brahma Sutra Bhasya of Shankaracharya',
      'Brahma Sutras: According to Sri Sankaracharya',
      'Drg-Drsya Viveka: An Inquiry into the Nature of the Seer and the Seen',
      'Eight Upanishads, With the Commentary of Shankaracharya',
      'The Gospel of Sri Ramakrishna',
      'How to Know God',
      'Living with the Himalayan Masters',
      "Self-knowledge: An English Translation of Shankaracharya's Atmabodha",
      'The Collected Works of Sri Ramana Maharshi',
      'The Complete Works of Swami Vivekananda',
      'The Life of Ramakrishna',
      'The Principal Upanishads',
      'Upadeshasahasri of Sri Shankara',
      'Vivekachudamani of Sri Sankaracharya',
      'Vivekananda: A Biography',
    ],
  },
  {
    value: 'acharya_philosophy',
    label: 'AM Philosophy by Acaryas',
    description: 'Philosophy and practical spiritual guidance by Ananda Marga Acaryas.',
    books: ['Rajadhiraja Yoga - Acarya Cidgananda Avadhuta', 'When the Time Comes'],
  },
];

const account = ref<unknown>(null);
const accountRateLimits = ref<unknown>(null);
const accountLabel = ref('Checking...');
const authLoading = ref(false);
const modelsLoading = ref(false);
const turnActive = ref(false);
const activeView = ref<'chat' | 'settings' | 'skills' | 'about'>('chat');
const drawerHidden = ref(false);
const navWidth = ref(214);
const isNavResizing = ref(false);
const widgetMode = ref(false);
const widgetCollapsed = ref(false);
const widgetDrawerOpen = ref(false);
const sourceScope = ref<SourceScope>([...defaultSourceScope]);
const terminalMode = ref(false);
const chatMode = ref<ChatRuntimeMode>('codex');
const hybridProvider = ref<HybridProvider>('deepseek');
const hybridApiModel = ref('deepseek-v4-flash');
const hybridBaseUrl = ref('https://api.deepseek.com');
const hybridMaxOutputTokens = ref(1100);
const hybridApiKeyDraft = ref('');
const hybridConfigured = ref(false);
const hybridStatusLoading = ref(false);
const hybridSaving = ref(false);
const hybridApiKeyMask = '••••••••••••';
const selectedModel = ref<string>('');
const reasoningEffort = ref('max');
const models = ref<JsonRecord[]>([]);
const threadId = ref<string | null>(null);
const activeTurnId = ref<string | null>(null);
const prompt = ref('');
const basePrompt = ref('');
const additionalPrompt = ref('');
const errorText = ref('');
const messages = ref<ChatMessage[]>([]);
const pendingRequests = ref<PendingRequest[]>([]);
const attachedFiles = ref<AttachedFile[]>([]);
const isDraggingFile = ref(false);
const messageList = ref<HTMLElement | null>(null);
const userScrolledAway = ref(false);
const widgetLauncher = ref<HTMLElement | null>(null);
const thinkingLetterRefs = ref<HTMLElement[]>([]);
const directory = ref<DirectoryListing | null>(null);
const conversationsDrawerOpen = ref(true);
const skillsLoading = ref(false);
const embeddedSkills = ref<SkillEntry[]>([]);
const codexSkills = ref<SkillEntry[]>([]);
const prefersReducedMotion = ref(false);
const embeddedSkillsDir = ref('src-electron/SKILLS');
const codexSkillsDir = ref('~/.codex/skills');
const embeddedSkillSaveState = ref<Record<string, 'idle' | 'saving' | 'saved'>>({});
const basePromptSaveState = ref<'idle' | 'saving' | 'saved'>('idle');
const toastMessage = ref('');
const toastVisible = ref(false);
const conversationHistory = ref<ConversationRecord[]>([]);
const terminalTranscript = ref('');
const terminalConversationId = ref<string | null>(null);
const terminalSessionId = ref<string | null>(null);
const terminalAutoStart = ref(false);
const activeHybridRequestId = ref<string | null>(null);
const terminalInputBuffer = ref('');
const terminalInputLines = ref<string[]>([]);
const sourceReader = ref<SourceReaderDocument | null>(null);
const sourceReaderCitation = ref<string | null>(null);
const sourceReaderLoading = ref(false);
const sourceReaderError = ref('');
const thinkingLetters = 'Thinking'.split('');
const thinkingAnimationByIndex = [
  'bounce',
  'flip',
  'spin',
  'tilt',
  'stretch',
  'slide',
  'pulse',
  'swing',
] as const;
let thinkingTimeline: gsap.core.Timeline | null = null;
let navResizePointerId: number | null = null;
let navResizePreviousCursor = '';
let navResizePreviousUserSelect = '';
let widgetOrbDrag: {
  pointerId: number;
  startX: number;
  startY: number;
  lastX: number;
  lastY: number;
  moved: boolean;
} | null = null;

const isLoggedIn = computed(() => {
  return accountDetails.value.isAuthenticated;
});

const accountDetails = computed(() => getAccountDetails(account.value));

const accountUsageDetails = computed(() => getAccountUsageDetails(accountRateLimits.value));

const modelOptions = computed<ModelOption[]>(() =>
  models.value
    .map((model) => normalizeModelOption(model))
    .filter((model): model is ModelOption => Boolean(model.value)),
);

const selectedModelOption = computed(() =>
  modelOptions.value.find((model) => model.value === selectedModel.value),
);

const fallbackReasoningEffortOptions: ReasoningEffortOption[] = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'max', label: 'Max' },
];

const reasoningEffortOptions = computed<ReasoningEffortOption[]>(() => {
  const metadataEfforts = selectedModelOption.value?.reasoningEfforts ?? [];
  const values =
    metadataEfforts.length > 0
      ? metadataEfforts
      : fallbackReasoningEffortOptions.map((option) => option.value);

  return values.map((value) => ({
    value,
    label: reasoningEffortLabel(value),
  }));
});

const reasoningEffortHelp = computed(() => {
  if (selectedModelOption.value?.reasoningEfforts.length) {
    return 'Available levels come from the selected model.';
  }

  return 'Uses Baba Chat defaults when the model does not publish effort levels.';
});

const visibleMessages = computed(() => messages.value.filter(isRenderableMessage));

const appShellStyle = computed<Record<string, string>>(() => ({
  '--nav-width': drawerHidden.value ? '0px' : `${navWidth.value}px`,
}));

const sourceScopeEmpty = computed(() => sourceScope.value.length === 0);

const sendButtonDisabled = computed(
  () =>
    !turnActive.value &&
    (sourceScopeEmpty.value || (!prompt.value.trim() && attachedFiles.value.length === 0)),
);

const showThinking = computed(() => turnActive.value);
const sourceReaderOpen = computed(() => Boolean(sourceReaderCitation.value));

let removeEventListener: (() => void) | undefined;
let widgetClickThrough = false;
const appSettingsVersion = 6;
const appSettingsStorageKey = 'baba-chat/settings';
const navWidthStorageKey = 'baba-chat/nav-width';
const conversationHistoryStorageKey = 'baba-chat/conversation-history';
const conversationHistoryStoreKey = 'baba-chat-conversation-history';
const legacyBasePromptStorageKey = 'directors-chat/base-prompt';
const legacyConversationHistoryStorageKey = 'directors-chat/conversation-history';
let basePromptSaveTimer: ReturnType<typeof setTimeout> | null = null;
let toastTimer: ReturnType<typeof setTimeout> | null = null;
let userScrollIntentTimer: ReturnType<typeof setTimeout> | null = null;
let hasLoadedSettings = false;
let storedModelChoice = '';
let storedReasoningEffort = '';
let reducedMotionMediaQuery: MediaQueryList | null = null;
let ignoreNextWidgetClick = false;
let programmaticScrollSequence = 0;
let handledProgrammaticScrollSequence = 0;
let userScrollIntentPending = false;
const navWidthMin = 168;
const navWidthMax = 360;
const terminalTranscriptMaxLength = 200_000;
const codexSessionIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// ANSI control sequences are part of the embedded terminal protocol.
/* eslint-disable no-control-regex */
const terminalControlCharacterPattern = new RegExp(
  '[\\u0000-\\u0008\\u000b\\u000c\\u000e-\\u001f\\u007f]',
  'g',
);
const terminalAnsiOscPattern = new RegExp('\\u001b\\][\\s\\S]*?(?:\\u0007|\\u001b\\\\)', 'g');
const terminalAnsiCsiPattern = new RegExp('\\u001b\\[[0-?]*[ -/]*[@-~]', 'g');
const terminalAnsiCharsetPattern = new RegExp('\\u001b\\([0-2]', 'g');
const terminalAnsiEscapePattern = new RegExp('\\u001b[^\\x20-\\x7e]', 'g');
const sourceCitationPattern = /\[\[BABA_SOURCE:\s*((?:Discourses|Stories|Other-Spiritual-Books|Acharya-Philosophy)\/[^\]\n]+?)\s*\]\]|((?:Discourses|Stories|Other-Spiritual-Books|Acharya-Philosophy)\/[^\n)\],;]+?\.(?:html?|md|markdown)(?:#[A-Za-z0-9/_-]+)?)/gi;
const inlineMarkdownPattern = /\*\*([^*\n]+?)\*\*|\*([^*\n]+?)\*/g;
/* eslint-enable no-control-regex */

function handleReducedMotionChange(event: MediaQueryListEvent) {
  prefersReducedMotion.value = event.matches;
}

onMounted(async () => {
  loadNavWidth();
  loadStoredSettings();
  loadConversationHistory();
  removeEventListener = window.directorsCodex?.onEvent(handleCodexEvent);
  reducedMotionMediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  prefersReducedMotion.value = reducedMotionMediaQuery.matches;
  reducedMotionMediaQuery.addEventListener?.('change', handleReducedMotionChange);
  window.addEventListener('mousemove', handleWidgetClickThroughMouseMove);
  const startupTasks = [loadCurrentDirectory(), loadSkills(), loadHybridStatus()];
  if (chatMode.value === 'codex') {
    startupTasks.push(refreshAccount(), loadModels());
  }
  await Promise.all(startupTasks);
});

onUnmounted(() => {
  endNavResize();
  removeEventListener?.();
  reducedMotionMediaQuery?.removeEventListener?.('change', handleReducedMotionChange);
  window.removeEventListener('mousemove', handleWidgetClickThroughMouseMove);
  thinkingTimeline?.kill();
  if (basePromptSaveTimer) {
    clearTimeout(basePromptSaveTimer);
    persistAppSettings();
  }
  if (toastTimer) {
    clearTimeout(toastTimer);
  }
  if (userScrollIntentTimer) {
    clearTimeout(userScrollIntentTimer);
  }
  void cancelHybridRequest();
  void setWidgetClickThrough(false);
  if (widgetMode.value) {
    void window.directorsCodex?.setWidgetMode(false);
  }
});

watch([widgetMode, widgetCollapsed], async () => {
  await nextTick();
  await syncWidgetWindowBounds();
  syncWidgetClickThrough();
  if (widgetCollapsed.value) {
    widgetDrawerOpen.value = false;
  }
});

watch(
  [
    basePrompt,
    additionalPrompt,
    selectedModel,
    reasoningEffort,
    chatMode,
    hybridProvider,
    hybridApiModel,
    hybridBaseUrl,
    hybridMaxOutputTokens,
  ],
  () => {
    if (!hasLoadedSettings) {
      return;
    }

    basePromptSaveState.value = 'saving';
    if (basePromptSaveTimer) {
      clearTimeout(basePromptSaveTimer);
    }

    basePromptSaveTimer = setTimeout(() => {
      persistAppSettings();
      basePromptSaveState.value = 'saved';
      showToast('Baba Chat settings saved');
    }, 2000);
  },
);

watch([showThinking, prefersReducedMotion], async ([visible, reducedMotion]) => {
  thinkingTimeline?.kill();
  thinkingTimeline = null;

  if (!visible || reducedMotion) {
    return;
  }

  await nextTick();

  thinkingTimeline = gsap.timeline({ repeat: -1, repeatDelay: 0.7 });

  shuffledIndexes(thinkingLetterRefs.value.length).forEach((letterIndex, order) => {
    const element = thinkingLetterRefs.value[letterIndex];
    if (!element) {
      return;
    }

    thinkingTimeline?.add(
      letterAnimation(element, thinkingAnimationByIndex[letterIndex] ?? 'bounce'),
      order * 0.5,
    );
  });
});

watch(showThinking, () => {
  void scrollToBottom(false, shouldStayPinned());
});

watch(selectedModel, (value) => {
  if (!hasLoadedSettings || !value) {
    return;
  }

  const options = reasoningEffortOptions.value;
  if (!options.some((option) => sameReasoningEffort(option.value, reasoningEffort.value))) {
    reasoningEffort.value = chooseDefaultReasoningEffort(options);
  }
});

watch(chatMode, (value, previousValue) => {
  if (!hasLoadedSettings || value === previousValue || value !== 'codex') {
    return;
  }

  void Promise.all([refreshAccount(), loadModels()]);
});

function loadNavWidth() {
  const storedWidth = Number(window.localStorage.getItem(navWidthStorageKey));
  if (Number.isFinite(storedWidth)) {
    navWidth.value = clampNavWidth(storedWidth);
  }
}

function handleNavResizeStart(event: PointerEvent) {
  if (drawerHidden.value) {
    return;
  }

  event.preventDefault();
  navResizePointerId = event.pointerId;
  isNavResizing.value = true;
  navResizePreviousCursor = document.body.style.cursor;
  navResizePreviousUserSelect = document.body.style.userSelect;
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';
  window.addEventListener('pointermove', handleNavResizeMove);
  window.addEventListener('pointerup', endNavResize);
  window.addEventListener('pointercancel', endNavResize);
}

function handleNavResizeMove(event: PointerEvent) {
  if (navResizePointerId !== event.pointerId) {
    return;
  }

  navWidth.value = clampNavWidth(event.clientX);
}

function handleNavResizeKeydown(event: KeyboardEvent) {
  if (drawerHidden.value) {
    return;
  }

  let nextWidth: number | null = null;
  if (event.key === 'ArrowLeft') {
    nextWidth = navWidth.value - 12;
  } else if (event.key === 'ArrowRight') {
    nextWidth = navWidth.value + 12;
  } else if (event.key === 'Home') {
    nextWidth = navWidthMin;
  } else if (event.key === 'End') {
    nextWidth = navWidthMax;
  }

  if (nextWidth === null) {
    return;
  }

  event.preventDefault();
  navWidth.value = clampNavWidth(nextWidth);
  persistNavWidth();
}

function endNavResize(event?: PointerEvent) {
  if (event && navResizePointerId !== null && navResizePointerId !== event.pointerId) {
    return;
  }

  if (navResizePointerId !== null) {
    persistNavWidth();
  }

  navResizePointerId = null;
  isNavResizing.value = false;
  document.body.style.cursor = navResizePreviousCursor;
  document.body.style.userSelect = navResizePreviousUserSelect;
  window.removeEventListener('pointermove', handleNavResizeMove);
  window.removeEventListener('pointerup', endNavResize);
  window.removeEventListener('pointercancel', endNavResize);
}

function persistNavWidth() {
  window.localStorage.setItem(navWidthStorageKey, String(navWidth.value));
}

function clampNavWidth(value: number) {
  return Math.round(Math.min(Math.max(value, navWidthMin), navWidthMax));
}

async function refreshAccount() {
  try {
    account.value = await window.directorsCodex?.accountRead(true);
    accountLabel.value = describeAccount(account.value);
    await refreshAccountRateLimits();
  } catch (error) {
    accountLabel.value = 'Not connected';
    accountRateLimits.value = null;
    setError(error);
  }
}

async function refreshAccountRateLimits() {
  if (!getAccountDetails(account.value).isAuthenticated) {
    accountRateLimits.value = null;
    return;
  }

  try {
    accountRateLimits.value = await window.directorsCodex?.accountRateLimitsRead();
  } catch (error) {
    accountRateLimits.value = null;
    setError(error);
  }
}

async function loadHybridStatus() {
  hybridStatusLoading.value = true;

  try {
    const status = normalizeHybridStatus(await window.directorsCodex?.hybridStatus());
    hybridConfigured.value = status.configured;
    if (!hybridApiModel.value) {
      hybridApiModel.value = status.model;
    }
    if (!hybridBaseUrl.value) {
      hybridBaseUrl.value = status.baseUrl;
    }
  } catch (error) {
    hybridConfigured.value = false;
    setError(error);
  } finally {
    hybridStatusLoading.value = false;
  }
}

function selectHybridApiKeyCue(event: FocusEvent) {
  const input = event.currentTarget;
  if (
    hybridConfigured.value &&
    !hybridApiKeyDraft.value &&
    input instanceof HTMLInputElement
  ) {
    input.select();
  }
}

function handleHybridApiKeyInput(event: Event) {
  const input = event.target;
  if (!(input instanceof HTMLInputElement)) {
    return;
  }

  hybridApiKeyDraft.value = input.value === hybridApiKeyMask ? '' : input.value;
}

async function saveHybridApiKey() {
  const apiKey = hybridApiKeyDraft.value.trim();
  if (!apiKey) {
    return;
  }

  hybridSaving.value = true;
  clearError();

  try {
    const status = normalizeHybridStatus(await window.directorsCodex?.saveHybridApiKey(apiKey));
    hybridConfigured.value = status.configured;
    hybridApiKeyDraft.value = '';
    showToast('API key saved securely');
  } catch (error) {
    setError(error);
  } finally {
    hybridSaving.value = false;
  }
}

async function clearHybridApiKey() {
  hybridSaving.value = true;
  clearError();

  try {
    const status = normalizeHybridStatus(await window.directorsCodex?.clearHybridApiKey());
    hybridConfigured.value = status.configured;
    hybridApiKeyDraft.value = '';
    showToast('Saved API key cleared');
  } catch (error) {
    setError(error);
  } finally {
    hybridSaving.value = false;
  }
}

function handleHybridProviderChange() {
  const defaults = hybridProviderDefaults(hybridProvider.value);
  hybridApiModel.value = defaults.model;
  hybridBaseUrl.value = defaults.baseUrl;
}

async function loginWithOpenAI() {
  authLoading.value = true;
  clearError();

  try {
    await window.directorsCodex?.loginWithChatGpt();
    accountLabel.value = 'Waiting for browser sign-in...';
  } catch (error) {
    setError(error);
  } finally {
    authLoading.value = false;
  }
}

async function logout() {
  clearError();

  try {
    await window.directorsCodex?.logout();
    account.value = null;
    accountRateLimits.value = null;
    accountLabel.value = 'Not connected';
  } catch (error) {
    setError(error);
  }
}

async function loadModels() {
  modelsLoading.value = true;

  try {
    const result = await window.directorsCodex?.listModels();
    models.value = extractModels(result);
    const availableModels = modelOptions.value;
    const explicitModel = availableModels.find(
      (model) =>
        model.value === storedModelChoice &&
        !isLegacyModelChoice(model.value) &&
        !isLegacyModelChoice(model.label),
    );
    const defaultModel = explicitModel ?? chooseDefaultModel(availableModels);

    selectedModel.value = defaultModel?.value || '';
    const effortOptions = reasoningEffortOptions.value;
    const storedEffort = effortOptions.find((option) =>
      sameReasoningEffort(option.value, storedReasoningEffort),
    );
    reasoningEffort.value = storedEffort?.value ?? chooseDefaultReasoningEffort(effortOptions);
  } catch (error) {
    setError(error);
  } finally {
    modelsLoading.value = false;
  }
}

async function loadCurrentDirectory() {
  try {
    const result = await window.directorsCodex?.getCurrentDirectory();
    directory.value = normalizeDirectoryListing(result);
  } catch (error) {
    setError(error);
  }
}

async function loadSkills() {
  skillsLoading.value = true;

  try {
    const result = asRecord(await window.directorsCodex?.listSkills());
    embeddedSkillsDir.value = stringFrom(result, ['embeddedSkillsDir']) || embeddedSkillsDir.value;
    codexSkillsDir.value = stringFrom(result, ['codexSkillsDir']) || codexSkillsDir.value;
    embeddedSkills.value = normalizeSkillEntries(result?.embeddedSkills);
    codexSkills.value = normalizeSkillEntries(result?.codexSkills);
  } catch (error) {
    setError(error);
  } finally {
    skillsLoading.value = false;
  }
}

function loadConversationHistory() {
  void (async () => {
    try {
      const namespacedStoreValue = await window.directorsCodex?.storeRead(
        conversationHistoryStoreKey,
      );
      const legacyStoreValue =
        Array.isArray(namespacedStoreValue) && namespacedStoreValue.length > 0
          ? null
          : await window.directorsCodex?.storeRead('conversation-history');
      const namespacedLocalValue = parseStoredJson(
        window.localStorage.getItem(conversationHistoryStorageKey),
      );
      const legacyLocalValue = parseStoredJson(
        window.localStorage.getItem(legacyConversationHistoryStorageKey),
      );
      const candidate = firstStoredCollection(
        namespacedStoreValue,
        namespacedLocalValue,
        legacyStoreValue,
        legacyLocalValue,
      );

      conversationHistory.value = normalizeConversationHistory(candidate);

      if (conversationHistory.value.length > 0) {
        persistConversationHistory();
      }

      if (legacyLocalValue !== null) {
        window.localStorage.removeItem(legacyConversationHistoryStorageKey);
      }
    } catch {
      conversationHistory.value = [];
    }
  })();
}

function persistConversationHistory() {
  const data = normalizeConversationHistory(conversationHistory.value).slice(0, 25);
  conversationHistory.value = data;
  void window.directorsCodex?.storeWrite(conversationHistoryStoreKey, data);
  window.localStorage.setItem(conversationHistoryStorageKey, JSON.stringify(data));
}

function syncCurrentConversationRecord() {
  if (terminalMode.value) {
    syncTerminalConversationRecord();
    return;
  }

  if (!threadId.value) {
    return;
  }

  const currentDirectoryPath = directory.value?.path || '';
  const currentDirectoryName = directory.value?.name || 'No directory selected';
  const title =
    messages.value
      .find((message) => message.role === 'user' && message.text.trim())
      ?.text.split('\n')[0]
      ?.slice(0, 80) || currentDirectoryName;

  const nextRecord: ConversationRecord = {
    id: threadId.value,
    threadId: threadId.value,
    title,
    cwd: currentDirectoryPath,
    directoryName: currentDirectoryName,
    updatedAt: Date.now(),
    chatMode: chatMode.value,
    sourceScope: sourceScope.value,
    messages: sanitizeMessagesForStorage(messages.value),
  };

  saveConversationRecord(nextRecord);
}

function syncTerminalConversationRecord() {
  if (!terminalConversationId.value) {
    return;
  }

  const currentDirectoryPath = directory.value?.path || '';
  const currentDirectoryName = directory.value?.name || 'No directory selected';
  const firstInput = terminalInputLines.value.find((line) => line.trim())?.trim();
  const title = firstInput?.split('\n')[0]?.slice(0, 80) || 'Terminal session';

  saveConversationRecord({
    id: terminalConversationId.value,
    threadId: terminalConversationId.value,
    title,
    cwd: currentDirectoryPath,
    directoryName: currentDirectoryName,
    updatedAt: Date.now(),
    mode: 'terminal',
    terminalTranscript: terminalTranscript.value,
    terminalInputLines: [...terminalInputLines.value],
    ...(terminalSessionId.value ? { terminalSessionId: terminalSessionId.value } : {}),
    sourceScope: sourceScope.value,
    messages: [],
  });
}

function saveConversationRecord(nextRecord: ConversationRecord) {
  const previousRecord = conversationHistory.value.find((entry) => entry.id === nextRecord.id);
  const record =
    nextRecord.pinned === undefined && previousRecord?.pinned
      ? { ...nextRecord, pinned: true }
      : nextRecord;

  conversationHistory.value = sortConversationHistory([
    record,
    ...conversationHistory.value.filter((entry) => entry.id !== record.id),
  ]);
  persistConversationHistory();
}

function toggleConversationPinned(conversation: ConversationRecord) {
  conversationHistory.value = sortConversationHistory(
    conversationHistory.value.map((entry) =>
      entry.id === conversation.id ? { ...entry, pinned: !conversation.pinned } : entry,
    ),
  );
  persistConversationHistory();
}

async function deleteConversation(conversation: ConversationRecord) {
  const isCurrentConversation =
    conversation.id === terminalConversationId.value || conversation.threadId === threadId.value;

  if (isCurrentConversation) {
    await startNewConversation();
  }

  conversationHistory.value = conversationHistory.value.filter(
    (entry) => entry.id !== conversation.id,
  );
  persistConversationHistory();
  showToast('Conversation deleted');
}

function sortConversationHistory(records: ConversationRecord[]) {
  return [...records]
    .sort((left, right) => {
      const pinnedDifference = Number(Boolean(right.pinned)) - Number(Boolean(left.pinned));
      return pinnedDifference || right.updatedAt - left.updatedAt;
    })
    .slice(0, 25);
}

async function restoreConversation(conversation: ConversationRecord) {
  if (turnActive.value) {
    await interruptTurn();
  }
  await cancelHybridRequest();

  if (terminalMode.value) {
    terminalMode.value = false;
    await nextTick();
  }

  const restored = normalizeConversationRecord(conversation, 0);
  if (!restored) {
    setError('This saved conversation is not readable.');
    return;
  }

  threadId.value = restored.mode === 'terminal' ? null : restored.threadId;
  activeTurnId.value = null;
  turnActive.value = false;
  const latestUserMessage = [...restored.messages]
    .reverse()
    .find((message) => message.role === 'user');
  sourceScope.value =
    restored.sourceScope ?? latestUserMessage?.sourceScope ?? [...defaultSourceScope];
  chatMode.value = restored.chatMode ?? 'codex';
  basePromptInjected.value = true;
  prompt.value = '';
  resetScrollIntentState();
  terminalInputBuffer.value = '';
  terminalInputLines.value = restored.terminalInputLines ?? [];
  terminalTranscript.value = restored.terminalTranscript ?? '';
  messages.value =
    restored.mode === 'terminal' && terminalTranscript.value
      ? [
          {
            id: `${restored.id}-transcript`,
            role: 'assistant',
            text: terminalTranscript.value,
          },
        ]
      : sanitizeMessagesForStorage(restored.messages);
  pendingRequests.value = [];
  attachedFiles.value = [];
  clearError();
  activeView.value = 'chat';
  terminalConversationId.value = restored.mode === 'terminal' ? restored.id : null;
  terminalSessionId.value =
    restored.mode === 'terminal' ? (restored.terminalSessionId ?? null) : null;
  terminalAutoStart.value = restored.mode === 'terminal';
  terminalMode.value = restored.mode === 'terminal';
  await nextTick();
  if (!terminalMode.value) {
    await scrollToBottom(true);
  }
}

async function saveEmbeddedSkillEntry(skill: SkillEntry) {
  embeddedSkillSaveState.value = {
    ...embeddedSkillSaveState.value,
    [skill.skillFile]: 'saving',
  };

  try {
    await window.directorsCodex?.saveEmbeddedSkill(skill.skillFile, skill.content);
    const catalog = asRecord(await window.directorsCodex?.listSkills());
    embeddedSkills.value = normalizeSkillEntries(catalog?.embeddedSkills);
    embeddedSkillSaveState.value = {
      ...embeddedSkillSaveState.value,
      [skill.skillFile]: 'saved',
    };
    showToast(`Saved ${skill.name}`);
  } catch (error) {
    embeddedSkillSaveState.value = {
      ...embeddedSkillSaveState.value,
      [skill.skillFile]: 'idle',
    };
    setError(error);
  }
}

function isEmbeddedSkillSaving(skillFile: string) {
  return embeddedSkillSaveState.value[skillFile] === 'saving';
}

function handleFileDrop(event: DragEvent) {
  isDraggingFile.value = false;
  const files = Array.from(event.dataTransfer?.files ?? [])
    .map((file) => ({
      name: file.name,
      path: window.directorsCodex?.filePathForDroppedFile(file) || '',
    }))
    .filter((file) => file.path);

  const existingPaths = new Set(attachedFiles.value.map((file) => file.path));
  const newFiles = files.filter((file) => !existingPaths.has(file.path));

  attachedFiles.value = [...attachedFiles.value, ...newFiles];
}

function isCorpusSource(value: unknown): value is CorpusSource {
  return (
    value === 'discourses' ||
    value === 'stories' ||
    value === 'other_spiritual_books' ||
    value === 'acharya_philosophy'
  );
}

function orderedSourceScope(sources: Iterable<CorpusSource>): SourceScope {
  const selected = new Set(sources);
  return corpusSourceOrder.filter((source) => selected.has(source));
}

function isEverythingScope(scope: SourceScope) {
  return corpusSourceOrder.every((source) => scope.includes(source));
}

function isSourceScopeSelected(scope: CorpusSource | 'all') {
  return scope === 'all' ? isEverythingScope(sourceScope.value) : sourceScope.value.includes(scope);
}

function toggleSourceScope(scope: CorpusSource | 'all') {
  if (scope === 'all') {
    sourceScope.value = isEverythingScope(sourceScope.value)
      ? []
      : [...corpusSourceOrder];
    syncCurrentConversationRecord();
    return;
  }

  const selected = new Set(sourceScope.value);
  if (selected.has(scope)) {
    selected.delete(scope);
  } else {
    selected.add(scope);
  }

  sourceScope.value = orderedSourceScope(selected);
  syncCurrentConversationRecord();
}

function handleScopeKeydown(event: KeyboardEvent, currentScope: CorpusSource | 'all') {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    toggleSourceScope(currentScope);
    return;
  }

  if (
    event.key !== 'ArrowRight' &&
    event.key !== 'ArrowDown' &&
    event.key !== 'ArrowLeft' &&
    event.key !== 'ArrowUp'
  ) {
    return;
  }

  event.preventDefault();
  const currentIndex = sourceScopeOptions.findIndex((option) => option.value === currentScope);
  const direction = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : -1;
  const nextIndex =
    (currentIndex + direction + sourceScopeOptions.length) % sourceScopeOptions.length;
  const nextScope = sourceScopeOptions[nextIndex]?.value;

  if (!nextScope) {
    return;
  }

  void nextTick(() => {
    document.querySelector<HTMLButtonElement>(`[data-source-scope="${nextScope}"]`)?.focus();
  });
}

function handleScopeInfoKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
  }
}

async function toggleTerminalMode() {
  if (terminalMode.value) {
    terminalMode.value = false;
    await nextTick();
    resetTerminalSessionState();
    return;
  }

  resetTerminalSessionState();
  terminalAutoStart.value = false;
  terminalMode.value = true;
}

function handleTerminalStarted(id: string) {
  if (!terminalConversationId.value) {
    terminalConversationId.value = `terminal-${id}`;
  }
  syncTerminalConversationRecord();
}

function handleTerminalInput(data: string) {
  const input = stripTerminalControlSequences(data);

  for (const character of input) {
    if (character === '\r' || character === '\n') {
      const submittedLine = terminalInputBuffer.value.trim();
      if (submittedLine) {
        terminalInputLines.value = [...terminalInputLines.value, submittedLine].slice(0, 100);
        syncTerminalConversationRecord();
      }
      terminalInputBuffer.value = '';
      continue;
    }

    if (character === '\u0003') {
      terminalInputBuffer.value = '';
      continue;
    }

    if (character === '\u0008' || character === '\u007f') {
      terminalInputBuffer.value = terminalInputBuffer.value.slice(0, -1);
      continue;
    }

    if (character >= ' ') {
      terminalInputBuffer.value += character;
    }
  }
}

function handleTerminalOutput(data: string) {
  const cleanedOutput = cleanTerminalOutput(data);
  if (!cleanedOutput) {
    return;
  }

  terminalTranscript.value = appendTerminalTranscript(terminalTranscript.value, cleanedOutput);
  syncTerminalConversationRecord();
}

function handleTerminalStatus(status: EmbeddedTerminalStatusPayload) {
  if (status.codexSessionId && status.codexSessionId !== terminalSessionId.value) {
    terminalSessionId.value = status.codexSessionId;
    syncTerminalConversationRecord();
  }

  if (status.state === 'exited' || status.state === 'killed' || status.state === 'error') {
    syncTerminalConversationRecord();
  }
}

function handleTerminalStopped() {
  syncTerminalConversationRecord();
}

function handleTerminalCleared() {
  terminalTranscript.value = '';
  syncTerminalConversationRecord();
}

function resetTerminalSessionState() {
  terminalConversationId.value = null;
  terminalSessionId.value = null;
  terminalAutoStart.value = false;
  terminalTranscript.value = '';
  terminalInputBuffer.value = '';
  terminalInputLines.value = [];
}

function appendTerminalTranscript(current: string, next: string) {
  const combined = `${current}${next}`;
  if (combined.length <= terminalTranscriptMaxLength) {
    return combined;
  }

  return `[Earlier terminal output omitted]\n${combined.slice(-terminalTranscriptMaxLength)}`;
}

function cleanTerminalOutput(value: string) {
  return stripTerminalControlSequences(value)
    .replace(/\r/g, '')
    .replace(terminalControlCharacterPattern, '');
}

function stripTerminalControlSequences(value: string) {
  return value
    .replace(terminalAnsiOscPattern, '')
    .replace(terminalAnsiCsiPattern, '')
    .replace(terminalAnsiCharsetPattern, '')
    .replace(terminalAnsiEscapePattern, '');
}

async function handleComposerAction() {
  if (turnActive.value) {
    await interruptTurn();
    return;
  }

  await sendPrompt();
}

async function sendPrompt() {
  const text = prompt.value.trim();
  if ((!text && attachedFiles.value.length === 0) || turnActive.value) {
    return;
  }

  if (sourceScopeEmpty.value) {
    return;
  }

  clearError();
  if (chatMode.value !== 'api' && !isLoggedIn.value) {
    addMessage(
      `login-required-${Date.now()}`,
      'system',
      'You are not logged in to Baba Chat yet. Open Settings to sign in with your Codex account.',
    );
    activeView.value = 'settings';
    return;
  }

  if (chatMode.value === 'api' && !hybridConfigured.value) {
    addMessage(
      `hybrid-key-required-${Date.now()}`,
      'system',
      'API mode needs a provider API key. Open Settings to configure it.',
    );
    activeView.value = 'settings';
    return;
  }

  const files = [...attachedFiles.value];
  const messageText = buildPromptText(text, files);
  const hybridHistory = sanitizeMessagesForStorage(messages.value).filter(
    (message): message is { id: string; role: 'user' | 'assistant'; text: string } =>
      message.role === 'user' || message.role === 'assistant',
  );
  addMessage(
    `user-${Date.now()}`,
    'user',
    buildVisibleUserMessage(text, files),
    [...sourceScope.value],
  );
  prompt.value = '';
  attachedFiles.value = [];
  turnActive.value = true;

  try {
    if (chatMode.value === 'api') {
      await sendHybridPrompt(messageText, hybridHistory);
      return;
    }

    if (!threadId.value) {
      const thread = await window.directorsCodex?.startThread({
        cwd: directory.value?.path,
        model: selectedModel.value || undefined,
      });
      const threadRecord = asRecord(thread);
      threadId.value =
        stringFrom(threadRecord, ['threadId', 'id']) ||
        stringFrom(asRecord(threadRecord?.thread), ['id']) ||
        null;
    }

    if (!threadId.value) {
      throw new Error('Codex did not return a thread id.');
    }

    const turn = await window.directorsCodex?.startTurn({
      threadId: threadId.value,
      text: buildTurnInputText(messageText, sourceScope.value),
      cwd: directory.value?.path,
      model: selectedModel.value || undefined,
      reasoningEffort: reasoningEffort.value || undefined,
    });

    const turnRecord = asRecord(turn);
    activeTurnId.value =
      stringFrom(turnRecord, ['turnId', 'id']) ||
      stringFrom(asRecord(turnRecord?.turn), ['id']) ||
      null;
    basePromptInjected.value = true;
    syncCurrentConversationRecord();
  } catch (error) {
    turnActive.value = false;
    activeTurnId.value = null;
    setError(error);
  }
}

async function sendHybridPrompt(
  messageText: string,
  history: Array<{ id: string; role: 'user' | 'assistant'; text: string }>,
) {
  const hybridCwd = directory.value?.path;
  if (!hybridCwd) {
    throw new Error('Select a working directory before using API mode.');
  }

  const requestId = `hybrid-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  activeHybridRequestId.value = requestId;
  threadId.value ||= requestId;
  turnActive.value = true;
  syncCurrentConversationRecord();

  try {
    const result = await window.directorsCodex?.completeHybrid({
      requestId,
      task: messageText,
      cwd: hybridCwd,
      sourceScope: serializeSourceScope(sourceScope.value),
      provider: hybridProvider.value,
      apiBaseUrl: hybridBaseUrl.value,
      apiModel: hybridApiModel.value,
      maxOutputTokens: hybridMaxOutputTokens.value,
      basePrompt: sanitizePromptForInjection(basePrompt.value),
      additionalPrompt: sanitizePromptForInjection(additionalPrompt.value),
      history: history.map((message) => ({ role: message.role, text: message.text })),
    });

    if (result?.status !== 'ok' || !result.answer) {
      if (result?.code === 'request_cancelled') {
        return;
      }
      throw new Error(result?.error || 'The API returned no answer.');
    }

    addMessage(`assistant-${requestId}`, 'assistant', result.answer);
  } catch (error) {
    setError(error);
  } finally {
    if (activeHybridRequestId.value === requestId) {
      activeHybridRequestId.value = null;
      turnActive.value = false;
      syncCurrentConversationRecord();
    }
  }
}

async function cancelHybridRequest() {
  const requestId = activeHybridRequestId.value;
  if (!requestId) {
    return;
  }

  activeHybridRequestId.value = null;
  turnActive.value = false;
  await window.directorsCodex?.cancelHybrid(requestId).catch(() => undefined);
}

async function interruptTurn() {
  if (activeHybridRequestId.value) {
    await cancelHybridRequest();
    return;
  }

  if (!threadId.value || !activeTurnId.value) {
    turnActive.value = false;
    return;
  }

  try {
    await window.directorsCodex?.interruptTurn(threadId.value, activeTurnId.value);
  } catch (error) {
    setError(error);
  }
}

async function answerRequest(requestId: string | number, decision: string) {
  const request = pendingRequests.value.find((item) => item.requestId === requestId);

  try {
    await window.directorsCodex?.respondToServerRequest({
      requestId,
      result: resultForRequest(request, decision),
    });
    pendingRequests.value = pendingRequests.value.filter((item) => item.requestId !== requestId);
  } catch (error) {
    setError(error);
  }
}

async function setWidgetMode(enabled: boolean) {
  clearError();

  try {
    await setWidgetClickThrough(false);
    await window.directorsCodex?.setWidgetMode(enabled);
    widgetMode.value = enabled;
    widgetCollapsed.value = false;
    widgetDrawerOpen.value = false;
    if (enabled) {
      activeView.value = 'chat';
    }
  } catch (error) {
    setError(error);
  }
}

function openWidgetView(view: 'chat' | 'settings' | 'skills' | 'about') {
  widgetCollapsed.value = false;
  activeView.value = view;
  widgetDrawerOpen.value = false;
}

function loadStoredSettings() {
  const storedSettings = normalizeStoredSettings(
    parseStoredJson(window.localStorage.getItem(appSettingsStorageKey)),
  );
  const legacyPrompt = window.localStorage.getItem(legacyBasePromptStorageKey) || '';
  const storedBasePrompt = sanitizeStoredPrompt(storedSettings.basePrompt || legacyPrompt);
  const knownDefaultPrompt = [
    buildPreviousDefaultBasePrompt(),
    buildPreviousArchiveBasePrompt(),
  ].includes(storedBasePrompt);
  const migratedBasePrompt =
    !storedBasePrompt ||
    (storedSettings.version < appSettingsVersion && knownDefaultPrompt)
      ? buildDefaultBasePrompt()
      : storedBasePrompt;
  const migratedHybridOutputTokens =
    storedSettings.version < appSettingsVersion && storedSettings.hybridMaxOutputTokens === 700
      ? 1100
      : storedSettings.hybridMaxOutputTokens;

  storedModelChoice = isLegacyModelChoice(storedSettings.selectedModel)
    ? ''
    : storedSettings.selectedModel;
  storedReasoningEffort = storedSettings.reasoningEffort;
  chatMode.value = storedSettings.chatMode;
  hybridProvider.value = storedSettings.hybridProvider;
  hybridApiModel.value =
    storedSettings.hybridApiModel || hybridProviderDefaults(hybridProvider.value).model;
  hybridBaseUrl.value =
    storedSettings.hybridBaseUrl || hybridProviderDefaults(hybridProvider.value).baseUrl;
  hybridMaxOutputTokens.value = migratedHybridOutputTokens;
  selectedModel.value = storedModelChoice;
  reasoningEffort.value = storedReasoningEffort || 'max';
  basePrompt.value = migratedBasePrompt;
  additionalPrompt.value = sanitizeStoredPrompt(storedSettings.additionalPrompt);
  hasLoadedSettings = true;

  if (
    legacyPrompt ||
    storedSettings.version !== appSettingsVersion ||
    migratedBasePrompt !== storedSettings.basePrompt
  ) {
    persistAppSettings();
  }

  window.localStorage.removeItem(legacyBasePromptStorageKey);
}

function resetBasePrompt() {
  basePrompt.value = buildDefaultBasePrompt();
}

async function startNewConversation() {
  if (turnActive.value) {
    await interruptTurn();
  }
  await cancelHybridRequest();

  if (terminalMode.value) {
    terminalMode.value = false;
    await nextTick();
    resetTerminalSessionState();
  }

  threadId.value = null;
  activeTurnId.value = null;
  turnActive.value = false;
  basePromptInjected.value = false;
  prompt.value = '';
  resetScrollIntentState();
  messages.value = [];
  pendingRequests.value = [];
  attachedFiles.value = [];
  clearError();
}

function showToast(message: string) {
  toastMessage.value = message;
  toastVisible.value = true;

  if (toastTimer) {
    clearTimeout(toastTimer);
  }

  toastTimer = setTimeout(() => {
    toastVisible.value = false;
  }, 2400);
}

function handleWidgetOrbPointerDown(event: PointerEvent) {
  const target = event.currentTarget;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  void setWidgetClickThrough(false);
  target.setPointerCapture(event.pointerId);
  widgetOrbDrag = {
    pointerId: event.pointerId,
    startX: event.screenX,
    startY: event.screenY,
    lastX: event.screenX,
    lastY: event.screenY,
    moved: false,
  };
}

function handleWidgetOrbPointerMove(event: PointerEvent) {
  if (!widgetOrbDrag || widgetOrbDrag.pointerId !== event.pointerId) {
    return;
  }

  const totalDeltaX = event.screenX - widgetOrbDrag.startX;
  const totalDeltaY = event.screenY - widgetOrbDrag.startY;
  const deltaX = event.screenX - widgetOrbDrag.lastX;
  const deltaY = event.screenY - widgetOrbDrag.lastY;

  if (!widgetOrbDrag.moved && Math.hypot(totalDeltaX, totalDeltaY) < 4) {
    return;
  }

  widgetOrbDrag.moved = true;
  widgetOrbDrag.lastX = event.screenX;
  widgetOrbDrag.lastY = event.screenY;
  window.directorsCodex?.moveWindowBy(deltaX, deltaY);
}

function handleWidgetOrbPointerUp(event: PointerEvent) {
  if (!widgetOrbDrag || widgetOrbDrag.pointerId !== event.pointerId) {
    return;
  }

  const wasDrag = widgetOrbDrag.moved;
  widgetOrbDrag = null;

  const target = event.currentTarget;
  if (target instanceof HTMLElement && target.hasPointerCapture(event.pointerId)) {
    target.releasePointerCapture(event.pointerId);
  }

  if (wasDrag) {
    ignoreNextWidgetClick = true;
  }
}

function handleWidgetOrbClick(event: MouseEvent) {
  if (ignoreNextWidgetClick) {
    ignoreNextWidgetClick = false;
    return;
  }

  widgetCollapsed.value = !widgetCollapsed.value;
  void nextTick(() => {
    syncWidgetClickThrough(event);
  });
}

function handleWidgetOrbPointerCancel(event: PointerEvent) {
  widgetOrbDrag = null;

  const target = event.currentTarget;
  if (target instanceof HTMLElement && target.hasPointerCapture(event.pointerId)) {
    target.releasePointerCapture(event.pointerId);
  }
}

function handleWidgetClickThroughMouseMove(event: MouseEvent) {
  syncWidgetClickThrough(event);
}

function syncWidgetClickThrough(event?: MouseEvent | PointerEvent) {
  if (!widgetMode.value || !widgetCollapsed.value) {
    void setWidgetClickThrough(false);
    return;
  }

  if (!event) {
    if (widgetCollapsed.value) {
      void setWidgetClickThrough(false);
    }
    return;
  }

  void setWidgetClickThrough(!isPointInsideWidgetOrb(event.clientX, event.clientY));
}

function isPointInsideWidgetOrb(clientX: number, clientY: number) {
  const launcher = widgetLauncher.value;
  if (!launcher) {
    return false;
  }

  const interactiveOrbs = Array.from(launcher.querySelectorAll<HTMLElement>('.widget-orb'));

  return interactiveOrbs.some((orb) => {
    const rect = orb.getBoundingClientRect();
    const radius = Math.min(rect.width, rect.height) / 2;
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;

    return Math.hypot(clientX - centerX, clientY - centerY) <= radius;
  });
}

async function setWidgetClickThrough(enabled: boolean) {
  if (widgetClickThrough === enabled) {
    return;
  }

  widgetClickThrough = enabled;
  await window.directorsCodex?.setWidgetClickThrough(enabled);
}

async function syncWidgetWindowBounds() {
  if (!widgetMode.value) {
    return;
  }

  await window.directorsCodex?.setWidgetCollapsed(widgetCollapsed.value);
}

async function windowAction(action: 'minimize' | 'maximize' | 'close') {
  try {
    await window.directorsCodex?.windowAction(action);
  } catch (error) {
    setError(error);
  }
}

function resultForRequest(request: PendingRequest | undefined, decision: string) {
  if (request?.method === 'item/permissions/requestApproval') {
    if (decision !== 'accept') {
      return {
        permissions: {},
        scope: 'turn',
      };
    }

    const permissions = asRecord(request.params?.permissions);

    return {
      permissions: {
        network: permissions?.network,
        fileSystem: permissions?.fileSystem,
      },
      scope: 'turn',
    };
  }

  return { decision };
}

function handleCodexEvent(event: unknown) {
  const record = asRecord(event);
  if (!record) {
    return;
  }

  if (record.type === 'server/request') {
    const requestRecord = asRecord(record.request);
    if (requestRecord === null) {
      return;
    }

    pendingRequests.value.push(describeRequest(requestRecord));
    return;
  }

  const method = typeof record.method === 'string' ? record.method : '';
  const params = asRecord(record.params);

  if (method === 'account/updated') {
    void refreshAccount();
    return;
  }

  if (method === 'account/rateLimits/updated') {
    void refreshAccountRateLimits();
    return;
  }

  if (method === 'turn/started') {
    activeTurnId.value =
      stringFrom(params, ['turnId', 'id']) || stringFrom(asRecord(params?.turn), ['id']);
    turnActive.value = true;
    void scrollToBottom(false, shouldStayPinned());
    return;
  }

  if (method === 'turn/completed') {
    turnActive.value = false;
    activeTurnId.value = null;
    return;
  }

  if (method === 'item/started') {
    handleItemStarted(params);
    return;
  }

  if (method === 'item/completed') {
    handleItemCompleted(params);
    return;
  }

  if (method === 'item/agentMessage/delta') {
    appendToMessage(
      stringFrom(params, ['itemId']) || `assistant-${Date.now()}`,
      'assistant',
      stringFrom(params, ['delta']) || '',
    );
    return;
  }

  if (method.endsWith('/outputDelta')) {
    // Tool output remains an internal app-server event. It must never become a chat message.
    return;
  }
}

function handleItemStarted(params: JsonRecord | null) {
  const item = asRecord(params?.item);
  const itemType = stringFrom(item, ['type']);

  // Assistant text arrives through deltas/completion. Shell, command, and research items are
  // intentionally handled as internal state only so they cannot leak into the transcript.
  if (itemType === 'command_execution' || itemType === 'commandExecution') {
    return;
  }
}

function handleItemCompleted(params: JsonRecord | null) {
  const item = asRecord(params?.item);
  if (!item) {
    return;
  }

  const itemId = stringFrom(params, ['itemId']) || stringFrom(item, ['id']);
  const itemType = stringFrom(item, ['type']);

  if (!itemId) {
    return;
  }

  const text = messageTextFrom(item);
  if (text && (itemType === 'assistant_message' || itemType === 'agentMessage')) {
    setMessage(itemId, 'assistant', text);
  }
}

function describeRequest(request: JsonRecord): PendingRequest {
  const method = stringFrom(request, ['method']) || 'server/request';
  const params = asRecord(request.params);
  const command = stringFrom(params, ['command']) || stringFrom(params, ['reason']);
  const cwdText = stringFrom(params, ['cwd']);
  const detail = [
    command ? `Requested action: ${command}` : '',
    cwdText ? `Workspace: ${cwdText}` : '',
  ]
    .filter(Boolean)
    .join('\n');

  return {
    requestId: requestIdFrom(request),
    method,
    title: titleForRequest(method),
    detail: detail || 'Codex requested approval to continue.',
    params,
  };
}

function titleForRequest(method: string) {
  if (method.includes('commandExecution')) {
    return 'Run command?';
  }

  if (method.includes('fileChange')) {
    return 'Apply file change?';
  }

  if (method.includes('permissions')) {
    return 'Grant permission?';
  }

  return 'Codex needs input';
}

function requestIdFrom(request: JsonRecord) {
  const id = request.id;
  return typeof id === 'string' || typeof id === 'number' ? id : Date.now();
}

function addMessage(id: string, role: MessageRole, text: string, messageSourceScope?: SourceScope) {
  if (role === 'tool' || messages.value.some((message) => message.id === id)) {
    return;
  }

  const shouldStickToBottom = shouldStayPinned();
  const messageScope = messageSourceScope ?? sourceScope.value;

  messages.value.push({
    id,
    role,
    text,
    ...(role === 'user' ? { sourceScope: [...messageScope] } : {}),
  });
  syncCurrentConversationRecord();
  void scrollToBottom(false, shouldStickToBottom);
}

function appendToMessage(id: string, role: MessageRole, text: string) {
  if (role === 'tool' || !text) {
    return;
  }

  const shouldStickToBottom = shouldStayPinned();
  const message = messages.value.find((item) => item.id === id);

  if (message) {
    message.text += text;
  } else {
    messages.value.push({ id, role, text });
  }

  syncCurrentConversationRecord();
  void scrollToBottom(false, shouldStickToBottom);
}

function setMessage(id: string, role: MessageRole, text: string) {
  if (role === 'tool') {
    return;
  }

  const shouldStickToBottom = shouldStayPinned();
  const message = messages.value.find((item) => item.id === id);

  if (message) {
    message.text = text;
    message.role = role;
  } else {
    messages.value.push({ id, role, text });
  }

  syncCurrentConversationRecord();
  void scrollToBottom(false, shouldStickToBottom);
}

function isNearBottom(element = messageList.value) {
  if (!element) {
    return true;
  }

  return element.scrollHeight - element.scrollTop - element.clientHeight <= 96;
}

function isAtBottom(element = messageList.value) {
  if (!element) {
    return true;
  }

  return element.scrollHeight - element.scrollTop - element.clientHeight <= 2;
}

function handleMessageScroll(event: Event) {
  const element =
    event.currentTarget instanceof HTMLElement ? event.currentTarget : messageList.value;
  if (!element) {
    return;
  }

  if (userScrollIntentPending) {
    clearUserScrollIntent();
    handledProgrammaticScrollSequence = programmaticScrollSequence;
    userScrolledAway.value = !isAtBottom(element);
    return;
  }

  if (handledProgrammaticScrollSequence < programmaticScrollSequence) {
    handledProgrammaticScrollSequence = programmaticScrollSequence;
    userScrolledAway.value = false;
    return;
  }

  userScrolledAway.value = !isNearBottom(element);
}

function handleMessageWheel(event: WheelEvent) {
  if (event.deltaY === 0) {
    return;
  }

  markUserScrollIntent();
  if (event.deltaY < 0) {
    userScrolledAway.value = true;
  }
}

function handleMessagePointerDown(event: PointerEvent) {
  const element = messageList.value;
  if (!element) {
    return;
  }

  const rect = element.getBoundingClientRect();
  const scrollbarWidth = element.offsetWidth - element.clientWidth;
  const scrollbarHitArea = Math.max(scrollbarWidth, 12);
  if (event.clientX >= rect.right - scrollbarHitArea) {
    markUserScrollIntent();
  }
}

function handleMessageTouchMove() {
  markUserScrollIntent();
}

function handleMessageKeydown(event: KeyboardEvent) {
  if (!['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)) {
    return;
  }

  markUserScrollIntent();
  if (event.key === 'ArrowUp' || event.key === 'PageUp' || event.key === 'Home') {
    userScrolledAway.value = true;
  }
}

function markUserScrollIntent() {
  userScrollIntentPending = true;
  handledProgrammaticScrollSequence = programmaticScrollSequence;

  if (userScrollIntentTimer) {
    clearTimeout(userScrollIntentTimer);
  }

  userScrollIntentTimer = setTimeout(() => {
    userScrollIntentPending = false;
  }, 250);
}

function clearUserScrollIntent() {
  userScrollIntentPending = false;
  if (userScrollIntentTimer) {
    clearTimeout(userScrollIntentTimer);
    userScrollIntentTimer = null;
  }
}

function resetScrollIntentState() {
  clearUserScrollIntent();
  handledProgrammaticScrollSequence = programmaticScrollSequence;
  userScrolledAway.value = false;
}

function shouldStayPinned() {
  return !userScrolledAway.value && isNearBottom();
}

async function scrollToBottom(force = false, stickToBottom = shouldStayPinned()) {
  const element = messageList.value;
  const shouldScroll = force || stickToBottom;
  if (!element || !shouldScroll) {
    return;
  }

  await nextTick();
  const currentElement = messageList.value;
  if (!currentElement || (!force && userScrolledAway.value)) {
    return;
  }

  if (force) {
    resetScrollIntentState();
  }

  programmaticScrollSequence += 1;
  userScrolledAway.value = false;
  currentElement.scrollTop = currentElement.scrollHeight;
}

function extractModels(value: unknown) {
  const record = asRecord(value);
  const list = Array.isArray(value)
    ? value
    : Array.isArray(record?.data)
      ? record.data
      : Array.isArray(record?.models)
        ? record.models
        : Array.isArray(record?.items)
          ? record.items
          : [];

  return list.filter((item): item is JsonRecord => Boolean(asRecord(item)));
}

function normalizeModelOption(model: JsonRecord): ModelOption {
  const id = stringFrom(model, ['id', 'model', 'slug', 'name']);
  const label = stringFrom(model, ['displayName', 'name', 'label', 'id', 'model']);

  return {
    label: label || id || 'Unknown model',
    value: id || label || '',
    raw: model,
    reasoningEfforts: extractReasoningEfforts(model),
  };
}

function extractReasoningEfforts(model: JsonRecord) {
  const values: string[] = [];
  const candidates = [
    model.supportedReasoningEfforts,
    model.supportedReasoningEffort,
    model.reasoningEfforts,
    model.reasoning_efforts,
    model.supportedEfforts,
    model.supported_efforts,
    model.effortLevels,
    model.effort_levels,
    model.reasoning,
    asRecord(model.capabilities)?.reasoningEfforts,
    asRecord(model.capabilities)?.supportedReasoningEfforts,
    asRecord(model.capabilities)?.reasoning,
  ];

  candidates.forEach((candidate) => collectReasoningEfforts(candidate, values));

  return values.filter(
    (value, index, allValues) =>
      allValues.findIndex((item) => sameReasoningEffort(item, value)) === index,
  );
}

function collectReasoningEfforts(value: unknown, values: string[]) {
  if (Array.isArray(value)) {
    value.forEach((item) => {
      if (typeof item === 'string' && isReasoningEffortName(item)) {
        values.push(item.trim().toLowerCase());
      } else {
        collectReasoningEfforts(item, values);
      }
    });
    return;
  }

  const record = asRecord(value);
  if (!record) {
    return;
  }

  ['efforts', 'levels', 'values', 'supported', 'supportedEfforts', 'supported_efforts'].forEach(
    (key) => collectReasoningEfforts(record[key], values),
  );
}

function isReasoningEffortName(value: string) {
  return /^(?:minimal|low|medium|high|max|xhigh|ultra|none)$/i.test(value.trim());
}

function reasoningEffortLabel(value: string) {
  const normalized = value.trim().toLowerCase();
  if (normalized === 'max' || normalized === 'xhigh' || normalized === 'ultra') {
    return 'Max';
  }

  return humanize(normalized);
}

function sameReasoningEffort(left: string, right: string) {
  if (!left || !right) {
    return false;
  }

  const normalize = (value: string) => {
    const normalized = value.trim().toLowerCase();
    return normalized === 'xhigh' || normalized === 'ultra' ? 'max' : normalized;
  };

  return normalize(left) === normalize(right);
}

function chooseDefaultReasoningEffort(options: ReasoningEffortOption[]) {
  return (
    options.find((option) => sameReasoningEffort(option.value, 'max'))?.value ||
    options.find((option) => sameReasoningEffort(option.value, 'high'))?.value ||
    options[options.length - 1]?.value ||
    'max'
  );
}

function chooseDefaultModel(options: ModelOption[]) {
  return [...options].sort(
    (left, right) => modelPreferenceScore(left) - modelPreferenceScore(right),
  )[0];
}

function modelPreferenceScore(model: ModelOption) {
  const id = model.value.trim().toLowerCase();
  const label = model.label.trim().toLowerCase();

  if (id === 'luna') {
    return 0;
  }

  if (label === 'luna') {
    return 1;
  }

  if (id.includes('luna') || label.includes('luna')) {
    return 2;
  }

  return 3;
}

function isLegacyModelChoice(value: string) {
  return /director(?:'s|’s)?\s*chat|directors-chat/i.test(value);
}

function parseStoredJson(value: string | null) {
  if (!value) {
    return null;
  }

  try {
    return JSON.parse(value) as unknown;
  } catch {
    return null;
  }
}

function firstStoredCollection(...values: unknown[]) {
  const nonEmptyCollection = values.find((value) => Array.isArray(value) && value.length > 0);
  if (nonEmptyCollection) {
    return nonEmptyCollection;
  }

  return values.find((value) => Array.isArray(value)) ?? [];
}

function hybridProviderDefaults(provider: HybridProvider) {
  return provider === 'openai-compatible'
    ? { model: 'gpt-4.1-mini', baseUrl: 'https://api.openai.com/v1' }
    : { model: 'deepseek-v4-flash', baseUrl: 'https://api.deepseek.com' };
}

function normalizeHybridStatus(value: unknown): HybridApiStatus {
  const record = asRecord(value);
  const provider =
    stringFrom(record, ['provider']).toLowerCase() === 'openai-compatible'
      ? 'openai-compatible'
      : 'deepseek';
  const defaults = hybridProviderDefaults(provider);
  return {
    configured: Boolean(record?.configured),
    provider,
    model: stringFrom(record, ['model']) || defaults.model,
    baseUrl: stringFrom(record, ['baseUrl']) || defaults.baseUrl,
    maxOutputTokens:
      typeof record?.maxOutputTokens === 'number'
        ? normalizeHybridOutputTokens(record.maxOutputTokens)
        : 1100,
  };
}

function sanitizeHybridModel(value: string) {
  return value
    .trim()
    .replace(/[^A-Za-z0-9._:/-]/g, '')
    .slice(0, 160);
}

function sanitizeHybridBaseUrl(value: string) {
  const candidate = value.trim().replace(/\/+$/, '');
  try {
    const url = new URL(candidate);
    if ((url.protocol !== 'http:' && url.protocol !== 'https:') || url.username || url.password) {
      return '';
    }
    return url.toString().replace(/\/+$/, '');
  } catch {
    return '';
  }
}

function normalizeHybridOutputTokens(value: unknown) {
  const numericValue = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(numericValue)) {
    return 1100;
  }
  return Math.min(Math.max(Math.round(numericValue), 256), 2000);
}

function normalizeStoredSettings(value: unknown): StoredAppSettings {
  const root = asRecord(value);
  const source = asRecord(root?.settings) ?? root;

  return {
    version: typeof source?.version === 'number' ? source.version : 0,
    selectedModel: stringFrom(source, ['selectedModel', 'modelId', 'model']),
    reasoningEffort: stringFrom(source, ['reasoningEffort', 'reasoning_effort', 'effort']),
    chatMode:
      ['api', 'api-hybrid'].includes(
        stringFrom(source, ['chatMode', 'runtime', 'runtimeMode']).toLowerCase(),
      )
        ? 'api'
        : 'codex',
    hybridProvider:
      stringFrom(source, ['hybridProvider', 'apiProvider']).toLowerCase() === 'openai-compatible'
        ? 'openai-compatible'
        : 'deepseek',
    hybridApiModel: stringFrom(source, ['hybridApiModel', 'apiModel']) || 'deepseek-v4-flash',
    hybridBaseUrl:
      stringFrom(source, ['hybridBaseUrl', 'apiBaseUrl']) || 'https://api.deepseek.com',
    hybridMaxOutputTokens:
      typeof source?.hybridMaxOutputTokens === 'number'
        ? Math.min(Math.max(Math.round(source.hybridMaxOutputTokens), 256), 2000)
        : 1100,
    basePrompt: stringFrom(source, ['basePrompt', 'base_prompt', 'masterDirective', 'directive']),
    additionalPrompt: stringFrom(source, [
      'additionalPrompt',
      'additional_prompt',
      'extraPrompt',
      'extra_prompt',
    ]),
  };
}

function sanitizeStoredPrompt(value: string) {
  const normalized = value.replace(/\r\n/g, '\n').trim();
  if (!normalized || isLegacyDirectorPrompt(normalized)) {
    return '';
  }

  return normalized
    .split('\n')
    .filter((line) => !isLegacyAbsoluteSkillPath(line))
    .join('\n')
    .trim();
}

function isLegacyDirectorPrompt(value: string) {
  return (
    /director(?:'s|’s)?\s+chat|directors-chat/i.test(value) ||
    /\/(?:Users|home|private\/var)\/.*(?:\.codex[\\/]skills|director)/i.test(value)
  );
}

function isLegacyAbsoluteSkillPath(value: string) {
  return /\/(?:Users|home|private\/var)\/.*(?:\.codex[\\/]skills|director)/i.test(value);
}

function persistAppSettings() {
  const settings: StoredAppSettings = {
    version: appSettingsVersion,
    selectedModel: isLegacyModelChoice(selectedModel.value) ? '' : selectedModel.value,
    reasoningEffort: reasoningEffort.value || 'max',
    chatMode: chatMode.value,
    hybridProvider: hybridProvider.value,
    hybridApiModel: sanitizeHybridModel(hybridApiModel.value),
    hybridBaseUrl: sanitizeHybridBaseUrl(hybridBaseUrl.value),
    hybridMaxOutputTokens: normalizeHybridOutputTokens(hybridMaxOutputTokens.value),
    basePrompt: sanitizeStoredPrompt(basePrompt.value) || buildDefaultBasePrompt(),
    additionalPrompt: sanitizeStoredPrompt(additionalPrompt.value),
  };

  window.localStorage.setItem(appSettingsStorageKey, JSON.stringify(settings));
}

function normalizeConversationHistory(value: unknown): ConversationRecord[] {
  const root = asRecord(value);
  const collection = Array.isArray(value)
    ? value
    : Array.isArray(root?.conversations)
      ? root.conversations
      : Array.isArray(root?.items)
        ? root.items
        : [];

  return sortConversationHistory(
    collection
      .map((entry, index) => normalizeConversationRecord(entry, index))
      .filter((entry): entry is ConversationRecord => Boolean(entry)),
  );
}

function normalizeConversationRecord(value: unknown, index: number): ConversationRecord | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const threadId = stringFrom(record, ['threadId', 'thread_id', 'conversationId', 'id']);
  if (!threadId) {
    return null;
  }

  const rawMessages = Array.isArray(record.messages)
    ? record.messages
    : Array.isArray(record.items)
      ? record.items
      : [];
  const normalizedMessages = rawMessages
    .map((message, messageIndex) => normalizeChatMessage(message, messageIndex))
    .filter((message): message is ChatMessage => Boolean(message));
  const mode =
    stringFrom(record, ['mode', 'conversationMode']).toLowerCase() === 'terminal'
      ? ('terminal' as const)
      : undefined;
  const storedChatMode =
    ['api', 'api-hybrid'].includes(
      stringFrom(record, ['chatMode', 'runtime', 'runtimeMode']).toLowerCase(),
    )
      ? ('api' as const)
      : undefined;
  const terminalTranscript = stringFrom(record, ['terminalTranscript', 'transcript', 'output']);
  const terminalSessionId = stringFrom(record, ['terminalSessionId', 'codexSessionId']);
  const terminalInputLines = Array.isArray(record.terminalInputLines)
    ? record.terminalInputLines
        .filter((line): line is string => typeof line === 'string')
        .map((line) => line.trim())
        .filter(Boolean)
        .slice(0, 100)
    : [];
  const firstUserMessage = normalizedMessages.find((message) => message.role === 'user');
  const title =
    stringFrom(record, ['title', 'name']).trim() ||
    firstUserMessage?.text.split('\n')[0]?.slice(0, 80) ||
    terminalInputLines[0]?.slice(0, 80) ||
    `Conversation ${index + 1}`;
  const normalizedSourceScope = normalizeSourceScope(record.sourceScope ?? record.source_scope);

  return {
    id: stringFrom(record, ['id', 'conversationId']) || threadId,
    threadId,
    title,
    cwd: stringFrom(record, ['cwd', 'workingDirectory', 'directory']),
    directoryName:
      stringFrom(record, ['directoryName', 'directoryLabel']) || 'No directory selected',
    updatedAt:
      typeof record.updatedAt === 'number'
        ? record.updatedAt
        : typeof record.updated_at === 'number'
          ? record.updated_at
          : Date.now(),
    ...(mode
      ? {
          mode,
          terminalTranscript,
          terminalInputLines,
          ...(codexSessionIdPattern.test(terminalSessionId) ? { terminalSessionId } : {}),
        }
      : {}),
    ...(storedChatMode ? { chatMode: storedChatMode } : {}),
    ...(normalizedSourceScope ? { sourceScope: normalizedSourceScope } : {}),
    ...(record.pinned === true ? { pinned: true } : {}),
    messages: normalizedMessages,
  };
}

function normalizeChatMessage(value: unknown, index: number): ChatMessage | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const rawRole = stringFrom(record, ['role', 'sender', 'type']).toLowerCase();
  const role: MessageRole =
    rawRole === 'user' || rawRole === 'human'
      ? 'user'
      : rawRole === 'assistant' || rawRole === 'agentmessage' || rawRole === 'agent_message'
        ? 'assistant'
        : rawRole === 'system'
          ? 'system'
          : 'tool';
  const text = messageTextFrom(record);

  if (!text || !isRenderableMessage({ id: '', role, text })) {
    return null;
  }

  const normalizedSourceScope = normalizeSourceScope(record.sourceScope ?? record.source_scope);

  return {
    id: stringFrom(record, ['id', 'itemId', 'messageId']) || `${role}-${index}`,
    role,
    text,
    ...(role === 'user'
      ? normalizedSourceScope
        ? { sourceScope: normalizedSourceScope }
        : {}
      : {}),
  };
}

function messageTextFrom(record: JsonRecord) {
  const directText = record.text ?? record.message ?? record.content ?? record.value;
  if (typeof directText === 'string') {
    return directText.trim();
  }

  if (Array.isArray(directText)) {
    return directText
      .map((part) => {
        if (typeof part === 'string') {
          return part;
        }

        const partRecord = asRecord(part);
        return stringFrom(partRecord, ['text', 'value', 'content']);
      })
      .filter(Boolean)
      .join('\n')
      .trim();
  }

  return '';
}

function normalizeSourceScope(value: unknown): SourceScope | undefined {
  const explicitEmptyArray = Array.isArray(value) && value.length === 0;
  const rawValues = Array.isArray(value)
    ? value
    : typeof value === 'string'
      ? value.split(/[+,]/)
      : [];

  if (rawValues.length === 0) {
    return explicitEmptyArray ? [] : undefined;
  }

  if (rawValues.length === 1 && rawValues[0] === 'none') {
    return [];
  }

  const selected = new Set<CorpusSource>();
  for (const rawValue of rawValues) {
    if (typeof rawValue !== 'string') {
      return undefined;
    }

    const normalizedValue = rawValue.trim();
    if (normalizedValue === 'all') {
      return [...corpusSourceOrder];
    }
    if (normalizedValue === 'default' || normalizedValue === 'both') {
      selected.add('discourses');
      selected.add('stories');
      continue;
    }
    if (!isCorpusSource(normalizedValue)) {
      return undefined;
    }
    selected.add(normalizedValue);
  }

  const normalized = orderedSourceScope(selected);
  return normalized.length > 0 ? normalized : undefined;
}

function isRenderableMessage(message: ChatMessage) {
  if (message.role === 'tool' || !message.text.trim()) {
    return false;
  }

  if (message.role === 'system' && isTraceText(message.text)) {
    return false;
  }

  return !isTraceText(message.text, message.role === 'system');
}

function messageParts(text: string): MessagePart[] {
  const parts: MessagePart[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let partIndex = 0;

  sourceCitationPattern.lastIndex = 0;
  while ((match = sourceCitationPattern.exec(text)) !== null) {
    const rawCitation = (match[1] || match[2] || '').trim().replace(/[.,;:)]+$/, '');
    const citation = parseSourceCitation(rawCitation);
    if (!citation) {
      continue;
    }

    if (match.index > lastIndex) {
      parts.push({
        key: `text-${partIndex++}`,
        kind: 'text',
        text: text.slice(lastIndex, match.index),
      });
    }

    parts.push({
      key: `citation-${partIndex++}`,
      kind: 'citation',
      citation,
    });
    lastIndex = sourceCitationPattern.lastIndex;
  }

  if (lastIndex < text.length || parts.length === 0) {
    parts.push({
      key: `text-${partIndex}`,
      kind: 'text',
      text: text.slice(lastIndex),
    });
  }

  return parts;
}

function inlineMessageParts(text: string, keyPrefix: string): InlineMessagePart[] {
  const parts: InlineMessagePart[] = [];
  let lastIndex = 0;
  let partIndex = 0;

  inlineMarkdownPattern.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = inlineMarkdownPattern.exec(text)) !== null) {
    const content = match[1] || match[2] || '';
    if (!content.trim()) {
      continue;
    }

    if (match.index > lastIndex) {
      parts.push({
        key: `${keyPrefix}-inline-${partIndex++}`,
        kind: 'text',
        text: text.slice(lastIndex, match.index),
      });
    }

    parts.push({
      key: `${keyPrefix}-inline-${partIndex++}`,
      kind: match[1] ? 'bold' : 'italic',
      text: content,
    });
    lastIndex = inlineMarkdownPattern.lastIndex;
  }

  if (lastIndex < text.length || parts.length === 0) {
    parts.push({
      key: `${keyPrefix}-inline-${partIndex}`,
      kind: 'text',
      text: text.slice(lastIndex),
    });
  }

  return parts;
}

function parseSourceCitation(value: string): SourceCitation | null {
  const match = /^(Discourses|Stories|Other-Spiritual-Books|Acharya-Philosophy)\/(.+?)(?:#(.+))?$/i.exec(value.trim());
  const sourcePrefix = match?.[1];
  const sourcePath = match?.[2];
  const sourceAnchor = match?.[3];
  if (!sourcePrefix || !sourcePath || !sourceAnchor) {
    return null;
  }

  const sourceByPrefix: Record<string, CorpusSource> = {
    discourses: 'discourses',
    stories: 'stories',
    'other-spiritual-books': 'other_spiritual_books',
    'acharya-philosophy': 'acharya_philosophy',
  };
  const source = sourceByPrefix[sourcePrefix.toLowerCase()];
  if (!source) {
    return null;
  }
  const prefixBySource: Record<CorpusSource, string> = {
    discourses: 'Discourses',
    stories: 'Stories',
    other_spiritual_books: 'Other-Spiritual-Books',
    acharya_philosophy: 'Acharya-Philosophy',
  };
  const prefix = prefixBySource[source];
  const path = `${prefix}/${sourcePath}`;
  const anchor = sourceAnchor.trim();
  if (!/\.(?:html?|md|markdown)$/i.test(sourcePath) || !anchor) {
    return null;
  }

  return {
    citation: `${path}#${anchor}`,
    source,
    path,
    anchor,
    label: `${humanizeSourceFilename(sourcePath)} · ${sourceLocationLabel(anchor, source)}`,
  };
}

function humanizeSourceFilename(value: string) {
  const filename = value.split('/').pop() || value;
  const withoutExtension = filename.replace(/\.(?:html?|md|markdown)$/i, '');
  const words = withoutExtension.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
  return words.replace(/\b\p{L}/gu, (letter) => letter.toUpperCase()) || 'Source file';
}

function sourceLocationLabel(anchor: string, source: CorpusSource) {
  if (source !== 'discourses') {
    const sectionMatch = /^section-(\d+)(?:\/chunk-(\d+))?$/i.exec(anchor);
    if (sectionMatch) {
      return sectionMatch[2]
        ? `section ${sectionMatch[1]}, excerpt ${sectionMatch[2]}`
        : `section ${sectionMatch[1]}`;
    }
  }

  if (/^\d+$/.test(anchor)) {
    return `paragraph ${anchor}`;
  }

  return `source location ${anchor.replace(/[-_]+/g, ' ')}`;
}

async function openSource(citation: string) {
  sourceReaderCitation.value = citation;
  sourceReader.value = null;
  sourceReaderError.value = '';
  sourceReaderLoading.value = true;

  const requestedCitation = citation;
  try {
    const cwd = directory.value?.path;
    if (!cwd) {
      throw new Error('Select a working directory before opening a source.');
    }

    const result = await window.directorsCodex?.readSource({ cwd, citation });
    if (sourceReaderCitation.value !== requestedCitation) {
      return;
    }

    const normalized = normalizeSourceReaderDocument(result);
    if (!normalized) {
      throw new Error('The cited source could not be read.');
    }
    sourceReader.value = normalized;
  } catch (error) {
    if (sourceReaderCitation.value === requestedCitation) {
      sourceReaderError.value = errorMessageForUi(error);
    }
  } finally {
    if (sourceReaderCitation.value === requestedCitation) {
      sourceReaderLoading.value = false;
    }
  }
}

function closeSourceReader() {
  sourceReaderCitation.value = null;
  sourceReader.value = null;
  sourceReaderLoading.value = false;
  sourceReaderError.value = '';
}

async function openOriginalSource() {
  const citation = sourceReaderCitation.value;
  const cwd = directory.value?.path;
  if (!citation || !cwd) {
    return;
  }

  try {
    await window.directorsCodex?.openSource({ cwd, citation });
  } catch (error) {
    sourceReaderError.value = errorMessageForUi(error);
  }
}

function normalizeSourceReaderDocument(value: unknown): SourceReaderDocument | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const sourceValue = stringFrom(record, ['source']).toLowerCase();
  const sourceByValue: Record<string, CorpusSource> = {
    discourses: 'discourses',
    stories: 'stories',
    other_spiritual_books: 'other_spiritual_books',
    acharya_philosophy: 'acharya_philosophy',
  };
  const source = sourceByValue[sourceValue];
  if (!source) {
    return null;
  }
  const citation = stringFrom(record, ['citation']);
  const anchor = stringFrom(record, ['anchor']);
  const rawPassages = Array.isArray(record.passages) ? record.passages : [];
  const passages = rawPassages
    .map((value) => asRecord(value))
    .filter((value): value is JsonRecord => Boolean(value))
    .map((value) => ({
      passageId: numberFrom(value, ['passage_id', 'passageId', 'id']) ?? 0,
      anchor: stringFrom(value, ['anchor']),
      ordinal: numberFrom(value, ['ordinal']) ?? 0,
      text: stringFrom(value, ['text']),
      selected: value.selected === true,
    }))
    .filter((passage) => passage.anchor && passage.text);

  if (!citation || !anchor || passages.length === 0) {
    return null;
  }

  return {
    citation,
    source,
    title: stringFrom(record, ['title']) || 'Baba source',
    book: stringFrom(record, ['book']),
    file: stringFrom(record, ['file', 'path']),
    anchor,
    sourcePath: stringFrom(record, ['source_path', 'sourcePath']),
    passages,
  };
}

function isTraceText(text: string, strict = false) {
  const trimmed = text.trim();
  if (
    /^\$\s+/.test(trimmed) ||
    /^(?:tool output|research trace|command execution)\b/i.test(trimmed)
  ) {
    return true;
  }

  if (!strict) {
    return false;
  }

  return (
    /^\{[\s\S]*\}$/.test(trimmed) &&
    /["']?(?:command|itemId|method|stdout|stderr|process|tool)["']?\s*:/i.test(trimmed)
  );
}

function sanitizeMessagesForStorage(source: ChatMessage[]) {
  return source.filter(isRenderableMessage).map((message) => ({
    id: message.id,
    role: message.role,
    text: message.text,
    ...(message.role === 'user' && message.sourceScope
      ? { sourceScope: [...message.sourceScope] }
      : {}),
  }));
}

function normalizeDirectoryListing(value: unknown): DirectoryListing | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const entries = Array.isArray(record.entries)
    ? record.entries
        .map((entry) => asRecord(entry))
        .filter((entry): entry is JsonRecord => Boolean(entry))
        .map((entry) => ({
          name: stringFrom(entry, ['name']),
          path: stringFrom(entry, ['path']),
          type:
            stringFrom(entry, ['type']) === 'directory'
              ? ('directory' as const)
              : ('file' as const),
        }))
        .filter((entry) => entry.name && entry.path)
    : [];

  return {
    path: stringFrom(record, ['path']),
    name: stringFrom(record, ['name']) || 'Directory',
    entries,
    total: typeof record.total === 'number' ? record.total : entries.length,
  };
}

function normalizeSkillEntries(value: unknown): SkillEntry[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((entry) => asRecord(entry))
    .filter((entry): entry is JsonRecord => Boolean(entry))
    .map((entry) => ({
      name: stringFrom(entry, ['name']) || 'Unnamed skill',
      directory: stringFrom(entry, ['directory']),
      skillFile: stringFrom(entry, ['skillFile']),
      summary: stringFrom(entry, ['summary']) || 'No summary available.',
      content: stringFrom(entry, ['content']),
    }))
    .filter((entry) => entry.skillFile);
}

const basePromptInjected = ref(false);

function buildPromptText(text: string, files: AttachedFile[]) {
  const fileLines = files.map((file) => `- ${file.path}`);
  const fileSection =
    fileLines.length > 0
      ? `\n\nAttached files. Use these full local paths when relevant:\n${fileLines.join('\n')}`
      : '';

  return `${text}${fileSection}`.trim();
}

function buildTurnInputText(text: string, scope: SourceScope) {
  const directive = sanitizePromptForInjection(basePrompt.value);
  const additional = sanitizePromptForInjection(additionalPrompt.value);
  const sourceScopeBlock = buildSourceScopeBlock(scope);
  const userMessage = ['<USER_MESSAGE>', text, '</USER_MESSAGE>'].join('\n');

  const sections = [sourceScopeBlock];
  sections.push(userMessage);
  const promptSections = [
    directive ? ['<BABA_CHAT_BASE_PROMPT>', directive, '</BABA_CHAT_BASE_PROMPT>'].join('\n') : '',
    additional
      ? ['<BABA_CHAT_ADDITIONAL_PROMPT>', additional, '</BABA_CHAT_ADDITIONAL_PROMPT>'].join('\n')
      : '',
  ].filter(Boolean);

  if (!basePromptInjected.value && promptSections.length > 0) {
    sections.unshift(...promptSections);
  }

  return sections.join('\n\n');
}

function sanitizePromptForInjection(value: string) {
  return sanitizeStoredPrompt(value)
    .replace(/<\/?BABA_CHAT_[^>]+>/gi, '')
    .trim();
}

function buildSourceScopeBlock(scope: SourceScope) {
  return `<BABA_SOURCE_SCOPE>${serializeSourceScope(scope)}</BABA_SOURCE_SCOPE>`;
}

function serializeSourceScope(scope: SourceScope) {
  const normalized = normalizeSourceScope(scope) ?? [...defaultSourceScope];
  if (normalized.length === 0) {
    return 'none';
  }
  if (isEverythingScope(normalized)) {
    return 'all';
  }
  if (
    normalized.length === defaultSourceScope.length &&
    defaultSourceScope.every((source) => normalized.includes(source))
  ) {
    return 'default';
  }
  return normalized.join('+');
}

function buildDefaultBasePrompt() {
  return [
    'You are Baba Chat, a helpful archive assistant for the works and life stories of Prabhat Ranjan Sarkar.',
    'Use the bundled Baba corpus research skill and local search tools for archive questions.',
    'Honor the <BABA_SOURCE_SCOPE> block and search the selected local corpus before answering.',
    'The source scope may be default, all, or a + joined combination of categories. The default scope contains Discourses and Baba Stories. Spiritual Scriptures and AM Philosophy by Acaryas are separate categories and are included only when selected.',
    'Search broadly for distinct passages, including apparently contrasting or qualifying statements, and connect them in the answer.',
    'For questions that require relationships across documents, themes, supports, qualifications, contrasts, or possible contradictions, use the local knowledge graph command: tools/baba-search/baba-search connections --source <scope> --query "<question>" --json. Treat graph relationships as hypotheses, verify their returned citations with the passage command, and do not treat an empty graph result as proof that no connection exists.',
    'Ground substantive claims in retrieved evidence, cite the relevant work and paragraph or story anchor, and say plainly when the corpus does not establish an answer.',
    'Answer the user directly in a clear, helpful style. This is a reader-facing archive conversation, not a software development workspace.',
    'For substantive questions, write a developed answer in 4 to 7 purposeful paragraphs, usually around 450 to 800 words when the evidence supports that depth. Start with a direct answer, then explain the main ideas and connect the sources instead of stopping at a short summary.',
    'Prefer paraphrase over long quotations. Never refer to source material as a chunk, snippet, evidence item, search result, or passage id in user-facing prose.',
    'End every substantive answer with one warm, optional follow-up question that invites the user to explore a related idea.',
    'For source-based claims, add the exact citation marker [[BABA_SOURCE:Discourses/File.html#3]], [[BABA_SOURCE:Stories/File.md#section-1/chunk-1]], [[BABA_SOURCE:Other-Spiritual-Books/File.md#section-1/chunk-1]], or [[BABA_SOURCE:Acharya-Philosophy/File.md#section-1/chunk-1]] using a citation returned by search. The app turns these markers into readable source links, so do not invent, alter, or explain the marker syntax.',
  ].join('\n');
}

function buildPreviousArchiveBasePrompt() {
  return [
    'You are Baba Chat, a helpful archive assistant for the works and life stories of Prabhat Ranjan Sarkar.',
    'Use the bundled Baba corpus research skill and local search tools for archive questions.',
    'Honor the <BABA_SOURCE_SCOPE> block and search the selected local corpus before answering.',
    'Search broadly for distinct passages, including apparently contrasting or qualifying statements, and connect them in the answer.',
    'Ground substantive claims in retrieved evidence, cite the relevant work and paragraph or story anchor, and say plainly when the corpus does not establish an answer.',
    'Answer the user directly in a clear, helpful style. This is a reader-facing archive conversation, not a software development workspace.',
  ].join('\n');
}

function buildPreviousDefaultBasePrompt() {
  return [
    'You are Baba Chat, a helpful archive assistant working inside a Codex Electron app.',
    'Treat the project root as the primary workspace.',
    `Check the embedded app-specific skills in "${embeddedSkillsDir.value}" before inventing app-local workflows.`,
    'Use src-electron/ for Electron shell, windowing, and IPC behavior when the task touches desktop integration.',
    'For questions about the Baba archive, honor the <BABA_SOURCE_SCOPE> block and search the selected local corpus before answering.',
    'Prefer clear, practical changes that fit the existing app structure.',
  ].join('\n');
}

function buildVisibleUserMessage(text: string, files: AttachedFile[]) {
  const fileNames = files.map((file) => `@${file.name}`);
  return [text, fileNames.join(' ')].filter(Boolean).join('\n');
}

function scopeLabel(scope: SourceScope) {
  const normalized = normalizeSourceScope(scope) ?? [...defaultSourceScope];
  if (normalized.length === 0) {
    return 'No sources selected';
  }
  if (isEverythingScope(normalized)) {
    return 'Everything';
  }

  return normalized
    .map((source) => sourceScopeOptions.find((option) => option.value === source)?.label)
    .filter((label): label is string => Boolean(label))
    .join(' + ');
}

function messageRoleLabel(role: MessageRole) {
  switch (role) {
    case 'user':
      return 'You';
    case 'assistant':
      return 'Baba Chat';
    case 'tool':
      return 'Research trace';
    case 'system':
      return 'System note';
    default:
      return role;
  }
}

function shuffledIndexes(length: number) {
  const indexes = Array.from({ length }, (_value, index) => index);

  for (let index = indexes.length - 1; index > 0; index -= 1) {
    const randomIndex = Math.floor(Math.random() * (index + 1));
    const current = indexes[index];
    const random = indexes[randomIndex];
    if (current === undefined || random === undefined) {
      continue;
    }
    indexes[index] = random;
    indexes[randomIndex] = current;
  }

  return indexes;
}

function letterAnimation(
  element: HTMLElement,
  animation: (typeof thinkingAnimationByIndex)[number],
) {
  gsap.set(element, {
    clearProps: 'all',
    transformOrigin: '50% 55%',
  });

  switch (animation) {
    case 'flip':
      return gsap
        .timeline()
        .to(element, { rotateX: 180, duration: 0.28, ease: 'power2.out' })
        .to(element, { rotateX: 360, duration: 0.28, ease: 'power2.in' })
        .set(element, { rotateX: 0 });
    case 'spin':
      return gsap
        .timeline()
        .to(element, { rotate: 360, duration: 0.56, ease: 'power2.inOut' })
        .set(element, { rotate: 0 });
    case 'tilt':
      return gsap
        .timeline()
        .to(element, { rotate: -18, duration: 0.2, ease: 'power2.out' })
        .to(element, { rotate: 16, duration: 0.2, ease: 'power2.inOut' })
        .to(element, { rotate: 0, duration: 0.16, ease: 'power2.in' });
    case 'stretch':
      return gsap
        .timeline()
        .to(element, { scaleY: 1.35, duration: 0.22, ease: 'power2.out' })
        .to(element, { scaleY: 1, duration: 0.3, ease: 'elastic.out(1, 0.45)' });
    case 'slide':
      return gsap
        .timeline()
        .to(element, { x: 8, duration: 0.2, ease: 'power2.out' })
        .to(element, { x: -5, duration: 0.18, ease: 'power2.inOut' })
        .to(element, { x: 0, duration: 0.18, ease: 'power2.in' });
    case 'pulse':
      return gsap
        .timeline()
        .to(element, { scale: 1.28, duration: 0.2, ease: 'power2.out' })
        .to(element, { scale: 1, duration: 0.28, ease: 'back.out(2)' });
    case 'swing':
      return gsap
        .timeline()
        .to(element, { rotateZ: 22, y: -3, duration: 0.22, ease: 'power2.out' })
        .to(element, { rotateZ: -12, y: 1, duration: 0.2, ease: 'power2.inOut' })
        .to(element, { rotateZ: 0, y: 0, duration: 0.16, ease: 'power2.in' });
    case 'bounce':
    default:
      return gsap
        .timeline()
        .to(element, { y: -9, duration: 0.22, ease: 'power2.out' })
        .to(element, { y: 0, duration: 0.34, ease: 'bounce.out' });
  }
}

function describeAccount(value: unknown) {
  const details = getAccountDetails(value);

  if (details.email !== 'Not available') {
    return `${details.email} · ${details.plan}`;
  }

  if (details.provider !== 'Unknown') {
    return details.provider;
  }

  return 'Not connected';
}

function getAccountDetails(value: unknown) {
  const root = asRecord(value);
  const accountRecord = asRecord(root?.account) ?? root;

  if (!accountRecord) {
    return {
      isAuthenticated: false,
      provider: 'Unknown',
      email: 'Not available',
      plan: 'Not available',
    };
  }

  const provider = humanize(stringFrom(accountRecord, ['type', 'authMode', 'mode']) || 'Unknown');
  const email = stringFrom(accountRecord, ['email', 'login', 'userEmail']) || 'Not available';
  const plan = humanize(
    stringFrom(accountRecord, ['planType', 'plan', 'subscription']) || 'Not available',
  );
  const type = stringFrom(accountRecord, ['type', 'authMode', 'mode']);
  const isAuthenticated =
    provider !== 'Unknown' ||
    email !== 'Not available' ||
    Boolean(type && type !== 'none' && type !== 'logged_out');

  return {
    isAuthenticated,
    provider,
    email,
    plan,
  };
}

function getAccountUsageDetails(value: unknown) {
  const root = asRecord(value);
  const rateLimits = asRecord(root?.rateLimits);
  const rateLimitsByLimitId = asRecord(root?.rateLimitsByLimitId);
  const fallbackRateLimit = rateLimitsByLimitId
    ? Object.values(rateLimitsByLimitId)
        .map(asRecord)
        .find((record) => Boolean(record))
    : null;
  const primaryWindow = asRecord((rateLimits ?? fallbackRateLimit)?.primary);
  const usedPercent = numberFrom(primaryWindow, ['usedPercent']);

  if (usedPercent === null) {
    return {
      remainingPercent: null,
      resetLabel: '',
    };
  }

  const normalizedUsedPercent = Math.min(Math.max(Math.round(usedPercent), 0), 100);
  const resetsAt = numberFrom(primaryWindow, ['resetsAt']);

  return {
    remainingPercent: 100 - normalizedUsedPercent,
    resetLabel: formatResetLabel(resetsAt),
  };
}

function humanize(value: string) {
  if (!value) {
    return value;
  }

  if (value === 'apiKey') {
    return 'API key';
  }

  return value.replace(/[_-]/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function stringFrom(record: JsonRecord | null | undefined, keys: string[]) {
  if (!record) {
    return '';
  }

  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string') {
      return value;
    }
    if (typeof value === 'number') {
      return String(value);
    }
  }

  return '';
}

function numberFrom(record: JsonRecord | null | undefined, keys: string[]) {
  if (!record) {
    return null;
  }

  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
  }

  return null;
}

function formatResetLabel(value: number | null) {
  if (value === null) {
    return '';
  }

  const resetDate = new Date(value * 1000);
  if (Number.isNaN(resetDate.getTime())) {
    return '';
  }

  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(resetDate);
}

function asRecord(value: unknown): JsonRecord | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as JsonRecord;
  }

  return null;
}

function setError(error: unknown) {
  const raw =
    error instanceof Error
      ? error.message
      : typeof error === 'string'
        ? error
        : JSON.stringify(error) || 'Unknown error';
  errorText.value = humanizeError(raw);
}

function errorMessageForUi(error: unknown) {
  const raw =
    error instanceof Error
      ? error.message
      : typeof error === 'string'
        ? error
        : JSON.stringify(error) || 'Unknown error';
  return humanizeError(raw);
}

function humanizeError(message: string): string {
  const lower = message.toLowerCase();

  if (
    lower.includes('insufficient_quota') ||
    lower.includes('exceeded your current quota') ||
    lower.includes('quota exceeded') ||
    lower.includes('billing') ||
    lower.includes('out of credits') ||
    lower.includes('rate limit') ||
    lower.includes('ratelimit') ||
    lower.includes('too many requests') ||
    lower.includes('429')
  ) {
    return 'Your Codex / OpenAI account has hit its usage limit or rate limit. Check your billing at platform.openai.com.';
  }

  if (
    lower.includes('unauthorized') ||
    lower.includes('401') ||
    lower.includes('invalid api key')
  ) {
    return 'Authentication failed. Re-open Settings and sign in again.';
  }

  if (
    lower.includes('network') ||
    lower.includes('enotfound') ||
    lower.includes('econnrefused') ||
    lower.includes('fetch failed')
  ) {
    return 'Network error - check your internet connection and try again.';
  }

  return message;
}

function clearError() {
  errorText.value = '';
}
</script>

<style scoped lang="scss">
.app-shell {
  --background: #f5f6f4;
  --panel: #fbfbf8;
  --card: #fdfdfb;
  --text: #171b18;
  --muted: #5e6660;
  --border: #cfd8d1;
  --accent: #22624f;
  --accent-ink: #f7fbf8;
  --secondary: #dbe6df;
  --danger: #ad2f2f;
  --nav-width: 190px;

  display: grid;
  height: 100vh;
  grid-template-rows: 58px minmax(0, 1fr);
  grid-template-columns: var(--nav-width) minmax(0, 1fr);
  overflow: hidden;
  background: var(--background);
  color: var(--text);
  font-family:
    Inter,
    ui-sans-serif,
    system-ui,
    -apple-system,
    BlinkMacSystemFont,
    'Segoe UI',
    sans-serif;
}

:global(html),
:global(body),
:global(#q-app) {
  background: transparent;
}

.app-shell--drawer-hidden {
  --nav-width: 0px;
}

.top-bar {
  display: flex;
  grid-column: 2 / -1;
  grid-row: 1;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
  padding: 0 16px;
  transition: border-color 180ms ease;
  -webkit-app-region: drag;
}

button,
select,
textarea,
input,
a {
  -webkit-app-region: no-drag;
}

.app-shell--drawer-hidden .top-bar {
  grid-column: 1 / -1;
}

.top-title {
  overflow: hidden;
  color: var(--text);
  font-size: 1rem;
  font-weight: 750;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-rail {
  display: flex;
  grid-column: 1;
  grid-row: 1 / -1;
  min-width: 0;
  height: 100%;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
  border-right: 1px solid var(--border);
  background: #dde8df;
  padding: 16px 12px;
  overflow-x: hidden;
  overflow-y: auto;
  opacity: 1;
  transition:
    opacity 160ms ease,
    padding 220ms cubic-bezier(0.22, 1, 0.36, 1);
}

.app-shell--drawer-hidden .nav-rail {
  border-right-color: transparent;
  opacity: 0;
  padding-right: 0;
  padding-left: 0;
  pointer-events: none;
}

.menu-toggle {
  display: inline-flex;
  width: 44px;
  height: 44px;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--card);
  color: var(--text);
  cursor: pointer;
  padding: 0;
  -webkit-app-region: no-drag;
}

.widget-mode-toggle {
  display: inline-flex;
  width: 42px;
  height: 42px;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  justify-self: end;
  border: 1px solid #c9d5cc;
  border-radius: 8px;
  background: #dde8df;
  color: #1d4f2c;
  cursor: pointer;
  padding: 0;
  -webkit-app-region: no-drag;
}

.widget-mode-toggle:hover {
  border-color: #adc0b2;
  background: #d3e0d6;
}

.window-controls {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
  -webkit-app-region: no-drag;
}

.window-control {
  display: inline-flex;
  width: 32px;
  height: 32px;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  padding: 0;
}

.window-control:hover {
  border-color: var(--border);
  background: var(--secondary);
  color: var(--text);
}

.window-control--close:hover {
  border-color: #d58b8b;
  background: #f2d3d3;
  color: #8e2020;
}

.nav-item {
  display: grid;
  width: 100%;
  height: 44px;
  grid-template-columns: 22px 1fr;
  gap: 10px;
  align-items: center;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font: inherit;
  font-size: 0.93rem;
  font-weight: 700;
  letter-spacing: 0;
  padding: 0 11px;
  text-align: left;
}

.nav-item:hover,
.nav-item--active,
.menu-toggle:hover {
  border-color: var(--border);
  background: var(--secondary);
  color: var(--text);
}

.drawer-section {
  display: grid;
  gap: 10px;
  margin-top: 8px;
}

.drawer-dropdown {
  grid-template-columns: minmax(0, 1fr) 16px;
  height: auto;
  padding-top: 10px;
  padding-bottom: 10px;
}

.drawer-dropdown__label {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.drawer-dropdown-panel {
  display: grid;
  gap: 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: rgba(251, 251, 248, 0.8);
  padding: 14px;
}

.drawer-heading {
  display: flex;
  align-items: center;
  gap: 8px;
}

.info-button {
  position: relative;
  display: inline-flex;
  width: 22px;
  height: 22px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--muted);
  cursor: help;
  padding: 0;
}

.info-button::after {
  content: attr(data-tooltip);
  position: absolute;
  top: calc(100% + 8px);
  left: 50%;
  z-index: 12;
  width: 220px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: rgba(23, 27, 24, 0.96);
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.18);
  color: #f7fbf8;
  font-size: 0.78rem;
  font-weight: 500;
  line-height: 1.4;
  opacity: 0;
  padding: 9px 10px;
  pointer-events: none;
  text-align: left;
  transform: translateX(-50%) translateY(-4px);
  transition:
    opacity 140ms ease,
    transform 140ms ease;
}

.info-button:hover::after,
.info-button:focus-visible::after {
  opacity: 1;
  transform: translateX(-50%) translateY(0);
}

.info-button:hover {
  background: rgba(34, 98, 79, 0.08);
  color: var(--accent);
}

.eyebrow,
.label {
  display: block;
  margin: 0 0 6px;
  color: var(--muted);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

h1,
h2 {
  margin: 0;
  line-height: 1.08;
}

h1 {
  font-size: 1.55rem;
}

h2 {
  overflow-wrap: anywhere;
  font-size: 1.05rem;
}

.account-state {
  overflow-wrap: anywhere;
  font-size: 0.92rem;
}

.full-width {
  width: 100%;
}

.select-control {
  width: 100%;
  height: 38px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--card);
  color: var(--text);
  font: inherit;
  padding: 0 10px;
}

.select-control:focus {
  border-color: var(--accent);
  outline: 2px solid #b8d0c4;
  outline-offset: 1px;
}

.text-control {
  width: 100%;
  height: 38px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--card);
  color: var(--text);
  font: inherit;
  padding: 0 10px;
}

.text-control:focus {
  border-color: var(--accent);
  outline: 2px solid #b8d0c4;
  outline-offset: 1px;
}

.directory-path {
  margin: 7px 0 0;
  color: var(--muted);
  font-size: 0.82rem;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.file-list {
  display: grid;
  align-content: start;
  gap: 4px;
  min-height: 0;
  margin: 0;
  overflow: auto;
  padding: 0;
  list-style: none;
}

.file-list li {
  display: grid;
  grid-template-columns: 18px 1fr;
  gap: 7px;
  align-items: center;
  min-height: 26px;
  color: #29302b;
  font-size: 0.87rem;
}

.file-list span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-directory {
  margin: 0;
  color: var(--muted);
  font-size: 0.9rem;
  line-height: 1.4;
}

.directory-footer {
  display: flex;
  justify-content: flex-end;
}

.directory-footer--stacked {
  justify-content: flex-start;
}

.directory-change-button:global(.dc-button--size-sm) {
  min-height: 28px;
  padding: 0 8px;
}

.directory-name {
  font-size: 1.15rem;
  font-weight: 800;
}

.directory-contents-card {
  display: grid;
  gap: 12px;
  max-height: 320px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.55);
  overflow: auto;
  padding: 12px;
}

.drawer-dropdown-panel--plain {
  border: none;
  background: transparent;
  padding: 2px 0 0;
  gap: 2px;
  margin-top: -4px;
}

.conversation-list {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.conversation-item {
  display: block;
  width: 100%;
  overflow: hidden;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font: inherit;
  font-size: 0.88rem;
  font-weight: 600;
  padding: 5px 9px 5px 0;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition:
    background 120ms ease,
    color 120ms ease;
}

.conversation-item:hover {
  background: var(--secondary);
  color: var(--text);
}

.nav-info-icon {
  position: relative;
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  color: var(--muted);
  opacity: 0.7;
}

.nav-info-icon::after {
  content: attr(data-tooltip);
  position: absolute;
  bottom: calc(100% + 8px);
  left: 50%;
  z-index: 12;
  width: 220px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: rgba(23, 27, 24, 0.96);
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.18);
  color: #f7fbf8;
  font-size: 0.78rem;
  font-weight: 500;
  line-height: 1.4;
  opacity: 0;
  padding: 9px 10px;
  pointer-events: none;
  text-align: left;
  transform: translateX(-50%) translateY(4px);
  transition:
    opacity 140ms ease,
    transform 140ms ease;
  white-space: normal;
}

.nav-info-icon:hover::after {
  opacity: 1;
  transform: translateX(-50%) translateY(0);
}

.chat-area {
  position: relative;
  display: grid;
  grid-column: 2 / -1;
  grid-row: 2;
  min-width: 0;
  height: 100%;
  grid-template-rows: minmax(0, 1fr) auto auto auto;
  overflow: hidden;
  background: var(--background);
}

.settings-area {
  display: grid;
  grid-column: 2 / -1;
  grid-row: 2;
  height: 100%;
  place-items: start center;
  overflow: auto;
  background: var(--background);
  padding: 42px clamp(24px, 6vw, 84px);
}

.settings-panel {
  display: grid;
  width: min(720px, 100%);
  gap: 18px;
}

.settings-panel h2 {
  font-size: 1.8rem;
}

.settings-card {
  display: grid;
  gap: 22px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel);
  padding: 22px;
}

.settings-card-header {
  display: grid;
  gap: 6px;
}

.settings-card-header h3 {
  margin: 0;
  font-size: 1.2rem;
}

.hybrid-settings {
  display: grid;
  gap: 18px;
  border-top: 1px solid var(--border);
  padding-top: 18px;
}

.settings-field {
  display: grid;
  gap: 8px;
}

.settings-textarea {
  width: 100%;
  min-height: 180px;
  resize: vertical;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--card);
  color: var(--text);
  font: inherit;
  line-height: 1.5;
  padding: 12px;
}

.settings-textarea:focus {
  border-color: var(--accent);
  outline: 2px solid #b8d0c4;
  outline-offset: 1px;
}

.account-details {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin: 0;
}

.account-details div {
  display: grid;
  gap: 4px;
}

.account-details dt {
  color: var(--muted);
  font-size: 0.74rem;
  font-weight: 700;
  text-transform: uppercase;
}

.account-details dd {
  margin: 0;
  overflow-wrap: anywhere;
  font-weight: 650;
}

.account-usage {
  display: grid;
  gap: 8px;
  margin-top: -4px;
  border-top: 1px solid var(--rule);
  padding-top: 16px;
}

.account-usage__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.account-usage__label {
  color: var(--muted);
  font-size: 0.74rem;
  font-weight: 700;
  text-transform: uppercase;
}

.account-usage__value {
  color: var(--accent);
  font-size: 0.92rem;
  font-weight: 750;
  white-space: nowrap;
}

.account-usage__track {
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--secondary);
}

.account-usage__fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
  transition: width 260ms ease;
}

.account-usage__meta {
  margin: 0;
  color: var(--muted);
  font-size: 0.78rem;
}

.settings-help {
  margin: 0;
  color: var(--muted);
  font-size: 0.86rem;
  font-style: italic;
  line-height: 1.5;
}

.inline-link {
  border: 0;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  font: inherit;
  font-weight: 700;
  padding: 0;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.settings-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-start;
}

.settings-status {
  margin: 0;
  color: var(--muted);
  font-size: 0.85rem;
}

.settings-status--success {
  color: var(--accent);
  font-weight: 700;
}

.skills-section {
  display: grid;
  gap: 14px;
  padding-top: 6px;
}

.skills-section + .skills-section {
  border-top: 1px solid var(--border);
  padding-top: 22px;
}

.skills-section-header {
  display: grid;
  gap: 6px;
}

.skills-section-header code,
.skills-item code {
  overflow-wrap: anywhere;
  color: var(--muted);
  font-size: 0.8rem;
}

.skills-list {
  display: grid;
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.skills-name-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.skills-name-item {
  color: var(--text);
  font-weight: 650;
}

.skills-item {
  display: grid;
  gap: 6px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--card);
  padding: 14px;
}

.skills-item-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.skills-item p {
  margin: 0;
  color: var(--muted);
  line-height: 1.45;
}

.skills-editor {
  min-height: 180px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 0.84rem;
}

.chat-overlay-actions {
  position: absolute;
  top: 14px;
  right: 16px;
  z-index: 6;
  display: flex;
  align-items: center;
  gap: 8px;
  -webkit-app-region: no-drag;
}

.chat-overlay-button {
  display: inline-flex;
  width: 36px;
  height: 36px;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--card);
  color: var(--text);
  cursor: pointer;
  padding: 0;
  -webkit-app-region: no-drag;
}

.chat-overlay-button--left {
  position: absolute;
  top: 14px;
  left: 16px;
  z-index: 6;
}

.chat-overlay-button:hover {
  border-color: #9fb8ad;
  background: var(--secondary);
}

.messages {
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
  padding: 64px clamp(20px, 5vw, 76px) 24px;
}

.empty-state {
  max-width: 520px;
  margin: auto;
  color: var(--muted);
  font-size: 1.08rem;
  line-height: 1.5;
  text-align: center;
}

.message {
  max-width: min(760px, 88%);
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--card);
  padding: 12px 14px;
}

.message span {
  display: block;
  margin-bottom: 6px;
  color: var(--muted);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.message pre {
  margin: 0;
  overflow-x: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 0.92rem;
  line-height: 1.5;
  white-space: pre-wrap;
}

.message--user {
  align-self: flex-end;
  border-color: #9fb8ad;
  background: #edf5f1;
}

.message--assistant {
  align-self: flex-start;
}

.message--tool,
.message--system {
  max-width: min(900px, 100%);
  background: #e9ece8;
}

.thinking {
  display: inline-flex;
  align-self: flex-start;
  gap: 0.08em;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--card);
  color: var(--muted);
  font-weight: 750;
  padding: 10px 13px;
}

.thinking span {
  display: inline-block;
  transform-origin: 50% 55%;
}

.approval-strip {
  display: grid;
  gap: 10px;
  border-top: 1px solid var(--border);
  background: #f1f1ec;
  padding: 14px clamp(20px, 5vw, 76px);
}

.approval {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--card);
  padding: 12px;
}

.approval p {
  margin: 4px 0 0;
  color: var(--muted);
  white-space: pre-wrap;
}

.approval-actions {
  display: flex;
  flex-shrink: 0;
  gap: 8px;
}

.composer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 42px 42px;
  gap: 10px;
  align-items: end;
  border-top: 1px solid var(--border);
  background: var(--panel);
  padding: 16px clamp(20px, 5vw, 76px);
}

.composer--dragging .composer-input-wrap {
  border-color: var(--accent);
  background: #eef6f1;
}

.composer-input-wrap {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--card);
  overflow: hidden;
}

.file-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  padding: 10px 11px 0;
}

.file-chip {
  max-width: 260px;
  overflow: hidden;
  border: 1px solid #8fb2a3;
  border-radius: 8px;
  background: #e3f2eb;
  color: var(--accent);
  font-size: 0.82rem;
  font-weight: 800;
  padding: 4px 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer-input {
  width: 100%;
  max-height: 180px;
  resize: vertical;
  border: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  line-height: 1.45;
  padding: 11px 12px;
}

.composer-input:focus {
  outline: none;
}

.composer-input-wrap:focus-within {
  border-color: var(--accent);
  outline: 2px solid #b8d0c4;
  outline-offset: 1px;
}

.send-button:disabled {
  background: #d5d9d6;
  color: #7c847e;
  cursor: not-allowed;
}

.error-text {
  margin: 0;
  border-top: 1px solid #e7b8b8;
  background: #f7e7e7;
  color: #8e2020;
  padding: 10px clamp(20px, 5vw, 76px);
}

.widget-launcher {
  position: absolute;
  right: 26px;
  bottom: 22px;
  z-index: 20;
  width: 220px;
  height: 220px;
  pointer-events: none;
  -webkit-app-region: no-drag;
}

.widget-launcher--collapsed {
  width: 92px;
  height: 92px;
}

.widget-orb {
  pointer-events: auto;
  -webkit-app-region: no-drag;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 999px;
  background: #22624f;
  box-shadow: 0 8px 24px rgba(10, 31, 25, 0.28);
  color: #f8fffb;
  cursor: pointer;
  padding: 0;
  touch-action: none;
  user-select: none;
}

.widget-orb:hover {
  transform: translateY(-1px);
}

.widget-orb--main {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 82px;
  height: 82px;
}

.widget-orb--expand {
  position: absolute;
  right: -2px;
  bottom: 58px;
  z-index: 2;
  width: 26px;
  height: 26px;
  background: rgba(34, 98, 79, 0.9);
  box-shadow: 0 2px 8px rgba(10, 31, 25, 0.28);
}

.widget-orb--expand:hover {
  background: rgba(25, 77, 62, 0.95);
}

.widget-orb--menu {
  position: absolute;
  right: 88px;
  bottom: 21px;
  width: 40px;
  height: 40px;
  background:
    radial-gradient(circle at 32% 28%, #ffffff 0 9%, transparent 10%),
    linear-gradient(145deg, #e7f1ec, #c3d5cb);
  color: #15392f;
  box-shadow: 0 4px 12px rgba(10, 31, 25, 0.18);
}

.widget-orb--menu:hover {
  background: linear-gradient(145deg, #d3e0d6, #b5c9bf);
}

.widget-nav-drawer {
  position: absolute;
  right: 86px;
  bottom: 70px;
  z-index: 3;
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 160px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: rgba(245, 246, 244, 0.98);
  box-shadow: 0 8px 24px rgba(10, 31, 25, 0.16);
  overflow: hidden;
  padding: 6px;
  pointer-events: auto;
  -webkit-app-region: no-drag;
}

.widget-nav-item {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 9px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  font: inherit;
  font-size: 0.88rem;
  font-weight: 650;
  padding: 9px 10px;
  text-align: left;
  transition: background 120ms ease;
}

.widget-nav-item:hover {
  background: var(--secondary);
}

.widget-nav-item--active {
  background: var(--secondary);
  color: var(--accent);
}

.app-shell--widget {
  position: relative;
  display: block;
  height: 100vh;
  overflow: hidden;
  background: transparent;
}

.app-shell--widget .top-bar,
.app-shell--widget .nav-rail {
  display: none;
}

.app-shell--widget .chat-area,
.app-shell--widget .settings-area {
  position: absolute;
  top: 22px;
  right: 176px;
  bottom: 116px;
  left: 24px;
  display: grid;
  overflow: auto;
  border-radius: 24px;
  background: rgba(245, 246, 244, 0.96);
}

.app-shell--widget .chat-area {
  grid-template-rows: minmax(0, 1fr) auto auto auto;
  overflow: hidden;
}

.app-shell--widget .settings-area {
  place-items: start stretch;
  align-content: start;
  padding: 22px;
  -webkit-app-region: drag;
}

.app-shell--widget .settings-area * {
  -webkit-app-region: no-drag;
}

.app-shell--widget .settings-panel {
  width: 100%;
}

.app-shell--widget .settings-panel h2 {
  font-size: 1.35rem;
}

.app-shell--widget .settings-card {
  padding: 16px;
}

.app-shell--widget .account-details {
  grid-template-columns: 1fr;
}

.app-shell--widget .messages {
  padding: 18px;
}

.app-shell--widget .empty-state {
  max-width: 320px;
  font-size: 0.95rem;
}

.app-shell--widget .message {
  max-width: 94%;
}

.app-shell--widget .approval-strip,
.app-shell--widget .composer,
.app-shell--widget .error-text {
  padding-right: 18px;
  padding-left: 18px;
}

.app-shell--widget .composer {
  grid-template-columns: minmax(0, 1fr) 40px 40px;
  padding-top: 12px;
  padding-bottom: 12px;
}

.app-shell--widget .composer-input {
  max-height: 108px;
}

.app-shell--widget-collapsed .chat-area,
.app-shell--widget-collapsed .settings-area {
  display: none;
}

.spin {
  animation: spin 800ms linear infinite;
}

.toast {
  position: fixed;
  top: 18px;
  right: 18px;
  z-index: 40;
  border: 1px solid #95b7a7;
  border-radius: 10px;
  background: rgba(232, 245, 236, 0.98);
  box-shadow: 0 10px 26px rgba(18, 45, 34, 0.16);
  color: #1b4f3a;
  padding: 12px 14px;
}

.toast strong {
  display: block;
  font-size: 0.92rem;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

:global(.dc-button) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: 8px;
  border: 1px solid transparent;
  cursor: pointer;
  font: inherit;
  font-size: 0.9rem;
  font-weight: 650;
  letter-spacing: 0;
  transition:
    background-color 140ms ease,
    border-color 140ms ease,
    color 140ms ease;
}

:global(.dc-button:disabled) {
  cursor: not-allowed;
  opacity: 0.7;
}

:global(.dc-button--default) {
  background: var(--accent);
  color: var(--accent-ink);
}

:global(.dc-button--default:hover:not(:disabled)) {
  background: #194d3e;
}

:global(.dc-button--secondary) {
  border-color: var(--border);
  background: var(--secondary);
  color: var(--text);
}

:global(.dc-button--ghost) {
  background: transparent;
  color: var(--text);
}

:global(.dc-button--outline) {
  border-color: var(--border);
  background: transparent;
  color: var(--text);
}

:global(.dc-button--destructive) {
  background: var(--danger);
  color: #fff8f8;
}

:global(.dc-button--size-default) {
  min-height: 38px;
  padding: 0 13px;
}

:global(.dc-button--size-sm) {
  min-height: 32px;
  padding: 0 10px;
}

:global(.dc-button--size-icon) {
  width: 42px;
  height: 42px;
  padding: 0;
}

@media (max-width: 860px) {
  .app-shell {
    --nav-width: 58px;

    height: auto;
    min-height: 100vh;
    grid-template-rows: 58px auto auto;
    grid-template-columns: min(var(--nav-width), 58px) minmax(0, 1fr);
    overflow: visible;
  }

  .nav-rail {
    position: sticky;
    top: 0;
    height: 100vh;
    grid-column: 1;
    grid-row: 1 / -1;
    padding: 12px 7px;
  }

  .nav-item span {
    display: none;
  }

  .chat-area {
    grid-column: 2;
    grid-row: 2;
    height: 72vh;
  }

  .settings-area {
    grid-column: 2;
    grid-row: 2;
    min-height: 100vh;
    padding: 24px;
  }

  .account-details {
    grid-template-columns: 1fr;
  }

  .approval {
    align-items: stretch;
    flex-direction: column;
  }

  .app-shell--widget {
    position: relative;
    display: block;
    height: 100vh;
    min-height: 0;
    overflow: hidden;
    background: transparent;
  }

  .app-shell--widget .top-bar,
  .app-shell--widget .nav-rail {
    display: none;
  }

  .app-shell--widget .chat-area,
  .app-shell--widget .settings-area {
    top: 22px;
    right: 176px;
    bottom: 116px;
    left: 24px;
    height: auto;
  }
}

/* Baba Chat visual system: warm paper, ink, and a single saffron signal. */
.app-shell {
  --background: #eee8dd;
  --panel: #f7f1e7;
  --card: #fbf7ef;
  --text: #2f2b27;
  --muted: #756c61;
  --border: #d2c5b4;
  --accent: #ae642d;
  --accent-ink: #fff6e9;
  --secondary: #e5dac9;
  --danger: #a84b40;
  --rule: #d7cabb;
  --sage: #65715f;
  --nav-width: 214px;

  background: var(--background);
  color: var(--text);
  font-family: 'Avenir Next', Avenir, 'Helvetica Neue', Helvetica, sans-serif;
  letter-spacing: 0.005em;
}

.app-shell--drawer-hidden {
  --nav-width: 0px;
}

.top-bar {
  gap: 10px;
  border-bottom-color: var(--rule);
  background: var(--panel);
  padding: 0 18px;
}

.top-brand-mark {
  display: inline-flex;
  width: 30px;
  height: 30px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--accent);
  border-radius: 50%;
  color: var(--accent);
  font-family:
    Iowan Old Style,
    Baskerville,
    'Times New Roman',
    serif;
  font-size: 1.1rem;
  font-weight: 600;
  line-height: 1;
}

.top-title-group {
  display: grid;
  gap: 1px;
  min-width: 0;
}

.top-title {
  font-family:
    Iowan Old Style,
    Baskerville,
    'Times New Roman',
    serif;
  font-size: 1.08rem;
  font-weight: 600;
  letter-spacing: 0.015em;
}

.top-subtitle {
  overflow: hidden;
  color: var(--muted);
  font-size: 0.67rem;
  letter-spacing: 0.08em;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}

.nav-rail {
  gap: 9px;
  border-right-color: var(--rule);
  background: #e2d7c6;
  padding: 21px 14px 16px;
}

.brand-lockup {
  display: grid;
  gap: 5px;
  margin: 0 8px 18px;
  padding: 3px 0 15px;
}

.brand-lockup__overline,
.brand-lockup__caption {
  color: var(--muted);
  font-size: 0.65rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.brand-lockup__name {
  color: var(--text);
  font-family:
    Iowan Old Style,
    Baskerville,
    'Times New Roman',
    serif;
  font-size: 1.45rem;
  font-weight: 600;
  letter-spacing: -0.02em;
}

.brand-lockup__rule {
  width: 42px;
  height: 1px;
  margin: 5px 0 3px;
  background: var(--accent);
}

.nav-item {
  border-radius: 4px;
  color: #665e54;
  font-size: 0.84rem;
  letter-spacing: 0.01em;
}

.nav-item:hover,
.nav-item--active,
.menu-toggle:hover {
  border-color: #c8b8a5;
  background: #ede4d6;
  color: var(--text);
}

.drawer-section {
  gap: 8px;
  margin-top: 9px;
}

.drawer-dropdown-panel {
  border-color: var(--border);
  border-radius: 4px;
  background: rgba(249, 243, 233, 0.72);
  padding: 13px;
}

.directory-contents-card {
  border-color: var(--border);
  border-radius: 3px;
  background: rgba(250, 246, 238, 0.68);
}

.conversation-item:hover {
  background: #ede4d6;
  color: var(--text);
}

.menu-toggle,
.window-control,
.chat-overlay-button,
.widget-mode-toggle {
  border-color: var(--border);
  background: transparent;
  color: var(--text);
}

.menu-toggle:hover,
.chat-overlay-button:hover,
.widget-mode-toggle:hover {
  border-color: #b99a7d;
  background: var(--secondary);
  color: var(--accent);
}

.window-control:hover {
  border-color: var(--border);
  background: var(--secondary);
  color: var(--text);
}

.window-control--close:hover {
  border-color: #c99991;
  background: #ead5cf;
  color: #8f3d35;
}

.chat-area,
.settings-area {
  background: var(--background);
}

.chat-area {
  grid-template-rows: auto auto minmax(0, 1fr) auto auto auto;
}

.chat-area--terminal {
  grid-template-rows: auto minmax(0, 1fr) auto auto auto;
}

.chat-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 32px;
  min-width: 0;
  border-bottom: 1px solid var(--rule);
  background: #f0e9de;
  padding: clamp(24px, 4vw, 42px) clamp(22px, 5vw, 76px) 18px;
}

.chat-header-copy {
  min-width: 0;
  max-width: 470px;
}

.chat-header-copy h1 {
  margin: 0;
  color: var(--text);
  font-family:
    Iowan Old Style,
    Baskerville,
    'Times New Roman',
    serif;
  font-size: clamp(2.25rem, 4.2vw, 4.25rem);
  font-weight: 500;
  letter-spacing: -0.055em;
  line-height: 0.98;
}

.chat-header-copy p {
  max-width: 390px;
  margin: 13px 0 0;
  color: var(--muted);
  font-size: 0.92rem;
  line-height: 1.55;
}

.chat-header-controls {
  display: flex;
  min-width: min(460px, 48%);
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
}

.scope-picker {
  width: 100%;
  max-width: 460px;
  margin: 0;
  border: 0;
  padding: 0;
}

.scope-picker legend {
  width: 100%;
  margin-bottom: 6px;
  color: var(--muted);
  font-size: 0.66rem;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.scope-picker__options {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  border: 0;
  background: transparent;
  overflow: visible;
}

.scope-option {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  justify-content: flex-start;
  gap: 7px;
  border: 0;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font: inherit;
  font-size: 0.78rem;
  font-weight: 700;
  padding: 0;
  transition: color 140ms ease;
}

.scope-option:hover {
  color: var(--text);
}

.scope-option--active {
  background: transparent;
  color: var(--text);
  font-weight: 750;
}

.scope-option--active:hover {
  background: transparent;
  color: var(--text);
}

.scope-option__info {
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
  color: var(--muted);
}

.scope-option__info::after {
  top: calc(100% + 8px);
  right: -8px;
  left: auto;
  width: min(260px, calc(100vw - 32px));
  transform: translateY(-4px);
}

.scope-option__info:hover::after,
.scope-option__info:focus-visible::after {
  transform: translateY(0);
}

.scope-option__info:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.scope-picker__help {
  display: block;
  margin-top: 6px;
  color: var(--muted);
  font-size: 0.72rem;
  text-align: right;
}

.terminal-mode-control {
  display: inline-flex;
  min-height: 34px;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font: inherit;
  font-size: 0.76rem;
  font-weight: 700;
  padding: 0 10px;
  transition:
    background-color 140ms ease,
    border-color 140ms ease,
    color 140ms ease;
}

.terminal-mode-control:hover,
.terminal-mode-control--active {
  border-color: #b99a7d;
  background: #eee2d2;
  color: var(--accent);
}

.terminal-panel {
  box-sizing: border-box;
  min-height: 0;
  overflow: hidden;
  border-bottom: 1px solid var(--rule);
  background: #e8ddcc;
  padding: 18px clamp(22px, 5vw, 76px);
}

.terminal-panel :deep(.codex-terminal) {
  height: 100%;
}

.terminal-placeholder {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 13px;
  border-bottom: 1px solid var(--rule);
  background: #e8ddcc;
  padding: 13px clamp(22px, 5vw, 76px);
}

.terminal-placeholder__mark {
  display: inline-flex;
  width: 36px;
  height: 36px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--accent);
  border-radius: 50%;
  color: var(--accent);
}

.terminal-placeholder__copy {
  min-width: 0;
}

.terminal-placeholder__copy .eyebrow {
  margin-bottom: 3px;
}

.terminal-placeholder__copy h2 {
  margin: 0;
  font-family:
    Iowan Old Style,
    Baskerville,
    'Times New Roman',
    serif;
  font-size: 1.25rem;
  font-weight: 600;
}

.terminal-placeholder__copy p {
  margin: 3px 0 0;
  color: var(--muted);
  font-size: 0.79rem;
  line-height: 1.45;
}

.terminal-placeholder__copy code {
  color: var(--text);
  font-size: 0.78rem;
}

.terminal-placeholder__badge {
  border: 1px solid #c3ae95;
  border-radius: 999px;
  color: var(--muted);
  font-size: 0.62rem;
  font-weight: 800;
  letter-spacing: 0.1em;
  padding: 5px 8px;
  text-transform: uppercase;
  white-space: nowrap;
}

.messages {
  gap: 18px;
  background: var(--background);
  padding: 28px clamp(22px, 5vw, 76px) 30px;
}

.empty-state {
  max-width: 680px;
  margin: auto;
  color: var(--muted);
  text-align: left;
}

.empty-state__seal {
  display: inline-flex;
  width: 52px;
  height: 52px;
  align-items: center;
  justify-content: center;
  margin-bottom: 22px;
  border: 1px solid var(--accent);
  border-radius: 50%;
  color: var(--accent);
  font-family:
    Iowan Old Style,
    Baskerville,
    'Times New Roman',
    serif;
  font-size: 1.7rem;
  line-height: 1;
}

.empty-state h2 {
  margin: 0;
  color: var(--text);
  font-family:
    Iowan Old Style,
    Baskerville,
    'Times New Roman',
    serif;
  font-size: clamp(2rem, 4vw, 3.35rem);
  font-weight: 500;
  letter-spacing: -0.045em;
}

.empty-state p {
  max-width: 600px;
  margin: 13px 0 0;
  font-size: 0.98rem;
  line-height: 1.65;
}

.empty-state__notes {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 28px;
  border-top: 1px solid var(--rule);
  padding-top: 13px;
  color: var(--text);
  font-size: 0.72rem;
  font-weight: 700;
  line-height: 1.4;
}

.empty-state__notes span {
  display: grid;
  gap: 4px;
}

.empty-state__notes strong {
  color: var(--accent);
  font-size: 0.65rem;
  letter-spacing: 0.1em;
}

.message {
  max-width: min(860px, 88%);
  border: 0;
  border-top: 1px solid var(--rule);
  border-radius: 0;
  background: transparent;
  padding: 16px 19px;
}

.message--user {
  border-top-color: #c09b78;
  border-right: 3px solid var(--accent);
  background: #e5d7c3;
  padding-right: 21px;
}

.message--assistant {
  border-left: 2px solid var(--sage);
}

.message--tool,
.message--system {
  background: #e6dfd4;
}

.message-meta {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 8px;
}

.message-role {
  color: var(--muted);
  font-size: 0.67rem;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.message pre {
  color: var(--text);
  font-family: inherit;
  font-size: 0.96rem;
  line-height: 1.65;
}

.message--tool pre {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 0.83rem;
}

.thinking {
  border: 0;
  border-left: 2px solid var(--sage);
  border-radius: 0;
  background: transparent;
  color: var(--muted);
  padding: 10px 13px;
}

.approval-strip {
  border-top-color: var(--rule);
  background: #e8ddcc;
  padding: 13px clamp(22px, 5vw, 76px);
}

.approval {
  border-color: var(--border);
  border-radius: 4px;
  background: #f6efe4;
  padding: 13px;
}

.approval p {
  color: var(--muted);
}

.composer {
  gap: 9px;
  border-top-color: var(--rule);
  background: var(--panel);
  padding: 14px clamp(22px, 5vw, 76px) 19px;
}

.composer--dragging .composer-input-wrap {
  border-color: var(--accent);
  background: #f5e7d4;
}

.composer-input-wrap {
  border-color: var(--border);
  border-radius: 4px;
  background: #fbf7ef;
}

.composer-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid #e3d8c8;
  color: var(--accent);
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.03em;
  padding: 8px 12px 7px;
}

.composer-meta strong {
  color: var(--text);
}

.composer-meta__hint {
  color: var(--muted);
  font-size: 0.65rem;
  font-weight: 600;
  letter-spacing: 0;
}

.composer-meta__warning {
  color: var(--danger);
}

.composer--source-blocked .composer-input-wrap {
  border-color: #d8c6b2;
  background: #f3ede4;
}

.composer--source-blocked .composer-input {
  color: var(--muted);
  cursor: not-allowed;
}

.composer-input {
  color: var(--text);
  font-family: inherit;
  font-size: 0.93rem;
  padding: 12px;
}

.composer-input-wrap:focus-within {
  border-color: var(--accent);
  outline-color: #c8a27e;
}

.file-chip {
  border-color: #c29d77;
  border-radius: 3px;
  background: #f0e0c9;
  color: #884b27;
}

.error-text {
  border-top-color: #d8aaa0;
  background: #f2ded8;
  color: #863e36;
  padding-right: clamp(22px, 5vw, 76px);
  padding-left: clamp(22px, 5vw, 76px);
}

.settings-area {
  padding: 42px clamp(24px, 6vw, 84px);
}

.settings-card {
  border-color: var(--border);
  border-radius: 4px;
  background: var(--panel);
  padding: 22px;
}

.settings-textarea,
.select-control,
.text-control {
  border-color: var(--border);
  border-radius: 4px;
  background: var(--card);
  color: var(--text);
}

.settings-textarea:focus,
.select-control:focus,
.text-control:focus {
  border-color: var(--accent);
  outline-color: #c8a27e;
}

.skills-item {
  border-color: var(--border);
  border-radius: 3px;
  background: var(--card);
}

.widget-orb {
  background: var(--accent);
  box-shadow: 0 10px 24px rgba(78, 47, 24, 0.23);
  color: var(--accent-ink);
}

.widget-orb:hover {
  background: #9b5425;
}

.widget-orb--expand {
  background: #8c522c;
}

.widget-orb--expand:hover {
  background: #764323;
}

.widget-orb--menu,
.widget-orb--menu:hover {
  background: #e3d5c1;
  color: var(--text);
}

.widget-nav-drawer {
  border-color: var(--border);
  border-radius: 4px;
  background: #f5eee3;
  box-shadow: 0 10px 24px rgba(78, 47, 24, 0.16);
}

.widget-nav-item:hover,
.widget-nav-item--active {
  background: #e8dccb;
  color: var(--accent);
}

.app-shell--widget .chat-area,
.app-shell--widget .settings-area {
  border: 1px solid var(--rule);
  border-radius: 18px;
  background: #f1e9dd;
  box-shadow: 0 14px 34px rgba(78, 47, 24, 0.14);
}

.app-shell--widget .chat-area {
  grid-template-rows: auto auto minmax(0, 1fr) auto auto auto;
}

.app-shell--widget .chat-header {
  display: block;
  border-radius: 18px 18px 0 0;
  padding: 16px 18px 12px;
}

.app-shell--widget .chat-header-copy p {
  display: none;
}

.app-shell--widget .chat-header-copy h1 {
  font-size: 1.45rem;
}

.app-shell--widget .chat-header-controls {
  min-width: 0;
  align-items: stretch;
  margin-top: 13px;
}

.app-shell--widget .scope-picker__help {
  text-align: left;
}

.app-shell--widget .chat-overlay-actions {
  top: 15px;
  right: 16px;
}

.app-shell--widget .terminal-placeholder {
  grid-template-columns: auto minmax(0, 1fr);
  padding: 11px 18px;
}

.app-shell--widget .terminal-placeholder__badge {
  display: none;
}

.app-shell--widget .messages {
  padding: 18px;
}

.app-shell--widget .empty-state {
  max-width: 360px;
}

button:focus-visible,
select:focus-visible,
textarea:focus-visible,
input:focus-visible,
[role='radio']:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
}

@media (max-width: 860px) {
  .app-shell {
    --nav-width: 58px;
  }

  .nav-rail {
    padding: 12px 7px;
  }

  .brand-lockup {
    margin-bottom: 10px;
  }

  .chat-header {
    align-items: stretch;
    flex-direction: column;
    gap: 20px;
  }

  .chat-header-controls {
    min-width: 0;
    align-items: stretch;
  }

  .scope-picker__help {
    text-align: left;
  }

  .terminal-mode-control {
    align-self: flex-start;
  }

  .message {
    max-width: 94%;
  }
}

@media (max-width: 620px) {
  .top-subtitle {
    display: none;
  }

  .chat-header {
    padding: 22px 18px 16px;
  }

  .chat-header-copy h1 {
    font-size: 2.45rem;
  }

  .scope-option {
    gap: 5px;
    font-size: 0.7rem;
    padding-right: 6px;
    padding-left: 6px;
  }

  .terminal-placeholder {
    grid-template-columns: auto minmax(0, 1fr);
    padding-right: 18px;
    padding-left: 18px;
  }

  .terminal-placeholder__badge {
    display: none;
  }

  .messages {
    padding-right: 18px;
    padding-left: 18px;
  }

  .message {
    max-width: 100%;
  }

  .empty-state__notes {
    grid-template-columns: 1fr;
    gap: 9px;
  }

  .composer {
    padding-right: 18px;
    padding-left: 18px;
  }

  .composer-meta {
    align-items: flex-start;
    flex-direction: column;
    gap: 3px;
  }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
  }
}

/* Resilience pass: the transcript owns the flexible space and the composer stays in the frame. */
.app-shell {
  min-width: 320px;
}

.chat-area {
  display: flex;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
}

.app-shell--widget .chat-area {
  display: flex;
  min-height: 0;
  flex-direction: column;
}

.chat-area--terminal {
  display: flex;
  flex-direction: column;
}

.chat-header,
.approval-strip,
.error-text,
.composer {
  flex: 0 0 auto;
  min-width: 0;
}

.messages {
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  overflow-anchor: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.terminal-panel {
  flex: 1 1 auto;
  min-height: 0;
}

.message {
  min-width: 0;
  overflow-wrap: anywhere;
}

.message pre {
  overflow-wrap: anywhere;
  word-break: break-word;
}

.composer {
  min-height: 84px;
}

.composer-input-wrap {
  min-width: 0;
}

.composer-input {
  display: block;
  min-width: 0;
}

.error-text {
  max-height: 130px;
  overflow: auto;
  overflow-wrap: anywhere;
}

.advanced-section {
  border-top: 1px solid var(--rule);
  padding-top: 16px;
}

.advanced-section summary {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  color: var(--text);
  cursor: pointer;
  font-size: 0.86rem;
  font-weight: 800;
  list-style-position: outside;
}

.advanced-section summary::marker {
  color: var(--accent);
}

.advanced-section summary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 4px;
}

.advanced-section__summary {
  color: var(--muted);
  font-size: 0.76rem;
  font-weight: 650;
}

.advanced-section__body {
  display: grid;
  gap: 14px;
  margin-top: 18px;
}

.widget-orb {
  border: 2px solid #fff5e7;
  transition:
    background-color 140ms ease,
    box-shadow 140ms ease,
    transform 140ms ease;
}

.widget-orb:focus-visible {
  outline: 3px solid #2f2b27;
  outline-offset: 4px;
}

.widget-orb--main {
  width: 84px;
  height: 84px;
  border-width: 3px;
  background: #ae642d;
  box-shadow:
    0 0 0 5px rgba(255, 246, 233, 0.78),
    0 10px 24px rgba(78, 47, 24, 0.3);
}

.widget-orb--main:hover {
  background: #8f4e25;
  box-shadow:
    0 0 0 5px rgba(255, 246, 233, 0.9),
    0 12px 26px rgba(78, 47, 24, 0.36);
}

.widget-orb--expand {
  width: 30px;
  height: 30px;
  border-color: #fff5e7;
  background: #2f2b27;
  color: #fff6e9;
  box-shadow: 0 4px 12px rgba(47, 43, 39, 0.32);
}

.widget-orb--expand:hover {
  background: #171411;
}

.widget-launcher--collapsed .widget-orb--main {
  width: 84px;
  height: 84px;
}

/* The Electron collapsed window is 148px square. Keep the renderer itself transparent and
   contain both recovery targets inside that viewport, after every earlier widget rule. */
.app-shell.app-shell--widget.app-shell--widget-collapsed {
  --widget-collapsed-size: 148px;

  position: relative;
  display: block;
  width: var(--widget-collapsed-size);
  min-width: 0;
  max-width: var(--widget-collapsed-size);
  height: var(--widget-collapsed-size);
  min-height: 0;
  max-height: var(--widget-collapsed-size);
  overflow: hidden;
  border-radius: 0;
  background: transparent !important;
  box-shadow: none;
}

.app-shell.app-shell--widget.app-shell--widget-collapsed
  .widget-launcher.widget-launcher--collapsed {
  position: absolute;
  inset: 0;
  z-index: 100;
  display: block;
  width: var(--widget-collapsed-size);
  height: var(--widget-collapsed-size);
  background: transparent;
  pointer-events: none;
}

.app-shell.app-shell--widget.app-shell--widget-collapsed
  .widget-launcher.widget-launcher--collapsed
  .widget-orb {
  visibility: visible;
  opacity: 1;
  pointer-events: auto;
}

.app-shell.app-shell--widget.app-shell--widget-collapsed
  .widget-launcher.widget-launcher--collapsed
  .widget-orb--expand {
  top: 14px;
  right: 14px;
  bottom: auto;
  z-index: 3;
  width: 30px;
  height: 30px;
  border: 2px solid #fff6e9;
  background: #2f2b27;
  color: #fff6e9;
  box-shadow: 0 4px 12px rgba(47, 43, 39, 0.42);
}

.app-shell.app-shell--widget.app-shell--widget-collapsed
  .widget-launcher.widget-launcher--collapsed
  .widget-orb--main {
  right: 14px;
  bottom: 14px;
  z-index: 2;
  width: 84px;
  height: 84px;
  border: 3px solid #fff6e9;
  background: #ae642d;
  color: #fff6e9;
  box-shadow:
    0 0 0 5px rgba(255, 246, 233, 0.84),
    0 10px 24px rgba(47, 43, 39, 0.42);
}

.app-shell.app-shell--widget.app-shell--widget-collapsed
  .widget-launcher.widget-launcher--collapsed
  .widget-orb--main:hover {
  background: #8f4e25;
}

@media (max-width: 620px) {
  .composer {
    min-height: 92px;
  }

  .advanced-section summary {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .widget-orb:hover,
  .widget-orb--main:hover {
    transform: none;
  }
}

.nav-rail {
  position: relative;
}

.nav-resize-handle {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 12;
  width: 10px;
  cursor: col-resize;
  touch-action: none;
}

.nav-resize-handle::after {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 4px;
  width: 1px;
  background: transparent;
  content: '';
  transition: background-color 140ms ease;
}

.nav-resize-handle:hover::after,
.app-shell--nav-resizing .nav-resize-handle::after {
  background: var(--accent);
}

.app-shell--nav-resizing {
  cursor: col-resize;
}

.app-shell--nav-resizing * {
  cursor: col-resize !important;
}

.nav-resize-handle:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

.app-shell--widget .chat-area,
.app-shell--widget .settings-area {
  border: 1px solid var(--rule);
  border-radius: 18px;
  background: #f1e9dd;
  box-shadow: 0 14px 34px rgba(78, 47, 24, 0.14);
}

.app-shell--widget .chat-header {
  border-radius: 18px 18px 0 0;
}

.app-shell.app-shell--widget {
  background: transparent !important;
}

.drawer-section {
  min-width: 0;
}

.drawer-dropdown-panel.drawer-dropdown-panel--plain {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: rgba(249, 243, 233, 0.72);
  padding: 0;
}

.conversation-list {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  padding: 7px;
}

.drawer-dropdown-panel.drawer-dropdown-panel--plain .empty-directory {
  padding: 7px;
}

.conversation-item {
  box-sizing: border-box;
  display: -webkit-box;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  line-height: 1.35;
  overflow-wrap: anywhere;
  text-overflow: ellipsis;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
}

.app-shell--widget .chat-header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 14px 9px;
}

.app-shell--widget .chat-header-copy {
  flex: 0 1 auto;
  max-width: none;
}

.app-shell--widget .chat-header-copy h1 {
  font-size: 1.35rem;
  letter-spacing: -0.035em;
  line-height: 1;
}

.app-shell--widget .chat-header-controls {
  min-width: 0;
  flex: 1 1 auto;
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px 12px;
  margin-top: 0;
}

.app-shell--widget .scope-picker {
  display: flex;
  width: auto;
  max-width: none;
  align-items: center;
}

.app-shell--widget .scope-picker legend {
  width: auto;
  margin: 0 7px 0 0;
  font-size: 0.6rem;
  letter-spacing: 0.08em;
}

.app-shell--widget .scope-picker__options {
  display: flex;
  gap: 10px;
  border: 0;
  background: transparent;
  overflow: visible;
}

.app-shell--widget .scope-option {
  min-height: 0;
  flex: 0 0 auto;
  gap: 5px;
  border: 0;
  background: transparent;
  color: var(--muted);
  font-size: 0.67rem;
  font-weight: 700;
  padding: 2px 0;
  text-decoration: none;
}

.app-shell--widget .scope-option:hover,
.app-shell--widget .scope-option--active,
.app-shell--widget .scope-option--active:hover {
  border: 0;
  background: transparent;
  color: var(--text);
}

.app-shell--widget .scope-option--active {
  font-weight: 750;
}

.app-shell--widget .terminal-mode-control {
  min-height: 0;
  gap: 5px;
  border: 0;
  background: transparent;
  color: var(--muted);
  font-size: 0.67rem;
  font-weight: 650;
  padding: 2px 0;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.app-shell--widget .terminal-mode-control:hover,
.app-shell--widget .terminal-mode-control--active {
  border: 0;
  background: transparent;
  color: var(--accent);
}

.brand-lockup {
  margin-bottom: 6px;
  padding-bottom: 6px;
}

.empty-state__description {
  max-width: 600px;
  margin: 13px 0 0;
  color: var(--muted);
  font-size: 0.98rem;
  line-height: 1.65;
}

.conversation-list {
  gap: 4px;
}

.conversation-list-item {
  position: relative;
  display: block;
  min-width: 0;
}

.conversation-item {
  position: relative;
  z-index: 1;
  width: 100%;
  padding-right: 7px;
}

.conversation-item-actions {
  display: flex;
  position: absolute;
  top: 50%;
  right: 3px;
  z-index: 2;
  align-items: flex-start;
  gap: 2px;
  border-radius: 5px;
  background: var(--panel);
  opacity: 0;
  pointer-events: none;
  transform: translateY(-50%);
  transition: opacity 120ms ease;
}

.conversation-list-item:hover .conversation-item-actions,
.conversation-list-item:focus-within .conversation-item-actions,
.conversation-list-item--pinned .conversation-item-actions {
  opacity: 1;
  pointer-events: auto;
}

.conversation-list-item:hover .conversation-item-actions {
  background: var(--secondary);
}

.conversation-item-action {
  display: inline-flex;
  width: 25px;
  height: 25px;
  flex: 0 0 25px;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  padding: 0;
}

.conversation-item-action:hover,
.conversation-item-action:focus-visible {
  border-color: var(--border);
  background: var(--secondary);
  color: var(--text);
}

.conversation-item-action--active {
  color: var(--accent);
}

.conversation-item-action--danger:hover,
.conversation-item-action--danger:focus-visible {
  border-color: #d5a39a;
  background: #f0dcd7;
  color: var(--danger);
}

.toggle-switch {
  display: inline-flex;
  width: 24px;
  height: 14px;
  flex: 0 0 24px;
  align-items: center;
  border: 1px solid currentColor;
  border-radius: 999px;
  padding: 2px;
  transition:
    background-color 140ms ease,
    border-color 140ms ease,
    color 140ms ease;
}

.toggle-switch__thumb {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
  transform: translateX(0);
  transition: transform 140ms ease;
}

.toggle-switch--active {
  border-color: var(--accent);
  background: var(--accent);
  color: var(--accent-ink);
}

.toggle-switch--active .toggle-switch__thumb {
  transform: translateX(10px);
}

@media (max-width: 620px) {
  .scope-option__toggle {
    width: 20px;
    height: 12px;
    flex-basis: 20px;
  }

  .scope-option__toggle .toggle-switch__thumb {
    width: 6px;
    height: 6px;
  }

  .scope-option__toggle.toggle-switch--active .toggle-switch__thumb {
    transform: translateX(8px);
  }
}

/* Keep the mode actions together so the terminal never replaces either escape hatch. */
.chat-overlay-actions {
  top: 12px;
  right: 16px;
  align-items: center;
  gap: 6px;
}

.chat-overlay-actions .chat-overlay-button,
.chat-overlay-actions .widget-mode-toggle {
  width: 34px;
  height: 34px;
  border-radius: 7px;
}

.chat-overlay-actions .widget-mode-toggle {
  flex: 0 0 34px;
}

.chat-overlay-actions .terminal-mode-control {
  min-height: 30px;
  gap: 6px;
  border-radius: 7px;
  border: 0;
  background: transparent;
  color: var(--muted);
  font-size: 0.72rem;
  padding: 2px 4px;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.chat-overlay-actions .terminal-mode-control svg {
  display: none;
}

.chat-overlay-actions .terminal-mode-control:hover,
.chat-overlay-actions .terminal-mode-control--active {
  border: 0;
  background: transparent;
  color: var(--accent);
}

.chat-header {
  align-items: center;
  justify-content: flex-start;
  gap: 24px;
  padding-top: 18px;
  padding-right: max(240px, clamp(22px, 5vw, 76px));
  padding-bottom: 18px;
}

.chat-header-copy h1 {
  font-size: clamp(2rem, 3.8vw, 3.5rem);
  white-space: nowrap;
}

.chat-header-copy {
  flex: 0 0 auto;
}

.chat-header-controls {
  min-width: 0;
  flex: 0 1 auto;
  flex-direction: row;
  align-items: center;
}

.scope-picker {
  display: flex;
  width: auto;
  min-width: 0;
  max-width: 100%;
  align-items: center;
}

.scope-picker legend {
  width: auto;
  margin: 0 8px 0 0;
}

.scope-picker__options {
  min-width: 0;
}

.scope-option {
  min-width: 0;
}

.terminal-panel {
  padding: 10px clamp(18px, 4vw, 56px);
}

.chat-area--terminal .chat-header {
  padding-top: 14px;
  padding-bottom: 14px;
}

.nav-rail > .nav-item {
  height: auto;
  min-height: 48px;
  padding-top: 12px;
  padding-bottom: 12px;
}

.app-shell--widget .chat-header {
  display: block;
  padding: 10px 14px 8px;
  text-align: center;
}

.app-shell--widget .chat-header-copy h1 {
  font-size: 1.35rem;
}

.app-shell--widget .chat-header-controls {
  justify-content: center;
  margin-top: 7px;
}

.app-shell--widget .scope-picker {
  justify-content: center;
}

.app-shell--widget .terminal-panel {
  padding: 8px 12px 10px;
}

.message-body {
  color: var(--text);
  font-family: inherit;
  font-size: 0.96rem;
  line-height: 1.65;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  word-break: break-word;
}

.message-body .message-text {
  display: inline;
  margin: 0;
  color: inherit;
  font-size: inherit;
  font-weight: inherit;
  letter-spacing: normal;
  text-transform: none;
  white-space: pre-wrap;
}

.message-body strong {
  font-weight: 750;
}

.message-body em {
  font-style: italic;
}

.source-link {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  gap: 5px;
  margin: 0 3px;
  border: 0;
  border-bottom: 1px solid #b77c49;
  background: transparent;
  color: #8d4d24;
  cursor: pointer;
  font: inherit;
  font-size: 0.83em;
  line-height: 1.35;
  padding: 0 1px 2px;
  text-align: left;
  vertical-align: baseline;
}

.source-link span {
  display: inline;
  margin: 0;
  overflow: hidden;
  color: inherit;
  font-size: inherit;
  font-weight: 700;
  letter-spacing: normal;
  text-overflow: ellipsis;
  text-transform: none;
  white-space: nowrap;
}

.source-link:hover,
.source-link:focus-visible {
  border-bottom-color: var(--accent);
  color: var(--accent);
  outline: none;
}

.source-reader-backdrop {
  position: fixed;
  inset: 0;
  z-index: 70;
  display: grid;
  place-items: center;
  background: rgba(35, 30, 25, 0.46);
  padding: 24px;
}

.source-reader {
  display: flex;
  width: min(920px, 100%);
  max-height: min(820px, calc(100vh - 48px));
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #c5ae92;
  background: #fbf6ed;
  box-shadow: 0 24px 70px rgba(49, 32, 18, 0.3);
  color: #302a25;
  outline: none;
}

.source-reader__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  border-bottom: 1px solid #dfcfbc;
  background: #f2e9dc;
  padding: 22px 26px 18px;
}

.source-reader__eyebrow {
  margin: 0 0 6px;
  color: #9a5c2d;
  font-size: 0.67rem;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.source-reader h2 {
  max-width: 720px;
  margin: 0;
  font-family:
    Iowan Old Style,
    Baskerville,
    'Times New Roman',
    serif;
  font-size: clamp(1.55rem, 3vw, 2.2rem);
  font-weight: 500;
  letter-spacing: -0.035em;
  line-height: 1.08;
}

.source-reader__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin: 9px 0 0;
  color: #74685d;
  font-size: 0.8rem;
  line-height: 1.4;
}

.source-reader__close {
  display: inline-flex;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  align-items: center;
  justify-content: center;
  border: 1px solid #cdbba5;
  border-radius: 50%;
  background: transparent;
  color: #665b51;
  cursor: pointer;
  padding: 0;
}

.source-reader__close:hover,
.source-reader__close:focus-visible {
  border-color: #ae642d;
  background: #e9d8c3;
  color: #7d421f;
  outline: none;
}

.source-reader__body {
  min-height: 0;
  overflow-y: auto;
  padding: 18px 26px 24px;
}

.source-reader__notice {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin-bottom: 18px;
  border-left: 2px solid #ae642d;
  color: #786a5c;
  font-size: 0.84rem;
  line-height: 1.45;
  padding: 2px 0 2px 11px;
}

.source-passages {
  display: grid;
  gap: 0;
}

.source-passage {
  border-top: 1px solid #e5d7c6;
  padding: 17px 0;
}

.source-passage:first-child {
  border-top: 0;
  padding-top: 0;
}

.source-passage--selected {
  position: relative;
  margin: 3px -13px;
  border: 1px solid #d49a62;
  background: #fff0c9;
  box-shadow: 0 7px 18px rgba(150, 94, 39, 0.09);
  padding: 17px 13px;
}

.source-passage__meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
  color: #9a5c2d;
  font-size: 0.67rem;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.source-passage__badge {
  border: 1px solid #d49a62;
  border-radius: 999px;
  background: #f6dca9;
  color: #75421e;
  font-size: 0.6rem;
  letter-spacing: 0.06em;
  padding: 3px 7px;
}

.source-passage p {
  margin: 0;
  color: #3b342e;
  font-family:
    Iowan Old Style,
    Baskerville,
    'Times New Roman',
    serif;
  font-size: 1.02rem;
  line-height: 1.72;
  white-space: pre-wrap;
}

.source-reader__state {
  display: flex;
  min-height: 230px;
  align-items: center;
  justify-content: center;
  gap: 9px;
  color: #796b5d;
  font-size: 0.9rem;
}

.source-reader__state--error {
  color: #8e3026;
  padding: 26px;
  text-align: center;
}

.source-reader__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-top: 1px solid #dfcfbc;
  background: #f2e9dc;
  padding: 12px 26px;
}

.source-reader__path {
  overflow: hidden;
  color: #8c7b6b;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  font-size: 0.7rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-reader__open-original {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  border: 0;
  background: transparent;
  color: #8d4d24;
  cursor: pointer;
  font: inherit;
  font-size: 0.77rem;
  font-weight: 750;
  padding: 5px 0;
}

.source-reader__open-original:hover,
.source-reader__open-original:focus-visible {
  color: var(--accent);
  outline: none;
  text-decoration: underline;
  text-underline-offset: 3px;
}

@media (max-width: 620px) {
  .chat-header {
    align-items: stretch;
    padding-right: 18px;
  }

  .chat-header-copy {
    max-width: 100%;
  }

  .chat-header-copy h1 {
    white-space: normal;
  }

  .chat-header-controls,
  .scope-picker,
  .scope-picker__options {
    width: 100%;
  }

  .source-reader-backdrop {
    padding: 10px;
  }

  .source-reader {
    max-height: calc(100vh - 20px);
  }

  .source-reader__header,
  .source-reader__body,
  .source-reader__footer {
    padding-right: 18px;
    padding-left: 18px;
  }

  .source-reader__footer {
    align-items: flex-start;
    flex-direction: column;
    gap: 6px;
  }

  .source-reader__path {
    max-width: 100%;
  }
}

.about-area {
  align-items: start;
}

.about-panel {
  display: grid;
  width: min(1040px, 100%);
  gap: 24px;
}

.about-header {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: 16px;
  border-bottom: 1px solid var(--rule);
  padding-bottom: 22px;
}

.about-header__mark {
  display: inline-flex;
  width: 48px;
  height: 48px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--accent);
  border-radius: 50%;
  color: var(--accent);
}

.about-header__eyebrow,
.about-source-card__eyebrow {
  margin: 0 0 6px;
  color: var(--accent);
  font-size: 0.66rem;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.about-header h1 {
  margin: 0;
  font-family: Iowan Old Style, Baskerville, 'Times New Roman', serif;
  font-size: clamp(2rem, 4vw, 3.5rem);
  font-weight: 500;
  letter-spacing: -0.045em;
  line-height: 1;
}

.about-header p:last-child {
  max-width: 680px;
  margin: 12px 0 0;
  color: var(--muted);
  font-size: 0.94rem;
  line-height: 1.6;
}

.about-source-list {
  display: grid;
  gap: 16px;
}

.about-source-card {
  display: grid;
  gap: 18px;
  border-top: 1px solid var(--border);
  padding-top: 20px;
}

.about-source-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.about-source-card h2 {
  margin: 0;
  font-family: Iowan Old Style, Baskerville, 'Times New Roman', serif;
  font-size: 1.55rem;
  font-weight: 600;
  letter-spacing: -0.025em;
}

.about-source-card__eyebrow {
  margin-bottom: 5px;
  color: var(--muted);
}

.about-source-card__mark {
  display: inline-flex;
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border);
  border-radius: 50%;
  color: var(--accent);
}

.about-source-card__description {
  max-width: 780px;
  margin: 0;
  color: var(--muted);
  font-size: 0.9rem;
  line-height: 1.55;
}

.about-book-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 28px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.about-book-list li {
  position: relative;
  padding-left: 16px;
  color: var(--text);
  font-size: 0.86rem;
  line-height: 1.45;
}

.about-book-list li::before {
  position: absolute;
  top: 0.64em;
  left: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  content: '';
}

@media (max-width: 620px) {
  .about-area {
    padding: 28px 18px;
  }

  .about-header {
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .about-header__mark {
    width: 40px;
    height: 40px;
  }

  .about-book-list {
    grid-template-columns: 1fr;
  }
}
</style>
