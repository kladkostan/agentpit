# agentpit/fastapi/main.py
import uvicorn
from contextlib import asynccontextmanager
from agentpit.fastapi.agentpit_server import AgentPitServer

@asynccontextmanager
async def lifespan(server: AgentPitServer):
    # --- Startup ---
    print("Agentpit server startup...")
    yield
    # --- Shutdown ---
    print("Agentpit server shutdown...")
    server.shutdown()

server = AgentPitServer(lifespan=lifespan)

@server.get("/")
def get_version():
    return server.get_version()

# This part is for running the app directly
if __name__ == "__main__":
    uvicorn.run("agentpit.fastapi.main:app", host="0.0.0.0", port=8000, reload=True)
