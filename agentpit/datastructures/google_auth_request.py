from pydantic import BaseModel


class GoogleAuthRequest(BaseModel):
    """The ID token Google Identity Services hands the browser.

    GIS calls its callback with `{credential: "<jwt>"}`; the field keeps that
    name so the front end forwards what it was given, unrenamed.
    """

    credential: str
