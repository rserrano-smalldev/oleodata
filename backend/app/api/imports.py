from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.imports import ImportCommitOut, ImportCommitRequest, ImportPreviewOut, RowErrorOut
from app.services.excel_import import commit_treatments_import, preview_treatments_excel

router = APIRouter(prefix="/v1/imports/treatments", tags=["imports"])


@router.post("/preview", response_model=ImportPreviewOut)
async def preview(file: UploadFile = File(...), session: AsyncSession = Depends(get_session)):
    content = await file.read()
    try:
        result = await preview_treatments_excel(session, content, file.filename or "tratamientos.xlsx")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ImportPreviewOut(
        token=result.token,
        filename=result.filename,
        header_row_number=result.header_row_number,
        column_mapping=result.column_mapping,
        total_data_rows=result.total_data_rows,
        rows_ok=result.rows_ok,
        rows_duplicate=result.rows_duplicate,
        rows_error=[RowErrorOut(row_number=e.row_number, reason=e.reason) for e in result.rows_error],
        sample=result.sample,
    )


@router.post("/commit", response_model=ImportCommitOut)
async def commit(payload: ImportCommitRequest, session: AsyncSession = Depends(get_session)):
    try:
        result = await commit_treatments_import(session, payload.token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ImportCommitOut(**result)
