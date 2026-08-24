from datetime import date

from pydantic import BaseModel


class DailyVariablePoint(BaseModel):
    day: date
    value: float
    source_code: str
    is_simulated: bool
    role: str | None = None


class DailySeriesOut(BaseModel):
    parcel_id: int
    start: date
    end: date
    variables: dict[str, list[DailyVariablePoint]]
    notes: list[str] = []
