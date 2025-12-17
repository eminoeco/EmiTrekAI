import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import re

# --- CONFIGURAZIONE ---
st.set_page_config(layout="wide", page_title="Dispatcher AI | SaaS Agnostic", page_icon="🚐")

DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722']
CAPACITA = {'berlina': 3, 'suv': 3, 'minivan': 7, 'van': 7, 'auto': 3}  # Chiavi in minuscolo per robustezza

# --- FUNZIONE GOOGLE MAPS ---
def get_gmaps_info(origin, destination):
    if not origin or not destination:
        return 30, "Indirizzo mancante"
    try:
        if "Maps_API_KEY" not in st.secrets:
            return 30, "Chiave API mancante"
        gmaps = googlemaps.Client(key=st.secrets["Maps_API_KEY"])
        res = gmaps.directions(origin, destination, mode="driving", departure_time=datetime.now(), language="it")
        if res:
            leg = res[0]['legs'][0]
            durata = int(leg['duration_in_traffic']['value'] / 60)
            distanza = leg['distance']['text']
            steps = [re.sub('<[^<]+?>', '', s['html_instructions']) for s in leg['steps']]
            strade = " ➡️ ".join([s.split("verso")[0].strip() for s in steps if any(k in s.lower() for k in ["via", "viale", "autostrada", "raccordo"])][:4])
            return durata, f"{strade or 'Percorso diretto'} ({distanza})"
    except Exception as e:
        return 30, f"Errore Maps: {str(e)[:60]}"
    return 30, "Non calcolato"

# --- MOTORE DI DISPATCH ---
def run_dispatch(df_prenotazioni, df_flotta, mapping):
    # Normalizza nomi colonne
    pren = df_prenotazioni.rename(columns=mapping['pren']).copy()
    flotta = df_flotta.rename(columns=mapping['flotta']).copy()

    # Colonne obbligatorie con fallback
    required_pren = ['id', 'ora', 'tipo_veicolo', 'prelievo', 'destinazione']
    required_flotta = ['autista', 'disponibile_da', 'tipo_veicolo', 'id_veicolo']

    for col in required_pren:
        if col not in pren.columns:
            st.error(f"Colonna obbligatoria mancante nelle prenotazioni: {col}")
            return pd.DataFrame()
    for col in required_flotta:
        if col not in flotta.columns:
            st.error(f"Colonna obbligatoria nella flotta: {col}")
            return pd.DataFrame()

    # Opzionali
    if 'passeggeri' not in pren.columns:
        pren['passeggeri'] = 1
    if 'posizione_iniziale' not in flotta.columns:
        flotta['posizione_iniziale'] = "Roma Centro"  # Fallback generico

    # Parsing orari
    def parse_time(t):
        if pd.isna(t): return datetime.combine(datetime.today(), datetime.min.time())
        if isinstance(t, str):
            t = t.strip().replace('.', ':')
            for fmt in ('%H:%M', '%H:%M:%S'):
                try: return datetime.strptime(t, fmt)
                except: pass
        if isinstance(t, (datetime, pd.Timestamp)):
            return t if t.time() != datetime.min.time() else datetime.combine(datetime.today(), t.time())
        return datetime.combine(datetime.today(), datetime.min.time())

    pren['dt_richiesta'] = pren['ora'].apply(parse_time)
    flotta['dt_disp'] = flotta['disponibile_da'].apply(parse_time)
    flotta['pos_attuale'] = flotta['posizione_iniziale']

    pren = pren.sort_values('dt_richiesta')
    risultati = []

    # Raggruppa per pooling: stesso orario (±5 min tolleranza opzionale, qui esatto per semplicità), stesso percorso e tipo
    pren['gruppo_key'] = list(zip(
        pren['dt_richiesta'].dt.round('5min'),  # Tolleranza 5 min per pooling realistico
        pren['prelievo'],
        pren['destinazione'],
        pren['tipo_veicolo'].str.lower()
    ))

    for (dt_key, prelievo, destinazione, tipo_v), group in pren.groupby('gruppo_key'):
        tipo_v = tipo_v.capitalize()
        tot_pax = group['passeggeri'].sum()
        capacita_max = CAPACITA.get(tipo_v.lower(), 4)

        if tot_pax > capacita_max:
            st.warning(f"Gruppo {group['id'].tolist()} richiede {tot_pax} pax ma {tipo_v} ha capienza {capacita_max}. Verranno assegnati separatamente.")
            # In caso di overflow, tratta singolarmente (semplice fallback)
            for _, single in group.iterrows():
                risultati.extend(assign_single(single, flotta, pren, risultati))
            continue

        # Assegna gruppo
        assigned = assign_group(group, dt_key, prelievo, destinazione, tipo_v, tot_pax, flotta)
        risultati.extend(assigned)

    return pd.DataFrame(risultati)

