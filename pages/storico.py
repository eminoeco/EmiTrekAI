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

# --- MAPPATURA COLORI ---
# Colori per i tipi di veicolo (usati nel colore del testo o evidenziazione)
VEHICLE_COLORS = {
    'Berlina': '#2ecc71', # Verde per le berline (come Andrea)
    'Minivan': '#3498db', # Blu per i minivan (come Carlo)
    'Bus': '#f39c12'      # Arancione
}

# Funzione per calcolare l'Ora Fine Servizio
def calculate_end_time(row):
    try:
        start_dt = datetime.combine(datetime.today(), row['Ora Effettiva Prelievo'])
        end_dt = start_dt + timedelta(minutes=int(row['Tempo Servizio Totale (Minuti)']))
        return end_dt.time()
    except:
        return time(0, 0) # Ritorna 00:00 in caso di errore

# Funzione per colorare le intestazioni dei DataFrames (per coerenza)
def color_header(text, color):
    return f'<h4 style="color: {color};">{text}</h4>'


# --- INIZIO DELLA PAGINA DI VISUALIZZAZIONE ---
if 'assegnazioni_complete' not in st.session_state:
    st.warning("Per favore, torna alla pagina principale per caricare i file e avviare il calcolo.")
else:
    assegnazioni_df = st.session_state['assegnazioni_complete']
    df_risorse = st.session_state['flotta_risorse']
    
    st.markdown("## 🤩 Risultati di Ottimizzazione EmiTrekAI", unsafe_allow_html=True)
    st.markdown("### La tua flotta sta lavorando in modo intelligente!")
    st.markdown("---")
    
    # 1. RIEPILOGO ASSEGNAZIONI
    st.markdown("### 📊 Riepilogo Assegnazioni e Ritardi")
    st.dataframe(
        assegnazioni_df[[
            'ID Prenotazione', 
            'Ora Prelievo Richiesta', 
            'Ora Effettiva Prelievo', 
            'Ritardo Prelievo (min)',
            'Tipo Veicolo Richiesto', 
            'Autista Assegnato', 
            'Stato Assegnazione'
        ]].sort_values(by='Ora Prelievo Richiesta')
    )
    
    # 2. STATO FLOTTA (CON COLORI)
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

    # 3. SEQUENZA OPERATIVA DETTAGLIATA (CON EXPANDER E COLORI COERENTI)
    st.markdown("## 🗓️ Sequenza Operativa Dettagliata per Autista")

    # Ottieni l'elenco degli autisti assegnati che hanno un colore mappato
    assigned_drivers = assegnazioni_df['Autista Assegnato'].dropna().unique().tolist()

    if assigned_drivers:
        
        for driver in assigned_drivers:
            driver_color = VEHICLE_COLORS.get(driver_assignments['Tipo Veicolo Richiesto'].iloc[0].capitalize(), '#95a5a6')
            
            # Filtra i viaggi assegnati a questo autista
            driver_assignments = assegnazioni_df[
                (assegnazioni_df['Autista Assegnato'] == driver) &
                (assegnazioni_df['Stato Assegnazione'] == 'ASSEGNATO')
            ].sort_values(by='Ora Effettiva Prelievo').reset_index(drop=True)
            
            if not driver_assignments.empty:
                
                # Calcola l'Ora Fine Servizio e aggiunge la colonna
                driver_assignments['Ora Fine Servizio'] = driver_assignments.apply(calculate_end_time, axis=1)

                # Usiamo un expander (cartella)
                with st.expander(f"🚗 {driver} ({driver_assignments.shape[0]} servizi) - [Tipo: {driver_assignments['Tipo Veicolo Richiesto'].iloc[0]}]", expanded=False):
                    
                    st.markdown(f"#### Clienti in Sequenza - Autista **{driver}**")
                    
                    # Applichiamo lo stile colorato alla tabella per rendere l'esperienza più amichevole
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
    
    # 4. RIEPILOGO CLIENTI NON ASSEGNATI (Per completezza operativa)
    non_assegnati = assegnazioni_df[assegnazioni_df['Stato Assegnazione'] == 'NON ASSEGNATO']
    if not non_assegnati.empty:
        st.error("🚨 Clienti NON ASSEGNATI - Nessuna risorsa disponibile o turno non coperto!")
        st.dataframe(non_assegnati[['ID Prenotazione', 'Ora Prelievo Richiesta', 'Tipo Veicolo Richiesto', 'Stato Assegnazione']])