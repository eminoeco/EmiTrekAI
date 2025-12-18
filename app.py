import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import re

# --- CONFIGURAZIONE INTERFACCIA E STILE ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | Gestione Flotta", page_icon="🚐")
pd.options.mode.chained_assignment = None

# CSS per pulsanti centrati, colori vivaci e titoli professionali
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

# --- SISTEMA DI ACCESSO (Login al 1° Click) ---
def check_password():
    if "password_correct" not in st.session_state:
        st.markdown('<h1 class="main-title">🔒 Accesso Area Riservata</h1>', unsafe_allow_html=True)
        st.markdown('<p class="sub-title">Gestione operativa flotta EmiTrekAI</p>', unsafe_allow_html=True)
        
        # Form per invio istantaneo senza doppio click
        with st.form("login_form", clear_on_submit=False):
            col_u, col_p = st.columns(2)
            with col_u:
                u = st.text_input("Username", key="u", autocomplete="off")
            with col_p:
                p = st.text_input("Password", type="password", key="p", autocomplete="off")
            
            _, col_btn_login, _ = st.columns([1, 0.6, 1])
            with col_btn_login:
                if st.form_submit_button("✨ ENTRA NEL SISTEMA"):
                    try:
                        # Verifica credenziali nei Secrets
                        if u in st.secrets["users"] and p == st.secrets["users"][u]["password"]:
                            st.session_state["password_correct"] = True
                            st.rerun() 
                        else:
                            st.error("⚠️ Credenziali non riconosciute.")
                    except:
                        st.error("❌ Errore di configurazione nei Secrets.")
        return False
    return True

# --- MOTORE DI CALCOLO (Google Maps & AI) ---
DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722']
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7}

def get_gmaps_info(origin, destination):
    """Calcola tempi reali tramite API Google Maps"""
    try:
        if "MAPS_API_KEY" not in st.secrets:
            return 30, "Chiave API mancante"
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, destination, mode="driving", departure_time=datetime.now())
        if res:
            leg = res[0]['legs'][0]
            # Durata reale comprensiva di traffico
            durata = int(leg.get('duration_in_traffic', leg['duration'])['value'] / 60)
            return durata, f"{leg['distance']['text']}"
    except Exception:
        return 30, "Stima manuale (Timeout)"
    return 30, "Stima"

