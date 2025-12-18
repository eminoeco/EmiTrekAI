import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time as dt_time
import googlemaps
import vertexai
from vertexai.generative_models import GenerativeModel
import tempfile, json, os

# --- 1. INIZIALIZZAZIONE VERTEX AI (EUROPE-WEST4) ---
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

# --- 2. GESTIONE TEMPI REALI ---
def get_metrics_real(origin, dest):
    try:
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, dest, mode="driving", departure_time=datetime.now())
        if not res: return 30, "N/D"
        
        g_min = int(res[0]['legs'][0].get('duration_in_traffic', res[0]['legs'][0]['duration'])['value'] / 60)
        dist = res[0]['legs'][0]['distance']['text']
        
        prompt = f"Dispatcher Roma: tratta {origin}->{dest}. Maps dice {g_min} min. Dimmi solo il numero dei minuti reali."
        ai_res = model.generate_content(prompt)
        final_t = int(''.join(filter(str.isdigit, ai_res.text)))
        return final_t, dist
    except:
        return 35, "Stima"

# --- 3. LOGICA DISPATCH + POOLING ---
def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()
    
    # Rilevamento automatico colonne
    c_ora = next((c for c in df_c.columns if 'ORA' in c.upper()), df_c.columns[1])
    c_prel = next((c for c in df_c.columns if 'PRELIEVO' in c.upper()), df_c.columns[2])
    c_dest = next((c for c in df_c.columns if 'DESTINAZIONE' in c.upper()), df_c.columns[3])
    c_tipo = next((c for c in df_c.columns if 'TIPO' in c.upper()), df_c.columns[4])
    f_aut = next((c for c in df_f.columns if 'AUTISTA' in c.upper()), df_f.columns[0])
    f_disp = next((c for c in df_f.columns if 'DISPONIBILE' in c.upper()), df_f.columns[2])

    def parse_t(t):
        if isinstance(t, (datetime, pd.Timestamp)): return t
        try: return datetime.combine(datetime.today(), datetime.strptime(str(t).replace('.', ':'), '%H:%M').time())
        except: return datetime.now()

    df_c['DT_T'] = df_c[c_ora].apply(parse_t)
    df_f['DT_A'] = df_f[f_disp].apply(parse_t)
    df_f['Pos'] = "BASE"
    
    results = []
    bar = st.progress(0)
    
    for i, (_, r) in enumerate(df_c.iterrows()):
        bar.progress((i + 1) / len(df_c))
        for idx, f in df_f.iterrows():
            if str(f['Tipo Veicolo']).upper() != str(r[c_tipo]).upper(): continue
            
            # Controllo Pooling (Se l'autista è già sul posto)
            is_pooling = f['Pos'] == r[c_prel]
            
            t_vuoto, _ = (0, "") if is_pooling else get_metrics_real(f['Pos'], r[c_prel])
            t_pieno, dist = get_metrics_real(r[c_prel], r[c_dest])

            # 10m Prelievo + Viaggio + 10m Scarico
            ready_customer = f['DT_A'] + timedelta(minutes=t_vuoto + 10)
            start_run = max(r['DT_T'], ready_customer)
            end_run = start_run + timedelta(minutes=t_pieno + 10)
            
            rit = int(max(0, (ready_customer - r['DT_T']).total_seconds() / 60))

            results.append({
                'Autista': f[f_aut], 'ID': r[next(c for c in df_c.columns if 'ID' in c.upper())],
                'Da': r[c_prel], 'A': r[c_dest],
                'Inizio': start_run.strftime('%H:%M'), 'Fine': end_run.strftime('%H:%M'),
                'Status': "🟢 OK" if rit <= 2 else f"🔴 RITARDO {rit} min",
                'Note': "POOLING" if is_pooling else ""
            })
            df_f.at[idx, 'DT_A'] = end_run
            df_f.at[idx, 'Pos'] = r[c_dest]
            break
            
    bar.empty()
    return pd.DataFrame(results)

# --- 4. UI ---
st.title("🚐 EmiTrekAI | Smart Dispatch")
u1 = st.file_uploader("Prenotazioni")
u2 = st.file_uploader("Flotta")

if u1 and u2 and st.button("🚀 ELABORA"):
    df_res = run_dispatch(pd.read_excel(u1), pd.read_excel(u2))
    st.dataframe(df_res, use_container_width=True)