import uuid

from pydantic import BaseModel


class RowErrorOut(BaseModel):
    row_number: int
    reason: str


class ImportPreviewOut(BaseModel):
    token: uuid.UUID
    filename: str
    header_row_number: int
    column_mapping: dict[str, str]
    total_data_rows: int
    rows_ok: int
    rows_duplicate: int
    rows_error: list[RowErrorOut]
    sample: list[dict]


class ImportCommitRequest(BaseModel):
    token: uuid.UUID


class ImportCommitOut(BaseModel):
    inserted: int
    batch_token: str