def assign_group(group, dt_richiesta, prelievo, destinazione, tipo_v, tot_pax, flotta):
    best_idx = None
    min_ritardo = float('inf')
    log = {}

    for idx, aut in flotta.iterrows():
        if aut['tipo_veicolo'].strip().lower() != tipo_v.lower():
            continue
        dur_vuoto, _ = get_gmaps_info(aut['pos_attuale'], prelievo)
        pronto = aut['dt_disp'] + timedelta(minutes=dur_vuoto + 10)
        ritardo = max(0, (pronto - dt_richiesta).total_seconds() / 60)
        if ritardo < min_ritardo:
            min_ritardo = ritardo
            best_idx = idx
            log = {'pronto': pronto, 'provenienza': aut['pos_attuale']}

    if best_idx is None:
        return []  # Nessun veicolo disponibile

    dur_corsa, itinerario = get_gmaps_info(prelievo, destinazione)
    partenza = max(dt_richiesta, log['pronto'])
    arrivo = partenza + timedelta(minutes=dur_corsa + 15)

    rows = []
    ids_gruppo = ", ".join(map(str, group['id'].tolist()))
    for _, riga in group.iterrows():
        rows.append({
            'Autista': flotta.at[best_idx, 'autista'],
            'ID': riga['id'],
            'Mezzo': flotta.at[best_idx, 'id_veicolo'],
            'Da': prelievo,
            'Partenza': partenza.strftime('%H:%M'),
            'A': destinazione,
            'Arrivo': arrivo.strftime('%H:%M'),
            'Status': "PUNTUALE" if min_ritardo <= 5 else f"RITARDO {int(min_ritardo)}m",
            'Passeggeri': riga['passeggeri'],
            'Gruppo': ids_gruppo if len(group) > 1 else "",
            'Itinerario': itinerario,
            'Provenienza': log['provenienza']
        })

    # Aggiorna flotta
    flotta.at[best_idx, 'dt_disp'] = arrivo
    flotta.at[best_idx, 'pos_attuale'] = destinazione

    return rows

def assign_single(single_row, flotta, pren_df, current_results):
    # Fallback semplice per singoli (senza pooling forzato)
    return assign_group(pd.DataFrame([single_row]), single_row['dt_richiesta'], single_row['prelievo'],
                        single_row['destinazione'], single_row['tipo_veicolo'].capitalize(), single_row['passeggeri'], flotta)

# --- INTERFACCIA ---
st.title("🚐 Dispatcher AI | Motore di Smistamento Agnostic")

if 'risultati' not in st.session_state:
    st.subheader("📂 Carica i file Excel")

    col1, col2 = st.columns(2)
    with col1:
        file_pren = st.file_uploader("📅 Prenotazioni clienti", type="xlsx")
    with col2:
        file_flotta = st.file_uploader("🚖 Flotta autisti", type="xlsx")

    if file_pren and file_flotta:
        try:
            df_p = pd.read_excel(file_pren)
            df_f = pd.read_excel(file_flotta)

            st.success("File caricati! Ora mappa le colonne obbligatorie.")

            cols_p = df_p.columns.tolist()
            cols_f = df_f.columns.tolist()

            with st.expander("🔧 Mappatura colonne Prenotazioni", expanded=True):
                map_p = {
                    'id': st.selectbox("Colonna ID Prenotazione", cols_p, index=cols_p.index(next((c for c in cols_p if 'id' in c.lower()), cols_p[0])) if any('id' in c.lower() for c in cols_p) else 0),
                    'ora': st.selectbox("Colonna Ora Arrivo/Richiesta (hh:mm)", cols_p, index=cols_p.index(next((c for c in cols_p if any(k in c.lower() for k in ['ora', 'time', 'arrivo']), cols_p[0]))),
                    'tipo_veicolo': st.selectbox("Colonna Tipo Veicolo Richiesto", cols_p, index=0),
                    'prelievo': st.selectbox("Colonna Indirizzo Prelievo/Partenza", cols_p),
                    'destinazione': st.selectbox("Colonna Destinazione Finale", cols_p),
                }

            with st.expander("🔧 Mappatura colonne Flotta"):
                map_f = {
                    'autista': st.selectbox("Colonna Nome Autista", cols_f),
                    'disponibile_da': st.selectbox("Colonna Disponibile Da (hh:mm)", cols_f),
                    'tipo_veicolo': st.selectbox("Colonna Tipo Veicolo", cols_f),
                    'id_veicolo': st.selectbox("Colonna ID/Targa Veicolo", cols_f),
                }

            if st.button("🚀 CALCOLA CRONOPROGRAMMA", type="primary", use_container_width=True):
                with st.spinner("Elaborazione in corso..."):
                    risultati = run_dispatch(df_p, df_f, {'pren': map_p, 'flotta': map_f})
                    if not risultati.empty:
                        st.session_state['risultati'] = risultati
                        st.rerun()
                    else:
                        st.error("Nessuna assegnazione possibile o errore nei dati.")
        except Exception as e:
            st.error(f"Errore caricamento: {str(e)}")
else:
    df = st.session_state['risultati']

    if st.button("🔄 Carica nuovi file"):
        st.session_state.clear()
        st.rerun()

    unique_drivers = df['Autista'].unique()
    color_map = {d: DRIVER_COLORS[i % len(DRIVER_COLORS)] for i, d in enumerate(unique_drivers)}

    st.subheader("🗓️ Cronoprogramma Operativo")
    display = df[['Autista', 'ID', 'Mezzo', 'Da', 'Partenza', 'A', 'Arrivo', 'Status', 'Passeggeri', 'Gruppo']]
    st.dataframe(display.style.apply(lambda x: [f"background-color: {color_map.get(x.Autista, '#333')}; color: white; font-weight: bold" for _ in x], axis=1),
                 use_container_width=True)

    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        st.header("🕵️ Dettaglio Autista")
        aut = st.selectbox("Seleziona autista", unique_drivers)
        for _, r in df[df['Autista'] == aut].iterrows():
            with st.expander(f"Corse {r['ID']} → Partenza {r['Partenza']} (Pax: {r['Passeggeri']})"):
                st.write(f"📍 A vuoto da: **{r['Provenienza']}**")
                if r['Gruppo']:
                    st.success(f"🚀 Pooling con ID: {r['Gruppo']}")

    with c2:
        st.header("🛣️ Dettaglio Percorso")
        id_sel = st.selectbox("Seleziona ID", df['ID'].unique())
        info = df[df['ID'] == id_sel].iloc[0]
        st.info(f"Itinerario reale (traffico incluso):\n\n{info['Itinerario']}")