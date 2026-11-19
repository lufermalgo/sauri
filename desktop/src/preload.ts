// Portal window preload (sandboxed, bundled as CommonJS): the portal gets a few whitelisted calls and nothing
// else; no Node, no ipcRenderer, no arbitrary channel. It listens only on the move's progress, the updater's state
// and the services status, and each payload is checked before the portal sees it.
import { contextBridge, ipcRenderer } from "electron";
import { PORTAL_CHANNELS, type PortalDesktopApi, relocateProgressOf, servicesStatusOf, updateStatusOf } from "./shared/portal-api.ts";

/** Listens on one main-process channel; the portal never sees the IPC event, only a checked copy of the payload. */
function listen<T>(channel: string, check: (value: unknown) => T | null, listener: (value: T) => void): () => void {
  const handler = (_event: Electron.IpcRendererEvent, payload: unknown) => {
    const value = check(payload);
    if (value) listener(value);
  };
  ipcRenderer.on(channel, handler);
  return () => {
    ipcRenderer.removeListener(channel, handler);
  };
}

const api: PortalDesktopApi = {
  getPaths: () => ipcRenderer.invoke(PORTAL_CHANNELS.getPaths),
  relocate: (kind) => ipcRenderer.invoke(PORTAL_CHANNELS.relocate, kind),
  onRelocateProgress: (listener) => listen(PORTAL_CHANNELS.relocateProgress, relocateProgressOf, listener),
  markSetupDone: () => ipcRenderer.invoke(PORTAL_CHANNELS.markSetupDone),
  getLocale: () => ipcRenderer.invoke(PORTAL_CHANNELS.getLocale),
  updates: {
    status: () => ipcRenderer.invoke(PORTAL_CHANNELS.updateStatus),
    check: () => ipcRenderer.invoke(PORTAL_CHANNELS.updateCheck),
    apply: () => ipcRenderer.invoke(PORTAL_CHANNELS.updateApply),
    setAutoCheck: (on) => ipcRenderer.invoke(PORTAL_CHANNELS.updateAutoCheck, on === true),
    onChange: (listener) => listen(PORTAL_CHANNELS.updateChanged, updateStatusOf, listener),
  },
  getServicesStatus: () => ipcRenderer.invoke(PORTAL_CHANNELS.servicesStatus),
  onServicesStatus: (listener) => listen(PORTAL_CHANNELS.servicesChanged, servicesStatusOf, listener),
};

contextBridge.exposeInMainWorld("sauriDesktop", api);
