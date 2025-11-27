import streamlit as st
import pandas as pd
import json
from datetime import datetime
from anthropic import Anthropic
import os
import re
import time

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
if 'validation_stats' not in st.session_state:
    st.session_state.validation_stats = {
        'total_processed': 0,
        'validation_passed': 0,
        'validation_corrected': 0,
        'validation_failed': 0
    }

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
        base = original.strip()
        if not base:
            continue

        # palabra + s opcional, con límites de palabra
        pattern = re.compile(rf"\b{re.escape(base)}(s)?\b", re.IGNORECASE)
        out = pattern.sub(replacement, out)

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
    Convierte palabras en MAYÚSCULAS a Capitalizado,
    pero mantiene acrónimos (PVC, CPVC, LED, etc.).
    """
    tokens = []
    for w in text.split():
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
    """Remueve la marca del título si aparece (case-insensitive)."""
    if not brand or not text:
        return text

    t = text
    t = t.replace(brand, "")
    t = t.replace(brand.upper(), "")
    t = t.replace(brand.lower(), "")
    t = t.replace(_cap_first(brand.lower()), "")

    return " ".join(t.split()).strip()

FORBIDDEN_TECH_TERMS = [
    "penetrante",
    "hidráulico", "hidraulico",
    "neumático", "neumatico",
    "amortiguador",
    "dieléctrico", "dielektrico",
    "epóxico", "epoxico", "epóxica", "epoxica",
    "antigripante",
    "dieléctrica", "dielektrica"
]

def remove_forbidden_terms(text: str) -> str:
    """
    Elimina términos técnicos que el modelo suele inventar
    y que no queremos a menos que vengan explícitos en el ERP.
    """
    if not text:
        return text

    out = str(text)
    for term in FORBIDDEN_TECH_TERMS:
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        out = pattern.sub("", out)

    # limpia espacios dobles / inicio / fin
    return " ".join(out.split())

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
    value = re.sub(r"\s*\([^)]*\)", "", value)
    return value.strip().upper()


def find_pattern_row(nomenclature_df: pd.DataFrame, dept, fam, cat):
    """
    Busca la fila de nomenclatura correcta para un dept/familia/categoría de ERP.

    1) Match por Departamento + Familia normalizados.
    2) Match exacto por Categoría normalizada.
    3) Si no hay, elige la categoría con más palabras en común.
    """
    dep_norm = normalize_tax_value(dept)
    fam_norm = normalize_tax_value(fam)
    cat_norm = normalize_tax_value(cat)

    candidates = nomenclature_df[
        (nomenclature_df['Departamento'].astype(str).apply(normalize_tax_value) == dep_norm) &
        (nomenclature_df['Familia'].astype(str).apply(normalize_tax_value) == fam_norm)
    ]
    if candidates.empty:
        return None

    with_cat = candidates[
        candidates['Categoria'].astype(str).apply(normalize_tax_value) == cat_norm
    ]
    if not with_cat.empty:
        return with_cat.iloc[0]

    cat_words = set(cat_norm.split())
    if not cat_words:
        return candidates.iloc[0]

    def score(cat_val):
        words = set(normalize_tax_value(cat_val).split())
        return len(cat_words & words)

    scores = candidates['Categoria'].apply(score)
    best_idx = scores.idxmax()
    return candidates.loc[best_idx]


# ========= Limpieza de frases genéricas "para ..." =========

GENERIC_PARA_PATTERNS = [
    r"\s*para\s+plomer[ií]a$",
    r"\s*para\s+tuber[ií]a$",
    r"\s*para\s+ferreter[ií]a$",
    r"\s*para\s+construcci[oó]n$",
    r"\s*para\s+el\s+hogar$",
    r"\s*para\s+hogar$",
]

def remove_generic_para_phrases(text: str) -> str:
    """
    Elimina finales genéricos:
    - para plomería, para tubería, para ferretería, para construcción, para el hogar.
    No toca usos específicos (para agua fría, para gas, etc.).
    """
    if not text:
        return text
    out = str(text)
    for pattern in GENERIC_PARA_PATTERNS:
        out = re.sub(pattern, "", out, flags=re.IGNORECASE)
    return " ".join(out.split())


# ========= Normalización semi-técnica de unidades =========

def normalize_units_semi_technical(text: str) -> str:
    """
    Normaliza unidades a estándar semi-técnico:
    - 'litros por minuto', 'Litros por Minuto', 'Lts/min' -> 'L/min'
    - 'metros' (después de número) -> 'm'
    - 'hp', 'Hp' -> 'HP' (con espacio después del número)
    """
    if not text:
        return text

    out = text

    # Variantes de litros por minuto -> L/min
    out = re.sub(r"[Ll]itros\s+por\s+minuto", "L/min", out)
    out = re.sub(r"[Ll]itros\s*/\s*minuto", "L/min", out)
    out = re.sub(r"[Ll]itros\s+minuto", "L/min", out)
    out = re.sub(r"[Ll]ts?\.?\s*/\s*min", "L/min", out)
    out = re.sub(r"L\s*/\s*minuto", "L/min", out, flags=re.IGNORECASE)
    out = re.sub(r"[lL]\s*/\s*min\b", "L/min", out)

    # metros -> m (número + "metros")
    out = re.sub(r"(\d+)\s*[Mm]etros\b", r"\1 m", out)

    # 'm altura' -> 'm'
    out = re.sub(r"m\s+[Aa]ltura", "m", out)

    # HP en mayúsculas y con espacio
    out = re.sub(r"(\d+\/\d+)\s*[Hh][Pp]\b", r"\1 HP", out)
    out = re.sub(r"(\d+(?:\.\d+)?)\s*[Hh][Pp]\b", r"\1 HP", out)

    # Limpiar espacios dobles
    out = " ".join(out.split())
    return out


# =========================
#   VALIDATION HELPERS
# =========================

def quick_validation_rules(original_title: str, generated_title: str) -> list:
    """
    Fast rule-based validation before AI validator.
    Returns list of issues found.
    """
    issues = []
    
    if not original_title or not generated_title:
        return issues
    
    # Rule 1: Check for problematic "para X" additions
    # These are generic phrases that shouldn't be added unless in original
    problematic_para = [
        'para agua sucia', 'para agua limpia',
        'para sellado de roscas', 'para sellado',
        'para drenajes y tuberías', 'para drenajes',
        'para construcción', 'para plomería',
        'para tubería', 'para ferretería'
    ]
    
    for phrase in problematic_para:
        if phrase in generated_title.lower():
            # Check if it's in original (accounting for abbreviations)
            orig_upper = original_title.upper()
            # Check common abbreviations
            abbrev_map = {
                'para agua sucia': ['A.SUCIA', 'A SUCIA'],
                'para agua limpia': ['A.LIMP', 'A LIMP'],
                'para sellado': ['P/SELLADO', 'P SELLADO'],
            }
            
            found_in_original = False
            if phrase in original_title.lower():
                found_in_original = True
            elif phrase in abbrev_map:
                for abbrev in abbrev_map[phrase]:
                    if abbrev in orig_upper:
                        # If abbreviated, we should convert but NOT add "para"
                        issues.append(f"Incorrectly added 'para' with abbreviation: '{phrase}' (original has '{abbrev}')")
                        found_in_original = True
                        break
            
            if not found_in_original:
                issues.append(f"Added generic phrase not in original: '{phrase}'")
    
    # Rule 2: Check for invented technical terms
    for term in FORBIDDEN_TECH_TERMS:
        if term.lower() in generated_title.lower() and term.lower() not in original_title.lower():
            issues.append(f"Invented technical term: '{term}'")
    
    # Rule 3: Check critical measurements are preserved
    measurements = re.findall(r'\d+(?:/\d+)?(?:\s*(?:mm|cm|m|plg|pulgada|Hp|HP|L/min|W))', original_title)
    for measure in measurements:
        # Normalize for comparison
        measure_normalized = measure.replace('Hp', 'HP').replace('hp', 'HP')
        gen_normalized = generated_title.replace('Hp', 'HP').replace('hp', 'HP')
        
        if measure_normalized not in gen_normalized:
            issues.append(f"Missing critical measurement: '{measure}'")
    
    return issues


def validate_with_agent(original_title: str, generated_title: str, api_key: str) -> dict:
    """
    Second AI agent that validates and corrects the first agent's output.
    Returns: dict with validation results
    """
    
    validation_prompt = f"""Eres un agente de control de calidad. Tu trabajo es validar y corregir títulos de productos generados por otro sistema.

