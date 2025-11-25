import streamlit as st
import pandas as pd
import json
from datetime import datetime
from anthropic import Anthropic
import os
import re

# Page config
st.set_page_config(
    page_title="Generador de Títulos - Cemaco",
    page_icon="📝",
    layout="wide"
)

# =========================
#   Session State Init
# =========================
if 'nomenclature_df' not in st.session_state:
    st.session_state.nomenclature_df = None
if 'transformation_memory' not in st.session_state:
    st.session_state.transformation_memory = {}
if 'generated_titles' not in st.session_state:
    st.session_state.generated_titles = []
if 'api_key' not in st.session_state:
    st.session_state.api_key = ""

# =========================
#   Helper Functions
# =========================

def load_nomenclature(file):
    """Load nomenclature CSV."""
    try:
        df = pd.read_csv(file, encoding='utf-8-sig')
        return df
    except Exception as e:
        st.error(f"Error cargando nomenclatura: {e}")
        return None

def apply_transformations(text, transformations):
    """
    Aplica transformaciones de manera:
    - insensible a mayúsculas/minúsculas
    - soportando singular/plural sencillo (pulgada/pulgadas)
    """
    if not text:
        return text

    out = text
    for original, replacement in transformations.items():
        # palabra base normalizada
        base = original.strip()
        if not base:
            continue

        # regex: palabra + s opcional, con límites de palabra
        pattern = re.compile(rf"\b{re.escape(base)}(s)?\b", re.IGNORECASE)
        out = pattern.sub(replacement, out)

    # limpia espacios dobles
    return " ".join(out.split())

# === Title post-processing helpers ===
ACRONYMS_OK = {
    "PVC", "CPVC", "AC", "DC", "LED", "RGB",
    "IP", "UV", "USB", "HDMI",
    "mm", "cm", "m", "plg"
}

def _cap_first(word: str) -> str:
    return word[:1].upper() + word[1:].lower() if word else word

def de_shout(text: str) -> str:
    """
    Turn ALL-CAPS words into Capitalized, but keep known acronyms as-is.
    Example: 'VALVULA PVC 1/2 PLG' -> 'Valvula PVC 1/2 PLG'
    """
    tokens = []
    for w in text.split():
        # Remove basic punctuation to inspect the core word
        stripped_left = w.lstrip(".,;:()[]{}-/")
        stripped = stripped_left.rstrip(".,;:()[]{}-/")
        bare = stripped

        if len(bare) > 1 and bare.isupper() and bare not in ACRONYMS_OK:
            prefix_len = len(w) - len(stripped_left)
            suffix_len = len(stripped) - len(bare)
            prefix = w[:prefix_len]
            suffix = w[len(w) - suffix_len:] if suffix_len > 0 else ""
            core = _cap_first(bare)
            tokens.append(f"{prefix}{core}{suffix}")
        else:
            tokens.append(w)
    return " ".join(tokens)

def remove_brand_occurrences(text: str, brand: str) -> str:
    """Remove brand mentions from a title if present (case-insensitive)."""
    if not brand:
        return text
    if not text:
        return text
    # Simple case-insensitive replace
    t = text
    t = t.replace(brand, "")
    t = t.replace(brand.upper(), "")
    t = t.replace(brand.lower(), "")
    # Also try capitalized form
    t = t.replace(_cap_first(brand.lower()), "")
    # Normalize spaces
    return " ".join(t.split()).strip()

# ========= Helpers para match de nomenclatura =========

def normalize_tax_value(value: str) -> str:
    """
    Normaliza valores de departamento/familia/categoría:
    - Convierte a string
    - Quita códigos entre paréntesis: 'Plomeria (0024)' -> 'Plomeria'
    - Quita espacios extra
    - Pone todo en MAYÚSCULAS
    """
    if value is None:
        return ""
    value = str(value)
    # Quitar códigos tipo " (0024)"
    value = re.sub(r"\s*\([^)]*\)", "", value)
    return value.strip().upper()