def run_dispatch(df_c, df_f):
    """Assegnazione intelligente dei servizi con saturazione flotta"""
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()
    
    def parse_time(t):
        if isinstance(t, str): return datetime.strptime(t.strip().replace('.', ':'), '%H:%M')
        return datetime.combine(datetime.today(), t)
        
    df_c['DT_Richiesta'] = df_c['Ora Arrivo'].apply(parse_time)
    df_f['DT_Disponibile'] = df_f['Disponibile Da (hh:mm)'].apply(parse_time)
    df_f['Posizione_Attuale'] = "BASE"
    df_f['Servizi_Count'] = 0 
    df_f['Last_Trip_Time'] = pd.NaT
    df_f['Passeggeri_Caricati'] = 0
    
    risultati = []
    df_c = df_c.sort_values(by='DT_Richiesta')

    for _, corsa in df_c.iterrows():
        tipo_v = str(corsa['Tipo Veicolo Richiesto']).strip().capitalize()
        cap_max = CAPACITA.get(tipo_v, 3)
        best_aut_idx = None
        min_punteggio = float('inf')
        match_info = {}

        # Filtro per tipologia veicolo
        autisti_idonei = df_f[df_f['Tipo Veicolo'].str.capitalize() == tipo_v]

        for idx, autista in autisti_idonei.iterrows():
            # 1. Verifica Car Pooling
            is_pooling = (autista['Posizione_Attuale'] == corsa['Destinazione Finale'] and 
                          not pd.isna(autista['Last_Trip_Time']) and
                          abs((autista['Last_Trip_Time'] - corsa['DT_Richiesta']).total_seconds()) <= 300 and 
                          autista['Passeggeri_Caricati'] < cap_max)
            
            if is_pooling:
                best_aut_idx = idx
                match_info = {'pronto': corsa['DT_Richiesta'], 'da': "Car Pooling", 'vuoto': 0, 'ritardo': 0}
                break

            # 2. Calcolo tempi di arrivo (Spostamento a vuoto + 15m accoglienza)
            if autista['Servizi_Count'] == 0:
                minuti_vuoto = 0
                ora_pronto = corsa['DT_Richiesta']
            else:
                minuti_vuoto, _ = get_gmaps_info(autista['Posizione_Attuale'], corsa['Indirizzo Prelievo'])
                ora_pronto = autista['DT_Disponibile'] + timedelta(minutes=minuti_vuoto + 15)

            # 3. Calcolo del ritardo effettivo
            ritardo = max(0, (ora_pronto - corsa['DT_Richiesta']).total_seconds() / 60)
            
            # 4. Logica AI Saturazione: Bonus a chi sta già lavorando
            bonus_saturazione = 5000 if autista['Servizi_Count'] > 0 else 0
            punteggio = (ritardo * 5000) + minuti_vuoto - bonus_saturazione

            if punteggio < min_punteggio:
                min_punteggio = punteggio
                best_aut_idx = idx
                match_info = {'pronto': ora_pronto, 'da': autista['Posizione_Attuale'] if autista['Servizi_Count'] > 0 else "BASE", 'vuoto': minuti_vuoto, 'ritardo': ritardo}

        # Assegnazione definitiva
        if best_aut_idx is not None:
            minuti_pieno, _ = get_gmaps_info(corsa['Indirizzo Prelievo'], corsa['Destinazione Finale'])
            partenza_effettiva = max(corsa['DT_Richiesta'], match_info['pronto'])
            arrivo_effettivo = partenza_effettiva + timedelta(minutes=minuti_pieno + 15) # +15m scarico

            risultati.append({
                'Autista': df_f.at[best_aut_idx, 'Autista'],
                'ID': corsa['ID Prenotazione'],
                'Mezzo': df_f.at[best_aut_idx, 'ID Veicolo'],
                'Tipo': tipo_v,
                'Prelievo': corsa['Indirizzo Prelievo'],
                'Partenza': partenza_effettiva,
                'Destinazione': corsa['Destinazione Finale'],
                'Arrivo': arrivo_effettivo,
                'Status': "🟢 OK" if match_info['ritardo'] <= 2 else f"🔴 RITARDO {int(match_info['ritardo'])} min",
                'M_Vuoto': match_info['vuoto'],
                'M_Pieno': minuti_pieno,
                'Provenienza': match_info['da'],
                'Ritardo_Val': int(match_info['ritardo'])
            })
            
            # Aggiornamento stato flotta
            df_f.at[best_aut_idx, 'DT_Disponibile'] = arrivo_effettivo
            df_f.at[best_aut_idx, 'Posizione_Attuale'] = corsa['Destinazione Finale']
            df_f.at[best_aut_idx, 'Last_Trip_Time'] = corsa['DT_Richiesta']
            df_f.at[best_aut_idx, 'Servizi_Count'] += 1
            df_f.at[best_aut_idx, 'Passeggeri_Caricati'] += 1
            
    return pd.DataFrame(risultati), df_f

