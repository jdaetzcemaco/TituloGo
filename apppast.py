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
    
    client = anthropic.Anthropic(api_key=st.secrets.get("ANTHROPIC_API_KEY", ""))
    
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
    
    # API Key input
    if "ANTHROPIC_API_KEY" not in st.secrets:
        api_key = st.text_input("Anthropic API Key", type="password")
        if api_key:
            st.secrets["ANTHROPIC_API_KEY"] = api_key
    
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
        for orig, repl in st.session_state.transformation_memory.items():
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
    # Create tabs for different modes
    tab1, tab2 = st.tabs(["🔨 Crear Título Individual", "📦 Procesamiento por Lote"])
    
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
    
    # TAB 2: Batch processing
    with tab2:
        st.subheader("Procesamiento por Lote")
        st.markdown("Sube un CSV con títulos del sistema existentes para generar las variantes faltantes")
        
        uploaded_batch = st.file_uploader(
            "Archivo CSV con títulos existentes",
            type=['csv'],
            key="batch_upload",
            help="Debe incluir columnas: titulo_sistema, departamento, familia, categoria"
        )
        
        if uploaded_batch:
            batch_df = pd.read_csv(uploaded_batch)
            st.dataframe(batch_df.head())
            
            required_cols = ['titulo_sistema', 'departamento', 'familia', 'categoria']
            missing_cols = [col for col in required_cols if col not in batch_df.columns]
            
            if missing_cols:
                st.error(f"❌ Faltan columnas requeridas: {', '.join(missing_cols)}")
            else:
                if st.button("🚀 Procesar Lote", type="primary"):
                    progress_bar = st.progress(0)
                    results = []
                    
                    for idx, row in batch_df.iterrows():
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
                        
                        progress_bar.progress((idx + 1) / len(batch_df))
                    
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

# Footer
st.markdown("---")
st.caption("Generador de Títulos de Catálogo - Cemaco © 2025")