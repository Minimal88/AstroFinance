"""
GUI simple para completar reclamos PALIG psico.

Envoltorio de tkinter sobre reclamos_palig_psico.py: permite elegir el PDF
de entrada y escribir las dos fechas variables, sin usar la terminal. El
resto (datos fijos, firma) se toma de la configuracion del script principal.

Uso:
    python reclamos_palig_psico_gui.py
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox

from reclamos_palig_psico import (
    DATE_RE,
    DEFAULT_FIRMA_PATH,
    default_output_path,
    fill_claim,
)


class ReclamoApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Reclamo PALIG Psico")
        self.resizable(False, False)

        padding = {"padx": 8, "pady": 6}

        tk.Label(self, text="PDF de reclamo:").grid(row=0, column=0, sticky="e", **padding)
        self.input_var = tk.StringVar()
        tk.Entry(self, textvariable=self.input_var, width=45, state="readonly").grid(
            row=0, column=1, **padding
        )
        tk.Button(self, text="Examinar...", command=self.choose_input).grid(
            row=0, column=2, **padding
        )

        tk.Label(self, text="Fecha inicio enfermedad (DD/MM/AAAA):").grid(
            row=1, column=0, sticky="e", **padding
        )
        self.fecha_inicio_var = tk.StringVar()
        tk.Entry(self, textvariable=self.fecha_inicio_var, width=20).grid(
            row=1, column=1, sticky="w", **padding
        )

        tk.Label(self, text="Fecha de servicio (DD/MM/AAAA):").grid(
            row=2, column=0, sticky="e", **padding
        )
        self.fecha_servicio_var = tk.StringVar()
        tk.Entry(self, textvariable=self.fecha_servicio_var, width=20).grid(
            row=2, column=1, sticky="w", **padding
        )

        tk.Button(self, text="Generar", command=self.generar).grid(
            row=3, column=0, columnspan=3, pady=12
        )

    def choose_input(self):
        path = filedialog.askopenfilename(
            title="Selecciona el PDF de reclamo",
            filetypes=[("PDF", "*.pdf")],
        )
        if path:
            self.input_var.set(path)

    def generar(self):
        input_path = self.input_var.get()
        fecha_inicio_enfermedad = self.fecha_inicio_var.get().strip()
        fecha_servicio = self.fecha_servicio_var.get().strip()

        if not input_path or not os.path.isfile(input_path):
            messagebox.showerror("Error", "Selecciona un PDF de reclamo valido.")
            return
        if not DATE_RE.match(fecha_inicio_enfermedad):
            messagebox.showerror(
                "Error", "Fecha inicio enfermedad invalida, formato DD/MM/AAAA."
            )
            return
        if not DATE_RE.match(fecha_servicio):
            messagebox.showerror("Error", "Fecha de servicio invalida, formato DD/MM/AAAA.")
            return
        if not os.path.isfile(DEFAULT_FIRMA_PATH):
            messagebox.showerror(
                "Error", f"No existe la imagen de firma '{DEFAULT_FIRMA_PATH}'."
            )
            return

        output_path = default_output_path(input_path)
        try:
            fill_claim(
                input_path, output_path, fecha_inicio_enfermedad, fecha_servicio, DEFAULT_FIRMA_PATH
            )
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo generar el reclamo: {exc}")
            return

        messagebox.showinfo("Listo", f"Reclamo completado escrito en:\n{output_path}")
        if os.name == "nt":
            os.startfile(output_path)


if __name__ == "__main__":
    ReclamoApp().mainloop()
