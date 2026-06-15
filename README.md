# Crowd Clip Importer

Una herramienta hecha en PySide para agilizar la carga, previsualización e importación de clips de animación FBX en definiciones de agentes en Houdini. Desarrollado originalmente para Maya/Golaem, ahora adaptado y actualizado para Houdini.

## Características

- **Interfaz Interactiva PySide**: Cuadrícula visual con reproducción en bucle a 24 FPS al pasar el cursor para previsualizar clips rápidamente.
- **Generador de Previsualizaciones en Segundo Plano**: Lanza subprocesos de `hython` en segundo plano para renderizar secuencias OpenGL, manteniendo la sesión principal de Houdini completamente fluida.
- **Extractor Dinámico de Locomoción**: Resuelve automáticamente las articulaciones de cadera/pelvis para fijar las animaciones en el sitio (*in-place*) en el origen.
- **Encuadre de Cámara Automático**: Calcula dinámicamente las cajas delimitadoras de la geometría del agente para encuadrar las previsualizaciones en un ángulo contrapicado óptimo a 45 grados.
- **Conexión de Nodos No Destructiva**: Crea y conecta de manera automática los nodos `agent` y `agentclip` SOP en tu red.

## Instalación y Configuración

1. Copia los scripts de python (`crowd_clip_manager.py` y `render_clip_preview.py`) en la carpeta de scripts de tu ruta de Houdini.
2. En Houdini, crea una nueva herramienta en tu estante (*Shelf Tool*) y pega el siguiente código en la pestaña de Script para lanzar la interfaz:

```python
import sys
# Reemplaza con la ruta local donde clonaste el repositorio
sys.path.append("C:/ruta/al/repositorio/clonado")

import crowd_clip_manager
import importlib
importlib.reload(crowd_clip_manager)

crowd_clip_manager.show_ui()
```

## Requisitos

- Python 3 con PySide2 o PySide6
