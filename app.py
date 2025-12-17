import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta
import numpy as np
from io import BytesIO

# FIX PER STREAMLIT CLOUD: disabilita warning e chained assignment
pd.options.mode.chained_assignment = None

# --- CONFIGURAZIONE GENERALE ---
st.set_page_config(layout="wide", page_title="EmiTrekAI: VOM", page_icon="🗓️")

# Inizializza lo stato in modo sicuro
if 'processed_data' not in st.session_state:
    st.session_state['processed_data'] = False
    st.session_state['assegnazioni_complete'] = None
    st.session_state['flotta_risorse'] = None
    st.session_state['authenticated'] = False
    st.session_state['user_role'] = None

# --- MAPPATURA COLORI E EMOJI ---
DRIVER_COLORS = {
    'Andrea': '#4CAF50', 'Carlo': '#2199F3', 'Giulia': '#FFC107',
    'Marco': '#E91E63', 'Luca': '#00BCD4', 'Sara': '#FF5722',
    'Elena': '#673AB7', 'DEFAULT': '#B0BEC5'
}

VEHICLE_EMOJIS = {
    'Berlina': '🚗', 'Minivan': '🚐', 'Suv': '🚙', 'Default': '❓' 
}

# --- STILI CSS ---
st.markdown(
    """
    <style>
    .stApp { background-color: #F0F8FF; }
    .big-font { font-size:20px !important; font-weight: bold; }
    .card-title-font { font-size: 16px !important; font-weight: bold; margin-bottom: 5px; }
    .driver-card { padding: 10px; border-radius: 8px; box-shadow: 1px 1px 5px rgba(0,0,0,0.1); margin-bottom: 10px; color: white; }
    .driver-card p { font-size: 13px; margin: 0; }
    </style>
    """,
    unsafe_allow_html=True
)

# --- FUNZIONI DI SERVIZIO ---
def check_credentials(username, password):
    if 'users' not in st.secrets:
        st.error("Errore: Configura i 'Secrets' su Streamlit Cloud (file secrets.toml).")
        return False, None
    if username in st.secrets.users:
        user_data = st.secrets.users[username]
        if user_data.password == password:
            return True, user_data.role
    return False, None

def to_time(val):
    if isinstance(val, datetime): return val.time()
    if isinstance(val, time): return val
    if isinstance(val, str): 
        for fmt in ('%H:%M', '%H.%M'):
            try: return datetime.strptime(val, fmt).time()
            except ValueError: continue
    return time(0, 0)

def time_to_minutes(t):
    return t.hour * 60 + t.minute

# --- LOGICA DI SCHEDULAZIONE (BILANCIATA) ---
def run_scheduling(df_clienti, df_flotta):
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
    df_risorse['Servizi Assegnati'] = 0 
    
    assegnazioni_df['Ora Prelievo Richiesta'] = assegnazioni_df['Ora Arrivo'].apply(to_time)
    assegnazioni_df = assegnazioni_df.sort_values(by='Ora Prelievo Richiesta').reset_index(drop=True)
    
    for index, cliente in assegnazioni_df.iterrows():
        ora_richiesta = cliente['Ora Prelievo Richiesta']
        veicolo_richiesto = str(cliente['Tipo Veicolo Richiesto']).capitalize()
        
        try:
            durata = int(cliente['Tempo Servizio Totale (Minuti)'])
        except: continue
        
        # Filtra autisti compatibili
        candidati = df_risorse[
            (df_risorse['Tipo Veicolo'] == veicolo_richiesto) & 
            (df_risorse['Disponibile Fino (hh:mm)'].apply(time_to_minutes) >= time_to_minutes(ora_richiesta))
        ].copy()
        
        if candidati.empty: continue
        
        # Calcola ritardo e bilanciamento
        t_richiesto = time_to_minutes(ora_richiesta)
        candidati['Ritardo'] = (candidati['Prossima Disponibilità'].apply(time_to_minutes) - t_richiesto).clip(lower=0)
        
        # Scelta: Priorità a meno ritardo, poi a chi ha lavorato meno (bilanciamento)
        scelto = candidati.sort_values(by=['Ritardo', 'Servizi Assegnati']).iloc[0]
        
        ritardo_min = int(scelto['Ritardo'])
        partenza_effettiva = (datetime.combine(datetime.today(), ora_richiesta) + timedelta(minutes=ritardo_min)).time()
        fine_servizio = (datetime.combine(datetime.today(), partenza_effettiva) + timedelta(minutes=durata)).time()
        
        if fine_servizio <= scelto['Disponibile Fino (hh:mm)']:
            assegnazioni_df.loc[index, 'Autista Assegnato'] = scelto['Autista']
            assegnazioni_df.loc[index, 'Stato Assegnazione'] = 'ASSEGNATO'
            assegnazioni_df.loc[index, 'Ora Effettiva Prelievo'] = partenza_effettiva
            assegnazioni_df.loc[index, 'Ritardo Prelievo (min)'] = ritardo_min
            
            df_risorse.loc[df_risorse['ID Veicolo'] == scelto['ID Veicolo'], 'Prossima Disponibilità'] = fine_servizio
            df_risorse.loc[df_risorse['ID Veicolo'] == scelto['ID Veicolo'], 'Servizi Assegnati'] += 1

    st.session_state['assegnazioni_complete'] = assegnazioni_df
    st.session_state['flotta_risorse'] = df_risorse
    st.session_state['processed_data'] = True

