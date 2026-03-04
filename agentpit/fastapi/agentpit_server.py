# agentpit/fastapi/agentpit_server.py
from fastapi import FastAPI

class AgentPitServer(FastAPI):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_api_route("/", self.get_version, methods=["GET"])

    def get_version(self) -> dict[str, str]:
        return {"version": "1.0"}

    def shutdown(self) -> None:
        print("AgentPitServer is shutting down...")
