import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta
import numpy as np

# FIX PER STREAMLIT CLOUD: disabilita warning e chained assignment
pd.options.mode.chained_assignment = None


# --- CONFIGURAZIONE GENERALE ---
st.set_page_config(layout="wide", page_title="EmiTrekAI: VOM", page_icon="🗓️")

# Inizializza lo stato in modo sicuro
if 'processed_data' not in st.session_state:
    st.session_state['processed_data'] = False
    st.session_state['assegnazioni_complete'] = None
    st.session_state['flotta_risorse'] = None

# --- MAPPATURA COLORI E EMOJI ---
DRIVER_COLORS = {
    'Andrea': '#4CAF50',  
    'Carlo': '#2199F3',   
    'Giulia': '#FFC107',  
    'DEFAULT': '#B0BEC5' 
}

VEHICLE_EMOJIS = {
    'Berlina': '🚗',
    'Minivan': '🚐',
    'Suv': '🚙', 
    'Default': '❓' 
}

STATUS_EMOJIS = {
    'ASSEGNATO': '✅',
    'NON ASSEGNATO': '❌'
}

# --- INIEZIONE CSS SEMPLIFICATA (Sfondo e Compattazione) ---
st.markdown(
    """
    <style>
    .stApp {
        background-color: #F0F8FF; /* Alice Blue - Azzurrino Chiaro */
    }
    .big-font {
        font-size:20px !important;
        font-weight: bold;
    }
    .driver-card {
        padding: 15px;
        border-radius: 10px;
        box-shadow: 2px 2px 10px rgba(0,0,0,0.1);
        margin-bottom: 15px;
    }
    div.stDataFrame {
        font-size: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True
)
# -----------------------------------------------------------------------------

# --- FUNZIONI DI SUPPORTO ---
def read_excel_file(uploaded_file):
    try:
        if uploaded_file.name.endswith('.csv'):
             df = pd.read_csv(uploaded_file)
        else:
             df = pd.read_excel(uploaded_file, engine='openpyxl')
        return df
    except Exception as e:
        st.error(f"Errore nella lettura del file: {e}")
        return None

def time_to_minutes(t):
    if isinstance(t, time): return t.hour * 60 + t.minute
    return 0

def to_time(val):
    if isinstance(val, datetime): return val.time()
    if isinstance(val, time): return val
    if isinstance(val, str): 
        try: return datetime.strptime(val, '%H:%M').time()
        except ValueError: pass
        try: return datetime.strptime(val, '%H.%M').time()
        except ValueError: return time(0, 0)
    return time(0, 0)

def calculate_end_time(row):
    try:
        start_dt = datetime.combine(datetime.today(), row['Ora Effettiva Prelievo'])
        end_dt = start_dt + timedelta(minutes=int(row['Tempo Servizio Totale (Minuti)']))
        return end_dt.time()
    except Exception:
        return time(0, 0)

# --- LOGICA DI SALVATAGGIO DEI DATI CARICATI (Chiamata dal pulsante) ---
def start_optimization(df_clienti, df_flotta):
    st.session_state['temp_df_clienti'] = df_clienti
    st.session_state['temp_df_flotta'] = df_flotta
    run_scheduling(st.session_state['temp_df_clienti'], st.session_state['temp_df_flotta'])

# --- LOGICA DI SCHEDULAZIONE (CORE) ---
def run_scheduling(df_clienti, df_flotta):
    # Logica di assegnazione (completa)
    assegnazioni_df = df_clienti.copy()
    assegnazioni_df['ID Veicolo Assegnato'] = np.nan
    assegnazioni_df['Autista Assegnato'] = np.nan
    assegnazioni_df['Stato Assegnazione'] = 'NON ASSEGNATO'
    assegnazioni_df['Ora Effettiva Prelievo'] = np.nan
    assegnazioni_df['Ritardo Prelievo (min)'] = 0 
    
    df_risorse = df_flotta.copy()
    
    df_risorse['Prossima Disponibilità'] = df_risorse['Disponibile Da (hh:mm)'].apply(to_time)
    df_risorse['Disponibile Fino (hh:mm)'] = df_risorse['Disponibile Fino (hh:mm)'].apply(to_time)
    df_risorse['Tipo Veicolo'] = df_risorse['Tipo Veicolo'].astype(str).str.capitalize()
    
    assegnazioni_df['Ora Prelievo Richiesta'] = assegnazioni_df['Ora Arrivo'].apply(to_time)
    assegnazioni_df['Tipo Veicolo Richiesto'] = assegnazioni_df['Tipo Veicolo Richiesto'].astype(str).str.capitalize()
    
    assegnazioni_df = assegnazioni_df.sort_values(by='Ora Prelievo Richiesta').reset_index(drop=True)
    
    for index, cliente in assegnazioni_df.iterrows():
        
        ora_richiesta = cliente['Ora Prelievo Richiesta']
        veicolo_richiesto = cliente['Tipo Veicolo Richiesto']
        
        if 'Tempo Servizio Totale (Minuti)' not in cliente or pd.isna(cliente['Tempo Servizio Totale (Minuti)']): continue
            
        try:
            tempo_servizio_totale = int(cliente['Tempo Servizio Totale (Minuti)'])
        except ValueError:
             continue
        
        candidati_validi = df_risorse[
            (df_risorse['Tipo Veicolo'] == veicolo_richiesto) & 
            (df_risorse['Disponibile Fino (hh:mm)'].apply(time_to_minutes) >= time_to_minutes(ora_richiesta)) 
        ].copy()
        
        if candidati_validi.empty: continue
        
        tempo_richiesto_min = time_to_minutes(ora_richiesta)
        
        candidati_validi['Ritardo Min'] = (candidati_validi['Prossima Disponibilità'].apply(time_to_minutes) - tempo_richiesto_min).clip(lower=0)
        risorsa_assegnata = candidati_validi.sort_values(by='Ritardo Min').iloc[0]
        
        ritardo_minuti = int(risorsa_assegnata['Ritardo Min']) 
        
        ora_effettiva_prelievo_dt = datetime.combine(datetime.today(), ora_richiesta) + timedelta(minutes=ritardo_minuti)
        ora_effettiva_prelievo = ora_effettiva_prelievo_dt.time()
        
        ora_fine_servizio_dt = ora_effettiva_prelievo_dt + timedelta(minutes=tempo_servizio_totale)
        ora_fine_servizio = ora_fine_servizio_dt.time()

        if ora_fine_servizio > risorsa_assegnata['Disponibile Fino (hh:mm)']: continue
            
        # AGGIORNA l'assegnazione
        assegnazioni_df.loc[index, 'ID Veicolo Assegnato'] = risorsa_assegnata['ID Veicolo']
        assegnazioni_df.loc[index, 'Autista Assegnato'] = risorsa_assegnata['Autista']
        assegnazioni_df.loc[index, 'Stato Assegnazione'] = 'ASSEGNATO'
        assegnazioni_df.loc[index, 'Ora Effettiva Prelievo'] = ora_effettiva_prelievo
        assegnazioni_df.loc[index, 'Ritardo Prelievo (min)'] = ritardo_minuti
        
        # AGGIORNA la risorsa
        df_risorse.loc[df_risorse['ID Veicolo'] == risorsa_assegnata['ID Veicolo'], 'Prossima Disponibilità'] = ora_fine_servizio

    # SALVA NELLO STATO E IMPOSTA COME PROCESSATO
    st.session_state['assegnazioni_complete'] = assegnazioni_df
    st.session_state['flotta_risorse'] = df_risorse
    st.session_state['processed_data'] = True
    st.rerun()

# --- LAYOUT PRINCIPALE ---

if not st.session_state['processed_data']:
    # === MOSTRA INTERFACCIA DI CARICAMENTO ===
    st.title("EmiTrekAI: Virtual Operations Manager")
    st.markdown("### Carica i file per ottimizzare la flotta.")
    st.markdown("---")

    col1, col2 = st.columns(2)
    uploaded_clients = None
    uploaded_flotta = None
    
    read_df_clienti = None
    read_df_flotta = None

    with col1:
        st.header("1. Clienti in Arrivo (Richieste)")
        uploaded_clients = st.file_uploader("Carica il file Prenotazioni Clienti (lista clienti)", type=['xlsx', 'csv'], key='clients_uploader')
        if uploaded_clients:
            read_df_clienti = read_excel_file(uploaded_clients)
            
    with col2:
        st.header("2. La mia flotta NCC (Risorse)")
        uploaded_flotta = st.file_uploader("Carica il file Flotta Personale (flotta ncc)", type=['xlsx', 'csv'], key='flotta_uploader')
        if uploaded_flotta:
            read_df_flotta = read_excel_file(uploaded_flotta)

    if read_df_clienti is not None and read_df_flotta is not None:
        st.success("File caricati con successo! Clicca il pulsante per avviare l'ottimizzazione.")
        st.button("Avvia Ottimizzazione e Visualizza Dashboard", key="run_btn", 
                  on_click=lambda: start_optimization(read_df_clienti, read_df_flotta))

else:
    # === MOSTRA DASHBOARD INTERATTIVA (DOPO IL CARICAMENTO) ===
    assegnazioni_df = st.session_state['assegnazioni_complete']
    df_risorse = st.session_state['flotta_risorse']

    # FIX NameError: Controlla se il DataFrame è vuoto/None
    if assegnazioni_df is None or assegnazioni_df.empty:
        st.error("Errore: I dati non sono stati caricati o il file è vuoto. Torna indietro e ricarica i file.")
        st.button("↩️ Torna al Caricamento File", on_click=lambda: st.session_state.update(processed_data=False))
        st.stop()
        
    st.markdown("## ✨ La Tua Flotta Sotto Controllo ✨", unsafe_allow_html=True)
    st.markdown("### Riepilogo Intuitivo: **Clienti & Operatori**")
    st.markdown("---")

    # --- NUOVA SEZIONE: RIEPILOGO A COLPO D'OCCHIO ---
    total_clients = assegnazioni_df.shape[0]
    assigned_clients = assegnazioni_df[assegnazioni_df['Stato Assegnazione'] == 'ASSEGNATO'].shape[0]
    unassigned_clients = total_clients - assigned_clients
    total_drivers = df_risorse['Autista'].nunique()
    
    st.subheader("👀 Panoramica Rapida")
    col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
    
    with col_kpi1:
        st.markdown(f"<p class='big-font'>Clienti Totali: {total_clients}</p>", unsafe_allow_html=True)
    with col_kpi2:
        st.markdown(f"<p class='big-font'>Clienti Assegnati: <span style='color:green'>{assigned_clients} ✅</span></p>", unsafe_allow_html=True)
    with col_kpi3:
        st.markdown(f"<p class='big-font'>Clienti Non Assegnati: <span style='color:red'>{unassigned_clients} ❌</span></p>", unsafe_allow_html=True)
    with col_kpi4:
        st.markdown(f"<p class='big-font'>Autisti in Flotta: {total_drivers} 🧑‍✈️</p>", unsafe_allow_html=True)
    
    st.markdown("---")

    # --- Sezione Operatori/Autisti con Schede Colorate e Emoji ---
    st.subheader("🧑‍✈️ I Nostri Operatori NCC")
    
    drivers_unique = df_risorse['Autista'].unique()
    drivers_overview_cols = st.columns(len(drivers_unique)) 
    
    for i, driver in enumerate(drivers_unique):
        with drivers_overview_cols[i]:
            driver_color = DRIVER_COLORS.get(driver, DRIVER_COLORS['DEFAULT'])
            driver_info = df_risorse[df_risorse['Autista'] == driver].iloc[0]
            vehicle_emoji = VEHICLE_EMOJIS.get(driver_info['Tipo Veicolo'], VEHICLE_EMOJIS['Default'])
            
            num_servizi = assegnazioni_df[assegnazioni_df['Autista Assegnato'] == driver].shape[0]

            st.markdown(f"""
            <div class="driver-card" style="background-color: {driver_color}; color: white;">
                <p class='big-font'>{driver} {vehicle_emoji}</p>
                <p>Veicolo: {driver_info['Tipo Veicolo']}</p>
                <p>Fine Servizio Ore: {driver_info['Prossima Disponibilità'].strftime('%H:%M')}</p>
                <p>Servizi Assegnati: {num_servizi}</p>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")

      # --- SEQUENZA OPERATIVA CON COLORE AUTISTA COME SOPRA ---
    st.markdown("## Sequenza Operativa Unificata: Dettaglio Servizi Assegnati")
    
    assigned_df = assegnazioni_df[assegnazioni_df['Stato Assegnazione'] == 'ASSEGNATO'].copy()
    
    if assigned_df.empty:
        st.info("Nessun servizio assegnato con successo.")
    else:
        assigned_df['Ora Fine Servizio'] = assigned_df.apply(calculate_end_time, axis=1)

        # DataFrame finale
        display_df = pd.DataFrame({
            'Autista'              : assigned_df['Autista Assegnato'].fillna('-'),
            'Cliente'              : assigned_df.get('ID Prenotazione', pd.Series('-', index=assigned_df.index)),
            'Partenza'             : 'FCO',
            'Ora Partenza'         : assigned_df['Ora Effettiva Prelievo'].apply(
                lambda x: x.strftime('%H:%M') if pd.notna(x) and hasattr(x, 'strftime') else '-'
            ),
            'Arrivo'               : assigned_df.get('Destinazione Finale', pd.Series('-', index=assigned_df.index)).fillna('-'),
            'Ora Arrivo'           : assigned_df['Ora Fine Servizio'].apply(
                lambda x: x.strftime('%H:%M') if pd.notna(x) and hasattr(x, 'strftime') else '-'
            ),
            'Ritardo (min)'        : assigned_df['Ritardo Prelievo (min)'].fillna(0).astype(int),
            'Veicolo'              : assigned_df['Tipo Veicolo Richiesto'].astype(str).apply(
                lambda x: VEHICLE_EMOJIS.get(x.strip().title(), 'Veicolo') + ' ' + x.strip().title()
            ),
            'Durata Servizio (min)': assigned_df['Tempo Servizio Totale (Minuti)'].fillna(0).astype(int),
        })

        # FUNZIONE DI COLORAZIONE
        def color_autista(row):
            colore = DRIVER_COLORS.get(row['Autista'], DRIVER_COLORS['DEFAULT'])
            return [f'background-color: {colore}; color: white' if col == 'Autista' else '' for col in display_df.columns]

        # APPLICA IL COLORE
        styled_df = display_df.style.apply(color_autista, axis=1)

        # MOSTRA LA TABELLA BELLA
        st.dataframe(styled_df, use_container_width=True, hide_index=True)_index=True)
    
            # Download
            csv = display_df.to_csv(index=False, encoding='utf-8-sig')
            st.download_button(
                label="Scarica Sequenza Operativa (Excel/CSV)",
                data=csv,
                file_name=f"Sequenza_FCO_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv"
            )
    
            st.markdown("---")
    
    # =============================================================================
