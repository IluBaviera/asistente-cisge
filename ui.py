import gradio as gr
import requests

API_URL = "http://127.0.0.1:8000/consultar"

def consultar_api(mensaje, historial):

    response = requests.post(
        API_URL,
        json={"mensaje": mensaje}
    )

    respuesta = response.json()["respuesta"]

    historial.append((mensaje, respuesta))

    return "", historial

with gr.Blocks() as demo:

    gr.Markdown("# 📲 Asistente Comercial CISGE")

    chatbot = gr.Chatbot(
        height=500
    )

    msg = gr.Textbox(
        placeholder="Escribe productos...",
        lines=3
    )

    enviar = gr.Button("Enviar")

    enviar.click(
        consultar_api,
        inputs=[msg, chatbot],
        outputs=[msg, chatbot]
    )

demo.launch(
    server_name="0.0.0.0"
)
