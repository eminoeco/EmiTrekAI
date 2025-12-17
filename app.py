import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import re

# --- CONFIGURAZIONE ---
st.set_page_config(layout="wide", page_title="Dispatcher AI | SaaS", page_icon="🚐")

# Colori e Capacità (configurabili se necessario, ma per ora fisse)
DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722']
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7}  # Assumi tipi standard; estendibile

# --- FUNZIONE API (CON LOG DI ERRORE) ---
def get_gmaps_info(origin, destination):
    try:
        if "Maps_API_KEY" not in st.secrets:
            return 30, "ERRORE: Chiave API mancante nei Secrets"
        
        api_key = st.secrets["Maps_API_KEY"]
        gmaps = googlemaps.Client(key=api_key)
        
        res = gmaps.directions(origin, destination, mode="driving", language="it", departure_time=datetime.now())
        
        if res:
            leg = res[0]['legs'][0]
            durata = int(leg['duration_in_traffic']['value'] / 60)
            distanza = leg['distance']['text']
            # Estrazione strade principali
            steps = [re.sub('<[^<]+?>', '', s['html_instructions']) for s in leg['steps']]
            info_strade = " ➡️ ".join([s.split("verso")[0].strip() for s in steps if any(k in s for k in ["Via", "Viale", "A91", "Raccordo", "Autostrada"])][:3])
            return durata, f"{info_strade} ({distanza})"
    except Exception as e:
        return 30, f"ERRORE API: {str(e)}"
    return 30, "Percorso non calcolato"

# --- MOTORE DI DISPATCH (AGGIORNATO CON POOLING) ---
def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()
    
    def parse_t(t):
        if isinstance(t, str): 
            t = t.strip().replace('.', ':')
            try:
                return datetime.strptime(t, '%H:%M')
            except ValueError:
                return datetime.combine(datetime.today(), datetime.min.time())  # Fallback se formato errato
        return datetime.combine(datetime.today(), t)
    
    # Assumi colonne obbligatorie nei file Excel:
    # Prenotazioni: 'ID Prenotazione', 'Ora Arrivo', 'Tipo Veicolo Richiesto', 'Indirizzo Prelievo', 'Destinazione Finale', 'Passeggeri' (aggiunta per pooling, default 1 se mancante)
    # Flotta: 'Autista', 'Disponibile Da (hh:mm)', 'Tipo Veicolo', 'ID Veicolo', 'Posizione Iniziale' (aggiunta per agnostico)
    
    if 'Passeggeri' not in df_c.columns:
        df_c['Passeggeri'] = 1  # Default a 1 se non specificato
    
    df_c['DT_Richiesta'] = df_c['Ora Arrivo'].apply(parse_t)
    df_f['DT_Disp'] = df_f['Disponibile Da (hh:mm)'].apply(parse_t)
    df_f['Pos_Attuale'] = df_f['Posizione Iniziale']  # Posizione iniziale dinamica dal file
    
    res_list = []
    df_c = df_c.sort_values(by='DT_Richiesta')
    
    # Raggruppa prenotazioni poolabili: stesso orario esatto, stesso prelievo, stessa destinazione, stesso tipo veicolo
    grouped = df_c.groupby(['DT_Richiesta', 'Indirizzo Prelievo', 'Destinazione Finale', 'Tipo Veicolo Richiesto'])
    
    for name, group in grouped:
        tipo_v = str(name[3]).strip().capitalize()
        prelievo = name[1]
        destinazione = name[2]
        dt_richiesta = name[0]
        tot_pax = group['Passeggeri'].sum()
        ids = ", ".join(group['ID Prenotazione'].astype(str))  # Unisci ID per gruppo
        
        # Trova autista migliore per il gruppo
        best_aut_idx = None
        min_ritardo = float('inf')
        info_log = {}
        
        for f_idx, aut in df_f.iterrows():
            if str(aut['Tipo Veicolo']).strip().capitalize() != tipo_v: continue
            if tot_pax > CAPACITA.get(tipo_v, 0): continue  # Salta se pax > capacità
            
            # Calcolo tempi reali per spostamento a vuoto
            dur_v, _ = get_gmaps_info(aut['Pos_Attuale'], prelievo)
            ora_pronto = aut['DT_Disp'] + timedelta(minutes=dur_v + 10)  # +10 per buffer
            ritardo = max(0, (ora_pronto - dt_richiesta).total_seconds() / 60)
            
            if ritardo < min_ritardo:
                min_ritardo = ritardo
                best_aut_idx = f_idx
                info_log = {'pronto': ora_pronto, 'provenienza': aut['Pos_Attuale']}
        
        if best_aut_idx is not None:
            # Calcolo itinerario principale
            dur_p, itinerario_p = get_gmaps_info(prelievo, destinazione)
            partenza_eff = max(dt_richiesta, info_log['pronto'])
            arrivo_eff = partenza_eff + timedelta(minutes=dur_p + 15)  # +15 buffer scarico
            
            # Aggiungi riga per il gruppo (ma espandi a una riga per cliente nel display finale)
            for idx, riga in group.iterrows():
                res_list.append({
                    'Autista': df_f.at[best_aut_idx, 'Autista'],
                    'ID': riga['ID Prenotazione'],
                    'Mezzo': df_f.at[best_aut_idx, 'ID Veicolo'],
                    'Da': prelievo,
                    'Partenza': partenza_eff.strftime('%H:%M'),
                    'A': destinazione,
                    'Arrivo': arrivo_eff.strftime('%H:%M'),
                    'Status': "PUNTUALE" if min_ritardo <= 5 else f"RITARDO {int(min_ritardo)}m",
                    'Itinerario': itinerario_p,
                    'Provenienza': info_log['provenienza'],
                    'Passeggeri': riga['Passeggeri'],
                    'Gruppo IDs': ids if len(group) > 1 else None  # Per tracciare pooling
                })
            
            # Aggiorna autista: nuova disp e pos
            df_f.at[best_aut_idx, 'DT_Disp'] = arrivo_eff
            df_f.at[best_aut_idx, 'Pos_Attuale'] = destinazione
    
    return pd.DataFrame(res_list)

