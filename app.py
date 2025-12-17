import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import re

# --- CONFIGURAZIONE ---
st.set_page_config(layout="wide", page_title="Dispatcher AI | Agnostic", page_icon="🚐")

DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722']
CAPACITA = {'berlina': 3, 'suv': 3, 'minivan': 7, 'van': 7, 'auto': 3}

# --- GOOGLE MAPS ---
def get_gmaps_info(origin, destination):
    if not origin or not destination or pd.isna(origin) or pd.isna(destination):
        return 30, "Indirizzo mancante"
    try:
        if "Maps_API_KEY" not in st.secrets:
            return 30, "Chiave API mancante"
        gmaps = googlemaps.Client(key=st.secrets["Maps_API_KEY"])
        res = gmaps.directions(origin, destination, mode="driving", departure_time=datetime.now(), language="it")
        if res and res[0]['legs']:
            leg = res[0]['legs'][0]
            durata = int(leg['duration_in_traffic']['value'] / 60)
            distanza = leg['distance']['text']
            steps = [re.sub('<[^<]+?>', '', s['html_instructions']) for s in leg['steps']]
            strade = " ➡️ ".join([s.split("verso")[0].strip() for s in steps if any(k in s.lower() for k in ["via", "viale", "autostrada", "raccordo"])][:4])
            return durata, f"{strade or 'Percorso diretto'} ({distanza})"
    except Exception as e:
        return 30, f"Errore Maps: {str(e)[:60]}"
    return 30, "Non calcolato"

# --- ASSEGNAZIONE SINGOLA O GRUPPO ---
def assign_to_fleet(group_df, dt_richiesta, prelievo, destinazione, tipo_v, flotta):
    """Assegna un gruppo (o singolo) al miglior autista disponibile"""
    tipo_v_lower = tipo_v.lower().strip()
    best_idx = None
    min_ritardo = float('inf')
    best_provenienza = ""

    for idx, aut in flotta.iterrows():
        if aut['tipo_veicolo'].strip().lower() != tipo_v_lower:
            continue
        
        dur_vuoto, _ = get_gmaps_info(aut['pos_attuale'], prelievo)
        pronto = aut['dt_disp'] + timedelta(minutes=dur_vuoto + 10)
        ritardo = max(0, (pronto - dt_richiesta).total_seconds() / 60)
        
        if ritardo < min_ritardo:
            min_ritardo = ritardo
            best_idx = idx
            best_provenienza = aut['pos_attuale']

    if best_idx is None:
        return []  # Nessun autista disponibile

    dur_corsa, itinerario = get_gmaps_info(prelievo, destinazione)
    partenza = max(dt_richiesta, flotta.at[best_idx, 'dt_disp'] + timedelta(minutes=dur_vuoto + 10))
    arrivo = partenza + timedelta(minutes=dur_corsa + 15)

    autista = flotta.at[best_idx, 'autista']
    mezzo = flotta.at[best_idx, 'id_veicolo']
    ids_gruppo = ", ".join(map(str, group_df['id'].tolist()))

    rows = []
    for _, riga in group_df.iterrows():
        rows.append({
            'Autista': autista,
            'ID': riga['id'],
            'Mezzo': mezzo,
            'Da': prelievo,
            'Partenza': partenza.strftime('%H:%M'),
            'A': destinazione,
            'Arrivo': arrivo.strftime('%H:%M'),
            'Status': "PUNTUALE" if min_ritardo <= 5 else f"RITARDO {int(min_ritardo)}m",
            'Passeggeri': riga['passeggeri'],
            'Gruppo': ids_gruppo if len(group_df) > 1 else "",
            'Itinerario': itinerario,
            'Provenienza': best_provenienza
        })

    # Aggiorna stato autista
    flotta.at[best_idx, 'dt_disp'] = arrivo
    flotta.at[best_idx, 'pos_attuale'] = destinazione

    return rows

