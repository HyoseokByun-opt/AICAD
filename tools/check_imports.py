"""Import every package AICAD needs and report what is missing."""
import importlib
import sys

MODULES = [
    ("cadquery", "CadQuery (modelling)"), ("OCP", "OpenCASCADE kernel (cadquery-ocp)"),
    ("flask", "Flask (web server)"), ("waitress", "Waitress (WSGI server)"),
    ("pypdfium2", "PDFium (PDF import)"), ("PIL", "Pillow (images)"), ("numpy", "NumPy"),
    ("cv2", "OpenCV (drawing analysis)"), ("ezdxf", "ezdxf (DXF import/export)"),
]


def main():
    bad = 0
    for mod, label in MODULES:
        try:
            m = importlib.import_module(mod)
            v = getattr(m, "__version__", "")
            print(f"  ok       {label} {v}")
        except Exception as e:  # noqa: BLE001
            bad += 1
            print(f"  MISSING  {label}: {e}")
    sys.path.insert(0, __file__.rsplit("tools", 1)[0] + "app")
    try:
        import aicad
        print(f"  ok       AICAD {aicad.__version__}")
    except Exception as e:  # noqa: BLE001
        bad += 1
        print(f"  MISSING  AICAD program: {e}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
