# -*- coding: utf-8 -*-
"""
SmartStudyInstructor V13 — Pedagogical Intelligence Engine
3.5-Agent LLM Pipeline:
  1. Content Analyst (Agent 1)
  2. Pedagogical Planner (Agent 2)
  3. DNA Classifier (Agent 1.5 - core/scene_dna.py)
  4. Scene Director (Agent 3 - DNA-Aware)
"""
import json
from typing import Dict, List, Optional
from app.utils.logger import log_info, log_error
from core.scene_dna import classify_scene_dna

class PedagogicalEngine:
    """
    Splits blueprint generation into focused, DNA-driven pedagogical steps.
    Translates raw materials into highly engaging structured scenes.
    """

    def __init__(self, llm_client):
        """
        Args:
            llm_client: Any LLMClient instance supporting _chat(system, user, max_tokens)
        """
        self._llm = llm_client

    # ──────────────────────────────────────────────────────────────────────
    # Agent 1: Content Analyst
    # ──────────────────────────────────────────────────────────────────────

    def analyze_content(self, document_text: str, vlm_pages: List[Dict] = None) -> Dict:
        """Analyzes raw document text and returns a structured content map."""
        vlm_context = ""
        if vlm_pages:
            summaries = []
            for p in vlm_pages:
                summaries.append(f"[Page {p.get('page_num')} | {p.get('page_type')}] {p.get('vlm_description', '')}")
            vlm_context = "\n=== VISUAL ANALYSIS ===\n" + "\n".join(summaries)

        system = """You are a Master Content Analyst. Your job is to deeply analyze the provided educational document and map out its core intellectual architecture. 
You must dynamically determine the number of scenes (slides) needed. DO NOT rush or compress topics. If the document is long and complex, recommend 10, 15, or even 20 scenes! One scene per major concept. 
Return ONLY a JSON object containing:
- "course_title": string
- "main_topics": array of strings
- "concept_dependency_graph": array of objects [{"concept": "X", "depends_on": ["Y"]}]
- "difficulty_progression": array of "beginner"/"intermediate"/"advanced" per topic
- "diagram_page_numbers": array of integers (if visuals present)
- "prerequisite_gaps": string describing what prior knowledge students need
- "has_equations": true/false (does the document contain mathematical formulas or equations?)
- "has_tables": true/false (does the document contain structured tabular data?)
- "equation_topics": array of topic names that contain math/formulas/equations
- "table_topics": array of topic names that have tabular or structured data
- "total_estimated_scenes": integer (Be generous. Generate exactly as many scenes as required to teach every concept thoroughly and without cognitive overload)."""

        user = f"{vlm_context}\n\nDOCUMENT:\n{document_text[:8000]}"
        raw = self._llm._chat(system, user, max_tokens=2048)

        try:
            result = self._extract_json(raw)
            log_info(f"[V13 Agent 1] Content Analysis: {result.get('total_estimated_scenes', '?')} scenes suggested")
            return result
        except Exception as e:
            log_error(f"[V13 Agent 1] Parse error: {e}")
            return {"concept_dependency_graph": [], "total_estimated_scenes": 5,
                    "course_title": "Unknown", "main_topics": []}

    # ──────────────────────────────────────────────────────────────────────
    # Agent 2: Pedagogical Planner
    # ──────────────────────────────────────────────────────────────────────

    def plan_pedagogy(self, content_analysis: Dict, document_text: str) -> Dict:
        """Decides overall narrative strategy and learning progressions."""
        system = """You are a World-Class Pedagogical Architect trained in Mayer's Multimedia Learning Principles, Socratic Scaffolding, and Cognitive Load Theory. 
Your goal is to transform the content analysis into an elegant, high-impact instructional plan. We want the student to have an active learning experience, NOT feel like they are watching the news.

For each concept in the content analysis, you must plan a custom pedagogical strategy:
1. "explanation_strategy": Choose from:
   - "first_principles": strip away all jargon and derive the concept from the absolute ground up.
   - "analogy_bridging": start with a powerful, relatable everyday analogy, then bridge to the technical details.
   - "socratic_challenge": start with a paradox or question that exposes a gap in the student's current model, then build the concept to solve it.
   - "visual_flowchart": heavily emphasize visual connections, drawing circles/arrows on diagrams first.
2. "expected_confusion_point": pinpoint the exact cognitive trap or common misconception students fall into for this topic.
3. "aha_moment_trigger": describe the precise conceptual breakthrough, metaphor, or visualization that immediately makes the concept click.
4. "pacing_note": "fast"/"normal"/"slow" based on cognitive difficulty, with a pedagogical reason.
5. "narrative_tone": Choose one: "storyteller", "socratic_mentor", "intuitive_scientist", "enthusiastic_engineer".
6. "animation_priority": "diagram", "bullets", or "both".

Return a single JSON object containing:
- "teaching_strategies": array of the above planned strategies per concept.
- "global_pacing_notes": general strategy to prevent cognitive overload.
- "narrative_arc": how the concepts connect to tell a unified pedagogical story.
Return ONLY valid JSON. No markdown, no explanations."""

        concepts_summary = json.dumps(content_analysis, indent=2)
        user = f"CONTENT ANALYSIS:\n{concepts_summary}\n\nDOCUMENT EXCERPT:\n{document_text[:4000]}"
        raw = self._llm._chat(system, user, max_tokens=2048)

        try:
            result = self._extract_json(raw)
            strategies = result.get("teaching_strategies", [])
            log_info(f"[V13 Agent 2] Pedagogy Plan: {len(strategies)} strategies, arc={result.get('narrative_arc', '?')}")
            return result
        except Exception as e:
            log_error(f"[V13 Agent 2] Parse error: {e}")
            return {"teaching_strategies": [], "narrative_arc": "building_blocks"}

    # ──────────────────────────────────────────────────────────────────────
    # Agent 3: DNA-Aware Scene Director
    # ──────────────────────────────────────────────────────────────────────

    def direct_scenes(
        self,
        pedagogy_plan: Dict,
        content_analysis: Dict,
        document_text: str,
        extracted_images: List[str] = None,
        diagram_spatial_data: Dict = None,
    ) -> Dict:
        """
        Generates the final Blueprint V5 JSON utilizing the new Scene DNA Classifier.
        This Scene Director is fully DNA-aware and prompts Agent 3 dynamically per scene
        to produce highly diverse scripts and correct animation metadata.
        """
        log_info("[V13 Agent 3] Launching DNA-aware Scene Director...")
        
        # 1. Map content chunks to separate scene blueprints sequentially
        main_topics = content_analysis.get("main_topics", [])
        if not main_topics:
            main_topics = ["Introduction", "Core Principles", "Applications", "Summary"]

        total_scenes = len(main_topics)
        scenes = []

        doc_len = len(document_text)

        valid_scenes_count = 0
        for i, topic_name in enumerate(main_topics):
            if doc_len < 4000:
                content_chunk = document_text
            else:
                chunk_sz = doc_len // max(1, total_scenes)
                start_idx = i * chunk_sz
                # Provide a generous overlap
                end_idx = min(start_idx + chunk_sz + 1000, doc_len)
                content_chunk = document_text[start_idx:end_idx]

            if not content_chunk.strip():
                log_info(f"Skipping topic '{topic_name}' because text chunk is empty.")
                continue

            # Resolve if this scene should contain a diagram
            has_diagram = False
            diagram_path = ""
            if extracted_images:
                # Assign diagrams round-robin or based on spatial references
                diagram_idx = i % len(extracted_images)
                diagram_path = extracted_images[diagram_idx]
                has_diagram = True

            # Agent 1.5: DNA Classifier
            dna_data = classify_scene_dna(
                content_chunk=content_chunk,
                has_diagram=has_diagram,
                diagram_type="diagram_spatial" if has_diagram else "none"
            )

            log_info(f"[V13 Scene {i+1}] Classified as {dna_data['dna_type']} | has_diagram={has_diagram}")

            # Look up Agent 2's pedagogy strategy for this topic
            strategies = pedagogy_plan.get("teaching_strategies", [])
            strategy = strategies[i] if i < len(strategies) else {}
            explanation_strategy = strategy.get("explanation_strategy", "first_principles")
            narrative_tone = strategy.get("narrative_tone", "storyteller")
            aha_trigger = strategy.get("aha_moment_trigger", "")
            pacing = strategy.get("pacing_note", "normal")

            # Rebuild Agent 3 Prompt dynamically based on DNA classification
            system_prompt = f"""You are directing scene number {i+1} of an educational video.
The scene MUST focus SPECIFICALLY on teaching the topic: "{topic_name}". Do NOT repeat content from other scenes.
The scene DNA type is {dna_data['dna_type']}. 
The narration style for this DNA type is: {dna_data['narration_style']}.
The teaching hooks you must use are: {json.dumps(dna_data['teaching_hooks'])}.

═══ NARRATION STYLE RULES FOR {dna_data['dna_type']} ═══
- For DNA-1 (CONCEPT_DEFINITION): Start with a real-world analogy hook (exactly one sentence), then explain definitions clearly.
- For DNA-2 (PROCESS_FLOW): Use sequential structure ("first... then... finally...") with deliberate Socratic pauses. Highlight transitions between steps.
- For DNA-3 (CAUSE_EFFECT): Use dramatic cause-effect language ("Because of X... this leads to Y..."). Highlight the link strongly.
- For DNA-4 (COMPARISON): Use analytical comparison language ("Unlike X... Y instead..."). Explicitly highlight cells or features.
- For DNA-5 (DIAGRAM_SPATIAL): Use guided tour language ("Let us first look at the big picture... now zoom in here..."). Explain labels in pedagogical order.
- For DNA-6 (WORKED_EXAMPLE): Use step-by-step mathematical breakdown language ("This part represents... this term means..."). Read formulas out loud in literal English.
- For DNA-7 (ANALOGY_BRIDGE): Use storytelling bridge language ("You already know how X works... this concept works exactly the same way..."). Draw a link at the climax.
- For DNA-8 (TAKEAWAY_SUMMARY): Use emphatic summary language ("Remember this above everything else..."). Deliver a massive final punch.

═══ GENERAL RULES ═══
- NARRATION LENGTH: STRICTLY 130-180 words.
- DO NOT use SSML/HTML tags in narration.
- Speak in a natural, flowing conversational narrative, never just reading off bullet points.
- Speak directly to the listener ("Let's look at this...", "Notice how...", "Now, let's trace...").
- For formulas: always write LaTeX equations inside the formula block, but read them literally in the narration.
- Return ONLY valid JSON matching the exact schema below. Do not wrap in markdown or preambles.

Schema:
{{
  "title": "Descriptive title (8-12 words)",
  "topic": "Topic Name",
  "heading_left": "Compelling hook headline or thought-provoking question (12-15 words, must be engaging and specific to the topic)",
  "gold_word": "The single most important keyword in this scene",
  "left_description": "2-3 sentences explaining the conceptual problem or big picture.",
  "heading_right": "Full Academic Name of the Concept (4-8 words)",
  "narration": "130-180 words Feynman-style spoken script matching narration_style.",
  "bullets": [
    {{
      "num": "01",
      "text": "Descriptive point explaining concept clearly (10-15 words)",
      "zoom_word": "key term in text",
      "trigger_word": "word_in_narration_that_triggers_bullet",
      "entrance": "slide_left"
    }}
  ],
  "takeaway": "Memorable, single-line notebook takeaway.",
  "animation_hints": {{
    "visual_priority": "diagram" | "text" | "math" | "table",
    "avatar_position": "corner" | "center" | "hidden",
    "glow_color": "#FFD700" | "#00E5FF" | "#FF3B3B" | "#4F8EF7"
  }},
  "diagram_trigger_word": "exact word in narration that triggers diagram to appear on screen",
  "attention_hooks": [
    {{
      "hook_type": "callout_bubble" | "did_you_know" | "warning_box",
      "trigger_word": "word_in_narration",
      "text": "1-sentence visual insight."
    }}
  ]
}}

IMPORTANT RULES:
- Generate exactly 3-5 bullets. Each bullet must be 10-15 words (not short!).
- heading_left MUST be 12-15 words — a full, compelling sentence or question. NOT short.
- heading_right MUST be 4-8 words — the full academic concept name.
- If diagrams exist, mention them in narration and set diagram_trigger_word to the spoken word that should display the diagram.
"""
            # Inject spatial or data specific instructions
            spatial_desc = ""
            if has_diagram and diagram_spatial_data and diagram_path in diagram_spatial_data:
                spatial_desc = f"\nDiagram spatial coordinates discovered:\n{json.dumps(diagram_spatial_data[diagram_path], indent=2)}"

            user_prompt = f"""You must focus this scene SPECIFICALLY on teaching: "{topic_name}".
Do NOT generate content about other topics. The heading, bullets, narration, and takeaway must all be unique to "{topic_name}".

═══ PEDAGOGICAL DIRECTION (from curriculum planner) ═══
- Explanation Strategy: {explanation_strategy}
- Narrative Tone: {narrative_tone}
- Aha Moment to trigger: {aha_trigger}
- Pacing: {pacing}

Content chunk to teach:
\"\"\"{content_chunk[:4000]}\"\"\"{spatial_desc}

Provide the output matching the schema."""

            # Run Scene Director per scene
            raw_scene_str = self._llm._chat(system_prompt, user_prompt, max_tokens=2048)
            try:
                scene_dict = self._extract_json(raw_scene_str)

                # Format scene matching original UI structures + DNA upgrades
                scene_dict["scene_id"] = f"scene_{valid_scenes_count+1:02d}"
                scene_dict["scene_index"] = valid_scenes_count + 1
                scene_dict["total_scenes"] = total_scenes
                scene_dict["scene_dna"] = dna_data
                scene_dict["scene_type"] = dna_data["layout_preset"]

                # Ensure diagram refs are populated
                if has_diagram:
                    scene_dict["diagram_refs"] = [diagram_path]
                    scene_dict["diagram_paths"] = [diagram_path]
                    if diagram_spatial_data and diagram_path in diagram_spatial_data:
                        spatial_info = diagram_spatial_data[diagram_path]
                        if isinstance(spatial_info, dict) and "visual" in spatial_info:
                            scene_dict["diagram_data"] = spatial_info["visual"]
                        else:
                            scene_dict["diagram_data"] = spatial_info
                    else:
                        scene_dict["diagram_data"] = {}
                        
                    # Force layout preset to a diagram-supporting layout
                    if scene_dict.get("scene_type") not in ["diagram_spatial", "process_flow"]:
                        scene_dict["scene_type"] = "diagram_spatial"
                        if isinstance(scene_dict.get("scene_dna"), dict):
                            scene_dict["scene_dna"]["layout_preset"] = "diagram_spatial"
                            scene_dict["scene_dna"]["dna_type"] = "DNA-5 DIAGRAM_SPATIAL"
                            scene_dict["scene_dna"]["narration_style"] = "guided_tour"
                else:
                    scene_dict["diagram_refs"] = []
                    scene_dict["diagram_paths"] = []
                    scene_dict["diagram_data"] = {}

                # Fallback list for zoom keywords
                scene_dict["zoom_words"] = [b.get("zoom_word") for b in scene_dict.get("bullets", []) if b.get("zoom_word")]

                # Enforce DNA-specific data structures
                if dna_data["dna_type"] == "DNA-6 WORKED_EXAMPLE":
                    # Use LLM-generated equation data if present, otherwise derive from topic
                    if not scene_dict.get("equation_data"):
                        scene_dict["equation_data"] = {
                            "latex": scene_dict.get("latex", f"{topic_name}"),
                            "steps": [
                                {"latex": b.get("text", ""), "label": f"Step {i+1}", "trigger_word": b.get("trigger_word", "")}
                                for i, b in enumerate(scene_dict.get("bullets", [])[:4])
                                if isinstance(b, dict)
                            ],
                            "variables": []
                        }
                elif dna_data["dna_type"] == "DNA-4 COMPARISON":
                    # Use LLM-generated table data if present, otherwise derive from bullets
                    if not scene_dict.get("table_data"):
                        bullets = scene_dict.get("bullets", [])
                        rows = []
                        for b in bullets:
                            if isinstance(b, dict):
                                text = b.get("text", "")
                                rows.append([text, "", ""])
                        scene_dict["table_data"] = {
                            "headers": ["Feature", topic_name, "Alternative"],
                            "rows": rows if rows else [["Aspect 1", "Value A", "Value B"]],
                            "focus_sequence": [
                                {"type": "row", "index": i, "trigger_word": b.get("trigger_word", "")}
                                for i, b in enumerate(bullets[:4])
                                if isinstance(b, dict)
                            ]
                        }

                scenes.append(scene_dict)
                valid_scenes_count += 1
                log_info(f"[V13 Scene Director] Choreographed scene {valid_scenes_count}/{total_scenes} ({dna_data['dna_type']})")

            except Exception as e:
                log_error(f"[V13 Scene Director] Failed to parse scene {i+1}: {e}")
                # Safe pedagogical fallback
                scenes.append({
                    "scene_id": f"scene_{valid_scenes_count+1:02d}",
                    "scene_index": valid_scenes_count + 1,
                    "total_scenes": total_scenes,
                    "scene_dna": dna_data,
                    "scene_type": dna_data["layout_preset"],
                    "topic": topic_name,
                    "heading_left": f"Let's explore {topic_name}",
                    "gold_word": topic_name.split()[0] if topic_name.split() else "Topic",
                    "left_description": f"Exploring the core details behind {topic_name} in depth.",
                    "heading_right": topic_name,
                    "narration": f"In this section, we examine {topic_name}. Think of it like a puzzle coming together piece by piece.",
                    "takeaway": "Takeaway: understanding fundamentals leads to mastery.",
                    "bullets": [
                        {"num": "01", "text": "Core element explained clearly", "zoom_word": "element", "trigger_word": "section", "entrance": "slide_left"}
                    ],
                    "diagram_refs": [diagram_path] if has_diagram else [],
                    "diagram_paths": [diagram_path] if has_diagram else [],
                    "diagram_data": diagram_spatial_data[diagram_path]["visual"] if (has_diagram and diagram_spatial_data and diagram_path in diagram_spatial_data and isinstance(diagram_spatial_data[diagram_path], dict) and "visual" in diagram_spatial_data[diagram_path]) else (diagram_spatial_data[diagram_path] if (has_diagram and diagram_spatial_data and diagram_path in diagram_spatial_data) else {}),
                    "diagram_trigger_word": "examine",
                    "zoom_words": ["element"]
                })
                valid_scenes_count += 1

        return {"scenes": scenes}

    # ──────────────────────────────────────────────────────────────────────
    # Full 3.5-Agent Pipeline
    # ──────────────────────────────────────────────────────────────────────

    def generate_blueprint_v5(
        self,
        document_text: str,
        extracted_images: List[str] = None,
        vlm_pages: List[Dict] = None,
        diagram_spatial_data: Dict = None,
    ) -> Dict:
        """
        Runs the full pipeline:
        Agent 1 (Content Analyst) -> Agent 2 (Pedagogical Planner) -> Agent 3 (DNA Scene Director)
        """
        log_info("=" * 60)
        log_info("[V13] Pedagogical Engine — DNA-Aware Pipeline Starting")
        log_info("=" * 60)

        # Agent 1: Analyze content
        content_analysis = self.analyze_content(document_text, vlm_pages)
        if not content_analysis or not any(content_analysis.values()):
            log_error("[V13] Content Analyst returned empty analysis.")
            return None

        # Agent 2: Plan pedagogy
        pedagogy_plan = self.plan_pedagogy(content_analysis, document_text)
        if not pedagogy_plan or not any(pedagogy_plan.values()):
            log_error("[V13] Pedagogical Planner returned empty plan.")
            return None

        # Agent 3: DNA-Aware Scene Director
        blueprint = self.direct_scenes(
            pedagogy_plan=pedagogy_plan,
            content_analysis=content_analysis,
            document_text=document_text,
            extracted_images=extracted_images,
            diagram_spatial_data=diagram_spatial_data,
        )

        if not blueprint.get("scenes"):
            log_error("[V13] Scene Director returned no scenes.")
            return None

        # Add engine tag
        for scene in blueprint.get("scenes", []):
            scene["_pedagogical_engine"] = "v13_3.5agent_dna"

        log_info(f"[V13] Pipeline Complete: {len(blueprint.get('scenes', []))} DNA-grounded scenes created")
        return blueprint

    @staticmethod
    def _extract_json(raw: str) -> Dict:
        """Robust JSON extraction supporting markdown blocks."""
        if raw.startswith("ERROR:"):
            raise ValueError(f"LLM API Error: {raw}")
            
        start_idx = raw.find('{')
        if start_idx == -1:
            raise ValueError("No JSON object found in response")

        bracket_count = 0
        end_idx = -1
        for i in range(start_idx, len(raw)):
            if raw[i] == '{':
                bracket_count += 1
            elif raw[i] == '}':
                bracket_count -= 1
                if bracket_count == 0:
                    end_idx = i + 1
                    break

        if end_idx == -1:
            raise ValueError("Incomplete JSON — LLM truncated response")

        return json.loads(raw[start_idx:end_idx])
