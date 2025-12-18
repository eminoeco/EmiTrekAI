import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps

# --- STILE E INTERFACCIA ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | Gestione Flotta", page_icon="🚐")
pd.options.mode.chained_assignment = None

st.markdown("""
    <style>
    .stButton > button {
        background-color: #FF4B4B; color: white; border-radius: 20px;
        height: 3.8em; width: 100%; font-size: 20px; font-weight: bold;
        transition: 0.3s; border: none; box-shadow: 0px 4px 15px rgba(255, 75, 75, 0.4);
        display: block; margin: 0 auto;
    }
    .stButton > button:hover { background-color: #FF1A1A; transform: scale(1.02); }
    .main-title { color: #1E1E1E; font-size: 45px; font-weight: 800; text-align: center; }
    .sub-title { color: #666; font-size: 18px; text-align: center; margin-bottom: 30px; }
    </style>
""", unsafe_allow_html=True)

# --- LOGIN (ISTANTANEO AL 1° CLICK) ---
def check_password():
    if "password_correct" not in st.session_state:
        st.markdown('<h1 class="main-title">🔒 Accesso Area Riservata</h1>', unsafe_allow_html=True)
        st.markdown('<p class="sub-title">Gestione operativa flotta EmiTrekAI</p>', unsafe_allow_html=True)
        # Form per invio istantaneo
        with st.form("login_form", clear_on_submit=False):
            c1, c2 = st.columns(2)
            with c1: u = st.text_input("Username", key="u", autocomplete="off")
            with c2: p = st.text_input("Password", type="password", key="p", autocomplete="off")
            _, cb, _ = st.columns([1, 0.6, 1])
            with cb:
                if st.form_submit_button("✨ ENTRA NEL SISTEMA"):
                    try:
                        if u in st.secrets["users"] and p == st.secrets["users"][u]["password"]:
                            st.session_state["password_correct"] = True; st.rerun()
                        else: st.error("⚠️ Credenziali errate.")
                    except: st.error("❌ Errore Secrets: Tabella [users] mancante.")
        return False
    return True

# --- LOGICA OPERATIVA CON FILTRO DI RAGIONEVOLEZZA ---
DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722']
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7}

def get_gmaps_info(origin, destination):
    try:
        if "MAPS_API_KEY" not in st.secrets: return 30, "Chiave assente", False
        g = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = g.directions(origin, destination, mode="driving", departure_time=datetime.now())
        if res:
            leg = res[0]['legs'][0]
            dur = int(leg.get('duration_in_traffic', leg['duration'])['value'] / 60)
            
            # PROTEZIONE ANTI-FOLLIA
            if dur > 90: # Se il tragitto supera l'ora e mezza (irrealistico per Roma centro)
                return 45, f"{leg['distance']['text']}", True # Forza 45 min e segnala errore
            return dur, f"{leg['distance']['text']}", False
    except: return 30, "Stima", True
    return 30, "Stima", False

def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip(); df_f.columns = df_f.columns.str.strip()
    def pt(t):
        if isinstance(t, str): return datetime.strptime(t.strip().replace('.', ':'), '%H:%M')
        return datetime.combine(datetime.today(), t)
    df_c['DT_R'] = df_c['Ora Arrivo'].apply(pt)
    df_f['DT_D'] = df_f['Disponibile Da (hh:mm)'].apply(pt)
    df_f['Pos'] = "BASE"; df_f['S_C'] = 0; df_f['L_T'] = pd.NaT; df_f['P_O'] = 0
    res_list = []
    df_c = df_c.sort_values(by='DT_R')
    for _, r in df_c.iterrows():
        tv = str(r['Tipo Veicolo Richiesto']).strip().capitalize()
        cm = CAPACITA.get(tv, 3); b_idx = None; min_p = float('inf'); m = {}
        ids = df_f[df_f['Tipo Veicolo'].str.capitalize() == tv]
        for idx, aut in ids.iterrows():
            is_p = (aut['Pos'] == r['Destinazione Finale'] and not pd.isna(aut['L_T']) and 
                    abs((aut['L_T'] - r['DT_R']).total_seconds()) <= 300 and aut['P_O'] < cm)
            if is_p: b_idx = idx; m = {'p': r['DT_R'], 'da': "Car Pooling", 'v': 0, 'rit': 0, 'err': False}; break
            if aut['S_C'] == 0: dv = 0; op = r['DT_R']; err_v = False
            else:
                dv, _, err_v = get_gmaps_info(aut['Pos'], r['Indirizzo Prelievo'])
                op = aut['DT_D'] + timedelta(minutes=dv + 15)
            rit = max(0, (op - r['DT_R']).total_seconds() / 60)
            bonus = 5000 if aut['S_C'] > 0 else 0 # Saturazione AI
            score = (rit * 5000) + dv - bonus
            if score < min_p: min_p = score; b_idx = idx; m = {'p': op, 'da': aut['Pos'] if aut['S_C'] > 0 else "Primo Servizio", 'v': dv, 'rit': rit, 'err': err_v}
        if b_idx is not None:
            dp, _, err_p = get_gmaps_info(r['Indirizzo Prelievo'], r['Destinazione Finale'])
            pe = max(r['DT_R'], m['p']); ae = pe + timedelta(minutes=dp + 15)
            res_list.append({
                'Autista': df_f.at[b_idx, 'Autista'], 'ID': r['ID Prenotazione'], 'Mezzo': df_f.at[b_idx, 'ID Veicolo'], 'Veicolo': tv,
                'Da': r['Indirizzo Prelievo'], 'Partenza': pe, 'A': r['Destinazione Finale'], 'Arrivo': ae,
                'Status': "🟢 OK" if m['rit'] <= 2 else f"🔴 RITARDO {int(m['rit'])} min",
                'M_V': m['v'], 'M_P': dp, 'Prov': m['da'], 'Ritardo_Min': int(m['rit']), 'API_Error': err_p or m['err']
            })
            df_f.at[b_idx, 'DT_D'] = ae; df_f.at[b_idx, 'Pos'] = r['Destinazione Finale']; df_f.at[b_idx, 'L_T'] = r['DT_R']; df_f.at[b_idx, 'S_C'] += 1; df_f.at[b_idx, 'P_O'] += 1
    return pd.DataFrame(res_list), df_f

