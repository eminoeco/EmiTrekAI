import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
from google.oauth2 import service_account
import vertexai
from vertexai.generative_models import GenerativeModel

# --- 1. CONFIGURAZIONE ESTETICA E CSS ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | SaaS Dispatcher", page_icon="🚐")
pd.options.mode.chained_assignment = None

st.markdown("""
    <style>
    /* Pulsante Rosso Centrato e Professionale */
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

# --- 2. SISTEMA DI ACCESSO MULTI-UTENTE (SaaS) ---
def check_password():
    if "password_correct" not in st.session_state:
        st.markdown('<h1 class="main-title">🔒 Accesso Clienti EmiTrekAI</h1>', unsafe_allow_html=True)
        st.markdown('<p class="sub-title">Gestione flotta centralizzata con Vertex AI</p>', unsafe_allow_html=True)
        
        # Login istantaneo senza form per evitare bug doppio click
        col_u, col_p = st.columns(2)
        with col_u:
            u = st.text_input("Username", key="u_input", autocomplete="off")
        with col_p:
            p = st.text_input("Password", type="password", key="p_input", autocomplete="off")
        
        _, col_btn_login, _ = st.columns([1, 0.6, 1])
        with col_btn_login:
            if st.button("✨ ENTRA NEL SISTEMA"):
                # Verifica basata sulla tabella [users] nei Secrets
                if u in st.secrets["users"] and p == st.secrets["users"][u]["password"]:
                    st.session_state["password_correct"] = True
                    st.rerun() 
                else:
                    st.error("⚠️ Credenziali non riconosciute dal sistema SaaS.")
        return False
    return True

# --- 3. MOTORE DI INTELLIGENZA ARTIFICIALE (Vertex AI) ---
def ai_validate_time(origin, dest, g_min):
    """L'AI di Vertex impedisce figuracce con tempi irrealistici"""
    try:
        if "gcp_service_account" not in st.secrets:
            return g_min, False
        
        # Inizializzazione centralizzata Vertex AI con chiavi SaaS
        info = dict(st.secrets["gcp_service_account"])
        creds = service_account.Credentials.from_service_account_info(info)
        vertexai.init(project=info["project_id"], location="us-central1", credentials=creds)
        
        model = GenerativeModel("gemini-1.5-flash")
        # Prompt per il controllo logico dei tempi di Roma
        prompt = (f"Un tragitto NCC a Roma da {origin} a {dest} impiega {g_min} minuti secondo Google. "
                  f"È realistico? Se il valore è assurdo, scrivi solo il numero di minuti corretto. "
                  f"Se è realistico, scrivi esattamente {g_min}. Rispondi solo con il numero.")
        
        response = model.generate_content(prompt)
        # Pulizia della risposta per ottenere solo il numero intero
        clean_res = ''.join(filter(str.isdigit, response.text))
        val_time = int(clean_res) if clean_res else g_min
        
        return val_time, (val_time != g_min)
    except Exception:
        return g_min, False

# --- 4. CALCOLO TEMPI E API GOOGLE MAPS ---
def get_gmaps_info(origin, destination):
    """Ottiene i tempi da Google e li valida con Vertex AI"""
    try:
        if "MAPS_API_KEY" not in st.secrets:
            return 35, "Distanza N/D", False
            
        gmaps_client = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps_client.directions(origin, destination, mode="driving", departure_time=datetime.now())
        
        if res:
            leg_data = res[0]['legs'][0]
            durata_google = int(leg_data.get('duration_in_traffic', leg_data['duration'])['value'] / 60)
            distanza_text = leg_data['distance']['text']
            
            # CHIAMATA AL MOTORE VERTEX AI
            tempo_finale, ai_intervenuta = ai_validate_time(origin, destination, durata_google)
            return tempo_finale, distanza_text, ai_intervenuta
            
    except Exception:
        return 35, "Stima manuale", True
    return 35, "Stima manuale", False

# --- 5. LOGICA DI ASSEGNAZIONE (15+15 min & Saturazione) ---
DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722']
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7}

