// The three folders the user chooses (shared by the main process and the setup window).
export type FolderKind = "recordings" | "database" | "models";
export const FOLDER_KINDS: readonly FolderKind[] = ["recordings", "database", "models"];
export type UserFolders = Record<FolderKind, string>;
