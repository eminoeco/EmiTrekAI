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
        df = pd.read_excel(uploaded_file, engine='openpyxl')
        return df
    except Exception as e:
        st.error(f"Errore nella lettura del file: {e}")
        return None

# --- CARICAMENTO DEI DUE FILE ---
col1, col2 = st.columns(2)

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
if uploaded_clients and uploaded_flotta:
    
    st.header("3. Risultati Assegnazione")

    # Inizializza il DataFrame delle assegnazioni
    assegnazioni_df = df_clienti.copy()
    assegnazioni_df['ID Veicolo Assegnato'] = None
    assegnazioni_df['Autista Assegnato'] = None
    assegnazioni_df['Stato Assegnazione'] = 'NON ASSEGNATO'
    
    # Crea una COPIA della flotta per tracciare la disponibilità (essenziale!)
    df_risorse = df_flotta.copy()

    # Converti gli orari in formato gestibile
    # Assumiamo che l'Ora Arrivo in clienti.xlsx sia solo l'ora (es. time(10, 0))
    def to_time(val):
        if isinstance(val, datetime): return val.time()
        return val # Presuppone che sia già un oggetto time o stringa formattata
    
    assegnazioni_df['Ora Prelievo Richiesta'] = assegnazioni_df['Ora Arrivo'].apply(to_time)


    # Ciclo di matching: assegna cliente per cliente
    for index, cliente in assegnazioni_df.iterrows():
        
        ora_richiesta = cliente['Ora Prelievo Richiesta']
        veicolo_richiesto = cliente['Tipo Veicolo Richiesto']

        # Ipotizziamo che un servizio duri MINIMO 60 minuti
        ora_fine_servizio = (datetime.combine(datetime.today(), ora_richiesta) + timedelta(hours=1)).time()
        
        # Cerca il PRIMO autista disponibile che soddisfa i criteri:
        # 1. Tipo Veicolo Corretto
        # 2. L'autista è disponibile prima dell'ora di prelievo
        # 3. L'autista è disponibile anche dopo la fine stimata del servizio
        
        candidati = df_risorse[
            (df_risorse['Tipo Veicolo'] == veicolo_richiesto) & 
            (df_risorse['Disponibile Da (hh:mm)'] <= ora_richiesta) &
            (df_risorse['Disponibile Fino (hh:mm)'] >= ora_fine_servizio) &
            (df_risorse['Stato Attuale'] == 'Libero')
        ]
        
        if not candidati.empty:
            # Scegli il primo veicolo disponibile
            risorsa_assegnata = candidati.iloc[0]
            
            # AGGIORNA l'assegnazione nel DataFrame di output
            assegnazioni_df.loc[index, 'ID Veicolo Assegnato'] = risorsa_assegnata['ID Veicolo']
            assegnazioni_df.loc[index, 'Autista Assegnato'] = risorsa_assegnata['Autista']
            assegnazioni_df.loc[index, 'Stato Assegnazione'] = 'ASSEGNATO'
            
            # AGGIORNA lo stato della risorsa nella flotta (per non riassegnarla subito)
            # Marcalo come occupato fino all'ora_fine_servizio
            df_risorse.loc[df_risorse['ID Veicolo'] == risorsa_assegnata['ID Veicolo'], 'Stato Attuale'] = 'OCCUPATO'

    # --- MOSTRA I RISULTATI ---
    
    st.subheader("Riepilogo Assegnazioni")
    st.dataframe(assegnazioni_df[['ID Prenotazione', 'Ora Arrivo', 'Tipo Veicolo Richiesto', 'ID Veicolo Assegnato', 'Autista Assegnato', 'Stato Assegnazione']])
    
    st.subheader("Stato Flotta Aggiornato")
    st.dataframe(df_risorse)
    