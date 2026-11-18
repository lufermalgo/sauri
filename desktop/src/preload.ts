// Portal window preload (sandboxed, bundled as CommonJS): the portal gets a few whitelisted calls and nothing
// else; no Node, no ipcRenderer, no arbitrary channel.
import { contextBridge, ipcRenderer } from "electron";
import { PORTAL_CHANNELS, type PortalDesktopApi } from "./shared/portal-api.ts";

const api: PortalDesktopApi = {
  getPaths: () => ipcRenderer.invoke(PORTAL_CHANNELS.getPaths),
  relocate: (kind) => ipcRenderer.invoke(PORTAL_CHANNELS.relocate, kind),
  markSetupDone: () => ipcRenderer.invoke(PORTAL_CHANNELS.markSetupDone),
  updates: {
    status: () => ipcRenderer.invoke(PORTAL_CHANNELS.updateStatus),
    check: () => ipcRenderer.invoke(PORTAL_CHANNELS.updateCheck),
    apply: () => ipcRenderer.invoke(PORTAL_CHANNELS.updateApply),
    setAutoCheck: (on) => ipcRenderer.invoke(PORTAL_CHANNELS.updateAutoCheck, on === true),
  },
};

contextBridge.exposeInMainWorld("sauriDesktop", api);
