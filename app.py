import streamlit as st
import datetime

# Configurazione pagina
st.set_page_config(
    page_title="Gelateria Cavour - Hub Gestionale",
    page_icon="🍦",
    layout="wide"
)

# Titolo Principale
st.title("🍦 Gelateria Cavour — Hub Gestionale AI")
st.caption("Pannello di Controllo & Monitoraggio Comande")

# Sidebar - Stato della Cassa e Menu
st.sidebar.header("⚙️ Stato Sistema")
st.sidebar.success("Cassa Lasersoft: Connessa (192.168.0.30:21930)")
st.sidebar.info("Stampante Comande: Orderman ESC/POS")

st.sidebar.divider()
st.sidebar.subheader("Menu Navigazione")
scelta = st.sidebar.radio("Vai a:", ["📊 Dashboard Comande", "📋 Menu & Listino", "🤖 Stato AI Tavoli"])

# Sezione 1: Dashboard Comande
if scelta == "📊 Dashboard Comande":
    st.header("📋 Comande in Corso")
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Ordini Oggi", "24", "+5 nell'ultima ora")
    col2.metric("Incasso Stimato", "€ 142,50", "+12%")
    col3.metric("Tavoli Attivi", "3", "Tavolo 2, 4, 7")

    st.divider()

    st.subheader("Ultimi Ordini Ricevuti")
    
    # Esempio Ordini
    ordini = [
        {"ora": "23:45", "tavolo": "Tavolo 4", "dettagli": "2x Coppa Cavour, 1x Caffe Espresso", "stato": "Inviato a Orderman", "totale": "€ 15,00"},
        {"ora": "23:50", "tavolo": "Tavolo 2", "dettagli": "1x Brioche col Tappo (Pistacchio), 1x Cappuccino", "stato": "In Corso", "totale": "€ 6,50"},
        {"ora": "00:01", "tavolo": "Tavolo 7", "dettagli": "1x Vaschetta Gelato 500g (Nocciola, Cioccolato)", "stato": "In Attesa", "totale": "€ 12,00"},
    ]

    for ord in ordini:
        with st.expander(f"🕒 {ord['ora']} — {ord['tavolo']} ({ord['totale']}) — {ord['stato']}"):
            st.write(f"**Prodotti:** {ord['dettagli']}")
            c1, c2 = st.columns(2)
            c1.button("Rinvia a Orderman", key=f"reprint_{ord['tavolo']}")
            c2.button("Segna come Servito", key=f"done_{ord['tavolo']}")

# Sezione 2: Menu e Listino
elif scelta == "📋 Menu & Listino":
    st.header("🍦 Gestione Menu Digitale")
    st.info("I prodotti sincronizzati qui saranno visibili in tempo reale sui tablet dei tavoli.")

    tab1, tab2 = st.tabs(["Gelati & Coppe", "Caffetteria & Bevande"])

    with tab1:
        st.subheader("Coppe Speciali")
        st.text_input("Prodotto 1", value="Coppa Cavour - € 6,50")
        st.text_input("Prodotto 2", value="Coppa Amarena - € 5,50")
    
    with tab2:
        st.subheader("Caffetteria")
        st.text_input("Prodotto 1", value="Caffè Espresso - € 1,30")
        st.text_input("Prodotto 2", value="Cappuccino - € 1,80")

# Sezione 3: AI Tavoli
elif scelta == "🤖 Stato AI Tavoli":
    st.header("🤖 Assistente AI ai Tavoli")
    st.success("L'AI è attiva sui tablet per l'upselling e le informazioni sugli allergeni.")
    
    st.subheader("Suggerimenti AI Più Efficaci stasera:")
    st.write("• Panna montata aggiuntiva (+€ 0,80) accettata 8 volte su 10.")
    st.write("• Abbinamento Brioche + Cappuccino consigliato con successo.")
