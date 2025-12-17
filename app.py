import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import re

# --- CONFIGURAZIONE ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | AI Dispatcher", page_icon="🤖")

# Palette Colori Professionale
DRIVER_COLORS = {'Andrea': '#2E7D32', 'Carlo': '#1565C0', 'Giulia': '#F9A825', 'Marco': '#C62828', 'DEFAULT': '#455A64'}
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7}
BASE_OPERATIVA = "Via dell'Aeroporto di Fiumicino, 00054 Fiumicino RM"

# --- FUNZIONE API GOOGLE ---
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
            return durata, f"{' ➡️ '.join(list(dict.fromkeys(strade))[:3])} ({distanza})", distanza
    except:
        return 30, "Percorso stimato (Errore API)", "10 km"
    return 30, "Percorso Standard", "10 km"
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import re

# --- CONFIGURAZIONE ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | Gestione Flotta", page_icon="🚐")

DRIVER_COLORS = {'Andrea': '#4CAF50', 'Carlo': '#2196F3', 'Giulia': '#FFC107', 'Marco': '#E91E63', 'DEFAULT': '#607D8B'}
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7}
BASE_OPERATIVA = "Via dell'Aeroporto di Fiumicino, 00054 Fiumicino RM"

# --- FUNZIONE API ---
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
    except:
        return 25, "Percorso stimato"
    return 25, "Percorso Standard"

# --- MOTORE DI DISPATCH CON ACCORPAMENTO ---
def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()
    
    def parse_t(t):
        if isinstance(t, str): return datetime.strptime(t.strip().replace('.', ':'), '%H:%M')
        return datetime.combine(datetime.today(), t)

    df_c['DT_Richiesta'] = df_c['Ora Arrivo'].apply(parse_t)
    df_f['DT_Disp'] = df_f['Disponibile Da (hh:mm)'].apply(parse_t)
    df_f['Posizione_Attuale'] = BASE_OPERATIVA
    df_f['Servizi'] = 0
    
    res_list = []
    assegnati = set()
    df_c = df_c.sort_values(by='DT_Richiesta')

    for idx, riga in df_c.iterrows():
        if idx in assegnati: continue
        tipo_v = str(riga['Tipo Veicolo Richiesto']).strip().capitalize()
        cap_max = CAPACITA.get(tipo_v, 3)

        # LOGICA DI ACCORPAMENTO (Grouping)
        # Cerchiamo altri passeggeri con stesso prelievo, destinazione e orario
        gruppo = df_c[(~df_c.index.isin(assegnati)) & 
                      (df_c['Indirizzo Prelievo'] == riga['Indirizzo Prelievo']) & 
                      (df_c['Destinazione Finale'] == riga['Destinazione Finale']) & 
                      (df_c['DT_Richiesta'] == riga['DT_Richiesta'])].head(cap_max)

        # Scelta autista basata su vicinanza e puntualità
        best_aut_idx = None
        min_punteggio = float('inf')
        info_temp = {}

        for f_idx, aut in df_f.iterrows():
            if str(aut['Tipo Veicolo']).strip().capitalize() != tipo_v: continue
            
            durata_v, _ = get_gmaps_info(aut['Posizione_Attuale'], riga['Indirizzo Prelievo'])
            ora_pronto = aut['DT_Disp'] + timedelta(minutes=durata_v + 10) # 10 min margine
            ritardo = max(0, (ora_pronto - riga['DT_Richiesta']).total_seconds() / 60)
            
            # Penalizziamo il ritardo molto più della distanza per garantire puntualità
            punteggio = (ritardo * 10) + durata_v 
            
            if punteggio < min_punteggio:
                min_punteggio = punteggio
                best_aut_idx = f_idx
                info_temp = {'pronto': ora_pronto, 'vuoto': durata_v, 'da': aut['Posizione_Attuale']}

        if best_aut_idx is not None:
            durata_p, itinerario_p = get_gmaps_info(riga['Indirizzo Prelievo'], riga['Destinazione Finale'])
            partenza_eff = max(riga['DT_Richiesta'], info_temp['pronto'])
            arrivo_eff = partenza_eff + timedelta(minutes=durata_p + 15)
            
            # Creiamo una riga per ogni passeggero del gruppo, ma assegnati allo stesso autista
            for g_idx in gruppo.index:
                res_list.append({
                    'Autista': df_f.at[best_aut_idx, 'Autista'],
                    'ID': df_c.at[g_idx, 'ID Prenotazione'],
                    'Mezzo': df_f.at[best_aut_idx, 'ID Veicolo'],
                    'Da': riga['Indirizzo Prelievo'],
                    'Partenza': partenza_eff.strftime('%H:%M'),
                    'A': riga['Destinazione Finale'],
                    'Arrivo': arrivo_eff.strftime('%H:%M'),
                    'Status': "PUNTUALE" if (partenza_eff - riga['DT_Richiesta']).total_seconds() <= 300 else "RITARDO",
                    'Vuoto_Min': info_temp['vuoto'],
                    'Provenienza': info_temp['da'],
                    'Itinerario': itinerario_p,
                    'Note': f"Viaggia in gruppo ({len(gruppo)} persone)"
                })
                assegnati.add(g_idx)
            
            df_f.at[best_aut_idx, 'DT_Disp'] = arrivo_eff
            df_f.at[best_aut_idx, 'Posizione_Attuale'] = riga['Destinazione Finale']

    return pd.DataFrame(res_list), df_f

