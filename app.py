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

# --- LOGIN (SECRETS TOML + NO CRONOLOGIA) ---
def check_password():
    if "password_correct" not in st.session_state:
        st.markdown('<h1 class="main-title">🔒 Accesso Area Riservata</h1>', unsafe_allow_html=True)
        st.markdown('<p class="sub-title">Gestione operativa flotta NCC</p>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1: u = st.text_input("Nome Utente", key="u", autocomplete="off")
        with c2: p = st.text_input("Password", type="password", key="p", autocomplete="off")
        _, cb, _ = st.columns([1, 1.5, 1])
        with cb:
            if st.button("✨ ENTRA NEL SISTEMA"):
                try:
                    if u in st.secrets["users"] and p == st.secrets["users"][u]["password"]:
                        st.session_state["password_correct"] = True
                        st.rerun()
                    else: st.error("🚫 Credenziali errate.")
                except: st.error("❌ Errore Secrets: Tabella [users] mancante.")
        return False
    return True

# --- LOGICA OPERATIVA ---
DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722']
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7}

def get_gmaps_info(origin, destination):
    try:
        if "MAPS_API_KEY" not in st.secrets: return 40, "Chiave mancante"
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, destination, mode="driving", departure_time=datetime.now())
        if res:
            leg = res[0]['legs'][0]
            dur = int(leg.get('duration_in_traffic', leg['duration'])['value'] / 60)
            if dur > 120: dur = 45 # Protezione anti-errore
            return dur, f"{leg['distance']['text']}"
    except: return 40, "Stima"
    return 40, "Stima"

def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip(); df_f.columns = df_f.columns.str.strip()
    def pt(t):
        if isinstance(t, str): return datetime.strptime(t.strip().replace('.', ':'), '%H:%M')
        return datetime.combine(datetime.today(), t)
    df_c['DT_R'] = df_c['Ora Arrivo'].apply(pt)
    df_f['DT_D'] = df_f['Disponibile Da (hh:mm)'].apply(pt)
    df_f['Pos'] = "BASE"; df_f['S_Count'] = 0; df_f['L_Time'] = pd.NaT; df_f['P_Oggi'] = 0
    res_list = []
    df_c = df_c.sort_values(by='DT_R')
    for _, r in df_c.iterrows():
        tv = str(r['Tipo Veicolo Richiesto']).strip().capitalize()
        cm = CAPACITA.get(tv, 3); best_idx = None; min_p = float('inf'); match = {}
        idonei = df_f[df_f['Tipo Veicolo'].str.capitalize() == tv]
        for idx, aut in idonei.iterrows():
            is_pool = (aut['Pos'] == r['Destinazione Finale'] and not pd.isna(aut['L_Time']) and 
                       abs((aut['L_Time'] - r['DT_R']).total_seconds()) <= 300 and aut['P_Oggi'] < cm)
            if is_pool:
                best_idx = idx; match = {'p': r['DT_R'], 'da': "Car Pooling", 'v': 0, 'rit': 0}; break
            if aut['S_Count'] == 0: dv = 0; op = r['DT_R']
            else:
                dv, _ = get_gmaps_info(aut['Pos'], r['Indirizzo Prelievo'])
                op = aut['DT_D'] + timedelta(minutes=dv + 15)
            rit = max(0, (op - r['DT_R']).total_seconds() / 60)
            bonus = 5000 if aut['S_Count'] > 0 else 0 # Saturazione turni
            punteggio = (rit * 5000) + dv - bonus
            if punteggio < min_p:
                min_p = punteggio; best_idx = idx; match = {'p': op, 'da': aut['Pos'] if aut['S_Count'] > 0 else "Primo Servizio", 'v': dv, 'rit': rit}
        if best_idx is not None:
            dp, _ = get_gmaps_info(r['Indirizzo Prelievo'], r['Destinazione Finale'])
            pe = max(r['DT_R'], match['p']); ae = pe + timedelta(minutes=dp + 15)
            res_list.append({
                'Autista': df_f.at[best_idx, 'Autista'], 'ID': r['ID Prenotazione'], 'Mezzo': df_f.at[best_idx, 'ID Veicolo'], 'Veicolo': tv,
                'Da': r['Indirizzo Prelievo'], 'Partenza': pe, 'A': r['Destinazione Finale'], 'Arrivo': ae,
                'Status': "🟢 OK" if match['rit'] <= 5 else f"🔴 RITARDO {int(match['rit'])} min",
                'M_V': match['v'], 'M_P': dp, 'Prov': match['da']
            })
            df_f.at[best_idx, 'DT_D'] = ae; df_f.at[best_idx, 'Pos'] = r['Destinazione Finale']; df_f.at[best_idx, 'L_Time'] = r['DT_R']; df_f.at[best_idx, 'S_Count'] += 1; df_f.at[best_idx, 'P_Oggi'] += 1
    return pd.DataFrame(res_list), df_f

