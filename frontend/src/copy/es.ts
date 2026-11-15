import { processing } from "./processing";
import { transcript } from "./transcript";
import { speakerReview } from "./speakerReview";
import { summary } from "./summary";
import { upload } from "./upload";
import { shell } from "./shell";
import { login } from "./login";
import { library } from "./library";
import { meeting } from "./meeting";

export const copy = {
  processing,
  transcript,
  speakerReview,
  summary,
  upload,
  shell,
  login,
  library,
  meeting,
} as const;
