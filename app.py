import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import re

# --- CONFIGURAZIONE ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | SaaS Dispatcher", page_icon="🚐")

DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722']
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7}
BASE_DEFAULT = "Via dell'Aeroporto di Fiumicino, 00054 Fiumicino RM"

# --- FUNZIONE API (CON IL TUO BLOCCO DI ERRORE) ---
def get_gmaps_info(origin, destination):
    try:
        if "Maps_API_KEY" not in st.secrets:
            return 30, "ERRORE: Maps_API_KEY non trovata nei Secrets"
        
        api_key = st.secrets["Maps_API_KEY"]
        gmaps = googlemaps.Client(key=api_key)
        
        res = gmaps.directions(origin, destination, mode="driving", language="it", departure_time=datetime.now())
        
        if res:
            leg = res[0]['legs'][0]
            durata = int(leg['duration_in_traffic']['value'] / 60)
            distanza = leg['distance']['text']
            steps = [re.sub('<[^<]+?>', '', s['html_instructions']) for s in leg['steps']]
            itinerario = " ➡️ ".join([s.split("verso")[0].strip() for s in steps if any(k in s for k in ["Via", "Viale", "A91", "Raccordo", "Autostrada"])][:3])
            return durata, f"{itinerario} ({distanza})"
            
    except Exception as e:
        # Blocco richiesto per visualizzare l'errore esatto a schermo
        st.error(f"ERRORE GOOGLE MAPS: {str(e)}")
        return 30, f"Errore: {str(e)}"
        
    return 30, "Percorso non calcolato"

# --- MOTORE DI DISPATCH UNIVERSALE ---
def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()
    
    def parse_t(t):
        if isinstance(t, str): return datetime.strptime(t.strip().replace('.', ':'), '%H:%M')
        return datetime.combine(datetime.today(), t)

    df_c['DT_Richiesta'] = df_c['Ora Arrivo'].apply(parse_t)
    df_f['DT_Disp'] = df_f['Disponibile Da (hh:mm)'].apply(parse_t)
    df_f['Pos_Attuale'] = BASE_DEFAULT
    df_f['Pax_Oggi'] = 0
    df_f['Last_Time'] = pd.NaT
    
    res_list = []
    df_c = df_c.sort_values(by='DT_Richiesta')

    for _, riga in df_c.iterrows():
        tipo_v = str(riga['Tipo Veicolo Richiesto']).strip().capitalize()
        cap_max = CAPACITA.get(tipo_v, 3)
        
        best_aut_idx = None
        min_ritardo = float('inf')
        match_info = {}

        for f_idx, aut in df_f.iterrows():
            if str(aut['Tipo Veicolo']).strip().capitalize() != tipo_v: continue
            
            # Logica Pooling: Stesso autista per stessa destinazione/ora
            is_pooling = (aut['Pos_Attuale'] == riga['Destinazione Finale'] and 
                          aut['Last_Time'] == riga['DT_Richiesta'] and 
                          aut['Pax_Oggi'] < cap_max)

            if is_pooling:
                best_aut_idx = f_idx
                match_info = {'pronto': riga['DT_Richiesta'], 'vuoto': 0, 'da': "Inviato con gruppo"}
                break

            dur_v, _ = get_gmaps_info(aut['Pos_Attuale'], riga['Indirizzo Prelievo'])
            ora_pronto = aut['DT_Disp'] + timedelta(minutes=dur_v + 10)
            ritardo = max(0, (ora_pronto - riga['DT_Richiesta']).total_seconds() / 60)
            
            if ritardo < min_ritardo:
                min_ritardo = ritardo
                best_aut_idx = f_idx
                match_info = {'pronto': ora_pronto, 'vuoto': dur_v, 'da': aut['Pos_Attuale']}

        if best_aut_idx is not None:
            dur_p, itinerario_p = get_gmaps_info(riga['Indirizzo Prelievo'], riga['Destinazione Finale'])
            partenza_eff = max(riga['DT_Richiesta'], match_info['pronto'])
            arrivo_eff = partenza_eff + timedelta(minutes=dur_p + 15)

            res_list.append({
                'Autista': df_f.at[best_aut_idx, 'Autista'],
                'ID': riga['ID Prenotazione'],
                'Mezzo': df_f.at[best_aut_idx, 'ID Veicolo'],
                'Da': riga['Indirizzo Prelievo'],
                'Partenza': partenza_eff.strftime('%H:%M'),
                'A': riga['Destinazione Finale'],
                'Arrivo': arrivo_eff.strftime('%H:%M'),
                'Status': "PUNTUALE" if (partenza_eff <= riga['DT_Richiesta'] + timedelta(minutes=5)) else f"RITARDO",
                'Itinerario': itinerario_p,
                'Provenienza': match_info['da']
            })
            
            df_f.at[best_aut_idx, 'DT_Disp'] = arrivo_eff
            df_f.at[best_aut_idx, 'Pos_Attuale'] = riga['Destinazione Finale']
            df_f.at[best_aut_idx, 'Last_Time'] = riga['DT_Richiesta']
            df_f.at[best_aut_idx, 'Pax_Oggi'] += 1

    return pd.DataFrame(res_list)

# --- INTERFACCIA ---
st.title("🚐 EmiTrekAI | SaaS Dispatcher Pro")

if 'risultati' not in st.session_state:
    st.subheader("📂 Caricamento File Excel")
    col1, col2 = st.columns(2)
    with col1: f_c = st.file_uploader("Upload Prenotazioni", type=['xlsx'])
    with col2: f_f = st.file_uploader("Upload Flotta", type=['xlsx'])
    
    if f_c and f_f:
        if st.button("ELABORA E CALCOLA", type="primary", use_container_width=True):
            st.session_state['risultati'] = run_dispatch(pd.read_excel(f_c), pd.read_excel(f_f))
            st.rerun()
else:
    # Una volta elaborato, il caricamento scompare
    if st.button("🔄 CARICA NUOVI DATI"):
        del st.session_state['risultati']; st.rerun()

    df = st.session_state['risultati']
    unique_drivers = df['Autista'].unique()
    color_map = {d: DRIVER_COLORS[i % len(DRIVER_COLORS)] for i, d in enumerate(unique_drivers)}

    st.subheader("🗓️ Cronoprogramma Clienti (Dettagliato)")
    st.dataframe(df[['Autista', 'ID', 'Mezzo', 'Da', 'Partenza', 'A', 'Arrivo', 'Status']].style.apply(
        lambda x: [f"background-color: {color_map.get(x.Autista)}; color: white; font-weight: bold" for _ in x], axis=1), use_container_width=True)

    st.divider()
    
    c_aut, c_cli = st.columns(2)
    with c_aut:
        st.header("🕵️ Dettaglio Autista")
        sel_aut = st.selectbox("Scegli Autista:", unique_drivers)
        for _, r in df[df['Autista'] == sel_aut].iterrows():
            with st.expander(f"Servizio {r['ID']} - Partenza {r['Partenza']}", expanded=True):
                st.write(f"📍 Proviene da: **{r['Provenienza']}**")
    
    with c_cli:
        st.header("📍 Dettaglio Cliente")
        sel_id = st.selectbox("Scegli ID Prenotazione:", df['ID'].unique())
        info = df[df['ID'] == sel_id].iloc[0]
        st.info(f"🛣️ **Itinerario Google:** {info['Itinerario']}")