import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time as dt_time
import googlemaps
import vertexai
from vertexai.generative_models import GenerativeModel
import tempfile, json, os

# --- 1. CONFIGURAZIONE VERTEX AI (EUROPE-WEST4) ---
if "VERTEX_READY" not in st.session_state:
    try:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            json.dump(dict(st.secrets["gcp_service_account"]), f)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = f.name
        vertexai.init(project=st.secrets["gcp_service_account"]["project_id"], location="europe-west4")
        st.session_state["vertex_model"] = GenerativeModel("gemini-1.5-flash")
        st.session_state["VERTEX_READY"] = True
    except Exception as e:
        st.error(f"Errore critico Vertex AI: {e}")

model = st.session_state.get("vertex_model")

# --- 2. GESTIONE TEMPI REALI ---
def get_metrics_real(origin, dest):
    try:
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, dest, mode="driving", departure_time=datetime.now())
        if not res: return None, "N/D"
        
        g_min = int(res[0]['legs'][0].get('duration_in_traffic', res[0]['legs'][0]['duration'])['value'] / 60)
        dist = res[0]['legs'][0]['distance']['text']
        
        # Validazione AI per il traffico di Roma
        prompt = f"Tratta Roma: {origin}->{dest}. Maps dice {g_min} min. Dimmi solo il numero dei minuti reali considerando traffico attuale."
        ai_res = model.generate_content(prompt)
        final_t = int(''.join(filter(str.isdigit, ai_res.text)))
        return final_t, dist
    except Exception:
        return 35, "Stima" # Valore di fallback se le API sono bloccate

# --- 3. LOGICA DISPATCH + POOLING ---
def run_dispatch(df_c, df_f):
    # Pulizia nomi colonne
    df_c.columns = df_c.columns.str.strip(); df_f.columns = df_f.columns.str.strip()
    
    # Rilevamento automatico
    c_id = next((c for c in df_c.columns if 'ID' in c.upper()), df_c.columns[0])
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
        
        assigned = False
        for idx, f in df_f.iterrows():
            # Controllo Tipo Veicolo
            if str(f['Tipo Veicolo']).upper() != str(r[c_tipo]).upper(): continue
            
            # --- LOGICA POOLING ---
            # Se l'autista sta andando nella stessa direzione ed è entro 20 min di gap
            is_pooling = False
            if f['Pos'] == r[c_prel] and abs((f['DT_A'] - r['DT_T']).total_seconds()/60) < 20:
                is_pooling = True

            t_vuoto, _ = get_metrics_real(f['Pos'], r[c_prel])
            t_pieno, dist = get_metrics_real(r[c_prel], r[c_dest])

            # Calcolo Tempi Tecnici (10m prelievo + 10m scarico)
            ready_customer = f['DT_A'] + timedelta(minutes=(0 if is_pooling else t_vuoto) + 10)
            start_run = max(r['DT_T'], ready_customer)
            end_run = start_run + timedelta(minutes=t_pieno + 10)
            
            ritardo = int(max(0, (ready_customer - r['DT_T']).total_seconds() / 60))

            results.append({
                'Autista': f[f_aut], 'ID': r[c_id], 'Orario': r[c_ora],
                'Da': r[c_prel], 'A': r[c_dest],
                'Inizio Effettivo': start_run.strftime('%H:%M'),
                'Fine Servizio': end_run.strftime('%H:%M'),
                'Status': "🟢 OK" if ritardo <= 2 else f"🔴 RITARDO {ritardo} min",
                'Distanza': dist, 'Note': "POOLING" if is_pooling else ""
            })
            
            df_f.at[idx, 'DT_A'] = end_run
            df_f.at[idx, 'Pos'] = r[c_dest]
            assigned = True
            break
            
    bar.empty()
    return pd.DataFrame(results)

# --- 4. INTERFACCIA ---
st.title("🚐 EmiTrekAI | Dispatch & Pooling")
up1 = st.file_uploader("Prenotazioni (.xlsx)")
up2 = st.file_uploader("Flotta (.xlsx)")

if up1 and up2 and st.button("🚀 ELABORA PIANO VIAGGI"):
    res = run_dispatch(pd.read_excel(up1), pd.read_excel(up2))
    st.dataframe(res, use_container_width=True)import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time as dt_time
