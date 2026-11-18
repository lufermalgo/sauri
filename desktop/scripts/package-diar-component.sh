#!/usr/bin/env bash
# Turns the speaker runtime (components/diar of the runtime build) into the downloadable component of design D9:
#   desktop/out/diar-<version>-mac-arm64.tar.gz  and  .sha256
# The archive is reproducible: sorted entries, fixed times and owners, normalized modes and a gzip header without a
# timestamp, so the same tree always gives the same SHA-256. The tree is checked against desktop/runtime-manifest.json
# before packing. The last line printed is the JSON to put in the catalog entry `diar-runtime`
# (scripts/engines/model-catalog.json). Nothing is uploaded: publishing a release needs the owner's OK (design D13).
#
# Usage: desktop/scripts/package-diar-component.sh [--runtime DIR] [--version X.Y.Z] [--out DIR]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUNTIME="${SAURI_RUNTIME_DIR:-$HOME/Library/Caches/sauri-runtime-build/runtime-current}"
OUT="$ROOT/desktop/out"
VERSION=""
while [ $# -gt 0 ]; do
  case "$1" in
    --runtime) RUNTIME="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    *) echo "usage: $0 [--runtime DIR] [--version X.Y.Z] [--out DIR]" >&2; exit 2 ;;
  esac
done

PYTHON="$RUNTIME/python/bin/python3"
[ -x "$PYTHON" ] || { echo "no runtime Python at $PYTHON; run desktop/scripts/build-runtime.sh" >&2; exit 1; }
[ -d "$RUNTIME/components/diar" ] || { echo "no components/diar in $RUNTIME" >&2; exit 1; }
mkdir -p "$OUT"

# -B: this run must not leave stdlib bytecode in the runtime's python/ folder, which is shipped in the app.
# (-I ignores PYTHON* variables, so PYTHONDONTWRITEBYTECODE alone would not be enough.)
"$PYTHON" -I -B - "$RUNTIME" "$ROOT" "$OUT" "$VERSION" <<'PY'
import gzip, hashlib, json, os, re, sys, tarfile

runtime, root, out, version = sys.argv[1:5]
catalog_path = os.path.join(root, "scripts", "engines", "model-catalog.json")
catalog = json.load(open(catalog_path, encoding="utf-8"))
entry = next((m for m in catalog["models"] if m.get("kind") == "component" and m.get("component") == "diar"), None)
version = version or (entry or {}).get("version") or ""
if not re.fullmatch(r"\d{1,4}\.\d{1,4}\.\d{1,6}", version):
    sys.exit("give --version X.Y.Z (the catalog has no diar component yet)")

base = os.path.join(runtime, "components", "diar")
pinned = json.load(open(os.path.join(root, "desktop", "runtime-manifest.json"), encoding="utf-8"))
piece = next(a for a in pinned["artifacts"] if a.get("path") == "components/diar")

def file_sha(path):
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()

# Same walk and line format as build-runtime.sh's tree_sha256 (and host-engine's check after unpacking).
lines, files, dirs, size = [], [], [], 0
for dirpath, subdirs, names in os.walk(base):
    subdirs.sort()
    dirs.append(dirpath)
    for name in sorted(names):
        path = os.path.join(dirpath, name)
        rel = os.path.relpath(path, base)
        if os.path.islink(path):
            sys.exit(f"links are not shipped in a component: {rel}")
        if not os.path.isfile(path):
            sys.exit(f"not a regular file: {rel}")
        size += os.path.getsize(path)
        lines.append(f"{rel}\0{file_sha(path)}\n")
        files.append(path)
tree = hashlib.sha256("".join(lines).encode()).hexdigest()
if tree != piece["tree_sha256"]:
    sys.exit(f"components/diar does not match desktop/runtime-manifest.json (tree {tree}); rebuild the runtime")

name = f"diar-{version}-mac-arm64.tar.gz"
target = os.path.join(out, name)
temporary = target + ".tmp"
FIXED_TIME = 1700000000  # any constant: the archive must not depend on when it was made

def info(path, is_dir):
    rel = "diar" if path == base else "diar/" + os.path.relpath(path, base)
    item = tarfile.TarInfo(rel)
    item.uid = item.gid = 0
    item.uname = item.gname = ""
    item.mtime = FIXED_TIME
    if is_dir:
        item.type, item.mode = tarfile.DIRTYPE, 0o755
    else:
        item.size = os.path.getsize(path)
        item.mode = 0o755 if os.stat(path).st_mode & 0o111 else 0o644
    return item

def order(entry):  # parents before their contents, then by path parts
    return () if entry[0] == base else tuple(os.path.relpath(entry[0], base).split(os.sep))

entries = sorted([(d, True) for d in dirs] + [(f, False) for f in files], key=order)
with open(temporary, "wb") as raw:
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for path, is_dir in entries:
                item = info(path, is_dir)
                if is_dir:
                    tar.addfile(item)
                else:
                    with open(path, "rb") as handle:
                        tar.addfile(item, handle)
os.replace(temporary, target)
digest = file_sha(target)
with open(target + ".sha256", "w", encoding="utf-8") as handle:
    handle.write(f"{digest}  {name}\n")
print(f"{target}: {os.path.getsize(target)} bytes, {len(files)} files, {size} bytes unpacked", file=sys.stderr)
print(json.dumps({"version": version, "release_tag": f"diar-{version}", "file": name,
                  "size": os.path.getsize(target), "sha256": digest, "tree_sha256": tree, "unpacked_size": size}))
PY
