# Third-party notices

Sauri for Mac (`Sauri.app`, built by `make package`) redistributes the components below. Each license was read
from the component's own license file (copied into the app from the exact source that was built or installed) or
from its project page; nothing here is assumed. Inside the app, the license texts are in
`Contents/Resources/runtime/licenses/` (native tools), `Contents/Resources/runtime/python/lib/python3.11/LICENSE.txt`
(CPython), each Python package's `*.dist-info` folder under `Contents/Resources/runtime/components/`, and
`Contents/Resources/LICENSE.electron.txt` and `LICENSES.chromium.html` (Electron and Chromium).

Sauri's own code is not covered by this file.

## Native components in the app

| Component | Version | License | Source | How it is shipped |
|---|---|---|---|---|
| Electron | 44.10.2 | MIT | https://github.com/electron/electron | App shell (`Sauri.app/Contents/Frameworks`). Chromium and its bundled libraries (FFmpeg among them) are listed in `LICENSES.chromium.html`. |
| CPython (python-build-standalone) | 3.11.18+20261026 | PSF-2.0 (plus the third-party licenses listed in CPython's `LICENSE.txt`) | https://github.com/astral-sh/python-build-standalone/releases/tag/20261026 | `runtime/python`. Built against libedit, not GNU readline; `_gdbm` is not built (python-build-standalone documentation), so no GPL code. |
| PostgreSQL | 16.16 | PostgreSQL License | https://ftp.postgresql.org/pub/source/v16.16/postgresql-16.16.tar.bz2 | `runtime/pg`, built from source (`--without-icu --without-readline`). |
| FFmpeg (`ffmpeg`, `ffprobe`) | 9.0.2 | LGPL-2.1-or-later (built without `--enable-gpl` and without `--enable-nonfree`) | https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz | `runtime/bin`, separate executables. See "FFmpeg source" below. |
| libopus | 1.6.1 | BSD-3-Clause | https://downloads.xiph.org/releases/opus/opus-1.6.1.tar.gz | Linked statically into `ffmpeg`. |
| whisper.cpp (`whisper-cli`, `whisper-vad-speech-segments`) | v1.9.5 (commit d1be6fde11ac6e0407606b4e42fe72d34add8037) | MIT | https://github.com/ggml-org/whisper.cpp | `runtime/bin`. |
| llama.cpp (`llama-server`) | commit af76639f728c69c74c873cc45f038aaa17afd09e | MIT | https://github.com/ggml-org/llama.cpp | `runtime/bin`. |
| FluidAudio (`fluidaudiocli`) | commit 16780f04d2ece24f67d0fc00efccd0296491c1a8 | Apache-2.0 | https://github.com/FluidInference/FluidAudio | `runtime/bin`. Compiled-in parts listed in FluidAudio's `ThirdPartyLicenses/` at that commit: NemoTextProcessing (text-processing-rs v0.3.0, Apache-2.0), VBx (Apache-2.0) and fastcluster (BSD-2-Clause, notice below). |

FluidAudio's LuxTTS lexicon bundle (`FluidAudio_LuxTtsG2pResources.bundle`) is **not** shipped: it is espeak-ng output
(GPL-3.0-or-later) and CC-BY-SA-4.0 word lists, outside FluidAudio's Apache-2.0
(`ThirdPartyLicenses/LuxTtsEnglishG2P-LICENSE.md`). Sauri does not use text-to-speech, and transcription with
`fluidaudiocli transcribe` was checked to work without it.

### FFmpeg source

The `ffmpeg` and `ffprobe` programs in the app were built from the unmodified FFmpeg 9.0.2 release:

- Source: https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz
- SHA-256: `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e`
- Release signature key: `FCF986EA15E6E293A5644F10B4322F04D67658D8`
- Build recipe: `build_ffmpeg` in `desktop/scripts/build-runtime.sh` (the exact `configure` options, static libopus
  1.6.1, no GPL and no nonfree parts). `runtime/bin/ffmpeg -buildconf` prints the options of the shipped binary.

To obtain the source, download the tarball above and check its SHA-256.

### fastcluster (compiled into `fluidaudiocli`)

Copyright:
  * Until package version 1.1.23: © 2011 Daniel Müllner <https://danifold.net>
  * All changes from version 1.1.24 on: © Google Inc. <https://www.google.com>
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

  * Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
  * Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

## Python packages in the app

Installed with `uv pip install --target` from the pinned files in `desktop/requirements/`. License names come from
each package's metadata and were checked against its license file in `*.dist-info`. The "Notes" column lists the
components that carry the package.

| Package | Version | License | Source | Notes |
|---|---|---|---|---|
| aio-pika | 10.2.3 | Apache-2.0 | https://github.com/mosquito/aio-pika | core |
| aiormq | 7.2.5 | Apache-2.0 | https://github.com/mosquito/aiormq | core |
| alembic | 1.20.1 | MIT | https://alembic.sqlalchemy.org | core |
| annotated-doc | 0.0.6 | MIT | https://github.com/fastapi/annotated-doc | asr-engine, core, host-engine, llm-engine |
| annotated-types | 0.8.0 | MIT | https://github.com/annotated-types/annotated-types | asr-engine, core, host-engine, llm-engine |
| anyio | 4.16.0 | MIT | https://github.com/agronholm/anyio | asr-engine, core, host-engine, llm-engine |
| argon2-cffi | 25.1.0 | MIT | https://github.com/hynek/argon2-cffi | core |
| argon2-cffi-bindings | 26.2.0 | MIT | https://github.com/hynek/argon2-cffi-bindings | core |
| asyncpg | 0.32.0 | Apache-2.0 | https://github.com/MagicStack/asyncpg | core |
| boto3 | 1.44.3 | Apache-2.0 | https://github.com/boto/boto3 | asr-engine, core |
| botocore | 1.44.3 | Apache-2.0 | https://github.com/boto/botocore | asr-engine, core |
| certifi | 2026.10.23 | MPL-2.0 | https://github.com/certifi/python-certifi | asr-engine, core, host-engine, llm-engine; MPL-2.0 (file-level copyleft; shipped unmodified, source at the URL) |
| cffi | 2.1.1 | MIT-0 | https://github.com/python-cffi/cffi | core |
| click | 8.5.1 | BSD-3-Clause | https://github.com/pallets/click/ | asr-engine, core, host-engine, llm-engine |
| fastapi | 0.163.0 | MIT | https://github.com/fastapi/fastapi | asr-engine, core, llm-engine |
| fastapi | 0.163.1 | MIT | https://github.com/fastapi/fastapi | host-engine |
| greenlet | 3.5.6 | MIT AND PSF-2.0 | https://greenlet.readthedocs.io | core |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 | asr-engine, core, host-engine, llm-engine |
| httpcore | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ | asr-engine, core, host-engine, llm-engine |
| httptools | 0.9.0 | MIT | https://github.com/MagicStack/httptools | asr-engine, core, host-engine, llm-engine |
| httpx | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx | asr-engine, core, host-engine, llm-engine |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna | asr-engine, core, host-engine, llm-engine |
| jmespath | 1.1.0 | MIT | https://github.com/jmespath/jmespath.py | asr-engine, core |
| Mako | 1.4.3 | MIT | https://www.makotemplates.org/ | core |
| MarkupSafe | 3.0.4 | BSD-3-Clause | https://github.com/pallets/markupsafe/ | core |
| multidict | 7.2.1 | Apache-2.0 | https://github.com/aio-libs/multidict | core |
| opentelemetry-api | 1.45.2 | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-api | asr-engine, core, host-engine, llm-engine |
| pamqp | 5.0.0 | BSD-3-Clause | https://github.com/gmr/pamqp | core |
| propcache | 0.5.4 | Apache-2.0 | https://github.com/aio-libs/propcache | core |
| pycparser | 3.12 | BSD-3-Clause | https://github.com/eliben/pycparser | core |
| pydantic | 2.14.3 | MIT | https://github.com/pydantic/pydantic | asr-engine, core, host-engine, llm-engine |
| pydantic_core | 2.50.4 | MIT | https://github.com/pydantic | asr-engine, core, host-engine, llm-engine |
| PyJWT | 2.15.1 | MIT | https://github.com/jpadilla/pyjwt | core |
| python-dateutil | 2.9.0.post0 | Apache-2.0 AND BSD-3-Clause | https://github.com/dateutil/dateutil | asr-engine, core |
| python-dotenv | 1.2.4 | BSD-3-Clause | https://github.com/theskumar/python-dotenv | asr-engine, core, host-engine, llm-engine |
| python-multipart | 0.0.33 | Apache-2.0 | https://github.com/Kludex/python-multipart | core |
| PyYAML | 6.0.3 | MIT | https://github.com/yaml/pyyaml | asr-engine, core, host-engine, llm-engine |
| s3transfer | 0.19.3 | Apache-2.0 | https://github.com/boto/s3transfer | asr-engine, core |
| six | 1.17.0 | MIT | https://github.com/benjaminp/six | asr-engine, core |
| SQLAlchemy | 2.1.8 | MIT | https://www.sqlalchemy.org | core |
| starlette | 1.10.0 | BSD-3-Clause | https://github.com/Kludex/starlette | asr-engine, core, host-engine, llm-engine |
| typing-inspection | 0.4.5 | MIT | https://github.com/pydantic/typing-inspection | asr-engine, core, host-engine, llm-engine |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions | asr-engine, core, host-engine, llm-engine |
| urllib3 | 2.8.0 | MIT | https://github.com/urllib3/urllib3 | asr-engine, core |
| uvicorn | 0.54.0 | BSD-3-Clause | https://uvicorn.dev/ | asr-engine, core, host-engine, llm-engine |
| uvloop | 0.23.0 | MIT OR Apache-2.0 | https://github.com/MagicStack/uvloop | asr-engine, core, host-engine, llm-engine |
| watchfiles | 1.3.0 | MIT | https://github.com/samuelcolvin/watchfiles | asr-engine, core, host-engine, llm-engine |
| websockets | 17.4 | BSD-3-Clause | https://github.com/python-websockets/websockets | asr-engine, core, host-engine, llm-engine |
| yarl | 1.25.1 | Apache-2.0 | https://github.com/aio-libs/yarl | core |

## Downloadable component: speaker runtime (`components/diar`)

Not inside the `.dmg` or `.zip`. It is published separately and downloaded during setup (design D9). It carries
the packages above marked `diar`, plus these:

| Package | Version | License | Source | Notes |
|---|---|---|---|---|
| attrs | 26.1.0 | MIT | https://github.com/python-attrs/attrs |  |
| cattrs | 26.2.1 | MIT | https://catt.rs |  |
| cloudpickle | 3.1.2 | BSD-3-Clause | https://github.com/cloudpipe/cloudpickle |  |
| colour-science | 0.4.7 | BSD-3-Clause | https://www.colour-science.org |  |
| coremltools | 9.0 | BSD-3-Clause | https://github.com/apple/coremltools |  |
| hdbscan | 0.8.44 | BSD-3-Clause | http://github.com/scikit-learn-contrib/hdbscan |  |
| joblib | 1.6.0 | BSD-3-Clause | https://joblib.readthedocs.io |  |
| llvmlite | 0.50.0 | BSD-2-Clause AND Apache-2.0 WITH LLVM-exception | https://github.com/numba/llvmlite | bundles LLVM (Apache-2.0 WITH LLVM-exception) |
| mpmath | 1.3.0 | BSD-3-Clause | https://github.com/fredrik-johansson/mpmath |  |
| narwhals | 2.28.0 | MIT | https://github.com/narwhals-dev/narwhals |  |
| numba | 0.68.1 | BSD-2-Clause | https://numba.pydata.org |  |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org |  |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |  |
| protobuf | 7.36.2 | BSD-3-Clause | https://developers.google.com/protocol-buffers/ |  |
| psutil | 7.2.2 | BSD-3-Clause | https://github.com/giampaolo/psutil |  |
| pyaml | 26.7.0 | WTFPL | https://github.com/mk-fg/pretty-yaml | permissive (WTFPL) |
| pynndescent | 0.7.0 | BSD-2-Clause | http://github.com/lmcinnes/pynndescent |  |
| scikit-learn | 1.9.1 | BSD-3-Clause | https://scikit-learn.org | bundles libomp (Apache-2.0 WITH LLVM-exception) |
| scipy | 1.17.1 | BSD-3-Clause | https://scipy.org/ | bundles libgfortran/libgcc_s (GPL-3.0-or-later WITH GCC-exception-3.1) and libquadmath (LGPL-2.1-or-later) as separate dylibs |
| senko | 0.1.0 | MIT | https://github.com/narcotic-sh/senko | bundles model weights: pyannote segmentation-3.0 (MIT, gated on Hugging Face) and CAM++ (Apache-2.0) |
| soundfile | 0.14.0 | BSD-3-Clause | https://github.com/bastibe/python-soundfile | bundles libsndfile (LGPL-2.1-or-later) as a separate dylib |
| sympy | 1.14.0 | BSD-3-Clause | https://github.com/sympy/sympy |  |
| termcolor | 3.3.0 | MIT | https://github.com/termcolor/termcolor |  |
| threadpoolctl | 3.8.0 | BSD-3-Clause | https://github.com/joblib/threadpoolctl |  |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | https://tqdm.github.io | MPL-2.0 part shipped unmodified |
| umap-learn | 0.6.0 | BSD-3-Clause | http://github.com/lmcinnes/umap |  |

Senko also ships CoreML and PyTorch weights: pyannote `segmentation-3.0` (MIT; https://huggingface.co/pyannote/segmentation-3.0)
and CAM++ `speech_campplus_sv_zh_en_16k-common_advanced` (Apache-2.0; listed in Senko's `THIRD_PARTY_LICENSES`).

## Portal (JavaScript bundled into `portal/assets`)

| Package | Version | License | Source |
|---|---|---|---|
| react | 18.3.1 | MIT | https://github.com/facebook/react |
| react-dom | 18.3.1 | MIT | https://github.com/facebook/react |
| scheduler | 0.23.2 | MIT | https://github.com/facebook/react |
| loose-envify | 1.4.0 | MIT | https://github.com/zertosh/loose-envify |
| js-tokens | 4.0.0 | MIT | https://github.com/lydell/js-tokens |
| use-sync-external-store | 1.7.0 | MIT | https://github.com/facebook/react |
| i18next | 26.7.2 | MIT | https://github.com/i18next/i18next |
| react-i18next | 17.1.13 | MIT | https://github.com/i18next/react-i18next |
| html-parse-stringify | 4.0.1 | MIT | https://github.com/i18next/html-parse-stringify |
| @babel/runtime | 7.29.7 | MIT | https://github.com/babel/babel |
| lucide-react | 1.66.0 | ISC | https://github.com/lucide-icons/lucide |

## Models: downloaded by the user, not redistributed

Sauri does not ship any model. The user downloads them from Hugging Face during setup; each download is checked
against the SHA-256 pinned in `scripts/engines/model-catalog.json`. Licenses as declared on each model card
(checked on 2026-11-18):

| Model (catalog id) | Hugging Face repository | License | Notes |
|---|---|---|---|
| whisper-large-v3-turbo-q5_0, whisper-small-q5_1 | ggerganov/whisper.cpp | MIT | GGML conversions of OpenAI Whisper. |
| silero-vad-v6.2.0 | ggml-org/whisper-vad | MIT | GGML conversion of Silero VAD. |
| parakeet-tdt-0.6b-v3-ultra-coreml | FluidInference/parakeet-ultra-coreml | CC-BY-4.0 | Core ML conversion of moondream/parakeet-ultra (CC-BY-4.0), a post-training of nvidia/parakeet-tdt-0.6b-v3 (CC-BY-4.0). Attribution is required; the portal shows it from the catalog. |
| qwen3.5-9b-q4_k_m | unsloth/Qwen3.5-9B-GGUF | Apache-2.0 | Quantization of Qwen/Qwen3.5-9B (Apache-2.0). |
| qwen3.5-4b-q4_k_m | unsloth/Qwen3.5-4B-GGUF | Apache-2.0 | Quantization of Qwen/Qwen3.5-4B. |
