import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps

# --- 1. CONFIGURAZIONE ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | Smart Dispatcher", page_icon="🚐")

# --- 2. MOTORE GOOGLE MAPS ---
def get_maps_data(origin, dest):
    try:
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, dest, mode="driving", departure_time=datetime.now())
        if res:
            leg = res[0]['legs'][0]
            minuti = int(leg.get('duration_in_traffic', leg['duration'])['value'] / 60)
            return minuti, leg['distance']['text']
    except Exception as e:
        st.sidebar.error(f"Errore Maps API: {e}")
    return 40, "N/D"

# --- 3. LOGICA DISPATCHER (Priorità Autisti Attivi + Pooling) ---
def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()
    
    # Rilevamento automatico colonne
    c_id = next((c for c in df_c.columns if 'ID' in c.upper()), df_c.columns[0])
    c_ora = next((c for c in df_c.columns if 'ORA' in c.upper()), df_c.columns[1])
    c_prel = next((c for c in df_c.columns if 'PRELIEVO' in c.upper()), df_c.columns[2])
    c_dest = next((c for c in df_c.columns if 'DESTINAZIONE' in c.upper()), df_c.columns[3])
    c_tipo = next((c for c in df_c.columns if 'TIPO' in c.upper()), df_c.columns[4])
    f_aut = next((c for c in df_f.columns if 'AUTISTA' in c.upper()), df_f.columns[0])
    f_disp = next((c for c in df_f.columns if 'DISPONIBILE' in c.upper()), df_f.columns[2])

    def parse_t(t):
        try: return datetime.combine(datetime.today(), datetime.strptime(str(t).replace('.', ':'), '%H:%M').time())
        except: return datetime.now()

    df_c['DT_TARGET'] = df_c[c_ora].apply(parse_t)
    df_f['DT_AVAIL'] = df_f[f_disp].apply(parse_t)
    df_f['Pos'] = "BASE"; df_f['Attivo'] = False # Stato iniziale

    results = []
    # Ordiniamo le prenotazioni per orario di partenza richiesto
    df_c = df_c.sort_values('DT_TARGET')

    for _, r in df_c.iterrows():
        best_driver_idx = None
        min_delay = float('inf')
        pooling_found = False

        # --- FASE 1: CERCA CAR POOLING O AUTISTA GIÀ ATTIVO ---
        # Priorità a chi è già fuori casa e può incastrare il viaggio
        for idx, f in df_f.iterrows():
            if str(f['Tipo Veicolo']).upper() != str(r[c_tipo]).upper(): continue
            
            # Calcolo tempo per arrivare al punto di ritrovo (Cliente n*2)
            t_per_ritrovo, _ = (0, "") if f['Pos'] == r[c_prel] else get_maps_data(f['Pos'], r[c_prel])
            
            # Orario in cui l'autista può effettivamente incontrare il cliente (10m ritrovo inclusi)
            ora_ritrovo_possibile = f['DT_AVAIL'] + timedelta(minutes=t_per_ritrovo + 10)
            
            ritardo = int(max(0, (ora_ritrovo_possibile - r['DT_TARGET']).total_seconds() / 60))
            
            # Se l'autista è già attivo e non fa ritardo, lo scegliamo subito (Pooling/Incastro)
            if f['Attivo'] and ritardo <= 5:
                best_driver_idx = idx
                min_delay = ritardo
                if f['Pos'] == r[c_prel]: pooling_found = True
                break
            
            # Teniamo traccia del miglior autista (anche non attivo) se nessuno è perfetto
            if ritardo < min_delay:
                min_delay = ritardo
                best_driver_idx = idx

        # --- FASE 2: ASSEGNAZIONE E CALCOLO PERCORSO ---
        if best_driver_idx is not None:
            f = df_f.loc[best_driver_idx]
            t_per_ritrovo, _ = (0, "") if f['Pos'] == r[c_prel] else get_maps_data(f['Pos'], r[c_prel])
            t_viaggio, dist = get_maps_data(r[c_prel], r[c_dest])

            inizio_effettivo = max(r['DT_TARGET'], f['DT_AVAIL'] + timedelta(minutes=t_per_ritrovo + 10))
            arrivo_destinazione = inizio_effettivo + timedelta(minutes=t_viaggio + 10) # +10m scarico

            results.append({
                'Autista': f[f_aut], 'ID': r[c_id], 'Da': r[c_prel], 'A': r[c_dest],
                'Partenza': inizio_effettivo.strftime('%H:%M'),
                'Arrivo': arrivo_destinazione.strftime('%H:%M'),
                'Durata': f"{t_viaggio} min", 'Distanza': dist,
                'Status': "🟢 OK" if min_delay <= 5 else f"🔴 RITARDO {min_delay} min",
                'Note': "💎 POOLING" if pooling_found else ("🔄 INCASTRO" if f['Attivo'] else "🆕 NUOVO")
            })

            # Aggiorna stato autista per il cliente successivo
            df_f.at[best_driver_idx, 'DT_AVAIL'] = arrivo_destinazione
            df_f.at[best_driver_idx, 'Pos'] = r[c_dest]
            df_f.at[best_driver_idx, 'Attivo'] = True

    return pd.DataFrame(results)

# --- 4. UI ---
st.title("🚐 EmiTrekAI | Dispatcher Intelligente")
up1 = st.file_uploader("📂 Prenotazioni", type=['xlsx'])
up2 = st.file_uploader("📂 Flotta", type=['xlsx'])

if up1 and up2 and st.button("🚀 GENERA PIANO OTTIMIZZATO"):
    df_res = run_dispatch(pd.read_excel(up1), pd.read_excel(up2))
    st.success("Piano generato: priorità autisti attivi e car pooling verificato.")
    st.dataframe(df_res, use_container_width=True)