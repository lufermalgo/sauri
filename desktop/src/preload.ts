// Portal window preload (sandboxed, bundled as CommonJS): the portal gets a few whitelisted calls and nothing
// else; no Node, no ipcRenderer, no arbitrary channel. The only channel it listens on is the move's progress.
import { contextBridge, ipcRenderer } from "electron";
import { PORTAL_CHANNELS, type PortalDesktopApi, relocateProgressOf } from "./shared/portal-api.ts";

const api: PortalDesktopApi = {
  getPaths: () => ipcRenderer.invoke(PORTAL_CHANNELS.getPaths),
  relocate: (kind) => ipcRenderer.invoke(PORTAL_CHANNELS.relocate, kind),
  onRelocateProgress: (listener) => {
    // The portal never sees the IPC event, only a checked copy of the payload.
    const handler = (_event: Electron.IpcRendererEvent, payload: unknown) => {
      const progress = relocateProgressOf(payload);
      if (progress) listener(progress);
    };
    ipcRenderer.on(PORTAL_CHANNELS.relocateProgress, handler);
    return () => {
      ipcRenderer.removeListener(PORTAL_CHANNELS.relocateProgress, handler);
    };
  },
  markSetupDone: () => ipcRenderer.invoke(PORTAL_CHANNELS.markSetupDone),
  getLocale: () => ipcRenderer.invoke(PORTAL_CHANNELS.getLocale),
  updates: {
    status: () => ipcRenderer.invoke(PORTAL_CHANNELS.updateStatus),
    check: () => ipcRenderer.invoke(PORTAL_CHANNELS.updateCheck),
    apply: () => ipcRenderer.invoke(PORTAL_CHANNELS.updateApply),
    setAutoCheck: (on) => ipcRenderer.invoke(PORTAL_CHANNELS.updateAutoCheck, on === true),
  },
};

contextBridge.exposeInMainWorld("sauriDesktop", api);
