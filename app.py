import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import io

# --- 1. CONFIGURAZIONE UI ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | Smart Dispatch", page_icon="🚐")

st.markdown("""
    <style>
    /* CENTRATURA E STILE TASTO ROSSO */
    .stButton { display: flex; justify-content: center; }
    div.stButton > button {
        background-color: #FF4B4B !important;
        color: white !important;
        border-radius: 30px !important;
        font-weight: bold !important;
        width: 350px !important;
        height: 4.5em !important;
        font-size: 20px !important;
        border: none !important;
        box-shadow: 0px 4px 15px rgba(255, 75, 75, 0.4);
    }
    .driver-box { padding: 20px; border-radius: 15px; text-align: center; color: white; margin-bottom: 20px; font-weight: bold; }
    .main-title { text-align: center; color: #1E1E1E; font-weight: 800; margin-bottom: 30px; }
    </style>
""", unsafe_allow_html=True)

# --- 2. MOTORE GOOGLE MAPS ---
def get_maps_data(origin, dest):
    try:
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, dest, mode="driving", departure_time=datetime.now())
        if res:
            leg = res[0]['legs'][0]
            # Recuperiamo i minuti reali dal traffico
            minuti_traffico = int(leg.get('duration_in_traffic', leg['duration'])['value'] / 60)
            return minuti_traffico, leg['distance']['text']
    except: return 45, "N/D"

# --- 3. LOGICA DISPATCH ---
def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip(); df_f.columns = df_f.columns.str.strip()
    c_id = next(c for c in df_c.columns if 'ID' in c.upper())
    c_ora = next(c for c in df_c.columns if 'ORA' in c.upper())
    c_prel = next(c for c in df_c.columns if 'PRELIEVO' in c.upper())
    c_dest = next(c for c in df_c.columns if 'DESTINAZIONE' in c.upper())
    c_tipo = next(c for c in df_c.columns if 'TIPO' in c.upper())
    f_aut = next(c for c in df_f.columns if 'AUTISTA' in c.upper())
    f_disp = next(c for c in df_f.columns if 'DISPONIBILE' in c.upper())

    def parse_t(t):
        try: return datetime.combine(datetime.today(), datetime.strptime(str(t)[:5].replace('.', ':'), '%H:%M').time())
        except: return datetime.now()

    df_c['DT_TARGET'] = df_c[c_ora].apply(parse_t)
    df_f['DT_AVAIL'] = df_f[f_disp].apply(parse_t)
    df_f['Pos'] = "BASE"; df_f['Servizi'] = 0
    df_f['Cap'] = df_f['Tipo Veicolo'].map({'Berlina': 3, 'Suv': 4, 'Minivan': 7}).fillna(3)

    results = []
    COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0']

    for _, r in df_c.sort_values('DT_TARGET').iterrows():
        assigned = False
        # POOLING
        for res in results:
            if (res['Da'] == r[c_prel] and res['A'] == r[c_dest] and 
                res['DT'] == r['DT_TARGET'] and res['Posti'] > 0 and res['Tipo'] == r[c_tipo]):
                results.append({**res, 'ID': r[c_id], 'Note': "💎 POOLING", 'Posti': res['Posti']-1})
                assigned = True; break

        if not assigned:
            for idx, f in df_f.iterrows():
                if str(f['Tipo Veicolo']).upper() != str(r[c_tipo]).upper(): continue
                t_v, _ = (0, "") if f['Pos'] == r[c_prel] else get_maps_data(f['Pos'], r[c_prel])
                t_p, dist = get_maps_data(r[c_prel], r[c_dest])
                
                # CUSCINETTO 10+10
                pronto_al_ritrovo = f['DT_AVAIL'] + timedelta(minutes=t_v + 10)
                partenza_effettiva = max(r['DT_TARGET'], pronto_al_ritrovo)
                arrivo_destinazione = partenza_effettiva + timedelta(minutes=t_p + 10)
                
                rit = int(max(0, (pronto_al_ritrovo - r['DT_TARGET']).total_seconds() / 60))
                
                results.append({
                    'Autista': f[f_aut], 'ID': r[c_id], 'Da': r[c_prel], 'A': r[c_dest],
                    'Inizio': partenza_effettiva.strftime('%H:%M'), 'Fine': arrivo_destinazione.strftime('%H:%M'),
                    'Status': "🟢 OK" if rit <= 5 else f"🔴 RITARDO {rit} min",
                    'Note': "🆕 NUOVO", 'Color': COLORS[idx % len(COLORS)],
                    'DT': r['DT_TARGET'], 'Posti': f['Cap']-1, 'Tipo': r[c_tipo], 'Dist': dist
                })
                df_f.at[idx, 'DT_AVAIL'] = arrivo_destinazione
                df_f.at[idx, 'Pos'] = r[c_dest]; df_f.at[idx, 'Servizi'] += 1
                assigned = True; break
    return pd.DataFrame(results), df_f

