import streamlit as st
import time
import re
import json
import os
import random
import io
import base64
from PIL import Image
from pypdf import PdfReader
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(
    page_title="NATUSIM - Hiring Room Inteligente",
    page_icon="🦐",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==============================================================================
# 1. PERSISTENCIA EN GOOGLE SHEETS Y RESPALDO LOCAL DE EVIDENCIAS
# ==============================================================================
DATA_FILE = "postulaciones_natusim.json"
EVIDENCIAS_DIR = "evidencias"

if not os.path.exists(EVIDENCIAS_DIR):
    os.makedirs(EVIDENCIAS_DIR, exist_ok=True)

@st.cache_resource
def conectar_sheet():
    """Conecta con la hoja de Google Sheets usando las credenciales de Service Account."""
    if "gcp_service_account" not in st.secrets or "SHEET_ID" not in st.secrets:
        return None
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(st.secrets["SHEET_ID"])
        try:
            return spreadsheet.worksheet("Resultados_CV")
        except Exception:
            # Si no existe la pestaña, crearla con encabezados
            ws = spreadsheet.add_worksheet(title="Resultados_CV", rows=1000, cols=12)
            ws.append_row([
                "Fecha", "Nombre", "Email", "Puesto", "Score CV",
                "Score Entrevista", "Score Tecnico", "Score Final",
                "Dictamen", "Biometria Audit", "Evidencia Foto", "Reporte"
            ])
            return ws
    except Exception as e:
        return None

def guardar_postulacion(registro, img_bytes=None):
    """Guarda la postulación en Google Sheets y en almacenamiento local de respaldo."""
    foto_filename = ""
    foto_base64 = ""
    if img_bytes:
        timestamp_clean = time.strftime('%Y%m%d_%H%M%S')
        email_clean = re.sub(r'[^a-zA-Z0-9]', '_', registro.get("email", "candidato"))
        foto_filename = f"{EVIDENCIAS_DIR}/foto_{timestamp_clean}_{email_clean}.jpg"
        with open(foto_filename, "wb") as f:
            f.write(img_bytes)
        foto_base64 = base64.b64encode(img_bytes).decode('utf-8')

    registro["foto_archivo"] = foto_filename
    registro["foto_base64"] = foto_base64

    # 1. Guardar en Google Sheets
    sheet = conectar_sheet()
    if sheet:
        try:
            sheet.append_row([
                registro.get("fecha", ""),
                registro.get("nombre", ""),
                registro.get("email", ""),
                registro.get("puesto", ""),
                registro.get("cv_score", 0.0),
                registro.get("interview_score", 0.0),
                registro.get("tech_score", 0.0),
                registro.get("score_final", 0.0),
                registro.get("dictamen", ""),
                registro.get("biometria_audit", ""),
                foto_filename,
                registro.get("reporte", "")
            ])
        except Exception:
            pass

    # 2. Respaldo local JSON
    local_data = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                local_data = json.load(f)
        except Exception:
            local_data = []
    local_data.append(registro)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(local_data, f, ensure_ascii=False, indent=2)

def cargar_postulaciones():
    """Recupera postulaciones desde Google Sheets o archivo local de respaldo."""
    sheet = conectar_sheet()
    if sheet:
        try:
            return sheet.get_all_records()
        except Exception:
            pass
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

# ==============================================================================
# 2. CONFIGURACIÓN DE IA (GEMINI 1.5 FLASH)
# ==============================================================================
api_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
if api_key:
    genai.configure(api_key=api_key)
MODELO = "gemini-1.5-flash"

# ==============================================================================
# 3. CONTROL DE SESIÓN Y VISTAS
# ==============================================================================
query_params = st.query_params
vista_admin = query_params.get("view") in ["rrhh", "resultados", "admin"]

# Inicializar variables de estado
defaults = {
    "step": 1,
    "candidate_name": "",
    "candidate_email": "",
    "puesto": "",
    "cv_score": 0.0,
    "interview_score": 7.0,
    "tech_score": 0.0,
    "interview_summary": "",
    "biometric_audit": "",
    "candidate_photo_bytes": None,
    "extracted_entities": {},
    "chat_history": [],
    "chat_turn": 0,
    "shuffled_banco": None,
    "quiz_start_time": None
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

st.title("🦐 NATUSIM - Hiring Room Inteligente de Preselección Camaronera")
st.caption("Sistema Autónomo de Selección Técnica y Validación de Identidad | Régimen de Campamento 15/6")

# ==============================================================================
# 4. PORTAL EXCLUSIVO DE RRHH (?view=rrhh)
# ==============================================================================
if vista_admin:
    st.subheader("🔒 Portal de Auditoría y Resultados de Selección (Uso Exclusivo RRHH)")
    st.caption("Consola unificada con evidencia fotográfica, verificación de identidad y desgloses de calificación.")

    rrhh_pw = st.secrets.get("RRHH_PASSWORD", "natusim2026")
    pwd = st.text_input("Ingrese la clave autorizada de Selección de Personal:", type="password", key="pwd_admin")

    if pwd == rrhh_pw:
        st.success("🔓 Sesión Administrativa de Selección Autorizada.")
        postulaciones = cargar_postulaciones()
        st.metric("Total de Postulaciones Evaluadas", len(postulaciones))

        if len(postulaciones) == 0:
            st.info("Aún no se registran evaluaciones completadas en la base de datos.")
        else:
            for idx, p in enumerate(reversed(postulaciones)):
                score_final = float(p.get("score_final", 0.0))
                dictamen = p.get("dictamen", "")
                color = "🟢" if score_final >= 7.5 else ("🟡" if score_final >= 5.5 else "🔴")

                with st.expander(f"{color} {p.get('nombre')} | {p.get('puesto')} | Score Final: {score_final:.1f}/10 ({p.get('fecha')})"):
                    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                    col_m1.metric("Score CV (30%)", f"{float(p.get('cv_score', 0)):.1f} / 10")
                    col_m2.metric("Entrevista IA (30%)", f"{float(p.get('interview_score', 0)):.1f} / 10")
                    col_m3.metric("Examen Técnico (40%)", f"{float(p.get('tech_score', 0)):.1f} / 10")
                    col_m4.metric("SCORE PONDERADO", f"{score_final:.1f} / 10")

                    st.markdown(f"**Correo Electrónico:** `{p.get('email')}`")
                    st.markdown(f"**Recomendación del Sistema:** **{dictamen}**")
                    st.markdown(f"**Auditoría Biométrica:** {p.get('biometria_audit', 'Verificada sin novedades')}")

                    # Mostrar Evidencia Fotográfica tomada junto a la Cédula
                    st.markdown("#### 📷 Evidencia Fotográfica y Documento de Identidad")
                    foto_b64 = p.get("foto_base64", "")
                    foto_path = p.get("foto_archivo", "")

                    if foto_b64:
                        try:
                            img_data = base64.b64decode(foto_b64)
                            st.image(img_data, caption=f"Fotografía del aspirante {p.get('nombre')} tomada durante la prueba", width=380)
                        except Exception:
                            st.caption("No se pudo previsualizar la foto en Base64.")
                    elif foto_path and os.path.exists(foto_path):
                        st.image(foto_path, caption=f"Fotografía local del aspirante {p.get('nombre')}", width=380)
                    else:
                        st.caption("Fotografía registrada en expediente digital.")

                    st.markdown("#### 📄 Informe Ejecutivo y Transcripción")
                    st.text_area(f"Expediente #{len(postulaciones)-idx}:", p.get("reporte", "Sin detalle disponible"), height=220)

        st.markdown("---")
        st.info("💡 **Navegación:** Para regresar al portal del postulante, retire `?view=rrhh` de la barra de direcciones.")
    elif pwd:
        st.error("❌ Clave incorrecta. Acceso restringido a personal autorizado.")
    st.stop()

# ==============================================================================
# 5. BANCOS DE PREGUNTAS CAMARONERAS DE CAMPO
# ==============================================================================
RAW_OPERARIOS = [
    ("Durante un turno nocturno a las 03:00 AM, el medidor marca bajo oxígeno (1.8 mg/L) y observa camarones en superficie. ¿Qué hace primero?",
     "Activar aireación de respaldo, suspender alimentación y avisar al supervisor.",
     ["Continúa alimentando normalmente.", "Apaga las bombas de la estación principal.", "Espera al turno de la mañana."]),
    ("Tras varios turnos continuos siente somnolencia severa cerca del agua. ¿Qué acción es la más segura?",
     "Informar al supervisor y solicitar una pausa o relevo seguro.",
     ["Ocultarlo para evitar llamados de atención.", "Tomar energizantes y continuar operando.", "Trabajar más rápido para terminar."]),
    ("Debe mover un saco de balanceado de 25 kg. ¿Cuál es la técnica ergonómica correcta?",
     "Carga cerca del cuerpo, piernas flexionadas y pedir ayuda si se requiere.",
     ["Espalda encorvada y jalar con los brazos.", "Girar el tronco rápidamente mientras levanta.", "Usar un solo brazo."]),
    ("Un compañero de cuadrilla propone no usar botas de caucho ni chaleco en el canal. ¿Qué hace?",
     "Mantener su EPP completo y reportar la presión para incumplir la norma.",
     ["Quitarse el EPP para trabajar en equipo.", "No decir nada e imitarlo.", "Salir del área sin avisar."]),
    ("Un compañero cae accidentalmente a un canal de drenaje profundo. ¿Qué hace primero?",
     "Pedir ayuda, activar protocolo de emergencia y usar equipo de rescate flotante.",
     ["Lanzarse inmediatamente al agua sin equipo.", "Retirarse a buscar herramientas.", "Jalarlo del brazo sin apoyo."]),
    ("Se derrama una cantidad considerable de alimento balanceado en el muelle. ¿Qué conducta es correcta?",
     "Limpiarlo e informar la pérdida o riesgo de contaminación.",
     ["Dejarlo en el sitio.", "Mezclarlo con tierra.", "Arrojarlo directo a la piscina."]),
    ("En la piscina 14 observa una mortalidad inusual de camarones en las orillas. ¿Qué hace?",
     "Registrar piscina/hora e informar de inmediato al biólogo o supervisor.",
     ["Ocultar los camarones muertos.", "Aplicar un insumo por cuenta propia.", "Cambiar la dosis de alimento."]),
    ("Falla un aireador diésel de madrugada. ¿Qué hace?",
     "Informar, aplicar equipo de respaldo y no intervenir mecánicamente sin autorización.",
     ["Golpear el motor.", "Desconectar otros equipos.", "Ignorar la falla."]),
    ("Dos compañeros discuten fuertemente durante la faena de pesca. ¿Qué hace?",
     "Mantener la calma, evitar un accidente y solicitar apoyo del supervisor.",
     ["Tomar partido por uno de ellos.", "Gritarles para que se callen.", "Abandonar la piscina."]),
    ("Le solicitan manipular un producto químico sin etiqueta ni ficha. ¿Qué hace?",
     "Solicitar instrucción, identificación del producto y EPP adecuado.",
     ["Aceptar y aplicarlo rápido.", "Imitar a otro trabajador.", "Mezclarlo con agua."]),
    ("Se presentan rayos, lluvia intensa y nula visibilidad en el campamento. ¿Qué hace?",
     "Informar y resguardarse según el protocolo de riesgos climáticos.",
     ["Continuar el recorrido habitual.", "Quitarse las botas.", "Acercarse a estructuras metálicas."]),
    ("¿Por qué es fundamental registrar con precisión la tabla de alimentación diaria?",
     "Para asegurar trazabilidad de cantidad, hora y piscina tratada.",
     ["Por llenar papeles exigidos.", "Para aparentar trabajo al supervisor.", "Solo si ocurren problemas."]),
    ("Dos supervisores le dan instrucciones contradictorias al mismo tiempo. ¿Qué hace?",
     "Confirmar educadamente cuál instrucción es la válida a ejecutar.",
     ["Elegir la instrucción más rápida.", "Ejecutar ambas a la vez.", "No hacer ninguna."]),
    ("Nota que una atarraya o herramienta tiene una rotura crítica. ¿Qué hace?",
     "Retirarla, informar y solicitar reparación o reemplazo.",
     ["Seguir usándola hasta que se rompa.", "Ocultarla en bodega.", "Entregársela a un compañero."]),
    ("Un compañero sugiere aumentar el alimento asignado sin autorización. ¿Qué hace?",
     "Seguir la tabla oficial y reportar el intento de ajuste al responsable.",
     ["Aceptar la sugerencia.", "Aumentar la dosis a escondidas.", "Alimentar sin control."]),
    ("Una tarea física repetitiva en tabla de picado le genera dolor lumbar. ¿Qué hace?",
     "Informar a seguridad ocupacional y solicitar pausas activas o rotación.",
     ["Ignorar el dolor.", "Acelerar el trabajo.", "Cambiar de puesto sin avisar."]),
    ("El puesto exige vivir en campamento bajo la jornada rotativa de 15/6. ¿Qué respuesta es la correcta?",
     "Confirmar honestamente su disponibilidad y compromisos familiares.",
     ["Aceptar aunque sepa que no podrá cumplirlo.", "Ocultar restricciones personales.", "Resolverlo cuando ya esté contratado."]),
    ("Comete un error involuntario al anotar los kg de balanceado. ¿Qué hace?",
     "Comunicar el error al supervisor y corregir según el protocolo de bitácora.",
     ["Borrar o tachar para que no se note.", "Culpar al turno anterior.", "Dejar la cifra errónea."]),
    ("El supervisor le corrige la técnica de lance de atarraya. ¿Qué hace?",
     "Escuchar con respeto, aplicar la técnica y solicitar demostración si hay duda.",
     ["Discutir y molestarse.", "Ignorar la sugerencia.", "Abandonar el trabajo."]),
    ("¿Qué condición favorece principalmente su permanencia a largo plazo en la empresa?",
     "Seguridad laboral, capacitación constante, claridad en turnos y desarrollo real.",
     ["Trabajar sin supervisión alguna.", "Que nunca cambien los horarios.", "No reportar novedades."])
]

RAW_BIOLOGOS = [
    ("A las 03:00 AM varias piscinas presentan una caída vertiginosa de oxígeno. ¿Qué prioriza?",
     "Activar aireación de emergencia, priorizar piscinas con mayor biomasa y comunicar a gerencia.",
     ["Esperar a la luz del día.", "Aplicar metabisulfito inmediatamente.", "Aumentar la tasa de alimentación."]),
    ("El equipo de campo reporta un parámetro de salinidad que no concuerda con el comportamiento del camarón. ¿Qué hace?",
     "Verificar la calibración del equipo, repetir la toma y contrastar con laboratorio.",
     ["Ignorar el reporte.", "Alterar la bitácora técnica.", "Tomar decisiones a simple vista."]),
    ("Se detecta mortalidad súbita con signos de hepatopáncreas pálido. ¿Cuál es el protocolo inicial?",
     "Restringir recambios de agua, tomar muestras para PCR/histopatología y revisar bioseguridad.",
     ["Aplicar antibióticos preventivos de inmediato.", "Mezclar aguas con piscinas vecinas.", "Ocultar el evento a gerencia."]),
    ("Para ajustar la tabla de alimentación diaria de una piscina, considera principalmente:",
     "Biomasa estimada, consumo en platos, temperatura, oxígeno disuelto y mortalidad.",
     ["Solamente el peso promedio semanal.", "La exigencia del operario alimentador.", "La tabla de la camaronera vecina."]),
    ("Antes de autorizar la aplicación de un insumo químico o biológico en agua debe:",
     "Revisar ficha técnica, objetivo, compatibilidad, parámetros de agua, EPP y registro.",
     ["Usar la dosis habitual histórica.", "Mezclar varios productos a la vez.", "Aplicar sin registro."]),
    ("Ocurre un derrame no controlado de producto químico en bodega. ¿Qué hace?",
     "Aislar la zona, consultar la hoja de seguridad (MSDS), usar EPP y activar contingencia.",
     ["Lavar con abundante agua hacia el drenaje de la piscina.", "Recogerlo con las manos sin protección.", "Esperar a que se evapore."]),
    ("Una falla eléctrica crítica deja sin energía los tableros de aireación de la zona A. ¿Qué estrategia aplica?",
     "Activar contingencia de generadores, priorizar piscinas críticas y monitorear oxígeno cada 30 min.",
     ["Suspender todas las actividades.", "Alimentar antes de que baje el oxígeno.", "Desconectar todo el sistema."]),
    ("Ante un evento de bloom algal masivo seguido de mortalidad celular, ¿cuál es el mayor riesgo?",
     "Anoxia nocturna severa y pico de toxicidad por amonio/nitritos.",
     ["Incremento de salinidad.", "Pérdida de turbidez.", "Exceso de alimento."]),
    ("Los registros de balanceado alimentado no coinciden con el inventario físico de bodega. ¿Qué hace?",
     "Auditar bitácoras de campo, conteo de sacos, despachos y entrevistar a los responsables.",
     ["Ajustar los números para cuadrar el saldo.", "Culpar al personal de transporte.", "Ignorar el desfase."]),
    ("La cuadrilla de campo se opone a implementar un nuevo protocolo de bioseguridad. ¿Qué hace?",
     "Escuchar las dificultades operativas, explicar la razón técnica y acompañar la implementación.",
     ["Sancionar masivamente.", "Cancelar el protocolo.", "Ejecutarlo solo."]),
    ("Durante una crisis operativa, el personal cuestiona sus órdenes técnicas. ¿Qué hace?",
     "Emitir instrucciones directas y breves, asignar roles y debatir tras estabilizar la piscina.",
     ["Entrar en discusión abierta.", "Permitir que cada quien actúe a su criterio.", "Esperar consenso absoluto."]),
    ("Un operario reporta voluntariamente un error en la dosificación de un insumo. ¿Qué hace?",
     "Mitigar el impacto técnico en la piscina, investigar la causa y promover la cultura de reporte.",
     ["Sancionarlo severamente de inmediato.", "Ocultar la novedad al jefe de producción.", "Quitarle sus funciones."]),
    ("Gerencia exige aumentar la densidad de siembra sin contar con aireación suficiente. ¿Qué hace?",
     "Presentar informe técnico proyectado con riesgos sanitarios, caída de rendimiento y alternativas viables.",
     ["Aceptar sin objeción.", "Rechazar sin fundamentación técnica.", "Alterar los datos de crecimiento."]),
    ("Considera errónea la recomendación de recambio aplicada por otro técnico. ¿Qué hace?",
     "Revisar los datos biológicos juntos en privado y definir un criterio unificado.",
     ["Desautorizarlo en público.", "Ignorar la situación.", "Dar órdenes contrapuestas al personal."]),
    ("Se registra una baja sistemática de rendimiento en el turno de madrugada. ¿Qué evalúa?",
     "Esquemas de descanso, pausas activas, iluminación en muros y carga de trabajo nocturna.",
     ["Presión salarial.", "Culpar a la calidad del camarón.", "Eliminar las rondas nocturnas."]),
    ("Un candidato calificado tiene una expectativa salarial fuera del rango de la vacante. ¿Cómo procede?",
     "Registrar la expectativa y remitir a RRHH para una negociación transparente basada en valor.",
     ["Descartarlo del proceso.", "Prometer aumentos informales.", "Ocultar el rango salarial."]),
    ("Un postulante demuestra alto conocimiento técnico pero rechaza acatar protocolos de EPP. ¿Qué hace?",
     "Reportar la incompatibilidad de seguridad y derivar a revisión humana obligatoria.",
     ["Recomendar contratación solo por su conocimiento.", "Ignorar la actitud en el informe.", "Descartarlo sin documentar el motivo."]),
    ("¿Qué factor es determinante para evitar la fuga de talento técnico en camaroneras?",
     "Transparencia, ruta de crecimiento profesional, condiciones dignas en campamento bajo jornada 15/6 y reconocimiento.",
     ["Salarios fijos sin incentivos.", "Evitar capacitaciones.", "Aumentar horas de turno."]),
    ("Un proveedor ofrece comisiones personales a cambio de aprobar un insumo de baja calidad. ¿Qué hace?",
     "Rechazar firmemente, reportar el intento de soborno a auditoría y evaluar el producto de forma objetiva.",
     ["Aceptar la propuesta.", "Ocultarlo a la empresa.", "Pedir una muestra gratis."]),
    ("La hoja de vida es sólida, pero la entrevista muestra dificultad para trabajar bajo presión. ¿Qué recomienda el sistema?",
     "Reflejar la contradicción en el informe y sugerir una entrevista presencial adicional con RRHH.",
     ["Contratar de inmediato por la hoja de vida.", "Ignorar la observación de la entrevista.", "Calificar automáticamente con 10/10."])
]

def preparar_banco_aleatorio(raw_list):
    """Genera opciones barajadas aleatoriamente para evitar patrones predecibles."""
    letters = ["A", "B", "C", "D"]
    banco = []
    for idx, (pregunta, correcta, incorrectas) in enumerate(raw_list):
        todas = [correcta] + list(incorrectas)
        random.shuffle(todas)
        corr_idx = todas.index(correcta)
        corr_letter = letters[corr_idx]
        opciones_rotuladas = [f"{letters[i]}) {todas[i]}" for i in range(4)]
        banco.append({
            "idx": idx,
            "q": pregunta,
            "opts": opciones_rotuladas,
            "ans": corr_letter
        })
    return banco

# ==============================================================================
# PASO 1: REGISTRO, AUDITORÍA BIOMÉTRICA CON CÉDULA Y CARGA DE CV
# ==============================================================================
if st.session_state.step == 1:
    st.subheader("Paso 1: Identificación del Aspirante, Fotografía con Cédula y CV")

    st.info(
        "📋 **INSTRUCCIONES OBLIGATORIAS PARA EL POSTULANTE:**\n"
        "1. Complete sus nombres completos y correo electrónico activo.\n"
        "2. **VERIFICACIÓN BIOMÉTRICA DE SEGURIDAD:** Debe tomarse una foto clara frente a la cámara web **sosteniendo su cédula de identidad física o documento oficial junto a su rostro**. La Inteligencia Artificial auditará la nitidez y presencia de ambos elementos.\n"
        "3. Adjunte su Hoja de Vida en formato PDF o TXT (o pegue el texto en el recuadro).\n"
        "4. Presione **'🚀 Validar Identidad y Analizar Hoja de Vida'** para iniciar."
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        puesto = st.selectbox("1. Seleccione la vacante a la que postula:", ["Operario Acuícola de Campo", "Biólogo / Técnico de Producción"])
        nombre = st.text_input("2. Nombres y Apellidos completos:", placeholder="Ej. Carlos Alberto Mendoza Ramos")
        email = st.text_input("3. Correo electrónico válido de contacto:", placeholder="carlos.mendoza@correo.com")

        # Alerta de postulaciones previas
        postulaciones_existentes = cargar_postulaciones()
        if email.strip():
            previas = sum(1 for p in postulaciones_existentes if str(p.get("email", "")).strip().lower() == email.strip().lower())
            if previas > 0:
                st.warning(f"ℹ️ Este correo ya registra {previas} evaluación(es) previas registradas en el sistema.")

        st.markdown("#### 📸 Evidencia de Identidad (Rostro + Cédula)")
        st.caption("Asegúrese de contar con buena iluminación y sostener su cédula visible a la altura del pecho o rostro.")
        img_camera = st.camera_input("Capturar fotografía oficial:")

        uploaded_cv = st.file_uploader("4. Adjunte su Hoja de Vida (PDF o TXT):", type=["pdf", "txt"])
        cv_text_fallback = st.text_area("5. O pegue el texto de su CV aquí si no dispone del archivo:", height=140)

    with col2:
        st.markdown("### 🎯 Parámetros de Selección Camaronera")
        st.markdown(
            "El departamento de Selección de Personal evalúa su postulación bajo los siguientes criterios:\n"
            "- **Operario Acuícola de Campo:** Experiencia práctica en piscinas, alimentación, muestreos y faena de pesca. (No se discrimina por nivel de instrucción).\n"
            "- **Biólogo / Técnico de Producción:** Formación en Acuicultura o Biología, manejo de calidad de agua, fitoplancton y patología.\n"
            "- **Régimen de Campamento:** Capacidad real de residir en finca bajo la jornada rotativa de **15 días de trabajo por 6 días libres (15/6)**."
        )

        if st.button("🚀 Validar Identidad y Analizar Hoja de Vida", type="primary"):
            regex_email = r"^[\w\.-]+@[\w\.-]+\.\w+$"
            if not nombre.strip() or not email.strip():
                st.error("⚠️ Ingrese su nombre completo y correo electrónico antes de continuar.")
                st.stop()
            if not re.match(regex_email, email.strip()):
                st.error("❌ Correo electrónico no válido. Ingrese una dirección con formato correcto (ej: usuario@dominio.com).")
                st.stop()
            if not img_camera:
                st.error("❌ **Requisito Obligatorio de Seguridad:** Debe capturar una fotografía sosteniendo su documento de identidad físico para validar su postulación.")
                st.stop()

            # Extracción del texto del CV
            extracted_text = ""
            if uploaded_cv is not None:
                if uploaded_cv.name.endswith(".pdf"):
                    try:
                        reader = PdfReader(uploaded_cv)
                        for page in reader.pages:
                            extracted_text += page.extract_text() or ""
                    except Exception:
                        extracted_text = ""
                else:
                    extracted_text = uploaded_cv.read().decode("utf-8", errors="ignore")
            else:
                extracted_text = cv_text_fallback

            if len(extracted_text.strip()) < 25:
                st.error("❌ Por favor adjunte un archivo PDF o pegue el contenido de su Hoja de Vida para ser evaluado.")
                st.stop()

            # Guardar datos en sesión
            st.session_state.candidate_name = nombre.strip()
            st.session_state.candidate_email = email.strip()
            st.session_state.puesto = puesto
            img_bytes = img_camera.getvalue()
            st.session_state.candidate_photo_bytes = img_bytes

            # ------------------------------------------------------------------
            # AUDITORÍA BIOMÉTRICA CON GEMINI 1.5 FLASH (VISIÓN ARTIFICIAL)
            # ------------------------------------------------------------------
            with st.spinner("🔍 La Inteligencia Artificial analiza la fotografía para validar identidad y documento oficial..."):
                biometria_aprobada = True
                detalle_biometria = "Validación fotográfica aceptada."

                if api_key:
                    try:
                        pil_img = Image.open(io.BytesIO(img_bytes))
                        model_vision = genai.GenerativeModel(MODELO)
                        prompt_biometria = f"""
                        Eres el auditor biométrico oficial de una empresa camaronera.
                        Analiza la siguiente imagen capturada por un aspirante al puesto de {puesto} llamado '{nombre}'.

                        REQUISITOS DE AUDITORÍA:
                        1. ¿Existe un rostro humano visible, claro y en primer plano?
                        2. ¿La persona sostiene o muestra un documento de identidad oficial (cédula, pasaporte, credencial)?

                        Responde ÚNICAMENTE un objeto JSON válido con esta estructura:
                        {{
                            "aprobado": true,
                            "motivo": "Explicación breve del resultado",
                            "rostro_visible": true,
                            "documento_visible": true
                        }}
                        """
                        res_vision = model_vision.generate_content([prompt_biometria, pil_img]).text
                        # Limpiar posible bloque de código markdown ```json
                        clean_json = re.search(r"\{.*\}", res_vision, re.DOTALL)
                        if clean_json:
                            data_bio = json.loads(clean_json.group(0))
                            biometria_aprobada = data_bio.get("aprobado", True)
                            detalle_biometria = data_bio.get("motivo", "Verificación biométrica procesada con éxito.")
                        else:
                            detalle_biometria = "Registro biométrico capturado para archivo de RRHH."
                    except Exception as e:
                        detalle_biometria = f"Registro biométrico almacenado para verificación humana ({e})."
                        biometria_aprobada = True
                else:
                    detalle_biometria = "Registro de imagen archivado para revisión de RRHH."

                if not biometria_aprobada:
                    st.error(f"❌ **Validación de Identidad no superada:** {detalle_biometria}")
                    st.info("💡 Por favor, tómese una nueva fotografía asegurándose de que su rostro esté iluminado y su cédula física sea claramente visible frente a la cámara.")
                    st.stop()

                st.session_state.biometric_audit = detalle_biometria

            # ------------------------------------------------------------------
            # ANÁLISIS DEL CV CON GEMINI
            # ------------------------------------------------------------------
            with st.spinner("📄 Analizando perfil curricular con la matriz técnica de producción..."):
                if api_key:
                    try:
                        model_cv = genai.GenerativeModel(MODELO)
                        prompt_cv = f"""
                        Actúa como el Jefe Técnico de Reclutamiento para una camaronera en Ecuador.
                        Evalúa esta Hoja de Vida para la vacante: {puesto}.
                        Candidato: {nombre}.

                        CONTENIDO DEL CV:
                        {extracted_text}

                        CRITERIOS:
                        - Si es 'Operario Acuícola de Campo': Califica de 1.0 a 10.0 en base a experiencia de campo previa en fincas (no discriminar por educación).
                        - Si es 'Biólogo / Técnico de Producción': Exige estudios universitarios en biología o acuicultura y manejo de piscinas.
                        - Formula una pregunta de validación técnica altamente personalizada sobre la experiencia mencionada.

                        Responde ÚNICAMENTE en formato JSON:
                        {{
                            "es_cv_valido": true,
                            "cv_score": 8.0,
                            "empresa_detectada": "nombre empresa o No especificada",
                            "cargo_detectado": "cargo previo",
                            "pregunta_1": "Pregunta técnica personalizada sobre su experiencia"
                        }}
                        """
                        res_cv = model_cv.generate_content(prompt_cv).text
                        clean_cv = re.search(r"\{.*\}", res_cv, re.DOTALL)
                        if clean_cv:
                            data_cv = json.loads(clean_cv.group(0))
                            st.session_state.cv_score = float(data_cv.get("cv_score", 7.5))
                            st.session_state.extracted_entities = {
                                "empresa": data_cv.get("empresa_detectada", "Experiencia previa"),
                                "cargo": data_cv.get("cargo_detectado", "Técnico")
                            }
                            q1 = data_cv.get("pregunta_1", f"En base a su experiencia en {st.session_state.extracted_entities['empresa']}, describa sus labores diarias en piscinas.")
                        else:
                            st.session_state.cv_score = 7.5
                            q1 = "Describa detalladamente las actividades operativas más complejas que realizó en su última labor camaronera."
                    except Exception:
                        st.session_state.cv_score = 7.5
                        q1 = "Describa detalladamente las actividades operativas más complejas que realizó en su última labor camaronera."
                else:
                    st.session_state.cv_score = 7.5
                    q1 = "Describa las actividades operativas y de campo que desempeñaba en su último trabajo en fincas."

                st.session_state.chat_history = [
                    {"role": "agent", "content": f"Hola {nombre}. Bienvenido al proceso de selección técnica de NATUSIM. {q1}"}
                ]
                st.session_state.chat_turn = 1
                st.session_state.step = 2
                st.rerun()

# ==============================================================================
# PASO 2: ENTREVISTA TÉCNICA DINÁMICA DE 5 PREGUNTAS
# ==============================================================================
elif st.session_state.step == 2:
    st.subheader("Paso 2: Entrevista Virtual Técnica (5 Preguntas Adaptativas)")
    st.info(
        "💬 **INSTRUCCIONES:**\n"
        "1. El entrevistador virtual le formulará 5 preguntas técnicas basadas en sus respuestas y experiencia.\n"
        "2. Escriba su respuesta con honestidad y el mayor detalle técnico posible.\n"
        "3. Al responder la quinta pregunta, el sistema habilitará el botón para ingresar al examen de casos reales."
    )
    st.caption("Esta conversación queda registrada y auditada por la IA para el expediente de Talento Humano.")
    st.success(f"📌 **Progreso:** Pregunta {st.session_state.chat_turn} de 5")

    for msg in st.session_state.chat_history:
        avatar = "🤖" if msg["role"] == "agent" else "👤"
        st.chat_message("assistant" if msg["role"] == "agent" else "user", avatar=avatar).write(msg["content"])

    if st.session_state.chat_turn <= 5:
        user_input = st.chat_input("Escriba su respuesta técnica aquí...")
        if user_input:
            st.session_state.chat_history.append({"role": "user", "content": user_input})
            t = st.session_state.chat_turn

            with st.spinner("El Evaluador analiza su respuesta y formula la siguiente interrogante..."):
                if api_key and t < 5:
                    try:
                        model = genai.GenerativeModel(MODELO)
                        dialogo = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.chat_history])
                        prompt_chat = f"""
                        Eres el entrevistador técnico de una empresa camaronera en Ecuador.
                        Puesto postulado: {st.session_state.puesto}.
                        Historial:
                        {dialogo}

                        Formula la pregunta NÚMERO {t+1} de 5.
                        Indaga sobre su criterio práctico ante imprevistos en piscinas, seguridad de campamento o manejo de turnos 15/6.
                        Haz una pregunta concisa, técnica y directa.
                        """
                        next_q = model.generate_content(prompt_chat).text.strip()
                    except Exception:
                        variadas = [
                            "¿Cómo procede si en plena madrugada una bomba de transferencia o aireador presenta falla eléctrica?",
                            "Describa una situación real donde tuvo que corregir un parámetro crítico de agua en menos de una hora.",
                            "¿Cómo maneja su adaptación física y familiar al régimen de campamento 15/6?",
                            "¿Qué protocolo sigue cuando detecta un producto biológico o balanceado con fecha próxima a expirar?"
                        ]
                        next_q = variadas[t % len(variadas)]
                elif t >= 5:
                    # EVALUACIÓN DE LAS RESPUESTAS POR GEMINI AL FINALIZAR
                    if api_key:
                        try:
                            model = genai.GenerativeModel(MODELO)
                            dialogo_completo = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.chat_history])
                            prompt_eval = f"""
                            Actúa como un evaluador técnico camaronero senior.
                            Evalúa el desempeño de este candidato para el puesto de {st.session_state.puesto} basándote en sus respuestas en la entrevista:

                            {dialogo_completo}

                            Devuelve ÚNICAMENTE un JSON:
                            {{
                                "interview_score": 8.0,
                                "resumen_tecnico": "Breve resumen de competencias demostradas y actitud hacia el trabajo de campamento 15/6"
                            }}
                            """
                            res_ev = model.generate_content(prompt_eval).text
                            clean_ev = re.search(r"\{.*\}", res_ev, re.DOTALL)
                            if clean_ev:
                                d_ev = json.loads(clean_ev.group(0))
                                st.session_state.interview_score = float(d_ev.get("interview_score", 7.5))
                                st.session_state.interview_summary = d_ev.get("resumen_tecnico", "Entrevista completada.")
                        except Exception:
                            st.session_state.interview_score = 7.5
                            st.session_state.interview_summary = "Entrevista completada y archivada."
                    next_q = "✅ ¡Entrevista completada satisfactoriamente! Presione el botón inferior para ingresar al examen situacional."

                st.session_state.chat_history.append({"role": "agent", "content": next_q})
                st.session_state.chat_turn += 1
                st.rerun()

    if st.session_state.chat_turn > 5:
        st.success("✅ **Ha culminado la fase de entrevista técnica.**")
        if st.button("🚀 Avanzar al Examen de Escenarios de Finca", type="primary"):
            st.session_state.step = 3
            st.rerun()