import googlemaps
import vertexai
from vertexai.generative_models import GenerativeModel
import tempfile, json, os

# --- 1. CONFIGURAZIONE VERTEX AI (EUROPE-WEST4) ---
if "VERTEX_READY" not in st.session_state:
    try:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            json.dump(dict(st.secrets["gcp_service_account"]), f)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = f.name
        vertexai.init(project=st.secrets["gcp_service_account"]["project_id"], location="europe-west4")
        st.session_state["vertex_model"] = GenerativeModel("gemini-1.5-flash")
        st.session_state["VERTEX_READY"] = True
    except Exception as e:
        st.error(f"Errore critico Vertex AI: {e}")

model = st.session_state.get("vertex_model")

# --- 2. GESTIONE TEMPI REALI ---
def get_metrics_real(origin, dest):
    try:
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, dest, mode="driving", departure_time=datetime.now())
        if not res: return None, "N/D"
        
        g_min = int(res[0]['legs'][0].get('duration_in_traffic', res[0]['legs'][0]['duration'])['value'] / 60)
        dist = res[0]['legs'][0]['distance']['text']
        
        # Validazione AI per il traffico di Roma
        prompt = f"Tratta Roma: {origin}->{dest}. Maps dice {g_min} min. Dimmi solo il numero dei minuti reali considerando traffico attuale."
        ai_res = model.generate_content(prompt)
        final_t = int(''.join(filter(str.isdigit, ai_res.text)))
        return final_t, dist
    except Exception:
        return 35, "Stima" # Valore di fallback se le API sono bloccate

# --- 3. LOGICA DISPATCH + POOLING ---
def run_dispatch(df_c, df_f):
    # Pulizia nomi colonne
    df_c.columns = df_c.columns.str.strip(); df_f.columns = df_f.columns.str.strip()
    
    # Rilevamento automatico
    c_id = next((c for c in df_c.columns if 'ID' in c.upper()), df_c.columns[0])
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
        
        assigned = False
        for idx, f in df_f.iterrows():
            # Controllo Tipo Veicolo
            if str(f['Tipo Veicolo']).upper() != str(r[c_tipo]).upper(): continue
            
            # --- LOGICA POOLING ---
            # Se l'autista sta andando nella stessa direzione ed è entro 20 min di gap
            is_pooling = False
            if f['Pos'] == r[c_prel] and abs((f['DT_A'] - r['DT_T']).total_seconds()/60) < 20:
                is_pooling = True

            t_vuoto, _ = get_metrics_real(f['Pos'], r[c_prel])
            t_pieno, dist = get_metrics_real(r[c_prel], r[c_dest])

            # Calcolo Tempi Tecnici (10m prelievo + 10m scarico)
            ready_customer = f['DT_A'] + timedelta(minutes=(0 if is_pooling else t_vuoto) + 10)
            start_run = max(r['DT_T'], ready_customer)
            end_run = start_run + timedelta(minutes=t_pieno + 10)
            
            ritardo = int(max(0, (ready_customer - r['DT_T']).total_seconds() / 60))

            results.append({
                'Autista': f[f_aut], 'ID': r[c_id], 'Orario': r[c_ora],
                'Da': r[c_prel], 'A': r[c_dest],
                'Inizio Effettivo': start_run.strftime('%H:%M'),
                'Fine Servizio': end_run.strftime('%H:%M'),
                'Status': "🟢 OK" if ritardo <= 2 else f"🔴 RITARDO {ritardo} min",
                'Distanza': dist, 'Note': "POOLING" if is_pooling else ""
            })
            
            df_f.at[idx, 'DT_A'] = end_run
            df_f.at[idx, 'Pos'] = r[c_dest]
            assigned = True
            break
            
    bar.empty()
    return pd.DataFrame(results)

# --- 4. INTERFACCIA ---
st.title("🚐 EmiTrekAI | Dispatch & Pooling")
up1 = st.file_uploader("Prenotazioni (.xlsx)")
up2 = st.file_uploader("Flotta (.xlsx)")

if up1 and up2 and st.button("🚀 ELABORA PIANO VIAGGI"):
    res = run_dispatch(pd.read_excel(up1), pd.read_excel(up2))
    st.dataframe(res, use_container_width=True)