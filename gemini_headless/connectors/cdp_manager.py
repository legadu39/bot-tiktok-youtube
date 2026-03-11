# -- coding: utf-8 --
from __future__ import annotations

"""
Gemini Headless — CDP Manager (Critical Mode · NASA++)
Endpoint-agnostic attach with atomic phases, deterministic logs, and a hard
stance on transport failures.

Updates V_Final: 
- Ajout 'Trend Analysis' pour détection de dégradation (Memory Leaks/Zombies).
- Gestion intelligente de l'historique de connexion.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional, Tuple, List, Dict
from urllib.parse import urlparse, urlencode, quote_plus
from playwright.async_api import async_playwright


# ─────────────────────────────────────────────────────────────────────────────
# Logging (JSON lines to logger or STDERR; never STDOUT)
# ─────────────────────────────────────────────────────────────────────────────
def _jlog(logger, evt: str, **payload) -> None:
    payload.setdefault("ts", time.time())
    try:
        line = json.dumps({"evt": evt, **payload}, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        line = json.dumps({"evt": evt, "unserializable": True}, ensure_ascii=False)
    try:
        if logger and hasattr(logger, "info"):
            logger.info(line)
        else:
            sys.stderr.write(line + "\n")
    except Exception:
        try:
            sys.stderr.write(line + "\n")
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Métriques & Détection de Dégradation (Intelligence)
# ─────────────────────────────────────────────────────────────────────────────
class PerformanceTracker:
    """Suit les performances de connexion pour détecter la dégradation."""
    _METRICS_FILE = Path(".cdp_metrics.json")
    _MAX_HISTORY = 10
    
    @classmethod
    def record_attach_time(cls, ms: int, logger=None):
        try:
            history = cls._load_history()
            history.append(ms)
            if len(history) > cls._MAX_HISTORY:
                history = history[-cls._MAX_HISTORY:]
            cls._save_history(history)
            
            # Analyse de tendance
            if len(history) >= 5:
                avg = sum(history) / len(history)
                # Si le temps actuel est 3x supérieur à la moyenne et > 200ms
                if ms > (avg * 3) and avg > 200:
                    _jlog(logger, "browser_degradation_detected", current=ms, avg=int(avg), action="recommend_restart")
                    return True # Signal de dégradation
        except Exception:
            pass
        return False

    @classmethod
    def _load_history(cls) -> List[int]:
        try:
            if cls._METRICS_FILE.exists():
                with open(cls._METRICS_FILE, "r") as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    @classmethod
    def _save_history(cls, history: List[int]):
        try:
            with open(cls._METRICS_FILE, "w") as f:
                json.dump(history, f)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# URL helpers
# ─────────────────────────────────────────────────────────────────────────────
def _is_ws_endpoint(u: str) -> bool:
    try:
        return u.strip().lower().startswith(("ws://", "wss://"))
    except Exception:
        return False


def _is_http_root(u: str) -> bool:
    try:
        pr = urlparse(u)
        if pr.scheme.lower() not in ("http", "https"):
            return False
        return True
    except Exception:
        return False


def _http_root_base(u: str) -> str:
    pr = urlparse(u)
    base = f"{pr.scheme}://{pr.netloc}"
    return base.rstrip("/")


async def _playwright_connect(pw, url: str):
    return await pw.chromium.connect_over_cdp(url)


# ─────────────────────────────────────────────────────────────────────────────
# HTTP helpers (for /json/* on root endpoint) — non-blocking via to_thread
# ─────────────────────────────────────────────────────────────────────────────
def _sync_http_get_json(url: str) -> Optional[Any]:
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=2.5) as resp:
            if resp.status != 200:
                return None
            raw = resp.read()
            return json.loads(raw.decode("utf-8", "ignore"))
    except Exception:
        return None


async def _http_get_json(url: str) -> Optional[Any]:
    return await asyncio.to_thread(_sync_http_get_json, url)


async def _http_create_target(http_root: str, target_url: str, logger=None) -> bool:
    try:
        quoted = quote_plus(target_url)
        q = f"{http_root.rstrip('/')}/json/new?{quoted}"
        data = await _http_get_json(q)
        ok = bool(data and isinstance(data, dict) and data.get("id"))
        _jlog(logger, "cdp_create_target", ok=ok, url=target_url)
        return ok
    except Exception as e:
        _jlog(logger, "cdp_warning", msg="json_new_failed", error=str(e))
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Page/context discovery & probing
# ─────────────────────────────────────────────────────────────────────────────
def _pick_context_with_pages(browser) -> Optional[Any]:
    try:
        for ctx in list(browser.contexts):
            try:
                if list(getattr(ctx, "pages", [])):
                    return ctx
            except Exception:
                continue
    except Exception:
        pass
    return None


def _count_all_pages(browser) -> int:
    try:
        n = 0
        for ctx in list(browser.contexts):
            try:
                n += len(list(getattr(ctx, "pages", [])))
            except Exception:
                continue
        return n
    except Exception:
        return 0


async def _wait_pages(browser, *, deadline_s: float, logger=None) -> Optional[Any]:
    end = time.monotonic() + float(deadline_s)
    last = -1
    while time.monotonic() < end:
        await asyncio.sleep(0.20)
        n = _count_all_pages(browser)
        if n != last:
            _jlog(logger, "cdp_wait_page", pages=n)
            last = n
        if n >= 1:
            ctx = _pick_context_with_pages(browser)
            if ctx is not None:
                return ctx
    _jlog(logger, "cdp_wait_page", pages=_count_all_pages(browser))
    return None


async def _probe_cdp_session(context, logger=None, *, t0: Optional[float] = None) -> bool:
    """
    Hard gate against dead transports.
    Logs attach_ms and updates performance tracker.
    """
    try:
        pages = list(getattr(context, "pages", []))
        if not pages:
            ms = int((time.monotonic() - t0) * 1000) if t0 is not None else None
            _jlog(logger, "cdp_attach", ok=False, error="no_pages", hard=False, attach_ms=ms)
            return False
        
        page = pages[-1]
        cdp = await context.new_cdp_session(page)
        try:
            await cdp.send("Runtime.enable")
            await cdp.send("Runtime.evaluate", {"expression": "1+1"})
        finally:
            try:
                await cdp.detach()
            except Exception:
                pass
        
        ms = int((time.monotonic() - t0) * 1000) if t0 is not None else None
        if ms is not None:
            is_degraded = PerformanceTracker.record_attach_time(ms, logger)
            _jlog(logger, "cdp_attach", ok=True, attach_ms=ms, degraded=is_degraded)
        else:
            _jlog(logger, "cdp_attach", ok=True)
            
        return True
    except Exception as e:
        msg = str(e) or ""
        hard = ("NoneType" in msg and ".send" in msg) or "detached" in msg.lower() or "closed" in msg.lower()
        ms = int((time.monotonic() - t0) * 1000) if t0 is not None else None
        _jlog(logger, "cdp_attach", ok=False, error=msg, hard=hard, attach_ms=ms)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# WS-only target creation via pure CDP
# ─────────────────────────────────────────────────────────────────────────────
async def _ws_create_target_via_cdp(browser, *, url: str, logger=None) -> bool:
    try:
        bcdp = await browser.new_browser_cdp_session()
        try:
            out = await bcdp.send("Target.createTarget", {"url": url or "about:blank"})
            ok = bool(out and out.get("targetId"))
            _jlog(logger, "cdp_create_target", ok=ok, url=url or "about:blank")
            return ok
        finally:
            try:
                await bcdp.detach()
            except Exception:
                pass
    except Exception as e:
        _jlog(logger, "cdp_warning", msg="ws_create_target_failed", error=str(e))
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Atomic attach_or_spawn
# ─────────────────────────────────────────────────────────────────────────────
async def attach_or_spawn(cfg: Any, *, logger: Any | None = None) -> Tuple[Any, Any]:
    """
    Attach to an existing Chrome via CDP (preferred) or spawn Chromium when allowed.
    """
    allow_spawn = os.getenv("ALLOW_SPAWN", "1") != "0"
    cdp_url: Optional[str] = getattr(cfg, "cdp_url", None)
    headless: bool = bool(getattr(cfg, "headless", False))
    use_cdp = bool(cdp_url) or not allow_spawn
    
    if not use_cdp and not allow_spawn:
        raise RuntimeError("ALLOW_SPAWN=0 and no cdp_url provided")

    async def _cleanup_pw(pw, browser):
        try:
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
        finally:
            try:
                await pw.stop()
            except Exception:
                pass

    async def _do_connect_once() -> Tuple[Any, Any, Any]:
        t0 = time.monotonic()
        pw = await async_playwright().start()
        browser = None
        try:
            if use_cdp:
                if not cdp_url:
                    raise RuntimeError("cdp_url required for CDP attach")
                
                browser = await _playwright_connect(pw, cdp_url)
                setattr(browser, "_pw_handle", pw)
                _jlog(logger, "cdp_connect", ok=True, url=cdp_url)

                ctx = _pick_context_with_pages(browser)

                if ctx is None:
                    if _is_http_root(cdp_url):
                        root = _http_root_base(cdp_url)
                        await _http_create_target(root, "about:blank", logger=logger)
                        await _http_create_target(root, "https://gemini.google.com/app", logger=logger)
                    else:
                        await _ws_create_target_via_cdp(browser, url="about:blank", logger=logger)
                        await _ws_create_target_via_cdp(browser, url="https://gemini.google.com/app", logger=logger)

                    ctx = await _wait_pages(browser, deadline_s=5.0, logger=logger)
                    if ctx is None:
                        if _is_http_root(cdp_url):
                            listing = await _http_get_json(_http_root_base(cdp_url) + "/json")
                            _jlog(logger, "cdp_debug_targets", count=len(listing or []))
                        raise RuntimeError("No context with pages after target creation")

                if not await _probe_cdp_session(ctx, logger=logger, t0=t0):
                    raise RuntimeError("cdp_probe_failed")

                return pw, browser, ctx

            # Spawn path
            browser = await pw.chromium.launch(headless=headless)
            setattr(browser, "_pw_handle", pw)
            _jlog(logger, "spawn_browser", ok=True, headless=headless)
            context = await browser.new_context()
            try:
                page = await context.new_page()
                _ = page
            except Exception:
                pass
            _jlog(logger, "cdp_wait_page", pages=len(list(getattr(context, "pages", []))))
            
            if not await _probe_cdp_session(context, logger=logger, t0=t0):
                raise RuntimeError("cdp_probe_failed_spawn")
            return pw, browser, context

        except Exception:
            await _cleanup_pw(pw, browser)
            raise

    attempt = 0
    last_err: Optional[str] = None
    while attempt < 2:
        try:
            pw, browser, context = await _do_connect_once()
            return browser, context
        except Exception as e:
            msg = str(e) or repr(e)
            last_err = msg
            hard = ("NoneType" in msg and ".send" in msg) or "cdp_probe_failed" in msg or "closed" in msg.lower()
            _jlog(logger, "cdp_attach_error", attempt=attempt, error=msg, hard=hard)
            attempt += 1
            if attempt >= 2:
                break
            try:
                await asyncio.sleep(0.35)
            except Exception:
                pass

    raise RuntimeError(f"attach_or_spawn_failed: {last_err or 'unknown'}")


__all__ = ["attach_or_spawn"]