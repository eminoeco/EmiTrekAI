import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import io

# --- 1. CONFIGURAZIONE UI ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | Smart Dispatch", page_icon="🚐")

st.markdown("""
    <style>
    div.stButton > button:first-child {
        background-color: #FF4B4B; color: white; border-radius: 25px;
        font-weight: bold; width: 100%; height: 4em; font-size: 20px; border: none;
    }
    .driver-box { padding: 20px; border-radius: 15px; text-align: center; color: white; margin-bottom: 20px; font-weight: bold; }
    .main-title { text-align: center; color: #1E1E1E; margin-bottom: 30px; font-weight: 800; }
    </style>
""", unsafe_allow_html=True)

# --- 2. MOTORE GOOGLE MAPS ---
def get_maps_data(origin, dest):
    try:
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, dest, mode="driving", departure_time=datetime.now())
        if res:
            leg = res[0]['legs'][0]
            return int(leg.get('duration_in_traffic', leg['duration'])['value'] / 60), leg['distance']['text']
    except: return 40, "N/D"

# --- 3. LOGICA DISPATCHER ---
def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip(); df_f.columns = df_f.columns.str.strip()
    c_ora = next((c for c in df_c.columns if 'ORA' in c.upper()), df_c.columns[1])
    c_prel = next((c for c in df_c.columns if 'PRELIEVO' in c.upper()), df_c.columns[2])
    c_dest = next((c for c in df_c.columns if 'DESTINAZIONE' in c.upper()), df_c.columns[3])
    c_tipo = next((c for c in df_c.columns if 'TIPO' in c.upper()), df_c.columns[4])
    f_aut = next((c for c in df_f.columns if 'AUTISTA' in c.upper()), df_f.columns[0])
    f_disp = next((c for c in df_f.columns if 'DISPONIBILE' in c.upper()), df_f.columns[2])

    def parse_t(t):
        try: return datetime.combine(datetime.today(), datetime.strptime(str(t)[:5].replace('.', ':'), '%H:%M').time())
        except: return datetime.now()

    df_c['DT_T'] = df_c[c_ora].apply(parse_t)
    df_f['DT_A'] = df_f[f_disp].apply(parse_t)
    df_f['Pos'] = "BASE"; df_f['Servizi'] = 0
    df_f['Cap'] = df_f['Tipo Veicolo'].map({'Berlina': 3, 'Suv': 4, 'Minivan': 7}).fillna(3)

    results = []
    DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0']

    for _, r in df_c.sort_values('DT_T').iterrows():
        assigned = False
        # SMART POOLING (Andrea prende i primi 3 se stessa tratta/orario)
        for res in results:
            if (res['Da'] == r[c_prel] and res['A'] == r[c_dest] and 
                res['DT'] == r['DT_T'] and res['Posti'] > 0 and res['Tipo'] == r[c_tipo]):
                results.append({**res, 'ID': r[df_c.columns[0]], 'Note': "💎 POOLING", 'Posti': res['Posti']-1})
                assigned = True; break

        if not assigned:
            for idx, f in df_f.iterrows():
                if str(f['Tipo Veicolo']).upper() != str(r[c_tipo]).upper(): continue
                t_v, _ = (0, "") if f['Pos'] == r[c_prel] else get_maps_data(f['Pos'], r[c_prel])
                t_p, dist = get_maps_data(r[c_prel], r[c_dest])
                pronto = f['DT_A'] + timedelta(minutes=t_v + 10)
                start = max(r['DT_T'], pronto)
                end = start + timedelta(minutes=t_p + 10)
                rit = int(max(0, (pronto - r['DT_T']).total_seconds() / 60))
                
                results.append({
                    'Autista': f[f_aut], 'ID': r[df_c.columns[0]], 'Da': r[c_prel], 'A': r[c_dest],
                    'Inizio': start.strftime('%H:%M'), 'Fine': end.strftime('%H:%M'),
                    'Status': "🟢 OK" if rit <= 5 else f"🔴 RITARDO {rit} min",
                    'Note': "🆕 NUOVO", 'Color': DRIVER_COLORS[idx % len(DRIVER_COLORS)],
                    'DT': r['DT_T'], 'Posti': f['Cap']-1, 'Tipo': r[c_tipo], 'Dist': dist
                })
                df_f.at[idx, 'DT_A'] = end; df_f.at[idx, 'Pos'] = r[c_dest]; df_f.at[idx, 'Servizi'] += 1
                assigned = True; break
    return pd.DataFrame(results), df_f

# --- 4. INTERFACCIA ---
if 'res_df' not in st.session_state:
    st.markdown('<h1 class="main-title">🚐 EmiTrekAI | Caricamento</h1>', unsafe_allow_html=True)
    c1, c2 = st.columns(2); u1 = c1.file_uploader("Prenotazioni"); u2 = c2.file_uploader("Flotta")
    if u1 and u2 and st.button("🚀 ELABORA PIANO VIAGGI"):
        res, fleet = run_dispatch(pd.read_excel(u1), pd.read_excel(u2))
        st.session_state.update({'res_df': res, 'fleet_df': fleet}); st.rerun()
else:
    df, flotta = st.session_state['res_df'], st.session_state['fleet_df']
    st.markdown(f'<h1 class="main-title">📊 Dashboard Operativa</h1>', unsafe_allow_html=True)
    
    cols = st.columns(len(flotta))
    for i, (_, row) in enumerate(flotta.iterrows()):
        aut = row[0]
        color = df[df['Autista'] == aut]['Color'].iloc[0] if aut in df['Autista'].values else "gray"
        cols[i].markdown(f'<div class="driver-box" style="background-color:{color};">{aut}<br>{row["Servizi"]} Servizi</div>', unsafe_allow_html=True)

    t1, t2 = st.tabs(["📋 Rendiconto", "🚘 Diario Autisti"])
    with t1:
        v = ['ID', 'Da', 'A', 'Inizio', 'Fine', 'Status', 'Note']
        st.dataframe(df[v + ['Color']].style.apply(lambda x: [f"background-color: {x.Color}; color: white" for _ in x], axis=1), column_order=v, use_container_width=True)
    with t2:
        for a in flotta.iloc[:, 0]:
            with st.expander(f"Programma {a}"): st.table(df[df['Autista'] == a][['ID', 'Da', 'A', 'Inizio', 'Fine', 'Status']])

    c_dl, c_back = st.columns(2)
    output = io.BytesIO()
    df.to_excel(output, index=False) # Fix: rimosso motore xlsxwriter per evitare errori
    c_dl.download_button("📥 Scarica Excel", output.getvalue(), "Piano.xlsx")
    if c_back.button("⬅️ NUOVO CARICAMENTO"):
        del st.session_state['res_df']; st.rerun()