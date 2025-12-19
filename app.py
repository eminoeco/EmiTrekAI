import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps

# --- 1. CONFIGURAZIONE ESTETICA ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | Smart Dispatch", page_icon="🚐")

# --- 2. MOTORE GOOGLE MAPS ---
def get_maps_data(origin, dest):
    try:
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, dest, mode="driving", departure_time=datetime.now())
        if res:
            leg = res[0]['legs'][0]
            minuti = int(leg.get('duration_in_traffic', leg['duration'])['value'] / 60)
            return minuti, leg['distance']['text']
    except: return 45, "N/D"

# --- 3. LOGICA DISPATCHER AVANZATA (CORREZIONE POOLING) ---
def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()
    
    # Rilevamento automatico colonne (Fix KeyError)
    c_ora = next((c for c in df_c.columns if 'ORA' in c.upper()), df_c.columns[1])
    c_prel = next((c for c in df_c.columns if 'PRELIEVO' in c.upper()), df_c.columns[2])
    c_dest = next((c for c in df_c.columns if 'DESTINAZIONE' in c.upper()), df_c.columns[3])
    c_tipo = next((c for c in df_c.columns if 'TIPO' in c.upper()), df_c.columns[4])
    f_aut = next((c for c in df_f.columns if 'AUTISTA' in c.upper()), df_f.columns[0])
    f_disp = next((c for c in df_f.columns if 'DISPONIBILE' in c.upper()), df_f.columns[2])

    # FIX ORARIO: Converte l'orario Excel senza forzare l'ora attuale (pomeriggio)
    def parse_excel_time(t):
        if isinstance(t, datetime): return t
        try: return datetime.combine(datetime.today(), datetime.strptime(str(t)[:5].replace('.', ':'), '%H:%M').time())
        except: return datetime.now()

    df_c['DT_TARGET'] = df_c[c_ora].apply(parse_excel_time)
    df_f['DT_AVAIL'] = df_f[f_disp].apply(parse_excel_time)
    df_f['Pos'] = "BASE"
    df_f['Capacita'] = df_f['Tipo Veicolo'].map({'Berlina': 3, 'Suv': 4, 'Minivan': 7})

    results = []
    df_c = df_c.sort_values('DT_TARGET')

    for _, r in df_c.iterrows():
        assigned = False
        
        # --- FASE 1: SMART POOLING (Andrea prende i primi 3 insieme) ---
        for res in results:
            if (res['Da'] == r[c_prel] and res['A'] == r[c_dest] and 
                res['Partenza_DT'] == r['DT_TARGET'] and 
                res['Posti_Liberi'] > 0 and res['Tipo'] == r[c_tipo]):
                
                results.append({
                    'Autista': res['Autista'], 'ID': r[next(c for c in df_c.columns if 'ID' in c.upper())],
                    'Da': r[c_prel], 'A': r[c_dest], 'Partenza': res['Partenza'], 'Arrivo': res['Arrivo'],
                    'Status': res['Status'], 'Note': "💎 POOLING", 'Partenza_DT': res['Partenza_DT'],
                    'Posti_Liberi': res['Posti_Liberi'] - 1, 'Tipo': r[c_tipo]
                })
                assigned = True
                break

        # --- FASE 2: ASSEGNAZIONE NUOVA ---
        if not assigned:
            for idx, f in df_f.iterrows():
                if str(f['Tipo Veicolo']).upper() != str(r[c_tipo]).upper(): continue
                
                t_vuoto, _ = (0, "") if f['Pos'] == r[c_prel] else get_maps_data(f['Pos'], r[c_prel])
                t_pieno, dist = get_maps_data(r[c_prel], r[c_dest])

                ora_pronto = f['DT_AVAIL'] + timedelta(minutes=t_vuoto + 10)
                partenza_effettiva = max(r['DT_TARGET'], ora_pronto)
                arrivo_effettivo = partenza_effettiva + timedelta(minutes=t_pieno + 10)
                
                rit = int(max(0, (ora_pronto - r['DT_TARGET']).total_seconds() / 60))

                results.append({
                    'Autista': f[f_aut], 'ID': r[next(c for c in df_c.columns if 'ID' in c.upper())],
                    'Da': r[c_prel], 'A': r[c_dest],
                    'Partenza': partenza_effettiva.strftime('%H:%M'),
                    'Arrivo': arrivo_effettivo.strftime('%H:%M'),
                    'Status': "🟢 OK" if rit <= 5 else f"🔴 RITARDO {rit} min",
                    'Note': "🆕 NUOVO", 'Partenza_DT': r['DT_TARGET'],
                    'Posti_Liberi': f['Capacita'] - 1, 'Tipo': r[c_tipo]
                })
                df_f.at[idx, 'DT_AVAIL'] = arrivo_effettivo
                df_f.at[idx, 'Pos'] = r[c_dest]
                assigned = True; break
            
    return pd.DataFrame(results)

# --- 4. UI ---
st.title("🚐 EmiTrekAI | Smart Dispatch")
u1 = st.file_uploader("📂 Prenotazioni", type=['xlsx'])
u2 = st.file_uploader("📂 Flotta", type=['xlsx'])

if u1 and u2 and st.button("🚀 GENERA PIANO"):
    df_res = run_dispatch(pd.read_excel(u1), pd.read_excel(u2))
    st.dataframe(df_res[['Autista', 'ID', 'Da', 'A', 'Partenza', 'Arrivo', 'Status', 'Note']], use_container_width=True)