# rastreador_precios.py
# Rastreador dinámico de precios — GitHub Actions + Google Sheets

import os
import re
from datetime import datetime

import gspread
import requests
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
import json

# ============================================================
# PASO 1: AUTENTICACIÓN SEGURA CON GOOGLE SHEETS
# ============================================================
# Las credenciales viven en una variable de entorno llamada
# GOOGLE_CREDENTIALS_JSON (un JSON completo de Service Account).
# GitHub Actions la inyecta en tiempo de ejecución → nunca
# toca el código ni el repositorio.

def autenticar_sheets():
    """Carga credenciales desde env-var y retorna el cliente gspread."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise EnvironmentError("Variable GOOGLE_CREDENTIALS_JSON no encontrada.")

    creds_dict = json.loads(creds_json)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


# ============================================================
# PASO 2: LEER LA PESTAÑA 'Configuracion'
# ============================================================
# Se espera que la pestaña tenga encabezados en la fila 1:
#   ID_Producto | Competidor | URL | Selector_CSS
# Ejemplo de fila:
#   PROD-001 | Amazon | https://... | span.a-price-whole

def obtener_configuracion(spreadsheet):
    """Retorna una lista de dicts con la config de cada producto."""
    hoja = spreadsheet.worksheet("Configuracion")
    registros = hoja.get_all_records()  # list[dict] usando la fila 1 como keys
    return registros


# ============================================================
# PASO 3: PETICIÓN HTTP SIMULANDO UN NAVEGADOR
# ============================================================
# Muchos sitios bloquean peticiones sin User-Agent.
# Enviamos uno real para pasar los filtros básicos anti-bot.

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
}

def obtener_html(url: str) -> str | None:
    """Hace GET a la URL y retorna el HTML. Retorna None si falla."""
    try:
        respuesta = requests.get(url, headers=HEADERS, timeout=15)
        respuesta.raise_for_status()  # lanza error si status >= 400
        return respuesta.text
    except requests.RequestException as e:
        print(f"  ⚠️  Error al acceder a {url}: {e}")
        return None


# ============================================================
# PASO 4: EXTRACCIÓN Y LIMPIEZA DEL PRECIO
# ============================================================
# BeautifulSoup busca el elemento por el selector CSS configurado.
# La limpieza convierte "US$ 1.299,99" → 1299.99 (float).

def extraer_precio(html: str, selector_css: str) -> float | None:
    """Parsea el HTML y extrae el precio como número flotante."""
    soup = BeautifulSoup(html, "html.parser")
    elemento = soup.select_one(selector_css)

    if not elemento:
        print(f"  ⚠️  Selector '{selector_css}' no encontró ningún elemento.")
        return None

    texto_raw = elemento.get_text(strip=True)
    print(f"  → Texto crudo extraído: '{texto_raw}'")

    # Elimina símbolos de moneda y espacios: "US$ 1.299,99" → "1.299,99"
    texto_limpio = re.sub(r"[^\d.,]", "", texto_raw)

    # Detecta si el formato es europeo (1.299,99) o americano (1,299.99)
    if re.search(r",\d{2}$", texto_limpio):           # termina en ,XX → europeo
        texto_limpio = texto_limpio.replace(".", "").replace(",", ".")
    else:                                              # formato americano
        texto_limpio = texto_limpio.replace(",", "")

    try:
        return float(texto_limpio)
    except ValueError:
        print(f"  ⚠️  No se pudo convertir '{texto_limpio}' a número.")
        return None


# ============================================================
# PASO 5: INYECCIÓN DE DATOS EN 'Historial_Diario'
# ============================================================
# Agrega UNA fila al final con: [Fecha, ID_Producto, Competidor, Precio]

def registrar_precio(spreadsheet, id_producto: str, competidor: str, precio: float):
    """Append de una fila nueva en la pestaña Historial_Diario."""
    hoja = spreadsheet.worksheet("Historial_Diario")
    fecha_hoy = datetime.utcnow().strftime("%Y-%m-%d")  # ISO 8601, UTC
    fila_nueva = [fecha_hoy, id_producto, competidor, precio]
    hoja.append_row(fila_nueva, value_input_option="USER_ENTERED")
    print(f"  ✅  Registrado: {fila_nueva}")


# ============================================================
# ORQUESTADOR PRINCIPAL
# ============================================================

def main():
    SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
    if not SPREADSHEET_ID:
        raise EnvironmentError("Variable SPREADSHEET_ID no encontrada.")

    print("🔐 Autenticando con Google Sheets...")
    cliente = autenticar_sheets()
    spreadsheet = cliente.open_by_key(SPREADSHEET_ID)

    print("📋 Leyendo configuración...")
    configuracion = obtener_configuracion(spreadsheet)
    print(f"   {len(configuracion)} producto(s) a rastrear.\n")

    for item in configuracion:
        id_producto  = item["ID_Producto"]
        competidor   = item["Competidor"]
        url          = item["URL"]
        selector_css = item["Selector_CSS"]

        print(f"🔍 [{id_producto}] {competidor} — {url}")

        html = obtener_html(url)
        if html is None:
            continue

        precio = extraer_precio(html, selector_css)
        if precio is None:
            continue

        registrar_precio(spreadsheet, id_producto, competidor, precio)

    print("\n🎉 Rastreo completado.")


if __name__ == "__main__":
    main()
