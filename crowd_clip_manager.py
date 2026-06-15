import os
import sys
import glob

# Try importing PySide6 or PySide2
try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    try:
        from PySide2 import QtCore, QtGui, QtWidgets
    except ImportError:
        # Fallback for headless environments/tests
        class MockQtCore:
            Qt = type('Qt', (), {'ItemFlags': None, 'KeepAspectRatio': 1, 'SmoothTransformation': 2})()
        QtCore = MockQtCore()
        QtGui = None
        QtWidgets = None

# Try importing Houdini
try:
    import hou
    IN_HOUDINI = True
except ImportError:
    IN_HOUDINI = False
    class MockHou:
        def node(self, path): return None
        class Error(Exception): pass
    hou = MockHou()

def get_preview_images(fbx_dir, clip_name):
    """
    Looks for a subdirectory matching the clip name containing PNG or JPG frame sequences.
    """
    possible_dirs = [
        os.path.join(fbx_dir, clip_name),
        os.path.join(fbx_dir, clip_name + "_preview"),
        os.path.join(fbx_dir, "previews", clip_name)
    ]
    for folder in possible_dirs:
        if os.path.isdir(folder):
            files = [
                os.path.join(folder, f)
                for f in os.listdir(folder)
                if f.lower().endswith(('.png', '.jpg', '.jpeg'))
            ]
            if files:
                return sorted(files)
    return []

def get_agent_nodes():
    """
    Scans the active Houdini scene for SOP nodes that contain or output agent primitives.
    """
    if not IN_HOUDINI:
        return ["/obj/test_agent1", "/obj/test_agent2"]
        
    nodes = []
    # Scan all geo objects
    for obj_node in hou.node("/obj").children():
        if obj_node.type().name() == "geo":
            for sop_node in obj_node.allSubChildren():
                if not hasattr(sop_node, "geometry"):
                    continue
                try:
                    geo = sop_node.geometry()
                    if geo and any(p.type() == hou.primType.Agent for p in geo.prims()):
                        nodes.append(sop_node.path())
                except:
                    pass
    return sorted(nodes)

def get_loaded_clips(agent_node_path):
    """
    Queries the selected agent node to find which clip names are already loaded.
    Checks downstream agentclip nodes first, falling back to definition clips.
    """
    if not IN_HOUDINI or not agent_node_path:
        return set()
        
    node = hou.node(agent_node_path)
    if not node:
        return set()
        
    clips = set()
    
    # 1. If selected node itself is an agentclip, use it
    clip_node = None
    if node.type().name().startswith("agentclip"):
        clip_node = node
    else:
        # 2. Check downstream outputs for agentclip node
        try:
            outputs = node.outputConnections()
            for conn in outputs:
                out_node = conn.outputNode()
                if out_node.type().name().startswith("agentclip"):
                    clip_node = out_node
                    break
        except:
            pass
            
    if clip_node:
        try:
            num = clip_node.parm("clips").eval()
            for i in range(1, num + 1):
                name_parm = clip_node.parm(f"name{i}")
                if name_parm:
                    val = name_parm.eval()
                    if val:
                        clips.add(val)
        except Exception as e:
            print(f"Error reading clips from agentclip node: {e}")
            
    # 3. Fallback: query geometry definition clips
    try:
        geo = node.geometry()
        if geo:
            prims = geo.prims()
            if prims:
                prim = prims[0]
                definition = prim.definition()
                for c in definition.clips():
                    clips.add(c.name())
    except:
        pass
        
    return clips


