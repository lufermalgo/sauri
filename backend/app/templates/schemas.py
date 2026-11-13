"""Wire contracts for user-owned summary templates and optional categories."""

from pydantic import BaseModel, Field


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    instructions: str
    category_id: str | None = None


class TemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    instructions: str | None = None
    category_id: str | None = None


class DefaultTemplateSelection(BaseModel):
    template_id: str


class TemplateOut(BaseModel):
    id: str
    name: str
    instructions: str
    owner_user_id: str
    category_id: str | None
    version: int
    is_default: bool
    created_at: str
    updated_at: str


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


class CategoryOut(BaseModel):
    id: str
    name: str
    owner_user_id: str
    created_at: str
