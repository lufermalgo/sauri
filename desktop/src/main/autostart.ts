// Open at login (Requirement 8.3): off by default, only for the installed app.
import { app } from "electron";

export function setLaunchAtLogin(on: boolean): void {
  // A development run would register the bare Electron binary as a login item.
  if (!app.isPackaged) return;
  app.setLoginItemSettings({ openAtLogin: on });
}
