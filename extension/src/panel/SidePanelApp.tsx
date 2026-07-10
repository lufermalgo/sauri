// Composición del Side_Panel — Req. 1.3, 1.4, 1.5, 1.6, 13.2, 13.3, 13.4
import React, { useCallback, useEffect, useRef, useState } from "react";
import { EncabezadoPanel } from "./components/EncabezadoPanel";
import { ControlesDeCaptura, type MicOption } from "./components/ControlesDeCaptura";
import { ListaDeNotas } from "./components/ListaDeNotas";
import { VistaDeAutenticacion } from "./components/VistaDeAutenticacion";
import { aplicarEventoCaptura } from "../core/captura";
import { derivarEstadoDeVista } from "../core/vista";
import { listarReuniones, login as loginApi, BACKEND_URL_DEFECTO } from "../core/api/client";
import { construirUrlDetalle } from "../core/detailUrl";
import type { EstadoDeCaptura, NotaDTO, SolicitudRemota } from "../core/types";
import "../core/design/tokens.css";

interface SauriBackgroundState {
  status: "idle" | "pending" | "recording";
}

function mapEstadoDeCaptura(status: SauriBackgroundState["status"]): EstadoDeCaptura {
  if (status === "recording") return "grabando";
  return "inactiva";
}

export function SidePanelApp() {
  const [sesionVigente, setSesionVigente] = useState<boolean | null>(null);
  const [estadoDeCaptura, setEstadoDeCaptura] = useState<EstadoDeCaptura>("inactiva");
  const [tiempoTranscurridoMs, setTiempoTranscurridoMs] = useState(0);
  const [microfonos, setMicrofonos] = useState<MicOption[]>([]);
  const [solicitudNotas, setSolicitudNotas] = useState<SolicitudRemota<NotaDTO>>({
    fase: "inicial",
    datos: null,
    previos: null,
  });
  const inicioGrabacionRef = useRef<number | null>(null);

  const cargarSesion = useCallback(async () => {
    const result = await chrome.storage.sync.get("authToken");
    setSesionVigente(Boolean(result.authToken));
  }, []);

  useEffect(() => {
    cargarSesion();
  }, [cargarSesion]);

  useEffect(() => {
    chrome.storage.session.get("sauriState").then((result) => {
      const state = result.sauriState as SauriBackgroundState | undefined;
      if (state) setEstadoDeCaptura(mapEstadoDeCaptura(state.status));
    });

    const listener = (changes: { [key: string]: chrome.storage.StorageChange }, areaName: string) => {
      if (areaName === "session" && changes.sauriState) {
        const state = changes.sauriState.newValue as SauriBackgroundState | undefined;
        setEstadoDeCaptura(mapEstadoDeCaptura(state?.status ?? "idle"));
      }
    };
    chrome.storage.onChanged.addListener(listener);
    return () => chrome.storage.onChanged.removeListener(listener);
  }, []);

  useEffect(() => {
    navigator.mediaDevices
      ?.enumerateDevices()
      .then((devices) => {
        const audioInputs = devices.filter((d) => d.kind === "audioinput");
        setMicrofonos(
          audioInputs.map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Micrófono ${i + 1}` }))
        );
      })
      .catch(() => setMicrofonos([]));
  }, []);

  // Cronómetro de grabación (Req. 3.9)
  useEffect(() => {
    if (estadoDeCaptura === "grabando") {
      if (inicioGrabacionRef.current === null) inicioGrabacionRef.current = Date.now();
      const interval = setInterval(() => {
        setTiempoTranscurridoMs(Date.now() - (inicioGrabacionRef.current ?? Date.now()));
      }, 1000);
      return () => clearInterval(interval);
    }
    inicioGrabacionRef.current = null;
    setTiempoTranscurridoMs(0);
  }, [estadoDeCaptura]);

  const cargarNotas = useCallback(async () => {
    setSolicitudNotas((prev) => ({ fase: "en_curso", datos: null, previos: prev.datos }));
    try {
      const notas = await listarReuniones(BACKEND_URL_DEFECTO);
      setSolicitudNotas({ fase: "exito", datos: notas, previos: null });
    } catch {
      setSolicitudNotas((prev) => ({ fase: "fallo", datos: null, previos: prev.datos }));
    }
  }, []);

  useEffect(() => {
    if (sesionVigente) cargarNotas();
  }, [sesionVigente, cargarNotas]);

  const handleNuevaNota = useCallback(() => {
    setEstadoDeCaptura((prev) => aplicarEventoCaptura(prev, "iniciar"));
    chrome.runtime.sendMessage({ type: "start-capture", resolution: { width: 1280, height: 720 }, micDeviceId: null });
  }, []);

  const handleToggleCaptura = useCallback(() => {
    if (estadoDeCaptura === "inactiva") {
      handleNuevaNota();
    } else if (estadoDeCaptura === "grabando") {
      setEstadoDeCaptura((prev) => aplicarEventoCaptura(prev, "detener"));
      chrome.runtime.sendMessage({ type: "stop-capture" });
    }
  }, [estadoDeCaptura, handleNuevaNota]);

  const handleAbrirAjustes = useCallback(() => {
    chrome.runtime.openOptionsPage?.();
  }, []);

  const handleAbrirNota = useCallback((reunionId: string) => {
    const url = construirUrlDetalle(reunionId);
    chrome.tabs.create({ url: chrome.runtime.getURL(url) });
  }, []);

  const handleLogin = useCallback(
    async (email: string, password: string) => {
      await loginApi(email, password, BACKEND_URL_DEFECTO);
      setSesionVigente(true);
    },
    []
  );

  if (sesionVigente === null) {
    return null;
  }

  if (!sesionVigente) {
    return <VistaDeAutenticacion onLogin={handleLogin} />;
  }

  const estadoDeVistaNotas = derivarEstadoDeVista(solicitudNotas);

  return (
    <div
      style={{
        minWidth: "320px",
        overflowX: "auto",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <EncabezadoPanel estadoDeCaptura={estadoDeCaptura} onNuevaNota={handleNuevaNota} />
      <ControlesDeCaptura
        estadoDeCaptura={estadoDeCaptura}
        microfonos={microfonos}
        onToggleCaptura={handleToggleCaptura}
        onAbrirAjustes={handleAbrirAjustes}
        tiempoTranscurridoMs={tiempoTranscurridoMs}
      />
      <ListaDeNotas
        estado={estadoDeVistaNotas}
        notas={solicitudNotas.datos ?? solicitudNotas.previos ?? []}
        onReintentar={cargarNotas}
        onAbrirNota={handleAbrirNota}
      />
    </div>
  );
}
