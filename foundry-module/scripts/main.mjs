import { ConnectionSetupApp } from "./ui/connection-setup-app.mjs";
import { SyncDialogApp } from "./ui/sync-dialog-app.mjs";
import { registerHpSyncHooks, registerLifecycleHooks } from "./hooks.mjs";

/**
 * Module entry point (`module.json`'s `esmodules`). Deliberately just
 * wiring: every piece of actual behavior lives in a file with no
 * dependency on the real Foundry runtime and is covered by
 * `foundry-module/test/` — this file itself is exercised only by
 * loading it inside a real Foundry client (see `foundry-module/
 * README.md`'s "Manual live-Foundry verification" section), which is
 * why it stays this small.
 */
registerLifecycleHooks({ connectionSetupAppClass: ConnectionSetupApp });
registerHpSyncHooks();

Hooks.on("getSceneControlButtons", (controls) => {
  const tokenControls = Array.isArray(controls) ? controls.find((c) => c.name === "token") : controls.token;
  if (!tokenControls) {
    return;
  }
  const tool = {
    name: "dnd-ai-sync",
    title: "DNDAI.SyncDialog.Title",
    icon: "fa-solid fa-dice-d20",
    button: true,
    visible: game.user?.isGM,
    onClick: () => new SyncDialogApp().render(true),
  };
  if (Array.isArray(tokenControls.tools)) {
    tokenControls.tools.push(tool);
  } else if (tokenControls.tools) {
    tokenControls.tools[tool.name] = tool;
  }
});
