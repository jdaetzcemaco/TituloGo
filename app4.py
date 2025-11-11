import streamlit as st
import pandas as pd
import json
from datetime import datetime
import anthropic
import os

# Page config
st.set_page_config(
    page_title="Generador de Títulos - Cemaco",
    page_icon="📝",
    layout="wide"
)

# Initialize session state
if 'nomenclature_df' not in st.session_state:
    st.session_state.nomenclature_df = None
if 'transformation_memory' not in st.session_state:
    st.session_state.transformation_memory = {}
if 'generated_titles' not in st.session_state:
    st.session_state.generated_titles = []
if 'api_key' not in st.session_state:
    st.session_state.api_key = ""

# Helper function to load nomenclature
def load_nomenclature(file):
    try:
        df = pd.read_csv(file, encoding='utf-8-sig')
        return df
    except Exception as e:
        st.error(f"Error cargando nomenclatura: {e}")
        return None

# Helper function to apply transformations consistently
def apply_transformations(text, transformations):
    """Apply saved transformations to maintain consistency"""
    result = text
    for original, replacement in transformations.items():
        result = result.replace(original, replacement)
    return result

# Function to generate titles using Claude
def generate_titles(product_info, nomenclature_pattern, transformations):
    """Generate 3 title variants using Claude API"""
    
    # Get API key from secrets or session state
    api_key = None
    try:
        if "ANTHROPIC_API_KEY" in st.secrets:
            api_key = st.secrets["ANTHROPIC_API_KEY"]
    except:
        pass
    
    if not api_key and 'api_key' in st.session_state:
        api_key = st.session_state.api_key
    
    if not api_key:
        st.error("❌ API key no configurada")
        return None
    
    client = anthropic.Anthropic(api_key=api_key)
    
    prompt = f"""Eres un experto en crear títulos de productos para catálogos de retail en Guatemala.

INFORMACIÓN DEL PRODUCTO:
{json.dumps(product_info, indent=2, ensure_ascii=False)}

PATRÓN DE NOMENCLATURA A SEGUIR:
{nomenclature_pattern}

TRANSFORMACIONES CONSISTENTES A APLICAR:
{json.dumps(transformations, indent=2, ensure_ascii=False)}

INSTRUCCIONES:
1. Genera 3 variantes de título siguiendo las reglas:
   
   a) TÍTULO SISTEMA (40 caracteres máximo):
      - Conciso, claro, sin marca si es genérico
      - Sigue el patrón de nomenclatura exactamente
      - Usa abreviaciones estándar en español
      - NO incluyas símbolos innecesarios
   
   b) TÍTULO ETIQUETA (36 caracteres máximo):
      - Si el título sistema cabe en 36 caracteres, usa el mismo
      - Si no, crea versión más corta manteniendo información crítica
      - Mismas reglas que título sistema
   
   c) TÍTULO SEO (para e-commerce):
      - Más descriptivo, optimizado para búsqueda en cemaco.com
      - Incluye palabras clave relevantes en español
      - Puede incluir marca si aplica
      - Sin límite estricto pero mantén entre 50-70 caracteres idealmente

2. Aplica todas las transformaciones de memoria proporcionadas
3. Mantén consistencia con abreviaciones guatemaltecas estándar
4. NO uses símbolos como ® o ™
5. Usa español de Guatemala

RESPONDE SOLO CON UN JSON VÁLIDO en este formato exacto:
{{
  "titulo_sistema": "...",
  "longitud_sistema": 40,
  "titulo_etiqueta": "...",
  "longitud_etiqueta": 36,
  "titulo_seo": "...",
  "longitud_seo": 65,
  "transformaciones_aplicadas": ["blanco→bco", "pulgadas→plg"],
  "cumple_nomenclatura": true,
  "notas": "Explicación breve si hay algo relevante"
}}

NO INCLUYAS NADA MÁS QUE EL JSON. NO uses bloques de código markdown.
"""

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
        return result
    except Exception as e:
        st.error(f"Error generando títulos: {e}")
        return None

