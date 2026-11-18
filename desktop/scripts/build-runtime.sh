#!/usr/bin/env bash
# Build the relocatable Sauri desktop runtime on an Apple silicon Mac (design D8, D9, D10).
#
# Usage:
#   build-runtime.sh [PIECE ...]   build the named pieces (default: all) into desktop/runtime/
#   build-runtime.sh --lock        regenerate desktop/requirements/*.txt (pinned, hashed where possible)
#   build-runtime.sh --verify [DIR] copy the runtime (default desktop/runtime) to a temp folder outside the
#                                  repository and exercise it with `env -i PATH=/usr/bin:/bin`
#   build-runtime.sh --clean       remove desktop/runtime/* (keeps the download cache)
#
# Pieces: python pg ffmpeg whisper llama fluidaudio components manifest
#
# Every download is HTTPS only and checked against the SHA-256 pinned below before it is unpacked; git
# sources are fetched by commit and checked with `git rev-parse`. A mismatch stops the build. Nothing is
# taken from Homebrew at run time: the build environment drops it from PATH and a final linkage check
# rejects any Mach-O file that points outside the runtime or the system.
set -euo pipefail
umask 022

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DESKTOP="$ROOT/desktop"
OUT="${SAURI_RUNTIME_DIR:-$DESKTOP/runtime}"
WORK="${SAURI_RUNTIME_WORK:-$HOME/Library/Caches/sauri-runtime-build}"
DOWNLOADS="$WORK/downloads"
LOCKS="$DESKTOP/requirements"
MANIFEST="$DESKTOP/runtime-manifest.json"
HASHES="$ROOT/scripts/engines/engine-hashes.json"
JOBS="$(sysctl -n hw.ncpu)"
export MACOSX_DEPLOYMENT_TARGET=14.0  # Parakeet (FluidAudio) needs macOS 14; see engine-hashes.json.

# ---- Pins ---------------------------------------------------------------------------------------------
CPYTHON_VERSION="3.11.18+20261026"
CPYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.11.18%2B20261026-aarch64-apple-darwin-install_only.tar.gz"
CPYTHON_SHA256="cba3455e18516fbe8668cff2820c9b6a53447c552d612443c2b2fb60d390a908"

PG_VERSION="16.16"
PG_URL="https://ftp.postgresql.org/pub/source/v16.16/postgresql-16.16.tar.bz2"
PG_SHA256="9d5cd8633043b75740d5d59749c6b7365e6aeb53c47098b1a5e80bb18f87881a"

# BSD-3-Clause; static, only for ffmpeg's `libopus` encoder (engine-common external/audio_prep.py).
OPUS_VERSION="1.6.1"
OPUS_URL="https://downloads.xiph.org/releases/opus/opus-1.6.1.tar.gz"
OPUS_SHA256="6ffcb593207be92584df15b32466ed64bbec99109f007c82205f0194572411a1"

# Also signed by the FFmpeg release key FCF986EA15E6E293A5644F10B4322F04D67658D8 (checked when pinned).
FFMPEG_VERSION="9.0.2"
FFMPEG_URL="https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz"
FFMPEG_SHA256="8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e"

WHISPER_VERSION="v1.9.5"
WHISPER_REPO="https://github.com/ggml-org/whisper.cpp.git"
WHISPER_COMMIT="d1be6fde11ac6e0407606b4e42fe72d34add8037"

LLAMA_REPO="https://github.com/ggml-org/llama.cpp.git"  # commit: engine-hashes.json llm.llama_cpp_commit
# fluidaudiocli: engine-hashes.json parakeet.source_repo / parakeet.source_commit

# Portable CPU baseline (M1 and later) instead of -mcpu=native; Metal does the heavy work.
GGML_FLAGS=(-DGGML_METAL=ON -DGGML_METAL_EMBED_LIBRARY=ON -DGGML_NATIVE=OFF
  -DGGML_CPU_ARM_ARCH=armv8.4-a+dotprod+fp16 -DGGML_OPENMP=OFF -DBUILD_SHARED_LIBS=OFF)
CMAKE_COMMON=(-DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_DEPLOYMENT_TARGET="$MACOSX_DEPLOYMENT_TARGET"
  "-DCMAKE_IGNORE_PREFIX_PATH=/opt/homebrew;/usr/local" -DCMAKE_FIND_USE_INSTALL_PREFIX=OFF)

COMPONENTS=(core host-engine asr-engine llm-engine diar)

