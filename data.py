# data.py

import os
import requests
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import streamlit as st

# Konfigurera loggning
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("app.log"),
              logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Använd Streamlits caching för att förbättra prestanda
@st.cache_data(show_spinner=False)
def fetch_all_suppliers(api_endpoint, headers):
    """
    Hämtar alla leverantörer utan paginering.
    """
    suppliers = []
    suppliers_query = '''
    query Suppliers {
        suppliers {
            id
            name
            status
        }
    }
    '''
    try:
        response = requests.post(api_endpoint,
                                 json={"query": suppliers_query},
                                 headers=headers)
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            raise Exception(
                f"GraphQL query error: {json.dumps(data['errors'], indent=2)}")

        fetched_suppliers = data['data']['suppliers']
        suppliers.extend(fetched_suppliers)

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error while fetching suppliers: {str(e)}")
        st.error(f"❌ Request error while fetching suppliers: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Error processing supplier data: {str(e)}")
        st.error(f"❌ Error processing supplier data: {str(e)}")
        return None

    return suppliers


@st.cache_data(show_spinner=False)
def fetch_supplied_product_variants(api_endpoint, headers, supplier_id, products_limit=100):
    """
    Hämtar alla suppliedProductVariants för en given leverantör, hanterar paginering.
    """
    variants = []
    page = 1

    variants_query = '''
    query SupplierVariants($id: Int!, $limit: Int!, $page: Int!) {
        supplier(id: $id) {
            suppliedProductVariants(limit: $limit, page: $page) {
                productVariant {
                    product {
                        id
                        name
                        status
                        productNumber
                        isBundle
                    }
                    productSizes {
                        stock {
                            productSize {
                                description
                                quantity
                            }
                        }
                    }
                }
            }
        }
    }
    '''

    while True:
        variables = {"id": supplier_id, "limit": products_limit, "page": page}

        try:
            response = requests.post(api_endpoint,
                                     json={
                                         "query": variants_query,
                                         "variables": variables
                                     },
                                     headers=headers)
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                raise Exception(
                    f"GraphQL query error: {json.dumps(data['errors'], indent=2)}"
                )

            fetched_variants = data['data']['supplier']['suppliedProductVariants']
            if not fetched_variants:
                break

            variants.extend(fetched_variants)

            if len(fetched_variants) < products_limit:
                break

            page += 1

        except requests.exceptions.RequestException as e:
            logger.error(
                f"Request error while fetching variants for supplier ID '{supplier_id}': {str(e)}"
            )
            st.error(
                f"❌ Request error while fetching variants for supplier ID '{supplier_id}': {str(e)}"
            )
            break
        except Exception as e:
            logger.error(
                f"Error processing variants for supplier ID '{supplier_id}': {str(e)}"
            )
            st.error(
                f"❌ Error processing variants for supplier ID '{supplier_id}': {str(e)}"
            )
            break

    return variants


@st.cache_data(show_spinner=False)
def fetch_all_suppliers_and_variants(api_endpoint, headers, products_limit=100):
    """
    Hämtar alla leverantörer och deras suppliedProductVariants.
    """
    suppliers = fetch_all_suppliers(api_endpoint, headers)
    if suppliers is None:
        return None

    suppliers_data = {}

    for supplier in suppliers:
        supplier_id = supplier['id']
        # Säkerställ att supplier_id är ett heltal
        try:
            supplier_id = int(supplier_id)
        except ValueError:
            logger.error(f"Invalid supplier ID: {supplier_id}")
            st.warning(f"⚠️ Invalid supplier ID: {supplier_id}")
            continue

        supplier_name = supplier['name']
        supplier_status = supplier['status']

        variants = fetch_supplied_product_variants(api_endpoint, headers,
                                                   supplier_id, products_limit)
        if not variants:
            logger.info(
                f"No product variants found for supplier: {supplier_name}")
            st.info(
                f"ℹ️ No product variants found for supplier: {supplier_name}")
            continue

        for variant in variants:
            product = variant['productVariant']['product']
            product_id = str(product['id']).strip().upper()
            product_name = product['name']
            product_status = product['status']
            product_number = product['productNumber']
            is_bundle = product['isBundle']

            product_sizes = variant['productVariant'].get('productSizes', [])
            if not product_sizes:
                # Hantera produkter utan storlekar
                key = (product_id, "N/A")
                if key not in suppliers_data:
                    suppliers_data[key] = {
                        "ProductID": product_id,
                        "Product Name": product_name,
                        "Product Number": product_number,
                        "Status": product_status,
                        "Is Bundle": is_bundle,
                        "Supplier": supplier_name,
                        "Stock Balance": 0,
                        "Size": "N/A"
                    }
                # Lägg till lagerbalans om det finns
                for size_entry in product_sizes:
                    stocks = size_entry.get('stock', [])
                    for stock in stocks:
                        quantity = stock.get('quantity', 0)
                        suppliers_data[key]['Stock Balance'] += quantity
            else:
                for size_entry in product_sizes:
                    stocks = size_entry.get('stock', [])
                    for stock in stocks:
                        product_size = stock.get('productSize', {})
                        quantity = stock.get('quantity', 0)
                        size_description = product_size.get('description', "N/A")

                        key = (product_id, size_description)
                        if key not in suppliers_data:
                            suppliers_data[key] = {
                                "ProductID": product_id,
                                "Product Name": product_name,
                                "Product Number": product_number,
                                "Status": product_status,
                                "Is Bundle": is_bundle,
                                "Supplier": supplier_name,
                                "Stock Balance": 0,
                                "Size": size_description
                            }

                        suppliers_data[key]['Stock Balance'] += quantity

    return suppliers_data