# --- 4. INTERFACCIA ---
if 'res_df' not in st.session_state:
    st.markdown('<h1 class="main-title">🚐 EmiTrekAI | Smart Dispatch</h1>', unsafe_allow_html=True)
    c1, c2 = st.columns(2); u1 = c1.file_uploader("Prenotazioni", type=['xlsx']); u2 = c2.file_uploader("Flotta", type=['xlsx'])
    if u1 and u2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚀 GENERA PIANO OPERATIVO"):
            res, fleet = run_dispatch(pd.read_excel(u1), pd.read_excel(u2))
            st.session_state.update({'res_df': res, 'fleet_df': fleet}); st.rerun()
else:
    df, flotta = st.session_state['res_df'], st.session_state['fleet_df']
    st.markdown(f'<h1 class="main-title">📊 Dashboard - {datetime.now().strftime("%d/%m/%Y")}</h1>', unsafe_allow_html=True)
    
    # BOX AUTISTI
    cols = st.columns(len(flotta))
    for i, (_, row) in enumerate(flotta.iterrows()):
        aut = row[0]
        color = df[df['Autista'] == aut]['Color'].iloc[0] if aut in df['Autista'].values else "gray"
        cols[i].markdown(f'<div class="driver-box" style="background-color:{color};">{aut}<br>{row["Servizi"]} Servizi</div>', unsafe_allow_html=True)

    st.divider()
    t1, t2 = st.tabs(["📋 Rendiconto Totale", "🚘 Diario Autisti"])
    with t1:
        v = ['ID', 'Da', 'A', 'Inizio', 'Fine', 'Status', 'Note']
        st.dataframe(df[v + ['Color']].style.apply(lambda x: [f"background-color: {x.Color}; color: white" for _ in x], axis=1), column_order=v, use_container_width=True)
    
    with t2:
        # FIX DIARIO VUOTO: Usiamo il nome esatto della colonna autista
        for a_name in flotta.iloc[:, 0].unique():
            personal_df = df[df['Autista'] == a_name]
            if not personal_df.empty:
                with st.expander(f"Programma Giornaliero: {a_name}"):
                    st.table(personal_df[['ID', 'Da', 'A', 'Inizio', 'Fine', 'Status', 'Note']])
            else:
                with st.expander(f"Programma Giornaliero: {a_name} (Nessun servizio)"):
                    st.write("L'autista non ha corse assegnate per oggi.")

    # TASTI FINALI CENTRATI
    st.markdown("<br>", unsafe_allow_html=True)
    col_dl, col_back = st.columns(2)
    output = io.BytesIO()
    df.to_excel(output, index=False)
    col_dl.download_button("📥 Scarica Excel", output.getvalue(), "EmiTrek_Piano.xlsx")
    if col_back.button("⬅️ NUOVO CARICAMENTO"):
        del st.session_state['res_df']; st.rerun()