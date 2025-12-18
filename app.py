import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
from google.oauth2 import service_account
import vertexai
from vertexai.generative_models import GenerativeModel

# --- 1. CONFIGURAZIONE ESTETICA ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | SaaS Smart Dispatch", page_icon="🚐")
pd.options.mode.chained_assignment = None

st.markdown("""
    <style>
    .stButton > button {
        background-color: #FF4B4B; color: white; border-radius: 20px;
        height: 3.8em; width: 100%; font-size: 20px; font-weight: bold;
        transition: 0.3s; border: none; box-shadow: 0px 4px 15px rgba(255, 75, 75, 0.4);
        display: block; margin: 0 auto;
    }
    .main-title { color: #1E1E1E; font-size: 45px; font-weight: 800; text-align: center; }
    </style>
""", unsafe_allow_html=True)

# --- 2. LOGIN ISTANTANEO ---
def check_password():
    if "password_correct" not in st.session_state:
        st.markdown('<h1 class="main-title">🔒 Accesso Area Riservata</h1>', unsafe_allow_html=True)
        col_u, col_p = st.columns(2)
        u = col_u.text_input("Username", key="u_input")
        p = col_p.text_input("Password", type="password", key="p_input")
        if st.button("✨ ENTRA NEL SISTEMA"):
            if u in st.secrets["users"] and p == st.secrets["users"][u]["password"]:
                st.session_state["password_correct"] = True; st.rerun()
            else: st.error("⚠️ Credenziali errate.")
        return False
    return True

# --- 3. MOTORE VERTEX AI & GOOGLE MAPS ---
def ai_validate_time(origin, dest, g_min):
    try:
        info = dict(st.secrets["gcp_service_account"])
        creds = service_account.Credentials.from_service_account_info(info)
        vertexai.init(project=info["project_id"], location="us-central1", credentials=creds)
        model = GenerativeModel("gemini-1.5-flash")
        prompt = f"NCC Roma: da {origin} a {dest} Google dice {g_min} min. Sii realista, non accettare tempi sotto i 45 min per Ciampino-Termini. Rispondi solo col numero."
        response = model.generate_content(prompt)
        return int(''.join(filter(str.isdigit, response.text))), True
    except: return g_min, False

def get_gmaps_info(origin, destination):
    try:
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, destination, mode="driving", departure_time=datetime.now())
        if res:
            leg = res[0]['legs'][0]
            dur = int(leg.get('duration_in_traffic', leg['duration'])['value'] / 60)
            final_t, ai_fix = ai_validate_time(origin, destination, dur)
            return final_t, leg['distance']['text'], ai_fix
    except: return 45, "N/D", True

# --- 4. LOGICA SMART DISPATCH (POOLING PER REQUISITO) ---
DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722']
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7}

