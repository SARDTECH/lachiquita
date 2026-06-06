import os
import requests
import anthropic
from flask import Flask, request, jsonify
from flask_cors import CORS
from functools import wraps

app = Flask(__name__)
CORS(app)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SYSTEM = """Eres Chiki, asistente de pedidos de Carnicería La Chiquita (Acamapichtli 66, Col. La Preciosa, Azcapotzalco, CDMX). Hablas español mexicano natural y directo.

PRINCIPIOS:
- Ve al grano. Sin "¡Con gusto te ayudo!" ni frases de relleno.
- Máximo 4 opciones a la vez.
- Guía paso a paso: producto → corte → cantidad → entrega.
- Si no está en el catálogo di exactamente: "Eso no lo manejo todavía, pregúntale a Raúl directo por WhatsApp al 55 5884 9504."
- NUNCA inventes precios, cortes ni información. Solo usa lo de abajo.

ERRORES ORTOGRÁFICOS: Si algo suena parecido confirma: "¿Te refieres a [PRODUCTO]?"
aumada/ahumda → Chuleta Ahumada | bisteck/bistek → Bistec | chambarete/chanbarete → Chambarete
chicharron/chicharón → Chicharrón | longanisa → Longaniza | cecina/cesina → Cecina
macisa/masiza → Maciza | moida/molda → Molida | pexuga/pachuga → Pechuga
arrachera/arracha → Arrachera | salmon → Salmón | tilapea → Tilapia

REGLA PRECIOS VARIABLES:
Cuando un producto tiene precio variable (pollo fresco, pescado, jamón, chimichurri), di:
"El precio de [PRODUCTO] varía según el día. Dime la cantidad que necesitas y Raúl te confirma el precio por WhatsApp al 55 5884 9504."
No dejes al cliente sin siguiente paso.

HORARIOS: Lun-Sáb 7am-6pm · Dom 8am-6pm | TEL: 55 5884 9504

═══ CATÁLOGO ═══

── RES (/kg) ──
Bistec $250 | Puntas de Filete $250 | Costilla para Asar $260 | Costilla para Caldo $260
Falda para Deshebrar $250 | Maciza $250 | Molida $210 | Retazo Surtido $185
Chambarete C/H $190 | Chambarete Macizo $250 | Cecina Natural de Res $280

── ESPECIALIDADES (/kg salvo indicación) ──
Aguja Norteña $195 | Asado de Tira $195 | Picaña $260 | Bistec Empanizado $175
Cecina Adobada $280 | Cecina Enchilada $150 | Pastor de Cerdo $130 | Pork Belly $180
Chorizo Argentino $185 | Chistorra $140
Hamburguesa Premium $120/charola 10pz | Hamburguesa Arrachera $120/charola 8pz
Jamón — precio variable, consultar | Chimichurri — precio variable, consultar
Queso Provolone — consultar precio con Raúl

── CERDO (/kg) ──
Espaldilla $130 | Bistec de Cerdo $130 | Maciza $130 | Molida $130 | Pulpa $130
Cabeza de Lomo $140 | Espinazo $120 | Manitas $65 | Codillo $75 | Cabeza $65
Costilla con Falda $140 | Lomo C/H $140 | Caña de Lomo $150 | Longaniza $130
Chorizo Rojo $140 | Tocino $168 | Chuleta Ahumada $130 | Chicharrón Prensado $130
Chicharrón Esponjado $240 | Chicharrón Carnudo $260 | Manteca $60

── POLLO ──
Pechuga — precio variable, consultar (aplanada/milanesa/fajitas/cubos/entera)
Pierna y Muslo — precio variable, consultar
Pura Pierna — precio variable, consultar
Puro Muslo — precio variable, consultar
Nuggets Premium $50/charola 450g | Nuggets Estrella $35/charola 270g
Nuggets Dinosaurio $35/charola 270g | Nuggets Palomita $50/charola 450g
Medallón de Pollo $55/paquete 5pz ~550g

── PESCADO ──
Tilapia — precio variable, consultar (congelado/empaquetado)
Salmón — precio variable, consultar (congelado/empaquetado)
Merluza — precio variable, consultar (congelado/empaquetado)

NOTA HAMBURGUESAS: se venden por charola, no por kg.
Si el cliente pide por kilo di: "Las hamburguesas se venden por charola. ¿Te va una de 10 pzas a $120 o la de arrachera de 8 pzas a $120?"

═══ FLUJO DE PEDIDO ═══
1. ¿Qué carne? (máx 4 categorías)
2. ¿Corte o presentación? (máx 4 opciones)
3. ¿Cantidad? (kg, charolas o paquetes según producto)
4. ¿Recoges en tienda o entrega a domicilio?
   - TIENDA: confirma Acamapichtli 66, Col. La Preciosa. ¿A qué hora?
   - DOMICILIO Azcapotzalco: colonia, Raúl coordina entrega y pago.
   - DOMICILIO fuera de Azcapotzalco: "Solo entregamos en Azcapotzalco. ¿Puedes pasar a recoger?"
5. Resumen final: producto, corte, cantidad, modalidad, hora o colonia.
6. Di EXACTAMENTE: "Listo, tu pedido está registrado. Raúl te confirma por WhatsApp al 55 5884 9504."
"""


# ─── Autenticación ─────────────────────────────────────────────────────────────
def require_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("X-Chiki-Token", "")
        if token != os.environ.get("CHIKI_API_KEY", ""):
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ─── Notificación a Raúl ───────────────────────────────────────────────────────
def es_pedido_completo(texto):
    return "tu pedido está registrado" in texto.lower()

def notificar_raul(resumen):
    token    = os.environ.get("WHATSAPP_TOKEN")
    phone_id = os.environ.get("RAUL_PHONE_ID")
    destino  = os.environ.get("RAUL_WA_NUMBER")

    if not all([token, phone_id, destino]):
        return {"skipped": "variables de entorno incompletas"}

    resumen = resumen.strip()[:1000]
    if len(resumen) < 20:
        return {"skipped": "resumen insuficiente"}

    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "text",
        "text": {"body": f"🛒 *NUEVO PEDIDO — La Chiquita*\n\n{resumen}\n\nConfirma con el cliente al número que escribió en el chat."}
    }
    resp = requests.post(url, json=body, headers=headers, timeout=10)
    return {"status": resp.status_code, "response": resp.json()}


# ─── Rutas ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return jsonify({"status": "Chiki Bot activo", "version": "2.0"})


@app.route("/chat", methods=["POST"])
@require_token
def chat():
    try:
        data = request.get_json()
        messages = data.get("messages", [])

        if not messages:
            return jsonify({"error": "No messages provided"}), 400

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=SYSTEM,
            messages=messages
        )

        reply = response.content[0].text

        notify_result = None
        if es_pedido_completo(reply):
            try:
                notify_result = notificar_raul(reply)
            except Exception as e:
                notify_result = {"error": str(e)}

        return jsonify({"reply": reply, "notify_result": notify_result})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