# --- GENERATORE VOS (Virtual Operations Summary) ---
def generate_vos_report(driver_name, driver_df, resources_df):
    info = resources_df[resources_df['Autista'] == driver_name].iloc[0]
    report = f"### 📊 VOS: Riepilogo Analitico Operatore {driver_name}\n\n"
    
    if driver_df.empty:
        return report + "Nessun servizio assegnato per questo turno."

    report += f"**Analisi Operativa:** {driver_name} gestisce **{len(driver_df)} servizi** con veicolo **{info['Tipo Veicolo']}**.\n\n"
    report += "**Dettaglio Passaggi:**\n"
    
    for i, row in driver_df.iterrows():
        ritardo = f" (+{row['Ritardo Prelievo (min)']}m ritardo)" if row['Ritardo Prelievo (min)'] > 0 else ""
        report += f"- {row['Ora Effettiva Prelievo'].strftime('%H:%M')}{ritardo}: Prelievo Cliente **{row['ID Prenotazione']}** da {row['Indirizzo Prelievo']} a {row['Destinazione Finale']}.\n"
    
    report += f"\n**Status Finale:** Disponibilità prevista dalle ore **{info['Prossima Disponibilità'].strftime('%H:%M')}**."
    return report

# --- INTERFACCIA UTENTE ---
if not st.session_state['authenticated']:
    st.title("🔐 Accesso EmiTrekAI")
    user = st.text_input("Username")
    pw = st.text_input("Password", type="password")
    if st.button("Login"):
        auth, role = check_credentials(user, pw)
        if auth:
            st.session_state['authenticated'] = True
            st.session_state['user_role'] = role
            st.rerun()
        else:
            st.error("Credenziali non valide")
else:
    if st.sidebar.button("Logout"):
        st.session_state['authenticated'] = False
        st.rerun()

    if not st.session_state['processed_data']:
        st.title("EmiTrekAI: Virtual Operations Manager")
        if st.session_state['user_role'] == 'admin':
            c1, c2 = st.columns(2)
            with c1: f_cli = st.file_uploader("Prenotazioni", type=['xlsx', 'csv'])
            with c2: f_flo = st.file_uploader("Flotta", type=['xlsx', 'csv'])
            
            if f_cli and f_flo:
                df_c = pd.read_excel(f_cli) if f_cli.name.endswith('xlsx') else pd.read_csv(f_cli)
                df_f = pd.read_excel(f_flo) if f_flo.name.endswith('xlsx') else pd.read_csv(f_flo)
                if st.button("Elabora Turni"):
                    run_scheduling(df_c, df_f)
                    st.rerun()
        else:
            st.info("Benvenuto. In attesa del caricamento dati dall'amministratore.")
    else:
        # DASHBOARD
        st.title("✨ Dashboard Operativa")
        df_res = st.session_state['flotta_risorse']
        df_ass = st.session_state['assegnazioni_complete']
        
        # Schede Autisti
        cols = st.columns(len(df_res))
        for i, row in df_res.iterrows():
            with cols[i]:
                colore = DRIVER_COLORS.get(row['Autista'], '#B0BEC5')
                st.markdown(f"""<div class='driver-card' style='background:{colore}'>
                <p class='card-title-font'>{row['Autista']} {VEHICLE_EMOJIS.get(row['Tipo Veicolo'], '❓')}</p>
                <p>Servizi: {row['Servizi Assegnati']}</p>
                <p>Libero: {row['Prossima Disponibilità'].strftime('%H:%M')}</p>
                </div>""", unsafe_allow_html=True)

        # Tabella Globale
        st.markdown("---")
        st.subheader("Sequenza Servizi")
        st.dataframe(df_ass[df_ass['Stato Assegnazione'] == 'ASSEGNATO'], use_container_width=True)

        # Report Individuale
        st.markdown("---")
        autista_sel = st.selectbox("Seleziona Autista per Report VOS", df_res['Autista'])
        driver_data = df_ass[df_ass['Autista Assegnato'] == autista_sel]
        st.info(generate_vos_report(autista_sel, driver_data, df_res))
        
        if st.button("Reset Dati"):
            st.session_state['processed_data'] = False
            st.rerun()