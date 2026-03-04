# agentpit/fastapi/main.py
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from pydantic_settings import BaseSettings

from agentpit.fastapi.agentpit_server import AgentPitServer


class Settings(BaseSettings):
    model_version: str = "default-model-v1"


settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    print("Application startup...")
    print(f"Loading model version: {settings.model_version}")
    app.state.agentpit_server = AgentPitServer()
    yield
    # --- Shutdown ---
    print("Application shutdown...")
    app.state.agentpit_server.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/")
def get_version(request: Request):
    server: AgentPitServer = request.app.state.agentpit_server
    return {"version": server.get_version()}


# This part is for running the app directly
if __name__ == "__main__":
    # pydantic-settings will automatically override defaults with
    # environment variables. For example, run:
    # MODEL_VERSION="custom-model-v2" python agentpit/fastapi/main.py
    uvicorn.run("agentpit.fastapi.main:app", host="0.0.0.0", port=8000, reload=True)