# ---- Helpers ------------------------------------------------------------------------------------------
log() { printf '[build-runtime %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { printf '[build-runtime] ERROR: %s\n' "$*" >&2; exit 1; }
sha256_of() { shasum -a 256 "$1" | cut -d' ' -f1; }
PY="$OUT/python/bin/python3"
# The runtime's own CPython, isolated from the environment; -B so build steps leave no stray bytecode in python/.
rpy() { "$PY" -I -B "$@"; }

# Build tools come from a private folder: only cmake and pkg-config are borrowed, by absolute path, and
# never linked. Homebrew stays out of PATH so configure scripts cannot pick up its libraries.
sanitize_env() {
  local tools="$WORK/tools" tool
  mkdir -p "$tools"
  for tool in cmake pkg-config uv; do
    local path
    path="$(command -v "$tool" || true)"
    [[ -n "$path" ]] || die "missing build tool: $tool"
    ln -sf "$path" "$tools/$tool"
  done
  export PATH="$tools:/usr/bin:/bin:/usr/sbin:/sbin"
  unset CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH LIBRARY_PATH DYLD_LIBRARY_PATH DYLD_FALLBACK_LIBRARY_PATH \
    PKG_CONFIG_PATH CFLAGS CXXFLAGS CPPFLAGS LDFLAGS CMAKE_PREFIX_PATH HOMEBREW_PREFIX PYTHONPATH \
    PYTHONHOME VIRTUAL_ENV CONDA_PREFIX || true
  export PKG_CONFIG_LIBDIR="$WORK/empty-pkgconfig"  # nothing is visible unless a step says so
  mkdir -p "$PKG_CONFIG_LIBDIR"
}

fetch() {  # fetch <url> <sha256> -> prints the verified local path
  local url="$1" expected="$2" name dest
  [[ "$url" == https://* ]] || die "refusing non-HTTPS download: $url"
  name="$(basename "${url%%\?*}")"; name="${name//%2B/+}"
  dest="$DOWNLOADS/$name"
  mkdir -p "$DOWNLOADS"
  if [[ -f "$dest" && "$(sha256_of "$dest")" == "$expected" ]]; then echo "$dest"; return; fi
  rm -f "$dest" "$dest.part"
  curl --proto '=https' --tlsv1.2 --fail --location --retry 3 --silent --show-error "$url" -o "$dest.part" >&2
  local actual; actual="$(sha256_of "$dest.part")"
  if [[ "$actual" != "$expected" ]]; then
    rm -f "$dest.part"
    die "SHA-256 mismatch for $name (expected $expected, got $actual); artifact not used"
  fi
  mv "$dest.part" "$dest"
  echo "$dest"
}

git_checkout() {  # git_checkout <https repo> <commit> <dir>
  local repo="$1" commit="$2" dir="$3"
  [[ "$repo" == https://* ]] || die "refusing non-HTTPS git remote: $repo"
  rm -rf "$dir"
  git init -q "$dir"
  git -C "$dir" remote add origin "$repo"
  git -C "$dir" -c protocol.file.allow=never fetch -q --depth 1 origin "$commit"
  git -C "$dir" checkout -q --detach FETCH_HEAD
  [[ "$(git -C "$dir" rev-parse HEAD)" == "$commit" ]] || die "$repo is not at pinned commit $commit"
}

pin() {  # pin <section> <field> from scripts/engines/engine-hashes.json
  rpy -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]][sys.argv[3]])' "$HASHES" "$1" "$2"
}

stamp_ok() { [[ -f "$OUT/.stamps/$1" && "$(cat "$OUT/.stamps/$1")" == "$2" ]]; }
stamp_set() { mkdir -p "$OUT/.stamps"; printf '%s' "$2" >"$OUT/.stamps/$1"; }

fresh_dir() { rm -rf "$1"; mkdir -p "$1"; }

# ---- Pieces -------------------------------------------------------------------------------------------
build_python() {
  local key="$CPYTHON_VERSION $CPYTHON_SHA256"
  stamp_ok python "$key" && [[ -x "$PY" ]] && { log "python: up to date"; return; }
  local tarball; tarball="$(fetch "$CPYTHON_URL" "$CPYTHON_SHA256")"
  local tmp="$WORK/python-unpack"; fresh_dir "$tmp"
  tar -xzf "$tarball" -C "$tmp"
  [[ -x "$tmp/python/bin/python3" ]] || die "unexpected CPython archive layout"
  rm -rf "$OUT/python"; mv "$tmp/python" "$OUT/python"; rm -rf "$tmp"
  rpy -c 'import sys, ssl, sqlite3; assert sys.version_info[:2] == (3, 11); print(sys.version)'
  stamp_set python "$key"
  log "python: $CPYTHON_VERSION installed"
}

relocate_pg() {  # rewrite absolute install names under $OUT/pg to @rpath, resolved from each file's location
  rpy - "$OUT/pg" <<'PY'
import os, subprocess, sys
root = os.path.realpath(sys.argv[1]); lib = os.path.join(root, "lib")
MAGIC = {b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xcf"}
def macho(path):
    try:
        with open(path, "rb") as f: return f.read(4) in MAGIC
    except OSError: return False
changed = 0
for dirpath, _, files in os.walk(root):
    for name in files:
        path = os.path.join(dirpath, name)
        if os.path.islink(path) or not macho(path): continue
        out = subprocess.run(["otool", "-L", path], check=True, capture_output=True, text=True).stdout
        deps = [line.split()[0] for line in out.splitlines()[1:] if line.strip()]
        args = []
        ident = subprocess.run(["otool", "-D", path], check=True, capture_output=True, text=True).stdout.splitlines()[1:]
        if ident and ident[0].strip():  # a real dylib (lib/postgresql/*.dylib are bundles without an id)
            args += ["-id", "@rpath/" + name]
        needs_rpath = False
        for dep in deps:
            if dep.startswith(root + "/") or (dep.startswith("/") and "/pg/lib/" in dep and not dep.startswith("/usr/")):
                args += ["-change", dep, "@rpath/" + os.path.basename(dep)]; needs_rpath = True
        if needs_rpath:
            rel = os.path.relpath(lib, os.path.dirname(path))
            rpath = "@loader_path" if rel == "." else "@loader_path/" + rel
            existing = subprocess.run(["otool", "-l", path], check=True, capture_output=True, text=True).stdout
            if rpath not in existing: args += ["-add_rpath", rpath]
        if args:
            subprocess.run(["install_name_tool", *args, path], check=True, capture_output=True)
            subprocess.run(["codesign", "--force", "--sign", "-", path], check=True, capture_output=True)
            changed += 1
print(f"pg relocation: {changed} Mach-O files rewritten and ad-hoc signed")
PY
}

build_pg() {
  local key="$PG_VERSION $PG_SHA256 icu=no readline=no"
  stamp_ok pg "$key" && [[ -x "$OUT/pg/bin/postgres" ]] && { log "pg: up to date"; return; }
  local tarball; tarball="$(fetch "$PG_URL" "$PG_SHA256")"
  local src="$WORK/pg-src"; fresh_dir "$src"
  tar -xjf "$tarball" -C "$src" --strip-components 1
  rm -rf "$OUT/pg"
  log "pg: configuring $PG_VERSION"
  (cd "$src" && ./configure --prefix="$OUT/pg" --without-icu --without-readline --disable-rpath \
      --without-openssl --without-gssapi --without-ldap >"$WORK/pg-configure.log" 2>&1) \
    || { tail -30 "$WORK/pg-configure.log" >&2; die "PostgreSQL configure failed"; }
  log "pg: compiling"
  (cd "$src" && make -j "$JOBS" >"$WORK/pg-build.log" 2>&1 && make install-strip >>"$WORK/pg-build.log" 2>&1) \
    || { tail -30 "$WORK/pg-build.log" >&2; die "PostgreSQL build failed"; }
  rm -rf "$OUT/pg/include" "$OUT/pg/lib/pkgconfig" "$OUT/pg/lib/postgresql/pgxs"
  find "$OUT/pg/lib" -name '*.a' -delete
  relocate_pg
  mkdir -p "$OUT/licenses/postgresql"; cp "$src/COPYRIGHT" "$OUT/licenses/postgresql/"
  rm -rf "$src"
  stamp_set pg "$key"
  log "pg: $PG_VERSION installed"
}

build_ffmpeg() {
  local key="$FFMPEG_VERSION $FFMPEG_SHA256 opus=$OPUS_VERSION $OPUS_SHA256 lgpl"
  stamp_ok ffmpeg "$key" && [[ -x "$OUT/bin/ffmpeg" && -x "$OUT/bin/ffprobe" ]] && { log "ffmpeg: up to date"; return; }
  local opus_tar ff_tar; opus_tar="$(fetch "$OPUS_URL" "$OPUS_SHA256")"; ff_tar="$(fetch "$FFMPEG_URL" "$FFMPEG_SHA256")"
  local opus_src="$WORK/opus-src" opus_prefix="$WORK/opus-install" ff_src="$WORK/ffmpeg-src"
  fresh_dir "$opus_src"; fresh_dir "$opus_prefix"; fresh_dir "$ff_src"
  tar -xzf "$opus_tar" -C "$opus_src" --strip-components 1
  log "ffmpeg: building static libopus $OPUS_VERSION"
  (cd "$opus_src" && ./configure --prefix="$opus_prefix" --disable-shared --enable-static --with-pic \
      --disable-doc --disable-extra-programs >"$WORK/opus-build.log" 2>&1 \
    && make -j "$JOBS" >>"$WORK/opus-build.log" 2>&1 && make install >>"$WORK/opus-build.log" 2>&1) \
    || { tail -30 "$WORK/opus-build.log" >&2; die "libopus build failed"; }
  tar -xJf "$ff_tar" -C "$ff_src" --strip-components 1
  log "ffmpeg: configuring $FFMPEG_VERSION (LGPL, no --enable-gpl, no --enable-nonfree)"
  # Decode WebM/Matroska (Opus, Vorbis, VP8, VP9), MP4/MOV (H.264, AAC) and plain audio uploads; encode
  # 16 kHz PCM WAV for the engines, JPEG for thumbnails and Ogg/Opus for external providers.
  (cd "$ff_src" && PKG_CONFIG_LIBDIR="$opus_prefix/lib/pkgconfig" ./configure \
      --prefix="$WORK/ffmpeg-install" --cc=clang --arch=arm64 \
      --extra-cflags="-mmacosx-version-min=$MACOSX_DEPLOYMENT_TARGET" \
      --extra-ldflags="-mmacosx-version-min=$MACOSX_DEPLOYMENT_TARGET" \
      --pkg-config="$WORK/tools/pkg-config" --pkg-config-flags=--static \
      --disable-everything --disable-autodetect --disable-doc --disable-debug --disable-ffplay \
      --disable-shared --enable-static --enable-ffmpeg --enable-ffprobe \
      --enable-zlib --enable-libopus --enable-network \
      --enable-protocol=file,pipe,http,tcp \
      --enable-demuxer=matroska,mov,ogg,wav,mp3,aac,flac \
      --enable-muxer=wav,mjpeg,ogg,null \
      --enable-decoder=opus,vorbis,vp8,vp9,h264,aac,mp3,mp3float,flac,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le \
      --enable-encoder=pcm_s16le,mjpeg,libopus,wrapped_avframe \
      --enable-parser=opus,vorbis,vp8,vp9,h264,aac,mpegaudio,flac \
      --enable-filter=scale,format,aformat,aresample,anull,null,trim,atrim,setpts,asetpts,buffer,buffersink,abuffer,abuffersink \
      >"$WORK/ffmpeg-configure.log" 2>&1) \
    || { tail -30 "$WORK/ffmpeg-configure.log" >&2; die "ffmpeg configure failed"; }
  log "ffmpeg: compiling"
  (cd "$ff_src" && make -j "$JOBS" >"$WORK/ffmpeg-build.log" 2>&1) \
    || { tail -30 "$WORK/ffmpeg-build.log" >&2; die "ffmpeg build failed"; }
  mkdir -p "$OUT/bin" "$OUT/licenses/ffmpeg" "$OUT/licenses/opus"
  install -m 755 "$ff_src/ffmpeg" "$OUT/bin/ffmpeg"
  install -m 755 "$ff_src/ffprobe" "$OUT/bin/ffprobe"
  cp "$ff_src/COPYING.LGPLv2.1" "$ff_src/COPYING.LGPLv3" "$ff_src/LICENSE.md" "$OUT/licenses/ffmpeg/"
  printf 'Source: %s\nSHA-256: %s\n' "$FFMPEG_URL" "$FFMPEG_SHA256" >"$OUT/licenses/ffmpeg/SOURCE"
  cp "$opus_src/COPYING" "$OUT/licenses/opus/"
  local config; config="$("$OUT/bin/ffmpeg" -hide_banner -buildconf)"
  grep -q -- '--enable-gpl' <<<"$config" && die "ffmpeg was configured with --enable-gpl"
  grep -q -- '--enable-nonfree' <<<"$config" && die "ffmpeg was configured with --enable-nonfree"
  rm -rf "$opus_src" "$opus_prefix" "$ff_src"
  stamp_set ffmpeg "$key"
  log "ffmpeg: $FFMPEG_VERSION installed ($("$OUT/bin/ffmpeg" -hide_banner -L 2>/dev/null | head -1))"
}

build_whisper() {
  local key="$WHISPER_COMMIT ${GGML_FLAGS[*]}"
  stamp_ok whisper "$key" && [[ -x "$OUT/bin/whisper-cli" && -x "$OUT/bin/whisper-vad-speech-segments" ]] \
    && { log "whisper: up to date"; return; }
  local src="$WORK/whisper-src" build="$WORK/whisper-build"
  git_checkout "$WHISPER_REPO" "$WHISPER_COMMIT" "$src"; rm -rf "$build"
  log "whisper: building $WHISPER_VERSION ($WHISPER_COMMIT) with Metal"
  { cmake -S "$src" -B "$build" "${CMAKE_COMMON[@]}" "${GGML_FLAGS[@]}" \
      -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF -DWHISPER_SDL2=OFF -DWHISPER_FFMPEG=OFF \
      -DWHISPER_CURL=OFF -DWHISPER_COREML=OFF \
    && cmake --build "$build" --config Release -j "$JOBS" --target whisper-cli whisper-vad-speech-segments
  } >"$WORK/whisper-build.log" 2>&1 || { tail -30 "$WORK/whisper-build.log" >&2; die "whisper.cpp build failed"; }
  mkdir -p "$OUT/bin" "$OUT/licenses/whisper.cpp"
  install -m 755 "$build/bin/whisper-cli" "$OUT/bin/whisper-cli"
  install -m 755 "$build/bin/whisper-vad-speech-segments" "$OUT/bin/whisper-vad-speech-segments"
  cp "$src/LICENSE" "$OUT/licenses/whisper.cpp/"
  rm -rf "$src" "$build"
  stamp_set whisper "$key"
  log "whisper: installed"
}

build_llama() {
  local commit; commit="$(pin llm llama_cpp_commit)"
  local key="$commit ${GGML_FLAGS[*]}"
  stamp_ok llama "$key" && [[ -x "$OUT/bin/llama-server" ]] && { log "llama: up to date"; return; }
  local src="$WORK/llama-src" build="$WORK/llama-build"
  git_checkout "$LLAMA_REPO" "$commit" "$src"; rm -rf "$build"
  log "llama: building llama-server ($commit) with Metal"
  { cmake -S "$src" -B "$build" "${CMAKE_COMMON[@]}" "${GGML_FLAGS[@]}" -DLLAMA_OPENSSL=OFF -DLLAMA_CURL=OFF \
      -DLLAMA_BUILD_TESTS=OFF \
    && cmake --build "$build" --config Release -j "$JOBS" --target llama-server
  } >"$WORK/llama-build.log" 2>&1 || { tail -30 "$WORK/llama-build.log" >&2; die "llama.cpp build failed"; }
  local help; help="$("$build/bin/llama-server" --help 2>/dev/null)" || die "llama-server --help failed"
  grep -q -- '--reasoning-budget' <<<"$help" && grep -q -- '--no-context-shift' <<<"$help" \
    || die "llama-server lacks --reasoning-budget/--no-context-shift"
  mkdir -p "$OUT/bin" "$OUT/licenses/llama.cpp"
  install -m 755 "$build/bin/llama-server" "$OUT/bin/llama-server"
  cp "$src/LICENSE" "$OUT/licenses/llama.cpp/"
  rm -rf "$src" "$build"
  stamp_set llama "$key"
  log "llama: installed"
}

build_fluidaudio() {
  local commit repo; commit="$(pin parakeet source_commit)"; repo="$(pin parakeet source_repo)"
  stamp_ok fluidaudio "$commit" && [[ -x "$OUT/bin/fluidaudiocli" ]] && { log "fluidaudio: up to date"; return; }
  command -v swift >/dev/null 2>&1 && xcode-select -p >/dev/null 2>&1 \
    || die "fluidaudiocli needs Swift 6 and Xcode or the Command Line Tools (xcode-select --install)"
  local major; major="$(swift --version 2>&1 | grep -Eo 'Swift version [0-9]+' | grep -Eo '[0-9]+$' | head -1)"
  [[ "${major:-0}" -ge 6 ]] || die "fluidaudiocli needs Swift 6 or later (found: $(swift --version 2>&1 | head -1))"
  local src="$WORK/fluidaudio-src" build="$WORK/fluidaudio-build"
  git_checkout "$repo" "$commit" "$src"; rm -rf "$build"
  log "fluidaudio: building fluidaudiocli ($commit), about 3 minutes"
  (cd "$src" && swift build -c release --product fluidaudiocli --scratch-path "$build") \
    >"$WORK/fluidaudio-build.log" 2>&1 || { tail -30 "$WORK/fluidaudio-build.log" >&2; die "FluidAudio build failed"; }
  mkdir -p "$OUT/bin" "$OUT/licenses/FluidAudio"
  rm -rf "$OUT/bin/fluidaudiocli" "$OUT/bin/"FluidAudio_*.bundle
  cp -L "$build/release/fluidaudiocli" "$OUT/bin/fluidaudiocli"; chmod 755 "$OUT/bin/fluidaudiocli"
  # SwiftPM resource bundles are looked up next to the executable.
  local bundle
  for bundle in "$build/release/"*.bundle; do [[ -e "$bundle" ]] && cp -R "$bundle" "$OUT/bin/"; done
  cp "$src/LICENSE" "$OUT/licenses/FluidAudio/"
  rm -rf "$src" "$build"
  stamp_set fluidaudio "$commit"
  log "fluidaudio: installed"
}

component_requirements() {  # source requirement file of a component
  case "$1" in
    core) echo "$ROOT/backend/uv.lock" ;;
    host-engine) echo "$ROOT/backend/host-engine/requirements-native.txt" ;;
    asr-engine) echo "$ROOT/scripts/engines/requirements-native-asr.txt" ;;
    llm-engine) echo "$ROOT/backend/llm-engine/requirements-native.txt" ;;
    diar) echo "$ROOT/backend/diar-engine/requirements-native.txt" ;;
  esac
}

