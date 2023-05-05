import ssl
from typing import Callable, List, Any, Dict, Union, Optional

from galaxy.api.errors import (
    AuthenticationRequired,
    UnknownBackendResponse,
    UnknownError,
    BackendTimeout,
)
from galaxy.api.types import (
    Game,
    LicenseInfo,
    LicenseType,
    UserInfo,
    UserPresence,
    Subscription,
    SubscriptionDiscovery,
    SubscriptionGame,
    Achievement,
    GameLibrarySettings,
    GameTime,
    Authentication, NextStep,
)

from backend_interface import BackendInterface

class SteamNetworkBackend(BackendInterface):
    """
    A backend that gets user data via the network, using a websocket.
    
    If we think of the communication between gog and the plugin as peer to peer, this is the code that actually implements the requests gog is sending us, and returns any data. 
    it will also send data to the various caches gog uses as it goes. To do this, it must communicate with Steam and, when authenticating, communicate with the user. 



    .. note:: 
        This class is separated from the main plugin file for legacy reasons. In the case we need to reintroduce the public profile fallback, we can. 
    """
    def __init__(
        self,
    ) -> None:
        pass

    # authentication
    async def authenticate(self, stored_credentials: Optional[Dict[str, Any]]=None) -> Union[Authentication, NextStep]:
        pass

    async def pass_login_credentials(self, deprecated:str, credentials: Dict[str, str], cookies: List[Dict[str, str]]) -> Union[NextStep, Authentication]:
        pass

    def register_auth_lost_callback(self, callback: Callable):
        pass

    # periodic tasks
    def tick(self):
        pass