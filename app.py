import streamlit as st
import pandas as pd
from datetime import datetime, time, timedelta
import numpy as np
from io import BytesIO

# FIX PER STREAMLIT CLOUD: disabilita warning e chained assignment
pd.options.mode.chained_assignment = None


# --- CONFIGURAZIONE GENERALE ---
st.set_page_config(layout="wide", page_title="EmiTrekAI: VOM", page_icon="🗓️")

# Inizializza lo stato in modo sicuro
if 'processed_data' not in st.session_state:
    st.session_state['processed_data'] = False
    st.session_state['assegnazioni_complete'] = None
    st.session_state['flotta_risorse'] = None

# --- MAPPATURA COLORI E EMOJI (7 COLORI) ---
DRIVER_COLORS = {
    'Andrea': '#4CAF50',    # Verde
    'Carlo': '#2199F3',     # Blu
    'Giulia': '#FFC107',    # Giallo
    'Marco': '#E91E63',     # Rosa/Fucsia
    'Luca': '#00BCD4',      # Azzurro
    'Sara': '#FF5722',      # Arancione
    'Elena': '#673AB7',     # Viola
    'DEFAULT': '#B0BEC5'    # Grigio
}

VEHICLE_EMOJIS = {
    'Berlina': '🚗',
    'Minivan': '🚐',
    'Suv': '🚙', 
    'Default': '❓' 
}

STATUS_EMOJIS = {
    'ASSEGNATO': '✅',
    'NON ASSEGNATO': '❌'
}

