# Design Document — Meeting Summaries and Templates

Spec: `.spectra/specs/meeting-summaries-templates/`
Requirements source: `requirements.md` @ commit `f5aa6b3e4d1e2c8a0816743f11de8a7a6ad8c43a`
(blob `4778a46e72f5022a5baf272cf987db0299ac1c0b`, SHA-256 `68fbb706d03d0c0bc7c397d6aaccf0c1297eb5777bb4c69563eaa2909e25389a`), Mira-APPROVED round 4, 2026-10-15 16:19, run `run_65668bdab7b74476`.
Baseline source: `PRODUCT_BASELINE.md` @ blob `fc498d2f0b79b780725238be388b61b908381811`
(approval record `22df139`; blob `6c6a3c3e…` @ `d738e78` carries the same product content).
Owner decision: Fer, 2026-10-15 — templates personal per user; one personal default selected
in platform settings, applied automatically across all categories to each transcription
summary until changed; initial release ships exactly one defined template.

## Resumen

Sauri currently produces a transcript and diarization per meeting, but the meeting view in the
web portal has no summary artifact and the platform has no notion of templates. The approved
requirements ask for (a) a structured summary as a distinct meeting artifact, (b) copy/download
of that summary, (c) user-owned, editable summary templates with optional categories, and (d) a
single personal default template selected in platform settings that is applied automatically to
every transcription summary for that user until changed. The spec deliberately leaves the
summary-generation method, accuracy thresholds, template visual layout, broader access-control
policy, and retention/deletion rules unresolved; this design does not decide them.

The solution consists of:

1. **Templates module** (`backend/app/templates/`): user-owned `Summary_Template` and
   `Template_Category` tables plus CRUD API under `/api/v1/templates`, following the existing
   router → service → repository → schemas layering, JWT auth, and sales-user authorization.
2. **Default-template resolution service**: a deterministic, dependency-free resolver in the
   templates module that, for a user with a configured default, returns that template id;
   per the owner decision it applies to transcription summaries automatically, across all
   categories. Behavior when no default is configured stays unspecified and the resolver
   returns `None` without guessing a fallback.
3. **Summaries module** (`backend/app/summaries/`): a `Meeting_Summary` entity persisted
   1:1 per meeting with a `template_id`/`template_version` lineage, produced by a dedicated
   `summarize` queue worker triggered when the transcription transaction commits (same
   enqueue pattern as the existing `transcribe` → `diarize` handoff).
4. **A fixed, structure-agnostic canonical summary model** (`topic` + `key_points`, the only
   two structural elements the requirements name), shaped by template-driven content selection
   and rendered to Markdown by a pure renderer.
5. **Meeting-view integration**: a new summary section in the portal's meeting view, distinct
   from transcript and notes, with copy and download actions; a platform-settings view for
   template CRUD and default selection.
6. **Tests-first TDD plan**: property tests (with `hypothesis`, ≥100 examples) for the
   resolver/renderer/selection contracts and unit/integration tests for API and worker
   behavior, each property sequenced RED before its implementation.

## Decisiones de Diseño Clave

**D1 — Summary generation stays out of scope; the design defines the mechanism, not the
method.** The requirements do not select a generation method or accuracy threshold. The design
therefore defines where summaries are produced (a queue worker triggered by transcription), what
they persist (a structured model), and what the worker requires to run (a `SummarizationEngine`
protocol). The engine's internal method is a task-level implementation choice, constrained by
the protocol, not a product decision made here. *Alternativas descartadas:* choosing an LLM
provider here would invent unapproved product scope; leaving generation entirely open would
leave the architecture under-specified for Zoya's task plan, since the worker, persistence, and
lineage model do not depend on which engine fills the protocol.

**D2 — Template applies to content selection, not visual layout.** A `Summary_Template`'s
stored form is a declarative **content-selection spec** (which structural elements to include),
validated at save time. `topic` and `key_points` are the only structural elements named by the
approved requirements, so the initial release defines exactly those two, both `true` in the one
defined template. What the requirements call "structure" is realized as content selection over
that fixed set; the Markdown layout of the rendered artifact is fixed by the renderer and is
not part of the template. *Alternativas descartadas:* a free-form prompt/markdown template
would be a generation method (unapproved, unbounded validation); a free-form section schema
would invent product structure the spec does not define; an empty set (a template selecting
nothing) would allow a template that produces no summary, which no acceptance criterion
supports — minimum selection is one element.

**D3 — Default is one nullable column on `users`, not a row in a per-user settings table.**
The owner decision gives every user at most one default template across all categories. A
`users.default_summary_template_id` FK (nullable, ON DELETE SET NULL) models that invariant
structurally; a separate settings table would need an extra uniqueness constraint to enforce
the same thing and adds a join for every generation. Category is carried by the template
itself, so "applies across all categories" needs no category-aware resolution logic — the
default is category-independent by construction. *Alternativas descartadas:* a per-category
default table contradicts the recorded decision; a general key/value settings table invites
unapproved future settings semantics and couples unrelated features.

