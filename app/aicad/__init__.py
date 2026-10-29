"""AICAD - AI-assisted CAD modelling from drawings and descriptions.

The package turns an engineering drawing (PDF, image, DXF) or a written
description into a parametric CadQuery model on the OpenCASCADE kernel and
exports it as STEP. A local vision-language model served by llama.cpp reads
the drawing and writes the model code; every step runs offline.
"""

__version__ = "0.1.0"
APP_NAME = "AICAD"
APP_FULL = "AI-assisted CAD Modelling"
