"""Wire contracts for user-owned summary templates and optional categories."""

from pydantic import BaseModel, ConfigDict, Field

from app.meetings.schemas import ResourceId

# Instructions are sent to the language model with every summary. 20,000 characters is
# about 5,000 tokens: far above the 1,329-character starter template, and small enough
# to leave the model's context window to the transcript.
MAX_INSTRUCTIONS_CHARS = 20_000


class TemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)
    instructions: str = Field(..., min_length=1, max_length=MAX_INSTRUCTIONS_CHARS)
    category_id: ResourceId | None = None


class TemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=128)
    instructions: str | None = Field(None, min_length=1, max_length=MAX_INSTRUCTIONS_CHARS)
    category_id: ResourceId | None = None


class DefaultTemplateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: ResourceId


class TemplateOut(BaseModel):
    id: str
    name: str
    instructions: str
    owner_user_id: str
    category_id: str | None
    version: int
    is_default: bool
    provenance: str | None = None
    created_at: str
    updated_at: str


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=128)


class CategoryOut(BaseModel):
    id: str
    name: str
    owner_user_id: str
    created_at: str
