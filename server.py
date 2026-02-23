from fastapi import FastAPI
import os

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok", "author": "Eren"}

@app.get("/health")
def health():
    return {"health": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )