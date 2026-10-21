# #505 verification notes — disposable object store for the live playback test

Verified by Ansel on 2026-10-21 (worktree `feature-issue-505-disposable-minio-ci`).
Everything below was executed, not inferred. Commands are reproducible.

## 1. BLOCKER: `minio/minio` is no longer pullable from Docker Hub

The committed candidate `bd02b9d` uses `minio/minio:latest`. That image cannot be
pulled any more, so the CI step would fail on a fresh GitHub runner.

Authoritative check (Docker Hub v2 repository API):

    https://hub.docker.com/v2/repositories/minio/minio/  -> HTTP 404 {"message":"object not found"}
    https://hub.docker.com/v2/repositories/minio/mc/     -> HTTP 404
    https://hub.docker.com/v2/repositories/rustfs/rustfs/ -> HTTP 200
    https://hub.docker.com/v2/repositories/rhysd/actionlint/ -> HTTP 200   (control)

The `minio` namespace listing on Docker Hub returns 20 repositories and neither
`minio` nor `mc` is among them. `docker pull minio/minio:latest` and
`docker pull quay.io/minio/minio:latest` both fail with 401; `dl.min.io` static
binaries return HTTP 410 Gone. MinIO's own README still points at
`quay.io/minio/minio`, but that path also requires credentials now.

Local `minio/minio:latest` (RELEASE.2025-09-07) is only in this machine's image
cache. A GitHub runner has no such cache, so local GREEN does not transfer.

## 2. SOLUTIONS: two pullable images verified end to end

### 2a. `bitnamilegacy/minio:2025.4.22` — real MinIO, RECOMMENDED

Found by Imre while the candidate was being reworked; independently verified here.
It is genuine MinIO (`Version: DEVELOPMENT.2025-04-22T22-12-26Z`), just served
from a namespace that still exists after the official `minio/minio` was removed.

    docker pull bitnamilegacy/minio:2025.4.22    # OK
    hub.docker.com/v2/repositories/bitnamilegacy/minio/ -> HTTP 200

Multi-arch index, covers the GitHub runner (amd64) and this machine (arm64):

    digest: sha256:50cec18ac4184af4671a78aedd5554942c8ae105d51a465fa82037949046da01
      linux/amd64 -> sha256:b55af04849786132c6571b916da9cfd77e1eaa813917929c06f023bebf94873b
      linux/arm64 -> sha256:ca15b14fa97abf68f856764b55bd9e6fa43a49bf95a1475b4a742c706cd0f38b

Verified behaviour:
  - Accepts `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` and
    `MINIO_API_CORS_ALLOW_ORIGIN`; health `/minio/health/ready` -> 200.
  - The server-side CORS env var is the way to set the policy (its S3 API still
    returns `NotImplemented` for `PutBucketCors`), so the current candidate
    shape - `put_bucket_cors` removed, `MINIO_API_CORS_ALLOW_ORIGIN` kept - is
    correct for this image.
  - CORS is enforced, not reflected: origin `http://localhost:5173` -> 204 with
    `access-control-allow-origin: http://localhost:5173`; origin
    `http://evil.example.com` -> 204 with NO allow-origin header.
  - Focused test result: `1 passed in 0.44s`.

Because it is real MinIO, the same env-var contract applies to the Compose
service in #512.

### 2b. `rustfs/rustfs` — S3-compatible alternative, fully verified

Also verified end to end, as a fallback if the Bitnami namespace disappears.
Different CORS mechanism: it IMPLEMENTS the S3 `PutBucketCors` API, so the
bucket CORS policy is set with the boto3 call that MinIO rejects, and
`MINIO_API_CORS_ALLOW_ORIGIN` is not used.

    docker pull rustfs/rustfs@sha256:9ca9559533b537d10482fe923288b676ad08f92a7069d9a17327fbae3cab688b   # OK

That digest is the multi-arch index and covers `linux/amd64` (GitHub runner) and
`linux/arm64`:
  - linux/amd64 -> sha256:128220dc9382bac81940a1a9616ee8c274a3f3b8f647eedbeb50df5bb8b49922
  - linux/arm64 -> sha256:a3951370f879374cb89cca3b495e05badab38807cc4cd609c54a35f93f6ccd64

Key difference from MinIO: **rustfs implements the S3 `PutBucketCors` API**.
So the CORS policy is set with the boto3 call that MinIO rejected with
`NotImplemented`. No server-side CORS env var is needed.

    client.put_bucket_cors(Bucket=bucket, CORSConfiguration={...})   # OK
    # readback: [{'AllowedHeaders': ['range'], 'AllowedMethods': ['GET'],
    #   'AllowedOrigins': ['http://localhost:5173'],
    #   'ExposeHeaders': ['Content-Range', 'Accept-Ranges'], 'MaxAgeSeconds': 300}]