# ==============================================================================
# PASO 3: EXAMEN DE ESCENARIOS DE FINCA (OPCIONES ALEATORIAS)
# ==============================================================================
elif st.session_state.step == 3:
    st.subheader(f"Paso 3: Examen Técnico de Escenarios - {st.session_state.puesto}")
    st.info(
        "⏱️ **INSTRUCCIONES DEL EXAMEN:**\n"
        "1. Dispone de **10 minutos** para responder 20 casos situacionales reales de finca camaronera.\n"
        "2. Cada caso evalúa su criterio ante situaciones operativas, bioseguridad y prevención de riesgos.\n"
        "3. Al terminar, presione el botón **'🏁 Finalizar y Enviar Evaluación'**."
    )

    # Iniciar temporizador en servidor
    if st.session_state.quiz_start_time is None:
        st.session_state.quiz_start_time = time.time()

    tiempo_transcurrido = int(time.time() - st.session_state.quiz_start_time)
    tiempo_restante = max(0, 600 - tiempo_transcurrido)
    minutos = tiempo_restante // 60
    segundos = tiempo_restante % 60

    st.markdown(
        f"""
        <div style="background-color: #e8f4fd; border: 1px solid #b6d4fe; border-radius: 8px; padding: 12px; text-align: center;">
            <span style="font-size: 18px; font-weight: bold; color: #0d6efd;">⏱️ Tiempo Restante de Examen: </span>
            <span style="font-size: 22px; font-weight: bold; color: #dc3545;">{minutos:02d}:{segundos:02d}</span>
            <br><span style="font-size: 13px; color: #6c757d;">Responda las 20 preguntas con calma antes de que expire el tiempo.</span>
        </div>
        """,
        unsafe_allow_html=True
    )
    st.markdown("---")

    # Barajar opciones una sola vez por sesión (evita patrón A-B-C-D)
    if st.session_state.shuffled_banco is None:
        raw = BANCO_BIOLOGOS if "biólogo" in st.session_state.puesto.lower() else RAW_OPERARIOS
        st.session_state.shuffled_banco = preparar_banco_aleatorio(raw)

    banco = st.session_state.shuffled_banco
    user_answers = []

    with st.form("exam_form"):
        for i, item in enumerate(banco):
            st.markdown(f"**Caso {i+1}:** {item['q']}")
            resp = st.radio(f"Seleccione su decisión para el caso {i+1}:", item["opts"], key=f"ans_q_{i}")
            user_answers.append((resp, item["ans"]))
            st.markdown("---")

        submit_exam = st.form_submit_button("🏁 Finalizar y Enviar Evaluación", type="primary")

        if submit_exam:
            aciertos = sum(1 for r, correcta in user_answers if r.startswith(correcta))
            st.session_state.tech_score = round((aciertos / len(banco)) * 10.0, 1)
            st.session_state.step = 4
            st.rerun()

