import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import re

# --- CONFIGURAZIONE ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | Gestione Operativa", page_icon="🚐")
pd.options.mode.chained_assignment = None

# Colori Professionali Generici
COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722']
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7}
BASE_DEFAULT = "Via dell'Aeroporto di Fiumicino, 00054 Fiumicino RM"

# --- FUNZIONE API (Sincronizzata con Maps_API_KEY) ---
def get_gmaps_info(origin, destination):
    try:
        api_key = st.secrets["Maps_API_KEY"]
        gmaps = googlemaps.Client(key=api_key)
        res = gmaps.directions(origin, destination, mode="driving", language="it", departure_time=datetime.now())
        if res:
            leg = res[0]['legs'][0]
            durata = int(leg['duration_in_traffic']['value'] / 60)
            distanza = leg['distance']['text']
            steps = [re.sub('<[^<]+?>', '', s['html_instructions']).split("verso")[0].strip() for s in leg['steps']]
            strade = [s for s in steps if any(k in s for k in ["Via", "Viale", "A91", "Raccordo", "Autostrada"])]
            return durata, f"{' ➡️ '.join(list(dict.fromkeys(strade))[:3])} ({distanza})"
    except Exception:
        return 25, "Calcolo GPS Standard"
    return 25, "Percorso non trovato"

# --- MOTORE DI DISPATCH (OGNI CLIENTE UNA RIGA) ---
def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()
    
    def parse_t(t):
        if isinstance(t, str): return datetime.strptime(t.strip().replace('.', ':'), '%H:%M')
        return datetime.combine(datetime.today(), t)

    df_c['DT_Richiesta'] = df_c['Ora Arrivo'].apply(parse_t)
    df_f['DT_Disp'] = df_f['Disponibile Da (hh:mm)'].apply(parse_t)
    df_f['Pos_Attuale'] = BASE_DEFAULT
    
    # Inizializziamo il conteggio passeggeri per mezzo/orario
    df_f['Pax_Caricati'] = 0
    df_f['Ultimo_Servizio_Time'] = pd.NaT
    
    res_list = []
    df_c = df_c.sort_values(by='DT_Richiesta')

    for idx, riga in df_c.iterrows():
        tipo_v = str(riga['Tipo Veicolo Richiesto']).strip().capitalize()
        cap_max = CAPACITA.get(tipo_v, 3)
        
        best_aut_idx = None
        min_ritardo = float('inf')
        info_temp = {}

        # Cerca l'autista migliore
        for f_idx, aut in df_f.iterrows():
            if str(aut['Tipo Veicolo']).strip().capitalize() != tipo_v: continue
            
            # LOGICA DI OTTIMIZZAZIONE: Se l'autista sta già andando lì alla stessa ora, usa lui!
            # (Ma crea comunque una riga separata per il cliente)
            is_same_trip = (aut['Pos_Attuale'] == riga['Destinazione Finale'] and 
                            aut['Ultimo_Servizio_Time'] == riga['DT_Richiesta'] and 
                            aut['Pax_Caricati'] < cap_max)

            if is_same_trip:
                best_aut_idx = f_idx
                # Nessun tempo di viaggio a vuoto aggiuntivo
                info_temp = {'pronto': riga['DT_Richiesta'], 'vuoto': 0, 'da': "Inviato con gruppo"}
                break 

            # Altrimenti calcola il tempo per arrivare dal servizio precedente
            durata_v, _ = get_gmaps_info(aut['Pos_Attuale'], riga['Indirizzo Prelievo'])
            ora_pronto = aut['DT_Disp'] + timedelta(minutes=durata_v + 10)
            ritardo = max(0, (ora_pronto - riga['DT_Richiesta']).total_seconds() / 60)
            
            if ritardo < min_ritardo:
                min_ritardo = ritardo
                best_aut_idx = f_idx
                info_temp = {'pronto': ora_pronto, 'vuoto': durata_v, 'da': aut['Pos_Attuale']}

        if best_aut_idx is not None:
            durata_p, itinerario_p = get_gmaps_info(riga['Indirizzo Prelievo'], riga['Destinazione Finale'])
            partenza_eff = max(riga['DT_Richiesta'], info_temp['pronto'])
            arrivo_eff = partenza_eff + timedelta(minutes=durata_p + 15)

            res_list.append({
                'Autista': df_f.at[best_aut_idx, 'Autista'],
                'ID': riga['ID Prenotazione'],
                'Mezzo': df_f.at[best_aut_idx, 'ID Veicolo'],
                'Da': riga['Indirizzo Prelievo'],
                'Partenza': partenza_eff.strftime('%H:%M'),
                'A': riga['Destinazione Finale'],
                'Arrivo': arrivo_eff.strftime('%H:%M'),
                'Status': "🟢 OK" if (partenza_eff <= riga['DT_Richiesta'] + timedelta(minutes=5)) else f"🔴 RITARDO {int((partenza_eff - riga['DT_Richiesta']).total_seconds()/60)}m",
                'Itinerario': itinerario_p,
                'Provenienza': info_temp['da']
            })
            
            # Aggiorna stato autista
            df_f.at[best_aut_idx, 'DT_Disp'] = arrivo_eff
            df_f.at[best_aut_idx, 'Pos_Attuale'] = riga['Destinazione Finale']
            df_f.at[best_aut_idx, 'Ultimo_Servizio_Time'] = riga['DT_Richiesta']
            df_f.at[best_aut_idx, 'Pax_Caricati'] += 1

    return pd.DataFrame(res_list), df_f

