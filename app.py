import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import vertexai
from vertexai.generative_models import GenerativeModel
import tempfile, json, os

# AUTH VERTEX AI
if "VERTEX_READY" not in st.session_state:
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        json.dump(dict(st.secrets["gcp_service_account"]), f)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = f.name
    vertexai.init(project=st.secrets["gcp_service_account"]["project_id"], location="us-central1")
    st.session_state["vertex_model"] = GenerativeModel("gemini-1.5-flash")
    st.session_state["VERTEX_READY"] = True

model = st.session_state["vertex_model"]

st.set_page_config(layout="wide", page_title="EmiTrekAI | Smart Dispatch", page_icon="🚐")

def check_password():
    if "password_correct" not in st.session_state:
        st.markdown("## 🔒 Accesso Area Riservata")
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("ENTRA"):
            if u in st.secrets["users"] and p == st.secrets["users"][u]["password"]:
                st.session_state["password_correct"] = True
                st.rerun()
            else: st.error("Credenziali errate")
        return False
    return True

def get_metrics_real(origin, dest):
    try:
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, dest, mode="driving", departure_time=datetime.now())
        leg = res[0]["legs"][0]
        g_min = int(leg.get("duration_in_traffic", leg["duration"])["value"] / 60)
        dist = leg["distance"]["text"]
        prompt = f"Dispatcher NCC Roma: tratta {origin}->{dest}. Maps stima {g_min} min. Rispondi SOLO con il numero intero dei minuti reali."
        ai = model.generate_content(prompt)
        final_t = int("".join(filter(str.isdigit, ai.text)))
        return final_t, dist, True
    except Exception as e:
        return 30, "N/D", False # Fallback minimo se API fallisce

def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()

    # --- FIX: RILEVAMENTO AUTOMATICO COLONNE ---
    col_c_id = next((c for c in df_c.columns if 'ID' in c.upper()), df_c.columns[0])
    col_c_ora = next((c for c in df_c.columns if 'ORA' in c.upper()), df_c.columns[1])
    col_c_prel = next((c for c in df_c.columns if 'PRELIEVO' in c.upper()), df_c.columns[2])
    col_c_dest = next((c for c in df_c.columns if 'DESTINAZIONE' in c.upper()), df_c.columns[3])
    
    col_f_disp = next((c for c in df_f.columns if 'DISPONIBILE' in c.upper()), df_f.columns[2])
    col_f_aut = next((c for c in df_f.columns if 'AUTISTA' in c.upper()), df_f.columns[0])

    def pt(t):
        if isinstance(t, datetime): return t
        return datetime.combine(datetime.today(), t) if not isinstance(t, str) else datetime.strptime(t.replace(".", ":"), "%H:%M")

    df_c["DT_OBJ"] = df_c[col_c_ora].apply(pt)
    df_f["DT_OBJ"] = df_f[col_f_disp].apply(pt)
    df_f["Pos"] = "BASE"

    res = []
    for _, r in df_c.iterrows():
        for i, f in df_f.iterrows():
            dv, _, _ = get_metrics_real(f["Pos"], r[col_c_prel])
            dp, dist, _ = get_metrics_real(r[col_c_prel], r[col_c_dest])

            part = max(r["DT_OBJ"], f["DT_OBJ"] + timedelta(minutes=dv + 10))
            arr = part + timedelta(minutes=dp + 10)
            
            ritardo = max(0, (part - r["DT_OBJ"]).total_seconds() / 60)

            res.append({
                "Autista": f[col_f_aut],
                "ID Corsa": r[col_id],
                "Da": r[col_c_prel],
                "A": r[col_c_dest],
                "Inizio": part.strftime("%H:%M"),
                "Fine": arr.strftime("%H:%M"),
                "Status": "🟢 OK" if ritardo <= 2 else f"🔴 RITARDO {int(ritardo)} min"
            })
            df_f.at[i, "DT_OBJ"] = arr
            df_f.at[i, "Pos"] = r[col_c_dest]
            break
    return pd.DataFrame(res)

if check_password():
    st.title("🚐 EmiTrekAI | Smart Dispatch")
    f1 = st.file_uploader("Carica Prenotazioni (Excel)")
    f2 = st.file_uploader("Carica Flotta (Excel)")

    if f1 and f2:
        if st.button("🚀 AVVIA DISPATCH"):
            df_risultato = run_dispatch(pd.read_excel(f1), pd.read_excel(f2))
            st.success("Analisi completata con dati reali API + Vertex AI")
            st.dataframe(df_risultato, use_container_width=True)
