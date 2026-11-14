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
  keyPoints: Array<string | { text: string; sources: Array<{ passageId: string; startMs: number; endMs: number }> }>;
  reviewState: "draft"; generation: number;
  createdAt: string; updatedAt: string;
}>>;
type StatusContract = Assert<Equal<SummaryRequestStatus, {
  eventId: string; generation: number;
  status: "pending" | "running" | "succeeded" | "failed";
  failureCause?: string | null;
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