tested_venv() {  # the native-engine venv that runs today on this Mac; its versions are the tested set
  local base="$HOME/.local/share/sauri/native-engines"
  case "$1" in
    host-engine) echo "$base/host-venv" ;;
    asr-engine) echo "$base/asr-venv" ;;
    llm-engine) echo "$base/llm/venv" ;;
    diar) echo "$base/diar-venv" ;;
  esac
}

lock_requirements() {
  [[ -x "$PY" ]] || build_python
  mkdir -p "$LOCKS"
  local name tmp="$WORK/lock"; fresh_dir "$tmp"
  log "lock: core from backend/uv.lock (no dev extras)"
  (cd "$ROOT/backend" && uv export --frozen --no-dev --no-emit-project --format requirements-txt \
      --no-header -o "$tmp/core.txt" >/dev/null)
  { echo "# Generated by desktop/scripts/build-runtime.sh --lock from backend/uv.lock; do not edit."
    cat "$tmp/core.txt"; } >"$LOCKS/core.txt"
  for name in host-engine asr-engine llm-engine diar; do
    local venv source constraints hashes=(--generate-hashes)
    venv="$(tested_venv "$name")"; source="$(component_requirements "$name")"
    [[ -x "$venv/bin/python" ]] || die "tested venv for $name not found at $venv; run make engines-install first"
    uv pip freeze --python "$venv/bin/python" --exclude-editable >"$tmp/$name.constraints" 2>/dev/null
    [[ "$name" == diar ]] && hashes=()  # Senko is a git source; uv cannot hash-check it
    log "lock: $name from ${source#"$ROOT"/} constrained to the tested venv"
    uv pip compile "$source" -c "$tmp/$name.constraints" ${hashes[@]+"${hashes[@]}"} --python "$PY" \
      --python-platform aarch64-apple-darwin --no-header --no-annotate --quiet -o "$tmp/$name.txt"
    { echo "# Generated by desktop/scripts/build-runtime.sh --lock from ${source#"$ROOT"/},"
      echo "# constrained to the versions installed in the tested native-engine venv; do not edit."
      cat "$tmp/$name.txt"; } >"$LOCKS/$name.txt"
  done
  rm -rf "$tmp"
  log "lock: wrote ${LOCKS#"$ROOT"/}/*.txt"
}

