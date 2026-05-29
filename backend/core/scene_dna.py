# -*- coding: utf-8 -*-
"""
SmartStudyInstructor — Scene DNA Classifier
Classifies raw ChromaDB text chunks and VLM descriptors into one of exactly
8 distinct Scene DNA archetypes. Each archetype is mapped to a specific
pedagogical narration style, visual layout preset, and GSAP animation strategy.
"""
import os
import re
import json
import google.generativeai as genai
from app.utils.logger import log_info, log_error, log_debug

# Configure Gemini — load from pydantic-settings (.env) with os.getenv fallback
try:
    from app.config import settings as _app_settings
    api_key = getattr(_app_settings, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
except ImportError:
    api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

_model = genai.GenerativeModel("gemini-2.0-flash")

# The 8 Scene DNA archetypes and their details
DNA_TYPES = {
    "DNA-1 CONCEPT_DEFINITION": {
        "layout_preset": "concept_definition",
        "narration_style": "conversational",
        "animation_strategy": "heading_glow_word_by_word_reveal"
    },
    "DNA-2 PROCESS_FLOW": {
        "layout_preset": "process_flow",
        "narration_style": "sequential",
        "animation_strategy": "step_glow_arrow_draw_panned_zoom"
    },
    "DNA-3 CAUSE_EFFECT": {
        "layout_preset": "cause_effect",
        "narration_style": "dramatic",
        "animation_strategy": "cause_red_glow_arrow_draw_effect_green_glow"
    },
    "DNA-4 COMPARISON": {
        "layout_preset": "comparison",
        "narration_style": "analytical",
        "animation_strategy": "columns_slide_in_cell_flash"
    },
    "DNA-5 DIAGRAM_SPATIAL": {
        "layout_preset": "diagram_spatial",
        "narration_style": "guided_tour",
        "animation_strategy": "pedagogical_walkthrough_circle_annotate"
    },
    "DNA-6 WORKED_EXAMPLE": {
        "layout_preset": "worked_example",
        "narration_style": "step_by_step",
        "animation_strategy": "katex_render_underline_draw_term_zoom"
    },
    "DNA-7 ANALOGY_BRIDGE": {
        "layout_preset": "analogy_bridge",
        "narration_style": "storytelling",
        "animation_strategy": "analogy_glow_bridge_arrow_draw_concept_reveal"
    },
    "DNA-8 TAKEAWAY_SUMMARY": {
        "layout_preset": "takeaway_summary",
        "narration_style": "emphatic",
        "animation_strategy": "navy_bg_avatar_center_gold_text_reveal"
    }
}

def classify_scene_dna(
    content_chunk: str,
    has_diagram: bool = False,
    diagram_type: str = "none"
) -> dict:
    """
    Classifies a raw text chunk into one of 8 Scene DNA types using Gemini 2.0 Flash.
    Returns a dictionary conforming to the required schema with keys:
      - dna_type (string, one of the 8 DNA types)
      - confidence (float between 0.0 and 1.0)
      - narration_style (string)
      - animation_strategy (string)
      - layout_preset (string)
      - teaching_hooks (list of strings)
    """
    default_dna = "DNA-1 CONCEPT_DEFINITION"
    fallback_response = {
        "dna_type": default_dna,
        "confidence": 1.0,
        "narration_style": DNA_TYPES[default_dna]["narration_style"],
        "animation_strategy": DNA_TYPES[default_dna]["animation_strategy"],
        "layout_preset": DNA_TYPES[default_dna]["layout_preset"],
        "teaching_hooks": [
            "Start with an intuitive everyday physical metaphor.",
            "Explain the abstract terms in simple, conversational English."
        ]
    }

    if not content_chunk or not content_chunk.strip():
        return fallback_response

    system_prompt = """You are an expert cognitive psychologist, senior curriculum designer, and media director.
Analyze the provided raw textbook/educational content chunk and determine which of the exactly 8 Scene DNA types best matches this content for highly engaging whiteboard video generation.

The 8 Scene DNA types are:
1. DNA-1 CONCEPT_DEFINITION: Standard textbook term, definition, or primary core concept being defined for the first time.
2. DNA-2 PROCESS_FLOW: A chronological series of steps, algorithm, loop, flowchart, chain of events, or step-by-step cycle (A -> B -> C).
3. DNA-3 CAUSE_EFFECT: A direct causal relationship between one thing/event leading to another (X leads to Y, cause and impact).
4. DNA-4 COMPARISON: Evaluating differences and similarities between two or more concepts, systems, items, or rows of features.
5. DNA-5 DIAGRAM_SPATIAL: Labeled schematic, map, architectural diagram, biology cell graph, or complex structural image where parts are pointed out.
6. DNA-6 WORKED_EXAMPLE: Mathematical formula, LaTeX equations, computational code snippets, logical worked derivations, or quantitative puzzles.
7. DNA-7 ANALOGY_BRIDGE: Deep, abstract concepts taught by mapping them explicitly to a familiar physical scenario first.
8. DNA-8 TAKEAWAY_SUMMARY: Final high-level summary, memorable mnemonic, warning, conclusion card, or end-of-topic notebook takeaway.

Return ONLY a valid JSON object. Do not include markdown ticks, backticks, conversational preamble, or explanations.

Schema:
{
  "dna_type": "DNA-1 CONCEPT_DEFINITION" | "DNA-2 PROCESS_FLOW" | "DNA-3 CAUSE_EFFECT" | "DNA-4 COMPARISON" | "DNA-5 DIAGRAM_SPATIAL" | "DNA-6 WORKED_EXAMPLE" | "DNA-7 ANALOGY_BRIDGE" | "DNA-8 TAKEAWAY_SUMMARY",
  "confidence": 0.95,
  "narration_style": "conversational" | "sequential" | "dramatic" | "analytical" | "guided_tour" | "step_by_step" | "storytelling" | "emphatic",
  "animation_strategy": "string matching layout animation direction",
  "layout_preset": "concept_definition" | "process_flow" | "cause_effect" | "comparison" | "diagram_spatial" | "worked_example" | "analogy_bridge" | "takeaway_summary",
  "teaching_hooks": ["hook sentence 1", "hook analogy 2", "pacing hint"]
}

Guidelines:
- If mathematical formulas/equations (like Latex, KaTeX, numbers, functions) are explicitly found, prefer DNA-6.
- If comparison keywords like "versus", "difference", "comparison", "unlike", "similarity", "on the other hand" appear, prefer DNA-4.
- If sequential keywords like "step 1", "first", "next", "afterwards", "finally", "process", "cycle" occur, prefer DNA-2.
- If cause/effect keywords like "causes", "results in", "leads to", "because of", "trigger", "effects" are strong, prefer DNA-3.
- If there is an image diagram mentioned or has_diagram is True, and it's a labeling graph, prefer DNA-5. Otherwise if it is a process diagram, prefer DNA-2.
"""

    user_prompt = f"""Content Chunk:
\"\"\"{content_chunk[:4000]}\"\"\"

Metadata:
- has_diagram: {has_diagram}
- diagram_type: {diagram_type}"""

    try:
        # Call Gemini model
        response = _model.generate_content([system_prompt, user_prompt])
        text = response.text.strip()
        
        # Robustly extract JSON block
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            log_error("[SceneDNA] No JSON object found in Gemini response. Text: " + text[:300])
            return fallback_response

        raw_dict = json.loads(match.group())
        dna_type = raw_dict.get("dna_type", default_dna).upper().strip()

        # Enforce exact match to known DNA list
        if dna_type not in DNA_TYPES:
            # Try fuzzy match
            matched = False
            for known in DNA_TYPES:
                if known.split()[-1] in dna_type or dna_type in known:
                    dna_type = known
                    matched = True
                    break
            if not matched:
                dna_type = default_dna

        preset = DNA_TYPES[dna_type]["layout_preset"]
        style = DNA_TYPES[dna_type]["narration_style"]
        strategy = DNA_TYPES[dna_type]["animation_strategy"]

        classified = {
            "dna_type": dna_type,
            "confidence": float(raw_dict.get("confidence", 0.8)),
            "narration_style": style,
            "animation_strategy": strategy,
            "layout_preset": preset,
            "teaching_hooks": list(raw_dict.get("teaching_hooks", fallback_response["teaching_hooks"]))
        }
        log_info(f"[SceneDNA] Content classified as {dna_type} with confidence {classified['confidence']:.2f}")
        return classified

    except json.JSONDecodeError as e:
        log_error(f"[SceneDNA] JSON parse error: {e}")
        return fallback_response
    except Exception as e:
        log_error(f"[SceneDNA] Classification failed: {e}")
        return fallback_response
