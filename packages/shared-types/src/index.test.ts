import { describe, expect, it } from "vitest";
import ts from "typescript";
import { MeetingOrigin, ProcessState } from "./index";

// Vitest transpiles type-only imports away. Compile a virtual consumer instead so
// missing exports, field drift, and lifecycle widening actually fail this test.
const summaryContractConsumer = `
import type {
  AttributedTurn, MeetingSummary, SummaryRequestStatus, SummaryTemplate, TemplateCategory, TranscriptPresentation,
} from "./index";
type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends
  (<T>() => T extends B ? 1 : 2) ? true : false;
type Assert<T extends true> = T;
type SummaryContract = Assert<Equal<MeetingSummary, {
  summaryId: string; meetingId: string; templateId: string; templateName: string;
  templateVersion: number; topic: string;
  schemaVersion?: 1 | 2;
  keyPoints: Array<string
    | { text: string; sources: Array<{ passageId: string; startMs: number; endMs: number }> }
    | {
      title: string; items: Array<{ text: string; subItems: string[] }>;
      sources: Array<{ passageId: string; startMs: number; endMs: number }>;
    }>;
  conclusion?: string | null;
  reviewState: "draft"; generation: number;
  createdAt: string; updatedAt: string;
}>>;
type StatusContract = Assert<Equal<SummaryRequestStatus, {
  eventId: string; generation: number;
  status: "pending" | "running" | "succeeded" | "failed";
  failureCause?: string | null;
  requestedAt?: string | null; startedAt?: string | null;
}>>;
type TemplateContract = Assert<Equal<SummaryTemplate, {
  id: string; name: string; ownerId: string; categoryId?: string;
  version: number; instructions: string; isDefault: boolean;
  createdAt: string; updatedAt: string;
}>>;
type CategoryContract = Assert<Equal<TemplateCategory, {
  id: string; name: string; ownerId: string; createdAt: string;
}>>;
type PresentationContract = Assert<Equal<TranscriptPresentation, "words" | "segments">>;
type AttributedTurnContract = Assert<Equal<AttributedTurn, {
  sequence: number; speakerId: string | null; speakerLabel: string | null;
  startMs: number; endMs: number; text: string; wordCount: number; hasAmbiguous: boolean;
}>>;
`;

describe("summary and personal template contracts", () => {
  it("exports exactly the designed camelCase fields, optional category and status union", () => {
    const fixturePath = ts.sys.resolvePath("src/summary-contract.fixture.ts");
    const options: ts.CompilerOptions = {
      strict: true,
      skipLibCheck: true,
      noEmit: true,
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ESNext,
      moduleResolution: ts.ModuleResolutionKind.Bundler,
    };
    const host = ts.createCompilerHost(options);
    const getSourceFile = host.getSourceFile.bind(host);
    host.getSourceFile = (fileName, languageVersion, onError, shouldCreateNewSourceFile) =>
      fileName === fixturePath
        ? ts.createSourceFile(fileName, summaryContractConsumer, languageVersion, true)
        : getSourceFile(fileName, languageVersion, onError, shouldCreateNewSourceFile);
    const program = ts.createProgram([fixturePath], options, host);
    const diagnostics = ts.getPreEmitDiagnostics(program).map((diagnostic) =>
      ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"),
    );
    expect(diagnostics).toEqual([]);
  });
});

describe("shared meeting types", () => {
  it("exposes synthetic contract enum values to package tests", () => {
    expect(ProcessState.Queued).toBe("queued");
    expect(MeetingOrigin.Manual).toBe("manual");
  });
});

describe("engines API contract", () => {
  const enginesContractConsumer = `
import type {
    EngineKeyState, EngineProbeResult, EngineProcessChoice, EngineProvider, EngineProviderCreate,
  } from "./index";
  import { LOCAL_DEFAULT_MODEL } from "./index";
  type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends
    (<T>() => T extends B ? 1 : 2) ? true : false;
  type Assert<T extends true> = T;
  // A provider as returned by the API never has a field that could hold the key value.
  type NoKeyValue = Assert<Equal<Extract<keyof EngineProvider, "key" | "api_key" | "secret" | "secret_ref">, never>>;
  type NoKeyValueInState = Assert<Equal<Extract<keyof EngineKeyState, "key" | "api_key" | "secret">, never>>;
  type ProbeShape = Assert<Equal<keyof EngineProbeResult, "ok" | "latency_ms" | "error_class" | "json_schema_ok" | "schema_error_class" | "schema_model">>;
  const choice: EngineProcessChoice = { provider_id: null, model: LOCAL_DEFAULT_MODEL, local_fallback: true };
  const create: EngineProviderCreate = { kind: "openai", label: "Work account" };
  // @ts-expect-error unknown kinds are rejected
  const bad: EngineProviderCreate = { kind: "nothing", label: "x" };
  void choice; void create; void bad;
  export type { NoKeyValue, NoKeyValueInState, ProbeShape };
  `;

  it("compiles against the exported types and never exposes a key value", () => {
    const options: ts.CompilerOptions = {
      target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
      moduleResolution: ts.ModuleResolutionKind.Bundler, strict: true, noEmit: true, skipLibCheck: true,
      lib: ["lib.es2022.d.ts"],
    };
    const host = ts.createCompilerHost(options);
    const virtualName = `${process.cwd()}/src/engines-contract-consumer.ts`;
    const original = host.getSourceFile.bind(host);
    host.getSourceFile = (name, languageVersion, ...rest) =>
      name === virtualName ? ts.createSourceFile(name, enginesContractConsumer, languageVersion) : original(name, languageVersion, ...rest);
    const originalExists = host.fileExists.bind(host);
    host.fileExists = (name) => name === virtualName || originalExists(name);
    const program = ts.createProgram([virtualName], options, host);
    const messages = ts.getPreEmitDiagnostics(program).map((d) => ts.flattenDiagnosticMessageText(d.messageText, "\n"));
    expect(messages).toEqual([]);
  });
});
