import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time as dt_time
import googlemaps
import vertexai
from vertexai.generative_models import GenerativeModel
import tempfile, json, os

# --- 1. INIZIALIZZAZIONE VERTEX AI (LOCATION EUROPE-WEST4) ---
if "VERTEX_READY" not in st.session_state:
    try:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            json.dump(dict(st.secrets["gcp_service_account"]), f)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = f.name
        vertexai.init(project=st.secrets["gcp_service_account"]["project_id"], location="europe-west4")
        st.session_state["vertex_model"] = GenerativeModel("gemini-1.5-flash")
        st.session_state["VERTEX_READY"] = True
    except Exception as e:
        st.error(f"Errore Vertex AI: {e}")

model = st.session_state.get("vertex_model")

# --- 2. FUNZIONE PARSING ORARI (RISOLVE IL PROBLEMA LETTURA EXCEL) ---
def parse_excel_time(t):
    if isinstance(t, (datetime, pd.Timestamp)): return t
    if isinstance(t, dt_time): return datetime.combine(datetime.today(), t)
    t_str = str(t).replace('.', ':').strip()
    try: return datetime.combine(datetime.today(), datetime.strptime(t_str, '%H:%M').time())
    except: return datetime.now()

# --- 3. MOTORE DI CALCOLO REALE (MAPS + VERTEX) ---
def get_metrics_real(origin, dest):
    try:
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, dest, mode="driving", departure_time=datetime.now())
        if not res: return 30, "N/D", False
        leg = res[0]['legs'][0]
        g_min = int(leg.get('duration_in_traffic', leg['duration'])['value'] / 60)
        prompt = f"Dispatcher Roma: tratta {origin}->{dest}. Maps stima {g_min} min. Rispondi SOLO col numero intero dei minuti."
        ai_res = model.generate_content(prompt)
        final_t = int(''.join(filter(str.isdigit, ai_res.text)))
        return final_t, leg['distance']['text'], True
    except: return 30, "N/D", False

# --- 4. LOGICA DISPATCH (FIX RITARDI E COLONNE) ---
def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()
    
    # Rilevamento Colonne
    c_ora = next((c for c in df_c.columns if 'ORA' in c.upper()), df_c.columns[1])
    c_prel = next((c for c in df_c.columns if 'PRELIEVO' in c.upper()), df_c.columns[2])
    c_dest = next((c for c in df_c.columns if 'DESTINAZIONE' in c.upper()), df_c.columns[3])
    f_disp = next((c for c in df_f.columns if 'DISPONIBILE' in c.upper()), df_f.columns[2])

    df_c['DT_TARGET'] = df_c[c_ora].apply(parse_excel_time)
    df_f['DT_AVAIL'] = df_f[f_disp].apply(parse_excel_time)
    df_f['Pos'] = "BASE"

    results = []
    progress = st.progress(0)
    for i, (_, r) in enumerate(df_c.iterrows()):
        progress.progress((i + 1) / len(df_c))
        for idx, f in df_f.iterrows():
            if f['Tipo Veicolo'].strip().upper() != r['Tipo Veicolo Richiesto'].strip().upper(): continue
            
            dv, _, _ = get_metrics_real(f['Pos'], r[c_prel])
            dp, dist, _ = get_metrics_real(r[c_prel], r[c_dest])

            # CALCOLO PRECISO: Disponibilità + Viaggio Vuoto + 10m Prelievo
            ready_at_customer = f['DT_AVAIL'] + timedelta(minutes=dv + 10)
            
            # Se l'autista è pronto PRIMA dell'orario richiesto, parte all'orario richiesto
            # Se è pronto DOPO, parte quando arriva (generando il ritardo)
            start_time = max(r['DT_TARGET'], ready_at_customer)
            end_time = start_time + timedelta(minutes=dp + 10)
            
            delay_min = int(max(0, (ready_at_customer - r['DT_TARGET']).total_seconds() / 60))

            results.append({
                'Autista': f['Autista'], 'ID': r['ID'], 'Da': r[c_prel], 
                'Inizio': start_time.strftime('%H:%M'), 'Fine': end_time.strftime('%H:%M'),
                'Status': "🟢 OK" if delay_min <= 2 else f"🔴 RITARDO {delay_min} min"
            })
            df_f.at[idx, 'DT_AVAIL'] = end_time
            df_f.at[idx, 'Pos'] = r[c_dest]
            break
    progress.empty()
    return pd.DataFrame(results)

# --- 5. UI ---
st.title("🚐 EmiTrekAI | Fix Dispatch")
f1 = st.file_uploader("Prenotazioni")
f2 = st.file_uploader("Flotta")

if f1 and f2 and st.button("🚀 AVVIA"):
    df_res = run_dispatch(pd.read_excel(f1), pd.read_excel(f2))
    st.dataframe(df_res, use_container_width=True)