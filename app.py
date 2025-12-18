import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
from google.oauth2 import service_account
import vertexai
from vertexai.generative_models import GenerativeModel

# --- 1. STILE E INTERFACCIA SaaS ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | Smart Dispatch", page_icon="🚐")
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
    .sub-title { color: #666; font-size: 18px; text-align: center; margin-bottom: 30px; }
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
                    st.session_state["password_correct"] = True
                    st.rerun()
                else: st.error("⚠️ Credenziali errate.")
        return False
    return True

# --- 3. MOTORE VERTEX AI & GOOGLE MAPS ---
def ai_validate_time(origin, dest, g_min):
    """L'AI supervisiona Google per evitare figuracce"""
    try:
        if "gcp_service_account" not in st.secrets: return g_min, False
        info = dict(st.secrets["gcp_service_account"])
        creds = service_account.Credentials.from_service_account_info(info)
        vertexai.init(project=info["project_id"], location="us-central1", credentials=creds)
        model = GenerativeModel("gemini-1.5-flash")
        prompt = f"Tragitto Roma {origin} a {dest}: Google dice {g_min} min. Se assurdo scrivi solo il numero reale, altrimenti scrivi {g_min}."
        response = model.generate_content(prompt)
        val_time = int(''.join(filter(str.isdigit, response.text)))
        return val_time, (val_time != g_min)
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
    except: return 35, "N/D", False
    return 35, "N/D", False

# --- 4. LOGICA SMART DISPATCHER (CERCA SOLUZIONI) ---
DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722']
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7}

def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip(); df_f.columns = df_f.columns.str.strip()
    def pt(t): return datetime.combine(datetime.today(), t) if not isinstance(t, str) else datetime.strptime(t.replace('.', ':'), '%H:%M')
    
    df_c['DT_R'] = df_c['Ora Arrivo'].apply(pt)
    df_f['DT_D'] = df_f['Disponibile Da (hh:mm)'].apply(pt)
    df_f['Pos'] = "BASE"; df_f['S_C'] = 0
    
    res_list = []
    df_c = df_c.sort_values(by='DT_R')

    for _, r in df_c.iterrows():
        tipo = r['Tipo Veicolo Richiesto'].strip().capitalize()
        autisti_idonei = df_f[df_f['Tipo Veicolo'].str.capitalize() == tipo]
        
        best_match = None
        min_ritardo = float('inf')
        
        # L'AI SCANSIONA TUTTI GLI AUTISTI PER EVITARE RITARDI
        for idx, aut in autisti_idonei.iterrows():
            if aut['S_C'] == 0:
                dv = 0; op = r['DT_R']; ai_v = False
            else:
                dv, _, ai_v = get_gmaps_info(aut['Pos'], r['Indirizzo Prelievo'])
                op = aut['DT_D'] + timedelta(minutes=dv + 15) # 15m accoglienza
            
            rit = max(0, (op - r['DT_R']).total_seconds() / 60)
            
            # Se l'autista è puntuale, lo assegniamo e interrompiamo la ricerca per questa corsa
            if rit <= 2: 
                best_match = (idx, op, dv, rit, ai_v, aut['Pos'] if aut['S_C']>0 else "BASE")
                break
            
            # Se tutti ritardano, salviamo chi ritarda meno
            if rit < min_ritardo:
                min_ritardo = rit
                best_match = (idx, op, dv, rit, ai_v, aut['Pos'] if aut['S_C']>0 else "BASE")

        if best_match:
            idx, op, dv, rit, ai_v, prov = best_match
            dp, _, ai_p = get_gmaps_info(r['Indirizzo Prelievo'], r['Destinazione Finale'])
            partenza = max(r['DT_R'], op)
            arrivo = partenza + timedelta(minutes=dp + 15) # 15m scarico
            
            res_list.append({
                'Autista': df_f.at[idx, 'Autista'], 'ID': r['ID Prenotazione'], 'Mezzo': df_f.at[idx, 'ID Veicolo'],
                'Da': r['Indirizzo Prelievo'], 'Partenza': partenza, 'A': r['Destinazione Finale'], 'Arrivo': arrivo,
                'Status': "🟢 OK" if rit <= 2 else f"🔴 RITARDO {int(rit)} min",
                'M_V': dv, 'M_P': dp, 'Prov': prov, 'Rit': int(rit), 'AI': ai_p or ai_v
            })
            df_f.at[idx, 'DT_D'] = arrivo; df_f.at[idx, 'Pos'] = r['Destinazione Finale']; df_f.at[idx, 'S_C'] += 1

    return pd.DataFrame(res_list), df_f

