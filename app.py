import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import vertexai
from vertexai.generative_models import GenerativeModel
import tempfile, json, os

# --- 1. CONFIGURAZIONE ESTETICA (Ripristino SaaS) ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | Smart Dispatch", page_icon="🚐")

st.markdown("""
    <style>
    .stButton > button {
        background-color: #FF4B4B; color: white; border-radius: 20px;
        height: 3.5em; width: 100%; font-size: 18px; font-weight: bold;
    }
    .main-title { color: #1E1E1E; font-size: 40px; font-weight: 800; text-align: center; margin-bottom: 20px;}
    </style>
""", unsafe_allow_html=True)

# --- 2. GESTIONE ACCESSO ---
def check_password():
    if "password_correct" not in st.session_state:
        st.markdown('<h1 class="main-title">🔒 Accesso Riservata</h1>', unsafe_allow_html=True)
        u = st.text_input("Username", key="u_input")
        p = st.text_input("Password", type="password", key="p_input")
        if st.button("ENTRA"):
            if u in st.secrets["users"] and p == st.secrets["users"][u]["password"]:
                st.session_state["password_correct"] = True; st.rerun()
            else: st.error("Credenziali errate.")
        return False
    return True

# --- 3. INIZIALIZZAZIONE VERTEX AI (FIX LOCATION) ---
if "VERTEX_READY" not in st.session_state:
    try:
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
            json.dump(dict(st.secrets["gcp_service_account"]), f)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = f.name
        
        # Usiamo europe-west4 come visto nei tuoi screenshot di successo
        vertexai.init(
            project=st.secrets["gcp_service_account"]["project_id"], 
            location="europe-west4" 
        )
        st.session_state["vertex_model"] = GenerativeModel("gemini-1.5-flash")
        st.session_state["VERTEX_READY"] = True
    except Exception as e:
        st.error(f"Errore inizializzazione: {e}")

model = st.session_state.get("vertex_model")

# --- 4. MOTORE DI CALCOLO REALE (MAPS + VERTEX) ---
def get_metrics_real(origin, dest):
    try:
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, dest, mode="driving", departure_time=datetime.now())
        if not res: return 30, "N/D", False
        
        leg = res[0]['legs'][0]
        g_min = int(leg.get('duration_in_traffic', leg['duration'])['value'] / 60)
        dist = leg['distance']['text']
        
        # Validazione AI mandatoria
        prompt = f"Dispatcher Roma: tratta {origin}->{dest}. Maps stima {g_min} min. Rispondi SOLO col numero intero dei minuti."
        ai_res = model.generate_content(prompt)
        final_t = int(''.join(filter(str.isdigit, ai_res.text)))
        return final_t, dist, True
    except:
        return 30, "N/D", False

# --- 5. LOGICA DISPATCH (10+Tempo+10) ---
def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()
    
    # Rilevamento automatico colonne per evitare NameError
    c_id = next((c for c in df_c.columns if 'ID' in c.upper()), df_c.columns[0])
    c_ora = next((c for c in df_c.columns if 'ORA' in c.upper()), df_c.columns[1])
    c_prel = next((c for c in df_c.columns if 'PRELIEVO' in c.upper()), df_c.columns[2])
    c_dest = next((c for c in df_c.columns if 'DESTINAZIONE' in c.upper()), df_c.columns[3])
    c_tipo = next((c for c in df_c.columns if 'TIPO' in c.upper()), df_c.columns[4])
    
    f_aut = next((c for c in df_f.columns if 'AUTISTA' in c.upper()), df_f.columns[0])
    f_disp = next((c for c in df_f.columns if 'DISPONIBILE' in c.upper()), df_f.columns[2])

    def pt(t):
        if isinstance(t, datetime): return t
        try: return datetime.combine(datetime.today(), datetime.strptime(str(t).replace('.', ':'), '%H:%M').time())
        except: return datetime.now()

    df_c['DT'] = df_c[c_ora].apply(pt)
    df_f['DT'] = df_f[f_disp].apply(pt)
    df_f['Pos'] = "BASE"
    df_f['Servizi'] = 0

    results = []
    bar = st.progress(0)
    for i, (_, r) in enumerate(df_c.iterrows()):
        bar.progress((i + 1) / len(df_c))
        for idx, f in df_f.iterrows():
            if f['Tipo Veicolo'].strip().upper() != r[c_tipo].strip().upper(): continue
            
            dv, _, _ = get_metrics_real(f['Pos'], r[c_prel])
            dp, dist, ai_ok = get_metrics_real(r[c_prel], r[c_dest])

            # Calcolo 10m prelievo + Viaggio + 10m scarico
            ready_time = f['DT'] + timedelta(minutes=dv + 10)
            partenza = max(r['DT'], ready_time)
            arrivo = partenza + timedelta(minutes=dp + 10)
            
            ritardo = max(0, (partenza - r['DT']).total_seconds() / 60)

            results.append({
                'Autista': f[f_aut], 'ID': r[c_id], 'Da': r[c_prel], 'A': r[c_dest],
                'Inizio': partenza.strftime('%H:%M'), 'Fine': arrivo.strftime('%H:%M'),
                'Status': "🟢 OK" if ritardo <= 2 else f"🔴 RITARDO {int(ritardo)} min",
                'AI': ai_ok
            })
            df_f.at[idx, 'DT'] = arrivo
            df_f.at[idx, 'Pos'] = r[c_dest]
            df_f.at[idx, 'Servizi'] += 1
            break
    bar.empty()
    return pd.DataFrame(results), df_f

# --- 6. UI DASHBOARD ---
if check_password():
    st.markdown('<h1 class="main-title">🚐 EmiTrekAI Dispatch</h1>', unsafe_allow_html=True)
    
    if 'results' not in st.session_state:
        c1, c2 = st.columns(2)
        f_p = c1.file_uploader("Carica Prenotazioni (.xlsx)", type=['xlsx'])
        f_f = c2.file_uploader("Carica Flotta (.xlsx)", type=['xlsx'])
        
        if f_p and f_f and st.button("🚀 AVVIA ANALISI"):
            res, fleet = run_dispatch(pd.read_excel(f_p), pd.read_excel(f_f))
            st.session_state['results'], st.session_state['fleet'] = res, fleet
            st.rerun()
    else:
        df, flotta = st.session_state['results'], st.session_state['fleet']
        
        st.write("### 📊 Stato Flotta")
        cols = st.columns(len(flotta))
        for i, (_, row) in enumerate(flotta.iterrows()):
            with cols[i]:
                st.info(f"**{row['Autista']}**\n\nServizi: {row['Servizi']}")

        st.divider()
        st.dataframe(df, use_container_width=True)
        
        if st.button("🔄 NUOVA ANALISI"):
            del st.session_state['results']; st.rerun()