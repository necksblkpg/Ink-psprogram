# app.py

import os
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

from data import fetch_all_products_with_sales
from sheets import push_to_google_sheets

# Konfigurera loggning (kan flyttas till en separat fil om önskas)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("app.log"),
              logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def main():
    # Minimal CSS för att förbättra layout utan att ändra sidomenyn
    st.markdown("""
        <style>
            .stButton>button {
                background-color: #4B8BBE;
                color: white;
                padding: 0.7em 2em;
                border-radius: 5px;
                border: none;
                font-size: 1em;
                width: 100%;
            }
            .stButton>button:hover {
                background-color: #357ABD;
            }
            table {
                border-collapse: collapse;
                width: 100%;
            }
            th, td {
                text-align: left;
                padding: 8px;
            }
            th {
                background-color: #f2f2f2;
            }
            tr:nth-child(even) {
                background-color: #f9f9f9;
            }
        </style>
        """, unsafe_allow_html=True)

    # Hämta miljövariabler
    api_endpoint = os.environ.get('YOUR_API_ENDPOINT')
    api_token = os.environ.get('CENTRA_API_TOKEN')

    if not api_endpoint or not api_token:
        st.error("API-endpoint och/eller token är inte inställda. Vänligen ställ in dem i dina miljövariabler.")
        return

    # Sidopanelens filter
    st.sidebar.header("⚙️ Filteralternativ")

    today = datetime.today()
    default_from_date = (today - timedelta(days=30)).strftime('%Y-%m-%d')
    default_to_date = today.strftime('%Y-%m-%d')

    with st.sidebar:
        active_filter = st.checkbox("✅ Visa endast aktiva produkter", value=True)
        bundle_filter = st.checkbox("🚫 Exkludera Bundles", value=True)
        exclude_supplier = st.checkbox("🚫 Exkludera 'Utgående produkt'", value=True)  # Ny checkbox
        shipped_filter = st.checkbox("📦 Inkludera endast ordrar med status 'SHIPPED'", value=True)

        st.markdown("---")
        st.subheader("⚙️ Lagerinställningar")
        lead_time = st.number_input("⏱️ Leveranstid (dagar)", min_value=1, value=7)
        safety_stock = st.number_input("🛡️ Säkerhetslager", min_value=0, value=10)

    # Datumväljare i huvudsektionen
    st.subheader("📅 Försäljningsdata Filter")
    col1, col2 = st.columns(2)

    with col1:
        from_date = st.date_input("Från Datum",
                                  value=datetime.strptime(default_from_date, '%Y-%m-%d'))
    with col2:
        to_date = st.date_input("Till Datum",
                                value=datetime.strptime(default_to_date, '%Y-%m-%d'))

    from_date_str = from_date.strftime('%Y-%m-%d')
    to_date_str = to_date.strftime('%Y-%m-%d')

    st.markdown("---")

    # Knappen för att hämta data
    fetch_button_container = st.container()
    with fetch_button_container:
        fetch_button = st.button("Hämta Produkt- och Försäljningsdata", key="fetch_data")

    if fetch_button:
        with st.spinner('Hämtar produkt- och försäljningsdata...'):
            merged_df = fetch_all_products_with_sales(
                api_endpoint, api_token,
                from_date_str, to_date_str,
                lead_time, safety_stock,
                only_shipped=shipped_filter
            )

        if merged_df is not None and not merged_df.empty:
            st.success("✅ Data hämtad framgångsrikt!")

            # Lägg till en ny tom kolumn "Quantity ordered" i DataFrame
            merged_df["Quantity ordered"] = ""

            # Tillämpa filter baserat på kryssrutorna
            if active_filter:
                if 'Status' in merged_df.columns:
                    merged_df = merged_df[merged_df['Status'] == "ACTIVE"]
                else:
                    st.warning("⚠️ Kolumnen 'Status' saknas i data.")

            if bundle_filter:
                if 'Is Bundle' in merged_df.columns:
                    merged_df = merged_df[merged_df['Is Bundle'] == False]
                else:
                    st.warning("⚠️ Kolumnen 'Is Bundle' saknas i data.")

            if exclude_supplier:
                if 'Supplier' in merged_df.columns:
                    merged_df = merged_df[merged_df['Supplier'] != "Utgående produkt"]
                else:
                    st.warning("⚠️ Kolumnen 'Supplier' saknas i data.")

            # Spara den filtrerade merged_df i session_state
            st.session_state['merged_df'] = merged_df.copy()

            if merged_df.empty:
                st.warning("⚠️ Inga produkter matchade de angivna filtren.")
            else:
                # Lägg till apostrof framför 'Product Number' för att undvika formateringsproblem i Google Sheets
                if 'Product Number' in merged_df.columns:
                    merged_df['Product Number'] = "'" + merged_df['Product Number'].astype(str)
                else:
                    st.warning("⚠️ Kolumnen 'Product Number' saknas i data.")

                # Uppdatera kolumnordningen i huvudfunktionen
                desired_order = [
                    "ProductID",
                    "Product Number", 
                    "Size",
                    "Product Name",
                    "Status",
                    "Is Bundle",
                    "Supplier",
                    "Quantity Sold",
                    "Stock Balance",
                    "Avg Daily Sales",
                    "Days to Zero",
                    "Reorder Level",
                    "Quantity to Order",
                    "Need to Order",
                    "Quantity ordered",  # lägg till nya kolumnen sist
                ]

                # Reordna kolumnerna om de finns
                existing_columns = [col for col in desired_order if col in merged_df.columns]
                merged_df = merged_df[existing_columns]

                # Uppdatera session_state med den reordnade DataFrame
                st.session_state['merged_df'] = merged_df.copy()

                # Visa dataframe med anpassad höjd och bredd
                st.dataframe(
                    merged_df,
                    height=600,
                    column_config={
                        "ProductID": st.column_config.TextColumn(
                            "ProductID",
                            help="Unikt produkt-ID",
                            width="medium"
                        ),
                        "Product Number": st.column_config.TextColumn(
                            "Product Number",
                            help="Produktnummer",
                            width="medium"
                        ),
                        "Size": st.column_config.TextColumn(
                            "Size",
                            help="Storlek",
                            width="small"
                        ),
                        "Product Name": st.column_config.TextColumn(
                            "Product Name",
                            help="Produktnamn",
                            width="large"
                        ),
                        "Status": st.column_config.TextColumn(
                            "Status",
                            help="Produktstatus",
                            width="small"
                        ),
                        "Is Bundle": st.column_config.TextColumn(
                            "Is Bundle",
                            help="Är produkten en bundle?",
                            width="small"
                        ),
                        "Supplier": st.column_config.TextColumn(
                            "Supplier",
                            help="Leverantör",
                            width="medium"
                        ),
                        "Quantity Sold": st.column_config.NumberColumn(
                            "Quantity Sold",
                            help="Antal sålda enheter",
                            format="%d"
                        ),
                        "Stock Balance": st.column_config.NumberColumn(
                            "Stock Balance",
                            help="Aktuellt lagersaldo",
                            format="%d"
                        ),
                        "Avg Daily Sales": st.column_config.NumberColumn(
                            "Avg Daily Sales",
                            help="Genomsnittlig daglig försäljning",
                            format="%.1f"
                        ),
                        "Days to Zero": st.column_config.NumberColumn(
                            "Days to Zero",
                            help="Dagar till lagret tar slut",
                            format="%d"
                        ),
                        "Reorder Level": st.column_config.NumberColumn(
                            "Reorder Level",
                            help="Beställningspunkt",
                            format="%d"
                        ),
                        "Quantity to Order": st.column_config.NumberColumn(
                            "Quantity to Order",
                            help="Rekommenderad beställningskvantitet",
                            format="%d"
                        ),
                        "Need to Order": st.column_config.TextColumn(
                            "Need to Order",
                            help="Behöver beställas?",
                            width="small"
                        ),
                        "Quantity ordered": st.column_config.TextColumn(
                            "Quantity ordered",
                            help="Manuell kolumn för beställd kvantitet",
                            width="medium"
                        )
                    }
                )

        else:
            st.error("❌ Misslyckades med att hämta data eller ingen data tillgänglig.")

    # Kontrollera om merged_df finns i session_state
    if 'merged_df' in st.session_state:
        merged_df = st.session_state['merged_df']

        # Knappen för att pusha data till Google Sheets
        push_sheet_button = st.button("📤 Push Data till Google Sheets", key="push_sheet")

        if push_sheet_button:
            with st.spinner('Pusha data till Google Sheets...'):
                st.markdown("🔍 Verifierar data innan push...")

                # Hantera NaN-värden innan push
                filtered_df = merged_df.replace([np.inf, -np.inf], np.nan).fillna('')

                sheet_name = f"Produkt_Försäljning_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                sheet_url = push_to_google_sheets(filtered_df, sheet_name)

                if sheet_url:
                    st.success(f"✅ Data har pushats till Google Sheets! [Öppna Sheet]({sheet_url})")
                else:
                    st.error("❌ Misslyckades med att pusha data till Google Sheets.")

    # Optional: Lägg till en enkel footer
    st.markdown("""
        <style>
            .footer {
                position: fixed;
                left: 0;
                bottom: 0;
                width: 100%;
                background-color: #f1f1f1;
                color: #333333;
                text-align: center;
                padding: 10px;
                font-size: 0.9em;
            }
        </style>
        <div class="footer">
            &copy; 2024 Ditt Företag. Alla rättigheter förbehållna.
        </div>
        """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
