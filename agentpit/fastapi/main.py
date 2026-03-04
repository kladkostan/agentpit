# agentpit/fastapi/main.py
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from pydantic_settings import BaseSettings

from agentpit.common import check_state
from agentpit.fastapi.agentpit_server import AgentPitServer

# The server will hold long-lived objects
agentpit_server = None


class Settings(BaseSettings):
    model_version: str = "default-model-v1"


# Default settings
settings = Settings()


# --- 2. Create a factory for the lifespan manager ---
def create_lifespan_manager(app: FastAPI, app_settings: Settings):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global agentpit_server
        # --- Startup ---
        print("Application startup...")
        print(f"Loading model version: {app_settings.model_version}")
        agentpit_server = AgentPitServer()
        yield
        # --- Shutdown ---
        print("Application shutdown...")
        agentpit_server.shutdown()
        agentpit_server = None
    return lifespan

# --- 3. Create and configure the FastAPI app ---
app = FastAPI(lifespan=create_lifespan_manager(None, settings))

@app.get("/")
async def read_root():
    return {"version": agentpit_server.get_version()}

# This part is now only for running the app directly
if __name__ == "__main__":
    # pydantic-settings will automatically override defaults with
    # environment variables. For example, run:
    # MODEL_VERSION="custom-model-v2" python agentpit/fastapi/main.py
    uvicorn.run("agentpit.fastapi.main:app", host="0.0.0.0", port=8000, reload=True)
