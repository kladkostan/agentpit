import uvicorn
from dotenv import load_dotenv

load_dotenv()

from agentpit.api.app import create_app

app = create_app()


if __name__ == "__main__":
    uvicorn.run("agentpit.api.main:app", host="0.0.0.0", port=8000, reload=True)
