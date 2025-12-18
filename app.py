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
        _, cb, _ = st.columns([1, 0.6, 1])
        with cb:
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
        prompt = f"NCC Roma: da {origin} a {dest} Google dice {g_min} min. Sii realista: no sotto i 45 min per Ciampino. Rispondi solo col numero."
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

# --- 4. LOGICA SMART DISPATCH (FIX KEYERROR) ---
DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722']
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7}

def run_dispatch(df_c, df_f):
    progress_bar = st.progress(0); status_text = st.empty()
    df_c.columns = df_c.columns.str.strip(); df_f.columns = df_f.columns.str.strip()
    
    # Rilevamento automatico nomi colonne per evitare KeyError
    col_id = next((c for c in df_c.columns if 'ID' in c), 'ID')
    col_ora = next((c for c in df_c.columns if 'Ora' in c), 'Ora Arrivo')
    col_dest = next((c for c in df_c.columns if 'Destinazione' in c), 'Destinazione Finale')
    col_prel = next((c for c in df_c.columns if 'Prelievo' in c), 'Indirizzo Prelievo')
    col_tipo = next((c for c in df_c.columns if 'Tipo' in c), 'Tipo Veicolo Richiesto')
    
    def pt(t): return datetime.combine(datetime.today(), t) if not isinstance(t, str) else datetime.strptime(t.replace('.', ':'), '%H:%M')
    df_c['DT_R'] = df_c[col_ora].apply(pt)
    df_f['DT_D'] = df_f['Disponibile Da (hh:mm)'].apply(pt)
    df_f['Pos'] = "BASE"; df_f['S_C'] = 0; df_f['P_Oggi'] = 0; df_f['Last_D'] = ""
    
    res_list = []
    df_c = df_c.sort_values(by=['DT_R', col_dest])
    total = len(df_c)

    for i, (_, r) in enumerate(df_c.iterrows()):
        status_text.text(f"Analisi Corsa {r[col_id]} con Vertex AI...")
        progress_bar.progress((i + 1) / total)
        
        req = r[col_tipo].strip().capitalize(); cap_max = CAPACITA.get(req, 3); assigned = False
        
        # Smart Pooling
        potenziali = df_f[(df_f['Tipo Veicolo'].str.capitalize() == req) & (df_f['Last_D'] == r[col_dest]) & (df_f['P_Oggi'] < cap_max)]
        for idx_p, aut_p in potenziali.iterrows():
            last = next(c for c in reversed(res_list) if c['Autista'] == aut_p['Autista'])
            if abs((last['Partenza'] - r['DT_R']).total_seconds()) <= 600:
                res_list.append({
                    'Autista': aut_p['Autista'], 'ID': r[col_id], 'Mezzo': aut_p['ID Veicolo'], 'Veicolo': req,
                    'Da': r[col_prel], 'Partenza': last['Partenza'], 'A': r[col_dest], 
                    'Arrivo': last['Arrivo'], 'Status': f"💎 ACCORPATO ({req})", 'Rit': 0, 'AI': True, 'Prov': "Pooling"
                })
                df_f.at[idx_p, 'P_Oggi'] += 1; assigned = True; break

        if not assigned:
            idonei = df_f[df_f['Tipo Veicolo'].str.capitalize() == req]
            best_m = None; min_rit = float('inf')
            for idx, aut in idonei.iterrows():
                dv = 0 if aut['S_C'] == 0 else get_gmaps_info(aut['Pos'], r[col_prel])[0]
                op = aut['DT_D'] + timedelta(minutes=dv + 10) # Accoglienza
                rit = max(0, (op - r['DT_R']).total_seconds() / 60)
                if rit <= 2: best_m = (idx, op, dv, rit); break
                if rit < min_rit: min_rit = rit; best_m = (idx, op, dv, rit)

            if best_m:
                idx, op, dv, rit = best_m
                dp, dist, ai_p = get_gmaps_info(r[col_prel], r[col_dest])
                partenza = max(r['DT_R'], op); arrivo = partenza + timedelta(minutes=dp + 10) # Scarico
                res_list.append({
                    'Autista': df_f.at[idx, 'Autista'], 'ID': r[col_id], 'Mezzo': df_f.at[idx, 'ID Veicolo'], 'Veicolo': req,
                    'Da': r[col_prel], 'Partenza': partenza, 'A': r[col_dest], 'Arrivo': arrivo,
                    'Status': "🟢 OK" if rit <= 2 else f"🔴 RITARDO {int(rit)} min",
                    'M_V': dv, 'M_P': dp, 'Prov': aut['Pos'], 'Rit': int(rit), 'AI': ai_p, 'Distanza': dist
                })
                df_f.at[idx, 'DT_D'] = arrivo; df_f.at[idx, 'Pos'] = r[col_dest]; 
                df_f.at[idx, 'S_C'] += 1; df_f.at[idx, 'P_Oggi'] = 1; df_f.at[idx, 'Last_D'] = r[col_dest]
    
    status_text.empty(); progress_bar.empty()
    return pd.DataFrame(res_list), df_f

