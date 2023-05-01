import abc
from typing import Callable, Set, Union, Optional
from functools import partial


class BackendInterface(abc.ABC):
    @abc.abstractmethod
    async def authenticate(self, stored_credentials=None):
        pass

    @abc.abstractmethod
    async def pass_login_credentials(self, deprecated:str, credentials, cookies):
        pass

    @abc.abstractmethod
    def register_auth_lost_callback(self, callback: Callable):
        pass

    @abc.abstractmethod
    def tick(self):
        pass