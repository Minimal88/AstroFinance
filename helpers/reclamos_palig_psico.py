"""
Completa reclamos de PALIG (Pan-American Life) psicologia.

PALIG regresa el PDF de "Solicitud de Autorizacion y Formulario de
Reclamacion" con la seccion del medico ya llena, pero la primera seccion
("A LLENAR POR EL ASEGURADO") en blanco. Este script sobrepone esa seccion
-la mayoria de los campos son fijos para este asegurado- mas la firma,
sobre el PDF escaneado recibido, y escribe un PDF nuevo.

Campos fijos (ver PATIENT_INFO): Compania, No. Poliza, No. Certificado,
Nombre completo del paciente, Sexo, Fecha de nacimiento, Tipo de paciente,
Motivo de la Consulta, Telefono, Correo electronico.

Campos que varian por reclamo (argumentos CLI): fecha de inicio de la
enfermedad, fecha de servicio.

Uso:
    python reclamos_palig_psico.py --input reclamo.pdf \
        --fecha-inicio-enfermedad 01/07/2026 --fecha-servicio 15/07/2026

    # Calibracion: si PALIG cambia el formulario, generar una cuadricula
    # de coordenadas para volver a medir las posiciones de FIELD_POSITIONS:
    python reclamos_palig_psico.py --input reclamo.pdf --debug-grid
"""

import argparse
import os
import re
import sys
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")

# Datos fijos del asegurado/paciente para este reclamante. Coordenadas en
# FIELD_POSITIONS fueron calibradas contra helpers/reclamo_template.pdf
# (formulario PALIG, carta 612x792pt) -- si PALIG cambia el formulario,
# recalibrar con --debug-grid.
PATIENT_INFO = {
    "compania": "WIND RIVER SYSTEMS COSTA RICA S.R.L",
    "poliza": "390",
    "certificado": "323",
    "nombre_paciente": "ESTEBAN MARTINEZ VALVERDE",
    "sexo": "M",
    "fecha_nacimiento": "08/08/1993",
    "tipo_paciente": "Titular",
    "motivo_consulta": "Enfermedad",
    "telefono": "84438908",
    "correo": "estemarval@gmail.com",
}

DEFAULT_FIRMA_PATH = os.path.join(SCRIPT_DIR, "firma.png")

# (page_index, x, y, font_size, max_width) -- x/y en puntos PDF (origen
# inferior izquierdo), y es la linea base del texto. max_width (opcional):
# si el texto no cabe a font_size, se reduce el tamano hasta que quepa
# (evita que campos largos como Compania se salgan de su celda).
FIELD_POSITIONS = {
    "compania": (0, 140, 632, 9, 165),
    "poliza": (0, 316, 632, 8, None),
    "certificado": (0, 420, 632, 8, None),
    "nombre_paciente": (0, 140, 608, 9, 235),
    "fecha_nacimiento": (0, 420, 609, 7, None),
    "fecha_inicio_enfermedad": (0, 420, 585, 7, None),
    "telefono": (0, 280, 555, 6.5, 65),
    "correo": (0, 350, 558, 6.5, 135),
    "fecha_servicio": (0, 145, 488, 8, None),
}

# Checkboxes: (page_index, center_x, center_y, box_size). Se dibuja una "X"
# centrada en la casilla seleccionada.
SEXO_CHECKBOXES = {
    "F": (0, 391.0, 605.6, 6),
    "M": (0, 401.2, 605.6, 6),
}
TIPO_PACIENTE_CHECKBOXES = {
    "Titular": (0, 149.8, 584.9, 7),
    "Conyugue": (0, 187.8, 584.9, 7),
    "Hijo": (0, 240.6, 584.9, 7),
}
MOTIVO_CONSULTA_CHECKBOXES = {
    "Accidente": (0, 139.7, 558.9, 7),
    "Enfermedad": (0, 184.5, 558.9, 7),
    "Maternidad": (0, 237.0, 558.9, 7),
}

# (page_index, x, y, width, height) -- esquina inferior izquierda de la firma.
FIRMA_POSITION = (0, 330, 484, 100, 18)


def draw_checkbox_mark(c, checkbox_positions, selected_key):
    if selected_key not in checkbox_positions:
        raise ValueError(
            f"'{selected_key}' no es una opcion valida; opciones: {list(checkbox_positions)}"
        )
    _, cx, cy, size = checkbox_positions[selected_key]
    c.setFont("Helvetica-Bold", size)
    c.drawCentredString(cx, cy - size * 0.35, "X")


def _draw_claim_content(c, fields, firma_path, page_index=0):
    """Dibuja campos, casillas y firma sobre un canvas ya abierto, para la
    pagina page_index. Compartido por build_overlay (llenado real) y
    draw_debug_grid (calibracion), asi ambos quedan siempre en sincronia."""
    for name, (field_page, x, y, font_size, max_width) in FIELD_POSITIONS.items():
        if field_page != page_index:
            continue
        text = fields[name]
        size = font_size
        if max_width is not None:
            while size > 5 and stringWidth(text, "Helvetica", size) > max_width:
                size -= 0.5
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica", size)
        c.drawString(x, y, text)

    for checkbox_positions, selected_key in (
        (SEXO_CHECKBOXES, PATIENT_INFO["sexo"]),
        (TIPO_PACIENTE_CHECKBOXES, PATIENT_INFO["tipo_paciente"]),
        (MOTIVO_CONSULTA_CHECKBOXES, PATIENT_INFO["motivo_consulta"]),
    ):
        if checkbox_positions[selected_key][0] == page_index:
            c.setFillColorRGB(0, 0, 0)
            draw_checkbox_mark(c, checkbox_positions, selected_key)

    firma_page, fx, fy, fw, fh = FIRMA_POSITION
    if firma_page == page_index and firma_path and os.path.isfile(firma_path):
        c.drawImage(firma_path, fx, fy, width=fw, height=fh, mask="auto", preserveAspectRatio=True)


