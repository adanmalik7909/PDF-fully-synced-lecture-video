# -*- coding: utf-8 -*-
"""
SmartStudyInstructor V10 — FFmpeg Pipeline
Pure subprocess FFmpeg — NO MoviePy.

Subtitle strategy (CORRECT):
  - FFmpeg BURNS the SRT file onto the video (synced with audio ✅)
  - HTML template has NO karaoke bar (removed to prevent double subtitles)
  - SRT subtitle styled beautifully: clean pill box, white text, readable size

Composition: slide webm + audio + SRT burn → scene MP4
Final:       xfade crossfade concat → lecture MP4
"""
import os
import subprocess
import shutil
import tempfile
from typing import List, Optional
from app.utils.logger import log_info, log_error


def _run(cmd: List[str], label: str = "FFmpeg") -> bool:
    """Run an FFmpeg command, log errors on failure."""
    try:
        log_info(f"[{label}] Running: {' '.join(cmd[:6])}... ({len(cmd)} args)")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            log_error(f"[{label}] FAILED (rc={result.returncode})")
            log_error(f"[{label}] STDERR (last 3000 chars): {result.stderr[-3000:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        log_error(f"[{label}] TIMEOUT after 600s")
        return False
    except Exception as e:
        log_error(f"[{label}] Exception: {e}")
        return False


def _safe_srt_path(srt_path: str) -> str:
    """
    Make SRT path safe for FFmpeg subtitles filter on Windows.
    Drive letter colon must be escaped: C:/path → C\\:/path
    """
    p = srt_path.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        p = p[0] + "\\:" + p[2:]
    return p


class FFmpegPipeline:

    # ── Beautiful subtitle style ──────────────────────────────────────
    # Uses ASS force_style. BorderStyle=3 = outline+shadow box.
    # PrimaryColour ABGR: white=&H00FFFFFF, gold=&H0053A8D4
    _SUBTITLE_STYLE = (
        "FontName=Arial,"
        "FontSize=22,"
        "PrimaryColour=&H00FFFFFF,"      # white text
        "OutlineColour=&H00000000,"      # black outline
        "BackColour=&HAA000000,"         # 67% opaque dark background
        "Bold=1,"
        "Italic=0,"
        "Outline=2,"
        "Shadow=0,"
        "BorderStyle=3,"                 # box with outline
        "Alignment=2,"                   # bottom-center
        "MarginV=100,"                   # 100px from bottom
        "MarginL=540,"                   # 540px from left (clears the 288px avatar at x=236)
        "MarginR=120"
    )

    def compose_scene(
        self,
        webm_path:   str,
        audio_path:  str,
        srt_path:    Optional[str],
        mood:        str,
        output_path: str,
        avatar_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        Compose one scene:
        1. Mux webm + audio → MP4
        2. BURN SRT subtitles (FFmpeg, synced with audio) → Final MP4
        Falls back to simple mux if SRT burn fails.
        """
        if not os.path.exists(webm_path):
            log_error(f"[FFmpeg] webm not found: {webm_path}")
            return None
        if not os.path.exists(audio_path):
            log_error(f"[FFmpeg] audio not found: {audio_path}")
            return None

        log_info(f"[FFmpeg] Composing → {os.path.basename(output_path)}")

        # Try SRT burn if file is available and non-empty
        use_srt = (
            srt_path is not None
            and os.path.exists(srt_path)
            and os.path.getsize(srt_path) > 10
        )

        if use_srt:
            log_info(f"[FFmpeg] ✅ Burning ASS subtitles → {os.path.basename(srt_path)} ({os.path.getsize(srt_path)} bytes)")
            result = self._mux_with_ass(webm_path, audio_path, srt_path, output_path, avatar_path, mood)
            if result:
                return result
            log_error("[FFmpeg] ⚠️ ASS burn failed — falling back to simple mux (NO subtitles)")
        else:
            log_info(f"[FFmpeg] ⚠️ No ASS subtitles: srt_path={srt_path}, exists={os.path.exists(srt_path) if srt_path else 'N/A'}")

        return self._simple_mux(webm_path, audio_path, output_path)

    def _mux_with_ass(
        self,
        webm_path:   str,
        audio_path:  str,
        ass_path:    str,
        output_path: str,
        avatar_path: Optional[str] = None,
        scene_type:  str = "concept"
    ) -> Optional[str]:
        """Mux webm + audio, burn ASS subtitles, and optionally overlay Kaggle avatar."""
        safe_ass = _safe_srt_path(ass_path)
        
        # Premium Circular Avatar Design (280px circle with 4px border)
        avatar_size = 280 
        border_size = 4
        total_size = avatar_size + (border_size * 2)
        accent_color = "3B82F6" # Royal Blue (No 0x prefix for FFmpeg colors)
        
        if avatar_path and os.path.exists(avatar_path):
            is_video = avatar_path.lower().endswith(".mp4")
            
            # Use geq-based alpha mask (more compatible than lutalpha)
            # geq sets alpha to 255 inside a circle, 0 outside
            half = avatar_size // 2
            circle_mask = f"geq=lum='p(X,Y)':a='if(lt(sqrt(pow(X-{half},2)+pow(Y-{half},2)),{half}),255,0)'"
            half_ring = total_size // 2
            ring_mask = f"geq=lum='p(X,Y)':a='if(lt(sqrt(pow(X-{half_ring},2)+pow(Y-{half_ring},2)),{half_ring}),255,0)'"
            
            filter_complex = (
                f"[1:v]scale={avatar_size}:{avatar_size},format=yuva420p,{circle_mask}[av];"
                f"color=c=0x{accent_color}:s={total_size}x{total_size}:d=1,format=yuva420p,{ring_mask}[ring];"
                f"[ring][av]overlay={border_size}:{border_size}[styled_av];"
                f"[0:v][styled_av]overlay=236:H-h-80[tmp_v];"
                f"[tmp_v]ass='{safe_ass}'[vout]"
            )
            
            cmd = [
                "ffmpeg", "-y",
                "-i", webm_path,
            ]
            
            if not is_video:
                cmd.extend(["-loop", "1", "-i", avatar_path])
            else:
                # If it's a lipsync video, we stream_loop it just in case it's shorter than audio
                cmd.extend(["-stream_loop", "-1", "-i", avatar_path])
                
            cmd.extend([
                "-i", audio_path,
                "-filter_complex", filter_complex,
                "-map", "[vout]",
                "-map", "2:a",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                "-movflags", "+faststart",
                output_path
            ])
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", webm_path,
                "-i", audio_path,
                "-filter_complex",
                f"[0:v]ass='{safe_ass}'[vout]",
                "-map", "[vout]",
                "-map", "1:a",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                "-movflags", "+faststart",
                output_path
            ]
            
        ok = _run(cmd, "mux_with_ass")
        if ok and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return output_path
        # Clean partial
        if os.path.exists(output_path):
            os.remove(output_path)
        return None

    def _simple_mux(
        self,
        webm_path:   str,
        audio_path:  str,
        output_path: str,
    ) -> Optional[str]:
        """Simple video + audio mux — reliable fallback (no subtitles)."""
        cmd = [
            "ffmpeg", "-y",
            "-i", webm_path,
            "-i", audio_path,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            output_path
        ]
        ok = _run(cmd, "simple_mux")
        if ok and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return output_path
        return None

    def concat_with_xfade(
        self,
        scene_mp4s:      List[str],
        scene_durations: List[float],   # in ms
        output_path:     str,
        transition_ms:   float = 400.0,
    ) -> Optional[str]:
        """Crossfade-concat all scene MP4s → final lecture MP4."""
        n = len(scene_mp4s)
        if n == 0:
            log_error("[FFmpeg] No scenes to concat.")
            return None
        if n == 1:
            shutil.copy(scene_mp4s[0], output_path)
            log_info(f"[FFmpeg] Single scene → {os.path.basename(output_path)}")
            return output_path

        log_info(f"[FFmpeg] xfade concat {n} scenes…")
        inputs = []
        for mp4 in scene_mp4s:
            inputs += ["-i", mp4]

        transition_sec      = transition_ms / 1000.0
        scene_durations_sec = [d / 1000.0 for d in scene_durations]

        v_filters, prev = [], "0:v"
        cumulative = 0.0
        for i in range(1, n):
            cumulative += scene_durations_sec[i - 1] - transition_sec
            out = f"v{i}" if i < n - 1 else "vfinal"
            v_filters.append(
                f"[{prev}][{i}:v]xfade=transition=fade:"
                f"duration={transition_sec:.2f}:offset={cumulative:.2f}[{out}]"
            )
            prev = out

        a_filters, prev_a = [], "0:a"
        cumulative_a = 0.0
        for i in range(1, n):
            cumulative_a += scene_durations_sec[i - 1] - transition_sec
            out = f"a{i}" if i < n - 1 else "afinal"
            a_filters.append(
                f"[{prev_a}][{i}:a]acrossfade=d={transition_sec:.2f}[{out}]"
            )
            prev_a = out

        filter_complex = ";".join(v_filters + a_filters)
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[vfinal]", "-map", "[afinal]",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "18", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "192k",
            output_path
        ]
        ok = _run(cmd, "xfade_concat")
        if ok and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return output_path

        log_error("[FFmpeg] xfade failed — simple concat fallback")
        return self._simple_concat(scene_mp4s, output_path)

    def _simple_concat(self, scene_mp4s: List[str], output_path: str) -> Optional[str]:
        """Fallback: FFmpeg concat demuxer (no transitions)."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as tmp:
            for mp4 in scene_mp4s:
                abs_p = os.path.abspath(mp4).replace("\\", "/")
                tmp.write(f"file '{abs_p}'\n")
            concat_txt = tmp.name

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_txt,
            "-c", "copy",
            output_path
        ]
        ok = _run(cmd, "simple_concat")
        os.remove(concat_txt)
        if ok and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            return output_path
        return None

    def mix_background_music(
        self,
        video_path:   str,
        music_path:   str,
        output_path:  str,
        music_volume: float = 0.04,
    ) -> Optional[str]:
        """Mix ambient music at low volume. Skips if file not found."""
        if not music_path or not os.path.exists(music_path):
            return video_path
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-stream_loop", "-1", "-i", music_path,
            "-filter_complex",
            f"[1:a]volume={music_volume}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            output_path
        ]
        log_info("[FFmpeg] Mixing background music…")
        ok = _run(cmd, "bg_music")
        return output_path if (ok and os.path.exists(output_path)) else video_path