# --- INTERFACCIA ---
st.title("🚐 EmiTrekAI | Dashboard Operativa Universale")

if 'res_c' not in st.session_state:
    st.subheader("📂 Caricamento File")
    c1, c2 = st.columns(2)
    with c1: f_c = st.file_uploader("File Prenotazioni", type=['xlsx'])
    with c2: f_f = st.file_uploader("File Flotta", type=['xlsx'])
    if f_c and f_f:
        if st.button("GENERA CRONOPROGRAMMA", type="primary", use_container_width=True):
            rc, rf = run_dispatch(pd.read_excel(f_c), pd.read_excel(f_f))
            st.session_state['res_c'], st.session_state['res_f'] = rc, rf
            st.rerun()
else:
    if st.button("🔄 RESET E NUOVO CARICAMENTO"):
        del st.session_state['res_c']; st.rerun()

    rc, rf = st.session_state['res_c'], st.session_state['res_f']
    unique_drivers = rc['Autista'].unique()
    driver_color_map = {d: COLORS[i % len(COLORS)] for i, d in enumerate(unique_drivers)}

    st.subheader("🗓️ Cronoprogramma Dettagliato (Una riga per Cliente)")
    st.dataframe(rc[['Autista', 'ID', 'Mezzo', 'Da', 'Partenza', 'A', 'Arrivo', 'Status']].style.apply(
        lambda x: [f"background-color: {driver_color_map.get(x.Autista)}; color: white; font-weight: bold" for _ in x], axis=1), use_container_width=True)

    st.divider()
    col_d, col_c = st.columns(2)
    with col_d:
        st.header("🕵️ Dettaglio Autista")
        sel_d = st.selectbox("Seleziona Autista:", unique_drivers)
        for _, j in rc[rc['Autista'] == sel_d].iterrows():
            with st.expander(f"🕒 Servizio {j['ID']} - Ore {j['Partenza']}", expanded=True):
                st.write(f"🔄 Proviene da: **{j['Provenienza']}**")

    with col_c:
        st.header("📍 Dettaglio Cliente")
        sel_c = st.selectbox("Seleziona ID Prenotazione:", rc['ID'].unique())
        c_info = rc[rc['ID'] == sel_c].iloc[0]
        st.info(f"🛣️ **Itinerario Reale Google:** {c_info['Itinerario']}")