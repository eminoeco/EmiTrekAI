import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps

# --- 1. CONFIGURAZIONE ESTETICA ---
st.set_page_config(layout="wide", page_title="EmiTrekAI | Smart Dispatch", page_icon="🚐")

st.markdown("""
    <style>
    .stButton > button { background-color: #FF4B4B; color: white; border-radius: 20px; font-weight: bold; width: 100%; height: 3.5em; }
    .driver-box { padding: 15px; border-radius: 12px; text-align: center; color: white; margin-bottom: 10px; font-weight: bold; }
    .main-title { color: #1E1E1E; font-size: 40px; font-weight: 800; text-align: center; margin-bottom: 20px;}
    </style>
""", unsafe_allow_html=True)

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

# --- 3. LOGICA DISPATCH + POOLING REALE ---
def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip(); df_f.columns = df_f.columns.str.strip()
    
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

    df_c['DT_T'] = df_c[c_ora].apply(parse_t)
    df_f['DT_A'] = df_f[f_disp].apply(parse_t)
    df_f['Pos'] = "BASE"; df_f['Servizi'] = 0; df_f['Occupazione'] = 0
    
    results = []
    DRIVER_COLORS = ['#4CAF50', '#2196F3', '#FFC107', '#E91E63', '#9C27B0']

    # Ordiniamo per orario per ottimizzare il pooling
    for i, (_, r) in enumerate(df_c.sort_values('DT_T').iterrows()):
        assigned = False
        
        # PROVA POOLING (Cerca un autista che sta già andando nella stessa destinazione)
        for idx, f in df_f.iterrows():
            if str(f['Tipo Veicolo']).upper() != str(r[c_tipo]).upper(): continue
            
            # Se l'autista ha appena finito o sta andando nella stessa destinazione entro 15 min
            if f['Pos'] == r[c_dest] and abs((f['DT_A'] - r['DT_T']).total_seconds()/60) < 20:
                is_ritardo = int(max(0, (f['DT_A'] - r['DT_T']).total_seconds() / 60))
                results.append({
                    'Autista': f[f_aut], 'Color': DRIVER_COLORS[idx % len(DRIVER_COLORS)],
                    'ID': r[c_id], 'Da': r[c_prel], 'A': r[c_dest],
                    'Inizio': r['DT_T'].strftime('%H:%M'), 'Fine': f['DT_A'].strftime('%H:%M'),
                    'Status': "🟢 OK" if is_ritardo <= 5 else f"🔴 RITARDO {is_ritardo} min",
                    'Note': "💎 POOLING (Insieme)"
                })
                assigned = True; break

        # ASSEGNAZIONE NORMALE se il pooling non è possibile
        if not assigned:
            for idx, f in df_f.iterrows():
                if str(f['Tipo Veicolo']).upper() != str(r[c_tipo]).upper(): continue
                
                t_vuoto, _ = get_maps_data(f['Pos'], r[c_prel])
                t_pieno, _ = get_maps_data(r[c_prel], r[c_dest])

                ora_pronto = f['DT_A'] + timedelta(minutes=t_vuoto + 10)
                inizio = max(r['DT_T'], ora_pronto)
                fine = inizio + timedelta(minutes=t_pieno + 10)
                
                rit = int(max(0, (ora_pronto - r['DT_T']).total_seconds() / 60))

                results.append({
                    'Autista': f[f_aut], 'Color': DRIVER_COLORS[idx % len(DRIVER_COLORS)],
                    'ID': r[c_id], 'Da': r[c_prel], 'A': r[c_dest],
                    'Inizio': inizio.strftime('%H:%M'), 'Fine': fine.strftime('%H:%M'),
                    'Status': "🟢 OK" if rit <= 5 else f"🔴 RITARDO {rit} min",
                    'Note': ""
                })
                df_f.at[idx, 'DT_A'] = fine
                df_f.at[idx, 'Pos'] = r[c_dest]; df_f.at[idx, 'Servizi'] += 1
                assigned = True; break
            
    return pd.DataFrame(results), df_f

# --- 4. UI ---
st.markdown('<h1 class="main-title">🚐 EmiTrekAI | Smart Dispatch</h1>', unsafe_allow_html=True)

if 'res' not in st.session_state:
    c1, c2 = st.columns(2)
    u1, u2 = c1.file_uploader("Prenotazioni"), c2.file_uploader("Flotta")
    if u1 and u2 and st.button("🚀 ELABORA PIANO"):
        res, fleet = run_dispatch(pd.read_excel(u1), pd.read_excel(u2))
        st.session_state['res'], st.session_state['fleet'] = res, fleet
        st.rerun()
else:
    df, flotta = st.session_state['res'], st.session_state['fleet']
    col_f_aut = next((c for c in flotta.columns if 'AUTISTA' in c.upper()), flotta.columns[0])
    
    st.write("### 🚘 Stato Autisti")
    cols = st.columns(len(flotta))
    for i, (_, row) in enumerate(flotta.iterrows()):
        aut_name = row[col_f_aut]
        color = df[df['Autista'] == aut_name]['Color'].iloc[0] if aut_name in df['Autista'].values else "gray"
        cols[i].markdown(f'<div class="driver-box" style="background-color:{color};">{aut_name}<br>Servizi: {row["Servizi"]}</div>', unsafe_allow_html=True)

    st.divider()
    view_cols = ['Autista', 'ID', 'Da', 'Inizio', 'A', 'Fine', 'Status', 'Note']
    st.dataframe(df[view_cols + ['Color']].style.apply(lambda x: [f"background-color: {x.Color}; color: white" for _ in x], axis=1), column_order=view_cols, use_container_width=True)
    
    if st.button("🔄 RESET"):
        del st.session_state['res']; st.rerun()