TÍTULO ORIGINAL DEL ERP: {original_title}
TÍTULO GENERADO: {generated_title}

REGLAS ESTRICTAS DE VALIDACIÓN:

1. REGLA CRÍTICA - Conversión de abreviaciones vs "para":
   - Si el original dice "A.SUCIA" o "A SUCIA" → convertir a "Agua Sucia" (SIN agregar "para")
   - Si el original dice "A.LIMP" o "A LIMP" → convertir a "Agua Limpia" (SIN agregar "para")
   - Si el original dice "P/" → convertir a "para"
   - Si el original dice "C/" → convertir a "con"
   - NUNCA agregues "para" antes de una abreviación convertida a menos que el original tenga "P/"

2. REGLA CRÍTICA - Frases genéricas:
   - NUNCA agregues "para sellado de roscas" a menos que esté explícito en el original
   - NUNCA agregues "para drenajes y tuberías" a menos que esté explícito
   - NUNCA agregues contexto genérico que no esté en el original

3. Especificaciones técnicas:
   - TODA especificación en el título generado debe existir en el original
   - NO inventes características técnicas
   - Mantén medidas exactas (HP, plg, mm, cm, m, L/min)

4. Frases "para X" solo si:
   - Están explícitas en el original, O
   - Son conversión directa de "P/" en el original