# REPORT INDIVIDUALE AUTISTA (da mettere alla fine del file, senza indentazione)
# =============================================================================

if st.session_state.get('processed_data', False):
    st.markdown("---")
    st.subheader("Report Individuale Autista")

    # Usa il display_df che hai già creato sopra nella sequenza operativa
    if 'display_df' in locals() and not display_df.empty:
        autisti_con_corse = sorted(display_df['Autista'].dropna().unique())
        
        if autisti_con_corse:
            selected_driver = st.selectbox(
                "Scegli l'autista per il report personale",
                options=autisti_con_corse
            )

            driver_df = display_df[display_df['Autista'] == selected_driver].copy()
            driver_df = driver_df.reset_index(drop=True)
            driver_df.index += 1

            driver_color = DRIVER_COLORS.get(selected_driver, DRIVER_COLORS['DEFAULT'])

            st.markdown(f"""
            <div style="padding:20px; background:{driver_color}; color:white; border-radius:12px; text-align:center; font-size:26px; font-weight:bold; margin:30px 0;">
                Report Giornaliero — {selected_driver}
            </div>
            """, unsafe_allow_html=True)

            st.dataframe(driver_df, use_container_width=True, hide_index=False)

            oggi = datetime.now().strftime("%d-%m-%Y")

            # PDF
            try:
                from io import BytesIO
                from reportlab.lib.pagesizes import A4
                from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
                from reportlab.lib.styles import getSampleStyleSheet
                from reportlab.lib import colors as rl_colors

                buffer = BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=A4)
                elements = []
                styles = getSampleStyleSheet()

                elements.append(Paragraph(f"<b>Report Autista: {selected_driver}</b>", styles['Title']))
                elements.append(Paragraph(f"Data: {oggi}<br/><br/>", styles['Normal']))

                data = [["N.", "Cliente", "Ora Part.", "Destinazione", "Veicolo", "Ritardo", "Durata"]]
                for i, row in driver_df.iterrows():
                    data.append([i, row['Cliente'], row['Ora Partenza'], row['Arrivo'],
                                row['Veicolo'], f"{row['Ritardo (min)']} min", f"{row['Durata Servizio (min)']} min"])

                table = Table(data)
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), rl_colors.HexColor(driver_color)),
                    ('TEXTCOLOR', (0,0), (-1,0), rl_colors.white),
                    ('GRID', (0,0), (-1,-1), 1, rl_colors.black),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                    ('BACKGROUND', (0,1), (-1,-1), rl_colors.beige),
                ]))
                elements.append(table)
                doc.build(elements)

                st.download_button(
                    label="Scarica Report PDF",
                    data=buffer.getvalue(),
                    file_name=f"Report_{selected_driver}_{oggi}.pdf",
                    mime="application/pdf"
                )
            except:
                st.info("Reportlab non installato – solo Excel disponibile")

            # Excel
            excel_buffer = BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                driver_df.to_excel(writer, index=True, sheet_name=selected_driver[:30])
            st.download_button(
                label="Scarica Report Excel",
                data=excel_buffer.getvalue(),
                file_name=f"Report_{selected_driver}_{oggi}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("Nessun autista con corse oggi.")
    else:
        st.info("Carica i file e avvia l'ottimizzazione per vedere i report.")
