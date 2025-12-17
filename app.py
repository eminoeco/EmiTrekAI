import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import re

# --- CONFIGURAZIONE ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | Gestione Pro", page_icon="🚐")
pd.options.mode.chained_assignment = None

# Colori assegnati
DRIVER_COLORS = {'Andrea': '#4CAF50', 'Carlo': '#2196F3', 'Giulia': '#FFC107', 'Marco': '#E91E63', 'DEFAULT': '#607D8B'}
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7}
BASE_OPERATIVA = "Via dell'Aeroporto di Fiumicino, 00054 Fiumicino RM"

# --- FUNZIONE API GOOGLE MAPS ---
def get_gmaps_info(origin, destination):
    try:
        api_key = st.secrets["GOOGLE_MAPS_API_KEY"]
        gmaps = googlemaps.Client(key=api_key)
        res = gmaps.directions(origin, destination, mode="driving", language="it", departure_time=datetime.now())
        if res:
            leg = res[0]['legs'][0]
            durata = int(leg['duration_in_traffic']['value'] / 60)
            steps = [re.sub('<[^<]+?>', '', s['html_instructions']).split("verso")[0].strip() for s in leg['steps']]
            strade = [s for s in steps if any(k in s for k in ["Raccordo", "Uscita", "Via", "Viale", "A91"])]
            return durata, " ➡️ ".join(list(dict.fromkeys(strade))[:3])
    except:
        return 20, "Percorso Standard"

# --- MOTORE DI DISPATCH ---
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

        gruppo = df_c[(~df_c.index.isin(assegnati)) & (df_c['Indirizzo Prelievo'] == riga['Indirizzo Prelievo']) & 
                      (df_c['Destinazione Finale'] == riga['Destinazione Finale']) & (df_c['DT_Richiesta'] == riga['DT_Richiesta'])].head(cap_max)

        candidati = pd.concat([df_f[df_f['Servizi'] > 0], df_f[df_f['Servizi'] == 0]])
        best_aut_idx = None; min_ritardo = float('inf')

        for f_idx, aut in candidati.iterrows():
            if str(aut['Tipo Veicolo']).strip().capitalize() != tipo_v: continue
            durata_v, _ = get_gmaps_info(aut['Posizione_Attuale'], riga['Indirizzo Prelievo'])
            ora_pronto = aut['DT_Disp'] + timedelta(minutes=(15 if aut['Servizi'] > 0 else 0) + durata_v)
            ritardo = max(0, (ora_pronto - riga['DT_Richiesta']).total_seconds() / 60)
            
            if ritardo < min_ritardo:
                min_ritardo = ritardo; best_aut_idx = f_idx
                info_temp = {'pronto': ora_pronto, 'vuoto': durata_v, 'da': aut['Posizione_Attuale']}

        if best_aut_idx is not None:
            durata_p, itinerario_p = get_gmaps_info(riga['Indirizzo Prelievo'], riga['Destinazione Finale'])
            partenza_eff = max(riga['DT_Richiesta'], info_temp['pronto'])
            arrivo_eff = partenza_eff + timedelta(minutes=15 + durata_p)
            anticipo = (riga['DT_Richiesta'] - info_temp['pronto']).total_seconds() / 60

            for g_idx in gruppo.index:
                res_list.append({
                    'Autista': df_f.at[best_aut_idx, 'Autista'], 'ID': df_c.at[g_idx, 'ID Prenotazione'],
                    'Mezzo': df_f.at[best_aut_idx, 'ID Veicolo'], 'Da': riga['Indirizzo Prelievo'],
                    'Partenza': partenza_eff.strftime('%H:%M'), 'A': riga['Destinazione Finale'],
                    'Arrivo': arrivo_eff.strftime('%H:%M'), 'Status': "PUNTUALE" if min_ritardo <= 5 else f"RITARDO {int(min_ritardo)}m",
                    'Vuoto_Min': info_temp['vuoto'], 'Provenienza': info_temp['da'], 'Arrivo_Effettivo': info_temp['pronto'].strftime('%H:%M'),
                    'Anticipo': int(anticipo) if anticipo > 0 else 0, 'Itinerario': itinerario_p
                })
                assegnati.add(g_idx)
            
            df_f.at[best_aut_idx, 'DT_Disp'] = arrivo_eff
            df_f.at[best_aut_idx, 'Posizione_Attuale'] = riga['Destinazione Finale']
            df_f.at[best_aut_idx, 'Servizi'] += 1

    return pd.DataFrame(res_list), df_f

