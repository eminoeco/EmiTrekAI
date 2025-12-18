import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps

# --- CONFIGURAZIONE E STILE ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | Gestione Flotta", page_icon="🚐")
pd.options.mode.chained_assignment = None

st.markdown("""
    <style>
    .stButton > button {
        background-color: #FF4B4B; color: white; border-radius: 20px;
        height: 3.5em; width: 100%; font-size: 20px; font-weight: bold;
        transition: 0.3s; border: none; box-shadow: 0px 4px 15px rgba(255, 75, 75, 0.3);
    }
    .stButton > button:hover { background-color: #FF1A1A; transform: translateY(-2px); }
    .main-title { color: #1E1E1E; font-size: 45px; font-weight: 800; text-align: center; padding-top: 10px; }
    .sub-title { color: #666; font-size: 18px; text-align: center; margin-bottom: 30px; }
    </style>
""", unsafe_allow_html=True)

# --- LOGIN OTTIMIZZATO (Senza doppio click) ---
def check_password():
    if "password_correct" not in st.session_state:
        st.markdown('<h1 class="main-title">🔒 Accesso Area Riservata</h1>', unsafe_allow_html=True)
        st.markdown('<p class="sub-title">Inserisci le tue credenziali per operare sulla flotta</p>', unsafe_allow_html=True)
        
        col1, col2 = st.columns([1,1])
        with col1: 
            user_input = st.text_input("Nome Utente", key="user_box")
        with col2: 
            pwd_input = st.text_input("Password", type="password", key="pass_box")
        
        # Centriamo il tasto di login
        _, col_btn, _ = st.columns([1, 2, 1])
        with col_btn:
            if st.button("ACCEDI AL SISTEMA"):
                try:
                    # Legge dalla tabella [users.USERNAME] nei Secrets
                    if user_input in st.secrets["users"] and pwd_input == st.secrets["users"][user_input]["password"]:
                        st.session_state["password_correct"] = True
                        st.rerun() # Forza il caricamento immediato per evitare l'errore al primo click
                    else:
                        st.error("🚫 Credenziali non corrette. Riprova.")
                except KeyError:
                    st.error("❌ Configurazione Secrets errata (Tabella 'users' mancante).")
        return False
    return True

# --- FUNZIONI DI CALCOLO (GOOGLE E AI) ---
DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722']
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7}

def get_gmaps_info(origin, destination):
    try:
        if "MAPS_API_KEY" not in st.secrets: return 40, "Chiave mancante"
        api_key = st.secrets["MAPS_API_KEY"]
        gmaps = googlemaps.Client(key=api_key)
        res = gmaps.directions(origin, destination, mode="driving", departure_time=datetime.now())
        if res:
            leg = res[0]['legs'][0]
            durata = int(leg.get('duration_in_traffic', leg['duration'])['value'] / 60)
            if durata > 120: durata = 45 # Protezione anti-follia API
            return durata, f"{leg['distance']['text']}"
    except: return 40, "Stima prudenziale"
    return 40, "Stima"