def build_overlay(width, height, fecha_inicio_enfermedad, fecha_servicio, firma_path):
    """Crea un PDF de una pagina (en memoria) con la seccion del asegurado."""
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(width, height))

    fields = dict(PATIENT_INFO)
    fields["fecha_inicio_enfermedad"] = fecha_inicio_enfermedad
    fields["fecha_servicio"] = fecha_servicio

    _draw_claim_content(c, fields, firma_path)

    c.save()
    buffer.seek(0)
    return PdfReader(buffer)


def fill_claim(input_path, output_path, fecha_inicio_enfermedad, fecha_servicio, firma_path):
    reader = PdfReader(input_path)
    page = reader.pages[0]
    mediabox = page.mediabox
    overlay = build_overlay(
        float(mediabox.width), float(mediabox.height),
        fecha_inicio_enfermedad, fecha_servicio, firma_path,
    )
    page.merge_page(overlay.pages[0])

    writer = PdfWriter()
    writer.add_page(page)
    for extra_page in reader.pages[1:]:
        writer.add_page(extra_page)

    with open(output_path, "wb") as f:
        writer.write(f)


def draw_debug_grid(
    input_path,
    output_path,
    fecha_inicio_enfermedad=None,
    fecha_servicio=None,
    firma_path=DEFAULT_FIRMA_PATH,
    step=20,
):
    """Sobrepone una cuadricula de coordenadas (en puntos PDF) y, encima, el
    mismo contenido que fill_claim dibujaria (campos, casillas, firma) sobre
    cada pagina de input_path -- asi se ven lineas y datos juntos al
    recalibrar FIELD_POSITIONS/CHECKBOXES si PALIG cambia el formulario. Las
    fechas son opcionales: si se omiten se usa un texto de relleno, solo
    para ubicar el campo."""
    reader = PdfReader(input_path)
    writer = PdfWriter()

    fields = dict(PATIENT_INFO)
    fields["fecha_inicio_enfermedad"] = fecha_inicio_enfermedad or "DD/MM/AAAA"
    fields["fecha_servicio"] = fecha_servicio or "DD/MM/AAAA"

    for page_index, page in enumerate(reader.pages):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=(width, height))

        c.setFont("Helvetica", 6)
        for x in range(0, int(width) + 1, step):
            c.setStrokeColorRGB(1, 0.7, 0.7)
            c.line(x, 0, x, height)
            c.setFillColorRGB(1, 0, 0)
            c.drawString(x + 1, height - 8, str(x))
        for y in range(0, int(height) + 1, step):
            c.setStrokeColorRGB(0.7, 0.7, 1)
            c.line(0, y, width, y)
            c.setFillColorRGB(0, 0, 1)
            c.drawString(1, y + 1, str(y))

        _draw_claim_content(c, fields, firma_path, page_index=page_index)

        c.save()
        buffer.seek(0)
        overlay = PdfReader(buffer)
        page.merge_page(overlay.pages[0])
        writer.add_page(page)

    with open(output_path, "wb") as f:
        writer.write(f)


def default_output_path(input_path):
    base, ext = os.path.splitext(input_path)
    return f"{base}_completo{ext or '.pdf'}"


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="PDF del reclamo recibido de PALIG")
    parser.add_argument("--output", help="Ruta del PDF de salida (default: <input>_completo.pdf)")
    parser.add_argument("--fecha-inicio-enfermedad", help="Formato DD/MM/AAAA")
    parser.add_argument("--fecha-servicio", help="Formato DD/MM/AAAA")
    parser.add_argument("--firma", default=DEFAULT_FIRMA_PATH, help="Ruta a la imagen de firma (PNG)")
    parser.add_argument(
        "--debug-grid", action="store_true",
        help="En vez de llenar el reclamo, sobrepone una cuadricula de coordenadas para calibrar FIELD_POSITIONS",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])

    if not os.path.isfile(args.input):
        sys.exit(f"Error: no existe el archivo de entrada '{args.input}'")

    output_path = args.output or default_output_path(args.input)

    if args.debug_grid:
        draw_debug_grid(
            args.input,
            output_path,
            fecha_inicio_enfermedad=args.fecha_inicio_enfermedad,
            fecha_servicio=args.fecha_servicio,
            firma_path=args.firma,
        )
        print(f"Cuadricula de calibracion escrita en '{output_path}'")
        return

    if not args.fecha_inicio_enfermedad or not DATE_RE.match(args.fecha_inicio_enfermedad):
        sys.exit("Error: --fecha-inicio-enfermedad es requerida, formato DD/MM/AAAA")
    if not args.fecha_servicio or not DATE_RE.match(args.fecha_servicio):
        sys.exit("Error: --fecha-servicio es requerida, formato DD/MM/AAAA")
    if not os.path.isfile(args.firma):
        sys.exit(f"Error: no existe la imagen de firma '{args.firma}'")

    fill_claim(args.input, output_path, args.fecha_inicio_enfermedad, args.fecha_servicio, args.firma)
    print(f"Reclamo completado escrito en '{output_path}'")


if __name__ == "__main__":
    main()
