import { TOKEN_KEY } from "./api";

/** What the portal knows about the signed-in user: the claims the API puts in the login token. */
export interface SessionUser {
  name: string | null;
  email: string | null;
}

function claim(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function decodePayload(token: string): Record<string, unknown> | null {
  const part = token.split(".")[1];
  if (!part) return null;
  try {
    const base64 = part.replace(/-/g, "+").replace(/_/g, "/");
    const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
    const payload: unknown = JSON.parse(new TextDecoder().decode(bytes));
    return payload && typeof payload === "object" ? (payload as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/**
 * Reads the display name and email from the stored token. The token is not verified here:
 * the API verifies it on every request, and these values are only shown, never trusted.
 * Returns null when there is no token or it carries neither claim.
 */
export function readSessionUser(): SessionUser | null {
  let token: string | null = null;
  try {
    token = localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
  const payload = token ? decodePayload(token) : null;
  if (!payload) return null;
  const name = claim(payload, "name");
  const email = claim(payload, "email");
  return name || email ? { name, email } : null;
}

/** Up to two uppercase initials from the display name, or from the email's local part. */
export function userInitials(user: SessionUser): string {
  const source = user.name ?? user.email?.split("@")[0] ?? "";
  const words = source.split(/[\s._+-]+/).filter(Boolean);
  const letters = [words[0], words.length > 1 ? words[words.length - 1] : undefined]
    .filter((word): word is string => Boolean(word))
    .map((word) => Array.from(word)[0]);
  return letters.join("").toUpperCase();
}
