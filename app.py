import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta

st.set_page_config(layout="wide")
st.title("EmiTrekAI: Virtual Operations Manager")
st.markdown("---")

# Funzione ausiliaria per la lettura dei file
def read_excel_file(uploaded_file):
    try:
        # Usiamo openpyxl che abbiamo aggiunto in requirements.txt
        if uploaded_file.name.endswith('.csv'):
             df = pd.read_csv(uploaded_file)
        else:
             df = pd.read_excel(uploaded_file, engine='openpyxl')
        return df
    except Exception as e:
        st.error(f"Errore nella lettura del file: {e}")
        return None

# Funzione per convertire time in total minutes of the day (necessario per confronto/sottrazione)
def time_to_minutes(t):
    return t.hour * 60 + t.minute

# --- CARICAMENTO DEI DUE FILE ---
col1, col2 = st.columns(2)

uploaded_clients = None
uploaded_flotta = None
df_clienti = None
df_flotta = None

with col1:
    st.header("1. Clienti in Arrivo (Richieste)")
    uploaded_clients = st.file_uploader(
        "Carica il file Prenotazioni Clienti (clienti.xlsx)", 
        type=['xlsx', 'csv'], 
        key='clients_uploader'
    )
    if uploaded_clients:
        df_clienti = read_excel_file(uploaded_clients)
        if df_clienti is not None:
            st.dataframe(df_clienti)

with col2:
    st.header("2. Flotta NCC (Risorse)")
    uploaded_flotta = st.file_uploader(
        "Carica il file Flotta Personale (flotta_ncc.xlsx)", 
        type=['xlsx', 'csv'], 
        key='flotta_uploader'
    )
    if uploaded_flotta:
        df_flotta = read_excel_file(uploaded_flotta)
        if df_flotta is not None:
            st.dataframe(df_flotta)

st.markdown("---")

