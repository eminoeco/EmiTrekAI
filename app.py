import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
from google.oauth2 import service_account
import vertexai
from vertexai.generative_models import GenerativeModel
import time

# --- 1. ESTETICA E PULSANTI ROSSI CENTRATI ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | Professional", page_icon="🚐")
st.markdown("""
    <style>
    .stButton > button {
        background-color: #FF4B4B; color: white; border-radius: 20px;
        height: 3.8em; width: 100%; font-size: 20px; font-weight: bold;
        display: block; margin: 0 auto;
    }
    .main-title { color: #1E1E1E; font-size: 45px; font-weight: 800; text-align: center; }
    </style>
""", unsafe_allow_html=True)

# --- 2. MOTORE AD ALTA DISPONIBILITÀ (NO 0 MIN) ---
def get_metrics_with_retry(origin, dest, retries=2):
    """Strategia di recupero dati: riprova se Maps o Vertex tardano"""
    for i in range(retries):
        try:
            gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
            res = gmaps.directions(origin, dest, mode="driving", departure_time=datetime.now())
            if res:
                leg = res[0]['legs'][0]
                g_dur = int(leg.get('duration_in_traffic', leg['duration'])['value'] / 60)
                dist = leg['distance']['text']
                
                # Chiamata a Vertex AI per validazione logistica
                info = dict(st.secrets["gcp_service_account"])
                creds = service_account.Credentials.from_service_account_info(info)
                vertexai.init(project=info["project_id"], location="us-central1", credentials=creds)
                model = GenerativeModel("gemini-1.5-flash")
                prompt = f"NCC Roma: da {origin} a {dest}. Maps stima {g_dur} min. Fornisci solo il numero intero dei minuti reali."
                ai_res = model.generate_content(prompt)
                final_t = int(''.join(filter(str.isdigit, ai_res.text)))
                return final_t, dist, True
        except:
            time.sleep(1) # Attesa tecnica prima di riprovare
    return 30, "N/D", False # Fallback minimo realistico solo dopo 2 tentativi falliti

# --- 3. LOGICA DISPATCH (10+10 MINUTI) ---
def run_dispatch(df_c, df_f):
    bar = st.progress(0); status = st.empty()
    df_c.columns = df_c.columns.str.strip(); df_f.columns = df_f.columns.str.strip()
    
    # Auto-rilevamento colonne
    col_id = next((c for c in df_c.columns if 'ID' in c), df_c.columns[0])
    col_ora = next((c for c in df_c.columns if 'Ora' in c), 'Ora Arrivo')
    col_prel = next((c for c in df_c.columns if 'Prelievo' in c), 'Indirizzo Prelievo')
    col_dest = next((c for c in df_c.columns if 'Destinazione' in c), 'Destinazione Finale')
    col_tipo = next((c for c in df_c.columns if 'Tipo' in c), 'Tipo Veicolo Richiesto')

    def pt(t): return datetime.combine(datetime.today(), t) if not isinstance(t, str) else datetime.strptime(t.replace('.', ':'), '%H:%M')
    df_c['DT_R'] = df_c[col_ora].apply(pt)
    df_f['DT_D'] = df_f['Disponibile Da (hh:mm)'].apply(pt)
    df_f['Pos'] = "BASE"; df_f['S_C'] = 0; df_f['Last_D'] = ""
    
    res_list = []
    df_c = df_c.sort_values(by=['DT_R', col_dest])

    for i, (_, r) in enumerate(df_c.iterrows()):
        status.text(f"📡 Analisi Corsa {r[col_id]} con Vertex AI...")
        bar.progress((i + 1) / len(df_c))
        
        req = r[col_tipo].strip().capitalize()
        idonei = df_f[df_f['Tipo Veicolo'].str.capitalize() == req]
        best_m = None; min_rit = float('inf')

        for idx, aut in idonei.iterrows():
            # Tempo di posizionamento (con 10 min accoglienza)
            dv, _, _ = get_metrics_with_retry(aut['Pos'], r[col_prel])
            op = aut['DT_D'] + timedelta(minutes=dv + 10) 
            rit = max(0, (op - r['DT_R']).total_seconds() / 60)
            if rit < min_rit: min_rit = rit; best_m = (idx, op, dv, rit)

        if best_m:
            idx, op, dv, rit = best_m
            dp, dist, ai_p = get_metrics_with_retry(r[col_prel], r[col_dest])
            partenza = max(r['DT_R'], op)
            arrivo = partenza + timedelta(minutes=dp + 10) # 10 min scarico
            
            res_list.append({
                'Autista': df_f.at[idx, 'Autista'], 'ID': r[col_id], 'Mezzo': df_f.at[idx, 'ID Veicolo'],
                'Da': r[col_prel], 'Inizio': partenza.strftime('%H:%M'), 'A': r[col_dest], 
                'Fine': arrivo.strftime('%H:%M'), 'Status': "🟢 OK" if rit <= 2 else f"🔴 RITARDO {int(rit)} min",
                'M_V': dv, 'M_P': dp, 'Rit': int(rit), 'AI': ai_p, 'Dist': dist
            })
            df_f.at[idx, 'DT_D'] = arrivo; df_f.at[idx, 'Pos'] = r[col_dest]; df_f.at[idx, 'S_C'] += 1

    status.empty(); bar.empty()
    return pd.DataFrame(res_list), df_f

# --- 4. INTERFACCIA OPERATIVA ---
if "password_correct" not in st.session_state:
    st.markdown('<h1 class="main-title">🔒 EmiTrekAI Access</h1>', unsafe_allow_html=True)
    _, cb, _ = st.columns([1, 0.6, 1])
    with cb:
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("🚀 LOGIN"):
            if u in st.secrets["users"] and p == st.secrets["users"][u]["password"]:
                st.session_state["password_correct"] = True; st.rerun()
else:
    st.sidebar.button("🔓 LOGOUT", on_click=lambda: st.session_state.pop("password_correct"))
    st.markdown('<h1 class="main-title">🚐 EmiTrekAI | SaaS Dispatch</h1>', unsafe_allow_html=True)
    
    if 'risultati' not in st.session_state:
        c1, c2 = st.columns(2)
        f_p = c1.file_uploader("Prenotazioni", type=['xlsx']); f_f = c2.file_uploader("Flotta", type=['xlsx'])
        if f_p and f_f:
            if st.button("🚀 ORGANIZZA I VIAGGI"):
                res, f_a = run_dispatch(pd.read_excel(f_p), pd.read_excel(f_f))
                st.session_state['risultati'], st.session_state['f_a'] = res, f_a; st.rerun()
    else:
        # VISUALIZZAZIONE RISULTATI
        st.write("### 📊 Stato Flotta")
        flotta_cols = st.columns(len(st.session_state['f_a']))
        for i, (_, row) in enumerate(st.session_state['f_a'].iterrows()):
            with flotta_cols[i]: st.success(f"**{row['Autista']}**\n\nServizi: {row['S_C']}")
        
        st.divider()
        st.dataframe(st.session_state['risultati'], use_container_width=True)
        
        # DIARIO DI BORDO CON RITARDI EVIDENZIATI
        st.subheader("🕵️ Diario di Bordo")
        for _, r in st.session_state['risultati'].iterrows():
            if "🔴" in r['Status']:
                st.error(f"⚠️ {r['Autista']} - Corsa {r['ID']}: {r['Status']}")
        
        if st.sidebar.button("🔄 NUOVA ANALISI"): del st.session_state['risultati']; st.rerun()