# --- INTERFACCIA ---
if check_password():
    st.sidebar.button("🔓 LOGOUT", on_click=lambda: st.session_state.pop("password_correct"))
    st.markdown('<h1 class="main-title">🚐 EmiTrekAI Dispatcher</h1>', unsafe_allow_html=True)
    if 'risultati' not in st.session_state:
        c1, c2 = st.columns(2)
        with c1: f_c = st.file_uploader("📋 Prenotazioni (.xlsx)", type=['xlsx'])
        with c2: f_f = st.file_uploader("🚘 Flotta (.xlsx)", type=['xlsx'])
        if f_c and f_f:
            _, cb, _ = st.columns([1, 1.5, 1])
            with cb:
                if st.button("🚀 ORGANIZZA I VIAGGI DI OGGI"):
                    res, f_a = run_dispatch(pd.read_excel(f_c), pd.read_excel(f_f))
                    st.session_state['risultati'], st.session_state['f_f'] = res, f_a; st.rerun()
    else:
        df, flotta = st.session_state['risultati'], st.session_state['f_f']
        colors = {d: DRIVER_COLORS[i % len(DRIVER_COLORS)] for i, d in enumerate(flotta['Autista'].unique())}
        
        # BOX RIEPILOGO
        st.write("### 📊 Stato Mezzi")
        cols = st.columns(len(flotta))
        for i, (_, aut) in enumerate(flotta.iterrows()):
            with cols[i]: st.markdown(f'<div style="background-color:{colors[aut["Autista"]]}; padding:20px; border-radius:15px; text-align:center; color:white;"><small>{aut["Autista"]}</small><br><b style="font-size:22px;">{aut["Tipo Veicolo"]}</b><br><hr style="margin:10px 0; border:0; border-top:1px solid rgba(255,255,255,0.3);">Servizi: {aut["S_C"]}</div>', unsafe_allow_html=True)

        st.divider()
        st.subheader("🗓️ Tabella di Marcia")
        df['Inizio'] = pd.to_datetime(df['Partenza']).dt.strftime('%H:%M'); df['Fine'] = pd.to_datetime(df['Arrivo']).dt.strftime('%H:%M')
        st.dataframe(df[['Autista', 'ID', 'Mezzo', 'Da', 'Inizio', 'A', 'Fine', 'Status']].style.apply(lambda x: [f"background-color: {colors.get(x.Autista)}; color: white; font-weight: bold" for _ in x], axis=1), use_container_width=True)
        
        st.divider()
        ca, cc = st.columns(2)
        with ca:
            st.header("🕵️ Diario Autisti")
            sel = st.selectbox("Seleziona Autista:", flotta['Autista'].unique())
            for _, r in df[df['Autista'] == sel].iterrows():
                with st.expander(f"Corsa {r['ID']} - Ore {r['Inizio']}", expanded=False):
                    # ALERT ANTI-FOLLIA
                    if r['API_Error']:
                        st.warning("⚠️ ATTENZIONE: Google ha fornito un tempo irrealistico. L'AI ha corretto il tempo a 45 min per sicurezza.")
                    if r['Ritardo_Min'] > 0:
                        st.error(f"⚠️ RITARDO DI {r['Ritardo_Min']} MINUTI!")
                    st.write(f"📍 Proviene da: **{r['Prov']}**")
                    st.write(f"⏱️ Tempo prelievo: **{r['M_V']} min** + 15m accoglienza")
                    st.write(f"⏱️ Viaggio cliente: **{r['M_P']} min** + 15m scarico")
                    st.write(f"✅ Libero dalle: **{r['Fine']}**")
        with cc:
            st.header("📍 Dettaglio Spostamento")
            sid = st.selectbox("Cerca ID Prenotazione:", df['ID'].unique())
            inf = df[df['ID'] == sid].iloc[0]
            st.success(f"👤 **Autista:** {inf['Autista']} | 🏢 **Veicolo:** {inf['Veicolo']}")
            st.markdown(f"📍 **Prelievo:** {inf['Da']} (**{inf['Inizio']}**)")
            st.markdown(f"🏁 **Destinazione:** {inf['A']} (**{inf['Fine']}**)")