# --- INTERFACCIA ---
st.title("🚐 EmiTrekAI | Operations Management")

# Se non ci sono risultati, mostriamo lo stato flotta. Se ci sono, lo nascondiamo.
if 'res_c' not in st.session_state:
    st.subheader("🧑‍✈️ Stato Flotta Disponibile")
    st.info("Carica i file Excel per generare il piano operativo. Dopo l'elaborazione, questa sezione sparirà per pulizia.")
else:
    st.success("✅ Piano Generato. Card flotta rimosse per ottimizzare lo spazio.")

st.divider()

c1, c2 = st.columns(2)
with c1: f_c = st.file_uploader("📂 Carica Prenotazioni (Excel)", type=['xlsx'])
with c2: f_f = st.file_uploader("🚐 Carica Flotta (Excel)", type=['xlsx'])

if f_c and f_f:
    if st.button("ELABORA E GENERA REPORT", type="primary", use_container_width=True):
        dc = pd.read_excel(f_c); df = pd.read_excel(f_f)
        rc, rf = run_dispatch(dc, df)
        st.session_state['res_c'], st.session_state['res_f'] = rc, rf
        st.rerun()

if 'res_c' in st.session_state:
    rc = st.session_state['res_c']
    rf = st.session_state['res_f']

    # 1. TABELLA COLORATA
    st.subheader("🗓️ Cronoprogramma Ottimizzato")
    def color_table(row):
        color = DRIVER_COLORS.get(row['Autista'], '#607D8B')
        return [f'background-color: {color}; color: white; font-weight: bold;' for _ in row]
    
    st.dataframe(rc[['Autista', 'ID', 'Mezzo', 'Da', 'Partenza', 'A', 'Arrivo', 'Status']].style.apply(color_table, axis=1), use_container_width=True)

    st.divider()

    # 2. DIARIO DI BORDO AUTISTI
    col_aut, col_cli = st.columns(2)

    with col_aut:
        st.header("🕵️ Diario di Bordo Autisti")
        sel_d = st.selectbox("Seleziona Autista per dettagli:", rf['Autista'].unique())
        d_jobs = rc[rc['Autista'] == sel_d].sort_values(by='Partenza')
        
        for _, job in d_jobs.iterrows():
            with st.expander(f"🕒 Servizio {job['ID']} - Ore {job['Partenza']}", expanded=True):
                st.markdown(f"""
                **SPOSTAMENTO TECNICO:**
                - 🔄 Muove da: **{job['Provenienza']}**
                - ⏱️ Tempo a vuoto stimato: **{job['Vuoto_Min']} min**
                - 🏁 Arrivo al punto di carico: **{job['Arrivo_Effettivo']}**
                - ⏱️ **Anticipo sul cliente:** {job['Anticipo']} min
                """)
        
        st.subheader("🖨️ Foglio Stampabile")
        txt_print = f"FOGLIO DI SERVIZIO: {sel_d}\n" + "-"*30 + "\n"
        for _, job in d_jobs.iterrows():
            txt_print += f"[{job['Partenza']}] {job['Da']} -> {job['A']}\n(Scarico ore {job['Arrivo']})\n" + "-"*30 + "\n"
        st.text_area("Copia per stampa o messaggi:", txt_print, height=150)

    with col_cli:
        st.header("📍 Analisi Clienti AI")
        sel_c = st.selectbox("Seleziona ID Cliente:", rc['ID'].unique())
        c_info = rc[rc['ID'] == sel_c].iloc[0]
        st.markdown(f"""
        <div style="background-color: #ffffff; padding: 20px; border-radius: 10px; border-left: 10px solid {DRIVER_COLORS.get(c_info['Autista'])}; box-shadow: 2px 2px 5px rgba(0,0,0,0.1);">
            <h3>Riassunto Viaggio {sel_c}</h3>
            <p><b>PERCORSO:</b> Da {c_info['Da']} a {c_info['A']}</p>
            <p><b>ITINERARIO SUGGERITO AI:</b><br><i>{c_info['Itinerario']}</i></p>
            <hr>
            <p><b>LOGICA NCC:</b> Autista {c_info['Autista']} si posiziona con un margine di {c_info['Anticipo']} min per garantire puntualità.</p>
        </div>
        """, unsafe_allow_html=True)