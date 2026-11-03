# Hermes Blob TODO

Open items for the Hermes side of this fork, in no particular order.

## Companion

- **Expand towards the screen, not off it.** When the companion sits at the top of the screen (the card opens below it), the expand button should grow the card from top to bottom. Check `maxHeight` / the card's `y` and `transformOrigin` in `Main.qml` for the `anchorFromBottom === false` case, and the chevron direction (it should point down to grow there).
- **Per-bot custom looks.** A custom shape/colour is one setting for the whole companion (`syncAppearance: false`), so every bot wears it. Consider saving a custom look per bot, with Reset returning that bot to its Hermes look.
- **Auto-sync the roster.** Re-run the Hermes sync when `~/.hermes/profiles` changes, so new or restyled profiles appear without clicking Sync bots.
- **Show/hide shortcut.** Add a Hyprland binding (README suggests `SUPER + ALT + B` → `omarchy-shell io.github.tcballard.grokbot-desktop toggleVisible`).

## Hermes

- **Donna's compression threshold.** Donna compresses at 85% of a 500k window (~425k tokens), so every bubble ask carries a large Bot Chat. Consider `compression.threshold: 0.5` for her profile. Owner's decision.
- **Vision fallback keeps the task model (Hermes bug, not this project).** When a session's frozen `auxiliary.vision` credential no longer matches the config, the gateway returns vision to the primary route but keeps the task's own `model`, so the primary provider is asked for a model it does not serve (`404 model: grok-4.6`). Report upstream to NousResearch/hermes-agent if wanted.
- **Older history past a compression.** A Bot Chat's live transcript starts at its last compression (Sentinel, for one, has 150 compacted rows), so "Load 20 earlier messages" stops there. The bridge could read those rows read-only from the profile's `state.db` once the live transcript runs out, still capped at 100 exchanges.

## Upstream and identity

- **Fold Hermes back upstream.** PR #24 follow-ups offered (branch `pr24-followups`); PR #25 (dictation, Hex) and PR #26 (agent Stop, `askTimeoutSeconds`) open. tcballard is open to a backend-agnostic rename and to folding Hermes in (discussed on X). Plan: wait for his rename, then send focused PRs: card UI (compact/expand, Scroll down, `status`), Hermes roster + CLI dispatch, the gateway bridge, approvals/clarify + Compact.
- **Plugin id.** Still `io.github.tcballard.grokbot-desktop` so upstream merges stay clean. Rename to a Hermes Blob id (with a settings migration) if the fork stops tracking upstream.

## Done recently

- Load earlier Bot Chat exchanges, 20 at a time ("Load 20 earlier messages" at the top of the thread). Note: a Bot Chat's transcript starts at its last compression; exchanges before that are not loaded.