EJEMPLOS DE ERRORES COMUNES A CORREGIR:

❌ MAL:
Original: "BOMBA SUM A.SUCIA 1 1/2HP"
Generado: "Bomba Sumergible para Agua Sucia 1 1/2 HP"
Problema: Agregó "para" cuando el original solo tiene "A.SUCIA"

✅ BIEN:
Original: "BOMBA SUM A.SUCIA 1 1/2HP"
Corregido: "Bomba Sumergible Agua Sucia 1 1/2 HP"

❌ MAL:
Original: "CINTA TEFLON 1/2X7M"
Generado: "Cinta de Teflón 1/2 plg x 7 m para sellado de roscas"
Problema: Agregó "para sellado de roscas" que no está en original

✅ BIEN:
Original: "CINTA TEFLON 1/2X7M"
Corregido: "Cinta de Teflón 1/2 plg x 7 m"

ANALIZA:
1. Compara palabra por palabra el título generado vs original
2. Identifica cada adición que no esté en el original
3. Para cada adición pregunta: ¿Es técnicamente necesaria o es fluff genérico?
4. Corrige removiendo frases genéricas innecesarias

RESPONDE SOLO CON JSON VÁLIDO:
{{
    "is_valid": true/false,
    "corrected_title": "versión corregida del título",
    "issues_found": ["lista de problemas encontrados"],
    "removed_phrases": ["frases genéricas removidas"],
    "confidence": "high/medium/low"
}}"""

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            messages=[{"role": "user", "content": validation_prompt}]
        )
        
        response_text = response.content[0].text.strip()
        response_text = response_text.replace("```json", "").replace("```", "").strip()
        
        result = json.loads(response_text)
        return result
        
    except Exception as e:
        return {
            "is_valid": False,
            "corrected_title": generated_title,
            "issues_found": [f"Validation error: {str(e)}"],
            "removed_phrases": [],
            "confidence": "low"
        }


# =========================
#   BATCH PROCESSING
# =========================

def process_batch_with_validation(
    products_batch: list,
    nomenclature_pattern: str,
    transformations: dict,
    api_key: str,
    enable_ai_validation: bool = True
) -> list:
    """
    Process a batch of products (up to 50) in a single API call.
    Then validate each result.
    
    Returns: list of results with validation metadata
    """
    
    if not products_batch:
        return []
    
    # Build batch prompt
    products_json = []
    for p in products_batch:
        products_json.append({
            "titulo": p["titulo_sistema_existente"],
            "departamento": p["departamento"],
            "familia": p["familia"],
            "categoria": p["categoria"]
        })
    
    batch_prompt = f"""Eres experto en crear títulos de productos para catálogos de retail en Guatemala.