# --- 5. INTERFACCIA DASHBOARD ---
if check_password():
    st.markdown('<h1 class="main-title">🚐 EmiTrekAI | Gestione Viaggi</h1>', unsafe_allow_html=True)
    if 'risultati' not in st.session_state:
        c1, c2 = st.columns(2)
        f_p = c1.file_uploader("📋 Prenotazioni (.xlsx)", type=['xlsx'])
        f_f = c2.file_uploader("🚘 Flotta (.xlsx)", type=['xlsx'])
        if f_p and f_f:
            if st.button("🚀 ORGANIZZA I VIAGGI DI OGGI"):
                res, f_a = run_dispatch(pd.read_excel(f_p), pd.read_excel(f_f))
                st.session_state['risultati'], st.session_state['f_a'] = res, f_a
                st.rerun()
    else:
        df, flotta = st.session_state['risultati'], st.session_state['f_a']
        colors = {d: DRIVER_COLORS[i % len(DRIVER_COLORS)] for i, d in enumerate(flotta['Autista'].unique())}
        
        st.write("### 📊 Situazione Mezzi")
        cols = st.columns(len(flotta))
        for i, (_, aut) in enumerate(flotta.iterrows()):
            with cols[i]: st.markdown(f'<div style="background-color:{colors[aut["Autista"]]}; padding:20px; border-radius:15px; text-align:center; color:white;"><small>{aut["Autista"]}</small><br><b style="font-size:22px;">{aut["Tipo Veicolo"]}</b><br><hr style="margin:10px 0; border:0; border-top:1px solid rgba(255,255,255,0.3);">Servizi: {aut["S_C"]}</div>', unsafe_allow_html=True)

        st.divider()
        st.subheader("🗓️ Tabella di Marcia")
        df['Inizio'] = df['Partenza'].dt.strftime('%H:%M'); df['Fine'] = df['Arrivo'].dt.strftime('%H:%M')
        st.dataframe(df[['Autista', 'ID', 'Mezzo', 'Da', 'Inizio', 'A', 'Fine', 'Status']].style.apply(lambda x: [f"background-color: {colors.get(x.Autista)}; color: white; font-weight: bold" for _ in x], axis=1), use_container_width=True)

        st.divider()
        ca, cc = st.columns(2)
        with ca:
            st.header("🕵️ Diario Autisti")
            sel = st.selectbox("Seleziona Autista:", flotta['Autista'].unique())
            for _, r in df[df['Autista'] == sel].iterrows():
                with st.expander(f"Corsa {r['ID']} - Ore {r['Inizio']}", expanded=False):
                    if r['AI']: st.warning("🤖 Validazione AI: Tempi ricalcolati per precisione logistica.")
                    if r['Rit'] > 0: st.error(f"⚠️ RITARDO RILEVATO: {r['Rit']} minuti!")
                    st.write(f"📍 Proviene da: **{r['Prov']}**")
                    st.write(f"⏱️ Tempo prelievo: **{r['M_V']} min** + 15m accoglienza")
                    st.write(f"⏱️ Viaggio cliente: **{r['M_P']} min** + 15m scarico")
                    st.write(f"✅ Libero dalle: **{r['Fine']}**")
        
        if st.sidebar.button("🔄 NUOVA ANALISI"):
            del st.session_state['risultati']
            st.rerun()