# --- INTERFACCIA CLEAN ---
st.title("🚐 Dispatcher AI | SaaS - Motore di Smistamento Agnostic")

if 'risultati' not in st.session_state:
    st.subheader("📂 Caricamento File Excel")
    st.info("Assicurati che i file abbiano le colonne corrette:\n- Prenotazioni: 'ID Prenotazione', 'Ora Arrivo', 'Tipo Veicolo Richiesto', 'Indirizzo Prelievo', 'Destinazione Finale', 'Passeggeri' (opzionale, default 1)\n- Flotta: 'Autista', 'Disponibile Da (hh:mm)', 'Tipo Veicolo', 'ID Veicolo', 'Posizione Iniziale'")
    col1, col2 = st.columns(2)
    with col1: f_c = st.file_uploader("Upload Prenotazioni (.xlsx)", type=['xlsx'])
    with col2: f_f = st.file_uploader("Upload Flotta (.xlsx)", type=['xlsx'])
    
    if f_c and f_f:
        if st.button("CALCOLA CRONOPROGRAMMA", type="primary", use_container_width=True):
            try:
                df_pren = pd.read_excel(f_c)
                df_flot = pd.read_excel(f_f)
                st.session_state['risultati'] = run_dispatch(df_pren, df_flot)
                st.rerun()
            except Exception as e:
                st.error(f"Errore nel caricamento/elaborazione: {str(e)}")
else:
    if st.button("🔄 CARICA NUOVI FILE", type="secondary"):
        del st.session_state['risultati']
        st.rerun()

    df = st.session_state['risultati']
    
    # Colori dinamici per autisti
    unique_drivers = df['Autista'].unique()
    color_map = {d: DRIVER_COLORS[i % len(DRIVER_COLORS)] for i, d in enumerate(unique_drivers)}

    st.subheader("🗓️ Cronoprogramma (Una riga per cliente)")
    display_df = df[['Autista', 'ID', 'Mezzo', 'Da', 'Partenza', 'A', 'Arrivo', 'Status', 'Passeggeri', 'Gruppo IDs']]
    st.dataframe(display_df.style.apply(
        lambda x: [f"background-color: {color_map.get(x.Autista)}; color: white; font-weight: bold" for _ in x], axis=1), use_container_width=True)

    st.divider()
    
    c_aut, c_cli = st.columns(2)
    with c_aut:
        st.header("🕵️ Dettaglio Autista (con Tracking Spostamenti)")
        sel_aut = st.selectbox("Scegli Autista:", unique_drivers)
        for _, r in df[df['Autista'] == sel_aut].iterrows():
            with st.expander(f"Corsa {r['ID']} - Partenza ore {r['Partenza']} (Pax: {r['Passeggeri']})"):
                st.write(f"📍 Spostamento a vuoto da: **{r['Provenienza']}** → {r['Da']} (calcolato con traffico reale)")
                if r['Gruppo IDs']:
                    st.write(f"🚀 Pooling con: {r['Gruppo IDs']}")
    
    with c_cli:
        st.header("📍 Dettaglio Percorso")
        sel_id = st.selectbox("Scegli ID Prenotazione:", df['ID'].unique())
        info = df[df['ID'] == sel_id].iloc[0]
        st.info(f"🛣️ **Itinerario Google (con traffico):** {info['Itinerario']}")