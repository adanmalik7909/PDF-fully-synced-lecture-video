# -*- coding: utf-8 -*-
"""
SmartStudyInstructor V10 — Timeline Builder
The brain of the sync system. Takes TTS word timestamps + Blueprint scene
and produces a Master Timeline JSON where every visual event has an exact start_ms.
"""
import re
import os
import json
from typing import List, Dict, Optional


class TimelineBuilder:
    """
    Builds the Master Timeline JSON for one scene.

    Usage:
        builder = TimelineBuilder(scene=scene_dict, words=word_list, total_ms=14200)
        timeline = builder.build()  # → list of event dicts sorted by start_ms
    """

    def __init__(self, scene: Dict, words: List[Dict], total_ms: float):
        self.scene    = scene
        self.words    = words
        self.total_ms = total_ms
        self._used_indices: set = set()  # prevent reusing the same word occurrence

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def build(self) -> Dict:
        """Return the full Master Timeline JSON for this scene."""
        events = []

        events += self._scene_start()
        events += self._heading_focus()
        events += self._ken_burns()
        events += self._bullets()
        events += self._subtitles()
        events += self._zoom_words()
        events += self._diagram()
        events += self._takeaway()
        events += self._scene_end()
        events += self._spatial_actions()
        events += self._heading_actions()
        events += self._attention_hooks()
        events += self._teacher_draw_events()
        events += self._diagram_flow_events()
        events += self._component_highlight_events()
        events += self._diagram_teaching_sequence()
        events += self._shot_plan_events()
        events += self._formula_steps()
        events += self._table_focus_events()
        
        # UPGRADE A: Cursor Grounding System
        if self.scene.get("diagram_data"):
            cursor_events = self.generate_cursor_events(self.scene.get("diagram_data", {}), self.words)
            events += cursor_events

        # NOTE: AnimationBrain is invoked in blueprint_pipeline._build_scene()
        # after build(). Do NOT call it here to avoid duplicate animation events.

        # V13: Cognitive Load Optimization (resolve conflicts, add breathe moments)
        events = self._optimize_cognitive_load(events)

        # ── Animation Brain: Intelligent diagram events ─────────────
        if self.scene.get("diagram_refs") and len(self.scene["diagram_refs"]) > 0:
            from core.animation_brain import generate_animation_script
            primary_diagram_path = self.scene["diagram_refs"][0]
            
            # Make sure we find the existing file path
            actual_path = None
            candidates = [
                primary_diagram_path,
                os.path.join("backend", primary_diagram_path) if not primary_diagram_path.startswith("backend") else primary_diagram_path,
                os.path.join("static/uploads/diagrams", os.path.basename(str(primary_diagram_path))),
                os.path.join("backend/static/uploads/diagrams", os.path.basename(str(primary_diagram_path))),
            ]
            for cand in candidates:
                if cand and os.path.exists(cand):
                    actual_path = cand
                    break
                    
            if actual_path:
                brain_events = generate_animation_script(
                    scene=self.scene,
                    word_timestamps=self.words,
                    diagram_image_path=actual_path
                )
                events.extend(brain_events)
        # ─────────────────────────────────────────────────────────────

        # Sort by start_ms
        events.sort(key=lambda e: e["start_ms"])

        return {
            "scene_id":          self.scene.get("scene_id"),
            "total_duration_ms": self.total_ms,
            "audio_path":        self.scene.get("_audio_path", ""),
            "events":            events,
        }

    # ──────────────────────────────────────────────────────────────────────
    # Event builders
    # ──────────────────────────────────────────────────────────────────────

    def _scene_start(self) -> List[Dict]:
        return [self._ev(0, 400, "scene_start", {})]

    def _heading_focus(self) -> List[Dict]:
        return [self._ev(200, 3200, "heading_focus", {
            "heading_left":  self.scene.get("heading_left", ""),
            "heading_right": self.scene.get("heading_right", ""),
        })]

    def _ken_burns(self) -> List[Dict]:
        scene_type = self.scene.get("scene_type", "concept")
        kb_map = {
            "intro":         "zoom_in_center",
            "concept":       "pan_right",
            "diagram_focus": "zoom_toward_region",
            "comparison":    "pan_left",
            "process":       "pan_right",
            "summary":       "zoom_out",
        }
        direction = kb_map.get(scene_type, "pan_right")
        return [self._ev(0, self.total_ms, "ken_burns", {"direction": direction})]

    def _bullets(self) -> List[Dict]:
        events = []
        bullets = self.scene.get("bullets", [])
        prev_enter_ms = None

        for i, bullet in enumerate(bullets):
            # Handle legacy string array hallucinations from LLM
            if isinstance(bullet, str):
                bullet = {"text": bullet, "trigger_word": "", "entrance": "slide_left"}
            elif not isinstance(bullet, dict):
                continue
                
            trigger_word = bullet.get("trigger_word", "")
            found_ms = self._find_word_ms(trigger_word) if trigger_word else None

            if found_ms is None:
                # Proportional fallback
                fraction = (i + 1) / max(len(bullets) + 1, 2)
                found_ms = self.total_ms * fraction

            enter_ms  = max(0, found_ms - 100)
            active_ms = enter_ms + 100
            done_ms   = None  # filled when next bullet enters

            # Mark previous bullet as done when this one enters
            if prev_enter_ms is not None and i > 0:
                events.append(self._ev(enter_ms, enter_ms + 200, "bullet_done",
                                       {"index": i - 1}))

            events.append(self._ev(enter_ms, enter_ms + 600, "bullet_enter", {
                "index":    i,
                "entrance": bullet.get("entrance", "slide_left"),
                "text":     bullet.get("text", "")
            }))
            events.append(self._ev(active_ms, active_ms + 400, "bullet_active",
                                   {"index": i}))

            prev_enter_ms = enter_ms

        return events

    def _subtitles(self) -> List[Dict]:
        """Group words into subtitle chunks of 6 + per-word karaoke highlight."""
        events = []
        group_size = 6
        groups = [self.words[i:i+group_size]
                  for i in range(0, len(self.words), group_size)]

        subtitle_idx = 0
        for group in groups:
            if not group:
                continue
            start_ms = group[0]["start_ms"]
            end_ms   = group[-1]["end_ms"]

            events.append(self._ev(start_ms, end_ms, "subtitle_show", {
                "words": [{"word": w["word"],
                           "start_ms": w["start_ms"],
                           "end_ms":   w["end_ms"]} for w in group],
            }))

            for wi, word in enumerate(group):
                events.append(self._ev(
                    word["start_ms"], word["end_ms"],
                    "subtitle_word_hl",
                    {"word": word["word"], "index": wi, "group_idx": subtitle_idx}
                ))

            subtitle_idx += 1

        return events

    # ──────────────────────────────────────────────────────────────────────
    # UPGRADE A: CURSOR GROUNDING SYSTEM
    # ──────────────────────────────────────────────────────────────────────
    def generate_cursor_events(self, diagram_data: Dict, word_timestamps: List[Dict]) -> List[Dict]:
        """
        Uses Groq (LLaMA 3.3 70B) to align diagram elements with spoken words
        and generate cursor_move events. Falls back to empty list on failure.
        """
        cursor_events = []
        if not diagram_data or not word_timestamps:
            return cursor_events

        try:
            from groq import Groq
            # Read from app settings (pydantic-settings loads .env) with os.environ fallback
            try:
                from app.config import settings as app_settings
                api_key = getattr(app_settings, "GROQ_API_KEY", "") or os.environ.get("GROQ_API_KEY", "")
            except ImportError:
                api_key = os.environ.get("GROQ_API_KEY", "")
            if not api_key:
                print("[CursorGrounding] No GROQ_API_KEY set — skipping cursor events")
                return cursor_events

            client = Groq(api_key=api_key)

            # Trim word timestamps to avoid token overflow (send first 200 words max)
            trimmed_words = word_timestamps[:200]

            system_prompt = """You are a spatial-temporal grounding agent for educational videos.
Given spoken word timestamps and diagram element bounding boxes, generate cursor movement events.
Return ONLY a JSON array. Each object must have: event_type, timestamp_ms, element_id, target_x, target_y, label.
The target_x and target_y must be the center of the element's bounding box as normalized floats between 0.0 and 1.0 (e.g. if bbox is x:0.1, y:0.2, w:0.4, h:0.4, center is target_x:0.3, target_y:0.4).
If no elements match, return []. No explanation, no markdown."""

            user_prompt = f"""Words Timeline (first {len(trimmed_words)} words):
{json.dumps(trimmed_words, indent=2)}

Diagram Elements:
{json.dumps(diagram_data, indent=2)}"""

            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=2048,
                temperature=0.3,
            )
            text = resp.choices[0].message.content.strip()

            # Extract JSON block
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            generated_events = json.loads(text.strip())

            for ev in generated_events:
                tx = ev.get("target_x", 0.5)
                ty = ev.get("target_y", 0.5)
                region = {
                    "x_pct": tx - 0.05,
                    "y_pct": ty - 0.05,
                    "w_pct": 0.1,
                    "h_pct": 0.1
                }
                cursor_events.append({
                    "start_ms": ev.get("timestamp_ms", 0),
                    "end_ms": ev.get("timestamp_ms", 0) + 600,
                    "event_type": "diagram_cursor_move",
                    "data": {
                        "region": region,
                        "label": ev.get("label", ""),
                        "element_id": ev.get("element_id", "")
                    }
                })
        except Exception as e:
            # Graceful fallback — no cursor events if Groq fails
            print(f"[CursorGrounding] Groq call failed, skipping: {e}")
            
        return cursor_events


    def _zoom_words(self) -> List[Dict]:
        events = []
        zoom_words = self.scene.get("zoom_words", [])
        # Also pick up zoom_word from each bullet
        for b in self.scene.get("bullets", []):
            if isinstance(b, dict):
                zw = b.get("zoom_word", "")
                if zw and zw not in zoom_words:
                    zoom_words.append(zw)

        for i, zw in enumerate(zoom_words):
            found_ms = self._find_word_ms(zw)
            if found_ms is None:
                continue
            dur_ms = self._word_duration_ms(zw) or 400
            events.append(self._ev(found_ms, found_ms + dur_ms + 200, "zoom_word_glow", {
                "word":       zw,
                "element_id": f"zw_{i}",
            }))

        return events

    def _diagram(self) -> List[Dict]:
        events = []
        scene_type = self.scene.get("scene_type", "concept")

        # Diagram float-in (trigger word or proportional)
        diag_refs = self.scene.get("diagram_refs", []) or (
            [self.scene["diagram_ref"]] if self.scene.get("diagram_ref") else []
        )
        if diag_refs:
            diag_trigger = self.scene.get("diagram_trigger_word", "")
            found_ms = self._find_word_ms(diag_trigger) if diag_trigger else None
            if found_ms is None:
                found_ms = self.total_ms * 0.30  # show diagram after ~30%
            events.append(self._ev(found_ms, found_ms + 600, "diagram_enter", {}))

            # UPGRADE 2: Diagram Zoom and Annotation System
            zoom_in_ms = found_ms + 200
            events.append(self._ev(zoom_in_ms, zoom_in_ms + 1100, "diagram_zoom_in", {}))

            # Find next bullet
            next_bullet_ms = None
            bullets = self.scene.get("bullets", [])
            for b in bullets:
                if isinstance(b, dict):
                    tw = b.get("trigger_word", "")
                    b_ms = self._find_word_ms(tw) if tw else None
                    if b_ms is not None and b_ms > zoom_in_ms:
                        if next_bullet_ms is None or b_ms < next_bullet_ms:
                            next_bullet_ms = b_ms

            if next_bullet_ms is not None and next_bullet_ms > zoom_in_ms + 500:
                zoom_out_ms = next_bullet_ms - 500
            else:
                zoom_out_ms = zoom_in_ms + 4500

            events.append(self._ev(zoom_out_ms, zoom_out_ms + 1000, "diagram_zoom_out", {}))

            # ── V12: Diagram Walkthrough Chain ──────────────────────
            # Process visual_events as a choreographed sequence
            visual_events = self.scene.get("visual_events", [])
            valid_visuals = [v for v in visual_events if isinstance(v, dict)]

            if valid_visuals:
                # Step through each visual event with proper timing
                last_event_end = found_ms + 800  # start after diagram entrance

                for vi, vevent in enumerate(valid_visuals):
                    tw = vevent.get("trigger_word", "")
                    cms = self._find_word_ms(tw) if tw else None
                    if cms is None:
                        cms = last_event_end + 300  # 300ms gap between events

                    action = vevent.get("action", "highlight_and_zoom")
                    coords = vevent.get("target_coords", [0, 0, 1000, 1000])
                    label = vevent.get("label", "")

                    if action == "overview":
                        # Zoom out to show full diagram
                        events.append(self._ev(cms, cms + 2000, "diagram_overview", {
                            "label": label,
                        }))
                        last_event_end = cms + 2000

                    elif action == "highlight_and_zoom":
                        # Pan + Zoom to component
                        duration = 3500
                        events.append(self._ev(cms, cms + duration, "diagram_pan_zoom", {
                            "coords": coords,
                            "label": label,
                            "event_index": vi,
                        }))
                        # Label popup appears 400ms after zoom starts
                        if label:
                            events.append(self._ev(cms + 400, cms + duration - 200, "diagram_label_popup", {
                                "coords": coords,
                                "label": label,
                                "event_index": vi,
                            }))
                        last_event_end = cms + duration

                    elif action == "draw_arrow":
                        from_coords = vevent.get("from_coords", [0, 0, 0, 0])
                        to_coords = vevent.get("to_coords", coords)
                        events.append(self._ev(cms, cms + 2000, "diagram_draw_arrow", {
                            "from_coords": from_coords,
                            "to_coords": to_coords,
                            "label": label,
                        }))
                        last_event_end = cms + 2000

                    elif action == "zoom_out":
                        events.append(self._ev(cms, cms + 1500, "diagram_zoom_out_smooth", {
                            "label": label,
                        }))
                        last_event_end = cms + 1500

                    else:
                        # Generic highlight_and_zoom fallback
                        events.append(self._ev(cms, cms + 3500, "highlight_and_zoom", {
                            "coords": coords,
                            "label": label,
                            "event_index": vi,
                        }))
                        last_event_end = cms + 3500

            elif scene_type == "diagram_focus":
                # Fallback: simple zoom for diagram_focus scenes without visual_events
                zoom_ms = found_ms + 800
                events.append(self._ev(zoom_ms, zoom_ms + 3000, "diagram_zoom", {}))

            # Diagram callout pointers (legacy)
            for ci, callout in enumerate(self.scene.get("diagram_callouts", [])):
                if not isinstance(callout, dict):
                    continue
                tw = callout.get("trigger_word", "")
                cms = self._find_word_ms(tw) if tw else None
                if cms is None:
                    order = callout.get("explanation_order", ci + 1)
                    cms = found_ms + (order * 1500)
                events.append(self._ev(cms, cms + 2500, "diagram_pointer", {
                    "bbox":    callout.get("bbox", [0, 0, 0.2, 0.2]),
                    "label":   callout.get("label", ""),
                    "callout_index": ci,
                }))

        # Analogy overlay
        analogy_trigger = self.scene.get("analogy_trigger_word", "")
        analogy_img_kw  = self.scene.get("analogy_image_keyword", "")
        if analogy_trigger and analogy_img_kw:
            found_ms = self._find_word_ms(analogy_trigger)
            if found_ms is not None:
                events.append(self._ev(found_ms, found_ms + 3000, "analogy_overlay", {
                    "image_url": f"/api/assets/broll?q={analogy_img_kw.replace(' ', '+')}",
                }))

        return events

    def _takeaway(self) -> List[Dict]:
        show_ms = self.total_ms * 0.80
        return [self._ev(show_ms, self.total_ms, "takeaway_show", {
            "text": self.scene.get("takeaway", ""),
        })]

    def _scene_end(self) -> List[Dict]:
        end_ms = max(0, self.total_ms - 500)
        return [self._ev(end_ms, self.total_ms, "scene_end", {})]

    def _spatial_actions(self) -> List[Dict]:
        events = []
        spatial_actions = self.scene.get("spatial_actions", [])
        if not isinstance(spatial_actions, list):
            return events
        for action in spatial_actions:
            if not isinstance(action, dict):
                continue
            trigger = action.get("trigger_word", "")
            occurrence = action.get("trigger_word_occurrence", 1)
            found_ms = self._find_word_ms(trigger, occurrence=occurrence)
            
            if found_ms is not None:
                start_ms = max(0, found_ms - 50)
            else:
                start_ms = self.total_ms * 0.5  # fallback
                
            duration_ms = action.get("duration_ms", 2000)
            events.append(self._ev(start_ms, start_ms + duration_ms, f"spatial_{action.get('action_type', 'zoom_to_component')}", {
                "bbox": action.get("bbox"),
                "zoom_level": action.get("zoom_level", 1.5),
                "target_component_id": action.get("target_component_id"),
                "highlight_color": action.get("highlight_color", "#4F8EF7"),
                "label": action.get("label", ""),
                "duration_ms": duration_ms,
                "from_bbox": action.get("from_bbox"), # for draw_arrow
                "to_bbox": action.get("to_bbox"),     # for draw_arrow
                "row_index": action.get("row_index")  # for table_row_highlight
            }))
        return events

    def _heading_actions(self) -> List[Dict]:
        events = []
        heading_actions = self.scene.get("heading_actions", [])
        if not isinstance(heading_actions, list):
            heading_actions = []

        # Process explicit heading actions from LLM
        for ha in heading_actions:
            if not isinstance(ha, dict):
                continue
            found_ms = self._find_word_ms(ha.get("trigger_word", ""))
            start_ms = found_ms if found_ms is not None else 500
            duration_ms = ha.get("duration_ms", 1500)
            events.append(self._ev(start_ms, start_ms + duration_ms, "heading_action", {
                "action_type": ha.get("action_type", "heading_zoom"),
                "target": ha.get("target", "heading_right"),
                "zoom_level": ha.get("zoom_level", 1.12)
            }))

        # ── V12: Auto-generate heading events if LLM didn't provide any ──
        if not heading_actions:
            heading_right = self.scene.get("heading_right", "")
            if heading_right:
                # Try to find when the heading concept is first mentioned
                first_word = heading_right.split()[0] if heading_right.split() else ""
                found_ms = self._find_word_ms(first_word) if first_word else None
                if found_ms is not None:
                    # Auto heading zoom when first mentioned
                    events.append(self._ev(found_ms, found_ms + 1500, "heading_action", {
                        "action_type": "heading_zoom",
                        "target": "heading_right",
                        "zoom_level": 1.12,
                    }))
                    # Auto heading underline at 60% of scene
                    underline_ms = self.total_ms * 0.6
                    events.append(self._ev(underline_ms, underline_ms + 1200, "heading_action", {
                        "action_type": "heading_underline",
                        "target": "heading_right",
                    }))

        return events

    def _attention_hooks(self) -> List[Dict]:
        events = []
        hooks = self.scene.get("attention_hooks", [])
        if not isinstance(hooks, list):
            return events
        for hook in hooks:
            if not isinstance(hook, dict):
                continue
            found_ms = self._find_word_ms(hook.get("trigger_word", ""))
            start_ms = found_ms if found_ms is not None else self.total_ms * 0.6
            events.append(self._ev(start_ms, start_ms + 3500, "attention_hook", {
                "hook_type": hook.get("hook_type", "did_you_know"),
                "text": hook.get("text", ""),
                "position": hook.get("position", "top-right")
            }))
        return events

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────

    def _ev(self, start_ms: float, end_ms: float,
            event_type: str, data: Dict) -> Dict:
        return {
            "start_ms":   round(start_ms, 1),
            "end_ms":     round(end_ms, 1),
            "event_type": event_type,
            "data":       data,
        }

    def _normalize(self, word: str) -> str:
        return re.sub(r"[^\w]", "", word).lower()

    def _find_word_ms(self, trigger: str, occurrence: int = 1) -> Optional[float]:
        """Find the exact occurrence of trigger in self.words. Case-insensitive."""
        if not trigger or not self.words:
            return None
            
        # Split trigger phrase by space before stripping non-word characters
        trigger_words = trigger.split()
        if not trigger_words:
            return None
            
        first_word = re.sub(r"[^\w]", "", trigger_words[0]).lower()
        if not first_word:
            return None
        
        matches = []
        for i, w in enumerate(self.words):
            if first_word in re.sub(r"[^\w]", "", w["word"]).lower():
                matches.append((i, w["start_ms"]))
                
        if not matches:
            return None
            
        target_idx = min(max(occurrence - 1, 0), len(matches) - 1)
        match_i, match_ms = matches[target_idx]
        self._used_indices.add(match_i)
        return match_ms

    def _word_duration_ms(self, trigger: str) -> Optional[float]:
        """Return duration of first matching word."""
        if not trigger or not self.words:
            return None
        normalized = self._normalize(trigger)
        for w in self.words:
            if normalized in self._normalize(w["word"]):
                return w.get("duration_ms", 400)
        return None

    # ──────────────────────────────────────────────────────────────────────
    # V12.5 — Teacher Draw Events
    # ──────────────────────────────────────────────────────────────────────

    def _teacher_draw_events(self) -> List[Dict]:
        """Convert teacher_draw_actions from blueprint into timeline events."""
        events = []
        draw_actions = self.scene.get("teacher_draw_actions", [])
        if not isinstance(draw_actions, list):
            return events
        for action in draw_actions:
            if not isinstance(action, dict):
                continue
            trigger = action.get("trigger_word", "")
            found_ms = self._find_word_ms(trigger) if trigger else None
            start_ms = found_ms if found_ms is not None else self.total_ms * 0.5
            duration_ms = action.get("duration_ms", 2000)
            action_type = action.get("action_type", "underline")
            events.append(self._ev(start_ms, start_ms + duration_ms,
                f"teacher_{action_type}", {
                    "target_selector": action.get("target_selector", ""),
                    "color": action.get("color", "#C9B99A"),
                    "draw_duration_sec": action.get("draw_duration_sec", 0.6),
                    "bbox": action.get("bbox"),
                    "text": action.get("text", ""),
                    "position_x": action.get("position_x", 0.6),
                    "position_y": action.get("position_y", 0.3),
                    "duration_ms": duration_ms,
                    "from_bbox": action.get("from_bbox"),
                    "to_bbox": action.get("to_bbox"),
                }))
        return events

    def _diagram_flow_events(self) -> List[Dict]:
        """Convert diagram_flow_actions into animated particle events."""
        events = []
        flow_actions = self.scene.get("diagram_flow_actions", [])
        if not isinstance(flow_actions, list):
            return events
        for flow in flow_actions:
            if not isinstance(flow, dict):
                continue
            trigger = flow.get("trigger_word", "")
            found_ms = self._find_word_ms(trigger) if trigger else None
            start_ms = found_ms if found_ms is not None else self.total_ms * 0.4
            duration_ms = flow.get("duration_ms", 1500)
            events.append(self._ev(start_ms, start_ms + duration_ms,
                "diagram_flow_animate", {
                    "from_component": flow.get("from", ""),
                    "to_component": flow.get("to", ""),
                    "path_id": f"flow_{flow.get('from', '')}_{flow.get('to', '')}",
                    "duration_ms": duration_ms,
                    "loop": flow.get("loop", False),
                    "particle_color": flow.get("color", "#4F8EF7"),
                }))
        return events

    def _component_highlight_events(self) -> List[Dict]:
        """Auto-highlight diagram components in teaching sequence."""
        events = []
        components = self.scene.get("diagram_components", [])
        if not isinstance(components, list):
            return events
        sorted_comps = sorted(
            [c for c in components if isinstance(c, dict)],
            key=lambda c: c.get("explanation_order", 99)
        )
        for comp in sorted_comps:
            trigger = comp.get("trigger_keyword", "")
            found_ms = self._find_word_ms(trigger) if trigger else None
            start_ms = found_ms if found_ms is not None else self.total_ms * 0.5
            bbox = comp.get("bbox")
            if not bbox:
                continue
            events.append(self._ev(start_ms, start_ms + 2500,
                "diagram_component_highlight", {
                    "component_id": comp.get("id", ""),
                    "bbox": bbox,
                    "label": comp.get("label", ""),
                    "color": comp.get("highlight_color_hex", "#C9B99A"),
                }))
            # Pointer after highlight
            events.append(self._ev(start_ms + 200, start_ms + 2200,
                "spatial_pointer_to", {
                    "bbox": bbox,
                    "label": comp.get("label", ""),
                }))
        return events

    # ──────────────────────────────────────────────────────────────────────
    # V13 — Diagram 5-Step Teaching Sequence
    # ──────────────────────────────────────────────────────────────────────

    def _diagram_teaching_sequence(self) -> List[Dict]:
        """Convert diagram_teaching_sequence from Blueprint V5 into timed events."""
        events = []
        sequence = self.scene.get("diagram_teaching_sequence", [])
        if not isinstance(sequence, list) or not sequence:
            return events

        # Calculate start time — after diagram enters (~35% into scene)
        base_ms = self.total_ms * 0.35
        cursor_ms = base_ms

        for step in sequence:
            if not isinstance(step, dict):
                continue

            step_type = step.get("step", "")
            duration_sec = step.get("duration_sec", 2.5)
            duration_ms = duration_sec * 1000
            narration_cue = step.get("narration_cue", "")

            # Try to sync with narration using first 2 words of cue
            cue_words = narration_cue.split()[:2]
            synced_ms = None
            for word in cue_words:
                synced_ms = self._find_word_ms(word)
                if synced_ms is not None:
                    break
            start_ms = synced_ms if synced_ms is not None else cursor_ms

            if step_type == "overview":
                # Full diagram zoom-out view
                events.append(self._ev(start_ms, start_ms + duration_ms,
                    "diagram_zoom_reset", {"smooth": True}))

            elif step_type == "entry_point":
                comp_id = step.get("component_id", "")
                events.append(self._ev(start_ms, start_ms + duration_ms,
                    "diagram_component_highlight", {
                        "component_id": comp_id,
                        "bbox": step.get("bbox", [0.1, 0.1, 0.3, 0.3]),
                        "label": comp_id.replace("_", " ").title(),
                        "color": "#FFD700",
                    }))
                events.append(self._ev(start_ms + 200, start_ms + duration_ms - 200,
                    "teacher_circle", {
                        "bbox": step.get("bbox", [0.1, 0.1, 0.3, 0.3]),
                        "color": "#FFD700", "duration_ms": duration_ms,
                    }))

            elif step_type == "flow":
                from_comp = step.get("from", "")
                to_comp = step.get("to", "")
                events.append(self._ev(start_ms, start_ms + duration_ms,
                    "diagram_flow_animate", {
                        "from_component": from_comp,
                        "to_component": to_comp,
                        "path_id": f"flow_{from_comp}_{to_comp}",
                        "duration_ms": duration_ms,
                        "loop": False,
                        "particle_color": "#4F8EF7",
                    }))

            elif step_type == "key_insight":
                comp_id = step.get("component_id", "")
                events.append(self._ev(start_ms, start_ms + duration_ms,
                    "diagram_component_highlight", {
                        "component_id": comp_id,
                        "bbox": step.get("bbox", [0.3, 0.3, 0.4, 0.3]),
                        "label": comp_id.replace("_", " ").title(),
                        "color": "#FF6B35",
                    }))
                events.append(self._ev(start_ms + 300, start_ms + duration_ms,
                    "teacher_laser", {
                        "position_x": 0.5, "position_y": 0.4,
                        "duration_ms": duration_ms - 300,
                    }))

            elif step_type == "synthesis":
                events.append(self._ev(start_ms, start_ms + duration_ms,
                    "diagram_zoom_reset", {"smooth": True}))
                events.append(self._ev(start_ms + 500, start_ms + duration_ms,
                    "teacher_erase", {"duration_ms": 500}))

            cursor_ms = start_ms + duration_ms + 200  # 200ms gap between steps

        return events

    # ──────────────────────────────────────────────────────────────────────
    # V13 — ViMax Shot Planning (Layout Shifts)
    # ──────────────────────────────────────────────────────────────────────

    def _shot_plan_events(self) -> List[Dict]:
        """Convert shot_plan from Blueprint V5 into layout_shift events."""
        events = []
        shot_plan = self.scene.get("shot_plan", [])
        if not isinstance(shot_plan, list):
            return events

        for shot in shot_plan:
            if not isinstance(shot, dict):
                continue
            start_pct = shot.get("start_pct", 0)
            layout = shot.get("layout", "balanced")
            start_ms = self.total_ms * start_pct
            end_ms = self.total_ms * shot.get("end_pct", 1.0)

            events.append(self._ev(start_ms, end_ms, "layout_shift", {
                "layout": layout,
                "shot_name": shot.get("shot", "establish"),
            }))

        return events

    # ──────────────────────────────────────────────────────────────────────
    # V14 — Formula Step Events
    # ──────────────────────────────────────────────────────────────────────

    def _formula_steps(self) -> List[Dict]:
        """Generate formula_step events from scene's equation_data.
        Each step reveals a portion of the LaTeX formula, timed by
        trigger_word → _find_word_ms(). Falls back to proportional timing."""
        events = []
        equation_data = self.scene.get("equation_data", {})
        if not equation_data:
            return events

        latex_full = equation_data.get("latex", "")
        steps = equation_data.get("steps", [])
        variables = equation_data.get("variables", [])

        if steps:
            for i, step in enumerate(steps):
                trigger_word = step.get("trigger_word", "")
                trigger_ms = self._find_word_ms(trigger_word) if trigger_word else None
                if trigger_ms is None:
                    fraction = (i + 1) / (len(steps) + 1)
                    trigger_ms = self.total_ms * fraction

                step_start = max(0, trigger_ms - 50)
                events.append(self._ev(
                    step_start, step_start + 2000, "formula_step", {
                        "step_index": i,
                        "latex": step.get("latex", ""),
                        "label": step.get("label", f"Step {i+1}"),
                        "full_latex": latex_full,
                        "total_steps": len(steps),
                    }
                ))
        else:
            # Auto-generate 3 proportional reveal steps
            for i in range(3):
                fraction = (i + 1) / 4
                step_ms = self.total_ms * fraction
                events.append(self._ev(
                    step_ms, step_ms + 2000, "formula_step", {
                        "step_index": i,
                        "latex": latex_full,
                        "label": f"Part {i+1}",
                        "full_latex": latex_full,
                        "total_steps": 3,
                    }
                ))

        # Variable annotations
        for i, var in enumerate(variables):
            symbol = var.get("symbol", "")
            meaning = var.get("meaning", "")
            var_ms = self._find_word_ms(symbol) if symbol else None
            if var_ms is None:
                var_ms = self.total_ms * 0.7 + (i * 800)
            events.append(self._ev(
                var_ms, var_ms + 1500, "formula_variable_annotate", {
                    "symbol": symbol,
                    "meaning": meaning,
                    "var_index": i,
                }
            ))

        return events

    # ──────────────────────────────────────────────────────────────────────
    # V14 — Table Focus Events
    # ──────────────────────────────────────────────────────────────────────

    def _table_focus_events(self) -> List[Dict]:
        """Generate table_focus events from scene's table_data.
        Each focus event highlights a row or column, timed by
        trigger_word → _find_word_ms(). Falls back to proportional timing."""
        events = []
        table_data = self.scene.get("table_data", {})
        if not table_data:
            return events

        headers = table_data.get("headers", [])
        rows = table_data.get("rows", [])
        focus_sequence = table_data.get("focus_sequence", [])

        if focus_sequence:
            for i, focus in enumerate(focus_sequence):
                trigger_word = focus.get("trigger_word", "")
                trigger_ms = self._find_word_ms(trigger_word) if trigger_word else None
                if trigger_ms is None:
                    fraction = (i + 1) / (len(focus_sequence) + 1)
                    trigger_ms = self.total_ms * fraction

                focus_start = max(0, trigger_ms - 50)
                focus_type = focus.get("type", "row")
                focus_index = focus.get("index", 0)

                events.append(self._ev(
                    focus_start, focus_start + 2000, "table_focus", {
                        "focus_type": focus_type,
                        "focus_index": focus_index,
                        "headers": headers,
                        "highlight_color": "#FFD700" if focus_type == "column" else "#4F8EF7",
                        "label": headers[focus_index] if focus_type == "column" and focus_index < len(headers) else f"Row {focus_index + 1}",
                    }
                ))
        else:
            # Auto-generate: headers first, then rows
            if headers:
                header_ms = self.total_ms * 0.15
                events.append(self._ev(
                    header_ms, header_ms + 2000, "table_focus", {
                        "focus_type": "header",
                        "focus_index": -1,
                        "headers": headers,
                        "highlight_color": "#FFD700",
                        "label": "Table Headers",
                    }
                ))

            max_rows = min(len(rows), 4)
            for i in range(max_rows):
                fraction = 0.25 + (i * 0.15)
                row_ms = self.total_ms * fraction
                events.append(self._ev(
                    row_ms, row_ms + 2000, "table_focus", {
                        "focus_type": "row",
                        "focus_index": i,
                        "headers": headers,
                        "highlight_color": "#4F8EF7",
                        "label": f"Row {i + 1}",
                    }
                ))

        return events

    # ──────────────────────────────────────────────────────────────────────
    # V13 — Cognitive Load Optimizer (DNA-Aware, Mayer's 5 Rules)
    # ──────────────────────────────────────────────────────────────────────

    _MAJOR_EVENTS = {
        "bullet_enter", "bullet_active", "bullet_word_reveal", "diagram_pan_zoom",
        "teacher_write", "teacher_circle", "teacher_underline", "teacher_laser",
        "attention_hook", "diagram_component_highlight", "layout_shift",
        "formula_step", "table_focus", "difference_cell_flash", "term_underline_draw",
        "term_zoom", "bridge_arrow_draw", "analogy_panel_glow", "concept_panel_reveal"
    }

    def _optimize_cognitive_load(self, events: List[Dict]) -> List[Dict]:
        """
        Post-process timeline events to enforce Mayer's Multimedia Principles
        and 3Blue1Brown pedagogical parameters:
        
        Rule 1 — Segmentation: Max 2 animation events in any 800ms window. Push overlapping.
        Rule 2 — Signaling: 300ms pause (no animations) preceding any bullet_enter or diagram_zoom_in/diagram_pan_zoom.
        Rule 3 — Coherence: Remove animations that are not linked to trigger spoken words (missing word timestamp matches).
        Rule 4 — Temporal Contiguity: Animation and script words must be within 400ms. Shift to exactly 200ms before.
        Rule 5 — Breathing Room: Mandatory 600ms empty window after any diagram_zoom_out.
        """
        if not events:
            return events

        # Helper to check if event type is major animation
        def is_major(e):
            return e.get("event_type") in self._MAJOR_EVENTS

        # --- RULE 3 & 4: Coherence and Temporal Contiguity ---
        # Match each visual trigger event with narration timestamps and prune if unrelated
        refined_events = []
        for e in events:
            etype = e.get("event_type")
            
            # Non-visual triggers (scene_start, subtitle, audio) remain unmodified
            if etype in ("scene_start", "scene_end", "subtitle_show", "subtitle_word_hl", "ken_burns", "subtitle_dim"):
                refined_events.append(e)
                continue

            # CRITICAL: Animation Brain events have 'timestamp_ms' field and are
            # ALREADY speech-synchronized by _get_narration_word_ms(). They must
            # bypass Rule 3/4 — stripping them destroys all DNA-specific animations.
            if "timestamp_ms" in e:
                refined_events.append(e)
                continue

            # DNA structural events that are layout-driven (not speech-driven)
            # must also pass through without coherence pruning
            _DNA_PASSTHROUGH = {
                "heading_glow", "gold_word_pulse", "cause_highlight", "effect_highlight",
                "column_a_slide_in", "column_b_slide_in", "analogy_panel_glow",
                "bridge_arrow_draw", "concept_panel_reveal", "background_transition",
                "avatar_scale_to_center", "gold_text_fade_in", "avatar_return_to_corner",
                "formula_render", "annotation_circle", "flow_arrow_draw", "arrow_draw",
                "dramatic_pause", "diagram_overview", "heading_focus", "takeaway_show",
                "analogy_overlay", "diagram_enter", "diagram_exit",
                # V14: New AnimationBrain DNA-specific events
                "process_flow_pan", "sequential_zoom_per_region",
                "dramatic_arrow", "effect_reveal",
            }
            if etype in _DNA_PASSTHROUGH:
                refined_events.append(e)
                continue

            # Check spoken synchronization link
            trigger_word = e.get("data", {}).get("trigger_word") or e.get("trigger_word")
            if not trigger_word and is_major(e):
                # Check if it has a label, text or other metadata to resolve
                lbl = e.get("data", {}).get("label") or e.get("data", {}).get("text")
                if lbl:
                    trigger_word = lbl.split()[0] if lbl.split() else ""
            
            if is_major(e):
                if not trigger_word:
                    # Rule 3: Coherence - remove visual event if not tied to any spoken topic/word
                    continue
                
                # Find matching spoken timestamp
                word_ms = self._find_word_ms(trigger_word)
                if word_ms is None:
                    # Rule 3: Coherence - remove visual event if trigger word is not spoken at all in narration
                    continue
                
                # Rule 4: Temporal Contiguity - ensure sync within 400ms
                time_diff = abs(e["start_ms"] - word_ms)
                if time_diff > 400.0:
                    # Align precisely 200ms before spoken word to allow visual transition before sound
                    shift = word_ms - 200.0 - e["start_ms"]
                    e["start_ms"] = max(0.0, e["start_ms"] + shift)
                    e["end_ms"] = max(200.0, e["end_ms"] + shift)
                    if "timestamp_ms" in e:
                        e["timestamp_ms"] = e["start_ms"]

            refined_events.append(e)

        # Sort events by start_ms to process intervals chronologically
        refined_events.sort(key=lambda e: e["start_ms"])

        # --- RULE 2: Signaling (300ms quiet window preceding new bullet/zooms) ---
        for i in range(len(refined_events)):
            curr = refined_events[i]
            if curr.get("event_type") in ("bullet_enter", "bullet_word_reveal", "diagram_pan_zoom", "diagram_zoom_in", "process_flow_pan", "sequential_zoom_per_region"):
                target_start = curr["start_ms"]
                # Look backwards for preceding animations in [target_start - 300, target_start]
                for prev in refined_events[:i]:
                    if is_major(prev) and (target_start - 300.0 <= prev["start_ms"] <= target_start):
                        # Push current event forward to guarantee quiet window
                        delay = (prev["start_ms"] + 300.0) - curr["start_ms"]
                        curr["start_ms"] += delay
                        curr["end_ms"] += delay
                        if "timestamp_ms" in curr:
                            curr["timestamp_ms"] = curr["start_ms"]

        # Re-sort after pushing signaling quiet buffers
        refined_events.sort(key=lambda e: e["start_ms"])

        # --- RULE 5: Breathing Room (600ms empty window after diagram_zoom_out) ---
        for i in range(len(refined_events)):
            curr = refined_events[i]
            if curr.get("event_type") in ("diagram_zoom_out", "diagram_zoom_out_smooth", "zoom_out"):
                zoom_out_end = curr["start_ms"]
                # Ensure no major animation fires within 600ms after this zoom out
                for j in range(i + 1, len(refined_events)):
                    nxt = refined_events[j]
                    if is_major(nxt) and (zoom_out_end < nxt["start_ms"] < zoom_out_end + 600.0):
                        delay = (zoom_out_end + 600.0) - nxt["start_ms"]
                        nxt["start_ms"] += delay
                        nxt["end_ms"] += delay
                        if "timestamp_ms" in nxt:
                            nxt["timestamp_ms"] = nxt["start_ms"]

        # Re-sort after pushing breathing room delays
        refined_events.sort(key=lambda e: e["start_ms"])

        # --- RULE 1: Segmentation (Max 2 major animation events within any 800ms window) ---
        i = 0
        while i < len(refined_events):
            major_in_window = []
            win_start = refined_events[i]["start_ms"]
            
            # Find all major animations within [win_start, win_start + 800]
            for j in range(i, len(refined_events)):
                nxt = refined_events[j]
                if nxt["start_ms"] > win_start + 800.0:
                    break
                if is_major(nxt):
                    major_in_window.append(nxt)

            # If more than 2 animations are crowded in this 800ms window, segment them
            if len(major_in_window) > 2:
                # Keep the first two, and delay all subsequent ones beyond the window
                for idx in range(2, len(major_in_window)):
                    crowded_ev = major_in_window[idx]
                    delay = (win_start + 800.0) - crowded_ev["start_ms"]
                    crowded_ev["start_ms"] += delay
                    crowded_ev["end_ms"] += delay
                    if "timestamp_ms" in crowded_ev:
                        crowded_ev["timestamp_ms"] = crowded_ev["start_ms"]
                
                # Re-sort and repeat check at same index to ensure safety
                refined_events.sort(key=lambda e: e["start_ms"])
                continue
            i += 1

        # --- Auto-insert subtitle_dim during zoom glows or zooms for high focus ---
        dim_events = []
        for e in refined_events:
            if e["event_type"] in ("zoom_word_glow", "diagram_pan_zoom", "term_zoom"):
                dim_events.append(self._ev(
                    e["start_ms"], e["end_ms"],
                    "subtitle_dim", {"opacity": 0.3, "trigger_word": "dim"}
                ))
        refined_events.extend(dim_events)
        refined_events.sort(key=lambda e: e["start_ms"])

        return refined_events

