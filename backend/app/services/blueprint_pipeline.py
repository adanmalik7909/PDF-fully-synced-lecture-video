# -*- coding: utf-8 -*-
"""
SmartStudyInstructor V10 — Blueprint Pipeline
Timeline-Driven Architecture:
  TTS Engine → Timeline Builder → Scene Router → Playwright → FFmpeg

No MoviePy. No Librosa. Pure FFmpeg + edge-tts WordBoundary timestamps.
"""
import os
import sys
import tempfile
import uuid
import base64
import mimetypes
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from app.utils.logger import log_info, log_error
from app.config import settings

DEFAULT_AVATAR_PATH = "static/avatars/my_avatar.jpg"


def _safe_print(msg: str):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def _encode_image_b64(path: str) -> Optional[str]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        mime, _ = mimetypes.guess_type(path)
        return f"data:{mime or 'image/png'};base64,{data}"
    except Exception as e:
        log_error(f"[B64 encode] {path}: {e}")
        return None


class BlueprintPipeline:
    """
    V10 Timeline-Driven Pipeline.
    Orchestrates: TTS → Timeline → HTML → Playwright → FFmpeg.
    """

    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or settings.VIDEO_FOLDER
        os.makedirs(self.output_dir, exist_ok=True)
        self.temp_dir = tempfile.mkdtemp(prefix="blueprint_v10_")
        # Semaphore(1): Send only 1 scene at a time to Kaggle to prevent GPU race conditions
        self.semaphore = asyncio.Semaphore(1)
        # UPGRADE C: Semaphore(3) limits concurrent Playwright browsers to avoid memory crashes
        self.pw_semaphore = asyncio.Semaphore(3)
        log_info(f"[V14 Pipeline] Temp dir: {self.temp_dir}")

    def cleanup(self):
        import shutil, time
        for _ in range(3):
            try:
                shutil.rmtree(self.temp_dir)
                return
            except Exception:
                time.sleep(1)

    # ─────────────────────────────────────────────────────────────────────
    # Single-scene builder (runs in thread)
    # ─────────────────────────────────────────────────────────────────────

    async def _build_scene(
        self,
        scene_data:   Dict,
        scene_index:  int,
        total_scenes: int,
        avatar_path:  str,
        tts_result:   Dict,
    ) -> Optional[str]:
        """
        Given a pre-computed tts_result (from TTS Engine), build one scene:
          1. Resolve diagram images to base64
          2. Build Timeline JSON
          3. Render Jinja2 HTML (with TIMELINE_DATA embedded)
          4. Record via Playwright
          5. Compose via FFmpeg (mux + SRT subtitles)
        Returns path to final scene .mp4
        """
        from core.timeline_builder import TimelineBuilder
        from rendering.scene_router import SceneRouter
        from rendering.playwright_capture import record_scene_video
        from rendering.ffmpeg_pipeline import FFmpegPipeline

        scene_id = str(scene_data.get("scene_id", f"scene_{scene_index+1}"))
        _safe_print(f"  [V10] Building scene {scene_index+1}/{total_scenes}: {scene_id}")

        if not tts_result:
            log_error(f"  [V10] TTS result missing for {scene_id} — skipping.")
            return None

        audio_path       = tts_result["audio_path"]
        words            = tts_result["words"]
        total_duration_ms = tts_result["total_duration_ms"]
        srt_path         = tts_result.get("srt_path")

        scene_data["scene_index"] = scene_index + 1
        scene_data["total_scenes"] = total_scenes
        scene_data["duration_sec"] = total_duration_ms / 1000.0

        # -- Resolve diagrams → base64 and keep track of valid disk paths --
        refs = scene_data.get("diagram_refs", [])
        if not refs and scene_data.get("diagram_ref"):
            refs = [scene_data["diagram_ref"]]

        resolved_diagrams = []
        resolved_refs = []
        for ref in refs:
            candidates = [
                ref,                                                        # exact path from LLM/injection
                os.path.join("static/uploads/diagrams", os.path.basename(str(ref))),  # where extract_images_from_pdf saves
                os.path.join("static/assets/extracted_diagrams", os.path.basename(str(ref))),  # legacy
                os.path.join("static/uploads", os.path.basename(str(ref))),  # generic uploads
            ]
            for c in candidates:
                b64 = _encode_image_b64(c)
                if b64:
                    resolved_diagrams.append(b64)
                    resolved_refs.append(c)
                    _safe_print(f"    [Diagram] Resolved: {c}")
                    break
            else:
                _safe_print(f"    [Diagram] WARNING: Could not resolve: {ref}")

        scene_data["diagram_paths"] = resolved_diagrams
        scene_data["diagram_refs"] = resolved_refs
        if resolved_diagrams:
            scene_data["diagram_path"] = resolved_diagrams[0]
            _safe_print(f"    [Diagram] {len(resolved_diagrams)} diagram(s) loaded for scene {scene_id}")


        # -- Avatar Generation (Kaggle Cloud Wav2Lip) --
        actual_avatar = avatar_path or DEFAULT_AVATAR_PATH
        is_lipsync = False
        
        # Use Kaggle Cloud Client if URL is configured
        cloud_url = settings.CLOUD_RENDER_URL.strip() if settings.CLOUD_RENDER_URL else ""
        if cloud_url:
            from app.services.kaggle_client import KaggleCloudClient
            kaggle = KaggleCloudClient(cloud_url)
            _safe_print(f"    [Kaggle] Requesting lipsync for {scene_id} via '{cloud_url}'...")
            
            try:
                import time
                t0 = time.time()
                # Use semaphore to prevent overloading the single GPU on Kaggle
                async with self.semaphore:
                    lipsync_video = await kaggle.generate_lipsync(
                        scene_id=scene_id,
                        audio_path=audio_path,
                        avatar_image_path=actual_avatar
                    )
                
                if lipsync_video and os.path.exists(lipsync_video):
                    actual_avatar = lipsync_video
                    is_lipsync = True
                    elapsed = time.time() - t0
                    _safe_print(f"    [Kaggle] Lipsync success in {elapsed:.2f}s: {os.path.basename(actual_avatar)}")
                else:
                    _safe_print(f"    [Kaggle] Warning: Lipsync failed or returned empty. Using static.")
            except Exception as e:
                log_error(f"    [Kaggle] Exception: {e}")
                _safe_print(f"    [Kaggle] Error: Using static fallback.")
        else:
            _safe_print("    [Kaggle] No CLOUD_RENDER_URL. Using static avatar.")
            
        # We KEEP the avatar_path for the HTML so the JS logic (avatar-wrap) doesn't crash.
        # But we set a flag so the template can hide it if we are going to overlay it via FFmpeg.
        scene_data["avatar_path"] = avatar_path or DEFAULT_AVATAR_PATH
        scene_data["avatar_config"] = {
            "visible": True,
            "is_lipsync": is_lipsync,
            "hidden_for_ffmpeg": True  # Always hide HTML avatar; FFmpeg handles both lipsync and static overlay
        }

        scene_data["_audio_path"] = audio_path  # for TimelineBuilder

        # -- Build Master Timeline JSON --
        builder = TimelineBuilder(scene=scene_data, words=words, total_ms=total_duration_ms)
        timeline_data = builder.build()

        # NOTE: Animation Brain events are already injected inside TimelineBuilder.build()
        # via the generate_animation_script() function call. No duplicate call needed here.

        # -- Render HTML (with TIMELINE_DATA injected) --
        router = SceneRouter()
        html = router.render_scene_html(scene_data, timeline_data=timeline_data)
        if not html:
            log_error(f"  [V10] HTML render failed for {scene_id}")
            return None

        # -- Playwright: record .webm (runs in isolated thread with its own loop) --
        loop = asyncio.get_event_loop()
        
        # UPGRADE C: Limit to 3 concurrent Playwright processes
        async with self.pw_semaphore:
            webm_path = await loop.run_in_executor(
                None,  # default ThreadPoolExecutor
                lambda: record_scene_video(
                    html_content=html,
                    timeline_data=timeline_data,
                    total_duration_ms=total_duration_ms,
                    output_dir=self.temp_dir,
                    scene_id=scene_id,
                )
            )
        if not webm_path:
            log_error(f"  [V10] Playwright recording failed for {scene_id}")
            return None

        # -- FFmpeg: compose scene MP4 --
        fp = FFmpegPipeline()
        scene_mp4 = os.path.join(self.temp_dir, f"{scene_id}_final.mp4")
        _safe_print(f"    [FFmpeg] Subtitle file: {srt_path}")
        _safe_print(f"    [FFmpeg] Subtitle exists: {os.path.exists(srt_path) if srt_path else False}")
        _safe_print(f"    [FFmpeg] Avatar for overlay: {actual_avatar} (lipsync={is_lipsync})")
        result = fp.compose_scene(
            webm_path=webm_path,
            audio_path=audio_path,
            srt_path=srt_path,
            mood=scene_data.get("scene_mood") or scene_data.get("scene_type", "concept"),
            output_path=scene_mp4,
            avatar_path=actual_avatar,
        )

        if os.path.exists(webm_path):
            os.remove(webm_path)

        _safe_print(f"  [V10] Scene {scene_index+1}/{total_scenes} complete.")
        return result

    # ─────────────────────────────────────────────────────────────────────
    # Main entry point
    # ─────────────────────────────────────────────────────────────────────

    async def render_blueprint(
        self,
        blueprint_json: Dict,
        avatar_path: str = DEFAULT_AVATAR_PATH,
        progress_callback = None,
    ) -> Optional[str]:
        """
        Full V10 pipeline:
        1. TTS all scenes in parallel (asyncio.gather)
        2. Build Timeline + Render + Record in thread pool
        3. FFmpeg xfade concat → final lecture MP4
        """
        from rendering.ffmpeg_pipeline import FFmpegPipeline

        log_info("=" * 60)
        log_info("SmartStudyInstructor V10 — Timeline-Driven Pipeline")
        log_info("=" * 60)

        # -- Normalize scenes list --
        scenes_list = []
        if isinstance(blueprint_json, dict) and "scenes" in blueprint_json:
            scenes_list = blueprint_json["scenes"]
        elif isinstance(blueprint_json, list):
            scenes_list = blueprint_json
        elif isinstance(blueprint_json, dict):
            scenes_list = [blueprint_json[k] for k in sorted(blueprint_json.keys())]

        total = len(scenes_list)
        if total == 0:
            log_error("[V10] Blueprint has no scenes.")
            return None

        log_info(f"  Total scenes: {total}")
        if total == 0:
            log_error("[V14] Blueprint JSON received by pipeline:")
            log_error(str(blueprint_json)[:500])

        if progress_callback:
            progress_callback(10, "Generating voice & timestamps...")

        # -- STEP 1: TTS all scenes in parallel (async, non-blocking) --
        log_info("  STEP 1: TTS synthesis (parallel async)...")
        tts_dir = os.path.join(self.temp_dir, "tts")
        # Use async version directly — we are already in an async context
        from core.tts_engine import synthesize_all_scenes
        tts_results = await synthesize_all_scenes(scenes_list, tts_dir)

        if len(tts_results) != total:
            log_error(f"  TTS returned {len(tts_results)} results for {total} scenes!")

        if progress_callback:
            progress_callback(30, "Rendering animations & lipsync...")

        # -- STEP 2: Build + Render + Record all scenes in parallel --
        log_info("  STEP 2: Timeline + Playwright render (parallel async)…")
        scene_mp4s   = [None] * total
        scene_durations = [0.0] * total
        
        completed_scenes = 0

        async def process(idx, scene_data):
            nonlocal completed_scenes
            tr = tts_results[idx] if idx < len(tts_results) else {}
            dur_ms = tr.get("total_duration_ms", 10000.0)
            scene_durations[idx] = dur_ms
            mp4 = await self._build_scene(scene_data, idx, total, avatar_path, tr)
            completed_scenes += 1
            if progress_callback:
                progress_callback(30 + int((completed_scenes / total) * 50), f"Rendered scene {completed_scenes}/{total}")
            return idx, mp4

        results = await asyncio.gather(*[process(i, s) for i, s in enumerate(scenes_list)])
        for idx, mp4 in results:
            if mp4:
                scene_mp4s[idx] = mp4

        valid_mp4s = [(mp4, scene_durations[i])
                      for i, mp4 in enumerate(scene_mp4s) if mp4]

        if not valid_mp4s:
            log_error("[V10] No scenes rendered successfully.")
            return None

        mp4_paths = [m for m, _ in valid_mp4s]
        durations  = [d for _, d in valid_mp4s]

        if progress_callback:
            progress_callback(85, "Stitching video scenes together...")

        # -- STEP 3: FFmpeg xfade concat --
        log_info(f"  STEP 3: xfade concat of {len(mp4_paths)} scenes…")
        fp = FFmpegPipeline()
        raw_output = os.path.join(self.output_dir, f"lecture_raw_{uuid.uuid4().hex[:8]}.mp4")
        final_video = fp.concat_with_xfade(mp4_paths, durations, raw_output)

        if not final_video:
            log_error("[V10] Concat failed.")
            return None

        # -- STEP 4: Optional background music mix --
        output_path = os.path.join(self.output_dir, f"lecture_{uuid.uuid4().hex[:8]}.mp4")
        bg_music = "static/assets/ambient_music.mp3"
        if os.path.exists(bg_music):
            final_video = fp.mix_background_music(final_video, bg_music, output_path)
        else:
            import shutil
            shutil.move(raw_output, output_path)
            final_video = output_path

        log_info("=" * 60)
        log_info(f"  V10 DONE → {final_video}")
        log_info("=" * 60)
        return final_video
