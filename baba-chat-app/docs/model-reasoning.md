# Model and reasoning contract

This contract was verified against the installed `codex-cli 0.144.5` app-server on 2026-08-17.

## Wire protocol

The generated app-server bindings are authoritative for the installed binary:

- `thread/start` has a `model` field, but no reasoning-effort field.
- `turn/start` has an `effort` field. The generated description says it overrides reasoning effort for the current turn and subsequent turns.
- `model/list` returns `{ data, nextCursor }`.

Therefore the renderer-facing property is intentionally named `reasoningEffort`, but Baba Chat sends it to the app-server as `params.effort` on `turn/start`. Baba Chat does not send a made-up `reasoningEffort` or `reasoning_effort` wire field.

The renderer contract is:

```ts
window.directorsCodex.startTurn({
  threadId,
  text,
  model: 'gpt-5.6-luna',
  reasoningEffort: 'max',
});
```

`reasoningEffort` is optional. If it is absent, blank, or unsupported, the backend omits `effort` and Codex uses its normal default. The legacy renderer-facing `effort` property is also accepted as an alias, so existing callers continue to work. When both are present, `reasoningEffort` takes precedence.

Because `thread/start` does not accept effort in this installed protocol, the renderer should include `reasoningEffort` on the first `turn/start` and on later turns when the user changes the setting. The setting then follows the app-server behavior of applying to that turn and subsequent turns.

## Normalization

`normalizeReasoningEffort` accepts a string, trims surrounding whitespace, and lowercases it. It only returns the catalog values currently known to this client:

`low`, `medium`, `high`, `xhigh`, `max`, and `ultra`.

Every other value becomes `undefined`, which causes `effort` to be omitted. The model catalog remains typed with `string` for effort names because the installed protocol schema declares the underlying `ReasoningEffort` type as a string and a newer Codex binary may add a value.

The UI should use the selected model's `supportedReasoningEfforts` list when presenting choices. In the current catalog, Luna supports `low`, `medium`, `high`, `xhigh`, and `max`; it does not advertise `ultra`.

## `model/list` capability fields

The typed response preserves the fields exposed by the installed protocol for each model:

- `id` and `model`: model identifiers.
- `displayName` and `description`: picker-facing metadata.
- `hidden` and `isDefault`: visibility and catalog-default flags.
- `supportedReasoningEfforts`: effort values with a `reasoningEffort` name and human-readable `description`.
- `defaultReasoningEffort`: catalog default for that model.
- `inputModalities`: supported input types, such as `text` and `image`.
- `supportsPersonality`: whether the model supports personality selection.
- `serviceTiers`: available service tiers with `id`, `name`, and `description`.
- `defaultServiceTier`: the catalog default service tier, or `null`.
- `additionalSpeedTiers`: deprecated speed-tier identifiers retained by the protocol.
- `upgrade` and `upgradeInfo`: upgrade metadata, when present.
- `availabilityNux`: optional first-use availability message.

The live response for `gpt-5.6-luna` reported `defaultReasoningEffort: "medium"`, supported efforts through `"max"`, text and image input, `supportsPersonality: false`, `isDefault: false`, and a `priority` service tier.

## Evidence commands

The protocol bindings used for this check can be regenerated without modifying the project:

```bash
codex app-server generate-ts --experimental --out /tmp/codex-app-server-types
```

Inspect `v2/ThreadStartParams.ts`, `v2/TurnStartParams.ts`, `v2/Model.ts`, and `v2/ModelListResponse.ts` in that output. A live `initialize` followed by `model/list` against the installed binary confirmed the catalog fields and Luna's supported efforts.
