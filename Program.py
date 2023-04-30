import asyncio
import logging
import platform
import subprocess
import ssl
import sys
import webbrowser
import time
from functools import partial
from contextlib import suppress
from typing import List, Optional, NewType, Dict, AsyncGenerator, Any, Callable

import certifi

from backend_interface import BackendInterface
from backend_steam_network import SteamNetworkBackend

from http_client import HttpClient

logger = logging.getLogger(__name__)

class MinimalIntegration:
    def __init__(self):
        self._ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._ssl_context.load_verify_locations(certifi.where())
        self._http_client = HttpClient()
        self._user_profile_checker = UserProfileChecker(self._http_client)

        self._backend: BackendInterface = SteamNetworkBackend()

