📘 Instrucciones del Proyecto

Automatización de Títulos SAP / Ecommerce / SEO / Agentes

n8n + Python (Streamlit existente) + Batching seguro (11K SKUs)

⸻

1. Contexto y objetivo

Este proyecto automatiza la generación y optimización de títulos de productos para:
	•	SAP / ERP
	•	Labels (PLP / PDP)
	•	SEO (Ecommerce)
	•	Uso por bots o agentes de IA

El sistema DEBE mantener exactamente la misma lógica que ya funciona en:

👉 https://titulogo-jc.streamlit.app/

El objetivo es:
	•	Procesar ~11,000 títulos
	•	De forma automatizada
	•	Por lotes, sin romper el sistema
	•	Con trazabilidad, control de errores y reintentos

⸻

2. Principios no negociables (guardrails)
	1.	❌ NO cambiar la lógica actual
	2.	✅ Reutilizar el motor existente
	3.	🧠 Separar UI (Streamlit) de procesamiento (engine)
	4.	🔁 Procesar por lotes (batching)
	5.	🧾 Mantener historial y estado por SKU
	6.	♻️ Idempotencia (no reprocesar si no cambió el input)
3. Arquitectura general
   SAP / CSV / Sheet / VTEX
        ↓
       n8n
        ↓
   Batch Controller
        ↓
 FastAPI (Title Engine)
        ↓
 Result Store (DB / CSV / Sheet)
        ↓
   Bulk upload / uso por bots
4. Estructura del repositorio (recomendada)
   /app_streamlit.py              # UI existente (NO se rompe)
/title_engine/
  ├─ engine.py                 # lógica principal de títulos
  ├─ validators.py             # reglas, longitudes, bloqueos
  ├─ schemas.py                # input/output
/api_service/
  ├─ main.py                   # FastAPI para n8n
  ├─ requirements.txt
/tests/
📌 Regla clave:
Streamlit debe importar el motor, no duplicarlo.
from title_engine.engine import generate_titles_batch
5. Contrato de datos (input / output)

Input por producto
{
  "sku": "123456",
  "titulo_origen": "TALADRO ELECTRICO 500W",
  "marca": "Bosch",
  "categoria": "Herramientas"
}
Output esperado
{
  "sku": "123456",
  "optimized_title": "Taladro eléctrico Bosch 500W",
  "label_title": "Taladro Bosch 500W",
  "warnings": [],
  "status": "ok"
}
6. API para n8n (FastAPI)

Endpoint

POST /generate-titles

Body
{
  "batch_id": "2025-12-17_01",
  "items": [ ... ],
  "options": {
    "mode": "seo_and_label",
    "dry_run": false
  }
}
Reglas del API
	•	Máx 100–300 SKUs por request
	•	Timeout: ≤120s
	•	Reintentos seguros
	•	Logging por batch_id

⸻

7. Flujo n8n (paso a paso)

1️⃣ Trigger
	•	Manual / Cron / Webhook

2️⃣ Ingesta
	•	CSV / Google Sheet / SAP export / API

3️⃣ Normalización
	•	Limpieza de campos
	•	Mapping a esquema estándar

4️⃣ Control de estado (CRÍTICO)

Tabla title_jobs:
campo
descripción
sku
PK
hash_input
detecta cambios
status
pending / processing / done / error
optimized_title
resultado
label_title
resultado
error_message
si falla
last_run_at
timestamp
5️⃣ Split in Batches
	•	Tamaño inicial: 100
	•	Concurrency: 1–3
	•	Backoff entre lotes

6️⃣ HTTP Request
	•	Llamada al FastAPI
	•	Manejo de errores por lote

7️⃣ Persistencia
	•	Guardar resultados
	•	Exportar CSV final
	•	(opcional) push a VTEX / PIM

8️⃣ Alertas
	•	Slack / Email / Teams si hay fallos
  8. Parámetros recomendados (safe mode)
  BATCH_SIZE=100
CONCURRENCY=2
RETRIES=3
TIMEOUT_SECONDS=120
SLEEP_BETWEEN_BATCHES_MS=500
9. Validaciones obligatorias (títulos)
	•	❌ vacío
	•	❌ palabras prohibidas
	•	⚠️ atributos faltantes → warnings
	•	label_title ≤ límite definido
	•	optimized_title ≤ límite SEO

⸻

10. Cómo se integrará el código existente

Cuando entregues el código:
	1.	Se identifica el motor real
	2.	Se encapsula en:
	•	generate_one(item)
	•	generate_batch(items)
	3.	Streamlit sigue funcionando igual
	4.	FastAPI expone el motor para n8n
	5.	No se modifica ninguna regla de negocio

⸻

11. Checklist final

Python
	•	Lógica separada en engine
	•	Streamlit intacto
	•	FastAPI operativo
	•	Logs por batch

n8n
	•	Batching
	•	Control de estado
	•	Reintentos
	•	Export final

⸻

12. Notas finales

✔️ Este documento es la única fuente de verdad
✔️ Se puede versionar
✔️ Escala a 100K+ SKUs
✔️ Sirve para bots, SEO, SAP y ecommerce

  