# Main UI
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
    except:
        pass
    
    if not api_key_configured:
        if 'api_key' not in st.session_state:
            st.session_state.api_key = ""
        
        api_key_input = st.text_input("Anthropic API Key", 
                                       value=st.session_state.api_key,
                                       type="password",
                                       help="Obtén tu API key en console.anthropic.com")
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
    
    # Upload transformations file
    uploaded_transformations = st.file_uploader(
        "📤 Cargar Transformaciones Guardadas",
        type=['json'],
        key="upload_trans",
        help="Sube un archivo JSON con transformaciones previamente guardadas"
    )
    
    if uploaded_transformations:
        try:
            trans_data = json.load(uploaded_transformations)
            st.session_state.transformation_memory = trans_data
            st.success(f"✅ {len(trans_data)} transformaciones cargadas")
        except Exception as e:
            st.error(f"❌ Error al cargar transformaciones: {e}")
    
    # Load default transformations button
    if st.button("🔄 Cargar Transformaciones Comunes", help="Carga un set de transformaciones típicas"):
        default_transformations = {
            "blanco": "bco",
            "negro": "neg",
            "gris": "grs",
            "pulgadas": "plg",
            "pulgada": "plg",
            "centímetros": "cm",
            "centimetros": "cm",
            "metros": "m",
            "kilogramos": "kg",
            "gramos": "gr",
            "litros": "L",
            "mililitros": "ml",
            "acero inoxidable": "acero inox",
            "galvanizado": "galv",
            "cromado": "crom"
        }
        st.session_state.transformation_memory.update(default_transformations)
        st.success(f"✅ {len(default_transformations)} transformaciones comunes agregadas")
        st.rerun()
    
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
            st.rerun()
    
    # Display current transformations
    if st.session_state.transformation_memory:
        st.markdown("**Transformaciones Activas:**")
        for orig, repl in st.session_state.transformation_memory.items():
            col1, col2 = st.columns([3, 1])
            with col1:
                st.text(f"{orig} → {repl}")
            with col2:
                if st.button("🗑️", key=f"del_{orig}"):
                    del st.session_state.transformation_memory[orig]
                    st.rerun()
        
        # Download transformations button
        trans_json = json.dumps(st.session_state.transformation_memory, indent=2, ensure_ascii=False)
        st.download_button(
            label="📥 Descargar Transformaciones",
            data=trans_json,
            file_name=f"transformaciones_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            help="Guarda estas transformaciones para usarlas en el futuro"
        )
    else:
        st.info("👆 Agrega transformaciones o carga un archivo guardado")
    
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
    # Create tabs for different modes
    tab1, tab2, tab3 = st.tabs(["🔨 Crear Título Individual", "✏️ Ya Tengo Título Sistema", "📦 Procesamiento por Lote"])
    
    # TAB 1: Individual title creation
    with tab1:
        st.subheader("Crear Nuevo Título")
        
        # Selectors for hierarchy
        df = st.session_state.nomenclature_df
        
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
        
        # Get nomenclature pattern for selection
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
            
            # Input form for product attributes
            st.subheader("Información del Producto")
            
            product_name = st.text_input("Nombre del Producto", 
                                        help="Nombre base del producto")
            
            col1, col2 = st.columns(2)
            with col1:
                tipo = st.text_input("Tipo", help="Ej: Tornillo, Cable, Bomba")
                material = st.text_input("Material", help="Ej: Acero, PVC, Cobre")
                medidas = st.text_input("Dimensiones", help="Ej: 1/2 x 6m, 10x20cm")
            
            with col2:
                color = st.text_input("Color", help="Ej: Blanco, Negro, Gris")
                marca = st.text_input("Marca (opcional)", help="Solo si es relevante")
                otros = st.text_area("Otros atributos", help="Características adicionales")
            
            # Generate button
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
                            # Display results
                            st.success("✅ Títulos Generados Exitosamente")
                            
                            col1, col2, col3 = st.columns(3)
                            
                            with col1:
                                st.markdown("### 📋 Título Sistema")
                                chars_sistema = len(result['titulo_sistema'])
                                color_sistema = "green" if chars_sistema <= 40 else "red"
                                st.markdown(f"**{result['titulo_sistema']}**")
                                st.markdown(f"<span style='color:{color_sistema}'>Longitud: {chars_sistema}/40</span>", 
                                          unsafe_allow_html=True)
                            
                            with col2:
                                st.markdown("### 🏷️ Título Etiqueta")
                                chars_etiqueta = len(result['titulo_etiqueta'])
                                color_etiqueta = "green" if chars_etiqueta <= 36 else "red"
                                st.markdown(f"**{result['titulo_etiqueta']}**")
                                st.markdown(f"<span style='color:{color_etiqueta}'>Longitud: {chars_etiqueta}/36</span>", 
                                          unsafe_allow_html=True)
                            
                            with col3:
                                st.markdown("### 🌐 Título SEO")
                                chars_seo = len(result['titulo_seo'])
                                st.markdown(f"**{result['titulo_seo']}**")
                                st.markdown(f"Longitud: {chars_seo} caracteres")
                            
                            # Show transformations applied
                            if result.get('transformaciones_aplicadas'):
                                st.info(f"**Transformaciones aplicadas:** {', '.join(result['transformaciones_aplicadas'])}")
                            
                            # Save to history
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
    
    # TAB 2: Already have system title - generate label and SEO only
    with tab2:
        st.subheader("Ya Tengo el Título del Sistema")
        st.markdown("Genera únicamente los títulos de **Etiqueta** y **SEO** a partir de un título sistema existente")
        
        # Selectors for hierarchy
        col1, col2, col3 = st.columns(3)
        
        with col1:
            departamentos = sorted(df['Departamento'].unique())
            selected_dept_existing = st.selectbox("Departamento", options=departamentos, key="dept_existing")
        
        with col2:
            familias = sorted(df[df['Departamento'] == selected_dept_existing]['Familia'].unique())
            selected_familia_existing = st.selectbox("Familia", options=familias, key="familia_existing")
        
        with col3:
            categorias = sorted(df[
                (df['Departamento'] == selected_dept_existing) & 
                (df['Familia'] == selected_familia_existing)
            ]['Categoria'].unique())
            selected_categoria_existing = st.selectbox("Categoría", options=categorias, key="categoria_existing")
        
        # Get nomenclature pattern
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
            
            # Input for existing system title
            existing_title = st.text_area(
                "Título Sistema Existente",
                help="Pega aquí el título del sistema que ya tienes (máx 40 caracteres)",
                max_chars=50
            )
            
            if existing_title:
                chars_existing = len(existing_title)
                if chars_existing > 40:
                    st.warning(f"⚠️ El título tiene {chars_existing} caracteres (límite: 40)")
                else:
                    st.success(f"✅ Longitud: {chars_existing}/40 caracteres")
            
            # Generate button
            if st.button("🚀 Generar Etiqueta y SEO", type="primary", use_container_width=True, key="gen_existing"):
                if existing_title:
                    with st.spinner("Generando títulos de etiqueta y SEO..."):
                        product_info = {
                            "titulo_sistema_existente": existing_title,
                            "departamento": selected_dept_existing,
                            "familia": selected_familia_existing,
                            "categoria": selected_categoria_existing
                        }
                        
                        result = generate_titles(
                            product_info,
                            nomenclatura,
                            st.session_state.transformation_memory
                        )
                        
                        if result:
                            # Display results
                            st.success("✅ Títulos Generados Exitosamente")
                            
                            col1, col2, col3 = st.columns(3)
                            
                            with col1:
                                st.markdown("### 📋 Título Sistema (Original)")
                                st.markdown(f"**{existing_title}**")
                                st.markdown(f"Longitud: {len(existing_title)}/40")
                            
                            with col2:
                                st.markdown("### 🏷️ Título Etiqueta")
                                chars_etiqueta = len(result['titulo_etiqueta'])
                                color_etiqueta = "green" if chars_etiqueta <= 36 else "red"
                                st.markdown(f"**{result['titulo_etiqueta']}**")
                                st.markdown(f"<span style='color:{color_etiqueta}'>Longitud: {chars_etiqueta}/36</span>", 
                                          unsafe_allow_html=True)
                            
                            with col3:
                                st.markdown("### 🌐 Título SEO")
                                chars_seo = len(result['titulo_seo'])
                                st.markdown(f"**{result['titulo_seo']}**")
                                st.markdown(f"Longitud: {chars_seo} caracteres")
                            
                            # Show transformations applied
                            if result.get('transformaciones_aplicadas'):
                                st.info(f"**Transformaciones aplicadas:** {', '.join(result['transformaciones_aplicadas'])}")
                            
                            # Save to history
                            result_with_meta = {
                                "titulo_sistema": existing_title,
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
    
    # TAB 3: Batch processing
    with tab3:
        st.subheader("Procesamiento por Lote")
        st.markdown("Dos modos: **Simplificado** (solo títulos) o **Completo** (con categorías por fila)")
        
        # Mode selection
        mode = st.radio(
            "Modo de Procesamiento:",
            ["🎯 Simplificado - Una categoría para todos", "📋 Completo - Categorías individuales"],
            help="Simplificado: todos los títulos usan la misma categoría. Completo: cada título tiene su propia categoría en el CSV"
        )
        
        st.markdown("---")
        
        if mode == "🎯 Simplificado - Una categoría para todos":
            st.markdown("### 1️⃣ Selecciona la Categoría")
            st.caption("Todos los títulos que subas usarán esta categoría")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                departamentos_simple = sorted(df['Departamento'].unique())
                selected_dept_simple = st.selectbox("Departamento", options=departamentos_simple, key="dept_simple")
            
            with col2:
                familias_simple = sorted(df[df['Departamento'] == selected_dept_simple]['Familia'].unique())
                selected_familia_simple = st.selectbox("Familia", options=familias_simple, key="familia_simple")
            
            with col3:
                categorias_simple = sorted(df[
                    (df['Departamento'] == selected_dept_simple) & 
                    (df['Familia'] == selected_familia_simple)
                ]['Categoria'].unique())
                selected_categoria_simple = st.selectbox("Categoría", options=categorias_simple, key="categoria_simple")
            
            # Get nomenclature pattern
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
            st.caption("CSV o Excel con una columna llamada 'titulo_sistema' o 'titulos'")
            
            uploaded_simple = st.file_uploader(
                "Archivo con títulos",
                type=['csv', 'xlsx', 'xls'],
                key="simple_upload",
                help="Solo necesitas una columna con los títulos del sistema"
            )
            
            if uploaded_simple:
                # Read file based on extension
                file_extension = uploaded_simple.name.split('.')[-1].lower()
                
                try:
                    if file_extension == 'csv':
                        simple_df = pd.read_csv(uploaded_simple, encoding='utf-8-sig')
                    else:  # xlsx or xls
                        simple_df = pd.read_excel(uploaded_simple)
                    
                    # Find the titles column (flexible naming)
                    title_col = None
                    possible_names = ['titulo_sistema', 'titulos', 'titulo', 'títulos', 'título', 'title', 'titles']
                    
                    for col in simple_df.columns:
                        if col.lower().strip() in possible_names:
                            title_col = col
                            break
                    
                    if title_col is None:
                        st.error("❌ No se encontró una columna de títulos. Busqué: " + ", ".join(possible_names))
                        st.info("**Columnas encontradas:** " + ", ".join(simple_df.columns.tolist()))
                    else:
                        # Show preview
                        st.success(f"✅ {len(simple_df)} títulos cargados desde columna '{title_col}'")
                        st.dataframe(simple_df[[title_col]].head(10))
                        if len(simple_df) > 10:
                            st.caption(f"Mostrando las primeras 10 de {len(simple_df)} filas")
                        
                        # Process button
                        if st.button("🚀 Procesar Todos", type="primary", key="process_simple"):
                            if not pattern_row.empty:
                                progress_bar = st.progress(0)
                                status_text = st.empty()
                                results = []
                                
                                for idx, row in simple_df.iterrows():
                                    titulo = str(row[title_col]).strip()
                                    if titulo and titulo != 'nan':
                                        status_text.text(f"Procesando {idx + 1} de {len(simple_df)}: {titulo[:40]}...")
                                        
                                        product_info = {
                                            "titulo_sistema_existente": titulo,
                                            "departamento": selected_dept_simple,
                                            "familia": selected_familia_simple,
                                            "categoria": selected_categoria_simple
                                        }
                                        
                                        result = generate_titles(
                                            product_info,
                                            nomenclatura,
                                            st.session_state.transformation_memory
                                        )
                                        
                                        if result:
                                            results.append({
                                                'titulo_sistema_original': titulo,
                                                'titulo_etiqueta': result['titulo_etiqueta'],
                                                'titulo_seo': result['titulo_seo'],
                                                'departamento': selected_dept_simple,
                                                'familia': selected_familia_simple,
                                                'categoria': selected_categoria_simple
                                            })
                                    
                                    progress_bar.progress((idx + 1) / len(simple_df))
                                
                                status_text.empty()
                                
                                if results:
                                    st.success(f"✅ Procesados {len(results)} títulos exitosamente")
                                    results_df = pd.DataFrame(results)
                                    st.dataframe(results_df)
                                    
                                    # Download button
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
        
        else:  # Modo completo (original)
            st.markdown("### 📋 Modo Completo")
            st.caption("Tu archivo debe incluir: titulo_sistema, departamento, familia, categoria")
            
            # Add filters for batch processing
            st.markdown("### 🔍 Filtros (Opcional)")
            st.caption("Procesa solo productos de categorías específicas")
            
            col1, col2, col3, col4 = st.columns([3, 3, 3, 1])
            
            with col1:
                departamentos_batch = ["Todos"] + sorted(df['Departamento'].unique().tolist())
                selected_dept_batch = st.selectbox("Departamento", options=departamentos_batch, key="dept_batch")
            
            with col2:
                if selected_dept_batch != "Todos":
                    familias_batch = ["Todos"] + sorted(df[df['Departamento'] == selected_dept_batch]['Familia'].unique().tolist())
                else:
                    familias_batch = ["Todos"]
                selected_familia_batch = st.selectbox("Familia", options=familias_batch, key="familia_batch")
            
            with col3:
                if selected_dept_batch != "Todos" and selected_familia_batch != "Todos":
                    categorias_batch = ["Todos"] + sorted(df[
                        (df['Departamento'] == selected_dept_batch) & 
                        (df['Familia'] == selected_familia_batch)
                    ]['Categoria'].unique().tolist())
                else:
                    categorias_batch = ["Todos"]
                selected_categoria_batch = st.selectbox("Categoría", options=categorias_batch, key="categoria_batch")
            
            with col4:
                st.markdown("&nbsp;")
                if st.button("🔄", help="Resetear filtros"):
                    st.rerun()
            
            st.markdown("---")
        
        uploaded_batch = st.file_uploader(
            "Archivo CSV o Excel con títulos y categorías",
            type=['csv', 'xlsx', 'xls'],
            key="batch_upload",
            help="Debe incluir columnas: titulo_sistema, departamento, familia, categoria"
        )
        
        if uploaded_batch:
            # Read file based on extension
            file_extension = uploaded_batch.name.split('.')[-1].lower()
            
            try:
                if file_extension == 'csv':
                    batch_df = pd.read_csv(uploaded_batch, encoding='utf-8-sig')
                else:  # xlsx or xls
                    batch_df = pd.read_excel(uploaded_batch)
                
                # First, validate required columns
                required_cols = ['titulo_sistema', 'departamento', 'familia', 'categoria']
                missing_cols = [col for col in required_cols if col not in batch_df.columns]
                
                if missing_cols:
                    st.error(f"❌ Faltan columnas requeridas: {', '.join(missing_cols)}")
                    st.info("**Columnas encontradas:** " + ", ".join(batch_df.columns.tolist()))
                    st.info("**Columnas requeridas:** " + ", ".join(required_cols))
                else:
                    # Now apply filters if columns exist
                    filtered_df = batch_df.copy()
                    filter_applied = False
                    
                    if selected_dept_batch != "Todos":
                        filtered_df = filtered_df[filtered_df['departamento'] == selected_dept_batch]
                        filter_applied = True
                    
                    if selected_familia_batch != "Todos":
                        filtered_df = filtered_df[filtered_df['familia'] == selected_familia_batch]
                        filter_applied = True
                    
                    if selected_categoria_batch != "Todos":
                        filtered_df = filtered_df[filtered_df['categoria'] == selected_categoria_batch]
                        filter_applied = True
                    
                    # Show filter results
                    if filter_applied:
                        st.info(f"🔍 Filtros aplicados: {len(filtered_df)} de {len(batch_df)} productos seleccionados")
                    
                    st.dataframe(filtered_df.head(10))
                    if len(filtered_df) > 10:
                        st.caption(f"Mostrando las primeras 10 filas de {len(filtered_df)} productos")
                    
                    # Process button only if columns are valid
                    if len(filtered_df) == 0:
                        st.warning("⚠️ No hay productos que coincidan con los filtros seleccionados")
                    else:
                        if st.button("🚀 Procesar Lote", type="primary"):
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            results = []
                            
                            for idx, row in filtered_df.iterrows():
                                status_text.text(f"Procesando {idx + 1} de {len(filtered_df)}...")
                                
                                # Get nomenclature pattern
                                pattern_row = df[
                                    (df['Departamento'] == row['departamento']) & 
                                    (df['Familia'] == row['familia']) & 
                                    (df['Categoria'] == row['categoria'])
                                ]
                                
                                if not pattern_row.empty:
                                    nomenclatura = pattern_row.iloc[0]['Nomenclatura sugerida']
                                    
                                    product_info = {
                                        "titulo_sistema_existente": row['titulo_sistema'],
                                        "departamento": row['departamento'],
                                        "familia": row['familia'],
                                        "categoria": row['categoria']
                                    }
                                    
                                    result = generate_titles(
                                        product_info,
                                        nomenclatura,
                                        st.session_state.transformation_memory
                                    )
                                    
                                    if result:
                                        results.append({
                                            'titulo_sistema_original': row['titulo_sistema'],
                                            'titulo_etiqueta': result['titulo_etiqueta'],
                                            'titulo_seo': result['titulo_seo'],
                                            'departamento': row['departamento'],
                                            'familia': row['familia'],
                                            'categoria': row['categoria']
                                        })
                                
                                progress_bar.progress((idx + 1) / len(filtered_df))
                            
                            status_text.empty()
                            
                            if results:
                                st.success(f"✅ Procesados {len(results)} títulos")
                                results_df = pd.DataFrame(results)
                                st.dataframe(results_df)
                                
                                # Download button
                                csv = results_df.to_csv(index=False, encoding='utf-8-sig')
                                st.download_button(
                                    label="📥 Descargar Resultados",
                                    data=csv,
                                    file_name=f"batch_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                    mime="text/csv"
                                )
                
            except Exception as e:
                st.error(f"❌ Error al leer el archivo: {e}")

# Footer
st.markdown("---")
st.caption("Generador de Títulos de Catálogo - Cemaco © 2025")
