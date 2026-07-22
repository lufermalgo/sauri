// Speaker avatar — Req. 8.4
import { AVATAR_PALETTE } from "./design/tokens";

export { AVATAR_PALETTE };

/**
 * Derives up to two initials characters from a speaker label.
 * Ex: "Speaker 1" -> "S1"; "" -> "".
 */
export function labelInitials(label: string): string {
  if (!label) return "";
  const parts = label.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "";
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  const first = parts[0][0] ?? "";
  const last = parts[parts.length - 1][0] ?? "";
  return (first + last).toUpperCase();
}

/**
 * Indexes AVATAR_PALETTE deterministically and cyclically from the speaker's
 * `sequence` (1-indexed). Guarantees the same color for the same `sequence`
 * and cyclic reuse when there are more speakers than colors.
 */
export function avatarColor(sequence: number): string {
  const n = AVATAR_PALETTE.length;
  const idx = ((Math.trunc(sequence) - 1) % n + n) % n;
  return AVATAR_PALETTE[idx];
}
