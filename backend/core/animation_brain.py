import os
import json
import base64
import string
import google.generativeai as genai

# Lazy-load API key from pydantic-settings (loads .env) with os.getenv fallback
def _get_gemini_key():
    try:
        from app.config import settings as app_settings
        return getattr(app_settings, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
    except ImportError:
        return os.getenv("GEMINI_API_KEY", "")

_gemini_key = _get_gemini_key()
if _gemini_key:
    genai.configure(api_key=_gemini_key)
_gemini_model = genai.GenerativeModel("gemini-2.0-flash")

def generate_animation_script(
    scene: dict,
    word_timestamps: list,
    diagram_image_path: str = None
) -> list:
    try:
        # Step 1: Guard checks
        if diagram_image_path is None or not os.path.exists(diagram_image_path) or not word_timestamps:
            return []

        # Step 2: Build the full transcript for context-aware analysis
        full_transcript = " ".join([wt.get("word", "") for wt in word_timestamps])

        def get_phrase_ms(phrase, element_index):
            """Finds the exact start_ms of a phrase in the word_timestamps."""
            fallback_ms = (element_index * 3500) + 2000
            if not phrase:
                return fallback_ms
                
            phrase_words = phrase.lower().split()
            if not phrase_words:
                return fallback_ms
                
            # Sequence matching algorithm
            for i in range(len(word_timestamps)):
                match = True
                for j in range(len(phrase_words)):
                    if i + j >= len(word_timestamps):
                        match = False
                        break
                    
                    wt_word = word_timestamps[i+j].get("word", "").lower().translate(str.maketrans('', '', string.punctuation))
                    p_word = phrase_words[j].translate(str.maketrans('', '', string.punctuation))
                    
                    if p_word not in wt_word and wt_word not in p_word:
                        match = False
                        break
                
                if match:
                    return word_timestamps[i].get("start_ms", 0)
            
            # If exact phrase not found, try finding the most unique word in the phrase
            longest_word = max(phrase_words, key=len).translate(str.maketrans('', '', string.punctuation))
            if len(longest_word) > 3:
                for wt in word_timestamps:
                    wt_w = wt.get("word", "").lower().translate(str.maketrans('', '', string.punctuation))
                    if longest_word in wt_w or wt_w in longest_word:
                        return wt.get("start_ms", 0)

            return fallback_ms

        # Step 3: Get the scene DNA type
        dna_type = scene.get("scene_dna", {}).get("dna_type", "DIAGRAM_SPATIAL")

        # Step 4: Call Gemini Vision with Transcript Context
        transcript_context = f"\n\nHere is the exact spoken transcript of the teacher explaining this diagram:\n\"{full_transcript}\"\n\n"

        if dna_type == "PROCESS_FLOW":
            prompt = transcript_context + "You are analyzing an educational process flow diagram. Identify all process step nodes from left to right or top to bottom. For each node return its label, bounding box as percentages, AND identify the EXACT continuous phrase (2-5 words) from the provided transcript where the teacher first introduces or focuses on this specific step. Also identify all arrows connecting nodes. Return ONLY this JSON: { \"nodes\": [{\"id\": \"n1\", \"label\": \"...\", \"x_pct\": 0.0, \"y_pct\": 0.0, \"w_pct\": 0.0, \"h_pct\": 0.0, \"exact_transcript_phrase\": \"...\", \"teaching_order\": 1}], \"connections\": [{\"from_id\": \"n1\", \"to_id\": \"n2\", \"label\": \"...\"}] }"
        elif dna_type == "CAUSE_EFFECT":
            prompt = transcript_context + "You are analyzing an educational cause-and-effect diagram. Identify the cause element (left or top) and the effect element (right or bottom) and any connecting arrow. For both cause and effect, identify the EXACT continuous phrase (2-5 words) from the provided transcript where the teacher discusses them. Return ONLY this JSON: { \"cause\": {\"label\": \"...\", \"x_pct\": 0.0, \"y_pct\": 0.0, \"w_pct\": 0.0, \"h_pct\": 0.0, \"exact_transcript_phrase\": \"...\"}, \"effect\": {\"label\": \"...\", \"x_pct\": 0.0, \"y_pct\": 0.0, \"w_pct\": 0.0, \"h_pct\": 0.0, \"exact_transcript_phrase\": \"...\"}, \"connection_exists\": true }"
        else: # DIAGRAM_SPATIAL
            prompt = transcript_context + "You are analyzing an educational diagram with multiple labeled regions. Identify all distinct labeled elements (nodes, boxes, components, labels). Return them in the pedagogical order a teacher explains them based on the transcript. For each region, extract the EXACT continuous phrase (2-5 words) from the transcript where the teacher introduces it. Return ONLY this JSON: { \"regions\": [{\"id\": \"r1\", \"label\": \"...\", \"x_pct\": 0.0, \"y_pct\": 0.0, \"w_pct\": 0.0, \"h_pct\": 0.0, \"exact_transcript_phrase\": \"...\", \"annotation_type\": \"circle\"}], \"flow_connections\": [{\"from_id\": \"r1\", \"to_id\": \"r2\", \"label\": \"...\"}] } where annotation_type is circle for important nodes or highlight_box for zones."

        with open(diagram_image_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode()

        response = _gemini_model.generate_content([
            {"mime_type": "image/png", "data": img_data},
            prompt
        ])

        # Step 5: Parse JSON
        try:
            text = response.text
            import re
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                parsed_json = json.loads(match.group())
            else:
                parsed_json = json.loads(text)
        except Exception as e:
            print(f"[AnimationBrain] JSON parsing failed: {e}")
            return []

        events = []

        # Step 6 & 7: Match precise phrases and generate events
        if dna_type == "PROCESS_FLOW":
            nodes = parsed_json.get("nodes", [])
            nodes = sorted(nodes, key=lambda x: x.get("teaching_order", 0))
            connections = parsed_json.get("connections", [])
            
            for i, node in enumerate(nodes):
                phrase = node.get("exact_transcript_phrase", "")
                trigger_ms = get_phrase_ms(phrase, i)
                bbox = {
                    "x_pct": node.get("x_pct", 0), "y_pct": node.get("y_pct", 0),
                    "w_pct": node.get("w_pct", 0), "h_pct": node.get("h_pct", 0)
                }
                
                # Millisecond accurate panning
                events.append({
                    "event_type": "process_flow_pan",
                    "start_ms": max(200, trigger_ms - 200),
                    "data": {"region": bbox, "zoom_scale": 1.8, "hold_ms": 3000}
                })
                # Flow arrows perfectly timed
                for conn in connections:
                    if conn.get("from_id") == node.get("id"):
                        next_node = next((n for n in nodes if n.get("id") == conn.get("to_id")), None)
                        if next_node:
                            next_bbox = {
                                "x_pct": next_node.get("x_pct", 0), "y_pct": next_node.get("y_pct", 0),
                                "w_pct": next_node.get("w_pct", 0), "h_pct": next_node.get("h_pct", 0)
                            }
                            # Calculate distance to next node trigger for arrow timing
                            next_phrase = next_node.get("exact_transcript_phrase", "")
                            next_ms = get_phrase_ms(next_phrase, i+1)
                            arrow_ms = trigger_ms + 1200 # Default if next_ms is too far
                            if next_ms > trigger_ms and (next_ms - trigger_ms) < 4000:
                                arrow_ms = next_ms - 600 # Flow arrow 600ms before next node
                            
                            events.append({
                                "event_type": "flow_arrow_draw",
                                "start_ms": arrow_ms,
                                "data": {"from_region": bbox, "to_region": next_bbox, "label": conn.get("label", "")}
                            })
                
                # Zoom out gracefully if needed
                events.append({
                    "event_type": "diagram_zoom_out",
                    "start_ms": trigger_ms + 2800,
                    "data": {}
                })

        elif dna_type == "CAUSE_EFFECT":
            cause = parsed_json.get("cause", {})
            effect = parsed_json.get("effect", {})
            
            c_phrase = cause.get("exact_transcript_phrase", "")
            e_phrase = effect.get("exact_transcript_phrase", "")
            
            c_trigger_ms = get_phrase_ms(c_phrase, 0)
            e_trigger_ms = get_phrase_ms(e_phrase, 1)
            
            # Ensure chronological order
            if e_trigger_ms < c_trigger_ms + 1000:
                e_trigger_ms = c_trigger_ms + 2000
            
            c_bbox = {"x_pct": cause.get("x_pct",0), "y_pct": cause.get("y_pct",0), "w_pct": cause.get("w_pct",0), "h_pct": cause.get("h_pct",0)}
            e_bbox = {"x_pct": effect.get("x_pct",0), "y_pct": effect.get("y_pct",0), "w_pct": effect.get("w_pct",0), "h_pct": effect.get("h_pct",0)}
            
            events.append({
                "event_type": "process_flow_pan",
                "start_ms": max(100, c_trigger_ms - 200),
                "data": {"region": c_bbox, "zoom_scale": 1.8, "hold_ms": e_trigger_ms - c_trigger_ms}
            })
            events.append({
                "event_type": "cause_highlight",
                "start_ms": c_trigger_ms,
                "data": {"region": c_bbox, "annotation_color": "#FF4444"}
            })
            
            if parsed_json.get("connection_exists"):
                events.append({
                    "event_type": "dramatic_arrow",
                    "start_ms": c_trigger_ms + 1000,
                    "data": {"from_region": c_bbox, "to_region": e_bbox, "label": "causes"}
                })
                
            events.append({
                "event_type": "process_flow_pan",
                "start_ms": max(100, e_trigger_ms - 200),
                "data": {"region": e_bbox, "zoom_scale": 1.8, "hold_ms": 2500}
            })
            events.append({
                "event_type": "effect_reveal",
                "start_ms": e_trigger_ms,
                "data": {"region": e_bbox, "annotation_color": "#44FF88"}
            })
            events.append({
                "event_type": "diagram_zoom_out",
                "start_ms": e_trigger_ms + 2500,
                "data": {}
            })

        else: # DIAGRAM_SPATIAL
            regions = parsed_json.get("regions", [])
            flow_connections = parsed_json.get("flow_connections", [])
            
            # Sort regions strictly by their trigger timestamp so camera moves naturally
            for i, reg in enumerate(regions):
                reg["_trigger_ms"] = get_phrase_ms(reg.get("exact_transcript_phrase", ""), i)
            regions = sorted(regions, key=lambda r: r["_trigger_ms"])
            
            for i, reg in enumerate(regions):
                trigger_ms = reg["_trigger_ms"]
                bbox = {"x_pct": reg.get("x_pct",0), "y_pct": reg.get("y_pct",0), "w_pct": reg.get("w_pct",0), "h_pct": reg.get("h_pct",0)}
                
                if i == 0:
                    events.append({
                        "event_type": "diagram_overview",
                        "start_ms": 500,
                        "data": {}
                    })
                
                center_coords = {
                    "x_pct": bbox["x_pct"] + bbox["w_pct"]/2,
                    "y_pct": bbox["y_pct"] + bbox["h_pct"]/2,
                    "w_pct": 0, "h_pct": 0
                }
                
                # Move cursor a bit before zooming
                events.append({
                    "event_type": "diagram_cursor_move",
                    "start_ms": max(0, trigger_ms - 400),
                    "data": {"region": center_coords}
                })
                events.append({
                    "event_type": "sequential_zoom_per_region",
                    "start_ms": max(0, trigger_ms - 150),
                    "data": {"region": bbox, "zoom_scale": 2.4, "hold_ms": 2500}
                })
                
                ann_type = reg.get("annotation_type", "circle")
                ev_type = "diagram_annotate_circle" if ann_type == "circle" else "diagram_highlight_region"
                
                events.append({
                    "event_type": ev_type,
                    "start_ms": trigger_ms,
                    "data": {"region": bbox, "annotation_color": "#00E5FF" if ann_type=="circle" else "#FF4444"}
                })
                events.append({
                    "event_type": "diagram_zoom_out",
                    "start_ms": trigger_ms + 2500,
                    "data": {}
                })
            
            for conn in flow_connections:
                from_reg = next((r for r in regions if r.get("id") == conn.get("from_id")), None)
                to_reg = next((r for r in regions if r.get("id") == conn.get("to_id")), None)
                if from_reg and to_reg:
                    f_bbox = {"x_pct": from_reg.get("x_pct",0), "y_pct": from_reg.get("y_pct",0), "w_pct": from_reg.get("w_pct",0), "h_pct": from_reg.get("h_pct",0)}
                    t_bbox = {"x_pct": to_reg.get("x_pct",0), "y_pct": to_reg.get("y_pct",0), "w_pct": to_reg.get("w_pct",0), "h_pct": to_reg.get("h_pct",0)}
                    
                    # Exact time the arrow should appear (midway between from and to)
                    conn_ms = from_reg["_trigger_ms"] + 1200
                    if to_reg["_trigger_ms"] > from_reg["_trigger_ms"]:
                        conn_ms = from_reg["_trigger_ms"] + (to_reg["_trigger_ms"] - from_reg["_trigger_ms"]) // 2
                        
                    events.append({
                        "event_type": "diagram_flow_arrow",
                        "start_ms": conn_ms,
                        "data": {"from_region": f_bbox, "to_region": t_bbox, "label": conn.get("label", "")}
                    })

        # Step 8: Apply Cognitive Load Rules (Clean up overlapping animations)
        events.sort(key=lambda x: x.get("start_ms", 0))
        
        # Ensure no harsh camera cuts within 600ms of each other
        for i in range(1, len(events)):
            if events[i].get("start_ms", 0) - events[i-1].get("start_ms", 0) < 600:
                # If they are both zooms/pans, delay the second one slightly
                if any(k in events[i]["event_type"] for k in ["zoom", "pan"]) and any(k in events[i-1]["event_type"] for k in ["zoom", "pan"]):
                    events[i]["start_ms"] = events[i-1].get("start_ms", 0) + 700

        # Bullet collision check
        bullets = scene.get("bullets", [])
        bullet_ms_list = []
        for b in bullets:
            if isinstance(b, dict):
                tw = b.get("trigger_word", "")
                bullet_ms_list.append(get_phrase_ms(tw, 0))
                
        _CAMERA_EVENTS = {"diagram_zoom_in", "process_flow_pan", "sequential_zoom_per_region"}
        for ev in events:
            if ev["event_type"] in _CAMERA_EVENTS:
                for b_ms in bullet_ms_list:
                    if abs(ev.get("start_ms", 0) - b_ms) < 400:
                        ev["start_ms"] = ev.get("start_ms", 0) + 500

        events.sort(key=lambda x: x.get("start_ms", 0))
        
        # Conform to timeline_builder expected format
        for ev in events:
            if "end_ms" not in ev:
                ev["end_ms"] = ev.get("start_ms", 0) + ev.get("data", {}).get("hold_ms", 1000)

        return events

    except Exception as e:
        print(f"[AnimationBrain] Error generating accurate script: {e}")
        return []