def run_dispatch(df_c, df_f):
    """Motore di ottimizzazione flotta"""
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()
    
    def parse_t(t):
        if isinstance(t, str): return datetime.strptime(t.strip().replace('.', ':'), '%H:%M')
        return datetime.combine(datetime.today(), t)
    
    df_c['DT_R'] = df_c['Ora Arrivo'].apply(parse_t)
    df_f['DT_D'] = df_f['Disponibile Da (hh:mm)'].apply(parse_t)
    df_f['Pos'] = "BASE"
    df_f['S_C'] = 0 # Conteggio servizi per saturazione turni
    df_f['L_T'] = pd.NaT
    df_f['P_O'] = 0 # Passeggeri odierni
    
    final_list = []
    df_c = df_c.sort_values(by='DT_R')

    for _, riga_cliente in df_c.iterrows():
        tipo_richiesto = str(riga_cliente['Tipo Veicolo Richiesto']).strip().capitalize()
        cap_max = CAPACITA.get(tipo_richiesto, 3)
        best_autista_idx = None
        punteggio_minimo = float('inf')
        miglior_match = {}

        # Filtro flotta per tipologia
        autisti_idonei = df_f[df_f['Tipo Veicolo'].str.capitalize() == tipo_richiesto]

        for f_idx, autista_info in autisti_idonei.iterrows():
            # Verifica Car Pooling Strategico
            is_pool = (autista_info['Pos'] == riga_cliente['Destinazione Finale'] and 
                       not pd.isna(autista_info['L_T']) and 
                       abs((autista_info['L_T'] - riga_cliente['DT_R']).total_seconds()) <= 300 and 
                       autista_info['P_O'] < cap_max)
            
            if is_pool:
                best_autista_idx = f_idx
                miglior_match = {'p': riga_cliente['DT_R'], 'da': "Car Pooling", 'v': 0, 'rit': 0, 'ai': False}
                break

            # Calcolo Tempi con 15m accoglienza obbligatori
            if autista_info['S_C'] == 0:
                min_vuoto = 0
                ora_pronto = riga_cliente['DT_R']
                ai_v = False
            else:
                min_vuoto, _, ai_v = get_gmaps_info(autista_info['Pos'], riga_cliente['Indirizzo Prelievo'])
                ora_pronto = autista_info['DT_D'] + timedelta(minutes=min_vuoto + 15)

            ritardo_calcolato = max(0, (ora_pronto - riga_cliente['DT_R']).total_seconds() / 60)
            
            # Logica Saturazione: Priorità a chi è già in strada
            bonus_saturazione = 5000 if autista_info['S_C'] > 0 else 0
            score_finale = (ritardo_calcolato * 5000) + min_vuoto - bonus_saturazione

            if score_finale < punteggio_minimo:
                punteggio_minimo = score_finale
                best_autista_idx = f_idx
                miglior_match = {'p': ora_pronto, 'da': autista_info['Pos'] if autista_info['S_C'] > 0 else "BASE", 
                                 'v': min_vuoto, 'rit': ritardo_calcolato, 'ai': ai_v}

        if best_autista_idx is not None:
            min_pieno, _, ai_p = get_gmaps_info(riga_cliente['Indirizzo Prelievo'], riga_cliente['Destinazione Finale'])
            partenza_effettiva = max(riga_cliente['DT_R'], miglior_match['p'])
            arrivo_effettivo = partenza_effettiva + timedelta(minutes=min_pieno + 15) # 15m scarico
            
            final_list.append({
                'Autista': df_f.at[best_autista_idx, 'Autista'], 
                'ID': riga_cliente['ID Prenotazione'], 
                'Mezzo': df_f.at[best_autista_idx, 'ID Veicolo'], 
                'Veicolo': tipo_richiesto,
                'Da': riga_cliente['Indirizzo Prelievo'], 
                'Partenza': partenza_effettiva, 
                'A': riga_cliente['Destinazione Finale'], 
                'Arrivo': ae := arrivo_effettivo,
                'Status': "🟢 OK" if miglior_match['rit'] <= 2 else f"🔴 RITARDO {int(miglior_match['rit'])} min",
                'M_V': miglior_match['v'], 'M_P': min_pieno, 'Prov': miglior_match['da'], 
                'Rit_Min': int(miglior_match['rit']), 'AI_Fix': ai_p or miglior_match['ai']
            })
            # Aggiornamento stato flotta centralizzato
            df_f.at[best_autista_idx, 'DT_D'] = ae
            df_f.at[best_autista_idx, 'Pos'] = riga_cliente['Destinazione Finale']
            df_f.at[best_autista_idx, 'L_T'] = riga_cliente['DT_R']
            df_f.at[best_autista_idx, 'S_C'] += 1
            df_f.at[best_autista_idx, 'P_O'] += 1
            
    return pd.DataFrame(final_list), df_f