Vas a procesar {len(products_batch)} productos siguiendo el MISMO patrón de nomenclatura.

PATRÓN DE NOMENCLATURA A SEGUIR:
{nomenclature_pattern}

TRANSFORMACIONES CONSISTENTES:
{json.dumps(transformations, indent=2, ensure_ascii=False)}

REGLAS CRÍTICAS (OBLIGATORIAS):

1. ABREVIACIONES - NO agregues "para":
   - A.SUCIA / A SUCIA → "Agua Sucia" (NO "para Agua Sucia")
   - A.LIMP / A LIMP → "Agua Limpia" (NO "para Agua Limpia")
   - Solo usa "para" si el original tiene "P/" explícitamente

2. NUNCA agregues frases genéricas:
   - ❌ "para sellado de roscas"
   - ❌ "para drenajes y tuberías"
   - ❌ "para construcción"
   Solo agrega "para X" si:
   - Es conversión de "P/" en el original, O
   - El uso es específico (para gas, para agua fría, para exterior)

3. NUNCA incluyas marcas en los títulos

4. NUNCA inventes características técnicas que no estén en el original
   (No agregues: penetrante, hidráulico, neumático, dieléctrico, etc.)

5. Mantén medidas exactas: HP (mayúsculas), plg, mm, cm, m, L/min

6. Usa español natural con preposiciones (de, con, x) cuando corresponda

PRODUCTOS A PROCESAR:
{json.dumps(products_json, indent=2, ensure_ascii=False)}