def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()
    def parse_t(t):
        if isinstance(t, str): return datetime.strptime(t.strip().replace('.', ':'), '%H:%M')
        return datetime.combine(datetime.today(), t)
    
    df_c['DT_Richiesta'] = df_c['Ora Arrivo'].apply(parse_t)
    df_f['DT_Disp'] = df_f['Disponibile Da (hh:mm)'].apply(parse_t)
    df_f['Pos_Attuale'] = "BASE"; df_f['Servizi_Count'] = 0; df_f['Last_Time'] = pd.NaT; df_f['Pax_Oggi'] = 0
    
    res_list = []
    df_c = df_c.sort_values(by='DT_Richiesta')

    for _, riga in df_c.iterrows():
        tipo_v = str(riga['Tipo Veicolo Richiesto']).strip().capitalize()
        cap_max = CAPACITA.get(tipo_v, 3)
        best_aut_idx = None; min_punteggio = float('inf'); best_match_info = {}
        autisti_idonei = df_f[df_f['Tipo Veicolo'].str.capitalize() == tipo_v]

        for f_idx, aut in autisti_idonei.iterrows():
            # CAR POOLING
            is_pooling = (aut['Pos_Attuale'] == riga['Destinazione Finale'] and not pd.isna(aut['Last_Time']) and 
                          abs((aut['Last_Time'] - riga['DT_Richiesta']).total_seconds()) <= 300 and aut['Pax_Oggi'] < cap_max)
            if is_pooling:
                best_aut_idx = f_idx
                best_match_info = {'pronto': riga['DT_Richiesta'], 'da': "Car Pooling", 'dur_vuoto': 0, 'ritardo': 0}
                break

            # SATURAZIONE TURNI (Priorità a chi lavora già)
            if aut['Servizi_Count'] == 0: dur_v = 0; ora_pronto = riga['DT_Richiesta']
            else:
                dur_v, _ = get_gmaps_info(aut['Pos_Attuale'], riga['Indirizzo Prelievo'])
                ora_pronto = aut['DT_Disp'] + timedelta(minutes=dur_v + 15)

            ritardo = max(0, (ora_pronto - riga['DT_Richiesta']).total_seconds() / 60)
            bonus_attivita = 5000 if aut['Servizi_Count'] > 0 else 0
            punteggio = (ritardo * 5000) + dur_v - bonus_attivita

            if punteggio < min_punteggio:
                min_punteggio = punteggio; best_aut_idx = f_idx
                best_match_info = {'pronto': ora_pronto, 'da': aut['Pos_Attuale'] if aut['Servizi_Count'] > 0 else "Primo Servizio", 'dur_vuoto': dur_v, 'ritardo': ritardo}

        if best_aut_idx is not None:
            dur_p, _ = get_gmaps_info(riga['Indirizzo Prelievo'], riga['Destinazione Finale'])
            partenza_eff = max(riga['DT_Richiesta'], best_match_info['pronto'])
            arrivo_eff = partenza_eff + timedelta(minutes=dur_p + 15)
            res_list.append({
                'Autista': df_f.at[best_aut_idx, 'Autista'], 'ID': riga['ID Prenotazione'],
                'Mezzo': df_f.at[best_aut_idx, 'ID Veicolo'], 'Veicolo': tipo_v,
                'Da': riga['Indirizzo Prelievo'], 'Partenza': partenza_eff,
                'A': riga['Destinazione Finale'], 'Arrivo': arrivo_eff,
                'Status': "🟢 OK" if best_match_info['ritardo'] <= 5 else f"🔴 RITARDO {int(best_match_info['ritardo'])} min",
                'M_Vuoto': best_match_info['dur_vuoto'], 'M_Pieno': dur_p, 'Provenienza': best_match_info['da']
            })
            df_f.at[best_aut_idx, 'DT_Disp'] = arrivo_eff; df_f.at[best_aut_idx, 'Pos_Attuale'] = riga['Destinazione Finale']
            df_f.at[best_aut_idx, 'Last_Time'] = riga['DT_Richiesta']; df_f.at[best_aut_idx, 'Servizi_Count'] += 1; df_f.at[best_aut_idx, 'Pax_Oggi'] += 1
            
    return pd.DataFrame(res_list), df_f