# --- ESECUZIONE DASHBOARD ---
if check_password():
    # Logout laterale
    st.sidebar.button("🔓 ESCI DAL SISTEMA", on_click=lambda: st.session_state.pop("password_correct"))
    
    st.markdown('<h1 class="main-title">🚐 EmiTrekAI | Gestione Viaggi</h1>', unsafe_allow_html=True)
    st.markdown('<p class="sub-title">Monitoraggio e ottimizzazione flotta in tempo reale</p>', unsafe_allow_html=True)

    if 'risultati' not in st.session_state:
        st.write("### 📂 Carica i file della giornata")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            file_prenotazioni = st.file_uploader("📋 Lista Prenotazioni (.xlsx)", type=['xlsx'])
        with col_f2:
            file_flotta = st.file_uploader("🚘 Flotta Disponibile (.xlsx)", type=['xlsx'])
            
        if file_prenotazioni and file_flotta:
            st.markdown("<br>", unsafe_allow_html=True)
            _, col_btn_go, _ = st.columns([1, 1.5, 1])
            with col_btn_go:
                if st.button("🚀 ORGANIZZA I VIAGGI DI OGGI"):
                    df_res, df_flotta_agg = run_dispatch(pd.read_excel(file_prenotazioni), pd.read_excel(file_flotta))
                    st.session_state['risultati'] = df_res
                    st.session_state['flotta_finale'] = df_flotta_agg
                    st.rerun()
    else:
        # Visualizzazione Risultati
        df_res = st.session_state['risultati']
        df_flotta = st.session_state['flotta_finale']
        
        # Mappa colori autisti
        driver_colors = {d: DRIVER_COLORS[i % len(DRIVER_COLORS)] for i, d in enumerate(df_flotta['Autista'].unique())}
        
        st.write("### 📊 Riepilogo Operativo Flotta")
        box_cols = st.columns(len(df_flotta))
        for i, (_, autista_row) in enumerate(df_flotta.iterrows()):
            nome = autista_row['Autista']
            with box_cols[i]:
                st.markdown(f"""
                    <div style="background-color:{driver_colors[nome]}; padding:20px; border-radius:15px; text-align:center; color:white;">
                        <small>{nome}</small><br><b style="font-size:22px;">{autista_row['Tipo Veicolo']}</b><br>
                        <hr style="margin:10px 0; border:0; border-top:1px solid rgba(255,255,255,0.3);">
                        <span style="font-size:16px;">Servizi: {autista_row['Servizi_Count']}</span>
                    </div>
                """, unsafe_allow_html=True)

        st.divider()
        st.subheader("🗓️ Tabella di Marcia Ottimizzata")
        df_display = df_res.copy()
        df_display['Ora Inizio'] = df_display['Partenza'].dt.strftime('%H:%M')
        df_display['Ora Fine'] = df_display['Arrivo'].dt.strftime('%H:%M')
        
        st.dataframe(df_display[['Autista', 'ID', 'Mezzo', 'Prelievo', 'Ora Inizio', 'Destinazione', 'Ora Fine', 'Status']].style.apply(
            lambda x: [f"background-color: {driver_colors.get(x.Autista)}; color: white; font-weight: bold" for _ in x], axis=1), use_container_width=True)

        st.divider()
        col_d1, col_d2 = st.columns(2)
        
        with col_d1:
            st.header("🕵️ Diario di Bordo Autisti")
            sel_autista = st.selectbox("Seleziona Autista:", df_flotta['Autista'].unique())
            for _, r in df_res[df_res['Autista'] == sel_autista].iterrows():
                with st.expander(f"Corsa {r['ID']} - Ore {r['Partenza'].strftime('%H:%M')}", expanded=False):
                    # Sottolineatura Ritardo (Fondamentale)
                    if r['Ritardo_Val'] > 0:
                        st.error(f"⚠️ RITARDO RILEVATO: {r['Ritardo_Val']} minuti rispetto alla richiesta cliente!")
                    
                    st.write(f"📍 Proviene da: **{r['Provenienza']}**")
                    st.write(f"⏱️ Tempo di arrivo a vuoto: **{r['M_Vuoto']} min** + 15m accoglienza")
                    st.write(f"⏱️ Tempo di viaggio cliente: **{r['M_Pieno']} min** + 15m scarico")
                    st.write(f"✅ Autista nuovamente libero alle: **{r['Arrivo'].strftime('%H:%M')}**")
        
        with col_d2:
            st.header("📍 Dettaglio Spostamento")
            sel_id = st.selectbox("Cerca ID Prenotazione:", df_res['ID'].unique())
            info_corsa = df_res[df_res['ID'] == sel_id].iloc[0]
            st.success(f"👤 **Autista:** {info_corsa['Autista']} | 🏢 **Veicolo:** {info_corsa['Tipo']}")
            st.markdown(f"📍 **Prelievo:** {info_corsa['Prelievo']} (**{info_corsa['Partenza'].strftime('%H:%M')}**)")
            st.markdown(f"🏁 **Destinazione:** {info_corsa['Destinazione']} (**{info_corsa['Arrivo'].strftime('%H:%M')}**)")
            
            if "Car Pooling" in info_corsa['Provenienza']:
                st.warning("👥 Servizio effettuato in regime di Car Pooling.")
            
        if st.sidebar.button("🔄 NUOVA ANALISI"):
            del st.session_state['risultati']
            st.rerun()