def find_pattern_row(nomenclature_df: pd.DataFrame, dept, fam, cat):
    """
    Busca la fila de nomenclatura correcta para un dept/familia/categoría de ERP.

    1) Hace match por Departamento + Familia normalizados.
    2) Intenta match exacto por Categoría normalizada.
    3) Si no hay, elige la categoría con más palabras en común
       con la categoría de ERP (PVC, CPVC, ACC, etc.).
    """
    dep_norm = normalize_tax_value(dept)
    fam_norm = normalize_tax_value(fam)
    cat_norm = normalize_tax_value(cat)

    # Candidatos por departamento + familia
    candidates = nomenclature_df[
        (nomenclature_df['Departamento'].astype(str).apply(normalize_tax_value) == dep_norm) &
        (nomenclature_df['Familia'].astype(str).apply(normalize_tax_value) == fam_norm)
    ]
    if candidates.empty:
        return None

    # 1) Match exacto de categoría normalizada
    with_cat = candidates[
        candidates['Categoria'].astype(str).apply(normalize_tax_value) == cat_norm
    ]
    if not with_cat.empty:
        return with_cat.iloc[0]

    # 2) Match “mejor esfuerzo” por palabras en común
    cat_words = set(cat_norm.split())
    if not cat_words:
        return candidates.iloc[0]

    def score(cat_val):
        words = set(normalize_tax_value(cat_val).split())
        return len(cat_words & words)

    scores = candidates['Categoria'].apply(score)
    best_idx = scores.idxmax()
    return candidates.loc[best_idx]

# =========================
#   Claude Title Generator
# =========================

