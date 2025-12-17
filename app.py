import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import re

# --- CONFIGURAZIONE ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | SaaS Fleet Dispatcher", page_icon="🚐")
pd.options.mode.chained_assignment = None

DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0', '#00BCD4', '#FF5722']
CAPACITA = {'Berlina': 3, 'Suv': 3, 'Minivan': 7}

# --- FUNZIONE API ---
def get_gmaps_info(origin, destination):
    try:
        if "MAPS_API_KEY" not in st.secrets:
            return 30, "⚠️ Errore: Chiave non trovata"
        api_key = st.secrets["MAPS_API_KEY"]
        gmaps = googlemaps.Client(key=api_key)
        res = gmaps.directions(origin, destination, mode="driving", language="it", departure_time=datetime.now())
        if res:
            leg = res[0]['legs'][0]
            durata = int(leg['duration_in_traffic']['value'] / 60)
            distanza = leg['distance']['text']
            steps = [re.sub('<[^<]+?>', '', s['html_instructions']) for s in leg['steps']]
            itinerario = " ➡️ ".join([s.split("verso")[0].strip() for s in steps if any(k in s for k in ["Via", "Viale", "A91", "Raccordo", "Autostrada"])][:3])
            return durata, f"{itinerario} ({distanza})"
    except Exception:
        return 30, "Calcolo GPS Standard"
    return 30, "Non disponibile"

# --- MOTORE DI DISPATCH CON LOGICA ANTI-ABBANDONO E PROSSIMITÀ ---
def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()
    
    def parse_t(t):
        if isinstance(t, str): return datetime.strptime(t.strip().replace('.', ':'), '%H:%M')
        return datetime.combine(datetime.today(), t)

    df_c['DT_Richiesta'] = df_c['Ora Arrivo'].apply(parse_t)
    df_f['DT_Disp'] = df_f['Disponibile Da (hh:mm)'].apply(parse_t)
    df_f['Pos_Attuale'] = "BASE"
    df_f['Servizi_Count'] = 0 
    df_f['Pax_Oggi'] = 0
    df_f['Last_Time'] = pd.NaT
    
    res_list = []
    df_c = df_c.sort_values(by='DT_Richiesta')

    for _, riga in df_c.iterrows():
        tipo_v = str(riga['Tipo Veicolo Richiesto']).strip().capitalize()
        cap_max = CAPACITA.get(tipo_v, 3)
        best_aut_idx = None
        min_punteggio = float('inf') 
        best_match_info = {}

        autisti_idonei = df_f[df_f['Tipo Veicolo'].str.capitalize() == tipo_v]

        for f_idx, aut in autisti_idonei.iterrows():
            # PRIORITÀ 1: POOLING
            is_pooling = (aut['Pos_Attuale'] == riga['Destinazione Finale'] and 
                          not pd.isna(aut['Last_Time']) and
                          abs((aut['Last_Time'] - riga['DT_Richiesta']).total_seconds()) <= 300 and 
                          aut['Pax_Oggi'] < cap_max)

            if is_pooling:
                best_aut_idx = f_idx
                best_match_info = {'pronto': riga['DT_Richiesta'], 'da': "Pooling", 'dur_vuoto': 0, 'ritardo': 0}
                break

            # Calcolo Tempi (15m buffer scarico incorporato in DT_Disp)
            if aut['Servizi_Count'] == 0:
                dur_v = 0
                ora_pronto = riga['DT_Richiesta']
            else:
                dur_v, _ = get_gmaps_info(aut['Pos_Attuale'], riga['Indirizzo Prelievo'])
                # Buffer 15m per prelievo/accoglienza
                ora_pronto = aut['DT_Disp'] + timedelta(minutes=dur_v + 15)

            ritardo = max(0, (ora_pronto - riga['DT_Richiesta']).total_seconds() / 60)
            
            # Ragionamento AI: Priorità a chi è puntuale, poi a chi è più vicino
            # Usiamo un peso elevato per il ritardo per assicurarci che il sistema cerchi sempre il meno ritardatario
            punteggio = ritardo * 5000 + dur_v 

            if punteggio < min_punteggio:
                min_punteggio = punteggio
                best_aut_idx = f_idx
                best_match_info = {
                    'pronto': ora_pronto, 
                    'da': aut['Pos_Attuale'] if aut['Servizi_Count'] > 0 else "Primo Servizio",
                    'dur_vuoto': dur_v,
                    'ritardo': ritardo
                }

        if best_aut_idx is not None:
            dur_p, itinerario_p = get_gmaps_info(riga['Indirizzo Prelievo'], riga['Destinazione Finale'])
            partenza_eff = max(riga['DT_Richiesta'], best_match_info['pronto'])
            # Buffer 15m scarico finale
            arrivo_eff = partenza_eff + timedelta(minutes=dur_p + 15)

            res_list.append({
                'Autista': df_f.at[best_aut_idx, 'Autista'],
                'ID': riga['ID Prenotazione'],
                'Mezzo': df_f.at[best_aut_idx, 'ID Veicolo'],
                'Veicolo_Tipo': tipo_v,
                'Da': riga['Indirizzo Prelievo'],
                'Partenza': partenza_eff,
                'A': riga['Destinazione Finale'],
                'Arrivo': arrivo_eff,
                'Status': "🟢 OK" if best_match_info['ritardo'] <= 5 else f"🔴 RITARDO {int(best_match_info['ritardo'])} min",
                'Itinerario': itinerario_p,
                'Provenienza': best_match_info['da'],
                'Minuti_Vuoto': best_match_info['dur_vuoto'],
                'Minuti_Pieno': dur_p
            })
            df_f.at[best_aut_idx, 'DT_Disp'] = arrivo_eff
            df_f.at[best_aut_idx, 'Pos_Attuale'] = riga['Destinazione Finale']
            df_f.at[best_aut_idx, 'Last_Time'] = riga['DT_Richiesta']
            df_f.at[best_aut_idx, 'Servizi_Count'] += 1
            df_f.at[best_aut_idx, 'Pax_Oggi'] += 1
            
    return pd.DataFrame(res_list)