@st.cache_data(show_spinner=False)
def fetch_all_product_costs(api_endpoint, headers, limit=100):
    """
    Hämtar inköpspris (unitCost) för samtliga produkter (paginering),
    och returnerar en dict med key=produkt_id, value=inköpspris.
    Här antas att alla varianter av en produkt har samma pris,
    så vi tar första variantens 'unitCost' som "Inköpspris".
    """
    cost_dict = {}
    page = 1

    cost_query = '''
    query AllProductCosts($limit: Int!, $page: Int!) {
        products(limit: $limit, page: $page) {
            id
            productNumber
            variants {
                unitCost {
                    value
                }
            }
        }
    }
    '''

    while True:
        variables = {
            "limit": limit,
            "page": page
        }

        try:
            response = requests.post(api_endpoint,
                                     json={
                                         "query": cost_query,
                                         "variables": variables
                                     },
                                     headers=headers)
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                raise Exception(
                    f"GraphQL query error: {json.dumps(data['errors'], indent=2)}"
                )

            products = data['data']['products']
            if not products:
                break

            for p in products:
                product_id = str(p['id']).strip().upper()
                variants = p.get('variants', [])
                if variants and 'unitCost' in variants[0] and variants[0]['unitCost']:
                    cost_value = variants[0]['unitCost'].get('value', 0)
                else:
                    cost_value = 0

                # Spara i dict
                cost_dict[product_id] = cost_value

            if len(products) < limit:
                break

            page += 1

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error while fetching product costs: {str(e)}")
            st.error(f"❌ Request error while fetching product costs: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error processing product cost data: {str(e)}")
            st.error(f"❌ Error processing product cost data: {str(e)}")
            return None

    return cost_dict