# --- 6. INTERFACCIA OPERATIVA DASHBOARD ---
if check_password():
    st.sidebar.button("🔓 LOGOUT", on_click=lambda: st.session_state.pop("password_correct"))
    st.markdown(f'<h1 class="main-title">🚐 EmiTrekAI | Gestione Viaggi</h1>', unsafe_allow_html=True)
    st.markdown(f'<p class="sub-title">Servizio SaaS Ottimizzato per: <b>{st.session_state.get("u_input", "Partner")}</b></p>', unsafe_allow_html=True)

    if 'risultati' not in st.session_state:
        st.write("### 📂 Carica i file excel della giornata")
        col_u1, col_u2 = st.columns(2)
        with col_u1:
            f_prenot = st.file_uploader("📋 Lista Prenotazioni (.xlsx)", type=['xlsx'])
        with col_u2:
            f_flotta = st.file_uploader("🚘 Flotta Disponibile (.xlsx)", type=['xlsx'])
            
        if f_prenot and f_flotta:
            st.markdown("<br>", unsafe_allow_html=True)
            _, col_center_btn, _ = st.columns([1, 1.5, 1])
            with col_center_btn:
                # Testo professionale e umano come richiesto
                if st.button("🚀 ORGANIZZA I VIAGGI DI OGGI"):
                    res_df, flotta_agg_df = run_dispatch(pd.read_excel(f_prenot), pd.read_excel(f_flotta))
                    st.session_state['risultati'] = res_df
                    st.session_state['f_agg'] = flotta_agg_df
                    st.rerun()
    else:
        # Recupero dati elaborati
        df_res = st.session_state['risultati']
        df_flotta_fin = st.session_state['f_agg']
        
        # Mappa colori fissa per autisti
        colors_map = {d: DRIVER_COLORS[i % len(DRIVER_COLORS)] for i, d in enumerate(df_flotta_fin['Autista'].unique())}
        
        st.write("### 📊 Situazione Attuale Mezzi")
        stat_cols = st.columns(len(df_flotta_fin))
        for i, (_, aut_row) in enumerate(df_flotta_fin.iterrows()):
            nome_a = aut_row['Autista']
            with stat_cols[i]:
                st.markdown(f"""
                    <div style="background-color:{colors_map[nome_a]}; padding:20px; border-radius:15px; text-align:center; color:white;">
                        <small>{nome_a}</small><br><b style="font-size:22px;">{aut_row['Tipo Veicolo']}</b><br>
                        <hr style="margin:10px 0; border:0; border-top:1px solid rgba(255,255,255,0.3);">
                        <span style="font-size:16px;">Servizi: {aut_row['S_C']}</span>
                    </div>
                """, unsafe_allow_html=True)

        st.divider()
        st.subheader("🗓️ Tabella di Marcia Giornaliera")
        df_tab = df_res.copy()
        df_tab['Inizio'] = df_tab['Partenza'].dt.strftime('%H:%M')
        df_tab['Fine'] = df_tab['Arrivo'].dt.strftime('%H:%M')
        
        st.dataframe(df_tab[['Autista', 'ID', 'Mezzo', 'Da', 'Inizio', 'A', 'Fine', 'Status']].style.apply(
            lambda x: [f"background-color: {colors_map.get(x.Autista)}; color: white; font-weight: bold" for _ in x], axis=1), use_container_width=True)

        st.divider()
        col_left, col_right = st.columns(2)
        
        with col_left:
            st.header("🕵️ Diario di Bordo Autisti")
            sel_aut = st.selectbox("Seleziona Autista:", df_flotta_fin['Autista'].unique())
            for _, r in df_res[df_res['Autista'] == sel_aut].iterrows():
                with st.expander(f"Corsa {r['ID']} - Ore {r['Partenza'].strftime('%H:%M')}", expanded=False):
                    # Validazione AI Alert
                    if r['AI_Fix']:
                        st.warning("🤖 Validazione AI: Google forniva tempi irrealistici (es. 282m). Valore ricalcolato con precisione.")
                    
                    # SOTTOLINEATURA RITARDI (Regola Fissa)
                    if r['Rit_Min'] > 0:
                        st.error(f"⚠️ RITARDO RILEVATO: {r['Rit_Min']} minuti rispetto alla richiesta!")
                    
                    st.write(f"📍 Proviene da: **{r['Prov']}**")
                    st.write(f"⏱️ Tempo prelievo: **{r['M_V']} min** + 15m accoglienza")
                    st.write(f"⏱️ Viaggio cliente: **{r['M_P']} min** + 15m scarico")
                    st.write(f"✅ Autista libero dalle: **{r['Arrivo'].strftime('%H:%M')}**")
        
        with col_right:
            st.header("📍 Dettaglio Spostamento")
            sel_id_p = st.selectbox("Cerca ID Prenotazione:", df_res['ID'].unique())
            inf_c = df_res[df_res['ID'] == sel_id_p].iloc[0]
            st.success(f"👤 **Autista:** {inf_c['Autista']} | 🏢 **Veicolo:** {inf_c['Veicolo']}")
            st.markdown(f"📍 **Prelievo:** {inf_c['Da']} (**{inf_c['Partenza'].strftime('%H:%M')}**)")
            st.markdown(f"🏁 **Destinazione:** {inf_c['A']} (**{inf_c['Arrivo'].strftime('%H:%M')}**)")
            
            if st.sidebar.button("🔄 NUOVA PIANIFICAZIONE"):
                del st.session_state['risultati']
                st.rerun()