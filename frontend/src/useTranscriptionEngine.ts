import { useEffect, useState } from "react";
import { LOCAL_DEFAULT_MODEL } from "@sauri/shared-types";
import type { EngineProcessState, LocalModel } from "@sauri/shared-types";
import { listEngineProcesses, listLocalModels } from "./api";
import type { TranscriptionEngine } from "./processing-estimate";
import { resolvedDefault } from "./components/settings/engineLabels";

/** How long one answer is reused: the setting changes rarely and every progress bar asks for it. */
const CACHE_MS = 60_000;
const PARAKEET_ENGINE = "fluidaudio";
const LOCAL_PREFIX = "local:";

let cached: { at: number; value: Promise<TranscriptionEngine> } | null = null;

/** The local engine that would transcribe now, from the saved choice and the models installed on this computer. */
export function engineFor(setting: EngineProcessState | undefined, models: readonly LocalModel[]): TranscriptionEngine {
  if (setting && setting.provider_id !== null) return "whisper"; // an external provider: unknown speed, stay cautious
  const model = setting && setting.configured && setting.model !== LOCAL_DEFAULT_MODEL && setting.model.startsWith(LOCAL_PREFIX)
    ? models.find((entry) => entry.id === setting.model.slice(LOCAL_PREFIX.length))
    : resolvedDefault(models, "transcription");
  return model?.engine === PARAKEET_ENGINE ? "parakeet" : "whisper";
}

function fetchEngine(): Promise<TranscriptionEngine> {
  const cautious = () => "whisper" as const;
  try {
    return Promise.all([listEngineProcesses(), listLocalModels()]).then(
      ([processes, list]) => engineFor(processes.find((entry) => entry.capability === "transcription"), list.models),
      cautious,
    );
  } catch {
    return Promise.resolve(cautious());
  }
}

/** Forget the cached answer (after the person changes the engine or tests need a clean slate). */
export function resetTranscriptionEngine(): void {
  cached = null;
}

/**
 * Which engine the time estimates are for: Parakeet takes about 2 minutes per hour of audio, Whisper about 10.
 * Until the answer arrives, or when it cannot be read, it is Whisper: the page never promises a speed it cannot back.
 */
export function useTranscriptionEngine(): TranscriptionEngine {
  const [engine, setEngine] = useState<TranscriptionEngine>("whisper");
  useEffect(() => {
    let current = true;
    if (cached === null || Date.now() - cached.at > CACHE_MS) cached = { at: Date.now(), value: fetchEngine() };
    void cached.value.then((value) => current && setEngine(value));
    return () => {
      current = false;
    };
  }, []);
  return engine;
}
