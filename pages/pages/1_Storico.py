import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta

# Impostazioni generali della pagina (sfondo/icona)
st.set_page_config(
    layout="wide",
    page_title="EmiTrekAI - Schedulazione",
    page_icon="🗓️",
    initial_sidebar_state="expanded"
)

# Funzione per calcolare l'Ora Fine Servizio
def calculate_end_time(row):
    try:
        start_dt = datetime.combine(datetime.today(), row['Ora Effettiva Prelievo'])
        end_dt = start_dt + timedelta(minutes=int(row['Tempo Servizio Totale (Minuti)']))
        return end_dt.time()
    except:
        return time(0, 0) # Ritorna 00:00 in caso di errore

# --- MAPPATURA COLORI ---
# Colori per i tipi di veicolo (usati nel colore del testo o evidenziazione)
VEHICLE_COLORS = {
    'Berlina': '#2ecc71', # Verde Smeraldo
    'Minivan': '#3498db', # Blu
    'Bus': '#f39c12'      # Arancione
}

# --- INIZIO DELLA PAGINA DI VISUALIZZAZIONE ---
if 'assegnazioni_complete' not in st.session_state or 'flotta_risorse' not in st.session_state:
    st.warning("Per favore, torna alla pagina principale 'EmiTrekAI' per caricare i file e avviare il calcolo.")
else:
    assegnazioni_df = st.session_state['assegnazioni_complete']
    df_risorse = st.session_state['flotta_risorse']
    
    st.markdown("## 🤩 Risultati di Ottimizzazione EmiTrekAI", unsafe_allow_html=True)
    st.markdown("### La tua flotta sta lavorando in modo intelligente!")
    st.markdown("---")
    
    # 1. STATO FLOTTA (CON COLORI)
    st.markdown("### 🚦 Stato di Disponibilità della Flotta")
    
    # Mappiamo i colori delle risorse
    def highlight_resource_type(row):
        color = VEHICLE_COLORS.get(row['Tipo Veicolo'], 'gray')
        return [f'background-color: {color}; color: white; font-weight: bold;' if col == 'Tipo Veicolo' or col == 'Autista' else '' for col in row.index]

    st.dataframe(
        df_risorse[[
            'ID Veicolo', 
            'Autista', 
            'Tipo Veicolo', 
            'Prossima Disponibilità'
        ]].sort_values(by='Prossima Disponibilità').style.apply(highlight_resource_type, axis=1)
    )

    st.markdown("---")

    # 2. SEQUENZA OPERATIVA DETTAGLIATA (CON EXPANDER E COLORI COERENTI)
    st.markdown("## 🗓️ Sequenza Operativa Dettagliata per Autista")

    assigned_drivers = assegnazioni_df['Autista Assegnato'].dropna().unique().tolist()

    if assigned_drivers:
        
        for driver in assigned_drivers:
            
            driver_assignments = assegnazioni_df[
                (assegnazioni_df['Autista Assegnato'] == driver) &
                (assegnazioni_df['Stato Assegnazione'] == 'ASSEGNATO')
            ].sort_values(by='Ora Effettiva Prelievo').reset_index(drop=True)
            
            if not driver_assignments.empty:
                
                # Determina il colore basato sul TIPO DI VEICOLO ASSEGNATO (per coerenza)
                vehicle_type = driver_assignments['Tipo Veicolo Richiesto'].iloc[0].capitalize()
                driver_color = VEHICLE_COLORS.get(vehicle_type, '#95a5a6')
                
                # Calcola l'Ora Fine Servizio e aggiunge la colonna
                driver_assignments['Ora Fine Servizio'] = driver_assignments.apply(calculate_end_time, axis=1)

                # Usiamo un expander (cartella)
                with st.expander(f"🚗 {driver} ({driver_assignments.shape[0]} servizi) - [Tipo: {vehicle_type}]", expanded=False):
                    
                    st.markdown(f"#### Clienti in Sequenza - Autista **{driver}**")
                    
                    # Applichiamo lo stile colorato alla tabella
                    st.dataframe(
                        driver_assignments[[
                            'ID Prenotazione',
                            'Ora Effettiva Prelievo',
                            'Ora Fine Servizio',
                            'Ritardo Prelievo (min)',
                            'Destinazione Finale',
                            'Tempo Servizio Totale (Minuti)'
                        ]].style.set_properties(**{'background-color': driver_color, 'color': 'white'}, subset=['ID Prenotazione'])
                    )
    
    st.markdown("---")
    
    # 3. RICERCA E STORICO (La sezione della pagina secondaria che chiedevi)
    st.markdown("## 🔎 Ricerca e Storico Interattivo")
    
    tab1, tab2 = st.tabs(["Ricerca per Cliente (ID)", "Ricerca per Autista (Nome)"])
    
    with tab1:
        st.subheader("🔍 Dettagli per Cliente")
        client_id_list = [''] + assegnazioni_df['ID Prenotazione'].unique().tolist()
        selected_client_id = st.selectbox("Inserisci il Codice Identificativo del Cliente:", client_id_list)
        
        if selected_client_id:
            client_history = assegnazioni_df[assegnazioni_df['ID Prenotazione'] == selected_client_id]
            st.markdown(f"#### Dettagli del Cliente {selected_client_id}")
            st.dataframe(
                client_history[[
                    'ID Prenotazione', 
                    'Ora Prelievo Richiesta', 
                    'Ora Effettiva Prelievo', 
                    'Ritardo Prelievo (min)', 
                    'Autista Assegnato', 
                    'Stato Assegnazione'
                ]]
            )
            
    with tab2:
        st.subheader("👤 Storico Autista")
        driver_list = [''] + assigned_drivers
        selected_driver_name = st.selectbox("Inserisci il Nome dell'Operatore NCC:", driver_list)
        
        if selected_driver_name:
            driver_history = assegnazioni_df[assegnazioni_df['Autista Assegnato'] == selected_driver_name]
            st.markdown(f"#### Tutti i Viaggi Assegnati a {selected_driver_name}")
            st.dataframe(
                driver_history[[
                    'ID Prenotazione', 
                    'Ora Prelievo Richiesta', 
                    'Ora Effettiva Prelievo', 
                    'Destinazione Finale',
                    'Stato Assegnazione'
                ]]
            )