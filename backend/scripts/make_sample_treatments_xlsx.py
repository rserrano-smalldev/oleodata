"""Genera una plantilla Excel de EJEMPLO para el importador de tratamientos.

No es obligatoria: el importador (módulo 5) acepta cualquier estructura
razonable de columnas, siempre que existan sinónimos reconocibles. Esta
plantilla sirve solo como referencia y, a la vez, como fichero de prueba:
incluye deliberadamente una fila con una fecha inválida para demostrar que
el importador reporta el error sin bloquear el resto del lote.

Uso: python -m scripts.make_sample_treatments_xlsx [ruta_salida.xlsx]
"""

import sys

import openpyxl


def build_sample_workbook(parcel_code: str = "FINCA-REF") -> openpyxl.Workbook:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tratamientos"

    ws.append(["Cuaderno de campo — ejemplo (esta plantilla NO es obligatoria)"])
    ws.append([])
    ws.append(
        [
            "Fecha aplicación",
            "Parcela",
            "Tipo",
            "Nombre comercial",
            "Materia activa",
            "Dosis",
            "Ud.",
            "Plaga objetivo",
            "Coste",
        ]
    )
    ws.append(["12/03/2024", parcel_code, "Fungicida", "Producto ejemplo A", "Sustancia ejemplo", "2,5", "l/ha", "Repilo", "45,00"])
    ws.append([45372, parcel_code, "Insecticida", "Producto ejemplo B", "Sustancia ejemplo", 1.2, "l/ha", "Mosca del olivo", 38.5])
    # Fila con fecha inválida a propósito, para demostrar el manejo de errores
    # del importador (no debe abortar el resto del lote).
    ws.append(["31/13/2024", parcel_code, "Abono", "Producto ejemplo C", "", "10", "kg/ha", "", "20"])
    ws.append(["2024-05-02", parcel_code, "", "Cobre ejemplo", "", "3", "kg/ha", "Repilo", "30"])

    return wb


if __name__ == "__main__":
    output_path = sys.argv[1] if len(sys.argv) > 1 else "plantilla_tratamientos_ejemplo.xlsx"
    build_sample_workbook().save(output_path)
    print(f"Plantilla de ejemplo escrita en {output_path}")
