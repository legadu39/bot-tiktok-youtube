### gemini_headless/utils/session_guardian.py
# -*- coding: utf-8 -*-
"""
session_guardian.py — SessionGuardian Nasa++ (Critical Mode Extrême)
Updates V_Final: Predictive Maintenance (Learning MTTF) + Heartbeat
"""

from __future__ import annotations

import json
import time
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

# Import "Page" uniquement pour l'analyse statique
if TYPE_CHECKING:
    from playwright.async_api import Page, BrowserContext


# ---------------------------------------------------------------------------
# Logging JSON homogène
# ---------------------------------------------------------------------------
def _jsonlog(logger: Any, level: str, payload: Dict[str, Any]) -> None:
    payload.setdefault("ts", time.time())
    payload.setdefault("lvl", level.upper())
    try:
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        
        if logger and hasattr(logger, "info"):
            if payload["lvl"] == "INFO":
                logger.info(payload)
            elif payload["lvl"] == "WARNING" and hasattr(logger, "warning"):
                logger.warning(payload)
            elif payload["lvl"] == "ERROR" and hasattr(logger, "error"):
                logger.error(payload)
            else:
                sys.stderr.write(line)
                sys.stderr.flush()
        else:
            sys.stderr.write(line)
            sys.stderr.flush()
    except Exception:
        try:
            sys.stderr.write(json.dumps({"evt": "jlog_guardian_fallback", "lvl": "ERROR"}) + "\n")
            sys.stderr.flush()
        except Exception:
            pass 