# --- ESECUZIONE APP ---
if check_password():
    st.sidebar.button("🔓 LOGOUT", on_click=lambda: st.session_state.pop("password_correct"))
    st.markdown('<h1 class="main-title">🚐 EmiTrekAI Dispatcher</h1>', unsafe_allow_html=True)
    st.markdown('<p class="sub-title">Piano operativo ottimizzato per flotta NCC</p>', unsafe_allow_html=True)

    if 'risultati' not in st.session_state:
        st.write("### 📂 Caricamento Dati")
        c1, c2 = st.columns(2)
        with c1: f_c = st.file_uploader("📋 Lista Prenotazioni (.xlsx)", type=['xlsx'])
        with c2: f_f = st.file_uploader("🚘 Flotta Disponibile (.xlsx)", type=['xlsx'])
        if f_c and f_f:
            _, cb, _ = st.columns([1, 1.5, 1])
            with cb:
                if st.button("🚀 CALCOLA CRONOPROGRAMMA AI"):
                    res, f_agg = run_dispatch(pd.read_excel(f_c), pd.read_excel(f_f))
                    st.session_state['risultati'], st.session_state['flotta_finale'] = res, f_agg
                    st.rerun()
    else:
        if st.sidebar.button("🔄 NUOVA ANALISI"): del st.session_state['risultati']; st.rerun()
        df, flotta = st.session_state['risultati'], st.session_state['flotta_finale']
        df['Partenza'] = pd.to_datetime(df['Partenza']); df['Arrivo'] = pd.to_datetime(df['Arrivo'])
        colors = {d: DRIVER_COLORS[i % len(DRIVER_COLORS)] for i, d in enumerate(flotta['Autista'].unique())}
        st.write("### 📊 Situazione Mezzi")
        cols = st.columns(len(flotta))
        for i, (_, aut) in enumerate(flotta.iterrows()):
            n, s, t = aut['Autista'], aut['S_Count'], aut['Tipo Veicolo']
            with cols[i]:
                st.markdown(f'<div style="background-color:{colors[n]}; padding:20px; border-radius:15px; text-align:center; color:white;">'
                            f'<small>{n}</small><br><b style="font-size:24px;">{t}</b><br><hr style="margin:10px 0; border:0; border-top:1px solid rgba(255,255,255,0.3);">'
                            f'<span style="font-size:16px;">Servizi: {s}</span></div>', unsafe_allow_html=True)
        st.divider()
        st.subheader("🗓️ Tabella di Marcia")
        df_tab = df.copy(); df_tab['Inizio'] = df_tab['Partenza'].dt.strftime('%H:%M'); df_tab['Fine'] = df_tab['Arrivo'].dt.strftime('%H:%M')
        st.dataframe(df_tab[['Autista', 'ID', 'Mezzo', 'Da', 'Inizio', 'A', 'Fine', 'Status']].style.apply(
            lambda x: [f"background-color: {colors.get(x.Autista)}; color: white; font-weight: bold" for _ in x], axis=1), use_container_width=True)
        st.divider()
        ca, cc = st.columns(2)
        with ca:
            st.header("🕵️ Diario Autisti")
            sel = st.selectbox("Seleziona Autista:", flotta['Autista'].unique())
            for _, r in df[df['Autista'] == sel].iterrows():
                with st.expander(f"Corsa {r['ID']} - Ore {r['Partenza'].strftime('%H:%M')}", expanded=False):
                    st.write(f"📍 Proviene da: **{r['Prov']}**")
                    if r['M_V'] > 0: st.write(f"⏱️ Tempo prelievo: **{r['M_V']} min** + 15m accoglienza")
                    st.write(f"⏱️ Viaggio cliente: **{r['M_P']} min** + 15m scarico")
                    st.write(f"✅ Libero dalle: **{r['Arrivo'].strftime('%H:%M')}**")
        with cc:
            st.header("📍 Dettaglio Viaggio")
            sid = st.selectbox("Cerca ID Prenotazione:", df['ID'].unique())
            info = df[df['ID'] == sid].iloc[0]
            st.success(f"👤 **Autista:** {info['Autista']} | 🏢 **Veicolo:** {info['Veicolo']}")
            st.markdown(f"📍 **Prelievo:** {info['Da']} (**{info['Partenza'].strftime('%H:%M')}**)")
            st.markdown(f"🏁 **Destinazione:** {info['A']} (**{info['Arrivo'].strftime('%H:%M')}**)")