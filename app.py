import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time as dt_time
import googlemaps
import vertexai
from vertexai.generative_models import GenerativeModel
import tempfile, json, os

# --- 1. INIZIALIZZAZIONE VERTEX AI ---
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

# --- 2. PARSING ORARI ---
def parse_excel_time(t):
    if isinstance(t, (datetime, pd.Timestamp)): return t
    if isinstance(t, dt_time): return datetime.combine(datetime.today(), t)
    t_str = str(t).replace('.', ':').strip()
    try: return datetime.combine(datetime.today(), datetime.strptime(t_str, '%H:%M').time())
    except: return datetime.now()

# --- 3. METRICHE REALI ---
def get_metrics_real(origin, dest):
    try:
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, dest, mode="driving", departure_time=datetime.now())
        if not res: return 30, "N/D", False
        g_min = int(res[0]['legs'][0].get('duration_in_traffic', res[0]['legs'][0]['duration'])['value'] / 60)
        prompt = f"Dispatcher Roma: tratta {origin}->{dest}. Maps stima {g_min} min. Rispondi SOLO numero intero."
        ai = model.generate_content(prompt)
        return int(''.join(filter(str.isdigit, ai.text))), "OK", True
    except: return 30, "N/D", False

# --- 4. DISPATCH (FIX KEYERROR) ---
def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()
    
    # Rilevamento Flessibile (Upper/Lower/Space)
    c_id = next((c for c in df_c.columns if 'ID' in c.upper()), df_c.columns[0])
    c_ora = next((c for c in df_c.columns if 'ORA' in c.upper()), df_c.columns[1])
    c_prel = next((c for c in df_c.columns if 'PRELIEVO' in c.upper()), df_c.columns[2])
    c_dest = next((c for c in df_c.columns if 'DESTINAZIONE' in c.upper()), df_c.columns[3])
    c_tipo = next((c for c in df_c.columns if 'TIPO' in c.upper()), df_c.columns[4])
    
    f_aut = next((c for c in df_f.columns if 'AUTISTA' in c.upper()), df_f.columns[0])
    f_disp = next((c for c in df_f.columns if 'DISPONIBILE' in c.upper()), df_f.columns[2])
    f_tipo = next((c for c in df_f.columns if 'TIPO' in c.upper()), df_f.columns[1])

    df_c['DT_T'] = df_c[c_ora].apply(parse_excel_time)
    df_f['DT_A'] = df_f[f_disp].apply(parse_excel_time)
    df_f['Pos'] = "BASE"

    results = []
    bar = st.progress(0)
    for i, (_, r) in enumerate(df_c.iterrows()):
        bar.progress((i + 1) / len(df_c))
        for idx, f in df_f.iterrows():
            if f[f_tipo].strip().upper() != r[c_tipo].strip().upper(): continue
            
            dv, _, _ = get_metrics_real(f['Pos'], r[c_prel])
            dp, _, _ = get_metrics_real(r[c_prel], r[c_dest])

            ready = f['DT_A'] + timedelta(minutes=dv + 10)
            start = max(r['DT_T'], ready)
            end = start + timedelta(minutes=dp + 10)
            
            rit = int(max(0, (ready - r['DT_T']).total_seconds() / 60))

            results.append({
                'Autista': f[f_aut], 'ID': r[c_id], 'Da': r[c_prel], 
                'Inizio': start.strftime('%H:%M'), 'Fine': end.strftime('%H:%M'),
                'Status': "🟢 OK" if rit <= 2 else f"🔴 RITARDO {rit} min"
            })
            df_f.at[idx, 'DT_A'] = end
            df_f.at[idx, 'Pos'] = r[c_dest]
            break
    bar.empty()
    return pd.DataFrame(results)

# --- 5. UI ---
st.title("🚐 EmiTrekAI | Final Fix")
f1 = st.file_uploader("Prenotazioni")
f2 = st.file_uploader("Flotta")

if f1 and f2 and st.button("🚀 AVVIA"):
    df_res = run_dispatch(pd.read_excel(f1), pd.read_excel(f2))
    st.dataframe(df_res, use_container_width=True)