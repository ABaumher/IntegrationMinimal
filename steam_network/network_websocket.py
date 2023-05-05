import logging

from typing import Dict, Any, Optional, List, Set, Generator, Type, Union, Iterable, AsyncIterable

from websockets.typing import Data

import asyncio
from asyncio.futures import Future

import websockets
from galaxy.api.errors import BackendNotAvailable, BackendTimeout, BackendError, InvalidCredentials, NetworkError, AccessDenied

import time
import logging

from .socket_http_helper import SocketHttpHelper

Timeout = float
HostName = str

MessageFormat = Union[Data, Iterable[Data], AsyncIterable[Data]]

RECONNECT_INTERVAL_SECONDS = 20
MAX_INCOMING_MESSAGE_SIZE = 2**24
BLACKLISTED_CM_EXPIRATION_SEC = 300

logger = logging.getLogger(__name__)

async def sleep(seconds: int):
    await asyncio.sleep(seconds)

class NetworkWebsocket:
    """ Handles sending and receiving messages with the steam network. 

    This includes connecting to the steam network, and determining which severs (if any) we should not use (aka a blacklist)

    This does not explicitely define the messages being sent or parse what is received; that is the job of whatever using the websocket. 
    """
    def __init__(self) -> None:
        self._socket_helper = SocketHttpHelper()
        self._websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._future_lookup_by_job : Dict[int, Future] = {}
    
    async def acquire_connection(self) -> websockets.WebSocketClientProtocol:
        """ Acquire a websocket client protocol connection. It is assumed if you are calling this, the connection has yet to be acquired or was lost.
        """
        while True:
            for ws_address in self._websocket_list.get(self.used_server_cell_id):
                self._current_ws_address = ws_address
                try:
                    self._websocket = await asyncio.wait_for(websockets.connect(ws_address, ssl=self._ssl_context, max_size=MAX_INCOMING_MESSAGE_SIZE), 5)
                    logger.info(f'Connected to Steam on CM {ws_address} on cell_id {self.used_server_cell_id}')
                    return self._websocket
                except (asyncio.TimeoutError, OSError, websockets.InvalidURI, websockets.InvalidHandshake):
                    self._websocket_list.add_server_to_ignored(self._current_ws_address, timeout_sec=BLACKLISTED_CM_EXPIRATION_SEC)
                    continue

            logger.exception(
                "Failed to connect to any server, reconnecting in %d seconds...",
                RECONNECT_INTERVAL_SECONDS
            )
            await sleep(RECONNECT_INTERVAL_SECONDS)

    
    async def handle_receive_messages(self):
        pass
    
    async def _send_msg_with_id(self, message: MessageFormat, job_id: int) -> Future:
        """ Send a message, and return a Future object that contains the response. This removes the need for top-level callbacks and such, which are ugly and hard to work with.
            
        Unfortunately, as a coroutine, you need to await to get the result, then await again on the result. This is ugly, so 
        """

        pass

    async def send_message_wait_for_response_async(self, message: MessageFormat, job_id: int) -> MessageFormat:
        """Send a message, and yield execution until a response is received. Then return that response to the caller for processing.

        """
        the_future = await self._send_msg_with_id(message, job_id)
        return await the_future

    async def send_message_async(self, message: MessageFormat):
        """ Send a message, but do not worry about handling a response. This method assumes you will be doing that manually. 

        This is particularly useful for a response that sends multiple messages, where you will need to wait for either multiple futures or multiple callbacks. 

        """
        pass
    