## 3. Exact working CI step (rehearsed end to end)

For `bitnamilegacy/minio:2025.4.22` (real MinIO, recommended):

    docker run --detach --name sauri-ci-minio --publish 9000:9000 \
      --env MINIO_ROOT_USER="$MINIO_ROOT_USER" \
      --env MINIO_ROOT_PASSWORD="$MINIO_ROOT_PASSWORD" \
      --env MINIO_API_CORS_ALLOW_ORIGIN="$PLAYBACK_TEST_FRONTEND_ORIGIN" \
      bitnamilegacy/minio:2025.4.22

Notes proven locally:
  - The image already runs the server; no `server /data` or `--console-address`
    argument is needed (it is MinIO and those flags are also fine).
  - MinIO requires user >= 3 chars and password >= 8 chars; it refuses to start
    otherwise ("MINIO_ROOT_USER length should be at least 3, and
    MINIO_ROOT_PASSWORD length at least 8 characters").
  - Health endpoints work: `/minio/health/live` -> 200, `/minio/health/ready` -> 200,
    so the existing wait loop works unchanged.
  - Supply-chain note: `bitnamilegacy` is a THIRD-PARTY namespace, not Bitnami
    official. `bitnami/minio` still exists on Docker Hub but no longer serves
    the `latest` tag, and `bitnamilegacy` is where the legacy builds live. It is
    a fork of upstream MinIO, so pin the digest rather than trusting the tag
    implicitly, and treat "it is MinIO" as "it is a fork of MinIO".

## 4. Test result with a disposable object store

Focused test, unchanged from `origin/main`:

    OBJECT_STORE_ENDPOINT=http://127.0.0.1:9300 \
    OBJECT_STORE_BUCKET=sauri-recordings \
    MINIO_ROOT_USER=ciEphemeralUser \
    MINIO_ROOT_PASSWORD=ciEphemeralPassword \
    PLAYBACK_TEST_FRONTEND_ORIGIN=http://localhost:5173 \
    pytest tests/meetings/test_playback_storage_integration.py::test_signed_playback_source_supports_range_and_frontend_cors -q

    1 passed in 0.44s   (bitnamilegacy/minio)
    1 passed in 0.60s   (rustfs)

RED is the pre-existing `KeyError: 'OBJECT_STORE_ENDPOINT'` when the env is unset.

Full backend suite with the object store configured (rustfs run):
  - without object store: 4 failed, 281 passed, 3 skipped, 1 collection error
  - with object store:    3 failed, 282 passed, 3 skipped, 1 collection error
  (the object-store test is the one that flips from red to green; nothing else
   changed. The remaining failures are the known baseline: #249 speaker-review
   PUT schema, #407/#491 Alembic 009 lineage, #248 collection error.)

Note for QA: this worktree has no `backend/.venv`, so a QA run must use the
project venv at `/Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python`
or create one; Nia flagged exactly this on the previous round.

## 5. Baseline noise that is NOT a regression

`tests/transcription/test_worker.py::test_property_7_segment_to_turn_mapping`
fails intermittently with `hypothesis.errors.DeadlineExceeded` ("Test took
271.27ms, which exceeds the deadline of 200.00ms"). Reproduced with the object
store env unset: 1 passed, then 2 failed over three consecutive runs. It is a
Hypothesis deadline flake on the slower local 3.13 venv, already documented in
the ci.yml header as not reproducing in the CI runtime. Do not treat it as
caused by this change.

## 6. actionlint

Not installed on this machine, but it is runnable as a container (it pulls fine):

    docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest
    # -> 1.7.12, installed by building from source

## 7. Sequencing (re-checked 2026-10-21 ~21:25)

  - PR #509 `ci: secret-free lint, test and build checks` is OPEN and is the
    #497 workflow PR. The sequencing gate that blocked this card is satisfied.
  - `origin/feature/issue-497-secret-free-ci` is at `7501e47`
    ("fix(ci): pin actions and disable checkout credentials"), which this branch
    does not yet contain: `git rev-list --left-right --count` -> 1 behind / 3 ahead.
    Merge it in before finalising.
  - Open PR count is 4 (#506, #507, #509, #511). Team cap is 3, so opening the
    #505 PR needs a slot to be freed first. Do not close anything without Fer.
  - `origin/main` is `81a0932` (three PRs merged: #470, #477, #496).

## 8. Out of scope, but worth filing

`docker-compose.yml` still pins `image: minio/minio` (line 77), which is now
unpullable. The `sauri-fer-test` trial stack therefore cannot start its minio
service from a clean machine. This is a separate defect from #505 and should get
its own issue; it is not fixed by the CI change.
