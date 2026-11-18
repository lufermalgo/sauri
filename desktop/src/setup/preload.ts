// Setup window preload (sandboxed, bundled as CommonJS): exposes only the setup calls, never ipcRenderer itself.
import { contextBridge, ipcRenderer } from "electron";
import { CHANNELS, type SetupApi, type View } from "../shared/setup-api.ts";

const api: SetupApi = {
  state: () => ipcRenderer.invoke(CHANNELS.state),
  hardware: () => ipcRenderer.invoke(CHANNELS.hardware),
  setLocale: (locale) => ipcRenderer.invoke(CHANNELS.locale, locale),
  saveName: (name) => ipcRenderer.invoke(CHANNELS.identity, name),
  back: () => ipcRenderer.invoke(CHANNELS.back),
  inspect: (folders) => ipcRenderer.invoke(CHANNELS.inspect, folders),
  choose: (kind) => ipcRenderer.invoke(CHANNELS.choose, kind),
  finish: (folders) => ipcRenderer.invoke(CHANNELS.finish, folders),
  retry: () => ipcRenderer.invoke(CHANNELS.retry),
  openLogs: () => ipcRenderer.invoke(CHANNELS.logs),
  quit: () => ipcRenderer.invoke(CHANNELS.quit),
  onView: (listener) => {
    ipcRenderer.on(CHANNELS.view, (_event, view: View) => listener(view));
  },
};

contextBridge.exposeInMainWorld("sauriSetup", api);