def generate_titles(product_info, nomenclature_pattern, transformations):
    """Generate title variants using Claude API with post-processing."""
    
    # Get API key from secrets or session state
    api_key = None
    try:
        if "ANTHROPIC_API_KEY" in st.secrets:
            if st.secrets["ANTHROPIC_API_KEY"]:
                api_key = st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        pass
    
    if not api_key and 'api_key' in st.session_state:
        if st.session_state.api_key:
            api_key = st.session_state.api_key
    
    if not api_key:
        st.error("❌ API key no configurada")
        return None
    
    client = Anthropic(api_key=api_key)
    
    prompt = f"""Eres experto en crear títulos de productos para catálogos de retail en Guatemala.

INFORMACIÓN DEL PRODUCTO (útil para contexto, pero con reglas de exclusión):
{json.dumps(product_info, indent=2, ensure_ascii=False)}

PATRÓN DE NOMENCLATURA A SEGUIR:
{nomenclature_pattern}

TRANSFORMACIONES CONSISTENTES A APLICAR:
{json.dumps(transformations, indent=2, ensure_ascii=False)}

REGLAS CLAVE (OBLIGATORIAS):
- NUNCA incluyas la marca en ningún título, aunque venga en los datos.
- Evita nombres de taxonomía como departamento/familia/categoría en el título SEO; solo inclúyelos si son críticos para desambiguar entre productos muy distintos.
- Usa español de Guatemala.
- No uses símbolos como ® o ™.
- Usa abreviaciones estándar (plg, mm, cm, etc.) y respeta mayúsculas de acrónimos (PVC, CPVC, AC, DC, LED, mm, cm, plg).
- Si recibes palabras en MAYÚSCULAS, conviértelas a Capitalizado (primera letra mayúscula y resto minúsculas), salvo acrónimos.
- Límites:
  a) TÍTULO SISTEMA (40 caracteres máx):
     - Conciso, claro, sin marca
     - Sigue el patrón de nomenclatura exactamente
  b) TÍTULO ETIQUETA (36 caracteres máx):
     - Si el título sistema cabe en 36 caracteres, reutilízalo
     - Si no, crea una versión más corta manteniendo lo crítico
  c) TÍTULO SEO:
     - Más descriptivo, optimizado para búsqueda en cemaco.com
     - Incluye palabras clave relevantes del producto
     - Sin taxonomía salvo que desambiguar sea necesario
     - Idealmente entre 50 y 70 caracteres

RESPONDE SOLO CON UN JSON VÁLIDO con este formato exacto:
{{
  "titulo_sistema": "...",
  "longitud_sistema": 40,
  "titulo_etiqueta": "...",
  "longitud_etiqueta": 36,
  "titulo_seo": "...",
  "longitud_seo": 65,
  "transformaciones_aplicadas": [],
  "cumple_nomenclatura": true,
  "notas": ""
}}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text.strip()
        # Remove markdown code blocks if present
        response_text = response_text.replace("```json", "").replace("```", "").strip()
        
        result = json.loads(response_text)

        # --- Post-processing: remove brand + de-shout titles ---
        brand = ""
        try:
            brand = (product_info.get("marca") or "").strip()
        except Exception:
            brand = ""

        for key in ["titulo_sistema", "titulo_etiqueta", "titulo_seo"]:
            if key in result and isinstance(result[key], str):
                t = result[key]
        # 1) aplica memoria de transformaciones (pulgada -> plg)
        t = apply_transformations(t, transformations)
        # 2) quita marca por si se coló
        t = remove_brand_occurrences(t, brand)
        # 3) corrige mayúsculas
        t = de_shout(t)
        result[key] = " ".join(t.split())  # tidy spaces

        return result
    except Exception as e:
        st.error(f"Error generando títulos: {e}")
        return None

# =========================
#   MAIN UI
# =========================

st.title("📝 Generador de Títulos de Catálogo - Cemaco")
st.markdown("### Sistema de nomenclatura con memoria de transformaciones")

# Sidebar for file upload and transformations
with st.sidebar:
    st.header("Configuración")
    
    # API Key input - handle case when secrets.toml doesn't exist
    api_key_configured = False
    try:
        if "ANTHROPIC_API_KEY" in st.secrets and st.secrets["ANTHROPIC_API_KEY"]:
            api_key_configured = True
    except Exception:
        pass
    
    if not api_key_configured:
        if 'api_key' not in st.session_state:
            st.session_state.api_key = ""
        
        api_key_input = st.text_input(
            "Anthropic API Key", 
            value=st.session_state.api_key,
            type="password",
            help="Obtén tu API key en console.anthropic.com"
        )
        if api_key_input:
            st.session_state.api_key = api_key_input
            api_key_configured = True
    
    if not api_key_configured:
        st.warning("⚠️ Por favor ingresa tu Anthropic API Key para continuar")
    
    st.markdown("---")
    
    # Load nomenclature file
    st.subheader("1. Cargar Nomenclatura")
    uploaded_nomenclature = st.file_uploader(
        "Sube el archivo de nomenclatura",
        type=['csv'],
        help="Archivo CSV con departamentos, familias, categorías y patrones"
    )
    
    if uploaded_nomenclature:
        st.session_state.nomenclature_df = load_nomenclature(uploaded_nomenclature)
        if st.session_state.nomenclature_df is not None:
            st.success(f"✅ {len(st.session_state.nomenclature_df)} reglas cargadas")
    
    st.markdown("---")
    
    # Transformation memory
    st.subheader("2. Memoria de Transformaciones")
    st.caption("Mantén consistencia en abreviaciones")
    
    # Add new transformation
    col1, col2 = st.columns(2)
    with col1:
        original = st.text_input("Original", key="trans_orig")
    with col2:
        replacement = st.text_input("Reemplazo", key="trans_repl")
    
    if st.button("➕ Agregar Transformación"):
        if original and replacement:
            st.session_state.transformation_memory[original] = replacement
            st.success(f"Agregado: {original} → {replacement}")
    
    # Display current transformations
    if st.session_state.transformation_memory:
        st.markdown("**Transformaciones Activas:**")
        for orig, repl in list(st.session_state.transformation_memory.items()):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.text(f"{orig} → {repl}")
            with col2:
                if st.button("🗑️", key=f"del_{orig}"):
                    del st.session_state.transformation_memory[orig]
                    st.rerun()
    
    st.markdown("---")
    
    # Export results
    st.subheader("3. Exportar Resultados")
    if st.session_state.generated_titles:
        df_export = pd.DataFrame(st.session_state.generated_titles)
        csv = df_export.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="📥 Descargar Títulos Generados",
            data=csv,
            file_name=f"titulos_generados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )

# Main content area
if st.session_state.nomenclature_df is None:
    st.info("👈 Por favor carga el archivo de nomenclatura en el panel lateral para comenzar.")
else:
    df = st.session_state.nomenclature_df

    # Tabs
    tab1, tab2, tab3 = st.tabs([
        "🔨 Crear Título Individual",
        "✏️ Ya Tengo Título Sistema",
        "📦 Procesamiento por Lote"
    ])
    
    # -------------------------
    # TAB 1: Individual title
    # -------------------------
    with tab1:
        st.subheader("Crear Nuevo Título")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            departamentos = sorted(df['Departamento'].unique())
            selected_dept = st.selectbox("Departamento", options=departamentos)
        
        with col2:
            familias = sorted(df[df['Departamento'] == selected_dept]['Familia'].unique())
            selected_familia = st.selectbox("Familia", options=familias)
        
        with col3:
            categorias = sorted(df[
                (df['Departamento'] == selected_dept) & 
                (df['Familia'] == selected_familia)
            ]['Categoria'].unique())
            selected_categoria = st.selectbox("Categoría", options=categorias)
        
        pattern_row = df[
            (df['Departamento'] == selected_dept) & 
            (df['Familia'] == selected_familia) & 
            (df['Categoria'] == selected_categoria)
        ]
        
        if not pattern_row.empty:
            nomenclatura = pattern_row.iloc[0]['Nomenclatura sugerida']
            ejemplo = pattern_row.iloc[0]['Ejemplo aplicado']
            
            st.info(f"**Patrón de Nomenclatura:** {nomenclatura}")
            st.caption(f"Ejemplo: {ejemplo}")
            
            st.markdown("---")
            
            st.subheader("Información del Producto")
            
            product_name = st.text_input("Nombre del Producto", help="Nombre base del producto")
            
            col1, col2 = st.columns(2)
            with col1:
                tipo = st.text_input("Tipo", help="Ej: Tornillo, Cable, Bomba")
                material = st.text_input("Material", help="Ej: Acero, PVC, Cobre")
                medidas = st.text_input("Dimensiones", help="Ej: 1/2 x 6m, 10x20cm")
            
            with col2:
                color = st.text_input("Color", help="Ej: Blanco, Negro, Gris")
                marca = st.text_input("Marca (no se usará en el título)", help="Solo para contexto interno")
                otros = st.text_area("Otros atributos", help="Características adicionales")
            
            if st.button("🚀 Generar Títulos", type="primary", use_container_width=True):
                if product_name or tipo:
                    with st.spinner("Generando títulos optimizados..."):
                        product_info = {
                            "nombre_producto": product_name,
                            "tipo": tipo,
                            "material": material,
                            "dimensiones": medidas,
                            "color": color,
                            "marca": marca,
                            "otros_atributos": otros,
                            "departamento": selected_dept,
                            "familia": selected_familia,
                            "categoria": selected_categoria
                        }
                        
                        result = generate_titles(
                            product_info,
                            nomenclatura,
                            st.session_state.transformation_memory
                        )
                        
                        if result:
                            st.success("✅ Títulos Generados Exitosamente")
                            
                            col1, col2, col3 = st.columns(3)
                            
                            with col1:
                                st.markdown("### 📋 Título Sistema")
                                titulo_sistema = result.get('titulo_sistema', '')
                                chars_sistema = len(titulo_sistema)
                                color_sistema = "green" if chars_sistema <= 40 else "red"
                                st.markdown(f"**{titulo_sistema}**")
                                st.markdown(
                                    f"<span style='color:{color_sistema}'>Longitud: {chars_sistema}/40</span>",
                                    unsafe_allow_html=True
                                )
                            
                            with col2:
                                st.markdown("### 🏷️ Título Etiqueta")
                                titulo_etiqueta = result.get('titulo_etiqueta', '')
                                chars_etiqueta = len(titulo_etiqueta)
                                color_etiqueta = "green" if chars_etiqueta <= 36 else "red"
                                st.markdown(f"**{titulo_etiqueta}**")
                                st.markdown(
                                    f"<span style='color:{color_etiqueta}'>Longitud: {chars_etiqueta}/36</span>",
                                    unsafe_allow_html=True
                                )
                            
                            with col3:
                                st.markdown("### 🌐 Título SEO")
                                titulo_seo = result.get('titulo_seo', '')
                                chars_seo = len(titulo_seo)
                                st.markdown(f"**{titulo_seo}**")
                                st.markdown(f"Longitud: {chars_seo} caracteres")
                            
                            if result.get('transformaciones_aplicadas'):
                                st.info(
                                    f"**Transformaciones aplicadas:** "
                                    f"{', '.join(result['transformaciones_aplicadas'])}"
                                )
                            
                            result_with_meta = {
                                **result,
                                **product_info,
                                "fecha": datetime.now().isoformat()
                            }
                            st.session_state.generated_titles.append(result_with_meta)
                            
                            if result.get('notas'):
                                st.caption(f"📝 {result['notas']}")
                else:
                    st.warning("⚠️ Ingresa al menos el nombre del producto o tipo")
    
    # -------------------------
    # TAB 2: Already have system title
    # -------------------------
    with tab2:
        st.subheader("Ya Tengo el Título del Sistema")
        st.markdown(
            "Genera únicamente los títulos de **Etiqueta** y **SEO** a partir de un título sistema existente "
            "(sin marca y con corrección de mayúsculas)."
        )
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            departamentos = sorted(df['Departamento'].unique())
            selected_dept_existing = st.selectbox(
                "Departamento", options=departamentos, key="dept_existing"
            )
        
        with col2:
            familias = sorted(
                df[df['Departamento'] == selected_dept_existing]['Familia'].unique()
            )
            selected_familia_existing = st.selectbox(
                "Familia", options=familias, key="familia_existing"
            )
        
        with col3:
            categorias = sorted(df[
                (df['Departamento'] == selected_dept_existing) & 
                (df['Familia'] == selected_familia_existing)
            ]['Categoria'].unique())
            selected_categoria_existing = st.selectbox(
                "Categoría", options=categorias, key="categoria_existing"
            )
        
        pattern_row = df[
            (df['Departamento'] == selected_dept_existing) & 
            (df['Familia'] == selected_familia_existing) & 
            (df['Categoria'] == selected_categoria_existing)
        ]
        
        if not pattern_row.empty:
            nomenclatura = pattern_row.iloc[0]['Nomenclatura sugerida']
            ejemplo = pattern_row.iloc[0]['Ejemplo aplicado']
            
            st.info(f"**Patrón de Nomenclatura:** {nomenclatura}")
            st.caption(f"Ejemplo: {ejemplo}")
            
            st.markdown("---")
            
            existing_title = st.text_area(
                "Título Sistema Existente",
                help="Pega aquí el título del sistema que ya tienes (máx 40 caracteres)",
                max_chars=80
            )
            
            if existing_title:
                chars_existing = len(existing_title)
                if chars_existing > 40:
                    st.warning(f"⚠️ El título tiene {chars_existing} caracteres (límite: 40)")
                else:
                    st.success(f"✅ Longitud: {chars_existing}/40 caracteres")
            
            if st.button(
                "🚀 Generar Etiqueta y SEO",
                type="primary",
                use_container_width=True,
                key="gen_existing"
            ):
                if existing_title:
                    with st.spinner("Generando títulos de etiqueta y SEO..."):
                        product_info = {
                            "titulo_sistema_existente": existing_title,
                            "departamento": selected_dept_existing,
                            "familia": selected_familia_existing,
                            "categoria": selected_categoria_existing,
                            "marca": ""  # nunca usamos marca en títulos
                        }
                        
                        result = generate_titles(
                            product_info,
                            nomenclatura,
                            st.session_state.transformation_memory
                        )
                        
                        if result:
                            st.success("✅ Títulos Generados Exitosamente")
                            
                            col1, col2, col3 = st.columns(3)
                            
                            with col1:
                                st.markdown("### 📋 Título Sistema (Original)")
                                cleaned_existing = de_shout(
                                    remove_brand_occurrences(existing_title, "")
                                )
                                st.markdown(f"**{cleaned_existing}**")
                                st.markdown(f"Longitud: {len(cleaned_existing)}/40")
                            
                            with col2:
                                st.markdown("### 🏷️ Título Etiqueta")
                                titulo_etiqueta = result.get('titulo_etiqueta', '')
                                chars_etiqueta = len(titulo_etiqueta)
                                color_etiqueta = "green" if chars_etiqueta <= 36 else "red"
                                st.markdown(f"**{titulo_etiqueta}**")
                                st.markdown(
                                    f"<span style='color:{color_etiqueta}'>Longitud: {chars_etiqueta}/36</span>",
                                    unsafe_allow_html=True
                                )
                            
                            with col3:
                                st.markdown("### 🌐 Título SEO")
                                titulo_seo = result.get('titulo_seo', '')
                                chars_seo = len(titulo_seo)
                                st.markdown(f"**{titulo_seo}**")
                                st.markdown(f"Longitud: {chars_seo} caracteres")
                            
                            if result.get('transformaciones_aplicadas'):
                                st.info(
                                    f"**Transformaciones aplicadas:** "
                                    f"{', '.join(result['transformaciones_aplicadas'])}"
                                )
                            
                            result_with_meta = {
                                "titulo_sistema_original": cleaned_existing,
                                **result,
                                "departamento": selected_dept_existing,
                                "familia": selected_familia_existing,
                                "categoria": selected_categoria_existing,
                                "fecha": datetime.now().isoformat()
                            }
                            st.session_state.generated_titles.append(result_with_meta)
                            
                            if result.get('notas'):
                                st.caption(f"📝 {result['notas']}")
                else:
                    st.warning("⚠️ Por favor ingresa un título sistema")

    # -------------------------
    # TAB 3: Batch processing
    # -------------------------
    with tab3:
        st.subheader("Procesamiento por Lote")
        st.markdown(
            "Dos modos: **Simplificado** (una categoría para todos) "
            "o **Completo** (cada fila trae su categoría)."
        )

        # Choose which titles to generate
        generate_opts = st.multiselect(
            "¿Qué tipos de título quieres generar en el lote?",
            options=["Sistema", "Etiqueta", "SEO"],
            default=["Etiqueta", "SEO"],
            help="Elige uno, dos o los tres tipos."
        )
        want_sistema = "Sistema" in generate_opts
        want_etiqueta = "Etiqueta" in generate_opts
        want_seo = "SEO" in generate_opts

        mode = st.radio(
            "Modo de Procesamiento:",
            ["🎯 Simplificado - Una categoría para todos", "📋 Completo - Categorías individuales"],
            help="Simplificado: todos los títulos usan la misma categoría. "
                 "Completo: cada título tiene su propia categoría en el CSV"
        )
        
        st.markdown("---")
        
        if mode == "🎯 Simplificado - Una categoría para todos":
            st.markdown("### 1️⃣ Selecciona la Categoría")
            st.caption("Todos los títulos que subas usarán esta categoría")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                departamentos_simple = sorted(df['Departamento'].unique())
                selected_dept_simple = st.selectbox(
                    "Departamento", options=departamentos_simple, key="dept_simple"
                )
            
            with col2:
                familias_simple = sorted(
                    df[df['Departamento'] == selected_dept_simple]['Familia'].unique()
                )
                selected_familia_simple = st.selectbox(
                    "Familia", options=familias_simple, key="familia_simple"
                )
            
            with col3:
                categorias_simple = sorted(df[
                    (df['Departamento'] == selected_dept_simple) & 
                    (df['Familia'] == selected_familia_simple)
                ]['Categoria'].unique())
                selected_categoria_simple = st.selectbox(
                    "Categoría", options=categorias_simple, key="categoria_simple"
                )
            
            pattern_row = df[
                (df['Departamento'] == selected_dept_simple) & 
                (df['Familia'] == selected_familia_simple) & 
                (df['Categoria'] == selected_categoria_simple)
            ]
            
            if not pattern_row.empty:
                nomenclatura = pattern_row.iloc[0]['Nomenclatura sugerida']
                ejemplo = pattern_row.iloc[0]['Ejemplo aplicado']
                
                st.info(f"**Patrón:** {nomenclatura}")
                st.caption(f"Ejemplo: {ejemplo}")
            
            st.markdown("---")
            st.markdown("### 2️⃣ Sube tu Archivo")
            st.caption("CSV o Excel con una columna llamada 'titulo_sistema' o similar")
            
            uploaded_simple = st.file_uploader(
                "Archivo con títulos",
                type=['csv', 'xlsx', 'xls'],
                key="simple_upload",
                help="Solo necesitas una columna con los títulos del sistema (puede incluir SKU)."
            )
            
            if uploaded_simple:
                file_extension = uploaded_simple.name.split('.')[-1].lower()
                
                try:
                    if file_extension == 'csv':
                        simple_df = pd.read_csv(uploaded_simple, encoding='utf-8-sig')
                    else:
                        simple_df = pd.read_excel(uploaded_simple)
                    
                    title_col = None
                    possible_names = [
                        'titulo_sistema', 'titulos', 'titulo', 'títulos',
                        'título', 'title', 'titles'
                    ]
                    
                    for col in simple_df.columns:
                        if col.lower().strip() in possible_names:
                            title_col = col
                            break
                    
                    if title_col is None:
                        st.error(
                            "❌ No se encontró una columna de títulos. "
                            "Busqué: " + ", ".join(possible_names)
                        )
                        st.info(
                            "**Columnas encontradas:** " +
                            ", ".join(simple_df.columns.tolist())
                        )
                    else:
                        st.success(f"✅ {len(simple_df)} títulos cargados desde columna '{title_col}'")
                        st.dataframe(simple_df.head(10))
                        if len(simple_df) > 10:
                            st.caption(f"Mostrando las primeras 10 de {len(simple_df)} filas")
                        
                        if st.button(
                            "🚀 Procesar Todos",
                            type="primary",
                            key="process_simple"
                        ):
                            if not pattern_row.empty:
                                progress_bar = st.progress(0)
                                status_text = st.empty()
                                results = []
                                
                                for idx, row in simple_df.iterrows():
                                    titulo = str(row[title_col]).strip()
                                    if titulo and titulo != 'nan':
                                        status_text.text(
                                            f"Procesando {idx + 1} de {len(simple_df)}: "
                                            f"{titulo[:40]}..."
                                        )
                                        
                                        product_info = {
                                            "titulo_sistema_existente": titulo,
                                            "departamento": selected_dept_simple,
                                            "familia": selected_familia_simple,
                                            "categoria": selected_categoria_simple,
                                            "marca": ""
                                        }
                                        
                                        result = generate_titles(
                                            product_info,
                                            nomenclatura,
                                            st.session_state.transformation_memory
                                        )
                                        
                                        if result:
                                            row_out = {
                                                'titulo_sistema_original': titulo,
                                                'departamento': selected_dept_simple,
                                                'familia': selected_familia_simple,
                                                'categoria': selected_categoria_simple
                                            }
                                            if 'SKU' in simple_df.columns:
                                                row_out['SKU'] = row['SKU']
                                            if want_sistema and 'titulo_sistema' in result:
                                                row_out['titulo_sistema_generado'] = result['titulo_sistema']
                                            if want_etiqueta and 'titulo_etiqueta' in result:
                                                row_out['titulo_etiqueta'] = result['titulo_etiqueta']
                                            if want_seo and 'titulo_seo' in result:
                                                row_out['titulo_seo'] = result['titulo_seo']
                                            results.append(row_out)
                                    
                                    progress_bar.progress((idx + 1) / len(simple_df))
                                
                                status_text.empty()
                                
                                if results:
                                    st.success(f"✅ Procesados {len(results)} títulos exitosamente")
                                    results_df = pd.DataFrame(results)
                                    st.dataframe(results_df)
                                    
                                    csv = results_df.to_csv(index=False, encoding='utf-8-sig')
                                    st.download_button(
                                        label="📥 Descargar Resultados CSV",
                                        data=csv,
                                        file_name=f"titulos_procesados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                        mime="text/csv"
                                    )
                                else:
                                    st.warning("⚠️ No se procesaron títulos")
                
                except Exception as e:
                    st.error(f"❌ Error al leer el archivo: {e}")
        
        else:
            # ---------------------
            # Modo completo
            # ---------------------
            st.markdown("### 📋 Modo Completo")
            st.caption("Tu archivo debe incluir: titulo_sistema, departamento, familia, categoria (y opcionalmente SKU)")
            
            st.markdown("### 🔍 Filtros (Opcional)")
            st.caption("Procesa solo productos de categorías específicas")
            
            col1, col2, col3, col4 = st.columns([3, 3, 3, 1])
            
            with col1:
                departamentos_batch = ["Todos"] + sorted(df['Departamento'].unique().tolist())
                selected_dept_batch = st.selectbox(
                    "Departamento", options=departamentos_batch, key="dept_batch"
                )
            
            with col2:
                if selected_dept_batch != "Todos":
                    familias_batch = ["Todos"] + sorted(
                        df[df['Departamento'] == selected_dept_batch]['Familia'].unique().tolist()
                    )
                else:
                    familias_batch = ["Todos"]
                selected_familia_batch = st.selectbox(
                    "Familia", options=familias_batch, key="familia_batch"
                )
            
            with col3:
                if selected_dept_batch != "Todos" and selected_familia_batch != "Todos":
                    categorias_batch = ["Todos"] + sorted(df[
                        (df['Departamento'] == selected_dept_batch) &
                        (df['Familia'] == selected_familia_batch)
                    ]['Categoria'].unique().tolist())
                else:
                    categorias_batch = ["Todos"]
                selected_categoria_batch = st.selectbox(
                    "Categoría", options=categorias_batch, key="categoria_batch"
                )
            
            with col4:
                st.markdown("&nbsp;")
                if st.button("🔄", help="Resetear filtros"):
                    st.rerun()
            
            st.markdown("---")
        
            uploaded_batch = st.file_uploader(
                "Archivo CSV o Excel con títulos y categorías",
                type=['csv', 'xlsx', 'xls'],
                key="batch_upload",
                help="Debe incluir columnas: titulo_sistema, departamento, familia, categoria (y opcionalmente SKU)"
            )
            
            if uploaded_batch:
                file_extension = uploaded_batch.name.split('.')[-1].lower()
                
                try:
                    if file_extension == 'csv':
                        batch_df = pd.read_csv(uploaded_batch, encoding='utf-8-sig')
                    else:
                        batch_df = pd.read_excel(uploaded_batch)
                    
                    required_cols = ['titulo_sistema', 'departamento', 'familia', 'categoria']
                    missing_cols = [col for col in required_cols if col not in batch_df.columns]
                    
                    if missing_cols:
                        st.error(f"❌ Faltan columnas requeridas: {', '.join(missing_cols)}")
                        st.info(
                            "**Columnas encontradas:** " +
                            ", ".join(batch_df.columns.tolist())
                        )
                        st.info("**Columnas requeridas:** " + ", ".join(required_cols))
                    else:
                        filtered_df = batch_df.copy()
                        filter_applied = False
                        
                        if selected_dept_batch != "Todos":
                            filtered_df = filtered_df[
                                filtered_df['departamento'] == selected_dept_batch
                            ]
                            filter_applied = True
                        
                        if selected_familia_batch != "Todos":
                            filtered_df = filtered_df[
                                filtered_df['familia'] == selected_familia_batch
                            ]
                            filter_applied = True
                        
                        if selected_categoria_batch != "Todos":
                            filtered_df = filtered_df[
                                filtered_df['categoria'] == selected_categoria_batch
                            ]
                            filter_applied = True
                        
                        if filter_applied:
                            st.info(
                                f"🔍 Filtros aplicados: "
                                f"{len(filtered_df)} de {len(batch_df)} productos seleccionados"
                            )
                        
                        st.dataframe(filtered_df.head(10))
                        if len(filtered_df) > 10:
                            st.caption(
                                f"Mostrando las primeras 10 filas de {len(filtered_df)} productos"
                            )
                        
                        if len(filtered_df) == 0:
                            st.warning(
                                "⚠️ No hay productos que coincidan con los filtros seleccionados"
                            )
                        else:
                            if st.button("🚀 Procesar Lote", type="primary"):
                                progress_bar = st.progress(0)
                                status_text = st.empty()
                                results = []
                                
                                for idx, row in filtered_df.iterrows():
                                    status_text.text(
                                        f"Procesando {idx + 1} de {len(filtered_df)}..."
                                    )
                                    
                                    pattern = find_pattern_row(
                                        df,
                                        row['departamento'],
                                        row['familia'],
                                        row['categoria']
                                    )
                                    
                                    if pattern is None:
                                        # No hay regla para esa categoría (ej. Pisos Rústicos hoy)
                                        continue
                                    
                                    nomenclatura = pattern['Nomenclatura sugerida']
                                    
                                    product_info = {
                                        "titulo_sistema_existente": row['titulo_sistema'],
                                        "departamento": row['departamento'],
                                        "familia": row['familia'],
                                        "categoria": row['categoria'],
                                        "marca": ""
                                    }
                                    
                                    result = generate_titles(
                                        product_info,
                                        nomenclatura,
                                        st.session_state.transformation_memory
                                    )
                                    
                                    if result:
                                        row_out = {
                                            'titulo_sistema_original': row['titulo_sistema'],
                                            'departamento': row['departamento'],
                                            'familia': row['familia'],
                                            'categoria': row['categoria']
                                        }
                                        if 'SKU' in filtered_df.columns:
                                            row_out['SKU'] = row['SKU']
                                        if want_sistema and 'titulo_sistema' in result:
                                            row_out['titulo_sistema_generado'] = result['titulo_sistema']
                                        if want_etiqueta and 'titulo_etiqueta' in result:
                                            row_out['titulo_etiqueta'] = result['titulo_etiqueta']
                                        if want_seo and 'titulo_seo' in result:
                                            row_out['titulo_seo'] = result['titulo_seo']
                                        
                                        results.append(row_out)
                                    
                                    progress_bar.progress((idx + 1) / len(filtered_df))
                                
                                status_text.empty()
                                
                                if results:
                                    st.success(f"✅ Procesados {len(results)} títulos")
                                    results_df = pd.DataFrame(results)
                                    st.dataframe(results_df)
                                    
                                    csv = results_df.to_csv(index=False, encoding='utf-8-sig')
                                    st.download_button(
                                        label="📥 Descargar Resultados",
                                        data=csv,
                                        file_name=f"batch_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                        mime="text/csv"
                                    )
                                else:
                                    st.warning("⚠️ No se generaron resultados")
                
                except Exception as e:
                    st.error(f"❌ Error al leer el archivo: {e}")

# Footer
st.markdown("---")
st.caption("Generador de Títulos de Catálogo - Cemaco © 2025")