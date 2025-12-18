import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import googlemaps
import vertexai
from vertexai.generative_models import GenerativeModel
import tempfile, json, os

# =========================
# AUTH VERTEX AI (UNA VOLTA)
# =========================
if "VERTEX_READY" not in st.session_state:
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        json.dump(dict(st.secrets["gcp_service_account"]), f)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = f.name

    vertexai.init(
        project=st.secrets["gcp_service_account"]["project_id"],
        location="europe-west4"
    )

    st.session_state["vertex_model"] = GenerativeModel("gemini-1.5-flash")
    st.session_state["VERTEX_READY"] = True

model = st.session_state["vertex_model"]

# =========================
# CONFIG UI
# =========================
st.set_page_config(layout="wide", page_title="EmiTrekAI | SaaS Smart Dispatch", page_icon="🚐")
pd.options.mode.chained_assignment = None

# =========================
# ACCESSO
# =========================
def check_password():
    if "password_correct" not in st.session_state:
        st.markdown("## 🔒 Accesso Area Riservata")
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("ENTRA"):
            if u in st.secrets["users"] and p == st.secrets["users"][u]["password"]:
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("Credenziali errate")
        return False
    return True

# =========================
# METRICHE REALI
# =========================
def get_metrics_real(origin, dest):
    try:
        gmaps = googlemaps.Client(key=st.secrets["MAPS_API_KEY"])
        res = gmaps.directions(origin, dest, mode="driving", departure_time=datetime.now())
        leg = res[0]["legs"][0]
        g_min = int(leg.get("duration_in_traffic", leg["duration"])["value"] / 60)
        dist = leg["distance"]["text"]

        prompt = (
            f"Sei un dispatcher NCC a Roma. "
            f"Tratta {origin} -> {dest}. "
            f"Maps stima {g_min} minuti. "
            f"Considera ZTL, traffico reale e varchi. "
            f"Rispondi SOLO con il numero intero dei minuti."
        )

        ai = model.generate_content(prompt)
        final_t = int("".join(filter(str.isdigit, ai.text)))

        return final_t, dist, True

    except Exception as e:
        st.sidebar.error(f"Errore API: {e}")
        return None, "N/D", False

# =========================
# DISPATCH
# =========================
CAPACITA = {"Berlina": 3, "Suv": 3, "Minivan": 7}

def run_dispatch(df_c, df_f):
    df_c.columns = df_c.columns.str.strip()
    df_f.columns = df_f.columns.str.strip()

    def pt(t):
        return datetime.combine(datetime.today(), t) if not isinstance(t, str) else datetime.strptime(t.replace(".", ":"), "%H:%M")

    df_c["DT"] = df_c["Ora Arrivo"].apply(pt)
    df_f["DT"] = df_f["Disponibile Da (hh:mm)"].apply(pt)
    df_f["Pos"] = "BASE"

    res = []

    for _, r in df_c.iterrows():
        for i, f in df_f.iterrows():
            dv, _, _ = get_metrics_real(f["Pos"], r["Indirizzo Prelievo"])
            dp, dist, _ = get_metrics_real(r["Indirizzo Prelievo"], r["Destinazione Finale"])

            part = max(r["DT"], f["DT"] + timedelta(minutes=dv + 10))
            arr = part + timedelta(minutes=dp + 10)

            res.append({
                "Autista": f["Autista"],
                "ID": r["ID"],
                "Da": r["Indirizzo Prelievo"],
                "A": r["Destinazione Finale"],
                "Partenza": part,
                "Arrivo": arr,
                "Dist": dist
            })

            df_f.at[i, "DT"] = arr
            df_f.at[i, "Pos"] = r["Destinazione Finale"]
            break

    return pd.DataFrame(res)

# =========================
# UI
# =========================
if check_password():
    st.title("🚐 EmiTrekAI | Smart Dispatch")

    f1 = st.file_uploader("Prenotazioni")
    f2 = st.file_uploader("Flotta")

    if f1 and f2 and st.button("AVVIA"):
        df = run_dispatch(pd.read_excel(f1), pd.read_excel(f2))
        st.dataframe(df, use_container_width=True)
