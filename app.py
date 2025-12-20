import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import vertexai
from vertexai.generative_models import GenerativeModel
import io

# --- 1. CONFIGURAZIONE UI ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | Gemini Dispatch", page_icon="🚐")

st.markdown("""
    <style>
    .stButton, .stDownloadButton { display: flex; justify-content: center; width: 100%; }
    div.stButton > button, div.stDownloadButton > button {
        background-color: #FF4B4B !important; color: white !important;
        border-radius: 30px !important; font-weight: bold !important;
        width: 380px !important; height: 4.5em !important; font-size: 18px !important;
        margin: 20px auto !important; display: block !important;
    }
    .driver-box { padding: 20px; border-radius: 15px; text-align: center; color: white; margin-bottom: 20px; font-weight: bold; }
    .main-title { text-align: center; color: #1E1E1E; font-weight: 800; margin-bottom: 30px; }
    </style>
""", unsafe_allow_html=True)

# --- 2. INIZIALIZZAZIONE AI ---
vertexai.init(project=st.secrets["gcp_service_account"]["project_id"], location="europe-west4")
model = GenerativeModel("gemini-1.5-flash")

def get_maps_data(origin, dest):
    try:
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        # Chiediamo a Gemini di correggere l'indirizzo prima di mandarlo a Maps
        prompt = f"Correggi questo indirizzo per Google Maps a Roma: '{origin}'. Rispondi SOLO con l'indirizzo completo."
        clean_origin = model.generate_content(prompt).text.strip()
        
        res = gmaps.directions(clean_origin, dest + ", Roma", mode="driving", departure_time=datetime.now())
        if res:
            leg = res[0]['legs'][0]
            return int(leg.get('duration_in_traffic', leg['duration'])['value'] / 60), leg['distance']['text']
    except: return 45, "N/D"

# --- 3. LOGICA DISPATCH ---
def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip(); df_f.columns = df_f.columns.str.strip()
    
    # Rilevamento Colonne
    c_id = next(c for c in df_c.columns if 'ID' in c.upper())
    c_ora = next(c for c in df_c.columns if 'ORA' in c.upper())
    c_prel = next(c for c in df_c.columns if 'PRELIEVO' in c.upper())
    c_dest = next(c for c in df_c.columns if 'DESTINAZIONE' in c.upper())
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
        # SMART POOLING
        for res in results:
            if (res['Da'] == r[c_prel] and res['A'] == r[c_dest] and res['DT'] == r['DT_TARGET'] and res['Posti'] > 0):
                results.append({**res, 'ID': r[c_id], 'Note': "💎 POOLING", 'Posti': res['Posti']-1})
                assigned = True; break

        if not assigned:
            for idx, f in df_f.iterrows():
                if str(f['Tipo Veicolo']).upper() != str(r['Tipo Veicolo Richiesto']).upper(): continue
                
                t_v, _ = (0, "") if f['Pos'] == r[c_prel] else get_maps_data(f['Pos'], r[c_prel])
                t_p, dist = get_maps_data(r[c_prel], r[c_dest])
                
                pronto = f['DT_AVAIL'] + timedelta(minutes=t_v + 10)
                start = max(r['DT_TARGET'], pronto)
                end = start + timedelta(minutes=t_p + 10)
                rit = int(max(0, (pronto - r['DT_TARGET']).total_seconds() / 60))
                
                results.append({
                    'Autista': f[f_aut], 'ID': r[c_id], 'Da': r[c_prel], 'A': r[c_dest],
                    'Inizio': start.strftime('%H:%M'), 'Fine': end.strftime('%H:%M'),
                    'Status': "🟢 OK" if rit <= 5 else f"🔴 RITARDO {rit} min",
                    'Note': "🆕 NUOVO", 'Color': COLORS[idx % len(COLORS)],
                    'DT': r['DT_TARGET'], 'Posti': f['Cap']-1, 'Dist': dist
                })
                df_f.at[idx, 'DT_AVAIL'] = end; df_f.at[idx, 'Pos'] = r[c_dest]; df_f.at[idx, 'Servizi'] += 1
                assigned = True; break
    return pd.DataFrame(results), df_f

# --- 4. INTERFACCIA ---
if 'res_df' not in st.session_state:
    st.markdown('<h1 class="main-title">🚐 EmiTrekAI | AI Dispatcher</h1>', unsafe_allow_html=True)
    c1, c2 = st.columns(2); u1 = c1.file_uploader("📂 Prenotazioni"); u2 = c2.file_uploader("📂 Flotta")
    if u1 and u2 and st.button("🚀 ELABORA PIANO CON GEMINI"):
        res, fleet = run_dispatch(pd.read_excel(u1), pd.read_excel(u2))
        st.session_state.update({'res_df': res, 'fleet_df': fleet}); st.rerun()
else:
    df, flotta = st.session_state['res_df'], st.session_state['fleet_df']
    st.markdown(f'<h1 class="main-title">📊 Dashboard AI - {datetime.now().strftime("%d/%m/%Y")}</h1>', unsafe_allow_html=True)
    
    cols = st.columns(len(flotta))
    for i, (_, row) in enumerate(flotta.iterrows()):
        aut = row[0]
        color = df[df['Autista'] == aut]['Color'].iloc[0] if aut in df['Autista'].values else "gray"
        cols[i].markdown(f'<div class="driver-box" style="background-color:{color};">{aut}<br><span style="font-size:24px;">{row["Servizi"]}</span> Servizi</div>', unsafe_allow_html=True)

    st.divider()
    v_show = ['Autista', 'ID', 'Da', 'A', 'Inizio', 'Fine', 'Status', 'Note']
    st.dataframe(df[v_show + ['Color']].style.apply(lambda x: [f"background-color: {x.Color}; color: white" for _ in x], axis=1), column_order=v_show, use_container_width=True)

    # DOWNLOAD E RESET
    st.download_button("📥 SCARICA EXCEL", df.to_csv(index=False).encode('utf-8'), "Piano_AI.csv")
    if st.button("⬅️ NUOVO CARICAMENTO"):
        del st.session_state['res_df']; st.rerun()