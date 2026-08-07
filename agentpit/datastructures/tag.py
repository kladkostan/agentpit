from pydantic import BaseModel


class TagFacet(BaseModel):
    """A subcategory: a tag co-occurring with a top-level one."""

    slug: str
    label: str
    count: int


class TagNavEntry(BaseModel):
    """A top-level category and the subcategories beneath it."""

    slug: str
    label: str
    count: int
    facets: list[TagFacet]


class ListTagsResponse(BaseModel):
    tags: list[TagNavEntry]
