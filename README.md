# Houdini Crowd Clip Importer

An interactive PySide tool to streamline loading, previewing, and importing FBX animation clips into Houdini Crowd Agent Definitions. Originally developed for Maya/Golaem workflows, now adapted and updated for Houdini.

## Features

- **Interactive PySide UI**: Card-based grid with 24 FPS hover playback loops for quick clip previsualization.
- **Headless Preview Generator**: Spawns background `hython` subprocesses to render OpenGL sequences, keeping the main Houdini session fully responsive.
- **Dynamic Locomotion Extractor**: Automatically resolves hips/pelvis joints to enforce locked, in-place animations at the origin.
- **Automatic Camera Framing**: Dynamically computes agent geometry bounding boxes to frame previews at an optimal profile contrapicado angle.
- **Non-Destructive Node Wiring**: Automatically creates and updates `agent` and `agentclip` SOP nodes downstream in your network.

## Installation & Setup

1. Copy the python scripts (`crowd_clip_manager.py` and `render_clip_preview.py`) to your Houdini python path directory.
2. In Houdini, create a new Shelf Tool and paste the following Python code to launch the UI:

```python
import sys
# Replace with your local path to the scripts
sys.path.append("C:/path/to/cloned/repository")

import crowd_clip_manager
import importlib
importlib.reload(crowd_clip_manager)

crowd_clip_manager.show_ui()
```

## Requirements

- **Houdini 20.5+**
- Python 3 with PySide2 or PySide6
