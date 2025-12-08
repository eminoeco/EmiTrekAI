import streamlit as st
import pandas as pd
import os
from dotenv import load_dotenv

load_dotenv()  # se usi ancora il file .env per la chiave OpenAI

st.set_page_config(page_title="EmiTrekAI", page_icon="rocket", layout="centered")

st.title("EmiTrekAI")
st.markdown("### Il tuo Virtual Operations Manager per NCC e Bus")

# ==== UPLOADER NUOVO (QUESTO SOSTITUISCE IL VECCHIO CARICAMENTO FISSO) ====
uploaded_file = st.file_uploader(
    "Carica il tuo file di prenotazioni (Excel o CSV – anche super caotico)",
    type=["xlsx", "xls", "csv"]
)

if uploaded_file is not None:
    try:
        if uploaded_file.name.lower().endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
        
        st.success("File caricato correttamente!")
        st.write("Prime 10 righe del file:")
        st.dataframe(df.head(10))

        # ←←←← DA QUI IN POI LASCIA TUTTO IL TUO CODICE ESISTENTE ←←←←
        # (non toccare niente sotto questa riga – tutto quello che c’era prima continua a funzionare)
        
    except Exception as e:
        st.error(f"Errore nella lettura del file: {e}")
        st.stop()
else:
    st.info("Carica il primo file Excel/CSV e vedrai subito la magia")
    st.stop()
    