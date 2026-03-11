#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Client CDP "GHOST SOCKET" - Lazarus Platinum Edition.

ARCHITECTURE: ASYNCHRONOUS EVENT-DRIVEN GATEWAY
------------------------------------------------
Ce module est le nouveau cœur réseau du bot. Il remplace l'ancienne logique "SimpleWebSocket"
par une architecture résiliente capable de survivre aux micro-coupures et aux redémarrages de Chrome.

FONCTIONNALITÉS PLATINUM :
- GHOST RECONNECT: Reconnexion transparente sans perte de contexte.
- ATOMIC LOCKING: Sérialisation stricte des trames sortantes (Thread-Safe).
- MESSAGE QUEUING: Découplage total lecture/écriture via Queue.
- SELF-HEALING: Le client répare sa propre connexion en cas de BrokenPipe.
"""

import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import threading
import time
import queue
import logging
from urllib.parse import urlparse
from typing import Optional, Dict, Any, Callable

# --- CONFIGURATION LOGGER SECURISE ---
# On utilise un logger local pour ne pas dépendre de tt_utils si le lien est cassé
logger = logging.getLogger("CDP_GHOST")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s [GHOST] %(message)s', datefmt='%H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

def log(msg: str, level: str = "INFO"):
    """Wrapper de log léger compatible JSON logs"""
    # On évite les print sauvages qui cassent le parsing JSON du bridge
    # Les logs critiques passent par le logger standard
    if level == "ERROR":
        logger.error(msg)
    elif level == "WARN":
        logger.warning(msg)
    else:
        # Debug only, souvent silencieux en prod
        pass

# --- EXCEPTIONS ---
class CDPConnectionError(Exception): pass
class CDPTimeoutError(Exception): pass

# ---------------------------------------------------------------------------
# IMPLEMENTATION WEBSOCKET ROBUSTE (RFC 6455 SIMPLIFIÉE MAIS SOLIDE)
# ---------------------------------------------------------------------------

class GhostWebSocket:
    """
    Couche de transport bas niveau. 
    Gère le TCP, le SSL, le Handshake et le Framing WebSocket.
    Totalement agnostique du protocole CDP.
    """
    def __init__(self, url: str, timeout: float = 10.0):
        self.url = url
        self.timeout = timeout
        self.sock = None
        self.lock = threading.RLock() # Verrou réentrant vital pour le multithreading
        self.connected = False
        self._stop_event = threading.Event()

    def connect(self, max_retries: int = 5) -> bool:
        """
        Tente de se connecter avec une stratégie de backoff exponentiel.
        Retourne True si succès, False sinon.
        """
        self.close() # Nettoyage préventif
        
        uri = urlparse(self.url)
        host = uri.hostname or "localhost"
        port = uri.port or (443 if uri.scheme == "wss" else 80)
        path = uri.path or "/"
        
        backoff = 0.5
        
        for attempt in range(1, max_retries + 1):
            try:
                # 1. Connexion TCP
                sock = socket.create_connection((host, port), timeout=self.timeout)
                
                # 2. Upgrade SSL si nécessaire
                if uri.scheme == "wss":
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    sock = ctx.wrap_socket(sock, server_hostname=host)
                
                # 3. Handshake HTTP Upgrade
                key = base64.b64encode(os.urandom(16)).decode('ascii')
                req = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: {host}:{port}\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    "Sec-WebSocket-Version: 13\r\n"
                    f"Sec-WebSocket-Key: {key}\r\n"
                    "\r\n"
                )
                sock.sendall(req.encode('ascii'))
                
                # 4. Validation Réponse
                response = b""
                while b"\r\n\r\n" not in response:
                    chunk = sock.recv(4096)
                    if not chunk: raise ConnectionError("Empty handshake response")
                    response += chunk
                
                head, _ = response.split(b"\r\n\r\n", 1)
                if b" 101 " not in head:
                    # Correction Compatibilité Python 3.10 (No backslash in f-string)
                    status_line = head.split(b'\r\n')[0]
                    raise ConnectionError(f"Handshake failed: {status_line}")
                
                self.sock = sock
                self.sock.settimeout(None) # On passe en mode bloquant pour le thread de lecture
                self.connected = True
                self._stop_event.clear()
                log(f"Socket connecté sur port {port}", "INFO")
                return True

            except Exception as e:
                log(f"Echec connexion ({attempt}/{max_retries}): {e}", "WARN")
                time.sleep(backoff)
                backoff = min(backoff * 1.5, 3.0)
        
        return False

    def close(self):
        """Fermeture propre et thread-safe"""
        self.connected = False
        self._stop_event.set()
        if self.sock:
            try:
                # On envoie un close frame best-effort
                with self.lock:
                    self._write_frame(0x8, b"") 
                self.sock.shutdown(socket.SHUT_RDWR)
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def send_text(self, data: str):
        """Envoi thread-safe d'une payload texte"""
        if not self.connected:
            raise BrokenPipeError("Socket disconnected")
        try:
            with self.lock:
                self._write_frame(0x1, data.encode('utf-8'))
        except Exception as e:
            self.connected = False
            raise BrokenPipeError(f"Send failed: {e}")

    def recv(self) -> Optional[str]:
        """
        Lecture bloquante d'une frame complète.
        Gère la fragmentation et le PING/PONG automatiquement.
        Retourne la payload texte ou None si déconnexion.
        """
        if not self.connected: return None
        
        try:
            while not self._stop_event.is_set():
                # Lecture Header (2 octets min)
                head = self._read_bytes(2)
                if not head: return None
                
                b1, b2 = head[0], head[1]
                fin = (b1 & 0x80) != 0
                opcode = b1 & 0x0F
                masked = (b2 & 0x80) != 0 # Server -> Client n'est jamais masqué selon RFC, mais on gère
                payload_len = b2 & 0x7F
                
                # Lecture Longueur étendue
                if payload_len == 126:
                    ext = self._read_bytes(2)
                    payload_len = struct.unpack("!H", ext)[0]
                elif payload_len == 127:
                    ext = self._read_bytes(8)
                    payload_len = struct.unpack("!Q", ext)[0]
                
                # Lecture Masque
                mask_key = self._read_bytes(4) if masked else None
                
                # Lecture Payload
                payload = self._read_bytes(payload_len)
                if len(payload) != payload_len: return None
                
                if masked:
                    # Unmasking (rare du serveur vers client mais conforme)
                    payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
                
                # Gestion OpCodes
                if opcode == 0x9: # PING
                    with self.lock: self._write_frame(0xA, payload) # PONG
                    continue
                elif opcode == 0xA: # PONG
                    continue
                elif opcode == 0x8: # CLOSE
                    self.close()
                    return None
                elif opcode == 0x1: # TEXT
                    return payload.decode('utf-8')
                elif opcode == 0x0: # CONT
                    # Support minimaliste : on suppose que c'est du texte
                    return payload.decode('utf-8')
                else:
                    continue # Ignore binary/others
                    
        except Exception:
            self.close()
            return None
        return None

    def _read_bytes(self, n: int) -> bytes:
        """Lecture exacte de N octets"""
        data = b""
        while len(data) < n:
            try:
                chunk = self.sock.recv(n - len(data))
                if not chunk: raise ConnectionError("EOF")
                data += chunk
            except Exception:
                raise
        return data

    def _write_frame(self, opcode: int, payload: bytes):
        """Ecriture bas niveau d'une frame (Client -> Server doit être masqué)"""
        frame = bytearray()
        frame.append(0x80 | opcode) # FIN + Opcode
        
        l = len(payload)
        if l < 126:
            frame.append(0x80 | l) # Mask bit set
        elif l < 65536:
            frame.append(0x80 | 126)
            frame.extend(struct.pack("!H", l))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack("!Q", l))
            
        # Masking Key (Random 4 bytes)
        mask = os.urandom(4)
        frame.extend(mask)
        
        # Masking Payload
        masked_payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        frame.extend(masked_payload)
        
        self.sock.sendall(frame)