class ClipCardWidget(QtWidgets.QFrame):
    """
    Interactive card displaying a single clip. Hovering plays preview, clicking toggles selection.
    """
    selection_changed = QtCore.Signal()

    def __init__(self, clip_name, fbx_path, fbx_dir, parent=None):
        super().__init__(parent)
        self.setObjectName("ClipCard")
        self.clip_name = clip_name
        self.fbx_path = fbx_path
        self.fbx_dir = fbx_dir
        self.image_paths = get_preview_images(fbx_dir, clip_name)
        self.is_selected = False
        self.is_loaded = False
        self.current_frame = 0
        
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setLineWidth(2)
        
        self.init_ui()
        self.update_style()
        
        # Hover Playback Timer (24 FPS * 1.75 -> ~23ms interval)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(23)
        self.timer.timeout.connect(self.next_frame)

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        
        # Image Display Label
        self.image_label = QtWidgets.QLabel(self)
        self.image_label.setFixedSize(160, 120)
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: #121212; border-radius: 4px;")
        layout.addWidget(self.image_label)
        
        # Set first frame or placeholder
        self.show_frame(0)
        
        # Text Info
        self.title_label = QtWidgets.QLabel(self.clip_name, self)
        self.title_label.setObjectName("ClipTitle")
        self.title_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.title_label)
        
        # Badges layout
        self.badges_layout = QtWidgets.QHBoxLayout()
        self.badges_layout.setSpacing(4)
        
        # Loaded Badge
        self.loaded_badge = QtWidgets.QLabel("LOADED", self)
        self.loaded_badge.setObjectName("Badge")
        self.loaded_badge.setStyleSheet("background-color: #16a34a; color: white; font-weight: bold; font-size: 9px; border-radius: 3px; padding: 2px 4px;")
        self.loaded_badge.setVisible(False)
        self.badges_layout.addWidget(self.loaded_badge)
        
        # Missing Preview Badge
        self.missing_badge = QtWidgets.QLabel("NO PREVIEW", self)
        self.missing_badge.setObjectName("Badge")
        self.missing_badge.setStyleSheet("background-color: #dc2626; color: white; font-weight: bold; font-size: 9px; border-radius: 3px; padding: 2px 4px;")
        self.missing_badge.setVisible(len(self.image_paths) == 0)
        self.badges_layout.addWidget(self.missing_badge)
        
        layout.addLayout(self.badges_layout)
        
    def show_frame(self, index):
        if not self.image_paths:
            # Show placeholder text
            self.image_label.setText(f"🎥\n{self.clip_name}\n(No Preview)")
            self.image_label.setStyleSheet("background-color: #1a1a1a; color: #737373; font-weight: bold; text-align: center; border-radius: 4px;")
            return
            
        if index < len(self.image_paths):
            pix = QtGui.QPixmap(self.image_paths[index])
            if not pix.isNull():
                scaled = pix.scaled(self.image_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                self.image_label.setPixmap(scaled)
                
    def next_frame(self):
        if not self.image_paths:
            return
        self.current_frame = (self.current_frame + 1) % len(self.image_paths)
        self.show_frame(self.current_frame)
        
    def enterEvent(self, event):
        if self.image_paths:
            self.timer.start()
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        self.timer.stop()
        self.current_frame = 0
        self.show_frame(0)
        super().leaveEvent(event)
        
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.toggle_selection()
        super().mousePressEvent(event)
        
    def toggle_selection(self):
        self.is_selected = not self.is_selected
        self.update_style()
        self.selection_changed.emit()
        
    def set_loaded_state(self, is_loaded):
        self.is_loaded = is_loaded
        self.loaded_badge.setVisible(is_loaded)
        self.update_style()
        
    def update_style(self):
        # Apply style properties dynamically
        self.setProperty("selected", str(self.is_selected).lower())
        self.style().unpolish(self)
        self.style().polish(self)
        
        if self.is_selected:
            self.setStyleSheet("""
                QFrame#ClipCard {
                    background-color: #2b1442;
                    border: 2px solid #a855f7;
                    border-radius: 6px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame#ClipCard {
                    background-color: #262626;
                    border: 2px solid #404040;
                    border-radius: 6px;
                }
            """)


class CrowdClipImporterUI(QtWidgets.QDialog):
    """
    Main user interface for browsing, selecting, rendering, and importing crowd animation clips.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crowd Clip Importer Tool")
        self.resize(800, 600)
        self.setMinimumSize(600, 500)
        
        self.fbx_dir = ""
        self.cards = []
        
        self.init_ui()
        self.apply_styles()
        
        # Auto-fill active SOP path if any
        self.refresh_agents_list()
        
    def init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)
        
        # 1. FBX Directory Selector
        dir_layout = QtWidgets.QHBoxLayout()
        dir_layout.setSpacing(8)
        
        dir_label = QtWidgets.QLabel("FBX Directory:", self)
        dir_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        dir_layout.addWidget(dir_label)
        
        self.dir_input = QtWidgets.QLineEdit(self)
        self.dir_input.setPlaceholderText("Select folder containing FBX clips...")
        self.dir_input.textChanged.connect(self.on_dir_changed)
        dir_layout.addWidget(self.dir_input)
        
        self.browse_btn = QtWidgets.QPushButton("Browse", self)
        self.browse_btn.setObjectName("browseBtn")
        self.browse_btn.clicked.connect(self.browse_directory)
        dir_layout.addWidget(self.browse_btn)
        
        main_layout.addLayout(dir_layout)
        
        # 2. Target Node Selector
        target_layout = QtWidgets.QHBoxLayout()
        target_layout.setSpacing(8)
        
        target_label = QtWidgets.QLabel("Target Agent SOP:", self)
        target_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        target_layout.addWidget(target_label)
        
        self.agent_combo = QtWidgets.QComboBox(self)
        self.agent_combo.currentIndexChanged.connect(self.on_target_changed)
        target_layout.addWidget(self.agent_combo)
        
        self.refresh_nodes_btn = QtWidgets.QPushButton("Refresh Scene", self)
        self.refresh_nodes_btn.setObjectName("refreshBtn")
        self.refresh_nodes_btn.clicked.connect(self.refresh_agents_list)
        target_layout.addWidget(self.refresh_nodes_btn)
        
        main_layout.addLayout(target_layout)
        
        # 3. Scroll Area with Grid of Clips
        self.scroll_area = QtWidgets.QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("ScrollArea")
        
        self.grid_widget = QtWidgets.QWidget()
        self.grid_widget.setObjectName("GridWidget")
        self.grid_layout = QtWidgets.QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        
        self.scroll_area.setWidget(self.grid_widget)
        main_layout.addWidget(self.scroll_area)
        
        # 4. Bottom Info & Controls Bar
        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.setSpacing(12)
        
        self.info_label = QtWidgets.QLabel("No clips selected", self)
        self.info_label.setStyleSheet("font-size: 11px; color: #a3a3a3;")
        bottom_layout.addWidget(self.info_label)
        
        bottom_layout.addStretch()
        
        # Render Previews Button
        self.render_btn = QtWidgets.QPushButton("Generate Previews", self)
        self.render_btn.setObjectName("renderBtn")
        self.render_btn.clicked.connect(self.generate_selected_previews)
        self.render_btn.setEnabled(False)
        bottom_layout.addWidget(self.render_btn)
        
        # Import Button
        self.import_btn = QtWidgets.QPushButton("Import Selected Clips", self)
        self.import_btn.setObjectName("importBtn")
        self.import_btn.clicked.connect(self.import_selected_clips_to_scene)
        self.import_btn.setEnabled(False)
        bottom_layout.addWidget(self.import_btn)
        
        main_layout.addLayout(bottom_layout)
        
    def apply_styles(self):
        # Main stylesheet applying clean modern dark mode look with purple accents
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: #e2e8f0;
            }
            QLabel {
                color: #e2e8f0;
            }
            QLineEdit {
                background-color: #262626;
                border: 1px solid #404040;
                border-radius: 4px;
                padding: 6px;
                color: #f5f5f5;
            }
            QLineEdit:focus {
                border: 1px solid #a855f7;
            }
            QPushButton {
                background-color: #3b3b3b;
                color: #e2e8f0;
                border: 1px solid #282828;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4f4f4f;
                border-color: #5f5f5f;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #2b2b2b;
            }
            QPushButton:disabled {
                background-color: #2b2b2b;
                color: #555555;
                border-color: #222222;
            }
            QPushButton#importBtn {
                background-color: #d15000;
                border: 1px solid #f97316;
                color: white;
            }
            QPushButton#importBtn:hover {
                background-color: #ea650c;
                border-color: #fdba74;
            }
            QPushButton#importBtn:disabled {
                background-color: #382215;
                border-color: #2a1b10;
                color: #8c6653;
            }
            QPushButton#renderBtn {
                background-color: transparent;
                border: 2px solid #d15000;
                color: #ffa066;
            }
            QPushButton#renderBtn:hover {
                background-color: #d15000;
                color: white;
            }
            QPushButton#renderBtn:disabled {
                background-color: transparent;
                border-color: #382215;
                color: #8c6653;
            }
            QComboBox {
                background-color: #262626;
                border: 1px solid #404040;
                border-radius: 4px;
                padding: 6px;
                color: #f5f5f5;
                min-width: 200px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QScrollArea#ScrollArea {
                border: 1px solid #333333;
                background-color: #121212;
                border-radius: 6px;
            }
            QWidget#GridWidget {
                background-color: #121212;
            }
        """)

    def browse_directory(self):
        start_dir = self.dir_input.text() or os.path.expanduser("~")
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select FBX Animation Folder", start_dir
        )
        if selected:
            self.dir_input.setText(selected)
            
    def on_dir_changed(self, text):
        self.fbx_dir = text
        self.scan_and_populate_clips()
        
    def refresh_agents_list(self):
        self.agent_combo.clear()
        nodes = get_agent_nodes()
        self.agent_combo.addItems(nodes)
        
        # Update badge checks
        self.check_scene_loaded_badges()

    def on_target_changed(self, index):
        self.check_scene_loaded_badges()
        
    def scan_and_populate_clips(self):
        # Clear previous cards
        for card in self.cards:
            self.grid_layout.removeWidget(card)
            card.deleteLater()
        self.cards = []
        
        if not os.path.isdir(self.fbx_dir):
            return
            
        # Scan folder for FBX files
        fbx_files = [
            f for f in os.listdir(self.fbx_dir)
            if f.lower().endswith('.fbx')
        ]
        
        # Sort them
        fbx_files.sort()
        
        columns = 4
        for idx, fbx in enumerate(fbx_files):
            clip_name = os.path.splitext(fbx)[0]
            fbx_path = os.path.join(self.fbx_dir, fbx)
            
            card = ClipCardWidget(clip_name, fbx_path, self.fbx_dir, self)
            card.selection_changed.connect(self.on_selection_changed)
            
            row = idx // columns
            col = idx % columns
            self.grid_layout.addWidget(card, row, col)
            self.cards.append(card)
            
        # Check loaded badges immediately
        self.check_scene_loaded_badges()
        self.on_selection_changed()
        
    def check_scene_loaded_badges(self):
        target_path = self.agent_combo.currentText()
        loaded = get_loaded_clips(target_path)
        
        for card in self.cards:
            card.set_loaded_state(card.clip_name in loaded)
            
    def on_selection_changed(self):
        selected_cards = [c for c in self.cards if c.is_selected]
        count = len(selected_cards)
        
        if count == 0:
            self.info_label.setText("No clips selected")
            self.import_btn.setEnabled(False)
            self.render_btn.setEnabled(False)
        else:
            self.info_label.setText(f"{count} clip{'s' if count > 1 else ''} selected")
            self.import_btn.setEnabled(True)
            self.render_btn.setEnabled(True)
            
    def generate_selected_previews(self):
        if not IN_HOUDINI:
            QtWidgets.QMessageBox.information(self, "Stand-alone Mode", "Headless render is only available when running inside Houdini.")
            return
            
        selected_cards = [c for c in self.cards if c.is_selected]
        if not selected_cards:
            return
            
        # Build render target list
        fbx_targets = []
        for card in selected_cards:
            # We will render previews inside a folder named after the clip inside the current folder
            out_dir = os.path.join(self.fbx_dir, card.clip_name)
            fbx_targets.append((card.fbx_path, card.clip_name, out_dir))
            
        # Prompt user to confirm rendering
        msg = f"This will render OpenGL preview sequences for {len(fbx_targets)} selected clip(s).\n\nDo you want to continue?"
        if not QtWidgets.QMessageBox.question(self, "Generate Previews", msg) == QtWidgets.QMessageBox.Yes:
            return
            
        # Run render with Houdini Interruptable Operation
        try:
            self.run_headless_render(fbx_targets)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Render Error", f"An error occurred during preview render:\n{e}")
            
        # Re-scan to load the new previews
        self.scan_and_populate_clips()
        
    def run_headless_render(self, targets):
        import subprocess
        num_clips = len(targets)
        
        # Resolve hython path dynamically using HFS environment variable
        hfs = os.environ.get("HFS")
        if hfs:
            hython_path = os.path.join(hfs, "bin", "hython.exe").replace("\\", "/")
        else:
            hython_path = "C:/Program Files/Side Effects Software/Houdini 20.5.550/bin/hython.exe"
            
        # Locate the render script in the same directory as this module
        script_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(script_dir, "render_clip_preview.py").replace("\\", "/")
        
        try:
            with hou.InterruptableOperation("Rendering Clip Previews", open_interrupt_dialog=True) as op:
                for idx, (fbx_path, clip_name, out_dir) in enumerate(targets):
                    op.updateProgress(float(idx) / num_clips)
                    
                    cmd = [
                        hython_path,
                        script_path,
                        "--fbx", fbx_path,
                        "--clip", clip_name,
                        "--outdir", out_dir,
                        "--maxframes", "30"
                    ]
                    
                    # Hide the background console window on Windows
                    startupinfo = None
                    if sys.platform == "win32":
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        startupinfo.wShowWindow = subprocess.SW_HIDE
                        
                    # Launch background hython render
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        startupinfo=startupinfo,
                        text=True
                    )
                    
                    # Poll process to remain interactive and support cancellation
                    while proc.poll() is None:
                        op.updateProgress(float(idx) / num_clips)
                        QtCore.QThread.msleep(100)
                        
                    # Check execution result
                    stdout, stderr = proc.communicate()
                    if proc.returncode != 0:
                        print(f"Background render error for '{clip_name}':\n{stderr}\n{stdout}")
                        
        except hou.OperationInterrupted:
            # Terminate running render process if user cancelled
            if 'proc' in locals() and proc.poll() is None:
                proc.kill()
            print("Render cancelled by user.")
                        
    def import_selected_clips_to_scene(self):
        target_path = self.agent_combo.currentText()
        if not target_path:
            QtWidgets.QMessageBox.warning(self, "No Target Agent", "Please select a target Agent node first.")
            return
            
        selected_cards = [c for c in self.cards if c.is_selected]
        if not selected_cards:
            return
            
        clips_to_import = [
            (c.clip_name, c.fbx_path.replace("\\", "/"))
            for c in selected_cards
        ]
        
        success = import_selected_clips(target_path, clips_to_import)
        if success:
            # Refresh combo list state
            self.check_scene_loaded_badges()
            self.on_selection_changed()
            
            # Show success message
            QtWidgets.QMessageBox.information(
                self, "Import Success", f"Successfully imported {len(clips_to_import)} clip(s) to {target_path}."
            )


