import google.generativeai as genai
import json
import re
import base64
import os
import math
from pathlib import Path

# Lazy-load API key from environment fallback
def _get_gemini_key():
    try:
        from app.config import settings as app_settings
        return getattr(app_settings, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
    except ImportError:
        return os.getenv("GEMINI_API_KEY", "")

_gemini_key = _get_gemini_key()
if _gemini_key:
    genai.configure(api_key=_gemini_key)
_model = genai.GenerativeModel("gemini-2.0-flash")

def generate_animation_script(scene: dict, word_timestamps: list, diagram_image_path: str = None) -> list:
    """
    Intelligently generates detailed camera and visual synchronization events
    for diagrams, formulas, and tables using Gemini Vision and NLP mapping.
    """
    try:
        if not word_timestamps:
            return []

        # STEP 1 — Build word lookup at start of generate_animation_script
        word_ms = {}
        for wt in word_timestamps:
            clean = wt["word"].lower().strip(".,;:?!\"'-")
            if clean:
                word_ms[clean] = wt["start_ms"]
                if len(clean) > 4:
                    word_ms[clean[:5]] = wt["start_ms"]

        def find_best_ms(keyword, index, fallback_base=2000, spacing=3500):
            """Helper to search for trigger word in word_ms or return a smooth proportional fallback."""
            if not keyword:
                return fallback_base + index * spacing
            clean_kw = keyword.lower().strip(".,;:?!\"'-")
            
            # Exact match
            if clean_kw in word_ms:
                return word_ms[clean_kw]
            
            # Substring match
            for k, val in word_ms.items():
                if clean_kw in k or k in clean_kw:
                    return val
                    
            # 5-letter prefix match
            if len(clean_kw) > 4 and clean_kw[:5] in word_ms:
                return word_ms[clean_kw[:5]]
                
            return fallback_base + index * spacing

        # STEP 2 — Detect content type from scene dict
        dna_type = scene.get("scene_dna", {}).get("dna_type", "DIAGRAM_SPATIAL")
        has_diagram = bool(scene.get("diagram_refs"))
        has_formula = bool(scene.get("formula_refs"))
        has_table = bool(scene.get("table_data"))

        # Make sure diagram image path actually exists
        img_path = None
        if diagram_image_path and os.path.exists(diagram_image_path):
            img_path = diagram_image_path
        elif has_diagram:
            candidates = [
                scene["diagram_refs"][0],
                os.path.join("backend", scene["diagram_refs"][0]) if not scene["diagram_refs"][0].startswith("backend") else scene["diagram_refs"][0],
                os.path.join("static/uploads/diagrams", os.path.basename(str(scene["diagram_refs"][0]))),
                os.path.join("backend/static/uploads/diagrams", os.path.basename(str(scene["diagram_refs"][0])))
            ]
            for cand in candidates:
                if cand and os.path.exists(cand):
                    img_path = cand
                    break

        events = []

        # STEP 3 — Route to sub-function based on content
        if has_diagram and img_path:
            if dna_type == "PROCESS_FLOW":
                events = _process_flow_events(scene, word_ms, img_path, find_best_ms)
            elif dna_type == "CAUSE_EFFECT":
                events = _cause_effect_events(scene, word_ms, img_path, find_best_ms)
            else:
                events = _spatial_diagram_events(scene, word_ms, img_path, find_best_ms)
        elif has_formula:
            # Re-route diagram path to formula image if formula_refs exists
            formula_img = scene["formula_refs"][0]
            f_candidates = [
                formula_img,
                os.path.join("backend", formula_img) if not formula_img.startswith("backend") else formula_img,
                os.path.join("static/uploads/formulas", os.path.basename(str(formula_img))),
                os.path.join("backend/static/uploads/formulas", os.path.basename(str(formula_img)))
            ]
            f_img_path = None
            for cand in f_candidates:
                if cand and os.path.exists(cand):
                    f_img_path = cand
                    break
            events = _formula_events(scene, word_ms, f_img_path, find_best_ms)
        elif has_table:
            events = _table_events(scene, word_ms, find_best_ms)

        if not events:
            return []

        # STEP 4 — Cognitive load protection (apply to ALL returned events)
        # Sort events by timestamp_ms.
        events.sort(key=lambda x: x.get("timestamp_ms", 0))

        # Check consecutive camera cuts (zoom_in, zoom_out, overview)
        camera_event_types = {"diagram_zoom_in", "diagram_zoom_out", "diagram_overview", "process_flow_pan", "sequential_zoom_per_region"}
        for i in range(1, len(events)):
            diff = events[i].get("timestamp_ms", 0) - events[i-1].get("timestamp_ms", 0)
            if diff < 700:
                is_curr_cam = events[i].get("event_type") in camera_event_types
                is_prev_cam = events[i-1].get("event_type") in camera_event_types
                if is_curr_cam and is_prev_cam:
                    # push the later one to earlier_timestamp + 750ms
                    events[i]["timestamp_ms"] = events[i-1].get("timestamp_ms", 0) + 750

        # Conform key parameters to timeline builder format
        for ev in events:
            ev["start_ms"] = ev.get("timestamp_ms", 0)
            if "hold_ms" in ev.get("data", {}):
                ev["end_ms"] = ev["start_ms"] + ev["data"]["hold_ms"]
            else:
                ev["end_ms"] = ev["start_ms"] + 1500

        # Re-sort after adjusting timestamps
        events.sort(key=lambda x: x.get("start_ms", 0))
        return events

    except Exception as e:
        print("[AnimationBrain ERROR]", str(e))
        return []

def _get_image_base64(img_path):
    with open(img_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def _call_gemini_vision(img_path, prompt):
    img_b64 = _get_image_base64(img_path)
    response = _model.generate_content([
        {"mime_type": "image/png", "data": img_b64},
        prompt
    ])
    
    # Strip markdown markers if present
    text = response.text.strip()
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(0))
    return json.loads(text)

def _process_flow_events(scene, word_ms, img_path, find_ms_func) -> list:
    events = []
    try:
        prompt = (
            "Analyze this process flow diagram. Identify all rectangular nodes or process steps from left to right "
            "or top to bottom in the order they connect. For each node return: id (string), label (the text inside the node), "
            "x_pct (left edge as fraction 0.0-1.0 of image width), y_pct (top edge as fraction 0.0-1.0), "
            "w_pct (width fraction), h_pct (height fraction), trigger_keyword (the single most important word "
            "a teacher would say when explaining this step — must be a simple common English word). "
            "For each arrow connecting nodes return: from_id, to_id, label (optional text on arrow). "
            "Return ONLY valid JSON: {\"nodes\": [{\"id\":\"...\",\"label\":\"...\",\"x_pct\":0.0,\"y_pct\":0.0,\"w_pct\":0.0,\"h_pct\":0.0,\"trigger_keyword\":\"...\"}], \"arrows\": [{\"from_id\":\"...\",\"to_id\":\"...\",\"label\":\"...\"}]}"
        )
        data = _call_gemini_vision(img_path, prompt)
        nodes = data.get("nodes", [])
        arrows = data.get("arrows", [])

        # Add diagram overview establishing shot at 400ms
        events.append({
            "event_type": "diagram_overview",
            "timestamp_ms": 400,
            "data": {}
        })

        for idx, node in enumerate(nodes):
            trigger_keyword = node.get("trigger_keyword", "")
            trigger_ms = find_ms_func(trigger_keyword, idx, fallback_base=2500, spacing=3500)
            
            bbox = {
                "x_pct": node.get("x_pct", 0.0),
                "y_pct": node.get("y_pct", 0.0),
                "w_pct": node.get("w_pct", 0.2),
                "h_pct": node.get("h_pct", 0.2)
            }

            # diagram_cursor_move at trigger_ms - 600
            events.append({
                "event_type": "diagram_cursor_move",
                "timestamp_ms": max(100, trigger_ms - 600),
                "data": {"region": bbox}
            })

            # diagram_zoom_in at trigger_ms - 400
            events.append({
                "event_type": "diagram_zoom_in",
                "timestamp_ms": max(150, trigger_ms - 400),
                "data": {"region": bbox, "zoom_scale": 2.1, "hold_ms": 2800, "annotation_color": "#00E5FF"}
            })

            # diagram_annotate_circle at trigger_ms
            events.append({
                "event_type": "diagram_annotate_circle",
                "timestamp_ms": trigger_ms,
                "data": {"region": bbox, "annotation_color": "#00E5FF"}
            })

            # Find matching outgoing arrow from this node
            for arrow in arrows:
                if arrow.get("from_id") == node.get("id"):
                    to_node = next((n for n in nodes if n.get("id") == arrow.get("to_id")), None)
                    if to_node:
                        to_bbox = {
                            "x_pct": to_node.get("x_pct", 0.0),
                            "y_pct": to_node.get("y_pct", 0.0),
                            "w_pct": to_node.get("w_pct", 0.2),
                            "h_pct": to_node.get("h_pct", 0.2)
                        }
                        # diagram_flow_arrow at trigger_ms + 1600
                        events.append({
                            "event_type": "diagram_flow_arrow",
                            "timestamp_ms": trigger_ms + 1600,
                            "data": {
                                "from_region": bbox,
                                "to_region": to_bbox,
                                "label": arrow.get("label", ""),
                                "annotation_color": "#FFD700"
                            }
                        })

            # diagram_zoom_out at trigger_ms + 2800
            events.append({
                "event_type": "diagram_zoom_out",
                "timestamp_ms": trigger_ms + 2800,
                "data": {}
            })

    except Exception as e:
        print("[AnimationBrain PROCESS_FLOW Error]", e)
    return events

def _cause_effect_events(scene, word_ms, img_path, find_ms_func) -> list:
    events = []
    try:
        prompt = (
            "Analyze this cause and effect diagram. Identify the CAUSE element (usually on left or top) "
            "and the EFFECT element (usually on right or bottom) and any connecting arrow between them. "
            "Return ONLY JSON: {\"cause\": {\"label\":\"...\", \"x_pct\":0.0, \"y_pct\":0.0, \"w_pct\":0.0, \"h_pct\":0.0, \"trigger_keyword\":\"...\"}, "
            "\"effect\": {\"label\":\"...\", \"x_pct\":0.0, \"y_pct\":0.0, \"w_pct\":0.0, \"h_pct\":0.0, \"trigger_keyword\":\"...\"}, \"has_arrow\": true}"
        )
        data = _call_gemini_vision(img_path, prompt)
        cause = data.get("cause", {})
        effect = data.get("effect", {})

        cause_kw = cause.get("trigger_keyword", "")
        effect_kw = effect.get("trigger_keyword", "")

        cause_trigger_ms = find_ms_func(cause_kw, 0, fallback_base=2500, spacing=4000)
        effect_trigger_ms = find_ms_func(effect_kw, 1, fallback_base=6500, spacing=4000)

        # Enforce cron order
        if effect_trigger_ms <= cause_trigger_ms + 2000:
            effect_trigger_ms = cause_trigger_ms + 4000

        cause_bbox = {
            "x_pct": cause.get("x_pct", 0.1), "y_pct": cause.get("y_pct", 0.1),
            "w_pct": cause.get("w_pct", 0.3), "h_pct": cause.get("h_pct", 0.3)
        }
        effect_bbox = {
            "x_pct": effect.get("x_pct", 0.5), "y_pct": effect.get("y_pct", 0.1),
            "w_pct": effect.get("w_pct", 0.3), "h_pct": effect.get("h_pct", 0.3)
        }

        # diagram_overview at 300ms
        events.append({
            "event_type": "diagram_overview",
            "timestamp_ms": 300,
            "data": {}
        })

        # Cause Zoom-in
        events.append({
            "event_type": "diagram_zoom_in",
            "timestamp_ms": max(150, cause_trigger_ms - 400),
            "data": {"region": cause_bbox, "zoom_scale": 2.0, "hold_ms": 2200, "annotation_color": "#FF4444"}
        })

        # Cause Highlight Red
        events.append({
            "event_type": "diagram_highlight_region",
            "timestamp_ms": cause_trigger_ms,
            "data": {"region": cause_bbox, "annotation_color": "#FF4444"}
        })

        # Cause Zoom-out
        events.append({
            "event_type": "diagram_zoom_out",
            "timestamp_ms": cause_trigger_ms + 2200,
            "data": {}
        })

        # Arrow leading to effect
        if data.get("has_arrow", True):
            events.append({
                "event_type": "diagram_flow_arrow",
                "timestamp_ms": cause_trigger_ms + 2600,
                "data": {"from_region": cause_bbox, "to_region": effect_bbox, "label": "leads to", "annotation_color": "#FFD700"}
            })

        # Effect Zoom-in
        events.append({
            "event_type": "diagram_zoom_in",
            "timestamp_ms": effect_trigger_ms - 400,
            "data": {"region": effect_bbox, "zoom_scale": 2.0, "hold_ms": 2200, "annotation_color": "#44FF88"}
        })

        # Effect Highlight Green
        events.append({
            "event_type": "diagram_highlight_region",
            "timestamp_ms": effect_trigger_ms,
            "data": {"region": effect_bbox, "annotation_color": "#44FF88"}
        })

        # Effect Zoom-out
        events.append({
            "event_type": "diagram_zoom_out",
            "timestamp_ms": effect_trigger_ms + 2200,
            "data": {}
        })

    except Exception as e:
        print("[AnimationBrain CAUSE_EFFECT Error]", e)
    return events

def _spatial_diagram_events(scene, word_ms, img_path, find_ms_func) -> list:
    events = []
    try:
        prompt = (
            "You are an expert teacher analyzing an educational diagram. Identify all distinct labeled visual elements "
            "(boxes, nodes, organs, components, labels, zones — anything with a visible label or clear boundary). "
            "List them in the PEDAGOGICAL order a teacher would explain them — simplest/most fundamental first, "
            "complex/dependent later. For each element: id, label, x_pct, y_pct, w_pct, h_pct (all as 0.0-1.0 fractions "
            "of image dimensions), trigger_keyword (single word teacher says when discussing this), "
            "annotation_type (circle for important nodes, highlight_box for regions/zones). "
            "Also identify any flow connections between elements. Return ONLY JSON: "
            "{\"regions\": [{\"id\":\"...\",\"label\":\"...\",\"x_pct\":0.0,\"y_pct\":0.0,\"w_pct\":0.0,\"h_pct\":0.0,\"trigger_keyword\":\"...\",\"annotation_type\":\"...\"}], "
            "\"connections\": [{\"from_id\":\"...\",\"to_id\":\"...\",\"label\":\"...\"}]}"
        )
        data = _call_gemini_vision(img_path, prompt)
        regions = data.get("regions", [])
        connections = data.get("connections", [])

        # diagram_overview at 300ms
        events.append({
            "event_type": "diagram_overview",
            "timestamp_ms": 300,
            "data": {}
        })

        last_zoom_end = 500

        for idx, region in enumerate(regions):
            keyword = region.get("trigger_keyword", "")
            trigger_ms = find_ms_func(keyword, idx, fallback_base=2500, spacing=4000)

            # Avoid overlapping sequences
            if trigger_ms < last_zoom_end + 500:
                trigger_ms = last_zoom_end + 500

            bbox = {
                "x_pct": region.get("x_pct", 0.0),
                "y_pct": region.get("y_pct", 0.0),
                "w_pct": region.get("w_pct", 0.25),
                "h_pct": region.get("h_pct", 0.25)
            }

            # smaller width = higher zoom scale
            w_pct = bbox["w_pct"]
            scale = min(3.2, max(2.0, 0.15 / w_pct if w_pct > 0 else 0.15))

            # cursor move at trigger_ms - 700
            events.append({
                "event_type": "diagram_cursor_move",
                "timestamp_ms": max(100, trigger_ms - 700),
                "data": {"region": bbox}
            })

            # zoom-in at trigger_ms - 400
            events.append({
                "event_type": "diagram_zoom_in",
                "timestamp_ms": max(150, trigger_ms - 400),
                "data": {"region": bbox, "zoom_scale": scale, "hold_ms": 3000, "annotation_color": "#00E5FF"}
            })

            # Draw circle or highlight
            color = "#00E5FF" if region.get("annotation_type") == "circle" else "#FF4444"
            ann_type = "diagram_annotate_circle" if region.get("annotation_type") == "circle" else "diagram_highlight_region"
            events.append({
                "event_type": ann_type,
                "timestamp_ms": trigger_ms,
                "data": {"region": bbox, "annotation_color": color}
            })

            # zoom-out at trigger_ms + 3000
            events.append({
                "event_type": "diagram_zoom_out",
                "timestamp_ms": trigger_ms + 3000,
                "data": {}
            })

            last_zoom_end = trigger_ms + 3000

        # Connections flow arrows
        current_conn_ms = last_zoom_end + 500
        for conn in connections:
            from_reg = next((r for r in regions if r.get("id") == conn.get("from_id")), None)
            to_reg = next((r for r in regions if r.get("id") == conn.get("to_id")), None)
            if from_reg and to_reg:
                from_bbox = {
                    "x_pct": from_reg.get("x_pct", 0.0), "y_pct": from_reg.get("y_pct", 0.0),
                    "w_pct": from_reg.get("w_pct", 0.2), "h_pct": from_reg.get("h_pct", 0.2)
                }
                to_bbox = {
                    "x_pct": to_reg.get("x_pct", 0.0), "y_pct": to_reg.get("y_pct", 0.0),
                    "w_pct": to_reg.get("w_pct", 0.2), "h_pct": to_reg.get("h_pct", 0.2)
                }
                events.append({
                    "event_type": "diagram_flow_arrow",
                    "timestamp_ms": current_conn_ms,
                    "data": {"from_region": from_bbox, "to_region": to_bbox, "label": conn.get("label", ""), "annotation_color": "#FFD700"}
                })
                current_conn_ms += 1000

    except Exception as e:
        print("[AnimationBrain SPATIAL Error]", e)
    return events

def _formula_events(scene, word_ms, f_img_path, find_ms_func) -> list:
    events = []
    try:
        narration = scene.get("narration", "")
        
        # If no formula image exists, construct manual fallback steps or run standard Gemini Vision on formula if we have it
        if f_img_path:
            prompt = (
                f"You are a math teacher. Analyze this formula image. Break it down into 3-5 teaching steps "
                f"where each step reveals understanding of one part of the formula. Use this narration context: \"{narration}\". "
                f"For each step provide: step_index (0-based), latex (the LaTeX string for the part being explained — use standard LaTeX), "
                f"explanation (one plain English sentence explaining what this part means), trigger_keyword (the English word a teacher "
                f"would say when explaining this part — must be from typical math narration vocabulary like 'energy', 'mass', "
                f"'velocity', 'equals', 'therefore', 'squared', 'sum', 'integral'). Return ONLY JSON: "
                "{\"formula_title\": \"...\", \"steps\": [{\"step_index\": 0, \"latex\": \"...\", \"explanation\": \"...\", \"trigger_keyword\": \"...\"}]}"
            )
            data = _call_gemini_vision(f_img_path, prompt)
            steps = data.get("steps", [])
        else:
            # Fallback when no formula path exists: create standard steps based on formula_refs string or table/scene
            formulas = scene.get("formula_refs", ["E = mc^2"])
            steps = [
                {"step_index": 0, "latex": formulas[0], "explanation": "This represents our primary mathematical relation.", "trigger_keyword": "equals"}
            ]

        colors = ["#FFD700", "#00E5FF", "#FF4444", "#44FF88"]
        for idx, step in enumerate(steps):
            kw = step.get("trigger_keyword", "")
            trigger_ms = find_ms_func(kw, idx, fallback_base=2000, spacing=4000)

            # formula_step_reveal
            events.append({
                "event_type": "formula_step_reveal",
                "timestamp_ms": trigger_ms,
                "data": {
                    "step_index": step.get("step_index", idx),
                    "latex": step.get("latex", ""),
                    "explanation": step.get("explanation", "")
                }
            })

            # formula_term_highlight at trigger_ms + 400
            events.append({
                "event_type": "formula_term_highlight",
                "timestamp_ms": trigger_ms + 400,
                "data": {
                    "term": step.get("latex", ""),
                    "color": colors[idx % len(colors)]
                }
            })

    except Exception as e:
        print("[AnimationBrain FORMULA Error]", e)
    return events

def _table_events(scene, word_ms, find_ms_func) -> list:
    events = []
    try:
        table_data = scene.get("table_data", {})
        headers = table_data.get("headers", [])
        rows = table_data.get("rows", [])
        narration = scene.get("narration", "")

        # Ask Gemini (text only)
        prompt = (
            f"You are a teacher preparing a slideshow. I have a data table with these headers: {headers} "
            f"and these rows: {rows}.\nI will be explaining this table using the following narration: \"{narration}\".\n"
            f"Identify which rows, columns, or specific cells are most important for a teacher to highlight, "
            f"and align them chronologically with trigger keywords from the narration. "
            f"Return a sequence of highlights in exact order. ONLY JSON: "
            f"{{\"teaching_sequence\": [ {{\"type\": \"row\", \"index\": 1, \"trigger_keyword\": \"...\", \"color\": \"#00E5FF\", \"reason\": \"...\"}}, "
            f"{{\"type\": \"column\", \"index\": 0, \"trigger_keyword\": \"...\", \"color\": \"#FFD700\"}}, "
            f"{{\"type\": \"cell\", \"row_index\": 0, \"col_index\": 1, \"trigger_keyword\": \"...\", \"color\": \"#44FF88\"}} ]}}"
        )
        
        response = _model.generate_content(prompt)
        text = response.text.strip()
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(json_match.group(0)) if json_match else json.loads(text)
        sequence = data.get("teaching_sequence", [])

        for idx, item in enumerate(sequence):
            kw = item.get("trigger_keyword", "")
            trigger_ms = find_ms_func(kw, idx, fallback_base=2500, spacing=3500)

            hl_type = item.get("type", "row")
            color = item.get("color", "#00E5FF")

            if hl_type == "row":
                events.append({
                    "event_type": "table_row_focus",
                    "timestamp_ms": trigger_ms,
                    "data": {"row_index": item.get("index", 0), "color": color}
                })
            elif hl_type == "column":
                events.append({
                    "event_type": "table_column_highlight",
                    "timestamp_ms": trigger_ms,
                    "data": {"col_index": item.get("index", 0), "color": color}
                })
            elif hl_type == "cell":
                events.append({
                    "event_type": "table_cell_spotlight",
                    "timestamp_ms": trigger_ms,
                    "data": {"row_index": item.get("row_index", 0), "col_index": item.get("col_index", 0), "color": color}
                })

    except Exception as e:
        print("[AnimationBrain TABLE Error]", e)
    return events
