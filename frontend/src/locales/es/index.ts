import language from "./language.json";
import library from "./library.json";
import login from "./login.json";
import meeting from "./meeting.json";
import processing from "./processing.json";
import shell from "./shell.json";
import speakerReview from "./speakerReview.json";
import summary from "./summary.json";
import transcript from "./transcript.json";
import upload from "./upload.json";

/**
 * Spanish is the source language: its JSON files define the shape (and so the typed keys) that every
 * other language must match. One namespace per area; `src/i18n/index.ts` registers them.
 */
export const es = { language, library, login, meeting, processing, shell, speakerReview, summary, transcript, upload };

export type Resources = typeof es;
