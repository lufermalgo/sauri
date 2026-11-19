// «About Sauri» window preload (sandboxed, bundled as CommonJS): only reads the view, never ipcRenderer itself.
import { contextBridge, ipcRenderer } from "electron";
import { ABOUT_CHANNELS, type AboutApi, type AboutView } from "../shared/about-api.ts";

const api: AboutApi = {
  view: () => ipcRenderer.invoke(ABOUT_CHANNELS.view),
  onChange: (listener) => {
    ipcRenderer.on(ABOUT_CHANNELS.changed, (_event, view: AboutView) => listener(view));
  },
};

contextBridge.exposeInMainWorld("sauriAbout", api);
