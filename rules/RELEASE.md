# Releasing Sauri

How a maintainer cuts a desktop release today, by hand, on an Apple-silicon Mac. There is no release workflow in CI
yet: packaging and publishing are local steps. What runs inside the app is in [`HUMAN_MODEL.md`](HUMAN_MODEL.md).

## What ships, and where

| Piece | Built by | Published to | How users get it |
|---|---|---|---|
| **Mac app** `Sauri-<v>-mac-arm64.dmg` | `make package` | GitHub Release `v<v>` on `lufermalgo/sauri` | First install, from the landing or the release page. |
| **Mac app** `Sauri-<v>-mac-arm64.zip` | `make package` | same release | The in-app updater downloads it. |
| `.sha256` beside each file | `make package` | same release | The updater checks the `.zip`; the landing shows the `.dmg`'s. |
| **Speaker component** `diar-<x>-mac-arm64.tar.gz` | `desktop/scripts/package-diar-component.sh` | GitHub Release `diar-<x>` | Downloaded by the app during setup, as named in `model-catalog.json`. |
| **Models** | upstream projects | Hugging Face, pinned by revision and SHA-256 | Downloaded by the app; nothing to publish. |
| **Chrome extension** | `npm run build -w extension` | Chrome Web Store | Separate cycle (below). |
| **Landing** | static files in `landing/` | GitHub Pages (`.github/workflows/pages.yml`) | `https://lufermalgo.github.io/sauri/` |

The app is **not signed or notarized by Apple**. `electron-builder.json` signs it ad hoc (`"identity": "-"`), with
the hardened runtime off. The first time, users confirm it in System Settings › Privacy & Security › "Open Anyway";
the README and the landing say so. Signing needs an Apple Developer ID, which is a cost decision for the owner.

## 1. Bump the version

The app version lives in `desktop/package.json` and must match the workspace entry in the root `package-lock.json`.

```bash
npm version 0.2.5 -w desktop --no-git-tag-version
git diff --stat        # exactly desktop/package.json and package-lock.json, one line each
```

The version becomes the bundle's `Info.plist` version, the `build.json` in the app, the file names and the `/health`
version the extension sees. It must be plain `x.y.z`, higher than the last release. Merge the bump through a normal
pull request; package from the merged `main`.

## 2. Package: `make package`

Run from a clean checkout of `main` on an Apple-silicon Mac. It does, in order:

1. **Runtime.** Reuses `~/Library/Caches/sauri-runtime-build/runtime-current` (`RUNTIME_DIR`) when it has a
   `runtime-manifest.json`; otherwise runs `desktop/scripts/build-runtime.sh` there (slow: Python, PostgreSQL, ffmpeg,
   whisper.cpp, llama.cpp, FluidAudio, every download checked against a pinned SHA-256). Rebuild it yourself when
   `desktop/runtime-manifest.json`, `desktop/requirements/` or the engine pins changed since the cached build.
2. **Portal.** `VITE_API_BASE_URL= npm run build -w frontend` (same-origin build).
3. **App code.** `npm run build -w desktop`.
4. **Stage.** `desktop/scripts/stage.mjs` lays out `desktop/.stage/`: the runtime without the downloadable pieces,
   `app-sources/` (backend code and the two catalogs in `scripts/engines/`), `portal/`, `THIRD_PARTY_NOTICES.md` and
   `build.json` (version, commit, what was left out).
5. **Build.** `electron-builder --mac --arm64`: a `.dmg` and a `.zip` in `desktop/out/`.
6. **Verify.** `desktop/scripts/verify-package.mjs`: the runtime inside `Sauri.app` is byte for byte the staged one,
   every pinned binary still equals `runtime-manifest.json`, and no stray Python bytecode was shipped. A re-signed
   `whisper-cli`, for example, would no longer match its pin and transcription would refuse to start.
7. **Checksums.** `shasum -a 256` writes `<file>.sha256` beside the `.dmg` and the `.zip` (`<hex>  <file name>`, the
   format the updater parses).
