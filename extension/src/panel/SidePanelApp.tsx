// Composición del Side_Panel — Req. 1.3, 1.4, 1.5, 1.6, 13.2, 13.3, 13.4
import React, { useCallback, useEffect, useRef, useState } from "react";
import { EncabezadoPanel } from "./components/EncabezadoPanel";
import { ControlesDeCaptura, type MicOption } from "./components/ControlesDeCaptura";
import { ListaDeNotas } from "./components/ListaDeNotas";
import { VistaDeAutenticacion } from "./components/VistaDeAutenticacion";
import { aplicarEventoCaptura } from "../core/captura";
import { derivarEstadoDeVista } from "../core/vista";
import {
  listarReuniones,
  login as loginApi,
  eliminarReunion,
  renombrarReunion,
  BACKEND_URL_DEFECTO,
} from "../core/api/client";
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
  const [microfonoSeleccionado, setMicrofonoSeleccionado] = useState<MicOption | undefined>(undefined);
  const [errorMicrofono, setErrorMicrofono] = useState<string | null>(null);
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
    // enumerateDevices() solo devuelve deviceId/label reales si el origen ya
    // tiene permiso de micrófono concedido — de lo contrario vienen vacíos y
    // offscreen.ts termina tratando la grabación como "sin micrófono" aunque
    // el panel muestre uno seleccionado. Por eso se pide el permiso primero.
    navigator.mediaDevices
      ?.getUserMedia({ audio: true })
      .then((stream) => {
        stream.getTracks().forEach((track) => track.stop());
        return navigator.mediaDevices.enumerateDevices();
      })
      .then((devices) => {
        const audioInputs = devices.filter((d) => d.kind === "audioinput");
        const opciones = audioInputs.map((d, i) => ({ deviceId: d.deviceId, label: d.label || `Micrófono ${i + 1}` }));
        setMicrofonos(opciones);
        setMicrofonoSeleccionado((prev) => prev ?? opciones[0]);
      })
      .catch((error) => {
        const nombre = error instanceof DOMException ? error.name : String(error);
        console.error("[sauri] No se pudo acceder al micrófono:", nombre, error);
        setMicrofonos([]);
        setErrorMicrofono(
          nombre === "NotAllowedError"
            ? "Permiso de micrófono bloqueado para sauri. Ve a chrome://settings/content/microphone, busca la extensión sauri y cambia el permiso a 'Permitir', luego recarga la extensión."
            : nombre === "NotFoundError"
              ? "No se detectó ningún micrófono conectado."
              : `No se pudo acceder al micrófono (${nombre}).`
        );
      });
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

  // Refresca "Mis Notas" cuando termina una grabación (grabando/deteniendo → inactiva),
  // ya que la subida se procesa en el background sin que el panel lo sepa de otro modo.
  const estadoAnteriorRef = useRef<EstadoDeCaptura>("inactiva");
  useEffect(() => {
    if (estadoAnteriorRef.current !== "inactiva" && estadoDeCaptura === "inactiva") {
      cargarNotas();
    }
    estadoAnteriorRef.current = estadoDeCaptura;
  }, [estadoDeCaptura, cargarNotas]);

  const handleNuevaNota = useCallback(() => {
    setEstadoDeCaptura((prev) => aplicarEventoCaptura(prev, "iniciar"));
    chrome.runtime.sendMessage({
      type: "start-capture",
      resolution: { width: 1280, height: 720 },
      micDeviceId: microfonoSeleccionado?.deviceId ?? null,
    });
  }, [microfonoSeleccionado]);

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

  const handleEliminarNota = useCallback(
    async (reunionId: string) => {
      try {
        await eliminarReunion(reunionId, BACKEND_URL_DEFECTO);
        await cargarNotas();
      } catch (error) {
        console.error("[sauri] No se pudo eliminar la nota:", error);
      }
    },
    [cargarNotas]
  );

  const handleRenombrarNota = useCallback(
    async (reunionId: string, nuevoTitulo: string) => {
      try {
        await renombrarReunion(reunionId, nuevoTitulo, BACKEND_URL_DEFECTO);
        await cargarNotas();
      } catch (error) {
        console.error("[sauri] No se pudo renombrar la nota:", error);
      }
    },
    [cargarNotas]
  );

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
        microfonoSeleccionado={microfonoSeleccionado}
        onSeleccionarMicrofono={setMicrofonoSeleccionado}
        onToggleCaptura={handleToggleCaptura}
        onAbrirAjustes={handleAbrirAjustes}
        tiempoTranscurridoMs={tiempoTranscurridoMs}
        errorMicrofono={errorMicrofono}
      />
      <ListaDeNotas
        estado={estadoDeVistaNotas}
        notas={solicitudNotas.datos ?? solicitudNotas.previos ?? []}
        onReintentar={cargarNotas}
        onAbrirNota={handleAbrirNota}
        onEliminarNota={handleEliminarNota}
        onRenombrarNota={handleRenombrarNota}
      />
    </div>
  );
}