RESPONDE SOLO CON UN JSON ARRAY con {len(products_batch)} objetos (mismo orden que recibiste):
[
  {{
    "titulo_sistema": "max 40 caracteres",
    "titulo_etiqueta": "max 36 caracteres",
    "titulo_seo": "50-70 caracteres optimizado para búsqueda"
  }},
  ...
]"""

    try:
        client = Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": batch_prompt}]
        )
        
        response_text = message.content[0].text.strip()
        response_text = response_text.replace("```json", "").replace("```", "").strip()
        
        batch_results = json.loads(response_text)
        
        if not isinstance(batch_results, list):
            raise ValueError("Expected JSON array from batch processing")
        
        # Process each result
        final_results = []
        
        for idx, (product, result) in enumerate(zip(products_batch, batch_results)):
            
            # Apply post-processing
            brand = product.get("marca", "").strip()
            
            for key in ["titulo_sistema", "titulo_etiqueta", "titulo_seo"]:
                if key in result and isinstance(result[key], str):
                    t = result[key]
                    
                    # 1) Transformations
                    t = apply_transformations(t, transformations)
                    
                    # 2) Remove brand
                    t = remove_brand_occurrences(t, brand)
                    
                    # 3) Fix caps
                    t = de_shout(t)
                    
                    # 4) Remove forbidden terms
                    t = remove_forbidden_terms(t)
                    
                    # 5) Remove generic phrases
                    t = remove_generic_para_phrases(t)
                    
                    # 6) Normalize spaces
                    result[key] = " ".join(t.split())
            
            # Validation
            original_title = product["titulo_sistema_existente"]
            generated_seo = result.get("titulo_seo", "")
            
            # Quick rules validation (free & fast)
            quick_issues = quick_validation_rules(original_title, generated_seo)
            
            validation_metadata = {
                "validation_method": "none",
                "validation_status": "passed",
                "issues_found": [],
                "corrected": False
            }
            
            # AI validation if quick check found issues and enabled
            if quick_issues and enable_ai_validation:
                ai_validation = validate_with_agent(original_title, generated_seo, api_key)
                
                if not ai_validation.get("is_valid", True):
                    # Use corrected version
                    result["titulo_seo"] = ai_validation.get("corrected_title", generated_seo)
                    validation_metadata["corrected"] = True
                    validation_metadata["validation_status"] = "corrected"
                else:
                    validation_metadata["validation_status"] = "passed_with_warnings"
                
                validation_metadata["validation_method"] = "ai_validated"
                validation_metadata["issues_found"] = quick_issues + ai_validation.get("issues_found", [])
                
            elif quick_issues:
                # Just flag the issues without AI correction
                validation_metadata["validation_method"] = "rules_only"
                validation_metadata["validation_status"] = "warnings"
                validation_metadata["issues_found"] = quick_issues
            
            result["validation"] = validation_metadata
            final_results.append(result)
        
        return final_results
        
    except Exception as e:
        st.error(f"Error in batch processing: {e}")
        return []


# =========================
#   COVERAGE ANALYSIS
# =========================

def analyze_coverage(products_df: pd.DataFrame, nomenclature_df: pd.DataFrame) -> dict:
    """
    Analyze which products have matching nomenclature rules.
    Returns statistics and list of uncovered categories.
    """
    covered = 0
    uncovered_categories = {}
    
    for _, row in products_df.iterrows():
        pattern = find_pattern_row(
            nomenclature_df,
            row.get('departamento', ''),
            row.get('familia', ''),
            row.get('categoria', '')
        )
        if pattern is not None:
            covered += 1
        else:
            cat_key = f"{row.get('departamento', 'N/A')}/{row.get('familia', 'N/A')}/{row.get('categoria', 'N/A')}"
            if cat_key not in uncovered_categories:
                uncovered_categories[cat_key] = 0
            uncovered_categories[cat_key] += 1
    
    total = len(products_df)
    coverage_pct = (covered / total * 100) if total > 0 else 0
    
    return {
        'total': total,
        'covered': covered,
        'uncovered': total - covered,
        'coverage_percent': coverage_pct,
        'uncovered_categories': uncovered_categories
    }


# =========================
#   MAIN UI
# =========================

st.title("📝 Generador de Títulos de Catálogo - Cemaco")
st.markdown("### Sistema con validación de dos agentes y procesamiento por lotes")

# Sidebar
with st.sidebar:
    st.header("Configuración")

    # API Key
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

    # Nomenclatura
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

    # Validation settings
    st.subheader("2. Configuración de Validación")
    enable_ai_validation = st.checkbox(
        "Activar validación con IA",
        value=True,
        help="Usa un segundo agente de IA para validar y corregir títulos (duplica llamadas API pero mejora calidad)"
    )
    
    batch_size = st.slider(
        "Tamaño de lote",
        min_value=10,
        max_value=50,
        value=25,
        step=5,
        help="Cuántos productos procesar por llamada API (mayor = más rápido pero menos flexible)"
    )

    st.markdown("---")

    # Memoria de transformaciones
    st.subheader("3. Memoria de Transformaciones")
    st.caption("Mantén consistencia en abreviaciones (ej: pulgadas -> plg)")

    col1, col2 = st.columns(2)
    with col1:
        original = st.text_input("Original", key="trans_orig")
    with col2:
        replacement = st.text_input("Reemplazo", key="trans_repl")

    if st.button("➕ Agregar Transformación"):
        if original and replacement:
            st.session_state.transformation_memory[original] = replacement
            st.success(f"Agregado: {original} → {replacement}")

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

    # Validation stats
    if st.session_state.validation_stats['total_processed'] > 0:
        st.subheader("📊 Estadísticas de Validación")
        stats = st.session_state.validation_stats
        st.metric("Total Procesados", stats['total_processed'])
        st.metric("Aprobados", stats['validation_passed'])
        st.metric("Corregidos", stats['validation_corrected'])
        if stats['validation_failed'] > 0:
            st.metric("Fallidos", stats['validation_failed'])


# Main
if st.session_state.nomenclature_df is None:
    st.info("👈 Por favor carga el archivo de nomenclatura en el panel lateral para comenzar.")
else:
    df = st.session_state.nomenclature_df

    tab1, tab2 = st.tabs([
        "📦 Procesamiento por Lote",
        "🔍 Análisis de Cobertura"
    ])

    # -------------------------
    # TAB 1: Batch Processing
    # -------------------------
    with tab1:
        st.markdown("### 📋 Procesamiento por Lote con Validación")
        st.caption("Carga tu archivo CSV/Excel con productos para procesar")
        
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
                
                # Validate columns
                required_cols = ['titulo_sistema', 'departamento', 'familia', 'categoria']
                missing_cols = [col for col in required_cols if col not in batch_df.columns]
                
                if missing_cols:
                    st.error(f"❌ Faltan columnas requeridas: {', '.join(missing_cols)}")
                    st.info("**Columnas encontradas:** " + ", ".join(batch_df.columns.tolist()))
                    st.info("**Columnas requeridas:** " + ", ".join(required_cols))
                else:
                    st.success(f"✅ Archivo cargado: {len(batch_df)} productos")
                    
                    # Preview
                    st.dataframe(batch_df.head(10))
                    if len(batch_df) > 10:
                        st.caption(f"Mostrando las primeras 10 filas de {len(batch_df)} productos")
                    
                    # Processing options
                    col1, col2 = st.columns(2)
                    with col1:
                        want_sistema = st.checkbox("Generar Título Sistema", value=True)
                        want_etiqueta = st.checkbox("Generar Título Etiqueta", value=True)
                    with col2:
                        want_seo = st.checkbox("Generar Título SEO", value=True)
                        save_checkpoints = st.checkbox("Guardar checkpoints cada 500", value=True)
                    
                    st.markdown("---")
                    
                    if st.button("🚀 Procesar Lote", type="primary"):
                        
                        # Get API key
                        api_key = None
                        try:
                            if "ANTHROPIC_API_KEY" in st.secrets:
                                api_key = st.secrets["ANTHROPIC_API_KEY"]
                        except:
                            pass
                        if not api_key:
                            api_key = st.session_state.api_key
                        
                        if not api_key:
                            st.error("❌ API key no configurada")
                        else:
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            results = []
                            failed_products = []
                            
                            # Reset validation stats
                            st.session_state.validation_stats = {
                                'total_processed': 0,
                                'validation_passed': 0,
                                'validation_corrected': 0,
                                'validation_failed': 0
                            }
                            
                            # Process in batches
                            total_products = len(batch_df)
                            
                            for batch_start in range(0, total_products, batch_size):
                                batch_end = min(batch_start + batch_size, total_products)
                                batch_rows = batch_df.iloc[batch_start:batch_end]
                                
                                status_text.text(f"Procesando lote {batch_start+1}-{batch_end} de {total_products}...")
                                
                                # Prepare batch
                                products_batch = []
                                batch_patterns = []
                                
                                for idx, row in batch_rows.iterrows():
                                    pattern = find_pattern_row(
                                        df,
                                        row['departamento'],
                                        row['familia'],
                                        row['categoria']
                                    )
                                    
                                    if pattern is None:
                                        failed_products.append({
                                            'sku': row.get('SKU', 'N/A'),
                                            'titulo': row['titulo_sistema'],
                                            'categoria': row['categoria'],
                                            'reason': 'No matching nomenclature rule'
                                        })
                                        continue
                                    
                                    products_batch.append({
                                        "titulo_sistema_existente": row['titulo_sistema'],
                                        "departamento": row['departamento'],
                                        "familia": row['familia'],
                                        "categoria": row['categoria'],
                                        "marca": "",
                                        "row_data": row
                                    })
                                    batch_patterns.append(pattern['Nomenclatura sugerida'])
                                
                                if not products_batch:
                                    continue
                                
                                # Use first pattern (they should all be similar for same category)
                                nomenclatura = batch_patterns[0]
                                
                                # Process batch
                                try:
                                    batch_results = process_batch_with_validation(
                                        products_batch,
                                        nomenclatura,
                                        st.session_state.transformation_memory,
                                        api_key,
                                        enable_ai_validation
                                    )
                                    
                                    # Collect results
                                    for product, result in zip(products_batch, batch_results):
                                        row = product['row_data']
                                        
                                        row_out = {
                                            'titulo_sistema_original': row['titulo_sistema'],
                                            'departamento': row['departamento'],
                                            'familia': row['familia'],
                                            'categoria': row['categoria']
                                        }
                                        
                                        if 'SKU' in batch_df.columns:
                                            row_out['SKU'] = row['SKU']
                                        
                                        if want_sistema and 'titulo_sistema' in result:
                                            row_out['titulo_sistema_generado'] = result['titulo_sistema']
                                        if want_etiqueta and 'titulo_etiqueta' in result:
                                            row_out['titulo_etiqueta'] = result['titulo_etiqueta']
                                        if want_seo and 'titulo_seo' in result:
                                            row_out['titulo_seo'] = result['titulo_seo']
                                        
                                        # Add validation metadata
                                        if 'validation' in result:
                                            val = result['validation']
                                            row_out['validation_status'] = val.get('validation_status', 'unknown')
                                            if val.get('issues_found'):
                                                row_out['validation_issues'] = '; '.join(val['issues_found'])
                                            row_out['corrected'] = val.get('corrected', False)
                                            
                                            # Update stats
                                            st.session_state.validation_stats['total_processed'] += 1
                                            if val.get('validation_status') == 'passed':
                                                st.session_state.validation_stats['validation_passed'] += 1
                                            elif val.get('corrected'):
                                                st.session_state.validation_stats['validation_corrected'] += 1
                                        
                                        results.append(row_out)
                                    
                                    # Small delay to avoid rate limits
                                    time.sleep(0.5)
                                    
                                except Exception as e:
                                    st.warning(f"Error procesando lote {batch_start}-{batch_end}: {e}")
                                    for product in products_batch:
                                        failed_products.append({
                                            'sku': product['row_data'].get('SKU', 'N/A'),
                                            'titulo': product['titulo_sistema_existente'],
                                            'reason': str(e)
                                        })
                                
                                # Update progress
                                progress_bar.progress(batch_end / total_products)
                                
                                # Save checkpoint
                                if save_checkpoints and len(results) > 0 and len(results) % 500 == 0:
                                    checkpoint_df = pd.DataFrame(results)
                                    checkpoint_df.to_csv(f'checkpoint_{len(results)}.csv', index=False)
                                    st.info(f"💾 Checkpoint guardado: {len(results)} productos")
                            
                            status_text.empty()
                            progress_bar.progress(1.0)
                            
                            # Show results
                            if results:
                                st.success(f"✅ Procesados {len(results)} títulos")
                                
                                # Show validation summary
                                stats = st.session_state.validation_stats
                                col1, col2, col3 = st.columns(3)
                                with col1:
                                    st.metric("Aprobados", stats['validation_passed'])
                                with col2:
                                    st.metric("Corregidos", stats['validation_corrected'])
                                with col3:
                                    if failed_products:
                                        st.metric("Fallidos", len(failed_products))
                                
                                results_df = pd.DataFrame(results)
                                
                                # Filter to show corrected ones
                                if 'corrected' in results_df.columns:
                                    corrected_df = results_df[results_df['corrected'] == True]
                                    if len(corrected_df) > 0:
                                        st.markdown("### 🔧 Títulos Corregidos por Validador")
                                        st.dataframe(corrected_df[['titulo_sistema_original', 'titulo_seo', 'validation_issues']])
                                
                                st.markdown("### 📋 Todos los Resultados")
                                st.dataframe(results_df)
                                
                                # Download button
                                csv = results_df.to_csv(index=False, encoding='utf-8-sig')
                                st.download_button(
                                    label="📥 Descargar Resultados",
                                    data=csv,
                                    file_name=f"batch_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                    mime="text/csv"
                                )
                                
                                # Show failed products if any
                                if failed_products:
                                    st.markdown("### ⚠️ Productos No Procesados")
                                    failed_df = pd.DataFrame(failed_products)
                                    st.dataframe(failed_df)
                                    
                                    csv_failed = failed_df.to_csv(index=False, encoding='utf-8-sig')
                                    st.download_button(
                                        label="📥 Descargar Productos Fallidos",
                                        data=csv_failed,
                                        file_name=f"failed_products_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                        mime="text/csv"
                                    )
                            else:
                                st.warning("⚠️ No se generaron resultados")
                
            except Exception as e:
                st.error(f"❌ Error al leer el archivo: {e}")
    
    # -------------------------
    # TAB 2: Coverage Analysis
    # -------------------------
    with tab2:
        st.markdown("### 🔍 Análisis de Cobertura de Nomenclatura")
        st.caption("Verifica qué productos tienen reglas de nomenclatura definidas")
        
        uploaded_analysis = st.file_uploader(
            "Archivo CSV o Excel para analizar",
            type=['csv', 'xlsx', 'xls'],
            key="analysis_upload"
        )
        
        if uploaded_analysis:
            try:
                file_extension = uploaded_analysis.name.split('.')[-1].lower()
                if file_extension == 'csv':
                    analysis_df = pd.read_csv(uploaded_analysis, encoding='utf-8-sig')
                else:
                    analysis_df = pd.read_excel(uploaded_analysis)
                
                required_cols = ['departamento', 'familia', 'categoria']
                missing_cols = [col for col in required_cols if col not in analysis_df.columns]
                
                if missing_cols:
                    st.error(f"❌ Faltan columnas: {', '.join(missing_cols)}")
                else:
                    if st.button("🔍 Analizar Cobertura"):
                        with st.spinner("Analizando..."):
                            coverage = analyze_coverage(analysis_df, df)
                        
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Total Productos", coverage['total'])
                        with col2:
                            st.metric("Con Nomenclatura", coverage['covered'])
                        with col3:
                            st.metric("Cobertura", f"{coverage['coverage_percent']:.1f}%")
                        
                        if coverage['uncovered'] > 0:
                            st.warning(f"⚠️ {coverage['uncovered']} productos sin reglas de nomenclatura")
                            
                            st.markdown("### Categorías Sin Cobertura")
                            uncovered_list = []
                            for cat, count in coverage['uncovered_categories'].items():
                                uncovered_list.append({
                                    'Categoría': cat,
                                    'Productos Afectados': count
                                })
                            
                            uncovered_df = pd.DataFrame(uncovered_list)
                            uncovered_df = uncovered_df.sort_values('Productos Afectados', ascending=False)
                            st.dataframe(uncovered_df)
                            
                            csv_uncovered = uncovered_df.to_csv(index=False, encoding='utf-8-sig')
                            st.download_button(
                                label="📥 Descargar Categorías Sin Cobertura",
                                data=csv_uncovered,
                                file_name=f"uncovered_categories_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv"
                            )
                        else:
                            st.success("✅ Todos los productos tienen nomenclatura definida")
            
            except Exception as e:
                st.error(f"❌ Error: {e}")

# Footer
st.markdown("---")
st.caption("Generador de Títulos de Catálogo con Sistema de Validación de Dos Agentes -by JC - Cemaco © 2025")