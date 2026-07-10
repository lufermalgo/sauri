/**
 * Property test de idempotencia de la cola de subida (upload-queue.ts).
 *
 * Feature: meeting-capture-transcription, Property 14: Idempotencia de los manejadores del pipeline y de la ingesta
 * Task: 14.9 (faceta cliente) — Validates: Requirements 2.3, 4.1
 *
 * Para toda secuencia de reintentos sobre la cola de IndexedDB con la misma
 * claveIdempotencia, la extensión emite a lo sumo una subida efectiva
 * (sin duplicar el job en la cola).
 */

import { describe, it, expect, beforeEach } from "vitest";
import * as fc from "fast-check";
import { IDBFactory, IDBKeyRange } from "fake-indexeddb";

import { enqueueUpload, type EnqueueUploadInput } from "./upload-queue";

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  globalThis.IDBKeyRange = IDBKeyRange;
});

function arbEnqueueInput(): fc.Arbitrary<EnqueueUploadInput> {
  return fc.record({
    sessionId: fc.uuid(),
    claveIdempotencia: fc.uuid(),
    mimeType: fc.constantFrom(
      "video/webm;codecs=vp8,opus",
      "audio/webm;codecs=opus",
      "video/webm"
    ),
    notificationEmittedAt: fc.option(fc.date().map((d) => d.toISOString()), {
      nil: undefined,
    }),
  });
}

describe("Property 14 (faceta cliente): idempotencia de la cola de subida", () => {
  it("para cualquier número de reintentos de subida con la misma claveIdempotencia, a lo sumo una es efectiva", async () => {
    await fc.assert(
      fc.asyncProperty(
        arbEnqueueInput(),
        fc.integer({ min: 1, max: 8 }),
        async (input, reintentos) => {
          globalThis.indexedDB = new IDBFactory();
          globalThis.IDBKeyRange = IDBKeyRange;

          let exitosos = 0;
          let ids = new Set<string>();

          for (let i = 0; i < reintentos; i++) {
            try {
              const job = await enqueueUpload(input);
              exitosos += 1;
              ids.add(job.id);
            } catch {
              // Reintento rechazado por índice único de claveIdempotencia — esperado.
            }
          }

          // A lo sumo un reintento produce un job efectivamente encolado.
          expect(exitosos).toBe(1);
          expect(ids.size).toBe(1);
        }
      ),
      { numRuns: 100 }
    );
  });
});