**D4 — One summary per meeting; lineage-keyed idempotent overwrite.** `meeting_summaries`
carries a unique constraint on `meeting_id` (same 1:1 pattern as `transcripts`/`diarizations`).
The stored row's lineage (`template_id`, `template_version`) records what shaped it. The
requirements bind the default only to **subsequent** summaries (R5.6), so no automatic
re-shaping of historical summaries is defined; the upsert mechanism exists so that a further
`summarize` delivery (e.g. queue redelivery) is a deterministic no-op when the stored lineage
matches the currently resolved default, and an overwrite (with `generation + 1`) when lineage
differs. Template `version` increments exactly when the selection spec changes (name/category
edits do not alter what the template selects). *Alternativas descartadas:* a version-history
table invents retention the spec excludes and gives the initial release no requirement to
satisfy; regenerating on every delivery without lineage comparison makes worker behavior
nondeterministic under redelivery.

**D5 — Lineage is data, not authorization; template names are visible, definitions are not.**
Requirement 3.3 is verified through lineage: a generated summary records which template shaped
it. Lineage does not entitle a user to read another user's template definition; the templates
API only ever exposes the requesting user's own templates. The summary GET includes the
shaping template's **name** (resolved via FK; the template row cannot disappear while
referenced, since no deletion endpoint exists and the FK has no cascade) so the default is
identifiable in the UI (R5.4) without exposing definitions. *Alternativas descartadas:*
full definition read-through would silently create template sharing, which the owner decision
does not grant; hiding lineage entirely would leave "identify the default" (R5.4) unverifiable.