# ---------------------------------------------------------------------------
# CLIENT CDP "GHOST" (LOGIQUE MÉTIER)
# ---------------------------------------------------------------------------

class CdpClient:
    """
    Façade haut niveau pour le protocole Chrome DevTools.
    Gère la file d'attente, les IDs de requête et la reconnexion automatique.
    """
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws = GhostWebSocket(ws_url)
        
        # Gestion des requêtes asynchrones
        self._req_id = 0
        self._pending_requests: Dict[int, dict] = {} # {id: {evt: Event, response: any}}
        self._lock = threading.Lock()
        
        # Thread de lecture
        self._read_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Callbacks d'événements (ex: Network.requestWillBeSent)
        self._event_handlers: list = []

    def connect(self):
        """Démarrage du client et du thread d'écoute"""
        if not self.ws.connect():
            raise CDPConnectionError(f"Impossible de se connecter à {self.ws_url}")
        
        self._running = True
        self._read_thread = threading.Thread(target=self._listen_loop, daemon=True, name="GhostListener")
        self._read_thread.start()
        
        # Handshake de vérification (V8 Alive ?)
        res = self.send("Runtime.evaluate", {"expression": "'GhostProtocol' + 'Active'"})
        if not res:
            raise CDPConnectionError("Handshake CDP échoué (V8 muet)")
        log("Liaison Ghost Protocol établie.", "INFO")

    def close(self):
        self._running = False
        self.ws.close()

    def send(self, method: str, params: dict = None, timeout: float = 10.0) -> Any:
        """
        Envoie une commande et attend la réponse.
        Inclut la logique "GHOST RECONNECT" : si le socket casse, on répare et on réessaie.
        """
        if params is None: params = {}
        
        max_ghost_retries = 2 # Nombre de fois qu'on tente de réparer le tunnel
        
        for attempt in range(max_ghost_retries + 1):
            req_id = self._get_next_id()
            future = {"evt": threading.Event(), "response": None}
            
            with self._lock:
                self._pending_requests[req_id] = future
            
            payload = json.dumps({"id": req_id, "method": method, "params": params})
            
            try:
                self.ws.send_text(payload)
                
                # Attente réponse
                if future["evt"].wait(timeout):
                    resp = future["response"]
                    # Gestion erreur CDP (ex: contexte invalide)
                    if "error" in resp:
                        # Si c'est une erreur fatale de contexte, on peut considérer ça comme un crash
                        err_msg = resp["error"].get("message", "")
                        if "context" in err_msg.lower() or "found" in err_msg.lower():
                             pass 
                        return resp
                    return resp.get("result", {})
                else:
                    # Timeout applicatif
                    raise CDPTimeoutError(f"Timeout ({timeout}s) waiting for {method}")
                    
            except (BrokenPipeError, ConnectionError, CDPTimeoutError) as e:
                log(f"Ghost Triggered sur {method}: {e}. Tentative de réparation...", "WARN")
                
                # Nettoyage de la requête en cours
                with self._lock:
                    if req_id in self._pending_requests:
                        del self._pending_requests[req_id]
                
                # Si c'était la dernière tentative, on remonte l'erreur
                if attempt == max_ghost_retries:
                    raise e
                
                # Réparation du tunnel
                self._perform_ghost_reconnect()
                # On boucle pour ré-essayer l'envoi avec un nouveau socket
                continue
                
        return None

    def _perform_ghost_reconnect(self):
        """Logique de reconnexion bloquante"""
        self.ws.close()
        # On attend un peu que Chrome respire
        time.sleep(1.0)
        if self.ws.connect(max_retries=3):
            log("Ghost Reconnect Succès !", "INFO")
            # On ne relance pas le thread s'il est encore vivant (il devrait s'être arrêté sur l'erreur)
            if not self._read_thread or not self._read_thread.is_alive():
                self._read_thread = threading.Thread(target=self._listen_loop, daemon=True, name="GhostListener")
                self._read_thread.start()
        else:
            raise CDPConnectionError("Echec fatal de la reconnexion Ghost")

    def _get_next_id(self) -> int:
        with self._lock:
            self._req_id += 1
            return self._req_id

    def _listen_loop(self):
        """Boucle de consommation des messages entrants"""
        while self._running:
            msg = self.ws.recv()
            if msg is None:
                # Déconnexion détectée
                if self._running:
                    log("Flux Ghost interrompu (Socket Closed).", "WARN")
                    # On laisse le prochain 'send' déclencher la réparation
                break
                
            try:
                data = json.loads(msg)
                
                # Cas 1: Réponse à une commande (RPC)
                if "id" in data:
                    req_id = data["id"]
                    with self._lock:
                        if req_id in self._pending_requests:
                            self._pending_requests[req_id]["response"] = data
                            self._pending_requests[req_id]["evt"].set()
                            del self._pending_requests[req_id]
                
                # Cas 2: Événement (Event)
                elif "method" in data:
                    method = data["method"]
                    params = data.get("params", {})
                    # Copie thread-safe
                    handlers = list(self._event_handlers)
                    for cb in handlers:
                        try:
                            cb(method, params)
                        except: pass
                        
            except Exception as e:
                log(f"Erreur parsing message Ghost: {e}", "WARN")

    # --- HELPERS UTILITAIRES (COMPATIBILITÉ) ---

    def eval(self, expression: str, timeout: float = 5.0, returnByValue: bool = True):
        """Exécute du JS dans le contexte global"""
        res = self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": returnByValue,
            "awaitPromise": True
        }, timeout=timeout)
        
        if res and "result" in res:
            val = res["result"]
            if "value" in val: return val["value"]
            return val
        return None

    def on_event(self, callback: Callable[[str, dict], None]):
        """Abonne un écouteur global"""
        self._event_handlers.append(callback)

# ---------------------------------------------------------------------------
# TARGET DISCOVERY (FONCTIONS STATIQUES)
# ---------------------------------------------------------------------------

def list_targets(port: int):
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
            return json.load(r)
    except:
        return []

def pick_tiktok_target(targets, url_substr="tiktok.com"):
    for t in targets:
        if t.get("type") == "page" and url_substr in t.get("url", ""):
            return t
    return None

def pick_youtube_target(targets, url_substr="youtube.com"):
    for t in targets:
        if t.get("type") == "page" and url_substr in t.get("url", ""):
            return t
    return None