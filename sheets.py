# sheets.py

import logging
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread_dataframe import set_with_dataframe
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def authenticate_google_sheets():
    """
    Autentiserar med Google Sheets API med hjälp av en service account.
    """
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name("key.json", scope)
        client = gspread.authorize(creds)
        return client
    except FileNotFoundError:
        logger.error("key.json filen hittades inte. Kontrollera att den finns i rotkatalogen.")
        st.error("❌ key.json filen hittades inte. Kontrollera att den finns i rotkatalogen.")
        return None
    except Exception as e:
        logger.error(f"Autentiseringsfel: {str(e)}")
        st.error(f"❌ Autentiseringsfel: {str(e)}")
        return None


def push_to_google_sheets(df, sheet_name):
    """
    Skapar ett nytt Google Sheet, skriver data och delar det med en fördefinierad e-postadress.
    """
    try:
        client = authenticate_google_sheets()
        if client is None:
            st.error("❌ Kunde inte autentisera mot Google Sheets.")
            return None

        # Debugutskrift för att se kolumnerna innan beräkning
        print("Kolumner innan beräkning:", df.columns.tolist())

        # Kontrollera att nödvändiga kolumner finns
        if 'Stock Balance' not in df.columns or 'Avg Daily Sales' not in df.columns:
            st.error("❌ Saknar nödvändiga kolumner för Days to Zero beräkning")
            print("Saknade kolumner för Days to Zero beräkning")
            return None

        # Konvertera kolumnerna till numeriska värden
        df['Stock Balance'] = pd.to_numeric(df['Stock Balance'], errors='coerce')
        df['Avg Daily Sales'] = pd.to_numeric(df['Avg Daily Sales'], errors='coerce')

        # Beräkna Days to Zero och hantera specialfall
        df['Days to Zero'] = df.apply(lambda row: 
            '' if row['Avg Daily Sales'] == 0 else 
            int(round(row['Stock Balance'] / row['Avg Daily Sales'], 0))
            if pd.notnull(row['Stock Balance']) and pd.notnull(row['Avg Daily Sales']) 
            else '', axis=1
        )

        # Debugutskrift efter beräkning
        print("Kolumner efter beräkning:", df.columns.tolist())
        print("Exempel på Days to Zero värden:", df['Days to Zero'].head())

        # Definiera den önskade kolumnordningen
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
            "Quantity ordered"  # Lägg även till här
        ]

        # Reordna kolumnerna och behåll bara de som finns
        existing_columns = [col for col in desired_order if col in df.columns]
        df = df[existing_columns]

        # Skapa ett nytt Google Sheet
        sheet = client.create(sheet_name)
        worksheet = sheet.get_worksheet(0)

        # Använd set_with_dataframe för att skriva DataFrame till Google Sheets
        set_with_dataframe(worksheet, df)

        # Dela arket med en fördefinierad e-postadress
        predefined_email = 'neckwearsweden@gmail.com'
        try:
            sheet.share(predefined_email, perm_type='user', role='writer')
        except Exception as e:
            logger.error(f"Error sharing sheet with {predefined_email}: {str(e)}")
            st.error(f"❌ Misslyckades med att dela Google Sheet med {predefined_email}: {str(e)}")
            return None

        return sheet.url

    except Exception as e:
        logger.error(f"Error pushing data to Google Sheets: {str(e)}")
        st.error(f"❌ Misslyckades med att pusha data till Google Sheets: {str(e)}")
        return None