@st.cache_data(show_spinner=False)
def fetch_all_products(api_endpoint, api_token, limit=200):
    all_product_data = []

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_token}"
    }

    # Hämta data om leverantörer och varianter
    suppliers_data = fetch_all_suppliers_and_variants(api_endpoint,
                                                      headers,
                                                      products_limit=100)
    if suppliers_data is None:
        return None

    # Hämta lagerbalance (stock) via GraphQL
    product_query_template = '''
    query ProductStocks($limit: Int!, $page: Int!) {
        warehouses {
            stock(limit: $limit, page: $page) {
                productSize {
                    quantity
                    size {
                        name
                    }
                    productVariant {
                        product {
                            id
                            name
                            status
                            productNumber
                            isBundle
                        }
                    }
                }
            }
        }
    }
    '''

    page = 1
    while True:
        variables = {"limit": limit, "page": page}

        try:
            response = requests.post(api_endpoint,
                                     json={
                                         "query": product_query_template,
                                         "variables": variables
                                     },
                                     headers=headers)
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                raise Exception(
                    f"GraphQL query error: {json.dumps(data['errors'], indent=2)}"
                )

            warehouses = data['data']['warehouses']
            if not warehouses:
                break

            for warehouse in warehouses:
                stock_entries = warehouse.get('stock', [])
                for stock_entry in stock_entries:
                    product_info = stock_entry['productSize']['productVariant']['product']
                    product_id = str(product_info['id']).strip().upper()
                    product_name = product_info.get('name', 'N/A')
                    product_status = product_info.get('status', 'N/A')
                    product_number = product_info.get('productNumber', 'N/A')
                    is_bundle = product_info.get('isBundle', False)
                    quantity = stock_entry['productSize']['quantity']
                    size_name = (
                        stock_entry['productSize']['size']['name']
                        if stock_entry['productSize']['size']
                        else "N/A"
                    )

                    # Uppdatera stock balance och size från suppliers_data
                    key = (product_id, size_name)
                    if key in suppliers_data:
                        suppliers_data[key]['Stock Balance'] += quantity
                    else:
                        # Lägg till produkten i suppliers_data med "No Supplier"
                        suppliers_data[key] = {
                            "ProductID": product_id,
                            "Product Name": product_name,
                            "Product Number": product_number,
                            "Status": product_status,
                            "Is Bundle": is_bundle,
                            "Supplier": "No Supplier",
                            "Stock Balance": quantity,
                            "Size": size_name
                        }

            if len(warehouses[0].get('stock', [])) < limit:
                break

            page += 1

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error while fetching product stocks: {str(e)}")
            st.error(f"❌ Request error while fetching product stocks: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error processing product stock data: {str(e)}")
            st.error(f"❌ Error processing product stock data: {str(e)}")
            return None

    # Hämta inköpspris
    cost_dict = fetch_all_product_costs(api_endpoint, headers, limit=100)
    if cost_dict is None:
        # Om vi inte kunde hämta kostnader, sätt 0
        cost_dict = {}

    # Konvertera suppliers_data till DataFrame
    all_product_data = list(suppliers_data.values())
    if not all_product_data:
        logger.info("Ingen produktdata hittades.")
        st.info("ℹ️ Ingen produktdata hittades.")
        return pd.DataFrame()

    df = pd.DataFrame(all_product_data)

    # Lägg till kolumnen "Inköpspris" baserat på product_id
    df["Inköpspris"] = df["ProductID"].apply(lambda pid: cost_dict.get(pid, 0.0))

    # Säkerställ att 'Stock Balance' är av heltalstyp
    df['Stock Balance'] = pd.to_numeric(df['Stock Balance'], errors='coerce').fillna(0).astype(int)

    return df


@st.cache_data(show_spinner=False)
def fetch_sales_data(api_endpoint,
                     headers,
                     from_date_str,
                     to_date_str,
                     only_shipped=False,
                     limit=100):
    sales_data = []
    orders_page = 1

    # Anpassa GraphQL-frågan baserat på only_shipped
    if only_shipped:
        orders_query = '''
        query Orders($limit: Int!, $page: Int!, $from: DateTimeTz!, $to: DateTimeTz!) {
            orders(limit: $limit, page: $page, where: { orderDate: { from: $from, to: $to }, status: [SHIPPED] }) {
                orderDate
                status
                lines {
                    productVariant {
                        product {
                            id
                            name
                        }
                    }
                    size
                    quantity
                }
            }
        }
        '''
    else:
        orders_query = '''
        query Orders($limit: Int!, $page: Int!, $from: DateTimeTz!, $to: DateTimeTz!) {
            orders(limit: $limit, page: $page, where: { orderDate: { from: $from, to: $to } }) {
                orderDate
                status
                lines {
                    productVariant {
                        product {
                            id
                            name
                        }
                    }
                    size
                    quantity
                }
            }
        }
        '''

    while True:
        variables = {
            "limit": limit,
            "page": orders_page,
            "from": f"{from_date_str}T00:00:00Z",
            "to": f"{to_date_str}T23:59:59Z"
        }

        try:
            response = requests.post(api_endpoint,
                                     json={
                                         "query": orders_query,
                                         "variables": variables
                                     },
                                     headers=headers)
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                raise Exception(
                    f"GraphQL query error: {json.dumps(data['errors'], indent=2)}"
                )

            orders = data['data']['orders']
            if not orders:
                break

            for order in orders:
                # Om endast "SHIPPED" är valt, alla ordrar här är "SHIPPED"
                if only_shipped and order.get('status') != "SHIPPED":
                    continue

                lines = order.get('lines', [])
                for line in lines:
                    product_variant = line.get('productVariant')
                    if not product_variant:
                        continue
                    product = product_variant.get('product')
                    if not product:
                        continue
                    product_id = str(product['id']).strip().upper()
                    size = line['size'] if line['size'] else "N/A"
                    quantity = line.get('quantity', 1)

                    sales_data.append({
                        "ProductID": product_id,
                        "Size": size,
                        "Quantity Sold": quantity
                    })

            if len(orders) < limit:
                break

            orders_page += 1

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error while fetching orders: {str(e)}")
            st.error(f"❌ Request error while fetching orders: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error processing orders data: {str(e)}")
            st.error(f"❌ Error processing orders data: {str(e)}")
            return None

    return sales_data