# --- MOTORE PRINCIPALE ---
def run_dispatch(df_prenotazioni, df_flotta, mapping):
    pren = df_prenotazioni.rename(columns=mapping['pren']).copy()
    flotta = df_flotta.rename(columns=mapping['flotta']).copy()

    # Colonne obbligatorie
    req_pren = ['id', 'ora', 'tipo_veicolo', 'prelievo', 'destinazione']
    req_flotta = ['autista', 'disponibile_da', 'tipo_veicolo', 'id_veicolo']
    
    for col in req_pren:
        if col not in pren.columns:
            st.error(f"Colonna mancante in Prenotazioni: {col}")
            return pd.DataFrame()
    for col in req_flotta:
        if col not in flotta.columns:
            st.error(f"Colonna mancante in Flotta: {col}")
            return pd.DataFrame()

    # Opzionali
    if 'passeggeri' not in pren.columns:
        pren['passeggeri'] = 1
    if 'posizione_iniziale' not in flotta.columns:
        flotta['posizione_iniziale'] = "Base operativa"

    # Parsing orari
    def parse_time(t):
        if pd.isna(t):
            return datetime.combine(datetime.today(), datetime.min.time())
        if isinstance(t, str):
            t = t.strip().replace('.', ':')
            for fmt in ('%H:%M', '%H:%M:%S'):
                try:
                    return datetime.strptime(t, fmt)
                except:
                    pass
        if hasattr(t, 'time'):
            return datetime.combine(datetime.today(), t.time())
        return datetime.combine(datetime.today(), datetime.min.time())

    pren['dt_richiesta'] = pren['ora'].apply(parse_time)
    flotta['dt_disp'] = flotta['disponibile_da'].apply(parse_time)
    flotta['pos_attuale'] = flotta['posizione_iniziale']

    pren = pren.sort_values('dt_richiesta').reset_index(drop=True)
    risultati = []

    # Pooling: stesso orario (±5 min), stesso percorso e tipo veicolo
    pren['pool_key'] = (
        pren['dt_richiesta'].dt.floor('5min').astype(str) + "_" +
        pren['prelievo'].astype(str) + "_" +
        pren['destinazione'].astype(str) + "_" +
        pren['tipo_veicolo'].str.lower().str.strip()
    )

    for pool_key, group in pren.groupby('pool_key'):
        dt_richiesta = group['dt_richiesta'].min()
        prelievo = group['prelievo'].iloc[0]
        destinazione = group['destinazione'].iloc[0]
        tipo_v = group['tipo_veicolo'].iloc[0].capitalize()
        tot_pax = group['passeggeri'].sum()
        capacita = CAPACITA.get(tipo_v.lower(), 4)

        if tot_pax > capacita:
            st.warning(f"Gruppo ID {group['id'].tolist()} supera capacità ({tot_pax}/{capacita}). Assegno singolarmente.")
            for _, single in group.iterrows():
                single_group = pd.DataFrame([single])
                rows = assign_to_fleet(single_group, single['dt_richiesta'], single['prelievo'], single['destinazione'], tipo_v, flotta)
                risultati.extend(rows)
        else:
            rows = assign_to_fleet(group, dt_richiesta, prelievo, destinazione, tipo_v, flotta)
            risultati.extend(rows)

    return pd.DataFrame(risultati)

# --- INTERFACCIA ---
st.title("🚐 Dispatcher AI | Motore Agnostic")

if 'risultati' not in st.session_state:
    st.subheader("📂 Carica i file Excel")

    col1, col2 = st.columns(2)
    with col1:
        file_pren = st.file_uploader("Prenotazioni clienti", type="xlsx")
    with col2:
        file_flotta = st.file_uploader("Flotta autisti", type="xlsx")

    if file_pren and file_flotta:
        df_p = pd.read_excel(file_pren)
        df_f = pd.read_excel(file_flotta)

        st.success("File caricati! Mappa le colonne obbligatorie.")

        cols_p = df_p.columns.tolist()
        cols_f = df_f.columns.tolist()

        with st.expander("Mappatura Prenotazioni", expanded=True):
            map_pren = {
                'id': st.selectbox("ID Prenotazione", cols_p),
                'ora': st.selectbox("Ora Richiesta (hh:mm)", cols_p),
                'tipo_veicolo': st.selectbox("Tipo Veicolo", cols_p),
                'prelievo': st.selectbox("Indirizzo Prelievo", cols_p),
                'destinazione': st.selectbox("Destinazione", cols_p),
            }

        with st.expander("Mappatura Flotta", expanded=True):
            map_flotta = {
                'autista': st.selectbox("Autista", cols_f),
                'disponibile_da': st.selectbox("Disponibile da (hh:mm)", cols_f),
                'tipo_veicolo': st.selectbox("Tipo Veicolo", cols_f),
                'id_veicolo': st.selectbox("ID Veicolo / Targa", cols_f),
            }

        if st.button("CALCOLA CRONOPROGRAMMA", type="primary", use_container_width=True):
            with st.spinner("Elaborazione..."):
                df_ris = run_dispatch(df_p, df_f, {'pren': map_pren, 'flotta': map_flotta})
                if not df_ris.empty:
                    st.session_state.risultati = df_ris
                    st.rerun()
                else:
                    st.error("Nessuna corsa assegnata. Verifica dati e disponibilità.")

else:
    df = st.session_state.risultati

    if st.button("Carica nuovi file"):
        st.session_state.clear()
        st.rerun()

    colors = {aut: DRIVER_COLORS[i % len(DRIVER_COLORS)] for i, aut in enumerate(df['Autista'].unique())}

    st.subheader("Cronoprogramma Operativo")
    display_cols = ['Autista', 'ID', 'Mezzo', 'Da', 'Partenza', 'A', 'Arrivo', 'Status', 'Passeggeri', 'Gruppo']
    st.dataframe(
        df[display_cols].style.apply(
            lambda row: [f"background-color: {colors.get(row.Autista, '#333')}; color: white; font-weight: bold" for _ in row],
            axis=1
        ),
        use_container_width=True
    )

    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        st.header("Dettaglio Autista")
        autista = st.selectbox("Scegli autista", df['Autista'].unique())
        for _, r in df[df['Autista'] == autista].iterrows():
            with st.expander(f"ID {r['ID']} - {r['Partenza']} (Pax: {r['Passeggeri']})"):
                st.write(f"A vuoto da: **{r['Provenienza']}**")
                if r['Gruppo']:
                    st.success(f"Pooling: {r['Gruppo']}")

    with c2:
        st.header("Dettaglio Percorso")
        id_sel = st.selectbox("Scegli ID", df['ID'].unique())
        info = df[df['ID'] == id_sel].iloc[0]
        st.info(f"Itinerario (traffico reale):\n\n{info['Itinerario']}")