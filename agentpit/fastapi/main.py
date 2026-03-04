import argparse
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI

# --- 1. Define and parse command-line arguments ---
parser = argparse.ArgumentParser()
parser.add_argument("--model-version", default="default-model-v1", help="Version of the model to load")
args = parser.parse_args()

# This dictionary will hold your long-lived objects
long_lived_objects = {}

# --- 2. Create a factory for the lifespan manager ---
def create_lifespan_manager(model_version: str):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Code to run on startup
        print("Application startup...")
        # Use the argument passed from the command line
        print(f"Loading model version: {model_version}")
        long_lived_objects["model"] = model_version
        yield
        # Code to run on shutdown
        print("Application shutdown...")
        long_lived_objects.clear()
    return lifespan

# --- 3. Create the app and pass the lifespan manager ---
# The factory is called with the parsed argument
lifespan_manager = create_lifespan_manager(args.model_version)
app = FastAPI(lifespan=lifespan_manager)


@app.get("/")
async def root():
    model = long_lived_objects.get("model")
    return {"message": f"Hello World, using {model}"}

# --- 4. Run the app programmatically ---
# This part is needed to handle argument parsing before uvicorn starts
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