# --- INTERFACCIA ---
st.title("🚐 EmiTrekAI | Operations Management")

if 'res_c' not in st.session_state:
    st.subheader("📂 Caricamento File")
    c1, c2 = st.columns(2)
    with c1: f_c = st.file_uploader("Prenotazioni", type=['xlsx'])
    with c2: f_f = st.file_uploader("Flotta", type=['xlsx'])
    if f_c and f_f:
        if st.button("ELABORA E GENERA PIANO", type="primary", use_container_width=True):
            rc, rf = run_dispatch(pd.read_excel(f_c), pd.read_excel(f_f))
            st.session_state['res_c'], st.session_state['res_f'] = rc, rf
            st.rerun()
else:
    if st.button("🔄 RESET"):
        del st.session_state['res_c']
        st.rerun()

    rc, rf = st.session_state['res_c'], st.session_state['res_f']

    # Tabella principale pulita
    st.subheader("🗓️ Cronoprogramma Corse")
    st.dataframe(rc[['Autista', 'ID', 'Mezzo', 'Da', 'Partenza', 'A', 'Arrivo', 'Status', 'Note']].style.apply(
        lambda x: [f"background-color: {DRIVER_COLORS.get(x.Autista)}; color: white" for _ in x], axis=1), use_container_width=True)

    st.divider()

    # MENU A TENDINA (Come richiesto)
    col_d, col_c = st.columns(2)
    
    with col_d:
        st.header("🕵️ Dettaglio Autista")
        sel_d = st.selectbox("Seleziona Autista per vedere i suoi spostamenti:", rf['Autista'].unique())
        for _, job in rc[rc['Autista'] == sel_d].iterrows():
            with st.expander(f"🕒 Servizio {job['ID']} - Ore {job['Partenza']}", expanded=True):
                st.write(f"🔄 Muove da: **{job['Provenienza']}**")
                st.write(f"⏱️ Tempo a vuoto: **{job['Vuoto_Min']} min**")

    with col_c:
        st.header("📍 Dettaglio Cliente")
        sel_c = st.selectbox("Seleziona ID Prenotazione:", rc['ID'].unique())
        c_info = rc[rc['ID'] == sel_c].iloc[0]
        st.info(f"🛣️ **Percorso Reale:** {c_info['Itinerario']}")
        st.success(f"📌 **Nota Logistica:** {c_info['Note']}")