def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip(); df_f.columns = df_f.columns.str.strip()
    def pt(t): return datetime.combine(datetime.today(), t) if not isinstance(t, str) else datetime.strptime(t.replace('.', ':'), '%H:%M')
    
    df_c['DT_R'] = df_c['Ora Arrivo'].apply(pt)
    df_f['DT_D'] = df_f['Disponibile Da (hh:mm)'].apply(pt)
    df_f['Pos'] = "BASE"; df_f['S_C'] = 0; df_f['P_Oggi'] = 0; df_f['Last_D'] = ""
    
    res_list = []
    df_c = df_c.sort_values(by=['DT_R', 'Destinazione Finale'])

    for _, r in df_c.iterrows():
        req = r['Tipo Veicolo Richiesto'].strip().capitalize()
        cap_max = CAPACITA.get(req, 3)
        assigned = False
        
        # 1. TENTA ACCORPAMENTO (POOLING) - RISPETTA REQUISITO MEZZO
        potenziali = df_f[(df_f['Tipo Veicolo'].str.capitalize() == req) & 
                          (df_f['Last_D'] == r['Destinazione Finale']) & 
                          (df_f['P_Oggi'] < cap_max)]
        
        for idx_p, aut_p in potenziali.iterrows():
            last = next(c for c in reversed(res_list) if c['Autista'] == aut_p['Autista'])
            if abs((last['Partenza'] - r['DT_R']).total_seconds()) <= 900:
                res_list.append({
                    'Autista': aut_p['Autista'], 'ID': r['ID Prenotazione'], 'Mezzo': aut_p['ID Veicolo'],
                    'Da': r['Indirizzo Prelievo'], 'Partenza': last['Partenza'], 'A': r['Destinazione Finale'], 
                    'Arrivo': last['Arrivo'], 'Status': f"💎 ACCORPATO ({req})", 'Rit': 0, 'AI': True, 'Prov': "Pooling"
                })
                df_f.at[idx_p, 'P_Oggi'] += 1; assigned = True; break

        # 2. SE NON ACCORPABILE, ASSEGNA NUOVO
        if not assigned:
            idonei = df_f[df_f['Tipo Veicolo'].str.capitalize() == req]
            best_m = None; min_rit = float('inf')
            for idx, aut in idonei.iterrows():
                dv = 0 if aut['S_C'] == 0 else get_gmaps_info(aut['Pos'], r['Indirizzo Prelievo'])[0]
                op = aut['DT_D'] + timedelta(minutes=dv + 15)
                rit = max(0, (op - r['DT_R']).total_seconds() / 60)
                if rit <= 2: best_m = (idx, op, dv, rit); break
                if rit < min_rit: min_rit = rit; best_m = (idx, op, dv, rit)

            if best_m:
                idx, op, dv, rit = best_m
                dp, _, ai_p = get_gmaps_info(r['Indirizzo Prelievo'], r['Destinazione Finale'])
                partenza = max(r['DT_R'], op); arrivo = partenza + timedelta(minutes=dp + 15)
                res_list.append({
                    'Autista': df_f.at[idx, 'Autista'], 'ID': r['ID Prenotazione'], 'Mezzo': df_f.at[idx, 'ID Veicolo'],
                    'Da': r['Indirizzo Prelievo'], 'Partenza': partenza, 'A': r['Destinazione Finale'], 'Arrivo': arrivo,
                    'Status': "🟢 OK" if rit <= 2 else f"🔴 RITARDO {int(rit)} min",
                    'M_V': dv, 'M_P': dp, 'Prov': aut['Pos'], 'Rit': int(rit), 'AI': ai_p
                })
                df_f.at[idx, 'DT_D'] = arrivo; df_f.at[idx, 'Pos'] = r['Destinazione Finale']; 
                df_f.at[idx, 'S_C'] += 1; df_f.at[idx, 'P_Oggi'] = 1; df_f.at[idx, 'Last_D'] = r['Destinazione Finale']

    return pd.DataFrame(res_list), df_f

# --- 5. INTERFACCIA ---
if check_password():
    st.markdown('<h1 class="main-title">🚐 EmiTrekAI | Gestione Viaggi</h1>', unsafe_allow_html=True)
    if 'risultati' not in st.session_state:
        c1, c2 = st.columns(2)
        f_p = c1.file_uploader("Prenotazioni", type=['xlsx']); f_f = c2.file_uploader("Flotta", type=['xlsx'])
        if f_p and f_f:
            if st.button("🚀 ORGANIZZA I VIAGGI DI OGGI"):
                res, f_a = run_dispatch(pd.read_excel(f_p), pd.read_excel(f_f))
                st.session_state['risultati'], st.session_state['f_a'] = res, f_a; st.rerun()
    else:
        df, flotta = st.session_state['risultati'], st.session_state['f_a']
        colors = {d: DRIVER_COLORS[i % len(DRIVER_COLORS)] for i, d in enumerate(flotta['Autista'].unique())}
        st.subheader("🗓️ Tabella di Marcia Ottimizzata")
        df['Inizio'] = df['Partenza'].dt.strftime('%H:%M'); df['Fine'] = df['Arrivo'].dt.strftime('%H:%M')
        st.dataframe(df[['Autista', 'ID', 'Mezzo', 'Da', 'Inizio', 'A', 'Fine', 'Status']].style.apply(lambda x: [f"background-color: {colors.get(x.Autista)}; color: white; font-weight: bold" for _ in x], axis=1), use_container_width=True)
        st.divider()
        ca, cc = st.columns(2)
        with ca:
            st.header("🕵️ Diario Autisti")
            sel = st.selectbox("Seleziona Autista:", flotta['Autista'].unique())
            for _, r in df[df['Autista'] == sel].iterrows():
                with st.expander(f"Corsa {r['ID']} - Ore {r['Inizio']}"):
                    if r['Rit'] > 0: st.error(f"⚠️ RITARDO RILEVATO: {r['Rit']} minuti!")
                    st.write(f"📍 Destinazione: **{r['A']}**")
                    st.write(f"⏱️ Tempo viaggio AI: **{r['M_P']} min**")
                    st.write(f"✅ Libero alle: **{r['Fine']}**")
        with cc:
            st.header("📍 Dettaglio Cliente")
            sid = st.selectbox("Cerca ID Prenotazione:", df['ID'].unique())
            inf = df[df['ID'] == sid].iloc[0]
            st.success(f"👤 **Autista:** {inf['Autista']} | 🏢 **Veicolo:** {inf['Mezzo']}")
            if st.sidebar.button("🔄 NUOVA ANALISI"): del st.session_state['risultati']; st.rerun()