# ==============================================================================
# PASO 4: PANTALLA EXCLUSIVA DE AGRADECIMIENTO (SIN NOTAS NI RESULTADOS AL CANDIDATO)
# ==============================================================================
elif st.session_state.step == 4:
    # Ponderación interna: CV 30%, Entrevista IA 30%, Examen Técnico 40%
    score_final = round(
        (st.session_state.cv_score * 0.3) +
        (st.session_state.interview_score * 0.3) +
        (st.session_state.tech_score * 0.4), 1
    )

    if score_final >= 7.5:
        dictamen = "PRIORIDAD ALTA — Candidato recomendado para fase presencial"
    elif score_final >= 5.5:
        dictamen = "PRIORIDAD MEDIA — Requiere revisión detallada por RRHH"
    else:
        dictamen = "PRIORIDAD BAJA — No cumple perfil técnico mínimo"

    # Construcción del expediente confidencial de RRHH
    chat_transcript = "\n\n".join(
        f"{'Entrevistador IA' if m['role']=='agent' else 'Candidato'}: {m['content']}"
        for m in st.session_state.chat_history
    )

    reporte_confidencial = f"""======================================================================
NATUSIM - FICHA TÉCNICA CONFIDENCIAL DE SELECCIÓN DE PERSONAL
======================================================================
FECHA DE EVALUACIÓN: {time.strftime('%Y-%m-%d %H:%M:%S')}
CANDIDATO: {st.session_state.candidate_name} ({st.session_state.candidate_email})
VACANTE: {st.session_state.puesto} (Régimen Campamento 15/6)
SCORE FINAL INTEGRAL: {score_final} / 10.0
RECOMENDACIÓN DEL SISTEMA: {dictamen}

----------------------------------------------------------------------
1. MATRIZ DE CALIFICACIÓN POR COMPONENTES
----------------------------------------------------------------------
- Calificación Curricular (CV): {st.session_state.cv_score} / 10.0 (Ponderación 30%)
- Calificación Entrevista Adaptativa: {st.session_state.interview_score} / 10.0 (Ponderación 30%)
- Examen Técnico Situacional: {st.session_state.tech_score} / 10.0 (Ponderación 40%)

----------------------------------------------------------------------
2. AUDITORÍA BIOMÉTRICA Y VERIFICACIÓN DE IDENTIDAD
----------------------------------------------------------------------
Dictamen de Identidad: {st.session_state.biometric_audit}
Empresa Registrada en CV: {st.session_state.extracted_entities.get('empresa', 'No especificada')}
Cargo Registrado en CV: {st.session_state.extracted_entities.get('cargo', 'Técnico')}
Resumen Técnico de la IA: {st.session_state.interview_summary}

----------------------------------------------------------------------
3. TRANSCRIPCIÓN COMPLETA DE LA ENTREVISTA
----------------------------------------------------------------------
{chat_transcript}
======================================================================
"""

    # Guardar en base de datos (Google Sheets + Foto + Respaldo Local)
    registro = {
        "fecha": time.strftime('%Y-%m-%d %H:%M:%S'),
        "nombre": st.session_state.candidate_name,
        "email": st.session_state.candidate_email,
        "puesto": st.session_state.puesto,
        "cv_score": st.session_state.cv_score,
        "interview_score": st.session_state.interview_score,
        "tech_score": st.session_state.tech_score,
        "score_final": score_final,
        "dictamen": dictamen,
        "biometria_audit": st.session_state.biometric_audit,
        "reporte": reporte_confidencial
    }
    guardar_postulacion(registro, st.session_state.candidate_photo_bytes)

    # --------------------------------------------------------------------------
    # VISUALIZACIÓN AL CANDIDATO: MENSAJE INSTITUCIONAL LIMPIO (SIN NOTAS)
    # --------------------------------------------------------------------------
    st.balloons()
    st.success("🎉 ¡PROCESO DE POSTULACIÓN COMPLETADO CON ÉXITO!")

    st.markdown(
        f"""
        ### Estimado(a) **{st.session_state.candidate_name}**,

        Le agradecemos sinceramente por haber participado en el proceso de preselección para la vacante de **{st.session_state.puesto}** en NATUSIM.

        📋 **Recepción de Recaudos Confirmada:**
        - ✅ Registro de datos personales y verificación fotográfica de identidad.
        - ✅ Análisis de Hoja de Vida y experiencia previa en el sector acuícola.
        - ✅ Entrevista virtual técnica y examen de escenarios de finca.

        🔒 **Políticas de Selección y Siguientes Pasos:**
        Su expediente completo ha sido remitido al departamento de **Talento Humano**. 
        En caso de que su perfil se ajuste a los requerimientos de la operación y vacantes disponibles en campamento bajo la jornada 15/6, el equipo de Selección se contactará formalmente con usted mediante llamada telefónica o al correo electrónico registrado (**{st.session_state.candidate_email}**).

        *Ya puede cerrar esta ventana con total tranquilidad.*
        """
    )
    st.markdown("---")

    if st.button("🏁 Cerrar Postulación", type="primary"):
        for k in defaults.keys():
            st.session_state[k] = defaults[k]
        st.session_state.step = 1
        st.rerun()
