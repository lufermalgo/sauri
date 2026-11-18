// Portal window preload (sandboxed, bundled as CommonJS): the portal gets three whitelisted calls and nothing
// else; no Node, no ipcRenderer, no arbitrary channel.
import { contextBridge, ipcRenderer } from "electron";
import { PORTAL_CHANNELS, type PortalDesktopApi } from "./shared/portal-api.ts";

const api: PortalDesktopApi = {
  getPaths: () => ipcRenderer.invoke(PORTAL_CHANNELS.getPaths),
  relocate: (kind) => ipcRenderer.invoke(PORTAL_CHANNELS.relocate, kind),
  markSetupDone: () => ipcRenderer.invoke(PORTAL_CHANNELS.markSetupDone),
};

contextBridge.exposeInMainWorld("sauriDesktop", api);
