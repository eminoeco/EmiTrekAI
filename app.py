import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta

# --- CONFIGURAZIONE GENERALE ---
st.set_page_config(layout="wide", page_title="EmiTrekAI: VOM", page_icon="🗓️")

# Inizializza lo stato
if 'processed_data' not in st.session_state:
    st.session_state['processed_data'] = False
    st.session_state['assegnazioni_complete'] = None
    st.session_state['flotta_risorse'] = None

# --- MAPPATURA COLORI (SU RICHIESTA ESPRESSA) ---
# Ogni operatore NCC ha un colore fisso che lo identifica.
DRIVER_COLORS = {
    'Andrea': '#2ecc71', # Verde per Andrea
    'Carlo': '#3498db',  # Blu per Carlo
    'Giulia': '#f39c12', # Arancione per Giulia
    'DEFAULT': '#95a5a6' # Grigio per Autisti non mappati o Non Assegnato
}

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
    return t.hour * 60 + t.minute

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

# --- LOGICA DI SCHEDULAZIONE (CORE) ---
def run_scheduling(df_clienti, df_flotta):
    
    # Prepara i DataFrame per l'algoritmo
    assegnazioni_df = df_clienti.copy()
    assegnazioni_df['ID Veicolo Assegnato'] = None
    assegnazioni_df['Autista Assegnato'] = None
    assegnazioni_df['Stato Assegnazione'] = 'NON ASSEGNATO'
    assegnazioni_df['Ora Effettiva Prelievo'] = None
    assegnazioni_df['Ritardo Prelievo (min)'] = 0 
    
    df_risorse = df_flotta.copy()
    
    # Inizializza stato dinamico della risorsa
    df_risorse['Prossima Disponibilità'] = df_risorse['Disponibile Da (hh:mm)'].apply(to_time)
    df_risorse['Disponibile Fino (hh:mm)'] = df_risorse['Disponibile Fino (hh:mm)'].apply(to_time)
    df_risorse['Tipo Veicolo'] = df_risorse['Tipo Veicolo'].str.capitalize()
    
    assegnazioni_df['Ora Prelievo Richiesta'] = assegnazioni_df['Ora Arrivo'].apply(to_time)
    assegnazioni_df['Tipo Veicolo Richiesto'] = assegnazioni_df['Tipo Veicolo Richiesto'].str.capitalize()
    
    assegnazioni_df = assegnazioni_df.sort_values(by='Ora Prelievo Richiesta').reset_index(drop=True)
    
    for index, cliente in assegnazioni_df.iterrows():
        
        ora_richiesta = cliente['Ora Prelievo Richiesta']
        veicolo_richiesto = cliente['Tipo Veicolo Richiesto']
        
        if 'Tempo Servizio Totale (Minuti)' not in cliente or pd.isna(cliente['Tempo Servizio Totale (Minuti)']): continue
            
        tempo_servizio_totale = int(cliente['Tempo Servizio Totale (Minuti)'])
        
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
    st.experimental_rerun() # Forza il refresh per mostrare i risultati


# --- LAYOUT PRINCIPALE ---

if not st.session_state['processed_data']:
    # --- LOGICA DI SALVATAGGIO DEI DATI CARICATI ---
# Funzione chiamata quando l'utente clicca il pulsante
def start_optimization(df_clienti, df_flotta):
    # Salviamo i dati letti nello stato in modo che non si perdano al refresh
    st.session_state['temp_df_clienti'] = df_clienti
    st.session_state['temp_df_flotta'] = df_flotta
    
    # Eseguiamo la schedulazione passando i dati dallo stato temporaneo
    run_scheduling(st.session_state['temp_df_clienti'], st.session_state['temp_df_flotta'])
    
    # Pulizia (opzionale)
    if 'temp_df_clienti' in st.session_state: del st.session_state['temp_df_clienti']
    if 'temp_df_flotta' in st.session_state: del st.session_state['temp_df_flotta']


# --- LAYOUT PRINCIPALE ---

if not st.session_state['processed_data']:
    # === MOSTRA INTERFACCIA DI CARICAMENTO ===
    st.title("EmiTrekAI: Virtual Operations Manager")
    st.markdown("### Carica i file per ottimizzare la flotta.")
    st.markdown("---")

    col1, col2 = st.columns(2)
    uploaded_clients = None
    uploaded_flotta = None
    
    # Variabili per tenere i dati letti in questo ciclo
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
        st.success("File caricati con successo!")
        # Pulsante per avviare il calcolo
        st.button("Avvia Ottimizzazione e Visualizza Dashboard", key="run_btn", 
                  on_click=lambda: start_optimization(read_df_clienti, read_df_flotta))
        
else:
    # === MOSTRA DASHBOARD INTERATTIVA (DOPO IL CARICAMENTO) ===
    # Il resto del codice della dashboard interattiva e colorata
    # ... (Il codice che mostra la dashboard da riga 250 in poi DEVE RESTARE INCOLLATO QUI) ...
    
    assegnazioni_df = st.session_state['assegnazioni_complete']
    df_risorse = st.session_state['flotta_risorse']

    st.markdown("## 🤩 Risultati di Ottimizzazione EmiTrekAI", unsafe_allow_html=True)
    st.markdown("### La tua flotta sta lavorando in modo intelligente!")
    st.markdown("---")

    # 1. STATO FLOTTA (CON COLORI)
    # ... (Resto del codice della dashboard e delle tabs) ...
    
    # 1. STATO FLOTTA (CON COLORI PER AUTISTA)
    st.markdown("### 🚦 Stato di Disponibilità della Flotta (Colori Autista)")
    
    # ... (omissis, tutto il codice della dashboard finale) ...
    
    # 3. RICERCA E STORICO INTERATTIVO
    # ... (omissis, tutto il codice della dashboard finale) ...

    # Pulsante per resettare e tornare al caricamento file
    st.markdown("---")
    st.button("↩️ Torna al Caricamento File", on_click=lambda: st.session_state.update(processed_data=False))