# --- INTERFACCIA ---
st.title("🚐 EmiTrekAI | SaaS Fleet Dispatcher")

if 'risultati' not in st.session_state:
    st.subheader("📂 Caricamento Dati")
    c1, c2 = st.columns(2)
    with c1: f_c = st.file_uploader("Prenotazioni", type=['xlsx'])
    with c2: f_f = st.file_uploader("Flotta", type=['xlsx'])
    if f_c and f_f:
        if st.button("ELABORA CRONOPROGRAMMA"):
            st.session_state['risultati'] = run_dispatch(pd.read_excel(f_c), pd.read_excel(f_f))
            st.rerun()
else:
    if st.button("🔄 NUOVA ANALISI"):
        del st.session_state['risultati']; st.rerun()

    df = st.session_state['risultati']
    
    # CORREZIONE ERRORE ATTRIBUTO: Convertiamo entrambi in datetime
    df['Partenza'] = pd.to_datetime(df['Partenza'])
    df['Arrivo'] = pd.to_datetime(df['Arrivo'])
    
    unique_drivers = df['Autista'].unique()
    driver_color_map = {d: DRIVER_COLORS[i % len(DRIVER_COLORS)] for i, d in enumerate(unique_drivers)}

    # BOX RIEPILOGO
    st.write("### 📊 Riepilogo Flotta")
    cols = st.columns(len(unique_drivers))
    for i, autista in enumerate(unique_drivers):
        servizi = len(df[df['Autista'] == autista])
        mezzo = df[df['Autista'] == autista]['Mezzo'].iloc[0]
        with cols[i]:
            st.markdown(f"""<div style="background-color:{driver_color_map[autista]}; padding:10px; border-radius:8px; text-align:center; color:white;">
                <small>{autista}</small><br><strong>{mezzo}</strong><br>Servizi: {servizi}</div>""", unsafe_allow_html=True)

    st.divider()
    
    # TABELLA DI MARCIA
    st.subheader("🗓️ Tabella di Marcia (Ottimizzata AI)")
    df_tab = df.copy()
    df_tab['Partenza_H'] = df_tab['Partenza'].dt.strftime('%H:%M')
    df_tab['Arrivo_H'] = df_tab['Arrivo'].dt.strftime('%H:%M')
    st.dataframe(df_tab[['Autista', 'ID', 'Mezzo', 'Da', 'Partenza_H', 'A', 'Arrivo_H', 'Status']].style.apply(
        lambda x: [f"background-color: {driver_color_map.get(x.Autista)}; color: white; font-weight: bold" for _ in x], axis=1), use_container_width=True)

    st.divider()
    
    col_aut, col_cli = st.columns(2)
    with col_aut:
        st.header("🕵️ Spostamenti Autista")
        sel_aut = st.selectbox("Seleziona Autista:", unique_drivers)
        for _, r in df[df['Autista'] == sel_aut].iterrows():
            with st.expander(f"Corsa {r['ID']} - Ore {r['Partenza'].strftime('%H:%M')}", expanded=True):
                st.write(f"📍 Proviene da: **{r['Provenienza']}**")
                st.write(f"⏱️ Tempo a vuoto: **{r['Minuti_Vuoto']} min**")
                st.write(f"⏳ Buffer prelievo: **15 min**")
                st.write(f"⏱️ Viaggio cliente: **{r['Minuti_Pieno']} min**")
                st.write(f"⏳ Buffer scarico: **15 min**")

    with col_cli:
        st.header("📍 Dettaglio Cliente")
        sel_id = st.selectbox("ID Prenotazione:", df['ID'].unique())
        info = df[df['ID'] == sel_id].iloc[0]
        
        altri_pax = df[(df['Autista'] == info['Autista']) & 
                       (df['A'] == info['A']) &
                       (abs((df['Partenza'] - info['Partenza']).total_seconds()) <= 300) &
                       (df['ID'] != info['ID'])]['ID'].tolist()
        
        st.success(f"👤 **Autista:** {info['Autista']}")
        st.write(f"🏢 **Veicolo:** {info['Veicolo_Tipo']}")
        st.markdown(f"📍 **Partenza:** {info['Da']} (**{info['Partenza'].strftime('%H:%M')}**)")
        st.markdown(f"🏁 **Arrivo:** {info['A']}")
        if altri_pax:
            st.warning(f"👥 **Pooling:** {', '.join(map(str, altri_pax))}")
        else:
            st.info("🚘 **Servizio Singolo**")