class SessionGuardian:
    """
    Guardian de session avec intelligence prédictive (MTTF) et Heartbeat actif.
    """

    # Seuil de base
    DEFAULT_STALE_THRESHOLD_S = 300.0
    
    def __init__(self, profile_root: Path, logger: Any):
        self.profile_root = Path(profile_root)
        self.logger = logger
        self.stats_file = self.profile_root / "session_stats.json"
        
        # Predictive State
        self.session_start_ts = time.time()
        self.avg_lifespan = 3600.0 # Par défaut 1h
        self._load_stats()

    def _load_stats(self):
        try:
            if self.stats_file.exists():
                with open(self.stats_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.avg_lifespan = data.get("avg_lifespan", 3600.0)
        except Exception:
            pass

    def _save_stats(self):
        try:
            data = {"avg_lifespan": self.avg_lifespan, "last_updated": time.time()}
            with open(self.stats_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    def update_failure_stats(self, duration_alive: float):
        """Apprend la durée de vie réelle de la session."""
        if duration_alive > 60: # On ignore les échecs immédiats (bruit)
            # Moyenne exponentielle lissée (alpha=0.2)
            self.avg_lifespan = (self.avg_lifespan * 0.8) + (duration_alive * 0.2)
            self._save_stats()
            _jsonlog(self.logger, "INFO", {"evt": "guardian_learned_lifespan", "new_avg_s": int(self.avg_lifespan)})

    async def check_login_wall(self, page: "Page") -> bool:
        """
        Intelligence: Vérifie si on est bloqué sur une page de login explicite.
        Permet de 'fail-fast' au lieu d'attendre un timeout.
        """
        try:
            # Sélecteurs typiques de la page de login Google
            login_indicators = [
                "input[type='email']",
                "#identifierId",
                "text=Connexion",
                "text=Sign in",
                "a[href*='accounts.google.com/ServiceLogin']"
            ]
            
            for selector in login_indicators:
                if await page.locator(selector).is_visible():
                     _jsonlog(self.logger, "ERROR", {"evt": "guardian_login_wall_detected", "selector": selector})
                     return True
            return False
        except Exception:
            return False

    # -----------------------------------------------------------------------
    # API publique
    # -----------------------------------------------------------------------
    async def health(
        self,
        page: Optional["Page"] = None,
        *,
        required_cookie_names: Optional[List[str]] = None,
        cookie_domains: Optional[List[str]] = None,
        timeout_s: float = 5.0,
    ) -> Dict[str, Any]:
        """
        Vérifie l'état de la session. Ne jette **jamais**.
        """
        required = required_cookie_names or [
            "SAPISID", "SID", "__Secure-1PSID", "__Secure-3PSID"
        ]
        domains = cookie_domains or [
            ".google.com", "google.com", ".gemini.google.com", "gemini.google.com"
        ]

        out: Dict[str, Any] = {
            "ok": False,
            "status": "unknown",
            "err": None,
            "page_closed": False,
            "missing": [],
            "present": [],
            "domain_sample": domains[:],
            "min_remaining_s": 999999.9,
        }

        # Cas page absente
        if page is None:
            out["err"] = "page_none"
            out["status"] = "dead"
            return out

        # Cas page fermée
        try:
            if hasattr(page, "is_closed") and page.is_closed():
                out["err"] = "page_closed"
                out["page_closed"] = True
                out["status"] = "dead"
                return out
        except Exception:
            out["err"] = "page_closed_check_failed"
            out["page_closed"] = True
            out["status"] = "error"
            return out

        # Check DOM Login Wall (Fail Fast)
        if await self.check_login_wall(page):
            out["err"] = "login_wall_visible"
            out["status"] = "dead"
            out["ok"] = False
            return out

        # Récupération cookies via context (non bloquant)
        try:
            ctx = getattr(page, "context", None)() if callable(getattr(page, "context", None)) else getattr(page, "context", None)
        except Exception:
            ctx = None

        if not ctx:
            out["err"] = "no_context"
            out["status"] = "error"
            return out

        try:
            cookies = await ctx.cookies()
        except Exception as e:
            out["err"] = f"cookies_error: {e}"
            out["status"] = "error"
            return out

        # Filtrer cookies par domaine et collecter les noms + expiration
        names_present: List[str] = []
        min_expiry_ts = float('inf')
        now = time.time()
        
        try:
            for c in cookies or []:
                try:
                    dom = (c.get("domain") if isinstance(c, dict) else getattr(c, "domain", "")) or ""
                    name = (c.get("name") if isinstance(c, dict) else getattr(c, "name", "")) or ""
                    expires = (c.get("expires") if isinstance(c, dict) else getattr(c, "expires", -1)) or -1
                except Exception:
                    dom, name, expires = "", "", -1
                
                if not name:
                    continue
                
                if any(d in (dom or "") for d in domains):
                    if name not in names_present:
                        names_present.append(name)
                    
                    # Check expiry si c'est un cookie critique
                    if name in required and expires > 0:
                        if expires < min_expiry_ts:
                            min_expiry_ts = expires
        except Exception:
            pass

        missing = [n for n in required if n not in names_present]
        out["present"] = sorted(names_present)
        out["missing"] = missing

        # Évaluation de la fraîcheur
        if min_expiry_ts != float('inf'):
            out["min_remaining_s"] = max(0.0, min_expiry_ts - now)

        if missing:
            out["ok"] = False
            out["status"] = "dead"
            out["err"] = f"missing_cookies: {missing}"
            self.update_failure_stats(time.time() - self.session_start_ts)
        elif out["min_remaining_s"] < self.DEFAULT_STALE_THRESHOLD_S:
            out["ok"] = True 
            out["status"] = "stale"
            out["err"] = "cookies_expiring_soon"
        else:
            out["ok"] = True
            out["status"] = "healthy"

        return out

    def is_maintenance_due(self, health_stats: Dict[str, Any], last_interaction_ts: float) -> bool:
        """
        Intelligence: Détermine si une maintenance préventive est nécessaire
        en fonction de la santé de la session, de l'inactivité ET des statistiques prédictives.
        """
        now = time.time()
        min_remaining = health_stats.get("min_remaining_s", 999999)
        status = health_stats.get("status", "unknown")
        
        # Critère 1 : Session en danger immédiat (Stale)
        if status == "stale":
            return True
        
        # Critère 2 (Predictive): On approche de la fin de vie moyenne connue pour ce profil
        time_alive = now - self.session_start_ts
        predictive_threshold = self.avg_lifespan * 0.90 # Marge de 10%
        if time_alive > predictive_threshold:
             _jsonlog(self.logger, "INFO", {
                "evt": "predictive_maintenance_trigger",
                "time_alive_s": int(time_alive),
                "avg_lifespan_s": int(self.avg_lifespan)
            })
             return True

        # Critère 3 : Session proche de la zone dangereuse (< 10 min) ET inactivité prolongée (> 5 min)
        time_since_action = now - last_interaction_ts
        maintenance_threshold = 600.0
        if min_remaining < maintenance_threshold and time_since_action > 300:
            return True
            
        return False

    async def opportunistic_maintenance_check(
        self,
        page: Optional["Page"],
        last_activity_ts: float
    ) -> bool:
        """
        Exécute une vérification opportuniste durant Idle Time.
        """
        try:
            if not page or (hasattr(page, "is_closed") and page.is_closed()):
                return False
                
            now = time.time()
            if (now - last_activity_ts) < 300:
                return False

            h = await self.health(page)
            remaining = h.get("min_remaining_s", 99999)
            
            # Plus agressif si on est idle
            if remaining < 1200: 
                await self.repair_if_needed(page)
                return True
                
        except Exception:
            pass
        return False

    async def repair_if_needed(
        self,
        page: Optional["Page"],
        *,
        timeout_s: float = 30.0,
    ) -> Dict[str, Any]:
        """
        Tentative **non-invasive** de réparation.
        """
        result = {
            "ok": True,
            "attempted": False,
            "err": None,
            "need_reset": False,
        }

        # Vérification initiale
        h = await self.health(page)
        
        # Si c'est Healthy, on ne touche à rien
        if h.get("status") == "healthy":
            return result

        # Si Stale ou Dead, on intervient
        is_stale = h.get("status") == "stale"
        reason_log = "stale_preventive_refresh" if is_stale else "dead_recovery"

        result["ok"] = False
        result["attempted"] = True

        if page is None or (hasattr(page, "is_closed") and page.is_closed()):
            result["err"] = "page_none_or_closed"
            return result

        _jsonlog(self.logger, "INFO", {
            "evt": "session_repair_start",
            "reason": reason_log,
            "profile_dir": str(self.profile_root),
        })

        # Étape 1 : navigation / reload
        try:
            if is_stale:
                 await page.reload(wait_until="domcontentloaded", timeout=int(timeout_s * 1000))
            else:
                 await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=int(timeout_s * 1000))
            await _safe_sleep(0.6)
        except Exception as e:
            _jsonlog(self.logger, "WARNING", {"evt": "session_repair_nav_error", "err": str(e)})

        # Consent best-effort
        if not is_stale:
            try:
                from gemini_headless.utils.consent_detector import ConsentDetector 
                try:
                    if hasattr(ConsentDetector, "handle_if_present"):
                        await ConsentDetector.handle_if_present(page, timeout_ms=10_000, retries=1)
                    else:
                        cd = ConsentDetector(page, logger=self.logger)
                        await cd.skip_if_present(timeout_ms=10_000)
                except Exception:
                    pass
            except Exception:
                pass

        # Étape 2 : reload de confirmation
        if not is_stale:
            try:
                await page.reload(wait_until="domcontentloaded", timeout=int(timeout_s * 1000))
                await _safe_sleep(0.5)
            except Exception:
                pass

        # Étape 3 : re-check
        h2 = await self.health(page)
        
        if not h2.get("ok", False):
            result["ok"] = False
            result["need_reset"] = True
            result["err"] = "cookies_missing_after_repair"
            await self.mark_profile_for_reset(reason=result["err"], details={"missing": h2.get("missing", [])})
            _jsonlog(self.logger, "WARNING", {
                "evt": "session_repair_failed",
                "missing": h2.get("missing", []),
            })
            return result
        
        if is_stale and h2.get("status") == "stale":
             _jsonlog(self.logger, "WARNING", {
                "evt": "session_repair_still_stale",
                "msg": "Refresh did not extend cookies. Continuing anyway.",
            })

        # Reset timer start on success
        self.session_start_ts = time.time()
        
        result["ok"] = True
        _jsonlog(self.logger, "INFO", {
            "evt": "session_repair_ok",
            "profile_dir": str(self.profile_root),
        })
        return result

    async def mark_profile_for_reset(self, reason: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Marque le profil comme nécessitant un reset."""
        payload = {
            "ts": time.time(),
            "reason": reason,
            "details": details or {},
        }
        try:
            path = self.profile_root / ".reset_log.json"
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    async def lightweight_heartbeat(self, context: "BrowserContext") -> bool:
        """
        🧠 INTELLIGENCE N°2 : Heartbeat Prédictif et Léger.
        Effectue une requête HTTP GET ultra-légère via le contexte réseau de Playwright.
        Ne charge pas le DOM complet, économise le CPU, mais détecte si Google a invalidé le cookie
        (détection de redirection vers accounts.google.com).
        """
        try:
            _jsonlog(self.logger, "INFO", {"evt": "heartbeat_ping_started"})
            
            # Requête API sans interagir avec la page web visible
            response = await context.request.get(
                "https://gemini.google.com/app",
                max_redirects=0,  # Important : On veut intercepter la redirection, pas la suivre
                timeout=5000
            )
            
            # 301/302/303/307 indique une redirection de sécurité (vers la page de login)
            if response.status in [301, 302, 303, 307, 308]:
                location = response.headers.get("location", "")
                if "accounts.google.com" in location or "ServiceLogin" in location:
                    _jsonlog(self.logger, "ERROR", {"evt": "heartbeat_dead_session_redirect", "location": location})
                    self.update_failure_stats(time.time() - self.session_start_ts)
                    await self.mark_profile_for_reset(reason="heartbeat_redirect_to_login")
                    return False
            
            # API ou endpoint renvoyant un 401 direct
            if response.status == 401:
                _jsonlog(self.logger, "ERROR", {"evt": "heartbeat_dead_session_401"})
                return False

            _jsonlog(self.logger, "INFO", {"evt": "heartbeat_ping_ok", "status": response.status})
            return True
            
        except Exception as e:
            # En cas de problème réseau pur, on part du principe que la session est bonne
            # pour éviter un faux positif.
            _jsonlog(self.logger, "WARNING", {"evt": "heartbeat_ping_failed_network", "err": str(e)})
            return True

async def _safe_sleep(seconds: float) -> None:
    try:
        import asyncio
        await asyncio.sleep(max(0.0, float(seconds)))
    except Exception:
        pass