# --- ESECUZIONE APP ---
if check_password():
    st.markdown('<h1 class="main-title">🚐 EmiTrekAI Dispatcher</h1>', unsafe_allow_html=True)
    st.markdown('<p class="sub-title">Piano operativo ottimizzato per flotta NCC</p>', unsafe_allow_html=True)

    if 'risultati' not in st.session_state:
        st.write("### 📂 Caricamento Dati")
        c1, c2 = st.columns(2)
        with c1: f_c = st.file_uploader("📋 Lista Prenotazioni (.xlsx)", type=['xlsx'])
        with c2: f_f = st.file_uploader("🚘 Flotta Disponibile (.xlsx)", type=['xlsx'])
        
        if f_c and f_f:
            st.markdown("<br>", unsafe_allow_html=True)
            col_btn = st.columns([1, 2, 1])
            with col_btn[1]:
                if st.button("✨ CALCOLA CRONOPROGRAMMA AI"):
                    res, flotta_agg = run_dispatch(pd.read_excel(f_c), pd.read_excel(f_f))
                    st.session_state['risultati'] = res
                    st.session_state['flotta_finale'] = flotta_agg
                    st.rerun()
    else:
        if st.button("🔄 AVVIA NUOVA ANALISI"):
            del st.session_state['risultati']; st.rerun()

        df = st.session_state['risultati']; flotta = st.session_state['flotta_finale']
        df['Partenza'] = pd.to_datetime(df['Partenza']); df['Arrivo'] = pd.to_datetime(df['Arrivo'])
        driver_color_map = {d: DRIVER_COLORS[i % len(DRIVER_COLORS)] for i, d in enumerate(flotta['Autista'].unique())}

        # --- RIEPILOGO FLOTTA ---
        st.write("### 📊 Situazione Mezzi")
        cols = st.columns(len(flotta))
        for i, (_, aut) in enumerate(flotta.iterrows()):
            nome = aut['Autista']; servizi = aut['Servizi_Count']; tipo = aut['Tipo Veicolo']
            cor = driver_color_map.get(nome, "#BDC3C7")
            with cols[i]:
                st.markdown(f"""
                    <div style="background-color:{cor}; padding:20px; border-radius:15px; text-align:center; color:white; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                        <small>{nome}</small><br>
                        <b style="font-size:24px;">{tipo}</b><br>
                        <hr style="margin:10px 0; border:0; border-top:1px solid rgba(255,255,255,0.3);">
                        <span style="font-size:16px;">Servizi: {servizi}</span>
                    </div>
                """, unsafe_allow_html=True)

        st.divider()
        st.subheader("🗓️ Tabella di Marcia")
        df_tab = df.copy(); df_tab['Inizio'] = df_tab['Partenza'].dt.strftime('%H:%M'); df_tab['Fine'] = df_tab['Arrivo'].dt.strftime('%H:%M')
        st.dataframe(df_tab[['Autista', 'ID', 'Mezzo', 'Da', 'Inizio', 'A', 'Fine', 'Status']].style.apply(
            lambda x: [f"background-color: {driver_color_map.get(x.Autista)}; color: white; font-weight: bold" for _ in x], axis=1), use_container_width=True)

        st.divider()
        c_aut, c_cli = st.columns(2)
        with c_aut:
            st.header("🕵️ Diario Autisti")
            sel_aut = st.selectbox("Seleziona Autista:", flotta['Autista'].unique())
            for _, r in df[df['Autista'] == sel_aut].iterrows():
                with st.expander(f"Corsa {r['ID']} - Ore {r['Partenza'].strftime('%H:%M')}", expanded=False):
                    st.write(f"📍 Proviene da: **{r['Provenienza']}**")
                    if r['M_Vuoto'] > 0: st.write(f"⏱️ Guida a vuoto: **{r['M_Vuoto']} min** + 15m accoglienza")
                    st.write(f"⏱️ Viaggio cliente: **{r['M_Pieno']} min** + 15m scarico")
                    st.write(f"✅ Libero dalle: **{r['Arrivo'].strftime('%H:%M')}**")
        
        with c_cli:
            st.header("📍 Dettaglio Cliente")
            sel_id = st.selectbox("Cerca ID Prenotazione:", df['ID'].unique())
            info = df[df['ID'] == sel_id].iloc[0]
            st.success(f"👤 **Autista:** {info['Autista']} | 🏢 **Veicolo:** {info['Veicolo']}")
            st.markdown(f"📍 **Prelievo:** {info['Da']} (**{info['Partenza'].strftime('%H:%M')}**)")
            st.markdown(f"🏁 **Destinazione:** {info['A']} (**{info['Arrivo'].strftime('%H:%M')}**)")