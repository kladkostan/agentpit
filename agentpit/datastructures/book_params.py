from pydantic import BaseModel, Field


class BookParams(BaseModel):
    """One element of the `POST /books` batch request."""

    token_id: str = Field(min_length=1)
