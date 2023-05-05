
import yarl

from typing import List, Optional, Set, Dict, Any, Generator

import time
import logging

from galaxy.api.errors import BackendNotAvailable, BackendTimeout, BackendError, UnknownBackendResponse

import urllib
import json

from socket import timeout

Timeout = float
HostName = str

DEFAULT_TIMEOUT = 60

logger = logging.getLogger(__name__)

def current_time() -> float:
    """Alias to get the current time. 
    apparently time.time is confusing.
    
    :return: the current time as a float
    :rtype :class:`float`
    """
    return time.time()

class SocketHttpHelper():
    """ Helper class designed to handle getting the servers available that we can connect to via the websocket. 

    This abstracts away the http request we make to get all available servers and any related calls. The network_websocket only needs to call this to get a server. 
    """

    def __init__(self):
        self._servers_blacklist: Dict[HostName, Timeout] = {}

    @staticmethod 
    def __host_name(url: str) -> HostName:
        return yarl.URL(url).host
    
    def _get_server_names(self, cell_id:int) -> List[str]:
        """ Synchronous call to get a list of severs we can connect to.  
        
        since this is a simple request and response pair, we do not need async calls for it. Keep it simple.

        Throws backend related errors when something unexpected occurs. 

        :param cell_id: cell id to use in the url.
        :type cell_id: :class:`int`
        :return: list of server addressed to connect on
        :rtype: :class:`List[:class:`str`]`
        """
        url = f"http://api.steampowered.com/ISteamDirectory/GetCMList/v1/?cellid={cell_id}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                #data = json.loads(response.read().decode("utf-8"))
                data = json.load(response)
                logger.info("Received servers. JSON data: " + vars(data))
            return data['response']['serverlist_websockets']
        except timeout:
            raise BackendTimeout()
        except urllib.HTTPError:
            raise BackendNotAvailable();
        except urllib.URLError as error:
            if isinstance(error.reason, timeout):
                raise BackendTimeout();
            else:
                raise BackendNotAvailable();
        except json.JSONDecodeError as e:
            logging.error('Error decoding the json', exc_info=e)
            raise BackendNotAvailable(); #not really the right error because it means i screwed up but we'll go with it. 
        except (ValueError, KeyError) :
            logger.exception("Can not parse backend response")
            raise UnknownBackendResponse()
        except:
            raise BackendError()

    def get_next_available_server(self, cell_id: int) -> Generator[str, None, None]:
        """ Gets the list of available servers, and return the next available one. 

            This function returns an iterator instead of a list. In other words, it gets a list of data, but one returns one. the next time it is called, it returns the next entry, and so on.
            Technically yield returns a generator, a special type of iterator that can only be run once.
        """
        servers = self._get_server_names(cell_id)
        logger.debug("Got servers from backend: %s", str(servers))
        sockets = [f"wss://{server}/cmsocket/" for server in servers]
        for socket in sockets:
            #if the socket is not in the blacklist, or if it is, but the timeout period has elapsed, return it. 
            #if the socket is not in the blacklist, get will default to 0, which is less than the current time. Clever but confusing, hence this comment.
            if current_time() > self._servers_blacklist.get(self.__host_name(socket), 0):
                yield socket
            else:
                logger.info("Omitting blacklisted server %s", socket)

    def add_server_to_ignored(self, socket_addr: str, timeout_sec: int):
        """Adds the specified server at the given socket address to the blacklist, until timeout_sec seconds have elapsed

        """
        self._servers_blacklist[self.__host_name(socket_addr)] = current_time() + timeout_sec

