import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta
import numpy as np


# FIX CRITICI PER STREAMLIT CLOUD
pd.options.mode.chained_assignment = None  # Evita warning fastidiosi
st.set_option('deprecation.showPyplotGlobalUse', False)
np.random.seed(42)  # Riproducibilità

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

       # --- SEQUENZA OPERATIVA UNIFICATA (VERSIONE 100% COMPATIBILE STREAMLIT CLOUD) ---
    st.markdown("## Sequenza Operativa Unificata: Dettaglio Servizi Assegnati")

    assigned_df = assegnazioni_df[assegnazioni_df['Stato Assegnazione'] == 'ASSEGNATO'].copy()

    if not assigned_df.empty:
        # Resetta indice per sicurezza
        assigned_df = assigned_df.reset_index(drop=True)
        
        # Calcola ora fine servizio
        assigned_df['Ora Fine Servizio'] = assigned_df.apply(calculate_end_time, axis=1)

        # Crea il DataFrame finale con le colonne chiare
        display_df = pd.DataFrame({
            'Autista': assigned_df['Autista Assegnato'],
            'Cliente': assigned_df['ID Prenotazione'],
            'Partenza': assigned_df['Indirizzo Prelievo'],
            'Ora Partenza': assigned_df['Ora Effettiva Prelievo'].dt.strftime('%H:%M'),
            'Arrivo': assigned_df['Destinazione Finale'],
            'Ora Arrivo': assigned_df['Ora Fine Servizio'].dt.strftime('%H:%M'),
            'Ritardo (min)': assigned_df['Ritardo Prelievo (min)'].astype(int),
            'Veicolo': assigned_df['Tipo Veicolo Richiesto'].apply(
                lambda x: VEHICLE_EMOJIS.get(str(x).strip().capitalize(), 'Vo') + " " + str(x).strip().capitalize()
            ),
            'Durata (min)': assigned_df['Tempo Servizio Totale (Minuti)'].astype(int),
        })

        # MOSTRA LA TABELLA SENZA USARE .style (causa del crash online)
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )

        # Download button per Excel
        csv = display_df.to_csv(index=False).encode()
        st.download_button(
            label="Scarica Sequenza Operativa (Excel)",
            data=csv,
            file_name=f"Sequenza_Operativa_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )
    else:
        st.info("Nessun servizio assegnato con successo.")
    
    st.markdown("---")