# --- 5. INTERFACCIA ---
if check_password():
    st.sidebar.button("🔓 LOGOUT", on_click=lambda: st.session_state.pop("password_correct"))
    st.markdown('<h1 class="main-title">🚐 EmiTrekAI | Gestione Viaggi</h1>', unsafe_allow_html=True)
    if 'risultati' not in st.session_state:
        c1, c2 = st.columns(2)
        f_p = c1.file_uploader("Prenotazioni", type=['xlsx']); f_f = c2.file_uploader("Flotta", type=['xlsx'])
        if f_p and f_f:
            st.markdown("<br>", unsafe_allow_html=True)
            _, cb, _ = st.columns([1, 1.5, 1])
            with cb:
                if st.button("🚀 ORGANIZZA I VIAGGI DI OGGI"):
                    res, f_a = run_dispatch(pd.read_excel(f_p), pd.read_excel(f_f))
                    st.session_state['risultati'], st.session_state['f_a'] = res, f_a; st.rerun()
    else:
        df, flotta = st.session_state['risultati'], st.session_state['f_a']
        colors = {d: DRIVER_COLORS[i % len(DRIVER_COLORS)] for i, d in enumerate(flotta['Autista'].unique())}
        
        st.write("### 📊 Situazione Mezzi")
        stat_cols = st.columns(len(flotta))
        for i, (_, aut_row) in enumerate(flotta.iterrows()):
            nome_a = aut_row['Autista']
            with stat_cols[i]:
                st.markdown(f'<div style="background-color:{colors[nome_a]}; padding:20px; border-radius:15px; text-align:center; color:white;"><small>{nome_a}</small><br><b style="font-size:22px;">{aut_row["Tipo Veicolo"]}</b><br><hr style="margin:10px 0; border:0; border-top:1px solid rgba(255,255,255,0.3);">Servizi: {aut_row["S_C"]}</div>', unsafe_allow_html=True)

        st.divider()
        st.subheader("🗓️ Tabella di Marcia")
        df['Inizio'] = df['Partenza'].dt.strftime('%H:%M'); df['Fine'] = df['Arrivo'].dt.strftime('%H:%M')
        st.dataframe(df[['Autista', 'ID', 'Mezzo', 'Da', 'Inizio', 'A', 'Fine', 'Status']].style.apply(lambda x: [f"background-color: {colors.get(x.Autista)}; color: white; font-weight: bold" for _ in x], axis=1), use_container_width=True)

        st.divider()
        ca, cc = st.columns(2)
        with ca:
            st.header("🕵️ Diario Autista")
            sel = st.selectbox("Seleziona Autista:", flotta['Autista'].unique())
            for _, r in df[df['Autista'] == sel].iterrows():
                with st.expander(f"Corsa {r['ID']} - Ore {r['Inizio']}"):
                    if r['Rit'] > 0: st.error(f"⚠️ RITARDO RILEVATO: {r['Rit']} minuti!")
                    st.write(f"🏢 **Veicolo:** {r['Mezzo']} ({r['Veicolo']})")
                    st.write(f"⏱️ **Accoglienza:** 10 min | **Viaggio:** {r['M_P']} min | **Scarico:** 10 min")
                    st.write(f"✅ **Libero alle:** {r['Fine']}")
        with cc:
            st.header("📍 Dettaglio Cliente")
            sid = st.selectbox("Cerca ID Prenotazione:", df['ID'].unique())
            inf = df[df['ID'] == sid].iloc[0]
            st.success(f"👤 **Autista:** {inf['Autista']} | 🏢 **Veicolo:** {inf['Mezzo']}")
            st.markdown(f"📍 **Partenza:** {inf['Da']} (Ore {inf['Inizio']})")
            st.markdown(f"🏁 **Arrivo:** {inf['A']} (Ore {inf['Fine']})")
            if st.sidebar.button("🔄 NUOVA ANALISI"): del st.session_state['risultati']; st.rerun()