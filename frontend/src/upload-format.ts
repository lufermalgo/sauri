import { t } from "./i18n";
import { formatNumber } from "./i18n/format";

const BYTES_PER_MB = 1048576;

/** "1,5 MB" / "1.5 MB" for the chosen file; tiny files read "under 0.1 MB". */
export function fileSizeText(bytes: number): string {
  if (bytes < BYTES_PER_MB / 20) return t("upload:sizeUnderTenth");
  const size = formatNumber(bytes / BYTES_PER_MB, { maximumFractionDigits: 1, minimumFractionDigits: 1 });
  return t("upload:sizeMb", { size });
}

/** "312 of 473 MB · 65 %": one decimal below 10 MB, whole megabytes above. */
export function transferredText(loaded: number, total: number, percent: number): string {
  const megabytes = (bytes: number) => t("upload:sizeMb", {
    size: formatNumber(bytes / BYTES_PER_MB, { maximumFractionDigits: bytes < 10 * BYTES_PER_MB ? 1 : 0 }),
  });
  return t("upload:transferred", { loaded: megabytes(loaded), total: megabytes(total), percent });
}

/** `mm:ss` of a recording's length. */
export function durationText(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60).toString().padStart(2, "0")}:${(total % 60).toString().padStart(2, "0")}`;
}