def find_locomotion_joint(agent_node):
    """
    Finds a suitable locomotion joint name (e.g. mixamorig:Hips) from the agent's rig definition.
    """
    if not agent_node:
        return "root"
    try:
        geo = agent_node.geometry()
        if geo and geo.prims():
            definition = geo.prims()[0].definition()
            rig = definition.rig()
            # Heuristic 1: Find a joint containing "hips" or "pelvis" (standard for character rigs)
            for i in range(rig.transformCount()):
                name = rig.transformName(i)
                if name != "__locomotion__" and ("hips" in name.lower() or "pelvis" in name.lower()):
                    return name
            # Heuristic 2: If not found, look for "root" or "locomotion" (excluding __locomotion__)
            for i in range(rig.transformCount()):
                name = rig.transformName(i)
                if name != "__locomotion__" and ("root" in name.lower() or "locomotion" in name.lower()):
                    return name
            # Heuristic 3: Fallback to the top-level parent index == -1 (excluding __locomotion__)
            for i in range(rig.transformCount()):
                name = rig.transformName(i)
                if name != "__locomotion__" and rig.parentIndex(i) == -1:
                    return name
    except Exception as e:
        print(f"Warning: Failed to find locomotion joint from agent definition: {e}")
    return "root"


def import_selected_clips(agent_node_path, clips_to_import):
    """
    Core function that wires an agentclip node after the target agent node and sets up the multiparm.
    """
    if not IN_HOUDINI:
        print("Mock Import Success:", clips_to_import)
        return True
        
    agent_node = hou.node(agent_node_path)
    if not agent_node:
        return False
        
    try:
        # Resolve the locomotion joint name dynamically from the agent's rig
        locomotion_joint = find_locomotion_joint(agent_node)
        
        # Configure locomotion node on the agent SOP itself if it supports it
        fbx_loc_parm = agent_node.parm("fbxlocomotionnode")
        if fbx_loc_parm:
            fbx_loc_parm.set(locomotion_joint)
        create_loc_parm = agent_node.parm("createlocomotionjoint")
        if create_loc_parm:
            create_loc_parm.set(1)
        apply_loc_parm = agent_node.parm("applylocomotion")
        if apply_loc_parm:
            apply_loc_parm.set(0) # Keep in-place
            
        # Find downstream agentclip node
        outputs = agent_node.outputConnections()
        clip_node = None
        for conn in outputs:
            out_node = conn.outputNode()
            if out_node.type().name().startswith("agentclip"):
                clip_node = out_node
                break
                
        # If no agentclip node, create and wire one
        if not clip_node:
            parent = agent_node.parent()
            clip_node = parent.createNode("agentclip", f"{agent_node.name()}_clips")
            clip_node.setPosition(agent_node.position() + hou.Vector2(0, -1.0))
            clip_node.setInput(0, agent_node)
            
            # Wire outputs of agent_node to clip_node
            for conn in outputs:
                conn.outputNode().setInput(conn.inputIndex(), clip_node)
                
        # Configure shared locomotion settings on the agentclip SOP
        loc_node_parm = clip_node.parm("locomotionnode")
        if loc_node_parm:
            loc_node_parm.set(locomotion_joint)
        create_loc_joint_parm = clip_node.parm("createlocomotionjoint")
        if create_loc_joint_parm:
            create_loc_joint_parm.set(1)
        apply_clip_loc_parm = clip_node.parm("applylocomotion")
        if apply_clip_loc_parm:
            apply_clip_loc_parm.set(0) # Keep in-place
            
        # Read existing clips on clip_node
        existing_clips = {}
        num_existing = clip_node.parm("clips").eval()
        for i in range(1, num_existing + 1):
            c_name = clip_node.parm(f"name{i}").eval()
            if not c_name:
                continue
            c_file = clip_node.parm(f"file{i}").eval()
            c_src = clip_node.parm(f"source{i}").eval()
            existing_clips[c_name] = (c_file, c_src)
            
        # Add new clips
        for clip_name, fbx_path in clips_to_import:
            existing_clips[clip_name] = (fbx_path, "fbx")
            
        # Re-populate multiparm
        clip_node.parm("clips").set(len(existing_clips))
        for idx, (name, (file_path, source)) in enumerate(existing_clips.items(), start=1):
            clip_node.parm(f"name{idx}").set(name)
            clip_node.parm(f"source{idx}").set(source)
            clip_node.parm(f"file{idx}").set(file_path)
            
            # Force keep external reference
            keepref_parm = clip_node.parm(f"keepref{idx}")
            if keepref_parm:
                keepref_parm.set(1)
                
            # Force convert units (helps with scale mismatches)
            convert_parm = clip_node.parm(f"convertunits{idx}")
            if convert_parm:
                convert_parm.set(1)
                
            # Force convert to in-place
            inplace_parm = clip_node.parm(f"converttoinplace{idx}")
            if inplace_parm:
                inplace_parm.set(1)
                
        # Cook node to update representation
        clip_node.cook(force=True)
        return True
    except Exception as e:
        hou.ui.displayMessage(f"Failed to import clips: {e}", severity=hou.severityType.Error)
        return False


# Entry point for showing the UI inside Houdini
_current_manager_window = None

def show_ui():
    global _current_manager_window
    if _current_manager_window is not None:
        try:
            _current_manager_window.close()
            _current_manager_window.deleteLater()
        except:
            pass
            
    # Parent UI to the Houdini main window
    parent_win = hou.qt.mainWindow() if IN_HOUDINI else None
    _current_manager_window = CrowdClipImporterUI(parent_win)
    _current_manager_window.show()

# Standard python __main__ block for standalone running/testing
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = CrowdClipImporterUI()
    window.show()
    sys.exit(app.exec_())