8. **Clean up** the stage, the unpacked app and builder leftovers, then list `desktop/out/`.

`make package-clean` removes the outputs; the cached runtime stays.

### Smoke test before publishing

Open the `.dmg`, run the app and check the first run, a short recording and the portal. To keep it away from a real
installation, start it with an isolated home and port block, which the installed app honours too:

```bash
SAURI_DESKTOP_HOME="$(mktemp -d)" SAURI_API_PORT=42750 /Applications/Sauri.app/Contents/MacOS/Sauri
```

Before replacing your own installed copy, make sure nothing is processing: the updater refuses then, and a manual
swap would interrupt the work.

## 3. Publish the GitHub Release

```bash
v=0.2.5; out=desktop/out
gh release create "v$v" --repo lufermalgo/sauri --target main --title "Sauri $v" --notes-file notes.md \
  "$out/Sauri-$v-mac-arm64.dmg" "$out/Sauri-$v-mac-arm64.dmg.sha256" \
  "$out/Sauri-$v-mac-arm64.zip" "$out/Sauri-$v-mac-arm64.zip.sha256"
```

- Tag `v<version>`, the same version as `desktop/package.json`. Published, not a draft or pre-release: the updater
  skips those.
- File names must be exactly `Sauri-<v>-mac-arm64.zip` and `Sauri-<v>-mac-arm64.zip.sha256`; a release without
  both is invisible to installed apps.
