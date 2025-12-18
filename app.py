import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import vertexai
from vertexai.generative_models import GenerativeModel
import tempfile, json, os

# --- AUTH VERTEX AI (Configurazione sicura e persistente) ---
# Per evitare errori, inizializziamo Vertex AI una sola volta per sessione.
if "VERTEX_READY" not in st.session_state:
    try:
        # Crea un file temporaneo per le credenziali di servizio
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            json.dump(dict(st.secrets["gcp_service_account"]), f)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = f.name
        
        # Inizializza Vertex AI con il Project ID e la Location corretti
        vertexai.init(project=st.secrets["gcp_service_account"]["project_id"], location="us-central1")
        # Carica il modello Gemini una sola volta
        st.session_state["vertex_model"] = GenerativeModel("gemini-1.5-flash")
        st.session_state["VERTEX_READY"] = True
        # Pulisci il file temporaneo dopo l'uso
        os.remove(f.name) 
    except Exception as e:
        st.error(f"Errore inizializzazione Vertex AI. Verifica Secrets e permessi IAM: {e}")

model = st.session_state.get("vertex_model")

# --- CONFIGURAZIONE UI GLOBALE (Estetica avanzata) ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | SaaS Smart Dispatch", page_icon="🚐")
pd.options.mode.chained_assignment = None # Evita warning di Pandas