# --- LOGICA DI MATCHING (ESEGUITA SOLO SE ENTRAMBI I FILE SONO CARICATI) ---
if df_clienti is not None and df_flotta is not None:
    
    st.header("3. Risultati Assegnazione Ottimizzata")
    
    # 1. PREPARAZIONE DATI
    
    # Dati Clienti (Output)
    assegnazioni_df = df_clienti.copy()
    assegnazioni_df['ID Veicolo Assegnato'] = None
    assegnazioni_df['Autista Assegnato'] = None
    assegnazioni_df['Stato Assegnazione'] = 'NON ASSEGNATO'
    assegnazioni_df['Ora Effettiva Prelievo'] = None
    assegnazioni_df['Ritardo Prelievo (min)'] = 0 # Nuova colonna per il ritardo
    
    # Dati Flotta (Risorse Dinamiche)
    df_risorse = df_flotta.copy()
    
    # Inizializza lo stato dinamico della risorsa (Logica)
    def to_time(val):
        if isinstance(val, datetime): return val.time()
        # Se è una stringa 'hh:mm', prova a convertirla in time
        if isinstance(val, str): 
            try:
                return datetime.strptime(val, '%H:%M').time()
            except ValueError:
                return time(0, 0) # Fallback se il formato non è corretto
        return val
        
    # Colonna chiave per la nuova logica: quando l'autista è di nuovo libero (inizia con 'Disponibile Da')
    df_risorse['Prossima Disponibilità'] = df_risorse['Disponibile Da (hh:mm)'].apply(to_time)
    df_risorse['Disponibile Fino (hh:mm)'] = df_risorse['Disponibile Fino (hh:mm)'].apply(to_time)
    df_risorse['Tipo Veicolo'] = df_risorse['Tipo Veicolo'].str.capitalize() # Normalizza i tipi di veicolo
    
    # Prepara la colonna 'Ora Arrivo' dei clienti
    assegnazioni_df['Ora Prelievo Richiesta'] = assegnazioni_df['Ora Arrivo'].apply(to_time)
    
    
    # Ordina i clienti in base all'ora di arrivo richiesta (base per l'ottimizzazione)
    assegnazioni_df = assegnazioni_df.sort_values(by='Ora Prelievo Richiesta').reset_index(drop=True)
    
    
    # 2. ALGORITMO DI ASSEGNAZIONE E CALCOLO DEL RITARDO
    
    for index, cliente in assegnazioni_df.iterrows():
        
        ora_richiesta = cliente['Ora Prelievo Richiesta']
        veicolo_richiesto = cliente['Tipo Veicolo Richiesto'].capitalize()
        tempo_servizio_totale = cliente['Tempo Servizio Totale (Minuti)'] # A/R + Buffer, dalla nuova colonna
        
        # 2.1 FILTRA I CANDIDATI VALIDI
        
        # Filtra i candidati per tipo di veicolo corretto E che non superino il loro turno (Disponibile Fino)
        candidati_validi = df_risorse[
            (df_risorse['Tipo Veicolo'] == veicolo_richiesto) & 
            (df_risorse['Disponibile Fino (hh:mm)'] >= ora_richiesta) # Devono essere disponibili almeno all'ora richiesta
        ].copy() # Copia per lavorare senza SettingWithCopyWarning
        
        if candidati_validi.empty:
            continue # Prova il prossimo cliente
        
        # 2.2 SELEZIONA IL CANDIDATO MIGLIORE (QUELLO CON MENO RITARDO)
        
        # Calcola il Ritardo Potenziale per ogni candidato
        tempo_richiesto_min = time_to_minutes(ora_richiesta)
        
        # Ritardo = (Prossima Disponibilità in min) - (Ora Richiesta in min). Clip(lower=0) garantisce che non sia negativo.
        candidati_validi['Ritardo Min'] = (candidati_validi['Prossima Disponibilità'].apply(time_to_minutes) - tempo_richiesto_min).clip(lower=0)
        
        # Seleziona la risorsa che minimizza il Ritardo (ossia è libera prima)
        risorsa_assegnata = candidati_validi.sort_values(by='Ritardo Min').iloc[0]
        
        ritardo_minuti = int(risorsa_assegnata['Ritardo Min'])
        
        # 2.3 CALCOLA ORA EFFETTIVA E ORA FINE
        
        # L'ora effettiva di prelievo è l'Ora Richiesta + Ritardo (se Ritardo > 0)
        ora_effettiva_prelievo_dt = datetime.combine(datetime.today(), ora_richiesta) + timedelta(minutes=ritardo_minuti)
        ora_effettiva_prelievo = ora_effettiva_prelievo_dt.time()
        
        # L'autista sarà libero solo dopo la fine del servizio totale (dall'ora effettiva di prelievo)
        ora_fine_servizio_dt = ora_effettiva_prelievo_dt + timedelta(minutes=tempo_servizio_totale)
        ora_fine_servizio = ora_fine_servizio_dt.time()

        # 2.4 VERIFICA TERMINI E AGGIORNA
        
        # Controlla se la fine del servizio supera la Disponibilità Fino (Turno)
        if ora_fine_servizio > risorsa_assegnata['Disponibile Fino (hh:mm)']:
            continue # Non assegnare se sfora il turno
            
        # Altrimenti, assegna!
        
        # AGGIORNA l'assegnazione nel DataFrame di output
        assegnazioni_df.loc[index, 'ID Veicolo Assegnato'] = risorsa_assegnata['ID Veicolo']
        assegnazioni_df.loc[index, 'Autista Assegnato'] = risorsa_assegnata['Autista']
        assegnazioni_df.loc[index, 'Stato Assegnazione'] = 'ASSEGNATO'
        assegnazioni_df.loc[index, 'Ora Effettiva Prelievo'] = ora_effettiva_prelievo
        assegnazioni_df.loc[index, 'Ritardo Prelievo (min)'] = ritardo_minuti
        
        # AGGIORNA la prossima disponibilità della risorsa
        df_risorse.loc[df_risorse['ID Veicolo'] == risorsa_assegnata['ID Veicolo'], 'Prossima Disponibilità'] = ora_fine_servizio


    # 3. MOSTRA I RISULTATI
    
    st.subheader("Riepilogo Assegnazioni e Ritardi")
    st.dataframe(
        assegnazioni_df[[
            'ID Prenotazione', 
            'Ora Prelievo Richiesta', 
            'Ora Effettiva Prelievo', 
            'Ritardo Prelievo (min)',
            'Tipo Veicolo Richiesto', 
            'ID Veicolo Assegnato', 
            'Autista Assegnato', 
            'Stato Assegnazione'
        ]].sort_values(by='Ora Prelievo Richiesta')
    )
    
    st.subheader("Stato Flotta Aggiornato (Prossima Disponibilità)")
    st.dataframe(
        df_risorse[[
            'ID Veicolo', 
            'Autista', 
            'Tipo Veicolo', 
            'Disponibile Da (hh:mm)', 
            'Disponibile Fino (hh:mm)', 
            'Prossima Disponibilità'
        ]].sort_values(by='Prossima Disponibilità')
    )