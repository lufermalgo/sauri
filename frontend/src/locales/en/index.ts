import type { Resources } from "../es";
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

/** English bundle. Loaded on demand (dynamic import), so Spanish users never download it. */
export const en: Resources = { language, library, login, meeting, processing, shell, speakerReview, summary, transcript, upload };