# CSS personalizzato per un look & feel premium
st.markdown("""
    <style>
    /* Stile per i bottoni principali */
    .stButton > button {
        background-color: #FF4B4B; color: white; border-radius: 20px;
        height: 3.8em; width: 100%; font-size: 20px; font-weight: bold;
        transition: 0.3s; border: none; box-shadow: 0px 4px 15px rgba(255, 75, 75, 0.4);
        display: block; margin: 0 auto;
    }
    .stButton > button:hover { background-color: #FF1A1A; transform: scale(1.02); }
    
    /* Titoli principali */
    .main-title { color: #1E1E1E; font-size: 48px; font-weight: 800; text-align: center; margin-bottom: 30px;}
    h2 { color: #333; font-size: 32px; border-bottom: 2px solid #FF4B4B; padding-bottom: 10px; margin-top: 40px;}
    h3 { color: #555; font-size: 24px; margin-top: 30px;}
    
    /* Espansore per i dettagli */
    .streamlit-expanderHeader { background-color: #f0f2f6; border-radius: 10px; padding: 10px; border: 1px solid #ddd;}
    .streamlit-expanderContent { background-color: #ffffff; border-radius: 10px; padding: 15px; border: 1px solid #ddd; border-top: none;}
    
    /* Barre di avanzamento */
    .stProgress > div > div > div > div { background-color: #2196F3; }
    
    /* Messaggi di stato */
    .stAlert { border-radius: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- GESTIONE ACCESSO (Come prima, robusto) ---
def check_password():
    if "password_correct" not in st.session_state:
        st.markdown('<h1 class="main-title">🔒 Accesso Area Riservata EmiTrekAI</h1>', unsafe_allow_html=True)
        col_u, col_p = st.columns(2)
        u = col_u.text_input("Username", key="u_input")
        p = col_p.text_input("Password", type="password", key="p_input")
        _, cb, _ = st.columns([1, 0.6, 1])
        with cb:
            if st.button("✨ ENTRA NEL SISTEMA"):
                if u in st.secrets["users"] and p == st.secrets["users"][u]["password"]:
                    st.session_state["password_correct"] = True; st.rerun()
                else: st.error("⚠️ Credenziali errate. Riprova.")
        return False
    return True

# --- MOTORE AD ALTA PRECISIONE (API + VERTEX AI) ---
def get_metrics_real(origin, dest):
    """Interroga Maps e Vertex AI, senza fallback (ritorno diretto di None in caso di errore)"""
    if model is None: # Se Vertex AI non si è inizializzato
        st.error("Vertex AI non inizializzato. Impossibile calcolare metriche reali.")
        return None, "N/D", False

    try:
        # Google Maps Directions API
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, dest, mode="driving", departure_time=datetime.now())
        
        if not res: # Se Maps non trova un percorso
            st.sidebar.warning(f"Maps: Nessun percorso trovato per {origin} -> {dest}.")
            return None, "N/D", False

        leg = res[0]['legs'][0]
        g_min = int(leg.get('duration_in_traffic', leg['duration'])['value'] / 60)
        dist = leg['distance']['text']
        
        # Validazione logistica Vertex AI (il vero "cervello" del sistema)
        prompt = (f"Sei un dispatcher NCC a Roma. Tratta {origin} -> {dest}. Maps stima {g_min} min. "
                  f"Considera ZTL, traffico reale, varchi aeroportuali. "
                  f"Rispondi SOLO con il numero intero dei minuti effettivi che ci vogliono.")
        ai_res = model.generate_content(prompt)
        final_t = int(''.join(filter(str.isdigit, ai_res.text)))
        
        return final_t, dist, True
    except Exception as e:
        st.sidebar.error(f"Errore API/Vertex: {e}. Controlla credenziali e fatturazione.")
        return None, "N/D", False # Restituisce None se c'è un errore grave

# --- LOGICA SMART DISPATCH (Pooling, 10+Tempo+10, Colori) ---
DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722', '#8BC34A', '#795548']
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7} # Mappatura capacità veicoli

def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()

    # Rilevamento automatico delle colonne (più robusto)
    col_c_id = next((c for c in df_c.columns if 'ID' in c.upper()), 'ID Prenotazione') # Fallback più descrittivo
    col_c_ora = next((c for c in df_c.columns if 'ORA' in c.upper() and 'ARRIVO' in c.upper()), 'Ora Arrivo')
    col_c_prel = next((c for c in df_c.columns if 'PRELIEVO' in c.upper() or 'INDIRIZZO' in c.upper()), 'Indirizzo Prelievo')
    col_c_dest = next((c for c in df_c.columns if 'DESTINAZIONE' in c.upper() or 'FINALE' in c.upper()), 'Destinazione Finale')
    col_c_tipo = next((c for c in df_c.columns if 'TIPO' in c.upper() or 'VEICOLO' in c.upper()), 'Tipo Veicolo Richiesto')
    
    col_f_aut = next((c for c in df_f.columns if 'AUTISTA' in c.upper()), 'Autista')
    col_f_id_v = next((c for c in df_f.columns if 'ID' in c.upper() and 'VEICOLO' in c.upper()), 'ID Veicolo')
    col_f_tipo_v = next((c for c in df_f.columns if 'TIPO' in c.upper() and 'VEICOLO' in c.upper()), 'Tipo Veicolo')
    col_f_disp = next((c for c in df_f.columns if 'DISPONIBILE' in c.upper() and 'HH:MM' in c.upper()), 'Disponibile Da (hh:mm)')

    # Conversione orari in oggetti datetime per calcoli precisi
    def parse_time_robust(t):
        if isinstance(t, datetime): return t # Già datetime
        if isinstance(t, pd.Timestamp): return t.to_pydatetime() # Da Timestamp a datetime
        try: # Prova a parsare stringhe H:M o H.M
            return datetime.combine(datetime.today(), datetime.strptime(str(t).replace('.', ':'), '%H:%M').time())
        except ValueError: # Fallback se il formato non è riconosciuto
            return datetime.now() # Usa l'ora attuale come fallback per evitare crash

    df_c['DT_RICHIESTA'] = df_c[col_c_ora].apply(parse_time_robust)
    df_f['DT_DISPONIBILE'] = df_f[col_f_disp].apply(parse_time_robust)
    df_f['Posizione_Attuale'] = "BASE" # La posizione iniziale di tutti gli autisti
    df_f['Servizi_Completati'] = 0
    df_f['Passeggeri_Oggi'] = 0 # Contatore per il pooling
    df_f['Ultima_Destinazione'] = "" # Per lo smart pooling
    
    results_list = []
    df_c = df_c.sort_values(by=['DT_RICHIESTA', col_c_dest]) # Ordina per ottimizzare

    progress_text = "Analisi e ottimizzazione per ogni corsa in corso..."
    status_bar = st.progress(0, text=progress_text)

    for i, (_, booking) in enumerate(df_c.iterrows()):
        status_bar.progress((i + 1) / len(df_c), text=f"Elaborazione: Corsa {booking[col_c_id]} ({booking[col_c_prel]} -> {booking[col_c_dest]})")
        
        requested_vehicle_type = booking[col_c_tipo].strip().capitalize()
        max_capacity = CAPACITA.get(requested_vehicle_type, 3) # Capacità predefinita Berlina

        assigned = False
        
        # --- FASE 1: SMART POOLING (Accorpamento) ---
        # Cerca autisti dello stesso tipo che sono già nella destinazione precedente di un'altra corsa
        # e che possono prendere più passeggeri.
        potential_pooling_drivers = df_f[
            (df_f[col_f_tipo_v].str.capitalize() == requested_vehicle_type) & 
            (df_f['Ultima_Destinazione'] == booking[col_c_dest]) & 
            (df_f['Passeggeri_Oggi'] < max_capacity)
        ]
        
        for idx_pooling, driver_pooling in potential_pooling_drivers.iterrows():
            # Trova l'ultima corsa assegnata a questo autista
            last_assigned_job = next((job for job in reversed(results_list) if job['Autista'] == driver_pooling[col_f_aut]), None)
            
            if last_assigned_job and abs((last_assigned_job['Partenza'] - booking['DT_RICHIESTA']).total_seconds()) <= 600: # Max 10 min di attesa per pooling
                results_list.append({
                    'Autista': driver_pooling[col_f_aut],
                    'ID Corsa': booking[col_c_id],
                    'Mezzo': driver_pooling[col_f_id_v],
                    'Tipo Veicolo': requested_vehicle_type,
                    'Da': booking[col_c_prel],
                    'Inizio': last_assigned_job['Inizio'], # Stesso orario di partenza per il pooling
                    'A': booking[col_c_dest], 
                    'Fine': last_assigned_job['Fine'],     # Stesso orario di arrivo per il pooling
                    'Status': f"💎 ACCORPATO ({requested_vehicle_type})",
                    'Minuti a Vuoto': 0, 
                    'Minuti con Passeggero': 0,
                    'Ritardo (min)': 0,
                    'API_Usate': True, 
                    'Provenienza': "Pooling"
                })
                df_f.at[idx_pooling, 'Passeggeri_Oggi'] += 1 # Incrementa i passeggeri trasportati
                assigned = True
                break # Corsa assegnata tramite pooling

        # --- FASE 2: ASSEGNAZIONE SINGOLA (10m Prelievo + Viaggio + 10m Scarico) ---
        if not assigned:
            eligible_drivers = df_f[df_f[col_f_tipo_v].str.capitalize() == requested_vehicle_type]
            best_match = None
            min_overall_delay = float('inf') # Cerca il ritardo minimo per l'autista

            for idx_driver, driver_info in eligible_drivers.iterrows():
                # Tempo di viaggio a vuoto (dalla posizione attuale dell'autista al prelievo)
                empty_drive_time_minutes, _, api_ok_dv = get_metrics_real(driver_info['Posizione_Attuale'], booking[col_c_prel])
                
                if empty_drive_time_minutes is None: empty_drive_time_minutes = 30 # Fallback in caso di errore API/Vertex
                
                # Orario in cui l'autista sarà pronto per il prelievo (Disponibilità + Viaggio a Vuoto + 10m Accoglienza)
                driver_ready_time = driver_info['DT_DISPONIBILE'] + timedelta(minutes=empty_drive_time_minutes + 10) 
                
                # Calcola il ritardo (quanto l'autista è in ritardo rispetto all'ora richiesta dal cliente)
                current_delay = max(0, (driver_ready_time - booking['DT_RICHIESTA']).total_seconds() / 60)
                
                # Ottimizzazione: se il ritardo è minimo, prendilo subito
                if current_delay <= min_overall_delay:
                    min_overall_delay = current_delay
                    best_match = (idx_driver, driver_ready_time, empty_drive_time_minutes, current_delay)

            if best_match:
                idx_driver, driver_ready_time, empty_drive_time_minutes, final_delay_minutes = best_match
                
                # Tempo di viaggio con passeggero (dal prelievo alla destinazione finale)
                passenger_drive_time_minutes, distance_str, api_ok_dp = get_metrics_real(booking[col_c_prel], booking[col_c_dest])
                
                if passenger_drive_time_minutes is None: passenger_drive_time_minutes = 30 # Fallback in caso di errore API/Vertex

                # Orario di partenza effettivo (non prima dell'orario richiesto o quando l'autista è pronto)
                actual_departure_time = max(booking['DT_RICHIESTA'], driver_ready_time)
                
                # Orario di arrivo effettivo (Partenza + Tempo di Viaggio Cliente + 10m Scarico)
                actual_arrival_time = actual_departure_time + timedelta(minutes=passenger_drive_time_minutes + 10) 
                
                results_list.append({
                    'Autista': df_f.at[idx_driver, col_f_aut],
                    'ID Corsa': booking[col_c_id],
                    'Mezzo': df_f.at[idx_driver, col_f_id_v],
                    'Tipo Veicolo': requested_vehicle_type,
                    'Da': booking[col_c_prel],
                    'Inizio': actual_departure_time.strftime('%H:%M'),
                    'A': booking[col_c_dest], 
                    'Fine': actual_arrival_time.strftime('%H:%M'),
                    'Status': "🟢 OK" if final_delay_minutes <= 2 else f"🔴 RITARDO {int(final_delay_minutes)} min",
                    'Minuti a Vuoto': empty_drive_time_minutes, 
                    'Minuti con Passeggero': passenger_drive_time_minutes,
                    'Ritardo (min)': int(final_delay_minutes),
                    'API_Usate': api_ok_dv and api_ok_dp, # Entrambe le chiamate API devono essere andate a buon fine
                    'Provenienza': driver_info['Posizione_Attuale']
                })
                
                # Aggiorna lo stato dell'autista dopo aver assegnato la corsa
                df_f.at[idx_driver, 'DT_DISPONIBILE'] = actual_arrival_time
                df_f.at[idx_driver, 'Posizione_Attuale'] = booking[col_c_dest]
                df_f.at[idx_driver, 'Servizi_Completati'] += 1
                df_f.at[idx_driver, 'Passeggeri_Oggi'] = 1 # Reset per un nuovo cliente singolo
                df_f.at[idx_driver, 'Ultima_Destinazione'] = booking[col_c_dest] # Per futuro pooling
    
    status_bar.empty() # Rimuove la barra di caricamento
    return pd.DataFrame(results_list), df_f

# --- UI PRINCIPALE (Dashboard interattiva e colorata) ---
if check_password():
    st.sidebar.button("🔓 LOGOUT", on_click=lambda: st.session_state.pop("password_correct"))
    st.markdown('<h1 class="main-title">🚐 EmiTrekAI | Smart Dispatch SaaS</h1>', unsafe_allow_html=True)
    
    if 'results_df' not in st.session_state:
        st.subheader("Carica i Dati per Iniziare l'Ottimizzazione")
        col_upload_p, col_upload_f = st.columns(2)
        f_prenotazioni = col_upload_p.file_uploader("📋 Carica File Prenotazioni (.xlsx)", type=['xlsx'])
        f_flotta = col_upload_f.file_uploader("🚘 Carica File Flotta (.xlsx)", type=['xlsx'])
        
        if f_prenotazioni and f_flotta:
            st.markdown("<br>", unsafe_allow_html=True) # Spazio
            _, col_button, _ = st.columns([1, 1.5, 1])
            with col_button:
                if st.button("🚀 AVVIA L'OTTIMIZZAZIONE INTELLIGENTE"):
                    with st.spinner("Analisi in corso con Google Maps e Vertex AI..."):
                        results_df, updated_fleet_df = run_dispatch(pd.read_excel(f_prenotazioni), pd.read_excel(f_flotta))
                        st.session_state['results_df'] = results_df
                        st.session_state['updated_fleet_df'] = updated_fleet_df
                        st.success("🎉 Ottimizzazione completata! Visualizza i risultati qui sotto.")
                        st.rerun() # Aggiorna la pagina per mostrare i risultati
    else:
        # Recupera i dati dalla sessione
        results_df = st.session_state['results_df']
        updated_fleet_df = st.session_state['updated_fleet_df']
        
        # Mappa gli autisti ai colori per la coerenza visiva
        driver_color_map = {driver: DRIVER_COLORS[i % len(DRIVER_COLORS)] 
                            for i, driver in enumerate(updated_fleet_df['Autista'].unique())}

        # --- Sezione "Situazione Mezzi" (Box colorate) ---
        st.subheader("📊 Situazione Attuale della Flotta")
        fleet_display_cols = st.columns(len(updated_fleet_df))
        for i, (_, driver_row) in enumerate(updated_fleet_df.iterrows()):
            driver_name = driver_row['Autista']
            with fleet_display_cols[i]:
                st.markdown(f"""
                <div style="background-color:{driver_color_map[driver_name]}; padding:20px; border-radius:15px; text-align:center; color:white; height:150px;">
                    <small>{driver_name}</small><br>
                    <b style="font-size:22px;">{driver_row['Tipo Veicolo']}</b><br>
                    <hr style="margin:10px 0; border:0; border-top:1px solid rgba(255,255,255,0.3);">
                    Servizi: {driver_row['Servizi_Completati']}
                </div>
                """, unsafe_allow_html=True)

        st.divider()

        # --- Tabella riepilogativa (DataFrame con colori) ---
        st.subheader("🗓️ Diario di Bordo Dettagliato")
        # Applica i colori agli autisti nella tabella
        styled_df = results_df.style.apply(lambda x: [f"background-color: {driver_color_map.get(x['Autista'], 'white')}; color: white; font-weight: bold" 
                                                      if x['Status'].startswith("🔴") or x['Status'].startswith("💎") 
                                                      else f"background-color: {driver_color_map.get(x['Autista'], 'white')}; color: white"
                                                      for _ in x], axis=1)
        st.dataframe(styled_df, use_container_width=True)

        st.divider()
        
        # --- Sezione Dettagli Interattivi ---
        col_diary, col_details = st.columns(2)
        with col_diary:
            st.subheader("🕵️ Diario di Bordo Autista")
            selected_driver = st.selectbox("Seleziona Autista per Dettagli:", updated_fleet_df['Autista'].unique(), key="select_driver_detail")
            
            for _, job in results_df[results_df['Autista'] == selected_driver].iterrows():
                with st.expander(f"Corsa {job['ID Corsa']} - Ore {job['Inizio']} ({job['Status']})"):
                    if job['Status'].startswith("🔴"): 
                        st.error(f"⚠️ RITARDO CRITICO: {job['Ritardo (min)']} minuti!")
                    elif job['Status'].startswith("💎"):
                        st.info(f"✨ Corsa accorpata! ({job['Tipo Veicolo']} - {job['Provenienza']})")
                    else:
                        st.success("✅ Corsa in orario.")
                    
                    st.write(f"🏢 **Mezzo Assegnato:** {job['Mezzo']} ({job['Tipo Veicolo']})")
                    st.write(f"📍 **Da:** {job['Da']} | **A:** {job['A']}")
                    st.write(f"⏱️ **Tempi Stimati:** A vuoto: {job['Minuti a Vuoto']} min | Con passeggero: {job['Minuti con Passeggero']} min")
                    st.write(f"➡️ **Partenza Prevista:** {job['Inizio']} | **Arrivo Previsto:** {job['Fine']}")
                    st.write(f"✅ **Autista sarà libero alle:** {job['Fine']}")

        with col_details:
            st.subheader("📍 Dettaglio Singola Prenotazione")
            selected_booking_id = st.selectbox("Cerca Dettagli per ID Prenotazione:", results_df['ID Corsa'].unique(), key="select_booking_detail")
            
            booking_info = results_df[results_df['ID Corsa'] == selected_booking_id].iloc[0]
            st.markdown(f"**Cliente ID:** `{booking_info['ID Corsa']}`")
            st.markdown(f"**Autista Assegnato:** <span style='background-color:{driver_color_map.get(booking_info['Autista'], 'gray')}; color:white; padding:5px 10px; border-radius:5px;'>{booking_info['Autista']}</span>", unsafe_allow_html=True)
            st.markdown(f"**Veicolo:** `{booking_info['Mezzo']} ({booking_info['Tipo Veicolo']})`")
            st.markdown(f"**Partenza:** `{booking_info['Da']} alle {booking_info['Inizio']}`")
            st.markdown(f"**Destinazione:** `{booking_info['A']} con arrivo alle {booking_info['Fine']}`")
            st.markdown(f"**Stato:** `{booking_info['Status']}`")
            if not booking_info['API_Usate']:
                st.warning("⚠️ Nota: Alcuni tempi potrebbero essere stimati (errore API).")

        st.markdown("<br><br>", unsafe_allow_html=True) # Spazio alla fine
        _, col_reset, _ = st.columns([1, 1, 1])
        with col_reset:
            if st.button("🔄 AVVIA NUOVA ANALISI"): 
                for key in st.session_state.keys():
                    if key not in ["password_correct", "vertex_model", "VERTEX_READY"]: # Mantiene la password e l'init di Vertex
                        st.session_state.pop(key)
                st.rerun()