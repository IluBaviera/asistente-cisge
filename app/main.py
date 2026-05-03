from fastapi import FastAPI
from pydantic import BaseModel
from app.motor import consultar
from app.motor import log_consultas

app = FastAPI()

@app.get("/logs")
def ver_logs():
    return log_consultas[-20:]  # últimas 20 consultas

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