- It must be the repository's "Latest": the README links to `releases/latest`.
- **Notes** are for users, in plain language: what changed for them, what to do if anything. Spanish is fine (it is
  the app's default language); English is welcome too. No internal references, no paths from your Mac, nothing from
  real meetings. Mention once more that the app is not signed by Apple and how to open it.

## 4. How installed apps find it

`desktop/src/main/releases.ts` and `updater.ts`:

- Every 6 hours (and from the menu) the app reads
  `https://api.github.com/repos/lufermalgo/sauri/releases?per_page=20`. It takes the newest published `x.y.z` tag
  above its own version that carries the `.zip` and its `.sha256`. Tags such as `diar-0.1.0` are ignored.
- It downloads the `.zip` and checks it against the `.sha256`. **Every request and every redirect hop** must stay on the
  allow-list (`allowedUrl`): `api.github.com/repos/lufermalgo/sauri/releases`,
  `github.com/lufermalgo/sauri/releases/download/…` and `release-assets.githubusercontent.com`, HTTPS only, no
  credentials. If GitHub ever redirects downloads to another host, updates stop: fix `RELEASE_ASSET_HOSTS` and
  tell users to install that version from the `.dmg` by hand.
- It applies the update only when nothing is processing: back up the database, migrate with the new version, swap the
  app, relaunch; on failure it restores and keeps the old version.

Check after publishing:

```bash
curl -s "https://api.github.com/repos/lufermalgo/sauri/releases?per_page=20" | jq -r '.[0] | .tag_name, (.assets[].name)'
curl -sIL -o /dev/null -w '%{http_code}\n' "https://github.com/lufermalgo/sauri/releases/download/v$v/Sauri-$v-mac-arm64.zip"
```

A loopback rehearsal of the updater is possible with `SAURI_ALLOW_LOOPBACK_DOWNLOADS=1`, `SAURI_UPDATE_FEED_URL`
and `SAURI_RELEASES_BASE_URL` on `127.0.0.1` (see `releases.ts` and `updater.test.ts`).

## 5. Downloadable components

The speaker runtime (Senko and its Python dependencies) is too large for the app, so it ships alone.

1. `desktop/scripts/package-diar-component.sh --version 0.1.1` packs `components/diar` of the runtime into
   `desktop/out/diar-0.1.1-mac-arm64.tar.gz` and `.sha256`. The archive is reproducible. Its last line is the JSON
   (`version`, `release_tag`, `file`, `size`, `sha256`, `tree_sha256`, `unpacked_size`) for the `diar-runtime` entry
   of `scripts/engines/model-catalog.json`. Leave `catalog_version` alone; it is the file's schema version.
2. Publish the component **first**, without taking "Latest" from the app:

   ```bash
   gh release create diar-0.1.1 --repo lufermalgo/sauri --latest=false --title "Speaker component 0.1.1" \
     --notes "Speaker runtime for Sauri." desktop/out/diar-0.1.1-mac-arm64.tar.gz desktop/out/diar-0.1.1-mac-arm64.tar.gz.sha256
   ```

3. Merge the catalog change, then cut an app release. The catalog ships inside each app version, so installed apps
   only see a new component after they update. The host-engine downloads it under the same GitHub allow-list and
   checks the archive and the unpacked tree.

Models need no release: a model change is a catalog change (repository, pinned revision, file, size, SHA-256),
checked against the upstream file before it is merged.

## 6. Update the landing

The release config is a JSON block at the top of `landing/index.html` (`<script id="sauri-release">`):

| Field | Value |
|---|---|
| `version` | the new version |
| `downloadUrl` | `https://github.com/lufermalgo/sauri/releases/download/v<v>/Sauri-<v>-mac-arm64.dmg` |
| `fileSize` | the `.dmg` size as Finder shows it, e.g. `272 MB` |
| `sha256` | the hex from `Sauri-<v>-mac-arm64.dmg.sha256` |

Leave a value empty rather than guessing; the page hides what is empty. When `styles.css`, `tokens.css`, `release.js`
or `motion.js` change, bump their `?v=` value in `index.html`, `privacidad.html` and `404.html`. Merge to `main`; the
Pages workflow deploys. Then check that every link answers 200:

```bash
base=https://lufermalgo.github.io/sauri/
{ echo "$base"; echo "${base}sitemap.xml"
  for p in index.html privacidad.html; do
    grep -oE '(href|src)="[^"#:]+"' "landing/$p" | sed -E "s|^[a-z]+=\"([^\"]+)\"$|$base\1|"; done
  grep -ohE 'https://(lufermalgo\.github\.io|github\.com/lufermalgo)/[^"]+' landing/index.html
} | sort -u | while read -r u; do printf '%s %s\n' "$(curl -s -o /dev/null -L -w '%{http_code}' "$u")" "$u"; done
```

## 7. The Chrome extension

The extension has its own version (`extension/manifest.json`, `extension/package.json`) and its own cycle.
`npm run build -w extension` produces `extension/dist/sauri-extension.zip`; the publisher submits it in the Chrome Web
Store dashboard. Listing text, permission justifications and the version history are in `extension/CHROMEWEBSTORE.md`
and `extension/store/`. The app pairs only with extension ids in `ALLOWED_EXTENSION_IDS`
(`desktop/src/main/services.ts`): a new id needs an app release first. Keep the app's API compatible with the
extension version users already have; store review can take days.

## Checklist

- [ ] Version bumped in `desktop/package.json` and `package-lock.json`, merged to `main`.
- [ ] Cached runtime is current (rebuilt if pins or requirements changed).
- [ ] `make package` passed, including `verify-package`; `desktop/out/` has the `.dmg`, `.zip` and both `.sha256`.
- [ ] Smoke test on an isolated home: setup, a short recording, transcript, speakers, summary.
- [ ] Any new component released first (`diar-<x>`, `--latest=false`) and its catalog entry merged.
- [ ] Release `v<v>` published (not draft, not pre-release, marked Latest) with the four files and plain notes.
- [ ] Releases API lists it; the `.zip` URL answers 200.
- [ ] Landing release config updated (`version`, `downloadUrl`, `fileSize`, `sha256`, `?v=` if assets changed).
- [ ] After the Pages deploy, every landing link answers 200.
- [ ] An installed older version finds the update and applies it.
- [ ] Extension changes, if any, submitted to the Chrome Web Store and `CHROMEWEBSTORE.md` updated.