build_components() {
  command -v uv >/dev/null || die "uv is required"
  local name
  for name in "${COMPONENTS[@]}"; do
    local lock="$LOCKS/$name.txt" target="$OUT/components/$name"
    [[ -f "$lock" ]] || die "missing ${lock#"$ROOT"/}; run $0 --lock"
    local key; key="$(sha256_of "$lock") $CPYTHON_VERSION"
    stamp_ok "component-$name" "$key" && [[ -d "$target" ]] && { log "component $name: up to date"; continue; }
    local flags=(--require-hashes --no-build)
    [[ "$name" == diar ]] && flags=()  # Senko is built from its pinned git commit
    log "component $name: installing from ${lock#"$ROOT"/}"
    rm -rf "$target"
    UV_PYTHON_DOWNLOADS=never UV_NO_CONFIG=1 uv pip install --quiet --target "$target" --python "$PY" \
      --python-platform aarch64-apple-darwin --no-deps --compile-bytecode ${flags[@]+"${flags[@]}"} -r "$lock" \
      >"$WORK/component-$name.log" 2>&1 || { tail -30 "$WORK/component-$name.log" >&2; die "component $name failed"; }
    rm -rf "$target/bin"  # console scripts carry absolute shebangs; the app runs `python -m` instead
    fix_build_ids "$target"
    stamp_set "component-$name" "$key"
  done
}