def process_sales_data(sales_data, from_date, to_date):
    """
    Bearbetar försäljningsdata för att beräkna total såld mängd och genomsnittlig daglig försäljning.
    """
    if not sales_data:
        return pd.DataFrame(
            columns=["ProductID", "Size", "Quantity Sold", "Avg Daily Sales"])

    sales_df = pd.DataFrame(sales_data)

    # Beräkna total försäljning per produkt och storlek
    sales_summary = sales_df.groupby(['ProductID', 'Size']).agg({
        'Quantity Sold': 'sum'
    }).reset_index()

    # Beräkna antalet dagar i datumintervallet
    days_in_range = (pd.to_datetime(to_date) - pd.to_datetime(from_date)).days + 1

    # Beräkna genomsnittlig daglig försäljning
    sales_summary["Avg Daily Sales"] = (
        sales_summary["Quantity Sold"] / days_in_range
    ).round(1)

    # Säkerställ att 'Quantity Sold' är heltal
    sales_summary["Quantity Sold"] = sales_summary["Quantity Sold"].astype(int)

    return sales_summary


def merge_product_and_sales_data(products_df, sales_summary_df):
    if products_df.empty:
        logger.info("Produktdata är tom. Ingen data att visa.")
        st.info("ℹ️ Produktdata är tom. Ingen data att visa.")
        return pd.DataFrame()

    merged_df = pd.merge(products_df,
                         sales_summary_df,
                         on=['ProductID', 'Size'],
                         how='left')
    merged_df['Quantity Sold'] = merged_df['Quantity Sold'].fillna(0).astype(int)
    merged_df['Avg Daily Sales'] = merged_df['Avg Daily Sales'].fillna(0).astype(float).round(1)
    return merged_df


def calculate_reorder_metrics(df, lead_time, safety_stock):
    """
    Beräknar omordernivå, beställningskvantitet och om en beställning behövs.
    """
    if df.empty:
        return df

    # Beräkna omordernivå
    df["Reorder Level"] = (df["Avg Daily Sales"] * lead_time) + safety_stock

    # Beräkna kvantitet att beställa
    df["Quantity to Order"] = df["Reorder Level"] - df["Stock Balance"]
    df["Quantity to Order"] = df["Quantity to Order"].apply(lambda x: max(x, 0))

    # Bestäm om vi behöver göra en beställning
    df["Need to Order"] = df["Quantity to Order"].apply(lambda x: "Yes" if x > 0 else "No")

    return df


@st.cache_data(show_spinner=False)
def fetch_all_products_with_sales(api_endpoint,
                                  api_token,
                                  from_date_str,
                                  to_date_str,
                                  lead_time,
                                  safety_stock,
                                  only_shipped=False,
                                  product_limit=200,
                                  orders_limit=100):
    products_df = fetch_all_products(api_endpoint, api_token, limit=product_limit)
    if products_df is None:
        return None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_token}"
    }
    sales_data = fetch_sales_data(api_endpoint,
                                  headers,
                                  from_date_str,
                                  to_date_str,
                                  only_shipped=only_shipped,
                                  limit=orders_limit)
    if sales_data is None:
        return None

    # Bearbeta försäljningsdata
    sales_summary_df = process_sales_data(sales_data, from_date_str, to_date_str)
    merged_df = merge_product_and_sales_data(products_df, sales_summary_df)

    # Lägg till omorderberäkningar
    merged_df = calculate_reorder_metrics(merged_df, lead_time, safety_stock)

    # Uppdaterad beräkning av Days to Zero
    merged_df['Days to Zero'] = ''  # Sätt standardvärde till tom sträng

    # Beräkna Days to Zero endast för produkter med försäljning
    mask = (merged_df['Avg Daily Sales'] > 0) & (merged_df['Stock Balance'] >= 0)
    merged_df.loc[mask, 'Days to Zero'] = (
        (merged_df.loc[mask, 'Stock Balance'] /
         merged_df.loc[mask, 'Avg Daily Sales']).round().astype(int)
    )

    # Konvertera kolumnen till string-typ för att hantera eventuella tomma värden
    merged_df['Days to Zero'] = merged_df['Days to Zero'].astype(str)
    # Ersätt tomma strängar med None för bättre visning
    merged_df['Days to Zero'] = merged_df['Days to Zero'].replace('', None)

    return merged_df
