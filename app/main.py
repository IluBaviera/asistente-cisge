from fastapi import FastAPI
from pydantic import BaseModel
from app.motor import consultar

app = FastAPI()

# Modelo de entrada
class Query(BaseModel):
    mensaje: str

# Endpoint básico (para probar si corre)
@app.get("/")
def root():
    return {"status": "ok"}

# Endpoint principal
@app.post("/consultar")
def consultar_api(query: Query):
    respuesta = consultar(query.mensaje)
    return {"respuesta": respuesta}
