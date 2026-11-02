# Hermes Blob TODO

Open items for the Hermes side of this fork, in no particular order.

## Companion

- **Expand towards the screen, not off it.** When the companion sits at the top of the screen (the card opens below it), the expand button should grow the card from top to bottom. Check `maxHeight` / the card's `y` and `transformOrigin` in `Main.qml` for the `anchorFromBottom === false` case, and the chevron direction (it should point down to grow there).
- **Show/hide shortcut.** Add a Hyprland binding (README suggests `SUPER + ALT + B` → `omarchy-shell io.github.tcballard.grokbot-desktop toggleVisible`).

## Hermes

- **Donna's compression threshold.** Donna compresses at 85% of a 500k window (~425k tokens), so every bubble ask carries a large Bot Chat. Consider `compression.threshold: 0.5` for her profile. Owner's decision.
- **Vision fallback keeps the task model (Hermes bug, not this project).** When a session's frozen `auxiliary.vision` credential no longer matches the config, the gateway returns vision to the primary route but keeps the task's own `model`, so the primary provider is asked for a model it does not serve (`404 model: grok-4.6`). Report upstream to NousResearch/hermes-agent if wanted.

## Upstream and identity

- **Feedback to tcballard.** Upstream PR #24 breaks five existing tests (IPC methods moved out of `Main.qml`) and its `IpcHandler` bridge logs `Type QVariant cannot be used across IPC` on stable Omarchy. Both are fixed here (commits `3cf9d53`, `e8956c5`); offer them on the PR.
- **Plugin id.** Still `io.github.tcballard.grokbot-desktop` so upstream merges stay clean. Rename to a Hermes Blob id (with a settings migration) if the fork stops tracking upstream.

## Done recently

- Load earlier Bot Chat exchanges, 20 at a time ("Load 20 earlier messages" at the top of the thread). Note: a Bot Chat's transcript starts at its last compression; exchanges before that are not loaded.