# A dylib built from source (Senko, sdists) keeps its build folder as its install name; make it relative.
fix_build_ids() {  # fix_build_ids <dir>
  rpy - "$1" "$HOME" <<'PY'
import os, subprocess, sys
root, home = sys.argv[1], sys.argv[2]
fixed = 0
for dirpath, _, files in os.walk(root):
    for name in files:
        path = os.path.join(dirpath, name)
        if os.path.islink(path) or not name.endswith((".dylib", ".so")): continue
        ident = [l for l in subprocess.run(["otool", "-D", path], capture_output=True, text=True).stdout.splitlines()
                 if not l.startswith(path)]  # drop the file-name headers (one per architecture)
        if ident and ident[0].startswith(home):
            subprocess.run(["install_name_tool", "-id", "@rpath/" + name, path], check=True, capture_output=True)
            subprocess.run(["codesign", "--force", "--sign", "-", path], check=True, capture_output=True)
            fixed += 1
if fixed: print(f"rewrote {fixed} build-folder install names under {os.path.basename(root)}")
PY
}

# Every dependency of every Mach-O file must be the system or a path relative to the file. Files we
# compile (bin/, pg/) must not carry any Homebrew or /usr/local search path; for third-party wheels such
# an unused LC_RPATH from their CI is reported as a warning.
check_linkage() {
  rpy - "$OUT" "$HOME" <<'PY'
import os, subprocess, sys
root, home = sys.argv[1], sys.argv[2]
MAGIC = {b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xcf"}
ALLOWED = ("/usr/lib/", "/System/Library/", "@rpath/", "@loader_path/", "@executable_path/")
bad, warn, count = set(), set(), 0
for dirpath, _, files in os.walk(root):
    for name in files:
        path = os.path.join(dirpath, name)
        if os.path.islink(path): continue
        try:
            with open(path, "rb") as f:
                if f.read(4) not in MAGIC: continue
        except OSError: continue
        count += 1; rel = os.path.relpath(path, root)
        own = {l.strip() for l in subprocess.run(["otool", "-D", path], capture_output=True, text=True).stdout.splitlines()
               if l.startswith(("/", "@")) or not l.endswith(":")}
        for line in subprocess.run(["otool", "-L", path], capture_output=True, text=True).stdout.splitlines():
            if not line.startswith("\t"): continue  # file/architecture headers
            dep = line.strip().split(" (compatibility")[0]
            if dep in own: continue  # the file's own install name
            if not dep.startswith(ALLOWED): bad.add(f"{rel} -> {dep}")
        loads = "\n".join(l for l in subprocess.run(["otool", "-l", path], capture_output=True, text=True)
                          .stdout.splitlines() if not l.startswith(path))  # drop the file-name headers
        if home in loads: bad.add(f"{rel} load commands mention the build user's home folder")
        for marker in ("/opt/homebrew", "/usr/local/"):
            if marker in loads:
                (warn if rel.startswith(("components/", "python/")) else bad).add(f"{rel} load commands mention {marker}")
for w in sorted(warn): print("warning:", w)
if bad:
    print("\n".join(sorted(bad)), file=sys.stderr)
    sys.exit(f"linkage check failed: {len(bad)} problems")
print(f"linkage check: {count} Mach-O files, every dependency is the system or relative ({len(warn)} warnings)")
PY
}

write_manifest() {
  local llama_commit fluid_commit fluid_repo senko
  llama_commit="$(pin llm llama_cpp_commit)"; fluid_commit="$(pin parakeet source_commit)"; fluid_repo="$(pin parakeet source_repo)"
  senko="$(grep -Eo 'senko @ git\+[^ ]+' "$ROOT/backend/diar-engine/requirements-native.txt")"
  rpy - "$OUT" "$MANIFEST" <<PY
import hashlib, json, os, sys
root, manifest = sys.argv[1], sys.argv[2]
def file_sha(path):
    with open(path, "rb") as f: return hashlib.file_digest(f, "sha256").hexdigest()
def tree(rel):
    base = os.path.join(root, rel); lines = []; size = 0
    for dirpath, dirs, files in os.walk(base):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                lines.append(f"{os.path.relpath(path, base)}\0link:{os.readlink(path)}\n"); continue
            size += os.path.getsize(path)
            lines.append(f"{os.path.relpath(path, base)}\0{file_sha(path)}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest(), len(lines), size
def mb(n): return round(n / 1_000_000, 1)
def binaries(names):
    out = {}; total = 0
    for name in names:
        path = os.path.join(root, "bin", name); total += os.path.getsize(path)
        out[name] = {"sha256": file_sha(path), "size_mb": mb(os.path.getsize(path))}
    return out, total
def lock_sha(name):
    return file_sha(os.path.join("$LOCKS", name + ".txt"))
artifacts = []
def tree_entry(entry, rel):
    digest, count, size = tree(rel)
    entry.update(path=rel, tree_sha256=digest, file_count=count, size_mb=mb(size)); artifacts.append(entry)
tree_entry({"name": "cpython", "version": "$CPYTHON_VERSION", "license": "PSF-2.0",
            "source_url": "$CPYTHON_URL", "source_sha256": "$CPYTHON_SHA256"}, "python")
tree_entry({"name": "postgresql", "version": "$PG_VERSION", "license": "PostgreSQL",
            "source_url": "$PG_URL", "source_sha256": "$PG_SHA256",
            "configure": "--without-icu --without-readline --disable-rpath; install names rewritten to @rpath"}, "pg")
for name, version, commit, url, files in (
    ("whisper.cpp", "$WHISPER_VERSION", "$WHISPER_COMMIT", "$WHISPER_REPO", ["whisper-cli", "whisper-vad-speech-segments"]),
    ("llama.cpp", None, "$llama_commit", "$LLAMA_REPO", ["llama-server"]),
    ("fluidaudio", None, "$fluid_commit", "$fluid_repo", ["fluidaudiocli"]),
):
    bins, total = binaries(files)
    entry = {"name": name, "version": version, "commit": commit, "source_url": url, "source_sha256": None,
             "source_pin": "git commit", "binaries": bins, "size_mb": mb(total)}
    if name == "fluidaudio":
        extra = sorted(d for d in os.listdir(os.path.join(root, "bin")) if d.endswith(".bundle"))
        entry["resource_bundles"] = extra
        entry["size_mb"] = mb(total + sum(tree("bin/" + d)[2] for d in extra))
    artifacts.append(entry)
bins, total = binaries(["ffmpeg", "ffprobe"])
artifacts.append({"name": "ffmpeg", "version": "$FFMPEG_VERSION", "license": "LGPL-2.1-or-later (no GPL, no nonfree)",
                  "source_url": "$FFMPEG_URL", "source_sha256": "$FFMPEG_SHA256",
                  "signature_key": "FCF986EA15E6E293A5644F10B4322F04D67658D8",
                  "static_libraries": [{"name": "libopus", "version": "$OPUS_VERSION", "license": "BSD-3-Clause",
                                        "source_url": "$OPUS_URL", "source_sha256": "$OPUS_SHA256"}],
                  "binaries": bins, "size_mb": mb(total)})
for name in ("core", "host-engine", "asr-engine", "llm-engine", "diar"):
    entry = {"name": "component-" + name, "requirements": "desktop/requirements/%s.txt" % name,
             "requirements_sha256": lock_sha(name), "python": "$CPYTHON_VERSION",
             "distribution": "downloadable" if name == "diar" else "base"}
    if name == "diar": entry["git_sources"] = ["$senko"]
    tree_entry(entry, "components/" + name)
base = sum(a["size_mb"] for a in artifacts if a.get("distribution") != "downloadable")
doc = {"schema": 1, "platform": "macos-arm64", "minimum_macos": "$MACOSX_DEPLOYMENT_TARGET",
       "built_by": "desktop/scripts/build-runtime.sh", "base_size_mb": round(base, 1),
       "downloadable_size_mb": round(sum(a["size_mb"] for a in artifacts if a.get("distribution") == "downloadable"), 1),
       "artifacts": artifacts}
text = json.dumps(doc, indent=2) + "\n"
for path in (manifest, os.path.join(root, "runtime-manifest.json")):
    with open(path + ".tmp", "w") as f: f.write(text)
    os.replace(path + ".tmp", path)
for a in artifacts: print(f"  {a['name']:<22} {a['size_mb']:>8} MB")
print(f"  {'base total':<22} {doc['base_size_mb']:>8} MB")
PY
}

# ---- Relocation check ---------------------------------------------------------------------------------
verify_runtime() {
  local source="${1:-$OUT}"
  [[ -x "$source/python/bin/python3" ]] || die "no runtime at $source"
  local tmp; tmp="$(mktemp -d /tmp/sauri-runtime-verify.XXXXXX)"
  log "verify: copying $source to $tmp/runtime"
  cp -R "$source" "$tmp/runtime"
  local media="$tmp/media"; mkdir -p "$media"
  cp "$ROOT/extension/src/fixtures/synthetic-av.webm" "$media/vp8-opus.webm"
  cp "$ROOT/landing/assets/follow.webm" "$media/vp9.webm"
  local h264=0 hbffmpeg; hbffmpeg="$(command -v ffmpeg || true)"
  if [[ -n "$hbffmpeg" && "$hbffmpeg" != "$tmp"/* ]]; then  # test input only, made before the clean run
    "$hbffmpeg" -v error -f lavfi -i testsrc=size=640x360:rate=25 -f lavfi -i sine=frequency=440 -t 2 \
      -c:v libx264 -pix_fmt yuv420p -c:a aac "$media/h264-aac.mp4" && h264=1
  fi
  env -i PATH=/usr/bin:/bin HOME="$tmp" TMPDIR="$tmp" H264="$h264" /bin/bash -euo pipefail -c '
    R="$1/runtime"; M="$1/media"; D="$1/pgdata"; S="$1/run"; mkdir -p "$S"
    show() { local n="$1" rc=0; shift; "$@" >"$1.out" 2>&1 || rc=$?; head -n "$n" "$1.out"; echo "(exit $rc)"; }
    echo "PATH=$PATH"; ! command -v brew >/dev/null || { echo "brew visible"; exit 1; }
    echo "--- python"; "$R/python/bin/python3" -I -c "import sys; print(sys.version.split()[0], sys.prefix)"
    for c in core:fastapi,sqlalchemy,asyncpg,alembic,uvicorn,argon2,jwt,aio_pika host-engine:fastapi,uvicorn,httpx \
             asr-engine:fastapi,uvicorn,pydantic,boto3,httpx llm-engine:fastapi,uvicorn,httpx diar:fastapi,senko,coremltools; do
      name="${c%%:*}"; mods="${c#*:}"
      PYTHONPATH="$R/components/$name" PYTHONNOUSERSITE=1 PYTHONSAFEPATH=1 "$R/python/bin/python3" -c "import $mods" \
        && echo "component $name: import $mods ok"
    done
    echo "--- postgresql"
    "$R/pg/bin/initdb" -D "$D" -U sauri --auth=trust -E UTF8 --locale=C >/dev/null && echo "initdb ok"
    "$R/pg/bin/pg_ctl" -D "$D" -o "-c listen_addresses= -k $S" -l "$1/pg.log" -w start
    "$R/pg/bin/psql" -h "$S" -U sauri -d postgres -Atc "select version()"
    "$R/pg/bin/pg_ctl" -D "$D" -w stop
    echo "--- whisper-cli --help"; show 3 "$R/bin/whisper-cli" --help
    echo "--- whisper-vad-speech-segments --help"; show 3 "$R/bin/whisper-vad-speech-segments" --help
    echo "--- llama-server --version"; "$R/bin/llama-server" --version 2>&1 | grep -E "^version|^built with"
    echo "--- fluidaudiocli transcribe --help"; show 2 "$R/bin/fluidaudiocli" transcribe --help
    echo "--- ffprobe -version"; "$R/bin/ffprobe" -version | head -1
    echo "--- ffmpeg -L"; "$R/bin/ffmpeg" -hide_banner -L | head -1
    echo "--- ffmpeg functional"
    "$R/bin/ffmpeg" -nostdin -v error -y -i "$M/vp8-opus.webm" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$1/a.wav" && echo "webm(opus) -> wav16k ok"
    "$R/bin/ffmpeg" -nostdin -v error -protocol_whitelist file -i "$M/vp8-opus.webm" -map 0:v:0 -frames:v 1 -vf scale=320:-2 -q:v 5 -f mjpeg pipe:1 | head -c 3 | od -An -tx1
    "$R/bin/ffmpeg" -nostdin -v error -i "$M/vp9.webm" -map 0:v:0 -frames:v 1 -vf scale=320:-2 -f mjpeg "$1/vp9.jpg" && echo "vp9 -> jpeg ok"
    "$R/bin/ffmpeg" -nostdin -v error -y -i "$1/a.wav" -c:a libopus -b:a 24000 -vbr constrained -application voip -f ogg "$1/a.ogg" && echo "wav -> ogg/libopus ok"
    "$R/bin/ffprobe" -v error -print_format json -show_entries format=duration:stream=codec_type "$M/vp8-opus.webm" | tr -d " \n"; echo
    if [ "$H264" = 1 ]; then
      "$R/bin/ffmpeg" -nostdin -v error -i "$M/h264-aac.mp4" -map 0:v:0 -frames:v 1 -f mjpeg "$1/h264.jpg" && echo "h264 -> jpeg ok"
      "$R/bin/ffmpeg" -nostdin -v error -y -i "$M/h264-aac.mp4" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$1/b.wav" && echo "mp4(aac) -> wav16k ok"
    else echo "h264 sample not generated (no reference ffmpeg); H.264 decode NOT VERIFIED"; fi
  ' verify "$tmp"
  rm -rf "$tmp"
  log "verify: done"
}

# ---- Main ---------------------------------------------------------------------------------------------
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || die "requires macOS on Apple silicon"
mkdir -p "$OUT" "$WORK"

case "${1:-}" in
  --verify) verify_runtime "${2:-}"; exit 0 ;;
  --clean) find "$OUT" -mindepth 1 -maxdepth 1 ! -name .gitignore -exec rm -rf {} +; log "cleaned $OUT"; exit 0 ;;
  --lock) sanitize_env; lock_requirements; exit 0 ;;
esac

PIECES=("$@")
[[ ${#PIECES[@]} -gt 0 ]] || PIECES=(python pg ffmpeg whisper llama fluidaudio components manifest)
sanitize_env
started=$SECONDS
for piece in "${PIECES[@]}"; do
  [[ -x "$PY" || "$piece" == python ]] || build_python
  case "$piece" in
    python) build_python ;;
    pg) build_pg ;;
    ffmpeg) build_ffmpeg ;;
    whisper) build_whisper ;;
    llama) build_llama ;;
    fluidaudio) build_fluidaudio ;;
    components) build_components ;;
    manifest) check_linkage; write_manifest ;;
    *) die "unknown piece: $piece" ;;
  esac
done
log "finished in $(( (SECONDS - started) / 60 )) min"
