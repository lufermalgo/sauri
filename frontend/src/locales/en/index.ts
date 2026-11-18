import type { Resources } from "../es";
import engines from "./engines.json";
import language from "./language.json";
import library from "./library.json";
import login from "./login.json";
import meeting from "./meeting.json";
import processing from "./processing.json";
import settings from "./settings.json";
import shell from "./shell.json";
import speakerReview from "./speakerReview.json";
import summary from "./summary.json";
import transcript from "./transcript.json";
import upload from "./upload.json";
import welcome from "./welcome.json";

/** English bundle. Loaded on demand (dynamic import), so Spanish users never download it. */
export const en: Resources = { engines, language, library, login, meeting, processing, settings, shell, speakerReview, summary, transcript, upload, welcome };