**D6 — The stored summary is the shaped artifact, in structured form plus rendered Markdown.**
The worker persists the **post-selection** content (the canonical elements restricted by the
template's selection) as structured columns, plus `rendered_markdown` for exact copy/download.
The summary IS the template-shaped output (R3.3), so storing unshaped engine output would
misrepresent the artifact; structured columns (not just the rendered string) keep the
selection invariants (P1) verifiable at the artifact level. *Alternativas descartadas:*
storing rendered Markdown only would make selection properties untestable against stored data;
storing unshaped engine output would decouple the artifact from the template that produced it.

**D7 — Design fixes data + transport only; portal layout stays open.** The requirements and
baseline explicitly leave portal layout unresolved. The design therefore specifies the API
surface, the `MeetingSummary` shared type, and a distinct summary section inside the existing
meeting view — and nothing about placement or styling beyond that. The baseline's imagined
left/center/right layout is recorded as future inspiration, not adopted. *Alternativas
descartadas:* adopting the imagined layout would decide an explicitly open question; skipping
frontend integration entirely would leave the requirements unverifiable end-to-end.

**D8 — Copy/download without extra endpoints.** Copy uses `navigator.clipboard` on already
fetched summary content; download serializes the same fetched content client-side as a
`.md` file via `URL.createObjectURL` + anchor click. No new backend endpoint is needed.
*Alternativas descartadas:* a backend `/download` endpoint adds auth surface for zero
requirement value; any extension clipboard bridge is outside this spec's surfaces.

**D9 — No default-behavior invented where the spec is silent.** Where the approved
requirements deliberately leave behavior unspecified, the design does not fill the gap: no
fallback template exists, so the resolver returns `None` when no default is configured and
generation simply does not run; engine failures follow the existing transcription-worker
discipline (exceptions propagate uncaught; queue redelivery governs) without new retry
semantics; access control reuses the existing sales-user policy without extending it; template
or category deletion is not designed because the requirements do not grant it. These silences
are requirements-scope boundaries, not gaps this design may close.

**D10 — Summaries in relational storage, not the object store.** The meeting summary is a
small, structured, per-meeting artifact queried by meeting id, like transcripts; object storage
is for media blobs. *Alternativas descartadas:* object-store storage would complicate querying
and lineage without any requirement benefit at this scale.

**D11 — Stable, meeting-scoped download filename.** The downloaded file is named
`meeting-summary-<meetingId>.md`: stable across downloads of the same meeting (re-downloading
overwrites the same local file), ASCII-safe, and free of locale-dependent date formatting.
*Alternativas descartadas:* date-stamped names would accumulate duplicate files and introduce
locale decisions the spec does not make; meeting-title-based names would leak rename history
into filenames.

**D12 — Template-driven content selection, not template-side rendering.** The renderer owns
all rendering; a template never carries markup. This keeps the template schema
requirements-shaped (D2) and makes "structure reflects the template" testable as selection
invariants (P1, P2) instead of string comparisons. *Alternativas descartadas:* template-carried
markup would smuggle layout authority into user data — an unapproved layout decision — and
would require sanitization the spec does not ask for.

**D13 — New API returns snake_case; the frontend maps explicitly.** The existing backend
endpoints serialize snake_case keys (verified: `GET /api/v1/meetings/{id}/transcript` returns
`transcript_id`, `supports_turns`, …; the templates endpoints likewise use Pydantic's default
snake_case), while `@sauri/shared-types` and `frontend/src/api.ts` use camelCase types. The
new endpoints follow the backend's snake_case convention, and `api.ts` gains **explicit
mapper functions** into the camelCase shared types for every new endpoint, so the frontend
contract is real instead of a blind cast. The pre-existing mismatch for older endpoints is
observed evidence only; this spec does not touch those endpoints. *Alternativas descartadas:*
camelCase responses would deviate from the adjacent transcript/diarization endpoints;
perpetuating the blind-cast pattern would repeat a latent runtime bug in new code.

## Arquitectura

```mermaid
graph TD
    subgraph "Web Frontend (React SPA)"
        MV["MeetingView with summary section (new)"]
        TV["TranscriptView (existing)"]
        TSV["TemplateSettingsView (new, platform settings)"]
        APIF["frontend/src/api.ts (extended, explicit mappers)"]
    end

    subgraph "Backend FastAPI"
        TR["templates/router.py<br/>/api/v1/templates"]
        TS["templates/service.py"]
        TREP["templates/repository.py"]
        SR["summaries/router.py<br/>/api/v1/meetings/{id}/summary"]
        SS["summaries/service.py"]
        SREP["summaries/repository.py"]
        RES["templates/default_resolver.py"]
        REN["summaries/renderer.py (pure)"]
    end

    subgraph "Workers (queue consumers)"
        TW["transcription worker (existing)"]
        SW["summaries worker (new, topic 'summarize')"]
        ENG["SummarizationEngine protocol"]
    end

    subgraph "PostgreSQL"
        T["summary_templates"]
        C["template_categories"]
        MS["meeting_summaries"]
        U["users (+ default_summary_template_id)"]
    end

    MV --> APIF
    TSV --> APIF
    APIF -->|REST + JWT| TR
    APIF -->|REST + JWT| SR
    TW -->|publish summarize on transcript commit| SW
    SW --> RES
    SW --> ENG
    SW --> REN
    SW --> SREP
    TR --> TS --> TREP
    SR --> SS --> SREP
    TS --> U
    TREP --> T
    TREP --> C
    SREP --> MS
```

Data flow — automatic default-template application (Requirements 5.5, 5.6):

```mermaid
sequenceDiagram
    participant TW as transcription worker
    participant Q as JobQueue (RabbitMQ)
    participant SW as summaries worker
    participant RES as default_resolver
    participant DB as PostgreSQL
    participant ENG as SummarizationEngine

    TW->>Q: publish "summarize" {meeting_id} (after transcript tx commit)
    Q->>SW: deliver message
    SW->>DB: load meeting, transcript, stored summary lineage
    alt default configured (users.default_summary_template_id not null)
        SW->>RES: resolve(user default row)
        RES-->>SW: template_id + version (or None if row vanished)
        alt stored lineage == resolved lineage
            SW->>DB: no-op (idempotent skip, D4)
        else lineage differs or no stored summary
            SW->>ENG: generate(transcript text)
            ENG-->>SW: canonical topic + key_points
            SW->>DB: upsert shaped summary + lineage + generation
        end
    else no default configured (unspecified by requirements)
        SW->>DB: nothing to do; skip silently
    end
```

Sequence notes (verified against `backend/app/transcription/worker.py` at `f5aa6b3e`): the
transcription worker currently publishes `{"meeting_id": ...}` to `"diarize"` after the
transcript transaction commits and does not alter `Meeting.process_state`. The summaries
worker receives the same message shape and likewise does not mutate `Meeting.process_state` —
summary generation is not a state-machine transition, so no new `ProcessState` value is
introduced (editing the state machine is outside this spec's approved scope).

## Componentes e Interfaces

### 1. Backend module: `backend/app/templates/`

New module following the project's router → service → repository → schemas layering
(patterns verified in `meetings/`, `ingestion/`, `transcription/`).

**`schemas.py`** (Pydantic v2; `backend/pyproject.toml` declares `pydantic>=2.0.0`):

```python
class TemplateSelectionSpec(BaseModel):
    """Declarative content-selection spec stored on a template (D2)."""
    include_topic: bool = True
    include_key_points: bool = True

    @model_validator(mode="after")
    def at_least_one_element(self) -> "TemplateSelectionSpec":
        if not (self.include_topic or self.include_key_points):
            raise ValueError("at least one structural element must be selected")
        return self

class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    category_id: str | None = None
    selection: TemplateSelectionSpec = TemplateSelectionSpec()

class TemplateUpdate(BaseModel):
    # All fields optional; None means "leave unchanged" (partial PATCH).
    # A PATCH convention detail (e.g. explicit-null clearing) is a task-level decision.
    name: str | None = Field(None, min_length=1, max_length=128)
    category_id: str | None = None
    selection: TemplateSelectionSpec | None = None

class TemplateOut(BaseModel):
    id: str
    name: str
    owner_user_id: str
    category_id: str | None
    version: int
    selection: TemplateSelectionSpec
    is_default: bool
    created_at: str  # ISO 8601
    updated_at: str  # ISO 8601

class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)

class CategoryOut(BaseModel):
    id: str
    name: str
    owner_user_id: str
    created_at: str
```

**`router.py`** — `prefix="/api/v1/templates"`, all routes JWT-authenticated and gated by the
existing `require_sales` authorization dependency (pattern verified in
`backend/app/auth/authorization.py`; denials are recorded in `access_log`):

| Method | Path | Purpose | Success | Notes |
|--------|------|---------|---------|-------|
| POST | `/api/v1/templates` | create template | 201 + `TemplateOut` | body `TemplateCreate`; `category_id` must belong to user, else 422 |
| GET | `/api/v1/templates` | list own templates | 200 + `TemplateOut[]` | identifies the default via `is_default` (R5.4) |
| GET | `/api/v1/templates/categories` | list own categories | 200 + `CategoryOut[]` | declared before `/{template_id}` (see guard below) |
| POST | `/api/v1/templates/categories` | create category | 201 + `CategoryOut` | |
| GET | `/api/v1/templates/{template_id}` | get own template | 200 / 404 | 404 also for another user's template (no existence leak) |
| PATCH | `/api/v1/templates/{template_id}` | edit own template | 200 + `TemplateOut` | bumps `version` when the selection changes (D4) |
| PUT | `/api/v1/templates/default` | set own default | 204 | body `{"template_id": str}`; template must be owned by the user, else 422 |

Static route ordering guard: `GET /api/v1/templates/categories` must be registered before
`GET /api/v1/templates/{template_id}` in the router file, or FastAPI resolves the path
parameter first and returns 404 with `template_id="categories"`.

`is_default` is computed by the service layer by comparing the template id with the user's
`users.default_summary_template_id`; it is not stored on the template row.

### 2. Backend module: `backend/app/summaries/`

**`engine.py`** — protocol only (D1):

```python
class SummarizationEngine(Protocol):
    async def generate(self, transcript_text: str) -> CanonicalSummary: ...
```

`CanonicalSummary` (Pydantic model): `topic: str`, `key_points: list[str]`. The engine is
selection-agnostic: it always produces the canonical elements from the transcript text; the
worker applies template selection (P1) afterwards, so selection stays testable without any
engine and engines stay interchangeable (D1).

**`repository.py`** — `SummaryRepository`: `upsert(summary_row)`,
`get_by_meeting(meeting_id)`, with the same session/transaction ownership conventions as
`TranscriptRepository` (verified: the caller controls the transaction; the repository does not
open, close, or commit the session).

**`service.py`** — `SummaryService`: `get_summary_for_user(meeting_id, user)` enforcing
meeting ownership (404 semantics below) and composing `render_markdown` output for the
response.

**`renderer.py`** — pure functions (no I/O):

```python
def apply_selection(summary: CanonicalSummary, selection: TemplateSelectionSpec) -> CanonicalSummary:
    """Returns the summary restricted to the selected structural elements (D2, D6)."""

def render_markdown(summary: CanonicalSummary) -> str:
    """Renders the fixed Markdown layout (D12). Never produces whitespace-only output."""
```

Renderer Markdown layout (fixed by design, not by template):

```markdown
# Meeting Summary

## Topic

<topic text>

## Key Points

- <point 1>
- <point 2>
```

Sections are omitted when not selected (template-driven) and rendered in the fixed order
above. When the stored topic text is empty, the renderer emits `-` for it (never empty
output).

**`worker.py`** — mirrors `transcription/worker.py` (verified message-validation and
exception disciplines at `f5aa6b3e`):

- Subscribes to topic `"summarize"`; message `{"meeting_id": str}`.
- Discards invalid/empty `meeting_id` with a warning log (same discipline as the
  transcription worker).
- Loads the meeting and its transcript; if either is missing, logs and returns (queue
  redelivery governs; no custom retry loop).
- Resolves the default template for `meeting.created_by` via
  `templates.default_resolver` (repository joins `users.default_summary_template_id` →
  `summary_templates`); if `None`, logs "no default configured; skipping summary generation"
  and returns. No fallback behavior is invented (D9).
- **Idempotent skip (D4):** if a stored summary exists whose `(template_id, template_version)`
  equals the resolved default's, acks without regenerating.
- Calls the configured `SummarizationEngine` via `create_summarization_engine()` (factory
  reading `SUMMARIZATION_PROVIDER` from env, same pattern as `transcription/factory.py`;
  an unrecognized value raises `ValueError` at worker startup, mirroring
  `create_asr_engine()`). Engine exceptions propagate uncaught — the same discipline as the
  transcription worker — so queue redelivery governs retries (D9).
- Applies `apply_selection(content, template.selection)`, then persists via
  `SummaryRepository.upsert` in a single transaction with the shaped content
  (`topic`, `key_points_json`), `rendered_markdown = render_markdown(shaped)` stored for
  exact-copy integrity, `template_id`, `template_version = template.version`,
  `generation = previous.generation + 1` (or 1 when none), and `updated_at = now(UTC)`.
- Publishes nothing downstream; does not mutate `Meeting.process_state`.

**Wiring in `backend/app/worker.py`**: `start_worker` imported from `app.summaries.worker`
and subscribed after the diarization worker (one import + one call, matching the existing
bootstrap; verified structure of `backend/app/worker.py`).

**Enqueue point**: `backend/app/transcription/worker.py` gains one call after the transcript
transaction commits, alongside the existing `diarize` publish:

```python
if queue is not None and transcript_created:
    await queue.publish("summarize", {"meeting_id": meeting_id})
```

### 3. Backend API surface: meeting summary read

Added in `backend/app/summaries/router.py`, registered in `backend/app/main.py`:

| Method | Path | Purpose | Success | Errors |
|--------|------|---------|---------|--------|
| GET | `/api/v1/meetings/{meeting_id}/summary` | get the meeting's summary artifact | 200 | 404 meeting / 404 summary / 403 non-sales |

Access rule: same as every meeting route — meeting must exist and
`meeting.created_by == user.id`, else `404` (the existing meetings routes' 404-not-403
ownership convention, verified at `backend/app/meetings/router.py`); `require_sales` still
gates the route itself with `403` + audit log for non-sales users.

GET response body (snake_case keys, D13):

```json
{
  "summary_id": "uuid",
  "meeting_id": "uuid",
  "template_id": "uuid",
  "template_name": "Default Summary Template",
  "template_version": 3,
  "topic": "...",
  "key_points": ["..."],
  "rendered_markdown": "# Meeting Summary\n\n## Topic\n\n...",
  "generation": 2,
  "created_at": "2026-10-15T21:04:00+00:00",
  "updated_at": "2026-10-15T21:04:00+00:00"
}
```

`template_name` is always included (name only; definitions are never exposed through this
endpoint, D5). There is no regeneration endpoint: the requirements bind the default to
subsequent transcription summaries only, so historical summaries are not re-shaped on demand
(see Scope Boundaries).

### 4. Data model additions (`backend/app/infra/models.py` + Alembic migration `008_`)

```python
class TemplateCategory(Base):
    """Optional grouping for a user's summary templates (R4)."""
    __tablename__ = "template_categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SummaryTemplate(Base):
    """User-owned, editable summary template (R3, R4, R5)."""
    __tablename__ = "summary_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    category_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("template_categories.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    include_topic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    include_key_points: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MeetingSummary(Base):
    """Structured summary artifact, 1:1 with a meeting (R1, R5)."""
    __tablename__ = "meeting_summaries"
    __table_args__ = (UniqueConstraint("meeting_id", name="uq_meeting_summary_meeting_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("summary_templates.id"), nullable=False
    )
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False, default="")
    key_points_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    rendered_markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

Plus, in the existing `User` model (`backend/app/infra/models.py`):

```python
default_summary_template_id: Mapped[str | None] = mapped_column(
    String(36), ForeignKey("summary_templates.id", ondelete="SET NULL"), nullable=True
)
```

`key_points_json` is order-preserving JSON text (see P2). All ids are `String(36)` UUIDs and
timestamps are `DateTime(timezone=True)`, matching every existing table (verified in
`backend/app/infra/models.py`).

Alembic migration `008_summaries_and_templates.py`
(`down_revision = "007_rename_schema_to_english"`, the verified current head):

1. `CREATE TABLE template_categories`, then `CREATE TABLE summary_templates` (columns as
   above; creation order matters — `users` must exist, and `users.default_summary_template_id`
   will reference `summary_templates`).
2. `CREATE TABLE meeting_summaries` (unique `meeting_id`).
3. `ALTER TABLE users ADD COLUMN default_summary_template_id VARCHAR(36) NULL REFERENCES
   summary_templates(id) ON DELETE SET NULL`.
4. Seed the one defined template (R5.1) **for each existing user**: `id` uuid4,
   `owner_user_id = user.id`, `name = 'Default Summary Template'`, `category_id = NULL`,
   `version = 1`, `include_topic = TRUE`, `include_key_points = TRUE`,
   `created_at = updated_at = now()`; then set each user's `default_summary_template_id` to
   their own copy's id. Naming rationale: the requirements and baseline explicitly state that
   `General > Resumen básico` is a proposal, not an approved default/template, so the seed
   uses a neutral name instead of silently adopting an unapproved label. The seed makes R5.1
   immediately satisfiable and demonstrates the default mechanism for existing users without
   inventing per-user fallback logic. It skips users that already own a template (guard).
   New users created afterwards by `backend/app/auth/seed.py` receive the same treatment in
   the application layer (a post-seed step creating the defined template + default per
   seeded user).
5. `downgrade()` reverses in exact reverse order (drop `users.default_summary_template_id`,
   drop `meeting_summaries`, drop `summary_templates`, drop `template_categories`).

### 5. Default-template resolver (`backend/app/templates/default_resolver.py`)

```python
from typing import NamedTuple

class ResolvedDefault(NamedTuple):
    template_id: str
    version: int

def resolve_default(template_row: "SummaryTemplate | None") -> ResolvedDefault | None:
    """Pure function: the user's configured default template, or None (D9)."""
    if template_row is None:
        return None
    return ResolvedDefault(template_id=template_row.id, version=template_row.version)
```

The repository layer supplies the user's default template row (join
`users.default_summary_template_id` → `summary_templates`); the pure function owns the
None-handling so the None semantics stay unit-testable without a database. The FK
`ON DELETE SET NULL` guarantees the DB cannot hold a dangling default id; if the referenced
row vanished inside a transaction race, the resolver's `None` path covers it.

### 6. Shared types (`packages/shared-types/src/index.ts`)

```typescript
/** Structured summary artifact associated 1:1 with a meeting (R1). */
export interface MeetingSummary {
  summaryId: string;
  meetingId: string;
  templateId: string;
  templateName: string;
  templateVersion: number;
  topic: string;
  keyPoints: string[];
  renderedMarkdown: string;
  generation: number;
  createdAt: string;
  updatedAt: string;
}

/** User-owned summary template (R3–R5). */
export interface SummaryTemplate {
  id: string;
  name: string;
  ownerId: string;
  categoryId?: string;
  version: number;
  selection: { includeTopic: boolean; includeKeyPoints: boolean };
  isDefault: boolean;
  createdAt: string;
  updatedAt: string;
}

/** Optional template grouping (R4). */
export interface TemplateCategory {
  id: string;
  name: string;
  ownerId: string;
  createdAt: string;
}
```

### 7. Web frontend integration (`frontend/src/`)

**`api.ts`** additions (same `getAuthHeaders`/`handleResponse` pattern, verified in the
existing file; every new function maps its snake_case response explicitly into the camelCase
shared types, D13):

```typescript
export async function getSummary(meetingId: string): Promise<MeetingSummary>;
export async function listTemplates(): Promise<SummaryTemplate[]>;
export async function createTemplate(input: {
  name: string;
  categoryId?: string | null;
  selection: { includeTopic: boolean; includeKeyPoints: boolean };
}): Promise<SummaryTemplate>;
export async function updateTemplate(
  id: string,
  input: Partial<{
    name: string;
    categoryId: string | null;
    selection: { includeTopic: boolean; includeKeyPoints: boolean };
  }>,
): Promise<SummaryTemplate>;
export async function listCategories(): Promise<TemplateCategory[]>;
export async function createCategory(name: string): Promise<TemplateCategory>;
export async function setDefaultTemplate(templateId: string): Promise<void>;
```

**`components/SummarySection.tsx`** (new): rendered inside the meeting view as a **separate
section** from the transcript view (R1.1). Owns local state only (`summary | null`,
`loading`, `error`); fetches on mount via `getSummary`; renders `renderedMarkdown` as
pre-formatted text (no new Markdown dependency); provides:

- **Copy** button → `navigator.clipboard.writeText(summary.renderedMarkdown)` (R2.1); success
  feedback is local UI state ("Copied"), no alert/dialog.
- **Download** button → serializes `summary.renderedMarkdown` into a `Blob`
  (`type: "text/markdown;charset=utf-8"`), object URL, anchor click named
  `meeting-summary-<meetingId>.md` (R2.2, D11).
- **Not-available state**: if `getSummary` returns 404 (no summary yet — e.g. no default
  configured, or generation not run), the section renders a neutral "No summary available for
  this meeting yet." message. This is a UI-state design, not a no-default fallback behavior
  (D9).

**`components/TemplateSettingsView.tsx`** (new): platform-settings surface for templates.
Reached from `App.tsx` by extending the `View` union type (verified current shape:
`{ type: "list" } | { type: "transcript"; meetingId: string }`) with `{ type: "templates" }`
and a nav entry. Contains:

- Template list with `isDefault` identification (R5.4) and a "Set as default" action per
  template (R5.3); the current default is visually marked.
- Create/edit template form: `name`, category dropdown (own categories + "No category",
  R4.3), and the two selection checkboxes (D2). Validation errors from 422 render inline.
- Category creation inline form (R4).

### 8. Worker bootstrap and configuration

- `SUMMARIZATION_PROVIDER` env var selects the engine via
  `summaries/factory.py::create_summarization_engine()`; recognized values and their default
  are fixed at task level (the protocol, not the provider, is the design contract). Startup
  raises `ValueError` on an unrecognized value, mirroring `create_asr_engine()`.
- No new Compose service is introduced. The summaries worker subscribes inside the existing
  worker process (`backend/app/worker.py`), avoiding the known Compose/diarization-engine gap
  pattern (AGENTS.md: the Compose stack does not define a diarization-engine service; do not
  widen that gap for summaries).

## Modelos de Datos

Entity-relationship additions (PostgreSQL, migration `008_summaries_and_templates`):

```mermaid
erDiagram
    USERS ||--o{ SUMMARY_TEMPLATES : owns
    USERS ||--o| SUMMARY_TEMPLATES : "default_summary_template_id (SET NULL)"
    USERS ||--o{ TEMPLATE_CATEGORIES : owns
    TEMPLATE_CATEGORIES ||--o{ SUMMARY_TEMPLATES : groups
    SUMMARY_TEMPLATES ||--o{ MEETING_SUMMARIES : "lineage (template_id, template_version)"
    MEETINGS ||--o| MEETING_SUMMARIES : "1:1 (uq_meeting_summary_meeting_id)"
    MEETINGS ||--o| TRANSCRIPTS : "input to generation"
```

Key data contracts:

- `summary_templates` selection is stored as two boolean columns (`include_topic`,
  `include_key_points`), not JSON, so DB-level NOT NULL/defaults are enforceable and the
  "at least one selected" rule is validated in the schema layer
  (`TemplateSelectionSpec` validator, D2).
- `meeting_summaries.key_points_json` preserves order; the renderer emits list items in
  stored order (P2).
- `meeting_summaries` has no `state`/`failure_cause` columns: a row exists only after a
  successful generation (failed attempts leave no row; queue redelivery governs retries,
  D9) — the artifact's existence is its state.
- Foreign keys: `meeting_summaries.meeting_id` cascades with the meeting (consistent with
  `transcripts`/`diarizations`); `meeting_summaries.template_id` has no cascade and no
  deletion endpoint exists, so lineage rows remain resolvable (D5);
  `users.default_summary_template_id` uses `SET NULL` (D3).

## Propiedades de Correctitud

**P1 — Template application is content selection (R3.3, R5.5).**
For any template `T` with selection `S` and any canonical summary `C`:
`shaped = apply_selection(C, S)`; then
`shaped.topic == C.topic` iff `S.include_topic`, else `shaped.topic == ""`;
`shaped.key_points == C.key_points` iff `S.include_key_points`, else `shaped.key_points == []`.
Also: the summary persisted for a generation carries `template_id == T.id` and
`template_version == T.version` at generation time, and its stored structured content equals
`apply_selection(engine_output, S)` (lineage + shaped artifact, D4/D5/D6).
*Valida: R3.3, R5.5.*

**P2 — Renderer determinism and content preservation.**
For any shaped summary `S'`:
`render_markdown(S')` is deterministic (same input → same output string); it preserves the
stored order of `key_points`; it contains the topic text iff it is non-empty (an empty topic
renders as `-`); it never produces an empty or whitespace-only string (minimum artifact is
`# Meeting Summary`); every element not present in `S'` is absent from the output.
*Valida: R1.2 (clearly organized content), R2.1/R2.2 (copy/download carry the exact content).*

**P3 — Default resolution is unique, personal, and category-blind (R5.3–R5.6).**
For any user `u` and any snapshot of `users`/`summary_templates`:
- at most one default exists for `u` (single nullable column, D3);
- `resolve_default` returns that template's `(id, version)`, or `None` iff the column is null
  (D9: no fallback invented);
- the resolved template's `owner_user_id == u.id` (personal; enforced by FK + service checks);
- resolution never reads the template's category (category-blind, R5.3/R5.5);
- workers re-resolve the default per message (no cached default), so after the user changes
  the default, subsequent generations use the new one (R5.6).
*Valida: R5.3, R5.4, R5.5, R5.6.*

**P4 — Initial-release invariant: exactly one defined template per user.**
After seeding/migration, every user has exactly one `Summary_Template` row (the defined one),
it is that user's default, and it selects both structural elements. Creating additional
templates is allowed (R5.2) but the seeded one remains the only auto-seeded template.
*Valida: R5.1, R5.2.*

**P5 — Summary is a distinct artifact with meeting-bound identity (R1.1, R1.3).**
For any meeting `m`: at most one `meeting_summaries` row exists for `m` (unique constraint);
its `meeting_id` references `m`; the portal's meeting view presents it in a section distinct
from transcript and notes (component boundary, verified by component test rather than
property test).
*Valida: R1.1, R1.3.*

**P6 — Copy/download exactness (R2.1, R2.2).**
The clipboard write payload and the downloaded file's text equal `summary.renderedMarkdown`
exactly; the download filename is `meeting-summary-<meetingId>.md` (verified by component
test with mocked clipboard/object-URL).
*Valida: R2.1, R2.2.*

**P7 — API and storage privacy boundaries.**
Any templates API response for user `u` contains only templates owned by `u`; the summary GET
for user `u` requires `meeting.created_by == u.id`, else 404; `require_sales` denials are
recorded in `access_log`. Boundary check (repository/service level): for any user pair
(u1 ≠ u2), `list_templates(u1)` ∩ `{t : t.owner_user_id == u2.id}` = ∅.
*Valida: cross-surface privacy boundary; `SECURITY.md` access-control rules (JWT + sales-user
restriction + access audit apply to the new endpoints).*

**P8 — Idempotent redelivery under lineage (D4).**
For any meeting whose stored summary has lineage `(T, v)`: a `summarize` delivery resolving
the same `(T, v)` is a no-op (stored content and `generation` unchanged); a delivery
resolving a different lineage (`T' ≠ T` or `v' ≠ v`, e.g. after the user changes the default
or the template's selection is edited) overwrites the row with the new shaped content and
`generation + 1`.
*Valida: R5.6 boundary, D4.*

## Manejo de Errores

| Scenario | Behavior |
|----------|----------|
| `POST /api/v1/templates` with `category_id` not owned by user | 422, no row created |
| Template create/update with neither element selected | 422 (`TemplateSelectionSpec` validator) |
| `PUT /api/v1/templates/default` with another user's template id | 422, no change |
| `GET /api/v1/templates/{id}` for another user's template | 404 (no existence leak) |
| Meeting summary GET for nonexistent or not-owned meeting | 404 (existing meetings convention) |
| Summary GET when no summary exists for the meeting | 404 (same style as the transcript endpoint's "not available" detail); frontend shows the neutral empty state |
| Worker message with missing/empty `meeting_id` | Discarded with warning log (transcription-worker convention) |
| Worker: meeting or transcript row missing at process time | Log + return (queue redelivery governs; no custom retry) |
| Worker: no default configured for the meeting owner | Log "no default configured; skipping" and return — behavior unspecified by requirements; no fallback (D9) |
| Worker: engine raises | Exception propagates uncaught (transcription-worker discipline); queue redelivery governs; no failed row is persisted (D9) |
| Worker: stored lineage equals resolved default lineage | Idempotent no-op ack (D4, P8) |
| Worker: engine returns empty topic and empty key_points with both selected | Stored as-is; renderer guarantees a non-whitespace artifact (P2). Engine-quality thresholds are unapproved scope (D1) |
| `SUMMARIZATION_PROVIDER` unrecognized at worker startup | `ValueError` at startup, mirroring `create_asr_engine()` |
| `GET /api/v1/templates/categories` vs `/{template_id}` route conflict | Static route registered first (implementation-order guard in the router file) |
| Frontend copy blocked (clipboard permission) | Button shows a transient "Copy failed" state; no data loss |
| Frontend `getSummary` 404 | Neutral "No summary available for this meeting yet." (UI state, not fallback behavior) |

## Estrategia de Testing

**Enfoque dual: unit/integration + property-based.** Rationale: the resolver, selection, and
renderer are pure functions — ideal property-test territory; API/worker behavior is
integration-tested like the existing modules.

- **Property-based** (`hypothesis`, verified present in `backend` dev dependencies;
  ≥100 examples per property, per AGENTS.md milestone criteria): P1–P5, P8 where automatable
  (P1, P2, P3, P4 seed shape, P5 DB constraint via integration fixture, P8).
- **Unit/integration**: router behavior (auth, 404/422 semantics), worker message handling
  and idempotent skip, frontend component tests (`vitest` + `@testing-library/react`,
  already in `frontend` devDependencies) for SummarySection states and copy/download
  exactness (P6, P7 frontend half).

**Estructura de archivos (backend):**

```
backend/tests/
├── templates/
│   ├── test_templates_api.py             # unit/integration
│   ├── test_default_resolver_property.py # P3 (property)
│   └── test_selection_spec.py            # validator unit tests
├── summaries/
│   ├── test_renderer_property.py         # P1, P2 (property)
│   ├── test_worker.py                    # integration (skip/no-default/idempotent paths)
│   └── test_summary_api.py               # unit/integration
└── integration/
    └── test_summary_pipeline.py          # transcribe→summarize end-to-end
```

**Estructura de archivos (frontend):**

```
frontend/src/components/
├── SummarySection.tsx
├── SummarySection.test.tsx
├── TemplateSettingsView.tsx
└── TemplateSettingsView.test.tsx
```

**TDD sequencing (binding for the task plan):** every property P1–P8 lands as a failing test
(RED) before its implementation (GREEN), then refactor. The RED commit for a property lives
in the same worktree/branch immediately before the implementation commit that makes it pass.
The task plan must sequence test tasks before their implementation tasks in the dependency
graph (AGENTS.md non-negotiable TDD order).

**Test handoff prerequisites (for Zoya's plan):**

- Pre-production base branch/SHA: `feature/issue-task_23304e68098a4c6b-meeting-summaries-design`
  branched at `f5aa6b3e4d1e2c8a0816743f11de8a7a6ad8c43a` (merge-base with `main`:
  `a753dee72703f3aeaf97c3b163de6b4954ab80e9`).
- Failing-command evidence to produce at RED time: `cd backend && pytest
  tests/summaries/test_renderer_property.py tests/templates/test_default_resolver_property.py
  -q` must fail with collection errors naming the missing modules
  (`app.summaries.renderer`, `app.templates.default_resolver`) — this captured RED output is
  the required transfer evidence for the implementation task.
- Authorized integration route: the `transcribe` → `summarize` enqueue in
  `backend/app/transcription/worker.py` and the worker subscription in
  `backend/app/worker.py`.
- Candidate worktree: this branch's worktree or a successor created by
  `_tools/new-worktree.sh` per AGENTS.md §7.

**Comandos:**

```bash
cd backend && pytest tests/templates tests/summaries -q
cd backend && pytest tests/integration/test_summary_pipeline.py -q
cd frontend && npm run test -- --run src/components/SummarySection.test.tsx
cd frontend && npm run typecheck && npm run test
cd backend && ruff check . && mypy .
```

## Scope Boundaries (explicit non-decisions)

Restated for the auditor: this design does not select a summarization method or accuracy
threshold (D1); does not define template visual layout beyond the fixed renderer layout
(D2, D12); does not define access control beyond the existing sales-user policy (P7); does
not define retention/deletion beyond existing `RETENTION_DAYS` flows and FK cascade behavior,
and defines no template/category deletion endpoints (D9); does not adopt the baseline's
imagined portal layout (D7); does not define behavior for users without a configured default
beyond "generation does not run" (D9); and defines no summary-regeneration endpoint, because
the requirements bind the default to subsequent transcription summaries only — historical
summaries keep their lineage as recorded. Category names are free text owned by the user; no
category taxonomy is invented. The download filename is the one concrete user-visible string
this design fixes (D11, P6).