# --- INIEZIONE CSS SEMPLIFICATA ---
st.markdown(
    """
    <style>
    .stApp {
        background-color: #F0F8FF;
    }
    .big-font {
        font-size:20px !important;
        font-weight: bold;
    }
    .card-title-font {
        font-size: 16px !important; 
        font-weight: bold;
        margin-bottom: 5px; 
    }
    .driver-card {
        padding: 8px;
        border-radius: 8px;
        box-shadow: 1px 1px 5px rgba(0,0,0,0.1);
        margin-bottom: 8px;
        line-height: 1.2;
        height: 100%;
    }
    .driver-card p {
        font-size: 12px;
        margin: 0;
    }
    div.stDataFrame {
        font-size: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True
)
# -----------------------------------------------------------------------------

# --- FUNZIONI DI SUPPORTO ---
def read_excel_file(uploaded_file):
    try:
        if uploaded_file.name.endswith('.csv'):
             df = pd.read_csv(uploaded_file)
        else:
             df = pd.read_excel(uploaded_file, engine='openpyxl')
        return df
    except Exception as e:
        st.error(f"Errore nella lettura del file: {e}")
        return None

def time_to_minutes(t):
    if isinstance(t, time): return t.hour * 60 + t.minute
    return 0

def to_time(val):
    if isinstance(val, datetime): return val.time()
    if isinstance(val, time): return val
    if isinstance(val, str): 
        try: return datetime.strptime(val, '%H:%M').time()
        except ValueError: pass
        try: return datetime.strptime(val, '%H.%M').time()
        except ValueError: return time(0, 0)
    return time(0, 0)

def calculate_end_time(row):
    try:
        start_dt = datetime.combine(datetime.today(), row['Ora Effettiva Prelievo'])
        end_dt = start_dt + timedelta(minutes=int(row['Tempo Servizio Totale (Minuti)']))
        return end_dt.time()
    except Exception:
        return time(0, 0)

def start_optimization(df_clienti, df_flotta):
    st.session_state['temp_df_clienti'] = df_clienti
    st.session_state['temp_df_flotta'] = df_flotta
    run_scheduling(st.session_state['temp_df_clienti'], st.session_state['temp_df_flotta'])

# --- LOGICA DI SCHEDULAZIONE (CORE CON BILANCIAMENTO DEL CARICO) ---
def run_scheduling(df_clienti, df_flotta):
    
    assegnazioni_df = df_clienti.copy()
    assegnazioni_df['ID Veicolo Assegnato'] = np.nan
    assegnazioni_df['Autista Assegnato'] = np.nan
    assegnazioni_df['Stato Assegnazione'] = 'NON ASSEGNATO'
    assegnazioni_df['Ora Effettiva Prelievo'] = np.nan
    assegnazioni_df['Ritardo Prelievo (min)'] = 0 
    
    df_risorse = df_flotta.copy()
    df_risorse['Prossima Disponibilità'] = df_risorse['Disponibile Da (hh:mm)'].apply(to_time)
    df_risorse['Disponibile Fino (hh:mm)'] = df_risorse['Disponibile Fino (hh:mm)'].apply(to_time)
    df_risorse['Tipo Veicolo'] = df_risorse['Tipo Veicolo'].astype(str).str.capitalize()
    
    # Inizializza il contatore dei servizi per il load balancing
    df_risorse['Servizi Assegnati'] = 0 
    
    assegnazioni_df['Ora Prelievo Richiesta'] = assegnazioni_df['Ora Arrivo'].apply(to_time)
    assegnazioni_df['Tipo Veicolo Richiesto'] = assegnazioni_df['Tipo Veicolo Richiesto'].astype(str).str.capitalize()
    
    assegnazioni_df = assegnazioni_df.sort_values(by='Ora Prelievo Richiesta').reset_index(drop=True)
    
    for index, cliente in assegnazioni_df.iterrows():
        
        ora_richiesta = cliente['Ora Prelievo Richiesta']
        veicolo_richiesto = cliente['Tipo Veicolo Richiesto']
        
        if 'Tempo Servizio Totale (Minuti)' not in cliente or pd.isna(cliente['Tempo Servizio Totale (Minuti)']): continue
            
        try:
            tempo_servizio_totale = int(cliente['Tempo Servizio Totale (Minuti)'])
        except ValueError:
             continue
        
        candidati_validi = df_risorse[
            (df_risorse['Tipo Veicolo'] == veicolo_richiesto) & 
            (df_risorse['Disponibile Fino (hh:mm)'].apply(time_to_minutes) >= time_to_minutes(ora_richiesta)) 
        ].copy()
        
        if candidati_validi.empty: continue
        
        tempo_richiesto_min = time_to_minutes(ora_richiesta)
        
        # Calcolo del ritardo minimo
        candidati_validi['Ritardo Min'] = (candidati_validi['Prossima Disponibilità'].apply(time_to_minutes) - tempo_richiesto_min).clip(lower=0)
        
        # LOGICA DI BILANCIAMENTO DEL CARICO: Ordina per 1. Ritardo Minimo, 2. Servizi Assegnati Minimi, 3. Prossima Disponibilità
        risorsa_assegnata = candidati_validi.sort_values(
            by=['Ritardo Min', 'Servizi Assegnati', 'Prossima Disponibilità']
        ).iloc[0] 
        
        ritardo_minuti = int(risorsa_assegnata['Ritardo Min']) 
        
        ora_effettiva_prelievo_dt = datetime.combine(datetime.today(), ora_richiesta) + timedelta(minutes=ritardo_minuti)
        ora_effettiva_prelievo = ora_effettiva_prelievo_dt.time()
        
        ora_fine_servizio_dt = ora_effettiva_prelievo_dt + timedelta(minutes=tempo_servizio_totale)
        ora_fine_servizio = ora_fine_servizio_dt.time()

        if ora_fine_servizio > risorsa_assegnata['Disponibile Fino (hh:mm)']: continue
            
        # AGGIORNA l'assegnazione
        assegnazioni_df.loc[index, 'ID Veicolo Assegnato'] = risorsa_assegnata['ID Veicolo']
        assegnazioni_df.loc[index, 'Autista Assegnato'] = risorsa_assegnata['Autista']
        assegnazioni_df.loc[index, 'Stato Assegnazione'] = 'ASSEGNATO'
        assegnazioni_df.loc[index, 'Ora Effettiva Prelievo'] = ora_effettiva_prelievo
        assegnazioni_df.loc[index, 'Ritardo Prelievo (min)'] = ritardo_minuti
        
        # AGGIORNA la risorsa (Prossima Disponibilità e conteggio servizi)
        df_risorse.loc[df_risorse['ID Veicolo'] == risorsa_assegnata['ID Veicolo'], 'Prossima Disponibilità'] = ora_fine_servizio
        df_risorse.loc[df_risorse['ID Veicolo'] == risorsa_assegnata['ID Veicolo'], 'Servizi Assegnati'] += 1

    # SALVA NELLO STATO E IMPOSTA COME PROCESSATO
    st.session_state['assegnazioni_complete'] = assegnazioni_df
    st.session_state['flotta_risorse'] = df_risorse
    st.session_state['processed_data'] = True
    st.rerun()

# --- FUNZIONE RATIONALE AI (ORA PIÙ UMANO) ---
def generate_ai_report_explanation(driver_df, driver_name, df_risorse):
    
    driver_info = df_risorse[df_risorse['Autista'] == driver_name].iloc[0]
    vehicle_type = driver_info['Tipo Veicolo']
    
    if driver_df.empty:
        return f"**Spiegazione Semplice per {driver_name}:**\n\nNon abbiamo trovato servizi adatti per te e il tuo veicolo ({vehicle_type}) in questa sequenza operativa. Questo è successo perché tutte le corse compatibili sono state assegnate ai tuoi colleghi per **bilanciare il lavoro** al meglio."
    
    total_services = driver_df.shape[0]
    total_duration = driver_df['Durata Servizio (min)'].sum()
    max_ritardo = driver_df['Ritardo (min)'].max()
    next_available = driver_info['Prossima Disponibilità'].strftime('%H:%M')
    
    # Inizio Rationale Umanizzato
    report = f"### 💡 Spiegazione delle Scelte (AI Rationale) per {driver_name}\n\n"
    report += f"Ciao {driver_name}, per oggi ti abbiamo organizzato **{total_services} servizi** che ti impegneranno per circa **{total_duration} minuti** totali.\n\n"
    
    # Rationale sui servizi (basato sul veicolo e sul bilanciamento)
    colleagues = df_risorse[(df_risorse['Tipo Veicolo'] == vehicle_type) & (df_risorse['Autista'] != driver_name)]['Autista'].tolist()
    
    report += f"**Perché tu e il tuo veicolo?** Guidi una **{vehicle_type}**. Ti abbiamo scelto per queste corse perché il sistema ha l'obiettivo di **dividere il lavoro in modo equo** tra tutti gli autisti con un mezzo simile ({', '.join(colleagues)}).\n\n"
        
    # Rationale sui ritardi
    if max_ritardo > 0:
        # Trova il cliente con il ritardo massimo per dare un esempio concreto
        client_id_with_max_delay = driver_df[driver_df['Ritardo (min)'] == max_ritardo].iloc[0]['Cliente']
        
        report += f"**Attenzione agli Orari:** Per la corsa con Cliente ID **{client_id_with_max_delay}**, c'è un ritardo massimo di **{max_ritardo} minuti** rispetto all'orario richiesto dal cliente. Ti abbiamo assegnato il servizio comunque perché, pur essendo occupato, eri la scelta migliore per non sovraccaricare troppo i tuoi colleghi. Segui l'Ora Partenza indicata nella tabella!\n\n"
    else:
        report += f"**Attenzione agli Orari:** Perfetto! Tutti i tuoi servizi sono stati programmati **senza ritardi** rispetto all'orario richiesto dai clienti. Partirai subito dopo aver finito la corsa precedente.\n\n"
        
    # Conclusione (RIMOSSO RIFERIMENTO A 19:00)
    report += f"**Quando hai finito?** L'ultima corsa assegnata terminerà circa alle **{next_available}**. Dopo quell'orario, sarai pronto per qualsiasi nuova richiesta arrivi."
    
    return report

# --- LAYOUT PRINCIPALE ---

if not st.session_state['processed_data']:
    # === MOSTRA INTERFACCIA DI CARICAMENTO ===
    st.title("EmiTrekAI: Virtual Operations Manager")
    st.markdown("### Carica i file per ottimizzare la flotta.")
    st.markdown("---")

    col1, col2 = st.columns(2)
    uploaded_clients = None
    uploaded_flotta = None
    
    read_df_clienti = None
    read_df_flotta = None

    with col1:
        st.header("1. Clienti in Arrivo (Richieste)")
        uploaded_clients = st.file_uploader("Carica il file Prenotazioni Clienti (lista clienti)", type=['xlsx', 'csv'], key='clients_uploader')
        if uploaded_clients:
            read_df_clienti = read_excel_file(uploaded_clients)
            
    with col2:
        st.header("2. La mia flotta NCC (Risorse)")
        uploaded_flotta = st.file_uploader("Carica il file Flotta Personale (flotta ncc)", type=['xlsx', 'csv'], key='flotta_uploader')
        if uploaded_flotta:
            read_df_flotta = read_excel_file(uploaded_flotta)

    if read_df_clienti is not None and read_df_flotta is not None:
        st.success("File caricati con successo! Clicca il pulsante per avviare l'ottimizzazione.")
        st.button("Avvia Ottimizzazione e Visualizza Dashboard", key="run_btn", 
                  on_click=lambda: start_optimization(read_df_clienti, read_df_flotta))

else:
    # === MOSTRA DASHBOARD INTERATTIVA (DOPO IL CARICAMENTO) ===
    assegnazioni_df = st.session_state['assegnazioni_complete']
    df_risorse = st.session_state['flotta_risorse']

    if assegnazioni_df is None or assegnazioni_df.empty:
        st.error("Errore: I dati non sono stati caricati o il file è vuoto. Torna indietro e ricarica i file.")
        st.button("↩️ Torna al Caricamento File", on_click=lambda: st.session_state.update(processed_data=False))
        st.stop()
        
    st.markdown("## ✨ La Tua Flotta Sotto Controllo ✨", unsafe_allow_html=True)
    st.markdown("### Riepilogo Intuitivo: **Clienti & Operatori**")
    st.markdown("---")

    # --- NUOVA SEZIONE: RIEPILOGO A COLPO D'OCCHIO ---
    total_clients = assegnazioni_df.shape[0]
    assigned_clients = assegnazioni_df[assegnazioni_df['Stato Assegnazione'] == 'ASSEGNATO'].shape[0]
    unassigned_clients = total_clients - assigned_clients
    total_drivers = df_risorse['Autista'].nunique()
    
    st.subheader("👀 Panoramica Rapida")
    col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
    
    with col_kpi1:
        st.markdown(f"<p class='big-font'>Clienti Totali: {total_clients}</p>", unsafe_allow_html=True)
    with col_kpi2:
        st.markdown(f"<p class='big-font'>Clienti Assegnati: <span style='color:green'>{assigned_clients} ✅</span></p>", unsafe_allow_html=True)
    with col_kpi3:
        st.markdown(f"<p class='big-font'>Clienti Non Assegnati: <span style='color:red'>{unassigned_clients} ❌</span></p>", unsafe_allow_html=True)
    with col_kpi4:
        st.markdown(f"<p class='big-font'>Autisti in Flotta: {total_drivers} 🧑‍✈️</p>", unsafe_allow_html=True)
    
    st.markdown("---")

    # --- Sezione Operatori/Autisti con Schede Colorate e Emoji ---
    st.subheader("🧑‍✈️ I Nostri Operatori NCC")
    
    drivers_unique = df_risorse['Autista'].unique()
    drivers_overview_cols = st.columns(len(drivers_unique)) 
    
    for i, driver in enumerate(drivers_unique):
        with drivers_overview_cols[i]:
            driver_color = DRIVER_COLORS.get(driver, DRIVER_COLORS['DEFAULT'])
            driver_info = df_risorse[df_risorse['Autista'] == driver].iloc[0]
            vehicle_emoji = VEHICLE_EMOJIS.get(driver_info['Tipo Veicolo'], VEHICLE_EMOJIS['Default'])
            
            num_servizi = assegnazioni_df[assegnazioni_df['Autista Assegnato'] == driver].shape[0]

            st.markdown(f"""
            <div class="driver-card" style="background-color: {driver_color}; color: white;">
                <p class='card-title-font'>{driver} {vehicle_emoji}</p>
                <p>Veicolo: {driver_info['Tipo Veicolo']}</p>
                <p>Fine Servizio Ore: {driver_info['Prossima Disponibilità'].strftime('%H:%M')}</p>
                <p>Servizi Assegnati: {num_servizi}</p>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")

    # --- PREPARAZIONE DATAFRAME DI VISUALIZZAZIONE ---
    assigned_df = assegnazioni_df[assegnazioni_df['Stato Assegnazione'] == 'ASSEGNATO'].copy()

    if assigned_df.empty:
        display_df = pd.DataFrame(columns=[
            'Autista', 'Cliente', 'Partenza', 'Ora Partenza', 
            'Arrivo', 'Ora Arrivo', 'Ritardo (min)', 'Veicolo', 'Durata Servizio (min)'
        ])
    else:
        assigned_df.reset_index(drop=True, inplace=True)
        assigned_df['Ora Fine Servizio'] = assigned_df.apply(calculate_end_time, axis=1)
        
        partenza_col = assigned_df.get('Indirizzo Prelievo', pd.Series('FCO', index=assigned_df.index)).fillna('FCO')
        
        display_df = pd.DataFrame({
            'Autista': assigned_df['Autista Assegnato'].fillna('-'),
            'Cliente': assigned_df.get('ID Prenotazione', pd.Series('-', index=assigned_df.index)),
            'Partenza': partenza_col,
            'Ora Partenza': assigned_df['Ora Effettiva Prelievo'].apply(
                lambda x: x.strftime('%H:%M') if pd.notna(x) and hasattr(x, 'strftime') else '-'
            ),
            'Arrivo': assigned_df.get('Destinazione Finale', pd.Series('-', index=assigned_df.index)).fillna('-'),
            'Ora Arrivo': assigned_df['Ora Fine Servizio'].apply(
                lambda x: x.strftime('%H:%M') if pd.notna(x) and hasattr(x, 'strftime') else '-'
            ),
            'Ritardo (min)': assigned_df['Ritardo Prelievo (min)'].fillna(0).astype(int),
            'Veicolo': assigned_df['Tipo Veicolo Richiesto'].astype(str).apply(
                lambda x: VEHICLE_EMOJIS.get(x.strip().title(), '❓') + ' ' + x.strip().title()
            ),
            'Durata Servizio (min)': assigned_df['Tempo Servizio Totale (Minuti)'].fillna(0).astype(int),
        })

    # --- SEZIONE DI VISUALIZZAZIONE DELLA TABELLA ---
    st.markdown("## 🗓️ Sequenza Operativa Unificata: Dettaglio Servizi Assegnati")

    if display_df.empty:
        st.info("Nessun servizio assegnato con successo.")
    else:
        def color_autista(row):
            colore = DRIVER_COLORS.get(row['Autista'], DRIVER_COLORS['DEFAULT'])
            return [f'background-color: {colore}; color: white' if col == 'Autista' else '' for col in display_df.columns]

        styled_df = display_df.style.apply(color_autista, axis=1)

        st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
        # Download
        csv = display_df.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="Scarica Sequenza Operativa (CSV)",
            data=csv,
            file_name=f"Sequenza_FCO_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )
    
    st.markdown("---")

    # =============================================================================
    # REPORT INDIVIDUALE AUTISTA (CON RATIONALE AI UMANIZZATO)
    # =============================================================================
    st.subheader("Report Individuale Autista")

    if not display_df.empty:
        autisti_con_corse = sorted(display_df['Autista'].dropna().unique())
        
        if autisti_con_corse:
            selected_driver = st.selectbox(
                "Scegli l'autista per il report personale",
                options=autisti_con_corse
            )

            driver_df = display_df[display_df['Autista'] == selected_driver].copy()
            driver_df.index = driver_df.index + 1
            driver_color = DRIVER_COLORS.get(selected_driver, DRIVER_COLORS['DEFAULT'])

            st.markdown(f"""
            <div style="padding:20px; background:{driver_color}; color:white; border-radius:12px; text-align:center; font-size:26px; font-weight:bold; margin:30px 0;">
                Report Giornaliero — {selected_driver}
            </div>
            """, unsafe_allow_html=True)

            st.dataframe(driver_df, use_container_width=True, hide_index=False)
            
            # AGGIUNGI IL REPORT AI ESPLICATIVO (UMANIZZATO)
            report_explanation = generate_ai_report_explanation(driver_df, selected_driver, df_risorse)
            st.info(report_explanation) # Usa st.info per un effetto 'pop-up' style box

            oggi = datetime.now().strftime("%d-%m-%Y")
            
            try:
                # Per reportlab (PDF)
                from reportlab.lib.pagesizes import A4
                from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
                from reportlab.lib.styles import getSampleStyleSheet
                from reportlab.lib import colors as rl_colors

                buffer = BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=A4)
                elements = []
                styles = getSampleStyleSheet()

                elements.append(Paragraph(f"<b>Report Autista: {selected_driver}</b>", styles['Title']))
                elements.append(Paragraph(f"Data: {oggi}<br/><br/>", styles['Normal']))

                data = [["N.", "Cliente", "Ora Part.", "Destinazione", "Veicolo", "Ritardo", "Durata"]]
                for i, row in driver_df.iterrows():
                    data.append([i, row['Cliente'], row['Ora Partenza'], row['Arrivo'],
                                 row['Veicolo'], f"{row['Ritardo (min)']} min", f"{row['Durata Servizio (min)']} min"])

                table = Table(data)
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), rl_colors.HexColor(driver_color)),
                    ('TEXTCOLOR', (0,0), (-1,0), rl_colors.white),
                    ('GRID', (0,0), (-1,-1), 1, rl_colors.black),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                    ('BACKGROUND', (0,1), (-1,-1), rl_colors.beige),
                ]))
                elements.append(table)
                doc.build(elements)

                st.download_button(
                    label="Scarica Report PDF",
                    data=buffer.getvalue(),
                    file_name=f"Report_{selected_driver}_{oggi}.pdf",
                    mime="application/pdf"
                )
            except ImportError:
                pass 

            # Excel
            excel_buffer = BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                driver_df.to_excel(writer, index=True, sheet_name=selected_driver[:30])
            st.download_button(
                label="Scarica Report Excel",
                data=excel_buffer.getvalue(),
                file_name=f"Report_{selected_driver}_{oggi}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        else:
            st.info("Nessun autista con corse oggi.")
    else:
        st.info("Carica i file e avvia l'ottimizzazione per vedere i report.")

    # Pulsante per resettare e tornare al caricamento file
    st.markdown("---")
    st.button("↩️ Torna al Caricamento File", on_click=lambda: st.session_state.update(processed_data=False))