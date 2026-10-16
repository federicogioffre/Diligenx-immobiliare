from pydantic import BaseModel, Field


class PropertyFieldSource(BaseModel):
    value: str
    source_document_ids: list[int] = Field(default_factory=list)
    source_filenames: list[str] = Field(default_factory=list)
    source_kinds: list[str] = Field(default_factory=list)


class PropertyHolder(BaseModel):
    name: str
    tax_code: str | None = None
    share: str | None = None
    right: str | None = None


class PropertyUnitRead(BaseModel):
    """One property unit, consolidated across the documents that describe it."""

    label: str
    values: dict[str, str] = Field(default_factory=dict)
    intestatari: list[PropertyHolder] = Field(default_factory=list)
    conflicting_fields: list[str] = Field(default_factory=list)
    field_sources: dict[str, list[PropertyFieldSource]] = Field(default_factory=dict)
    source_document_ids: list[int] = Field(default_factory=list)
    source_filenames: list[str] = Field(default_factory=list)


class PipelineStageRead(BaseModel):
    key: str
    agent_name: str
    label_it: str
    label_en: str
    reports_progress: bool
